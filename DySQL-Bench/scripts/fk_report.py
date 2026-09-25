#!/usr/bin/env python3
"""Print the data-checked hit rate of every declared/inferred FK in the given SQLite files, lowest first.
Usage (from DySQL-Bench/): ~/miniconda3/envs/dysql/bin/python scripts/fk_report.py dysql_bench/envs/*/data/*.sqlite"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dysql_bench.db_select import profile_db, all_fks

rows = []
for path in sys.argv[1:]:
    p = profile_db(path)
    for f in all_fks(p):
        rows.append((f["hit"] is not None, f["hit"] or 0.0, p["db"], f["source"],
                     f"{f['table']}.{','.join(f['cols'])}", f"{f['ref_table']}.{','.join(map(str, f['ref_cols']))}"))
for _, hit, db, src, child, ref in sorted(rows):
    print(f"{db:24s} {src:8s} {child} -> {ref}  {'unverified' if not _ else f'{hit:.3f}'}")
