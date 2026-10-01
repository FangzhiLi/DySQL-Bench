#!/usr/bin/env python3
"""Run v1's frozen check and this version's check on the same candidates and attribute every changed verdict.
Sets: DySQL's 1062 gold tasks, and every candidate under --results (default: v1's full run, ../v1/results).
Only candidate ids and counts go into the report, never task text.
Usage (from taskgen/v2/):
  ~/miniconda3/envs/dysql/bin/python scripts/check_diff.py --out docs/<date>-check-recalibration.md"""
import argparse, glob, os, sys
from collections import Counter, defaultdict
V2 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TASKGEN = os.path.dirname(V2)
sys.path[:0] = [V2, os.path.join(TASKGEN, "v1"), os.path.join(TASKGEN, "common")]   # taskgen_v2, taskgen_v1, taskgen_common
from taskgen_v1 import check as old_check
from taskgen_v2 import check as new_check, dysql, io

YES = {True: "通过", False: "拒绝"}


def kinds(result):
    return {x.split(":")[0] for x in result["reasons"]}


def section(title, pairs):
    trans = Counter((o["ok"], n["ok"]) for _, o, n in pairs)
    groups, relabel = defaultdict(list), Counter()
    for cid, o, n in pairs:
        ko, kn = kinds(o), kinds(n)
        if o["ok"] and not n["ok"]:
            groups["通过 → 拒绝：" + "+".join(sorted(kn))].append(cid)
        elif n["ok"] and not o["ok"]:
            groups["拒绝 → 通过：v1 的原因 " + "+".join(sorted(ko))].append(cid)
        elif not o["ok"] and ko != kn:
            groups["仍拒绝、原因变了：" + "+".join(sorted(ko)) + " → " + "+".join(sorted(kn))].append(cid)
        if o["task_type"] and n["task_type"] and o["task_type"] != n["task_type"]:
            relabel[f"{o['task_type']} → {n['task_type']}"] += 1
    lines = [f"## {title}（{len(pairs)} 条）", "", "| v1 | v2 | 条数 |", "|---|---|---|"]
    lines += [f"| {YES[a]} | {YES[b]} | {trans[(a, b)]} |" for a in (True, False) for b in (True, False)]
    lines += ["", "### 判决变化", ""]
    lines += [f"- {k}（{len(v)}）：" + ", ".join(v[:10]) + (" …" if len(v) > 10 else "") for k, v in sorted(groups.items())] or ["- 无"]
    lines += ["", "### 类型变化（两边都算出了类型的）", ""]
    lines += [f"- {k}：{v}" for k, v in relabel.most_common()] or ["- 无"]
    return lines


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results", default=os.path.join(TASKGEN, "v1", "results"))
    ap.add_argument("--out")
    a = ap.parse_args()
    pairs = []
    for env in dysql.ENVS:
        rec = dysql.db_rec(env)
        for c in dysql.candidates(env):
            pairs.append((c["id"], old_check.run_check_safe(rec, c), new_check.run_check_safe(rec, c)))
    lines = ["# 执行检查重新校准：v1 vs v2", "",
             "`scripts/check_diff.py` 生成：同一批候选分别跑 v1（tag `taskgen-v1`，冻结）和 v2 的 `check.run_check_safe`，逐条比较。"
             "只列候选 id，不摘录题目内容。", ""] + section("DySQL 金标准", pairs)
    recs = {v["db"]: v for v in io.load_db_recs().values()}
    pairs = []
    for f in sorted(glob.glob(os.path.join(a.results, "*", "candidates.jsonl"))):
        rec = recs[os.path.basename(os.path.dirname(f))]
        for c in io.read_jsonl(f):
            pairs.append((c["id"], old_check.run_check_safe(rec, c), new_check.run_check_safe(rec, c)))
    lines += [""] + section(f"候选：{os.path.relpath(a.results, V2)}", pairs)
    text = "\n".join(lines)
    print(text)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")


if __name__ == "__main__":
    main()
