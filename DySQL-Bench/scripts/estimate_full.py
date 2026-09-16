#!/usr/bin/env python3
"""Estimate full-run wall time from a pilot directory.
口径 A（墙钟）: pilot_wall_s / n_pilot_tasks * N_TOTAL            -- 已含并发排队，直接外推
口径 B（token）: 每任务 agent/user 生成 token 之和 / 各自实测 tok/s  -- 交叉验证
两者都乘 1.5 作为上限（pagila 提示词偏短，eu_soccer/retail 更长、任务更多）。
"""
import glob, json, sys, statistics

d = sys.argv[1]
N_TOTAL = 1062
CONC = int(sys.argv[2]) if len(sys.argv) > 2 else 5
rs = [r for f in glob.glob(f"{d}/*.json") if not f.endswith(".config.json") for r in json.load(open(f))]
wall = int(open(f"{d}/wall.txt").read().split()[1])
n = len(rs)
per_task = wall / n
est_a = per_task * N_TOTAL


def toks(traj):
    return sum((m.get("usage") or {}).get("completion_tokens") or 0 for m in traj if m.get("role") == "assistant")


def secs(traj):
    return sum(m.get("latency_s") or 0 for m in traj if m.get("role") == "assistant")


a_tok = sum(toks(r["traj"]) for r in rs); a_sec = sum(secs(r["traj"]) for r in rs)
u_tok = sum(toks(r.get("user_traj", [])) for r in rs); u_sec = sum(secs(r.get("user_traj", [])) for r in rs)
a_tps = a_tok / a_sec if a_sec else float("nan"); u_tps = u_tok / u_sec if u_sec else float("nan")
# 口径 B: 每任务串行生成时长，再按并发折算
est_b = (a_tok / a_tps + u_tok / u_tps) / n * N_TOTAL / CONC if a_sec and u_sec else float("nan")
steps = [r["meta"].get("n_steps") or 0 for r in rs]
lp = [r["meta"].get("last_prompt_tokens") or 0 for r in rs]
length_hits = sum(1 for r in rs for m in r["traj"] if m.get("finish_reason") == "length")
print(f"pilot tasks: {n}, wall: {wall}s, per task (concurrent, c={CONC}): {per_task:.0f}s")
print(f"agent: {a_tok} gen tok in {a_sec:.0f}s of request time, per-request tok/s ≈ {a_tps:.1f}")
print(f"user:  {u_tok} gen tok in {u_sec:.0f}s of request time, per-request tok/s ≈ {u_tps:.1f}")
print(f"steps avg {statistics.mean(steps):.1f} max {max(steps)}; last prompt tokens avg {statistics.mean(lp):.0f} max {max(lp)}")
print(f"finish_reason=length hits: {length_hits}")
print(f"估时 A（墙钟外推）: {est_a/3600:.1f} h   上限 ×1.5: {est_a*1.5/3600:.1f} h")
print(f"估时 B（token 口径）: {est_b/3600:.1f} h   上限 ×1.5: {est_b*1.5/3600:.1f} h")
