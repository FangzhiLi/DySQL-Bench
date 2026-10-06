#!/usr/bin/env python3
"""Repair the candidates the check rejected only for orphans or net no-ops (2026-10-05, user's decision), one database
at a time; each repair is a new candidate <tree>:1 that goes through check and verify like any other.
- orphans: the gold gets a cascade (taskgen_v2.repair.cascade) and the generation model rewrites the instruction;
- net no-ops, and orphans whose cascade would change too many rows: the same tree is generated again.
Both carry "repair": {"from": <old id>, "kind": "cascade" | "regenerated"}; results/<db>/repairs.jsonl lists them.
Usage (from taskgen/v2/):
  P=~/miniconda3/envs/dysql/bin/python
  $P scripts/repair_tasks.py --db bird:student_loan --workers 5
  $P scripts/taskgen.py check --db bird:student_loan     # then verify, dedup, convert as usual"""
import argparse, os, random, sys
from concurrent.futures import ThreadPoolExecutor, as_completed
V2 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [V2, os.path.join(os.path.dirname(V2), "common")]   # taskgen_v2, taskgen_common
from taskgen_v2 import check, db_profile, generate, io, llm, owners, repair

KINDS = {"orphans", "net_noop"}


def targets(cands, checks, done):
    """Candidates rejected for orphans or net no-ops and nothing else, first generation only, not repaired yet:
    {id: "cascade" | "regenerate"}."""
    out = {}
    for r in checks:
        kinds = {x.split(":")[0] for x in r["reasons"]}
        if r["ok"] or not kinds or not kinds <= KINDS or not r["id"].endswith(":0") or r["id"] in done:
            continue
        if cands.get(r["id"], {}).get("instruction"):
            out[r["id"]] = "regenerate" if "net_noop" in kinds else "cascade"
    return out


def new_id(cid):
    return cid.rsplit(":", 1)[0] + ":1"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", required=True); ap.add_argument("--anchors", default=io.ANCHORS_JSON)
    ap.add_argument("--profiles", default=db_profile.PROFILES_JSON); ap.add_argument("--out-dir")
    ap.add_argument("--workers", type=int, default=5, help="GLM plan limit: 5 concurrent requests"); ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    rec = io.load_db_recs(a.anchors)[a.db]
    prof = db_profile.get(a.db, a.profiles)
    out = a.out_dir or os.path.join(io.RESULTS, rec["db"])
    path = io.resolve_db_path(rec["path"])
    cands = {c["id"]: c for c in io.read_jsonl(f"{out}/candidates.jsonl")}
    done = {r["from"] for r in io.read_jsonl(f"{out}/repairs.jsonl")}
    todo = targets(cands, io.read_jsonl(f"{out}/check.jsonl"), done)
    if any(new_id(k) in cands for k in todo):
        sys.exit("a repair id already exists in candidates.jsonl; look before running again")
    materials = generate.context(rec, prof)
    client = llm.client_from_env("GEN")

    jobs, regen = [], [k for k, v in todo.items() if v == "regenerate"]
    for cid in (k for k, v in todo.items() if v == "cascade"):
        c = cands[cid]
        conn = check._memory_copy(path)
        stmts = repair.cascade(conn, owners.Tracer.from_profile(prof, rec, conn), [s for x in c["actions"] for s in check.split_statements(x["sql"])])
        conn.close()
        (regen.append(cid) if stmts is None else jobs.append((cid, stmts)))

    def one(job):
        cid, stmts = job
        try:
            resp = client.chat(repair.rewrite_messages(cands[cid], stmts, materials), temperature=generate.GEN_TEMPERATURE,
                               max_tokens=generate.GEN_MAX_TOKENS, top_p=generate.GEN_TOP_P)
            return cid, stmts, resp, repair.parse_rewrite(resp.get("content")), None
        except Exception as e:
            return cid, stmts, None, None, f"{type(e).__name__}: {e}"

    fixed, logs = [], []
    with ThreadPoolExecutor(max_workers=max(1, a.workers)) as ex:
        for f in as_completed([ex.submit(one, j) for j in jobs]):
            cid, stmts, resp, ins, err = f.result()
            if err:   # the model gave no usable rewrite: generate the tree again instead
                print(f"{cid}: rewrite failed ({err[:120]}), regenerating"); regen.append(cid); continue
            fixed.append({**cands[cid], "id": new_id(cid), "instruction": ins, "actions": [{"sql": s} for s in stmts],
                          "repair": {"from": cid, "kind": "cascade"}, "gen_model": resp.get("model"), "usage": resp.get("usage"),
                          "raw": resp.get("content"), "error": None})
            logs.append({"id": new_id(cid), "from": cid, "kind": "cascade"})
    io.append_jsonl(f"{out}/candidates.jsonl", fixed)

    # the same trees once more: generate.run skips the :0 ids already in the scratch file and writes :1
    trees_by_key = {(t["anchor_table"], str(t["key_value"])): t for t in io.read_jsonl(f"{out}/trees.jsonl")}
    tmp = f"{out}/_regenerate.jsonl"
    if os.path.exists(tmp):
        os.remove(tmp)
    io.append_jsonl(tmp, [cands[k] for k in regen])
    for r in prof["roots"]:
        anchor = db_profile.root_anchor(prof, r["table"])
        ts = [trees_by_key[(cands[k]["anchor_table"], str(cands[k]["key_value"]))] for k in regen if cands[k]["anchor_table"] == r["table"]]
        if ts:
            generate.run(rec, anchor, ts, client, tmp, random.Random(f"{a.seed}:repair:{r['table']}"), workers=a.workers,
                         per_tree=2, materials=materials)
    again = []
    for c in io.read_jsonl(tmp):
        if c["id"].endswith(":1"):
            src = c["id"][:-1] + "0"
            again.append({**c, "repair": {"from": src, "kind": "regenerated"}})
            logs.append({"id": c["id"], "from": src, "kind": "regenerated"})
    io.append_jsonl(f"{out}/candidates.jsonl", again)
    os.remove(tmp)
    io.append_jsonl(f"{out}/repairs.jsonl", logs)
    print(f"{a.db}: {len(todo)} to repair; cascade {len(fixed)}, regenerated {len(again)}")


if __name__ == "__main__":
    main()
