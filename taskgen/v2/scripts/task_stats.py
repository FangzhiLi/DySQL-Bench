#!/usr/bin/env python3
"""Compare task sets with DySQL-Bench on the design §3 metrics; one column per set.
Usage (from taskgen/v2/):
  P=~/miniconda3/envs/dysql/bin/python
  $P scripts/task_stats.py --set v1=../v1/results --set v2=results [--refresh-dysql] [--out FILE]
The DySQL column is cached in results/dysql_metrics.jsonl; pass --refresh-dysql after changing the check."""
import argparse, os, sys
V2 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [V2, os.path.join(os.path.dirname(V2), "common")]   # taskgen_v2, taskgen_common
from taskgen_v2 import io, metrics


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--set", action="append", default=[], metavar="NAME=RESULTS_DIR")
    ap.add_argument("--no-dysql", action="store_true")
    ap.add_argument("--dysql-env", action="append", help="only these DySQL databases in the DySQL column (car, cookbook)")
    ap.add_argument("--refresh-dysql", action="store_true")
    ap.add_argument("--out")
    a = ap.parse_args()
    cols = {}
    if not a.no_dysql:
        cache = os.path.join(io.RESULTS, "dysql_metrics.jsonl")
        if a.refresh_dysql and os.path.exists(cache):
            os.remove(cache)
        recs = metrics.from_dysql(cache)
        if a.dysql_env:
            recs = [r for r in recs if r["db"] in a.dysql_env]
        cols["DySQL" + (" " + "+".join(a.dysql_env) if a.dysql_env else "")] = metrics.compute(recs)
    for s in a.set:
        name, path = s.split("=", 1)
        cols[name] = metrics.compute(metrics.from_results(path))
    text = metrics.render(cols)
    print(text)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")


if __name__ == "__main__":
    main()
