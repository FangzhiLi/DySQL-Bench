#!/usr/bin/env python3
"""Run taskgen.check on DySQL-Bench's 1062 gold tasks and report the pass rate outside class 7 (spec §7: >= 90%).
Usage (from taskgen/v2/):
  ~/miniconda3/envs/dysql/bin/python scripts/calibrate_check.py --out docs/2026-09-28-check-calibration.md"""
import argparse, csv, glob, importlib, os, sys
from collections import Counter, defaultdict
V2 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [V2, os.path.join(os.path.dirname(V2), "common")]   # taskgen_v2, taskgen_common
from taskgen_common.db_select import profile_db, all_fks, row_key
from taskgen_common.db_anchor import update_targets, anchors
from taskgen_common.paths import DATA, DYSQL_ENVS
from taskgen_v2 import check

TYPES_CSV = os.path.join(DATA, "dysql_task_types.csv")
ENVS = sorted(os.path.basename(os.path.dirname(os.path.dirname(f))) for f in glob.glob(f"{DYSQL_ENVS}/*/data/*.sqlite"))


def dysql_db_rec(env):
    path = glob.glob(f"{DYSQL_ENVS}/{env}/data/*.sqlite")[0]
    p = profile_db(path)
    fks = [f for f in all_fks(p) if f["hit"] is None or f["hit"] >= 0.3]
    keys = {t["name"]: row_key(t) for t in p["tables"] if row_key(t)}
    anc = anchors(p, fks, keys, update_targets(p, keys, 200), 5)
    return {"source": "dysql", "db": env, "path": path, "anchors": anc,
            "fks": [{"table": f["table"], "col": f["cols"][0], "ref_table": f["ref_table"], "ref_col": f["ref_cols"][0],
                     "hit": f["hit"], "source": f["source"]} for f in fks if len(f["cols"]) == 1 and f["ref_cols"][0]]}


def _rows(env):
    with open(TYPES_CSV, encoding="utf-8") as f:
        return {int(r["idx"]): r for r in csv.DictReader(f) if r["env"] == env}


def dysql_candidates(env):
    tasks = importlib.import_module(f"dysql_bench.envs.{env}.tasks_test").TASKS_TEST
    rec = dysql_db_rec(env)
    meta = _rows(env)
    out = []
    for i, t in enumerate(tasks):
        m = meta[i]
        ids = [x.split(":", 1) for x in m["speaker_ids"].split(";") if ":" in x]
        anchor_table, kv = None, None
        if m["speaker"] == "db_person" and ids:
            anchor_table, kv = ids[0]
            kv = int(kv) if kv.lstrip("-").isdigit() else kv
        if anchor_table is None or not any(a["table"] == anchor_table for a in rec["anchors"]):
            written = {w.split(" ", 1)[1].split(":")[0] for w in m["writes"].split(" | ") if " " in w}
            a = next((a for a in rec["anchors"] if written <= {a["table"], *a["down"], *a["up"]}), rec["anchors"][0])
            anchor_table, kv = a["table"], None
        out.append({"id": f"dysql:{env}:{i}", "anchor_table": anchor_table, "key_value": kv, "group": m["group"],
                    "speaker_ids": [[t, k] for t, k in ids] if m["speaker"] == "db_person" else None,
                    "speaker_in_db": m["speaker"] == "db_person", "instruction": t.instruction,
                    "actions": [{"sql": a.kwargs["sql"]} for a in t.actions if a.name == "sql"]})
    return out


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
