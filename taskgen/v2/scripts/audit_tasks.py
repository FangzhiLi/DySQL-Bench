#!/usr/bin/env python3
"""Audit every finished task (output/manifest.json) with taskgen_v2.audit, and DySQL's 1062 gold tasks for reference
(2026-10-06). Writes results/audit/flags.jsonl (one line per task: its flags and stats) and prints the rate of each
flag in both sets. A flag means "read this task", not "bad".
Usage (from taskgen/v2/):
  P=~/miniconda3/envs/dysql/bin/python
  $P scripts/audit_tasks.py [--no-dysql] [--db NAME ...]"""
import argparse, json, os, re, sqlite3, sys, time
from collections import Counter
V2 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [V2, os.path.join(os.path.dirname(V2), "common")]
from taskgen_common.db_select import _q
from taskgen_v2 import audit, check, db_profile, dedup, dysql, io, owners

OUT = os.path.join(io.RESULTS, "audit")
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def schema_words(conn):
    """Table and column names a user would not write as plain English (snake_case or camelCase)."""
    out = set()
    for (t,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'"):
        for n in [t] + [r[1] for r in conn.execute(f"PRAGMA table_info({_q(t)})")]:
            if "_" in n or re.search(r"[a-z][A-Z]", n):
                out.add(n.lower())
    return out


def mentions_schema(instruction, words):
    return any(w.lower() in words for w in IDENT.findall(instruction or ""))


def row_values(conn, table, key, value):
    if not table or not key or value is None:
        return set()
    try:
        r = conn.execute(f"SELECT * FROM {_q(table)} WHERE {_q(key)} = ?", (value,)).fetchone()
    except sqlite3.Error:
        return set()
    return {check.norm_literal(v) for v in (r or ()) if v not in (None, "")}


def audit_v2(dbs, dysql_shingles):
    recs = io.load_db_recs(io.ANCHORS_JSON)
    manifest = json.load(open(os.path.join(V2, "output", "manifest.json")))
    for db, m in manifest.items():
        if dbs and db not in dbs:
            continue
        t0 = time.time()
        rec, prof = recs[m["db_key"]], db_profile.get(m["db_key"])
        path = io.resolve_db_path(rec["path"])
        probe = check._memory_copy(path)
        tr = owners.Tracer.from_profile(prof, rec, probe)
        edges = [(child, cols, parent, ref) for child, refs in tr.up.items() for cols, parent, ref in refs]
        a = audit.DbAudit(path, edges)
        words, idx = schema_words(a.conn), {}
        n = 0
        for t in io.read_jsonl(os.path.join(V2, "output", m["tasks"])):
            meta = t["meta"]
            stmts = [s for x in t["actions"] for s in check.split_statements(x["kwargs"]["sql"])]
            allowed = row_values(a.conn, meta["anchor_table"], meta.get("anchor_key"), meta.get("key_value"))
            flags, stats = a.run(t["instruction"], stmts, allowed, meta["plan"]["tables"]["public"])
            if meta["task_type"] != "6_entity":
                root = meta["anchor_table"]
                cols = (prof["persons"].get(root) or {}).get("name_cols") or []
                if root not in idx:
                    idx[root] = audit.name_index(a.conn, root, cols)
                flags += audit.identity(a.conn, root, meta["anchor_key"], meta["key_value"], cols, t["instruction"], idx[root])
            sim = audit.near_dup(t["instruction"], dysql_shingles)
            if sim >= audit.NEAR_DUP:
                flags.append({"k": "dysql_near_dup", "jaccard": round(sim, 3)})
            n += 1
            yield {"id": meta["id"], "db": db, "src": "v2", "task_type": meta["task_type"],
                   "repair": (meta.get("repair") or {}).get("kind"), "difficulty": meta["difficulty"]["level"],
                   "flags": flags, "stats": stats, "schema_mention": mentions_schema(t["instruction"], words),
                   "near_dup": round(sim, 3)}
        probe.close()
        print(f"{db}: {n} tasks in {time.time() - t0:.0f}s", flush=True)


def audit_dysql():
    for env in dysql.ENVS:
        t0 = time.time()
        rec = dysql.db_rec(env)
        edges = [(f["table"], (f["col"],), f["ref_table"], (f["ref_col"],)) for f in rec["fks"]]
        a = audit.DbAudit(rec["path"], edges)
        words = schema_words(a.conn)
        cands = dysql.candidates(env)
        anchors = {x["table"]: x["key"] for x in rec["anchors"]}
        for c in cands:
            stmts = [s for x in c["actions"] for s in check.split_statements(x["sql"])]
            allowed = set()
            for tbl, k in c.get("speaker_ids") or []:
                allowed |= row_values(a.conn, tbl, anchors.get(tbl), k)
            flags, stats = a.run(c["instruction"], stmts, allowed)
            yield {"id": c["id"], "db": env, "src": "dysql", "task_type": c["group"], "repair": None, "difficulty": None,
                   "flags": flags, "stats": stats, "schema_mention": mentions_schema(c["instruction"], words)}
        print(f"dysql {env}: {len(cands)} tasks in {time.time() - t0:.0f}s", flush=True)


def summary(recs):
    sets = {s: [r for r in recs if r["src"] == s] for s in ("v2", "dysql")}
    kinds = sorted({f["k"] for r in recs for f in r["flags"]})
    lines = ["| flag | v2 tasks | v2 % | DySQL tasks | DySQL % |", "|---|---|---|---|---|"]
    for k in kinds:
        cells = []
        for s in ("v2", "dysql"):
            n = sum(any(f["k"] == k for f in r["flags"]) for r in sets[s])
            cells += [str(n), f"{100 * n / max(1, len(sets[s])):.1f}"]
        lines.append(f"| {k} | " + " | ".join(cells) + " |")
    for s in ("v2", "dysql"):
        rs = sets[s]
        if not rs:
            continue
        st = Counter()
        for r in rs:
            st.update(r["stats"])
        lines.append(f"\n{s}: {len(rs)} tasks; with any flag {sum(bool(r['flags']) for r in rs)}; "
                     f"schema named {100 * sum(r['schema_mention'] for r in rs) / len(rs):.0f}%; "
                     f"self-contained WHERE statements {st['stmts_self_contained']}/{st['stmts_with_where']}; "
                     f"copies with unstated order {st['copy_order_unstated']}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", nargs="*"); ap.add_argument("--no-dysql", action="store_true")
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    gold = [r["instruction"] for r in io.read_jsonl(os.path.join(io.RESULTS, "dysql_metrics.jsonl"))]
    shingles = [dedup._shingles(x) for x in gold]
    recs = list(audit_v2(set(a.db or ()), shingles))
    if not a.no_dysql:
        recs += list(audit_dysql())
    with open(os.path.join(OUT, "flags.jsonl"), "w") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    text = summary(recs)
    open(os.path.join(OUT, "summary.md"), "w").write(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
