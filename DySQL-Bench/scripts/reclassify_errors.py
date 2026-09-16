#!/usr/bin/env python3
"""Rewrite legacy 'error' records that were really agent failures (context overflow, thinking exhausted
max_tokens) to their proper termination label. Reward stays 0. Idempotent. Skips files whose env is
still being written (pass --include-running to override).
Usage: python scripts/reclassify_errors.py results/full_<tag>/*.json
"""
import glob, json, sys
from dysql_bench.run import reclassify_error

paths = [f for a in sys.argv[1:] for f in glob.glob(a) if not f.endswith(".config.json")]
for f in paths:
    rs = json.load(open(f)); changed = 0
    for r in rs:
        if (r.get("meta") or {}).get("termination") != "error":
            continue
        label = reclassify_error(r)
        if label:
            r["meta"]["termination"] = label
            r["meta"]["reclassified_from"] = "error"
            r["info"]["server_error"] = label
            changed += 1
    if changed:
        json.dump(rs, open(f, "w"), indent=2)
    print(f"{f.split('/')[-1][:40]:40s} reclassified={changed} remaining_errors={sum(1 for r in rs if (r.get('meta') or {}).get('termination')=='error')}")
