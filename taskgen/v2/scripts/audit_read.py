#!/usr/bin/env python3
"""Blind reading of a sample of finished tasks (2026-10-06), after scripts/audit_tasks.py. A reader first sees only the
instruction, the speaker's record and the schema, writes down what the database should end up like, and only then
sees the gold SQL and the rows it changes. Files go to results/audit/read/.
Usage (from taskgen/v2/):
  P=~/miniconda3/envs/dysql/bin/python
  $P scripts/audit_read.py sample                       # sample.jsonl and batches.json
  $P scripts/audit_read.py blind   --batch 3            # tasks of batch 3 without a prediction yet
  $P scripts/audit_read.py predict --batch 3 --file p.json   # [{"id": ..., "pred": "..."}]
  $P scripts/audit_read.py reveal  --batch 3            # gold, its effect and the script flags, predicted tasks only
  $P scripts/audit_read.py verdict --batch 3 --file v.json   # [{"id", "verdict", "tags", "note"}]
  $P scripts/audit_read.py query   --db books "SELECT ..."   # read-only, 30 rows
  $P scripts/audit_read.py status
  $P scripts/audit_read.py --round risky risky          # 2026-10-07: the riskier subset, files in results/audit/read_risky/
  $P scripts/audit_read.py --round random2 random      # 2026-10-07: 300 random tasks no round has read yet
  (every other command takes --round the same way)"""
import argparse, json, math, os, random, re, sqlite3, sys
from collections import Counter, defaultdict
V2 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [V2, os.path.join(os.path.dirname(V2), "common")]
from taskgen_common.db_select import _q
from taskgen_v2 import audit, check, db_profile, io

READ = os.path.join(io.RESULTS, "audit", "read")
FLAGS = os.path.join(io.RESULTS, "audit", "flags.jsonl")
FLAG_CAP = 15       # flagged tasks read per flag kind
PERSON_SAMPLE = 260  # random person tasks read, spread over the databases by size (at least 4 each)
ENTITY_EACH = 2     # random entity tasks per entity database (each was spot-read 10 per database on 2026-10-05)
DOUBLE = 40         # random-sample tasks read a second time by another reader
BATCH = 32
RANDOM_N = 300      # second random round (2026-10-07), read by Opus
RANDOM_BATCHES = 10


def manifest():
    return json.load(open(os.path.join(V2, "output", "manifest.json")))


def tasks():
    out = {}
    for db, m in manifest().items():
        for t in io.read_jsonl(os.path.join(V2, "output", m["tasks"])):
            out[t["meta"]["id"]] = t
    return out


def weighted_sample(rng, items, k, weight):
    """k items without replacement, each drawn with chance proportional to weight (Efraimidis-Spirakis keys)."""
    keyed = sorted(items, key=lambda x: -rng.random() ** (1.0 / weight(x)))
    return keyed[:k]


def cmd_sample(a):
    os.makedirs(READ, exist_ok=True)
    rng = random.Random(0)
    ts = tasks()
    flags = {r["id"]: r for r in io.read_jsonl(FLAGS) if r["src"] == "v2"}
    why = defaultdict(list)
    for i, r in flags.items():
        if r["repair"]:
            why[i].append("repair:" + r["repair"])
    by_kind = defaultdict(list)
    for i, r in flags.items():
        for k in sorted({f["k"] for f in r["flags"]}):
            by_kind[k].append(i)
    for k, ids in sorted(by_kind.items()):
        for i in rng.sample(sorted(ids), min(FLAG_CAP, len(ids))):
            why[i].append("flag:" + k)

    def hard(i):
        m = ts[i]["meta"]
        sh = m["plan"]["shape"]
        return 2.0 if (sh.get("archive") or sh.get("ownership_subquery") or sh.get("batch") or m["task_type"] == "5_proxy") else 1.0
    rest = defaultdict(list)
    for i, t in ts.items():
        if i not in why:
            rest[t["meta"]["db"]].append(i)
    person = {d: ids for d, ids in rest.items() if ts[ids[0]]["meta"]["task_type"] != "6_entity"}
    total = sum(len(v) for v in person.values())
    random_ids = []
    for d, ids in sorted(rest.items()):
        k = ENTITY_EACH if d not in person else max(4, round(PERSON_SAMPLE * len(ids) / total))
        random_ids += weighted_sample(rng, sorted(ids), min(k, len(ids)), hard)
    for i in random_ids:
        why[i].append("random")
    ids = sorted(why, key=lambda i: (ts[i]["meta"]["db"], i))
    with open(os.path.join(READ, "sample.jsonl"), "w") as f:
        for i in ids:
            f.write(json.dumps({"id": i, "db": ts[i]["meta"]["db"], "why": why[i]}) + "\n")
    batches = {str(n): ids[s:s + BATCH] for n, s in enumerate(range(0, len(ids), BATCH))}
    batches["double"] = sorted(rng.sample(sorted(random_ids), min(DOUBLE, len(random_ids))), key=lambda i: (ts[i]["meta"]["db"], i))
    json.dump(batches, open(os.path.join(READ, "batches.json"), "w"), indent=1)
    c = Counter(w.split(":")[0] for v in why.values() for w in v)
    print(f"{len(ids)} tasks in {len(batches) - 1} batches (+ double {len(batches['double'])}): {dict(c)}")


def cmd_risky(a):
    """The riskier subset (2026-10-07): every task that inserts into a table that is not the speaker's own, and every
    archive-shaped task. Tasks the first round already read are read again, to compare."""
    os.makedirs(READ, exist_ok=True)
    ts = tasks()
    first = {json.loads(l)["id"] for l in open(os.path.join(io.RESULTS, "audit", "read", "sample.jsonl"))}
    why = defaultdict(list)
    for i, t in ts.items():
        m = t["meta"]
        own = set(m["plan"]["tables"]["own"])
        for x in t["actions"]:
            for s in check.split_statements(x["kwargs"]["sql"]):
                mt = re.match(r'(?is)\s*INSERT\s+(?:OR\s+\w+\s+)?INTO\s+["`\[]?(\w+)', s)
                if mt and mt.group(1) not in own and "insert_public" not in why[i]:
                    why[i].append("insert_public")
        if m["plan"]["shape"].get("archive"):
            why[i].append("archive")
        if i in first and why[i]:
            why[i].append("read_before")
    ids = sorted((i for i in why if why[i]), key=lambda i: (ts[i]["meta"]["db"], i))
    with open(os.path.join(READ, "sample.jsonl"), "w") as f:
        for i in ids:
            f.write(json.dumps({"id": i, "db": ts[i]["meta"]["db"], "why": why[i]}) + "\n")
    batches = {str(n): ids[s:s + BATCH] for n, s in enumerate(range(0, len(ids), BATCH))}
    json.dump(batches, open(os.path.join(READ, "batches.json"), "w"), indent=1)
    c = Counter(w for i in ids for w in why[i])
    print(f"{len(ids)} tasks in {len(batches)} batches: {dict(c)}")


def read_before():
    """Ids some earlier reading round sampled."""
    out = set()
    for d in os.listdir(os.path.join(io.RESULTS, "audit")):
        f = os.path.join(io.RESULTS, "audit", d, "sample.jsonl")
        if d.startswith("read") and os.path.join(io.RESULTS, "audit", d) != READ and os.path.exists(f):
            out |= {r["id"] for r in io.read_jsonl(f)}
    return out


def cmd_random(a):
    """RANDOM_N tasks drawn uniformly from those no earlier round read, spread over the databases by size, to estimate
    the bad rate of the unread rest (2026-10-07). Tasks already found bad (read_risky/bad.json) are left out."""
    os.makedirs(READ, exist_ok=True)
    rng = random.Random(1)
    ts = tasks()
    bad = {r["id"] for r in json.load(open(os.path.join(io.RESULTS, "audit", "read_risky", "bad.json")))}
    pool, skip = defaultdict(list), read_before() | bad
    for i, t in ts.items():
        if i not in skip:
            pool[t["meta"]["db"]].append(i)
    total = sum(len(v) for v in pool.values())
    # largest remainder, so the shares add up to RANDOM_N exactly
    share = {d: RANDOM_N * len(v) / total for d, v in pool.items()}
    k = {d: int(x) for d, x in share.items()}
    for d in sorted(share, key=lambda d: k[d] - share[d])[:RANDOM_N - sum(k.values())]:
        k[d] += 1
    ids = sorted((i for d, v in pool.items() for i in rng.sample(sorted(v), k[d])), key=lambda i: (ts[i]["meta"]["db"], i))
    with open(os.path.join(READ, "sample.jsonl"), "w") as f:
        for i in ids:
            f.write(json.dumps({"id": i, "db": ts[i]["meta"]["db"], "why": ["random"]}) + "\n")
    size = math.ceil(len(ids) / RANDOM_BATCHES)
    batches = {str(n): ids[s:s + size] for n, s in enumerate(range(0, len(ids), size))}
    json.dump(batches, open(os.path.join(READ, "batches.json"), "w"), indent=1)
    print(f"{len(ids)} of {total} unread tasks in {len(batches)} batches; "
          f"entity {sum(ts[i]['meta']['task_type'] == '6_entity' for i in ids)}")


def batch_ids(b):
    return json.load(open(os.path.join(READ, "batches.json")))[str(b)]


def done(kind, b):
    return {r["id"]: r for r in io.read_jsonl(os.path.join(READ, f"{kind}_{b}.jsonl"))}


_dbs = {}


def db_ctx(db):
    """(DbAudit, profile, read-only connection) of a database, opened once per process."""
    if db not in _dbs:
        m = manifest()[db]
        rec = io.load_db_recs(io.ANCHORS_JSON)[m["db_key"]]
        path = io.resolve_db_path(rec["path"])
        _dbs[db] = (path, db_profile.get(m["db_key"]), sqlite3.connect(f"file:{path}?mode=ro", uri=True))
    return _dbs[db]


def short(v, n=60):
    s = str(v)
    return s if len(s) <= n else s[:n] + "..."


def fmt_row(r, cols=None):
    return "{" + ", ".join(f"{c}: {short(v)}" for c, v in r.items() if c != "__rowid__" and v not in (None, "")
                           and (cols is None or c in cols)) + "}"


def speaker_row(conn, meta):
    try:
        cur = conn.execute(f"SELECT * FROM {_q(meta['anchor_table'])} WHERE {_q(meta['anchor_key'])} = ?", (meta["key_value"],))
        r = cur.fetchone()
        return dict(zip([d[0] for d in cur.description], r)) if r else None
    except sqlite3.Error:
        return None


WHO = {"1_self": "the person in this record, about their own data", "2_self_and_public": "the person in this record",
       "3_public_only": "the person in this record", "5_proxy": "a third party writing on behalf of the person in this record",
       "6_entity": "someone outside the database who says the entity below is theirs (no user table to authenticate against)"}


def cmd_blind(a):
    ts, preds = tasks(), done("pred", a.batch)
    todo = [i for i in batch_ids(a.batch) if i not in preds]
    shown = set()
    for i in todo:
        t = ts[i]; m = t["meta"]
        path, prof, conn = db_ctx(m["db"])
        if m["db"] not in shown:
            shown.add(m["db"])
            print(f"=== database {m['db']} ===\n{prof['description']}")
            if prof.get("quirks"):
                print("Data quirks: " + " | ".join(short(q, 200) for q in prof["quirks"]))
            for tb in sorted(db_profile.scope_tables(prof)):
                cols = [r[1] for r in conn.execute(f"PRAGMA table_info({_q(tb)})")]
                print(f"  {tb}({', '.join(cols[:30])}{', ...' if len(cols) > 30 else ''})")
            print()
        r = speaker_row(conn, m)
        print(f"### {i}\nSpeaker: {WHO.get(m['task_type'], m['task_type'])}.")
        print(f"Record ({m['anchor_table']}.{m['anchor_key']} = {m['key_value']}): {fmt_row(r) if r else 'not found'}")
        print(f"Instruction: {t['instruction']}\n")
    print(f"[{len(todo)} tasks without a prediction in batch {a.batch}]")


def _append(kind, b, path):
    text = open(path).read().strip()
    recs = json.loads(text) if text.startswith("[") else [json.loads(l) for l in text.splitlines() if l.strip()]
    ids = set(batch_ids(b))
    bad = [r.get("id") for r in recs if r.get("id") not in ids]
    if bad:
        sys.exit(f"not in batch {b}: {bad}")
    if kind == "pred":
        bad = [r["id"] for r in recs if not r.get("pred")]
    else:
        bad = [r["id"] for r in recs if r.get("verdict") not in ("good", "bad", "unsure") or not isinstance(r.get("tags", []), list)]
        missing = [r["id"] for r in recs if r["id"] not in done("pred", b)]
        if missing:
            sys.exit(f"no prediction yet for: {missing}")
    if bad:
        sys.exit(f"malformed records: {bad}")
    io.append_jsonl(os.path.join(READ, f"{kind}_{b}.jsonl"), recs)
    print(f"stored {len(recs)} {kind} records for batch {b}")


def cmd_predict(a):
    _append("pred", a.batch, a.file)


def cmd_verdict(a):
    _append("verdict", a.batch, a.file)


def effects_text(aud, t, conn):
    m = t["meta"]
    stmts = [s for x in t["actions"] for s in check.split_statements(x["kwargs"]["sql"])]
    allowed = {check.norm_literal(v) for v in (speaker_row(conn, m) or {}).values() if v not in (None, "")}
    aud.run(t["instruction"], stmts, allowed)
    out = []
    for n, op, tb, old, new in aud.last:
        keys = (aud.pk.get(tb) or {}).get("cols") or list((old or new or [{}])[0])[1:3]
        out.append(f"  [{n}] {op} {tb}: {len(old) if op != 'INSERT' else len(new)} row(s)")
        if op == "UPDATE":
            for o, r in list(zip(old, new))[:8]:
                ch = [f"{c}: {short(o.get(c))} -> {short(v)}" for c, v in r.items() if c != "__rowid__" and o.get(c) != v]
                out.append(f"      {fmt_row(o, keys)} " + "; ".join(ch))
        else:
            for r in (new if op == "INSERT" else old)[:8]:
                out.append(f"      {fmt_row(r)}")
        if max(len(old), len(new)) > 8:
            out.append(f"      ... {max(len(old), len(new)) - 8} more")
    return stmts, out


def cmd_reveal(a):
    ts, preds, verdicts = tasks(), done("pred", a.batch), done("verdict", a.batch)
    flags = {r["id"]: r for r in io.read_jsonl(FLAGS) if r["src"] == "v2"}
    auds = {}
    todo = [i for i in batch_ids(a.batch) if i in preds and i not in verdicts]
    for i in todo:
        t = ts[i]; m = t["meta"]
        path, prof, conn = db_ctx(m["db"])
        if m["db"] not in auds:
            auds[m["db"]] = audit.DbAudit(path)
        stmts, eff = effects_text(auds[m["db"]], t, conn)
        print(f"### {i}  (type {m['task_type']}, difficulty {m['difficulty']['level']}"
              f"{', repaired: ' + m['repair']['kind'] if m.get('repair') else ''})")
        print(f"Instruction: {t['instruction']}")
        print(f"Your prediction: {preds[i]['pred']}")
        print("Gold SQL:"); print("\n".join(f"  [{n}] {s}" for n, s in enumerate(stmts)))
        print("Effect on the database:"); print("\n".join(eff))
        fl = [f for f in flags.get(i, {}).get("flags", [])]
        print("Script flags: " + (json.dumps(fl, ensure_ascii=False) if fl else "none") + "\n")
    print(f"[{len(todo)} tasks revealed in batch {a.batch}]")


def cmd_query(a):
    if not re.match(r"(?is)^\s*(select|with|pragma)\b", a.sql):
        sys.exit("read-only: SELECT, WITH or PRAGMA only")
    path, _, conn = db_ctx(a.db)
    cur = conn.execute(a.sql)
    cols = [d[0] for d in cur.description or []]
    rows = cur.fetchmany(31)
    print(" | ".join(cols))
    for r in rows[:30]:
        print(" | ".join(short(v, 80) for v in r))
    if len(rows) > 30:
        print("... more rows")


def cmd_status(a):
    b = json.load(open(os.path.join(READ, "batches.json")))
    for k, ids in b.items():
        print(f"batch {k}: {len(ids)} tasks, predicted {len(done('pred', k))}, judged {len(done('verdict', k))}")


def main():
    global READ
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--round", help="a later reading round; its files go to results/audit/read_<round>/")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sample"); sub.add_parser("status"); sub.add_parser("risky"); sub.add_parser("random")
    for c in ("blind", "reveal"):
        sub.add_parser(c).add_argument("--batch", required=True)
    for c in ("predict", "verdict"):
        p = sub.add_parser(c); p.add_argument("--batch", required=True); p.add_argument("--file", required=True)
    q = sub.add_parser("query"); q.add_argument("--db", required=True); q.add_argument("sql")
    a = ap.parse_args()
    if a.round:
        READ = os.path.join(io.RESULTS, "audit", "read_" + a.round)
    {"sample": cmd_sample, "risky": cmd_risky, "random": cmd_random, "blind": cmd_blind, "predict": cmd_predict, "verdict": cmd_verdict, "reveal": cmd_reveal,
     "query": cmd_query, "status": cmd_status}[a.cmd](a)


if __name__ == "__main__":
    main()
