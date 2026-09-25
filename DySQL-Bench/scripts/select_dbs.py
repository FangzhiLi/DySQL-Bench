#!/usr/bin/env python3
"""Apply the data-gen DB filters (docs/2026-09-24-data-gen-db-selection.md) to candidate SQLite DBs.
Usage: conda run -n dysql python scripts/select_dbs.py \
         --source bird='/data/bird/*/*/*.sqlite' --source spider1='...' ... \
         --out results/db_select_all.csv --candidates ../docs/data_gen/candidate_dbs.csv
Source names used for leak lists and dedup order: bird, spider2, spider1, synsql."""
import argparse, csv, glob, os, sys
from collections import Counter
from multiprocessing import Pool
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dysql_bench.db_select import profile_db, evaluate, dedup, schema_items

ENVS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dysql_bench", "envs")
# DySQL's own DBs plus known same-origin copies (Chinook, Sakila/Pagila, EU soccer, Northwind).
LEAK = {"spider1": {"chinook_1", "store_1", "sakila_1", "soccer_1"},
        "bird": {"movie_3", "european_football_2", "law_episode", "ice_hockey_draft", "cookbook",
                 "retail_world", "cars", "human_resources"},
        "spider2": {"sqlite-sakila", "northwind", "EU_soccer", "complex_oracle", "BowlingLeague",
                    "EntertainmentAgency", "Pagila", "chinook", "music"}}
CFG = dict(tables=(3, 20), max_cols=250, rows=(200, 3_000_000), max_mb=100, min_fks=2,
           txn_min_rows=50, min_component_share=0.6, overlap=0.6)
DEDUP_ORDER = ["bird", "spider2", "spider1", "synsql"]
COLS = ["source", "db", "pass", "dup_of", "fail_reasons", "n_tables", "n_cols", "total_rows", "size_mb",
        "n_fks_declared", "n_fks_inferred", "has_person", "person_tables", "txn_tables", "txn_no_key",
        "fragmented", "leak_match", "max_leak_overlap", "table_names"]

def _job(a):
    source, path, cfg = a
    try:
        return {"source": source, **evaluate(profile_db(path), cfg)}
    except Exception as e:
        return {"source": source, "db": os.path.basename(path), "pass": False, "fail_reasons": [f"error: {e}"],
                "table_names": [], "schema": []}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", action="append", required=True, help="name=glob")
    ap.add_argument("--out", required=True)
    ap.add_argument("--candidates")
    ap.add_argument("--workers", type=int, default=16)
    a = ap.parse_args()
    leak_ref = {os.path.basename(f)[:-7]: schema_items(profile_db(f))
                for f in glob.glob(f"{ENVS}/*/data/*.sqlite")}
    jobs = []
    for s in a.source:
        name, pat = s.split("=", 1)
        cfg = {**CFG, "leak_names": LEAK.get(name, set()), "leak_ref": leak_ref}
        jobs += [(name, f, cfg) for f in sorted(glob.glob(pat))]
    with Pool(a.workers) as p:
        rows = dedup(p.map(_job, jobs, chunksize=16), DEDUP_ORDER, threshold=CFG["overlap"])
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    def write(path, rs):
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, COLS, extrasaction="ignore"); w.writeheader()
            for r in rs:
                w.writerow({k: "; ".join(v) if isinstance(v, list) else v for k, v in r.items()})
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
