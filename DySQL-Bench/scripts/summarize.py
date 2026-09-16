#!/usr/bin/env python3
"""Summarize DySQL-Bench result JSONs into pass^k and analysis stats.
Usage: python scripts/summarize.py results/full/*.json > docs/results/<date>.md
"""
import argparse, glob, json, statistics
from collections import Counter, defaultdict
from math import comb


def _mean(vals):
    vals = list(vals)
    return statistics.mean(vals) if vals else 0.0


def _group_stats(rs):
    by_task = defaultdict(list)
    for r in rs:
        by_task[r["task_id"]].append(1 if abs(r["reward"] - 1) < 1e-6 else 0)
    n_trials = max(len(v) for v in by_task.values())
    pk = {}
    for k in range(1, n_trials + 1):
        vals = [comb(sum(v), k) / comb(len(v), k) for v in by_task.values() if len(v) >= k]
        pk[k] = sum(vals) / len(vals) if vals else 0.0
    metas = [r.get("meta", {}) for r in rs]
    tables = Counter(t for m in metas for t in m.get("mismatched_tables", []))
    writes = [m.get("confirmed_before_write") for m in metas if m.get("confirmed_before_write") is not None]
    lp = [m["last_prompt_tokens"] for m in metas if m.get("last_prompt_tokens")]
    return {"n_tasks": len(by_task), "n_runs": len(rs), "pass_hat_k": pk,
            "avg_steps": _mean(m.get("n_steps") or 0 for m in metas),
            "avg_wall_s": _mean(m.get("wall_s") or 0 for m in metas),
            "avg_agent_tokens": _mean(m.get("agent_completion_tokens") or 0 for m in metas),
            "avg_user_tokens": _mean(m.get("user_completion_tokens") or 0 for m in metas),
            "fabricated_rate": sum(1 for m in metas if (m.get("n_fabricated_results") or 0) > 0) / len(rs),
            "sql_error_rate": sum(1 for m in metas if (m.get("n_sql_errors") or 0) > 0) / len(rs),
            "multi_sql_rate": sum(1 for m in metas if (m.get("n_extra_sql_blocks") or 0) > 0) / len(rs),
            "zero_row_write_rate": sum(1 for m in metas if (m.get("n_zero_row_writes") or 0) > 0) / len(rs),
            "confirm_rate": (sum(1 for c in writes if c) / len(writes)) if writes else None,
            "last_prompt_p50": statistics.median(lp) if lp else None,
            "last_prompt_max": max(lp) if lp else None,
            "termination_counts": dict(Counter(m.get("termination") for m in metas)),
            "top_mismatched_tables": tables.most_common(5)}


def summarize(results):
    out = {"overall": _group_stats(results), "by_env": {}, "by_length": {}}
    for key, field in (("by_env", "env"), ("by_length", "length")):
        groups = defaultdict(list)
        for r in results:
            groups[r.get("meta", {}).get(field, "?")].append(r)
        out[key] = {g: _group_stats(v) for g, v in sorted(groups.items())}
    return out


def to_markdown(s):
    lines = ["| group | tasks | runs | pass^1 | pass^3 | pass^5 | steps | wall s | agent tok | user tok | fab rate | multi-sql | sql err | 0-row write | confirm | last prompt p50/max | terminations |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    def row(name, g):
        pk = g["pass_hat_k"]
        f = lambda k: f"{100*pk[k]:.2f}" if k in pk else "-"
        conf = "-" if g["confirm_rate"] is None else f"{100*g['confirm_rate']:.0f}%"
        return (f"| {name} | {g['n_tasks']} | {g['n_runs']} | {f(1)} | {f(3)} | {f(5)} | {g['avg_steps']:.1f} | "
                f"{g['avg_wall_s']:.0f} | {g['avg_agent_tokens']:.0f} | {g['avg_user_tokens']:.0f} | "
                f"{100*g['fabricated_rate']:.1f}% | {100*g['multi_sql_rate']:.1f}% | "
                f"{100*g['sql_error_rate']:.1f}% | {100*g['zero_row_write_rate']:.1f}% | "
                f"{conf} | "
                f"{g['last_prompt_p50']}/{g['last_prompt_max']} | {g['termination_counts']} |")
    lines.append(row("overall", s["overall"]))
    for k, g in s["by_length"].items():
        lines.append(row(k, g))
    for k, g in s["by_env"].items():
        lines.append(row(k, g))
    lines.append("")
    lines.append(f"Top mismatched tables: {s['overall']['top_mismatched_tables']}")
    return "\n".join(lines)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("paths", nargs="+")
    a = p.parse_args()
    results = [r for path in a.paths for f in sorted(glob.glob(path))
               if not f.endswith(".config.json") for r in json.load(open(f))]
    print(to_markdown(summarize(results)))
