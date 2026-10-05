#!/usr/bin/env python3
"""Task-generation pipeline, one sub-command per step; every step resumes by record id.
Usage (from taskgen/v2/), pilot on beer_factory (its profile in data/db_profiles.json must be confirmed):
  P=~/miniconda3/envs/dysql/bin/python; DB=bird:beer_factory
  $P scripts/taskgen.py profile  check --db $DB
  $P scripts/taskgen.py trees    --db $DB --n 50 --seed 0
  $P scripts/taskgen.py generate --db $DB --workers 5
  $P scripts/taskgen.py check    --db $DB
  $P scripts/taskgen.py verify   --db $DB --workers 3
  $P scripts/taskgen.py dedup    --db $DB
  $P scripts/taskgen.py convert  --db $DB
  $P scripts/taskgen.py stats    --db $DB
Files: data/db_profiles.json; results/<db>/{trees,candidates,check,verify,selected}.jsonl; output/<db>/tasks.jsonl,
output/manifest.json."""
import argparse, glob, json, os, random, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
V2 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [V2, os.path.join(os.path.dirname(V2), "common")]   # taskgen_v2, taskgen_common
from taskgen_v2 import io, trees, schema, llm, prompt, generate, check, verify, dedup, convert, stats, db_profile, owners, profile_draft


def rec_and_dir(a):
    rec = io.load_db_recs(a.anchors)[a.db]
    out = a.out_dir or os.path.join(io.RESULTS, rec["db"])
    os.makedirs(out, exist_ok=True)
    return rec, out


def profile_of(a):
    try:
        return db_profile.get(a.db, a.profiles)
    except ValueError as e:
        sys.exit(str(e))


def same_profile(path, ver, what):
    """Refuse records made from another version of the profile: a prompt built from the old labels must not meet a
    check that reads the new ones."""
    old = sorted({str(r.get("profile_version")) for r in io.read_jsonl(path)} - {ver})
    if old:
        sys.exit(f"{path} holds {what} from profile version {', '.join(old)}, but the profile is now {ver}: "
                 "use a new --out-dir, or delete the file to build it again")


def cmd_trees(a):
    rec, out = rec_and_dir(a)
    prof = profile_of(a)
    same_profile(f"{out}/trees.jsonl", db_profile.version(prof), "trees")
    c = trees.open_ro(io.resolve_db_path(rec["path"]))
    tracer = owners.Tracer.from_profile(prof, rec, c)
    done = {(t["anchor_table"], str(t["key_value"])) for t in io.read_jsonl(f"{out}/trees.jsonl")}
    roots = [r for r in prof["roots"] if not a.anchor or r["table"] == a.anchor]
    rngs = {r["table"]: random.Random(f"{a.seed}:{r['table']}") for r in roots}   # per root: a rerun draws the same sample
    keys = {r["table"]: trees.root_key_values(c, prof, r, rngs[r["table"]]) for r in roots}
    for r, n in zip(roots, trees.allocate(a.n, [len(keys[r["table"]]) for r in roots])):
        t, rng = r["table"], rngs[r["table"]]
        built = [tr for kv in keys[t][:n] if (t, str(kv)) not in done
                 and (tr := trees.build_tree(c, prof, r, kv, rng, tracer))]
        io.append_jsonl(f"{out}/trees.jsonl", built)
        print(f"{t}: {len(built)} trees written")


def cmd_generate(a):
    rec, out = rec_and_dir(a)
    prof = profile_of(a)
    same_profile(f"{out}/trees.jsonl", db_profile.version(prof), "trees")
    same_profile(f"{out}/candidates.jsonl", db_profile.version(prof), "candidates")
    materials = generate.context(rec, prof)
    client = llm.client_from_env("GEN")
    all_trees = io.read_jsonl(f"{out}/trees.jsonl")
    if a.retry_errors:   # their check results are stale once the candidates are regenerated
        failed = {c["id"] for c in io.read_jsonl(f"{out}/candidates.jsonl")
                  if c.get("instruction") is None and (c.get("error") or "").startswith(generate.RETRYABLE)}
        chk = [r for r in io.read_jsonl(f"{out}/check.jsonl") if r["id"] not in failed]
        if os.path.exists(f"{out}/check.jsonl"):
            os.remove(f"{out}/check.jsonl")
        io.append_jsonl(f"{out}/check.jsonl", chk)
    t0, total = time.time(), {"written": 0, "errors": 0, "skipped": 0}
    for r in prof["roots"]:
        anchor = db_profile.root_anchor(prof, r["table"])
        ts = [t for t in all_trees if t["anchor_table"] == anchor["table"]]
        s = generate.run(rec, anchor, ts, client, f"{out}/candidates.jsonl",
                         random.Random(f"{a.seed}:{anchor['table']}"),   # per root: two roots must not draw the same plans
                         workers=a.workers, per_tree=a.per_tree, materials=materials, retry_errors=a.retry_errors)
        total = {k: total[k] + s[k] for k in total}
    usage = sum((c.get("usage") or {}).get("total_tokens", 0) for c in io.read_jsonl(f"{out}/candidates.jsonl"))
    print(f"{total} in {time.time() - t0:.0f}s; total tokens so far {usage}")


def cmd_check(a):
    rec, out = rec_and_dir(a)
    prof = profile_of(a)
    same_profile(f"{out}/candidates.jsonl", db_profile.version(prof), "candidates")
    done = io.done_ids(f"{out}/check.jsonl")
    todo = [c for c in io.read_jsonl(f"{out}/candidates.jsonl") if c["id"] not in done]
    n = ok = 0
    for c in todo:   # one line per candidate: a crash or a kill keeps everything checked so far
        r = check.run_check_safe(rec, c, profile=prof)
        io.append_jsonl(f"{out}/check.jsonl", [r])
        n += 1; ok += r["ok"]
    print(f"checked {n}, passed {ok}")


def cmd_verify(a):
    """check -> pre-cap -> verify (design §4.6): the candidates that passed the check, capped per template and per
    database, each judged with the database's DDL and the profile's data quirks."""
    dbs = [a.db] if not a.all_dbs else [k for k in io.load_db_recs(a.anchors) if os.path.exists(
        os.path.join(io.RESULTS, k.split(":", 1)[1], "check.jsonl"))]
    models = verify.models_from_env(a.models)
    for db in dbs:
        a.db = db
        rec, out = rec_and_dir(a)
        prof = profile_of(a)
        same_profile(f"{out}/candidates.jsonl", db_profile.version(prof), "candidates")
        cands = dedup.precap(io.read_jsonl(f"{out}/candidates.jsonl"), io.read_jsonl(f"{out}/check.jsonl"),
                             random.Random(a.seed), a.precap_template, a.precap_db)
        ddl, quirks = schema.ddl(io.resolve_db_path(rec["path"])), verify.notes_for(prof)
        t0 = time.time()
        s = verify.run(cands, models, f"{out}/verify.jsonl", workers=a.workers, context=lambda c: (ddl, quirks),
                       max_failures=a.max_failures)
        print(f"{db}: {s} in {time.time() - t0:.0f}s")
        if s["paused"]:   # the quota is gone (or the endpoint is down): stop here, the same command resumes
            print(f"paused after {a.max_failures} failed calls in a row; run verify again later", file=sys.stderr)
            sys.exit(3)


def merged(out):
    """Candidates that passed the check and the verifier, minus those a spot check excluded (excluded.jsonl:
    {"id", "reason", "by"} per line)."""
    chk = {r["id"]: r for r in io.read_jsonl(f"{out}/check.jsonl")}
    ver = {r["id"]: r for r in io.read_jsonl(f"{out}/verify.jsonl")}
    excluded = {r["id"] for r in io.read_jsonl(f"{out}/excluded.jsonl")}
    rows = []
    for c in io.read_jsonl(f"{out}/candidates.jsonl"):
        k, v = chk.get(c["id"]), ver.get(c["id"])
        if k and k["ok"] and v and v["pass"] and c["id"] not in excluded:
            rows.append({**c, "task_type": k["task_type"], "template": k["template"], "difficulty": k["difficulty"],
                         "writes": k["writes"], "votes": v["votes"], "verify_model": v.get("verify_model")})
    return rows


def cmd_dedup(a):
    rec, out = rec_and_dir(a)
    sel = dedup.select(dedup.near_duplicates(merged(out)), random.Random(a.seed), a.per_person, a.per_template, a.per_db)
    if os.path.exists(f"{out}/selected.jsonl"):
        os.remove(f"{out}/selected.jsonl")
    io.append_jsonl(f"{out}/selected.jsonl", sel)
    print(f"selected {len(sel)}")


def cmd_convert(a):
    rec, out = rec_and_dir(a)
    tasks = a.tasks or os.path.join(io.OUTPUT, rec["db"], "tasks.jsonl")
    manifest = a.manifest or os.path.join(io.OUTPUT, "manifest.json")
    n = convert.write_tasks(rec, io.read_jsonl(f"{out}/selected.jsonl"), tasks)
    convert.update_manifest(manifest, rec["db"], io.resolve_db_path(rec["path"]), tasks, a.db)
    print(f"wrote {n} tasks to {tasks}")


def cmd_stats(a):
    rec, out = rec_and_dir(a)
    d = stats.summarize(io.read_jsonl(f"{out}/candidates.jsonl"), io.read_jsonl(f"{out}/check.jsonl"),
                        io.read_jsonl(f"{out}/verify.jsonl"), io.read_jsonl(f"{out}/selected.jsonl"))
    print(stats.render(d))


def draft_profiles(a):
    hints, recs = json.load(open(a.hints, encoding="utf-8")), io.load_db_recs(a.anchors)
    have = db_profile.load(a.profiles)
    todo = [k for k in ([a.db] if a.db else sorted(hints)) if a.redo or k not in have]
    client, examples = llm.client_from_env("GEN"), profile_draft.load_examples()

    def one(k):   # each thread opens its own connection
        rec = recs[k]
        path = io.resolve_db_path(rec["path"])
        try:
            return k, profile_draft.draft(client, k, trees.open_ro(path), rec, path, hints[k], examples), None
        except Exception as e:
            return k, None, f"{type(e).__name__}: {e}"
    with ThreadPoolExecutor(max_workers=max(1, a.workers)) as ex:
        for f in as_completed([ex.submit(one, k) for k in todo]):
            k, prof, err = f.result()
            if err:
                print(f"{k}: FAILED {err}")
                continue
            profiles = db_profile.load(a.profiles)   # saved after every database: an interrupted run keeps what it has
            profiles[k] = prof
            db_profile.save(profiles, a.profiles)
            print(f"{k}: {prof['draft']['rounds']} round(s), {len(prof['draft']['errors'])} problem(s) left")


def sample_trees(entries, recs, seed, n):
    """Prompt-style data blocks of n trees per root of every valid profile, for the reviewer (rows of the database,
    so the file stays out of git)."""
    parts = []
    for x in entries:
        if x["errors"]:
            continue
        rec, prof = recs[x["key"]], x["profile"]
        c = trees.open_ro(io.resolve_db_path(rec["path"]))
        tracer = owners.Tracer.from_profile(prof, rec, c)
        for r in prof["roots"]:
            rng = random.Random(f"{seed}:{r['table']}")
            for kv in trees.root_key_values(c, prof, r, rng, n):
                t = trees.build_tree(c, prof, r, kv, rng, tracer)
                refs = [[gi, j] for gi, g in enumerate(t["events"]) for j in range(len(g["rows"]))]
                parts.append(f"# {x['key']} · {r['table']} {kv}\n\n" + prompt.data_blocks(t, refs, "the record the request is about" if db_profile.kind(prof) == "entity" else "the speaker's own row"))
    return "\n\n".join(parts)


def cmd_profile(a):
    if a.action == "draft":
        return draft_profiles(a)
    profiles, recs = db_profile.load(a.profiles), io.load_db_recs(a.anchors)
    keys = [a.db] if a.db else sorted(k for k, p in profiles.items() if not a.kind or db_profile.kind(p) == a.kind)
    missing = [k for k in keys if k not in profiles]
    if missing:
        sys.exit(f"no profile for {', '.join(missing)} in {a.profiles}")
    entries = []
    for k in keys:
        rec = recs[k]
        c = trees.open_ro(io.resolve_db_path(rec["path"]))
        entries.append({"key": k, "profile": profiles[k], "pk": schema.pk_info(c),
                        "errors": db_profile.validate(profiles[k], c, rec["fks"], rec.get("fks_composite", ()))})
    bad = [x["key"] for x in entries if x["errors"]]
    if a.action == "check":
        for x in entries:
            print(f"{x['key']}: " + (f"{len(x['errors'])} problems" if x["errors"] else "ok")
                  + ", " + db_profile.status(x["profile"]))
            for e in x["errors"]:
                print(f"  - {e}")
        sys.exit(1 if bad else 0)
    if a.action == "render":
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(db_profile.render_md(entries) + "\n")
        print(f"wrote {a.out}: {len(entries)} profiles, {len(bad)} with problems")
        if a.trees_out:
            with open(a.trees_out, "w", encoding="utf-8") as f:
                f.write(sample_trees(entries, recs, a.seed, a.sample_trees) + "\n")
            print(f"wrote {a.trees_out}")
    if a.action == "confirm":
        if not a.db:
            sys.exit("confirm needs --db")
        if bad:
            sys.exit(f"{a.db} has problems; run `profile check --db {a.db}`")
        profiles[a.db] = db_profile.confirm(profiles[a.db])
        db_profile.save(profiles, a.profiles)
        print(f"{a.db}: confirmed")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    def common(p):
        p.add_argument("--db", required=True); p.add_argument("--anchors", default=io.ANCHORS_JSON)
        p.add_argument("--out-dir"); p.add_argument("--seed", type=int, default=0)
        p.add_argument("--profiles", default=db_profile.PROFILES_JSON)
    p = sub.add_parser("profile"); p.add_argument("action", choices=["draft", "check", "render", "confirm"])
    p.add_argument("--db", help="one database (default: all in the hints for draft, all in the profiles file otherwise)")
    p.add_argument("--anchors", default=io.ANCHORS_JSON); p.add_argument("--profiles", default=db_profile.PROFILES_JSON)
    p.add_argument("--hints", default=profile_draft.HINTS_JSON); p.add_argument("--redo", action="store_true", help="draft again even if a profile exists")
    p.add_argument("--workers", type=int, default=5, help="GLM plan limit: 5 concurrent requests")
    p.add_argument("--out", help="render: the review page to write"); p.add_argument("--trees-out", help="render: sample trees for the reviewer (results/, not git)")
    p.add_argument("--kind", choices=db_profile.KINDS, help="check/render: only profiles of this kind")
    p.add_argument("--sample-trees", type=int, default=1); p.add_argument("--seed", type=int, default=0); p.set_defaults(f=cmd_profile)
    p = sub.add_parser("trees"); common(p); p.add_argument("--n", type=int, default=50); p.add_argument("--anchor", help="one root table only"); p.set_defaults(f=cmd_trees)
    p = sub.add_parser("generate"); common(p); p.add_argument("--workers", type=int, default=5, help="GLM plan limit: 5 concurrent requests"); p.add_argument("--per-tree", type=int, default=1); p.add_argument("--retry-errors", action="store_true", help="regenerate candidates whose API call failed (e.g. 429)"); p.set_defaults(f=cmd_generate)
    p = sub.add_parser("check"); common(p); p.set_defaults(f=cmd_check)
    p = sub.add_parser("verify"); common(p); p.add_argument("--models", help="model:votes,... (default: TASKGEN_VERIFY_MODELS, else TASKGEN_VERIFY_MODEL with verify.DEFAULT_VOTES)")
    p.add_argument("--precap-template", type=int, default=25); p.add_argument("--precap-db", type=int, default=900)
    p.add_argument("--max-failures", type=int, default=20, help="failed calls in a row before the run pauses (quota gone)")
    p.add_argument("--workers", type=int, default=3, help="Ollama Pro plan limit: 3 concurrent requests"); p.add_argument("--all-dbs", action="store_true"); p.set_defaults(f=cmd_verify)
    p = sub.add_parser("dedup"); common(p); p.add_argument("--per-person", type=int, default=2); p.add_argument("--per-template", type=int, default=15); p.add_argument("--per-db", type=int, default=600); p.set_defaults(f=cmd_dedup)
    p = sub.add_parser("convert"); common(p); p.add_argument("--tasks"); p.add_argument("--manifest"); p.set_defaults(f=cmd_convert)
    p = sub.add_parser("stats"); common(p); p.set_defaults(f=cmd_stats)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
