#!/usr/bin/env python3
"""Apply the data-gen DB filters (docs/2026-09-24-data-gen-db-selection.md) to candidate SQLite DBs.
Usage (data layout: ~/Documents/Isa/text2sql_bench/README.md):
  T=~/Documents/Isa/text2sql_bench
  conda run -n dysql python scripts/select_dbs.py \
    --source "bird=$T/bird/train/train_databases/*/*.sqlite" --source "bird=$T/bird/dev/dev_databases/*/*.sqlite" \
    --source "spider2=$T/spider2_lite/sqlite/*.sqlite" --source "spider1=$T/spider1/test_database/*/*.sqlite" \
    --source "synsql=$T/synsql/databases/*/*.sqlite" \
    --holdout "spider1=$T/spider1/dev.json" --holdout "spider1=$T/spider1/test.json" \
    --out results/db_select/db_select_all.csv --candidates ../docs/data_gen/candidate_dbs.csv
Source names used for leak lists and dedup order: bird, spider2, spider1, synsql.
--holdout marks every db_id in an eval question file as excluded (Spider dev/test = CoSQL/SParC eval DBs).
Any DB whose schema overlaps an excluded DB (DySQL, LEAK, holdout) by >= CFG["overlap"] is excluded too."""
import argparse, csv, glob, json, os, sys
from collections import Counter
from multiprocessing import Pool
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dysql_bench.db_select import profile_db, evaluate, dedup, schema_items

ENVS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dysql_bench", "envs")
# DySQL's own DBs plus known same-origin copies (Chinook, Sakila/Pagila, EU soccer, Northwind),
# and the Ergast F1 data, which BIRD-Interact-full ships as `sports_events` (renamed columns, same rows).
LEAK = {"spider1": {"chinook_1", "store_1", "sakila_1", "soccer_1", "formula_1"},
        "bird": {"movie_3", "european_football_2", "law_episode", "ice_hockey_draft", "cookbook",
                 "retail_world", "cars", "human_resources", "formula_1"},
        "spider2": {"sqlite-sakila", "northwind", "EU_soccer", "complex_oracle", "BowlingLeague",
                    "EntertainmentAgency", "Pagila", "chinook", "music", "f1"}}
CFG = dict(tables=(3, 20), max_cols=250, rows=(200, 3_000_000), max_mb=300, min_fks=2, fk_min_hit=0.3,
           anchor_min_rows=5, long_text_avg_len=200, min_component_share=0.6, overlap=0.6)
DEDUP_ORDER = ["bird", "spider2", "spider1", "synsql"]
COLS = ["source", "db", "pass", "dup_of", "fail_reasons", "n_tables", "n_cols", "total_rows", "size_mb",
        "n_fks_declared", "n_fks_inferred", "n_fks_valid", "invalid_fks", "unverified_fks", "has_person_named",
        "anchor_kinds", "person_anchors", "entity_anchors", "update_targets", "targets_no_key",
        "composite_key_tables", "long_text_cols", "empty_string_cols", "fragmented", "leak_match",
        "max_leak_overlap", "table_names"]

def _profile(a):
    source, path = a
    try:
        return source, profile_db(path)
    except Exception as e:
        return source, {"db": os.path.splitext(os.path.basename(path))[0], "error": str(e)}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", action="append", required=True, help="name=glob")
    ap.add_argument("--out", required=True)
    ap.add_argument("--candidates")
    ap.add_argument("--holdout", action="append", default=[], help="source=eval question json (db_id fields)")
    ap.add_argument("--workers", type=int, default=16)
    a = ap.parse_args()
    excluded = {k: set(v) for k, v in LEAK.items()}
    for h in a.holdout:
        name, path = h.split("=", 1)
        excluded.setdefault(name, set()).update(ex["db_id"] for ex in json.load(open(path)))
    jobs = [(name, f) for s in a.source for name, pat in [s.split("=", 1)] for f in sorted(glob.glob(pat))]
    with Pool(a.workers) as p:
        profiles = p.map(_profile, jobs, chunksize=16)
    # reference schemas: DySQL's DBs plus every explicitly excluded DB, so copies of them are caught too
    leak_ref = {f"dysql:{os.path.basename(f)[:-7]}": schema_items(profile_db(f))
                for f in glob.glob(f"{ENVS}/*/data/*.sqlite")}
    leak_ref.update({f"{s}:{p['db']}": schema_items(p) for s, p in profiles
                     if "error" not in p and p["db"] in excluded.get(s, ())})
    rows = []
    for s, p in profiles:
        if "error" in p:
            rows.append({"source": s, "db": p["db"], "pass": False, "fail_reasons": [f"error: {p['error']}"],
                         "table_names": [], "schema": []})
            continue
        own = f"{s}:{p['db']}"
        cfg = {**CFG, "leak_names": excluded.get(s, set()),
               "leak_ref": {k: v for k, v in leak_ref.items() if k != own}}
        rows.append({"source": s, **evaluate(p, cfg)})
    rows = dedup(rows, DEDUP_ORDER, threshold=CFG["overlap"])
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    def write(path, rs):
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, COLS, extrasaction="ignore"); w.writeheader()
            for r in rs:
                w.writerow({k: "; ".join(v) if isinstance(v, list) else v for k, v in r.items() if k in COLS})
    write(a.out, rows)
    keep = [r for r in rows if r["pass"] and not r["dup_of"]]
    if a.candidates:
        os.makedirs(os.path.dirname(os.path.abspath(a.candidates)), exist_ok=True)
        write(a.candidates, keep)
    print(f"{'source':8s} {'total':>6s} {'pass':>5s} {'dup':>4s} {'keep':>5s}  top fail reasons")
    for s in dict.fromkeys(r["source"] for r in rows):
        rs = [r for r in rows if r["source"] == s]
        fr = Counter(x for r in rs for x in r["fail_reasons"])
        print(f"{s:8s} {len(rs):6d} {sum(r['pass'] for r in rs):5d} {sum(bool(r['dup_of']) for r in rs):4d} "
              f"{sum(r in keep for r in rs):5d}  {dict(fr.most_common(6))}")

if __name__ == "__main__":
    main()
