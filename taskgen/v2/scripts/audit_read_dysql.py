#!/usr/bin/env python3
"""Reading a sample of DySQL-Bench's own gold with the v2 rubric (2026-10-07), to compare the A/B rates.
  sample [--n 120]            sample.jsonl + batches.json (stratified by env, write tasks only)
  show --batch B              each task: env schema (first time), instruction, gold SQL, rows it changes
  query --env ENV "SELECT"    read-only, 30 rows
  verdict --batch B --file F  [{"id","verdict","tags","note"}]
  status"""
import argparse, json, os, random, re, sqlite3, sys
V2 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [V2, os.path.join(V2, "..", "common")]
from taskgen_v2 import audit, check, dysql
from taskgen_common.db_select import _q
READ = os.path.join(V2, "results", "audit", "read_dysql")

def stmts(c): return [s for x in c["actions"] for s in check.split_statements(x["sql"])]
def all_tasks():
    return {c["id"]: c for env in dysql.ENVS for c in dysql.candidates(env)}
def short(v, n=60):
    s = str(v); return s if len(s) <= n else s[:n] + "..."

def cmd_sample(a):
    os.makedirs(READ, exist_ok=True); rng = random.Random(7)
    ts = all_tasks(); by = {}
    for i, c in ts.items():
        if any(check.write_target(s) for s in stmts(c)):
            by.setdefault(i.split(":")[1], []).append(i)
    tot = sum(len(v) for v in by.values())
    ids = []
    for env, v in sorted(by.items()):
        ids += rng.sample(sorted(v), max(1, round(a.n * len(v) / tot)))
    ids.sort(key=lambda i: (i.split(":")[1], int(i.split(":")[2])))
    with open(os.path.join(READ, "sample.jsonl"), "w") as f:
        for i in ids: f.write(json.dumps({"id": i}) + "\n")
    json.dump({str(n): ids[s:s + 30] for n, s in enumerate(range(0, len(ids), 30))}, open(os.path.join(READ, "batches.json"), "w"), indent=1)
    print(len(ids), "tasks of", tot, "write tasks")

def batch(b): return json.load(open(os.path.join(READ, "batches.json")))[str(b)]

def cmd_show(a):
    ts = all_tasks(); shown = set(); auds = {}
    for i in batch(a.batch):
        c = ts[i]; env = i.split(":")[1]
        rec = dysql.db_rec(env)
        if env not in auds:
            auds[env] = audit.DbAudit(rec["path"], [(f["table"], (f["col"],), f["ref_table"], (f["ref_col"],)) for f in rec["fks"]])
        aud = auds[env]
        if env not in shown:
            shown.add(env); print(f"=== database {env} ===")
            for t in sorted(aud.names.values()):
                print(f"  {t}({', '.join(aud.columns(t)[:30])})")
            print()
        st = stmts(c); aud.run(c["instruction"], st, set())
        print(f"### {i}  (group {c['group']})\nInstruction: {c['instruction']}\nGold SQL:")
        for n, s in enumerate(st): print(f"  [{n}] {s}")
        print("Effect:")
        for n, op, tb, old, new in aud.last:
            print(f"  [{n}] {op} {tb}: {len(old) if op != 'INSERT' else len(new)} row(s)")
            if op == "UPDATE":
                for o, r in list(zip(old, new))[:6]:
                    print("      " + "; ".join(f"{k}: {short(o.get(k))} -> {short(v)}" for k, v in r.items() if k != "__rowid__" and o.get(k) != v))
            else:
                for r in (new if op == "INSERT" else old)[:6]:
                    print("      {" + ", ".join(f"{k}: {short(v)}" for k, v in r.items() if k != "__rowid__" and v not in (None, "")) + "}")
        print()

def cmd_query(a):
    if not re.match(r"(?is)^\s*(select|with|pragma)\b", a.sql): sys.exit("read-only")
    path = dysql.db_rec(a.env)["path"]
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True); cur = conn.execute(a.sql)
    print(" | ".join(d[0] for d in cur.description or []))
    for r in cur.fetchmany(30): print(" | ".join(short(v, 80) for v in r))

def cmd_verdict(a):
    recs = json.load(open(a.file)); ids = set(batch(a.batch))
    bad = [r.get("id") for r in recs if r.get("id") not in ids or r.get("verdict") not in ("good", "bad", "unsure")]
    if bad: sys.exit(f"bad records: {bad}")
    with open(os.path.join(READ, f"verdict_{a.batch}.jsonl"), "a") as f:
        for r in recs: f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("stored", len(recs))

def cmd_status(a):
    for k, ids in json.load(open(os.path.join(READ, "batches.json"))).items():
        p = os.path.join(READ, f"verdict_{k}.jsonl")
        n = len({json.loads(l)["id"] for l in open(p)}) if os.path.exists(p) else 0
        print(f"batch {k}: {len(ids)} tasks, judged {n}")

ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
sub.add_parser("sample").add_argument("--n", type=int, default=120)
sub.add_parser("show").add_argument("--batch", required=True)
q = sub.add_parser("query"); q.add_argument("--env", required=True); q.add_argument("sql")
v = sub.add_parser("verdict"); v.add_argument("--batch", required=True); v.add_argument("--file", required=True)
sub.add_parser("status")
a = ap.parse_args()
{"sample": cmd_sample, "show": cmd_show, "query": cmd_query, "verdict": cmd_verdict, "status": cmd_status}[a.cmd](a)
