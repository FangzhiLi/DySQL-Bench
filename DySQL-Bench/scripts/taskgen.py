#!/usr/bin/env python3
"""Task-generation pipeline, one sub-command per step; every step resumes by record id.
Usage (from DySQL-Bench/), pilot on beer_factory:
  P=~/miniconda3/envs/dysql/bin/python; DB=bird:beer_factory
  $P scripts/taskgen.py trees    --db $DB --n 50 --seed 0
  $P scripts/taskgen.py describe --db $DB
  $P scripts/taskgen.py generate --db $DB --workers 5
  $P scripts/taskgen.py check    --db $DB
  $P scripts/taskgen.py verify   --db $DB --votes 5 --workers 4
  $P scripts/taskgen.py dedup    --db $DB
  $P scripts/taskgen.py convert  --db $DB
  $P scripts/taskgen.py stats    --db $DB
Files: results/taskgen/<db>/{trees,candidates,check,verify,selected}.jsonl, others.json; data/taskgen/<db>/tasks.jsonl."""
import argparse, glob, json, os, random, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dysql_bench.taskgen import io, trees, schema, llm, prompt, generate, check, verify, dedup, convert, stats

DESC_PATH = os.path.join(io.REPO, "docs", "data_gen", "db_descriptions.json")


def rec_and_dir(a):
    rec = io.load_db_recs(a.anchors)[a.db]
    out = a.out_dir or os.path.join(io.ROOT, "results", "taskgen", rec["db"])
    os.makedirs(out, exist_ok=True)
    return rec, out


def cmd_trees(a):
    rec, out = rec_and_dir(a)
    c = trees.open_ro(io.resolve_db_path(rec["path"]))
    done = {(t["anchor_table"], str(t["key_value"])) for t in io.read_jsonl(f"{out}/trees.jsonl")}
    others = json.load(open(f"{out}/others.json")) if os.path.exists(f"{out}/others.json") else {}
    for anchor in io.person_anchors(rec):
        if a.anchor and anchor["table"] != a.anchor:
            continue
        trees.check_scope(anchor, rec["fks"], rec.get("fks_composite", ()))
        rng = random.Random(f"{a.seed}:{anchor['table']}")   # per anchor, so a rerun reproduces the same sample
        kvs = trees.anchor_key_values(c, anchor, rec["fks"], rng, a.n + 20)
        built = [t for kv in kvs[:a.n] if (anchor["table"], str(kv)) not in done
                 and (t := trees.build_tree(c, anchor, rec["fks"], kv, rng))]
        io.append_jsonl(f"{out}/trees.jsonl", built)
        # candidate 'other people' for type 4: the 20 rows after the sampled ones, names only
        extra = [trees.build_tree(c, anchor, rec["fks"], kv, rng, max_down=0, max_up=0) for kv in kvs[a.n:]]
        others[anchor["table"]] = [{"key_value": t["key_value"], "name": t["anchor_name"]} for t in built + extra if t][:20]
        print(f"{anchor['table']}: {len(built)} trees written")
    json.dump(others, open(f"{out}/others.json", "w"), ensure_ascii=False, default=str)


def cmd_describe(a):
    rec, _ = rec_and_dir(a)
    print(schema.describe_db(a.db, io.resolve_db_path(rec["path"]), llm.client_from_env("GEN"), DESC_PATH))


def cmd_generate(a):
    rec, out = rec_and_dir(a)
    path = io.resolve_db_path(rec["path"])
    desc = json.load(open(DESC_PATH)).get(a.db, "") if os.path.exists(DESC_PATH) else ""
    if not desc:
        sys.exit("run `describe` first")
    client = llm.client_from_env("GEN")
    all_trees = io.read_jsonl(f"{out}/trees.jsonl")
    others = json.load(open(f"{out}/others.json"))
    if a.retry_errors:   # their check results are stale once the candidates are regenerated
        failed = {c["id"] for c in io.read_jsonl(f"{out}/candidates.jsonl")
                  if c.get("instruction") is None and (c.get("error") or "").startswith(("LLMError", "RuntimeError", "ConnectionError"))}
        chk = [r for r in io.read_jsonl(f"{out}/check.jsonl") if r["id"] not in failed]
        if os.path.exists(f"{out}/check.jsonl"):
            os.remove(f"{out}/check.jsonl")
        io.append_jsonl(f"{out}/check.jsonl", chk)
    t0, total = time.time(), {"written": 0, "errors": 0, "skipped": 0}
    for anchor in io.person_anchors(rec):
        ts = [t for t in all_trees if t["anchor_table"] == anchor["table"]]
        s = generate.run(rec, anchor, ts, others.get(anchor["table"], []), client, f"{out}/candidates.jsonl",
                         random.Random(a.seed), workers=a.workers, per_tree=a.per_tree,
                         db_description=desc, schema_text=schema.schema_block(path), retry_errors=a.retry_errors)
        total = {k: total[k] + s[k] for k in total}
    usage = sum((c.get("usage") or {}).get("total_tokens", 0) for c in io.read_jsonl(f"{out}/candidates.jsonl"))
    print(f"{total} in {time.time() - t0:.0f}s; total tokens so far {usage}")


def cmd_check(a):
    rec, out = rec_and_dir(a)
    done = io.done_ids(f"{out}/check.jsonl")
    todo = [c for c in io.read_jsonl(f"{out}/candidates.jsonl") if c["id"] not in done]
    n = ok = 0
    for c in todo:   # one line per candidate: a crash or a kill keeps everything checked so far
        r = check.run_check_safe(rec, c)
        io.append_jsonl(f"{out}/check.jsonl", [r])
        n += 1; ok += r["ok"]
    print(f"checked {n}, passed {ok}")


def cmd_verify(a):
    dbs = [a.db] if not a.all_dbs else [k for k in io.load_db_recs(a.anchors) if os.path.exists(
        os.path.join(io.ROOT, "results", "taskgen", k.split(":", 1)[1], "check.jsonl"))]
    client = llm.client_from_env("VERIFY")
    for db in dbs:
        a.db = db
        rec, out = rec_and_dir(a)
        ok = {r["id"] for r in io.read_jsonl(f"{out}/check.jsonl") if r["ok"]}
        cands = [c for c in io.read_jsonl(f"{out}/candidates.jsonl") if c["id"] in ok]
        t0 = time.time()
        s = verify.run(cands, client, f"{out}/verify.jsonl", votes=a.votes, workers=a.workers,
                       ddl_text=schema.ddl(io.resolve_db_path(rec["path"])))
        print(f"{db}: {s} in {time.time() - t0:.0f}s")


def merged(out):
    chk = {r["id"]: r for r in io.read_jsonl(f"{out}/check.jsonl")}
    ver = {r["id"]: r for r in io.read_jsonl(f"{out}/verify.jsonl")}
    rows = []
    for c in io.read_jsonl(f"{out}/candidates.jsonl"):
        k, v = chk.get(c["id"]), ver.get(c["id"])
        if k and k["ok"] and v and v["pass"]:
            rows.append({**c, "task_type": k["task_type"], "template": k["template"], "difficulty": k["difficulty"],
                         "writes": k["writes"], "votes": v["votes"], "verify_model": v.get("verify_model")})
    return rows


def cmd_dedup(a):
    rec, out = rec_and_dir(a)
    sel = dedup.select(merged(out), random.Random(a.seed), a.per_person, a.per_template, a.per_db)
    if os.path.exists(f"{out}/selected.jsonl"):
        os.remove(f"{out}/selected.jsonl")
    io.append_jsonl(f"{out}/selected.jsonl", sel)
    print(f"selected {len(sel)}")


def cmd_convert(a):
    rec, out = rec_and_dir(a)
    tasks = a.tasks or os.path.join(io.ROOT, "data", "taskgen", rec["db"], "tasks.jsonl")
    manifest = a.manifest or os.path.join(io.ROOT, "data", "taskgen", "manifest.json")
    n = convert.write_tasks(rec, io.read_jsonl(f"{out}/selected.jsonl"), tasks)
    convert.update_manifest(manifest, rec["db"], io.resolve_db_path(rec["path"]),
                            tasks if a.tasks else os.path.relpath(tasks, io.ROOT), a.db)
    print(f"wrote {n} tasks to {tasks}")


def cmd_stats(a):
    rec, out = rec_and_dir(a)
    d = stats.summarize(io.read_jsonl(f"{out}/candidates.jsonl"), io.read_jsonl(f"{out}/check.jsonl"),
                        io.read_jsonl(f"{out}/verify.jsonl"), io.read_jsonl(f"{out}/selected.jsonl"))
    print(stats.render(d))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    def common(p):
        p.add_argument("--db", required=True); p.add_argument("--anchors", default=os.path.join(io.REPO, "docs", "data_gen", "candidate_anchors.json"))
        p.add_argument("--out-dir"); p.add_argument("--seed", type=int, default=0)
    p = sub.add_parser("trees"); common(p); p.add_argument("--n", type=int, default=50); p.add_argument("--anchor"); p.set_defaults(f=cmd_trees)
    p = sub.add_parser("describe"); common(p); p.set_defaults(f=cmd_describe)
    p = sub.add_parser("generate"); common(p); p.add_argument("--workers", type=int, default=5, help="GLM plan limit: 5 concurrent requests"); p.add_argument("--per-tree", type=int, default=1); p.add_argument("--retry-errors", action="store_true", help="regenerate candidates whose API call failed (e.g. 429)"); p.set_defaults(f=cmd_generate)
    p = sub.add_parser("check"); common(p); p.set_defaults(f=cmd_check)
    p = sub.add_parser("verify"); common(p); p.add_argument("--votes", type=int, default=3); p.add_argument("--workers", type=int, default=4); p.add_argument("--all-dbs", action="store_true"); p.set_defaults(f=cmd_verify)
    p = sub.add_parser("dedup"); common(p); p.add_argument("--per-person", type=int, default=2); p.add_argument("--per-template", type=int, default=15); p.add_argument("--per-db", type=int, default=600); p.set_defaults(f=cmd_dedup)
    p = sub.add_parser("convert"); common(p); p.add_argument("--tasks"); p.add_argument("--manifest"); p.set_defaults(f=cmd_convert)
    p = sub.add_parser("stats"); common(p); p.set_defaults(f=cmd_stats)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
