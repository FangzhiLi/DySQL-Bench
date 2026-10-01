#!/usr/bin/env python3
"""Run taskgen.check on DySQL-Bench's 1062 gold tasks and report the pass rate outside class 7 (spec §7: >= 90%).
Usage (from taskgen/v2/):
  ~/miniconda3/envs/dysql/bin/python scripts/calibrate_check.py --out docs/<date>-check-calibration.md"""
import argparse, os, sys
from collections import Counter
V2 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [V2, os.path.join(os.path.dirname(V2), "common")]   # taskgen_v2, taskgen_common
from taskgen_v2 import check
from taskgen_v2.dysql import ENVS, db_rec as dysql_db_rec, candidates as dysql_candidates


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--out"); ap.add_argument("--env", action="append")
    a = ap.parse_args()
    lines = ["# 执行检查在 DySQL 1062 条任务上的校准", "",
             "口径：去掉第 7 类（标准答案不改库）。'去掉部分 no-op' 再去掉只因 noop_write 失败的任务：它们的某条 gold 写语句命中 0 行，正是规则要拦的缺陷。", "",
             "| env | 非第7类任务 | 通过 | 通过率 | 去掉部分 no-op 后通过率 | 主要失败原因 | 类型一致 | 难度 简单/中等/困难 |", "|---|---|---|---|---|---|---|---|"]
    T = O = agree = NO = 0; levels = Counter(); all_reasons = Counter()
    for env in a.env or ENVS:
        rec = dysql_db_rec(env); n = ok = ag = noop = 0; reasons = Counter(); lv = Counter()
        for cand in dysql_candidates(env):
            r = check.run_check(rec, cand)
            if cand["group"] == "7_no_change":
                continue
            n += 1; ok += r["ok"]; ag += (r["task_type"] == cand["group"])
            noop += bool(r["reasons"]) and {x.split(":")[0] for x in r["reasons"]} == {"noop_write"}
            if r["difficulty"]: lv[r["difficulty"]["level"]] += 1
            for x in r["reasons"]: reasons[x.split(":")[0]] += 1
        T += n; O += ok; agree += ag; NO += noop; levels += lv; all_reasons += reasons
        lines.append(f"| {env} | {n} | {ok} | {ok / n:.0%} | {ok / (n - noop):.0%} | {', '.join(f'{k} {v}' for k, v in reasons.most_common(3))} | {ag / n:.0%} | {lv['easy']}/{lv['medium']}/{lv['hard']} |")
    lines.append(f"| **合计** | {T} | {O} | **{O / T:.0%}** | **{O / (T - NO):.0%}** | {', '.join(f'{k} {v}' for k, v in all_reasons.most_common(4))} | {agree / T:.0%} | {levels['easy']}/{levels['medium']}/{levels['hard']} |")
    text = "\n".join(lines)
    print(text)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")


if __name__ == "__main__":
    main()
