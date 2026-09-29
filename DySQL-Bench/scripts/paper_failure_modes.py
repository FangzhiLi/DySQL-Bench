#!/usr/bin/env python3
"""Measure the failure modes named in the DySQL-Bench paper (arXiv 2510.26495, sec. VI-D..F)
on our result dirs, so our numbers can be set next to theirs.
Usage: python scripts/paper_failure_modes.py results/<run_dir> [results/<run_dir> ...]
Per run: rate of each mode over all runs, pass rate with / without it, share of fails that carry it."""
import json, glob, re, sys, statistics
from collections import Counter

BLOCK = re.compile(r"```sql(.*?)```|<sql>(.*?)</sql>", re.DOTALL)
# paper VI-D: an SQL block immediately followed by <result> in the agent's own message
SQL_THEN_RESULT = re.compile(r"(?:```sql.*?```|<sql>.*?</sql>)\s*<result>", re.DOTALL)
REFUSE = re.compile(r"(unable|not able|cannot|can't|can not|couldn't|could not)\s+(to\s+)?"
                    r"(verify|proceed|authenticate|confirm your identity|locate your|find your|assist)", re.I)
ESCALATE = re.compile(r"human agent|transfer you|escalat", re.I)
AUTH = re.compile(r"authenticat|verify (your|the user|user)|identity|user table", re.I)
RESULT = re.compile(r"<result>(.*?)(?:</result>|$)", re.DOTALL)
SQL_BODY = re.compile(r"^\s*(SELECT|UPDATE|INSERT|DELETE|WITH|```sql)\b", re.I)  # <result> misused as an SQL wrapper
TOK = re.compile(r"[A-Za-z0-9][A-Za-z0-9.@:\-]*")
NUM = re.compile(r"(?<![\w.])\d{2,}(?![\w.])")
EMPTY_WORDS = {"no", "rows", "none", "empty", "result", "results", "found"}
WRITE = ("UPDATE", "INSERT", "DELETE")

def load(d):
    rs = []
    for f in sorted(glob.glob(d + "/*.json")):
        if not f.endswith("config.json"): rs += json.load(open(f))
    return [r for r in rs if "n_steps" in r["meta"]]  # drop traj_lost records

def repeated_line(c, min_len=40, times=3):
    lines = [l.strip() for l in c.splitlines() if len(l.strip()) >= min_len]
    return any(v >= times for v in Counter(lines).values())

def vals(s): return set(t.lower().rstrip(".") for t in TOK.findall(s))

def wrong_fabricated_read(T, i):
    """Agent message T[i] runs one SQL block and writes its own <result>; env's real result is T[i+1].
    True when the fabricated values do not cover the real ones (or invent rows for an empty result)."""
    c = T[i].get("content") or ""; b = BLOCK.search(c)
    if not (b and c[b.end():].lstrip().startswith("<result>")) or i + 1 >= len(T) or T[i + 1].get("name") != "sql": return False
    fab = RESULT.findall(c)[0]; real = (RESULT.findall(T[i + 1].get("content") or "") or [""])[0]
    if SQL_BODY.search(fab) or "Successfully" in real or real.startswith("Error"): return False
    if real.strip() in ("[]", ""): return bool(vals(fab) - EMPTY_WORDS)
    return not vals(real) <= vals(fab)

def flags(r):
    T = r["traj"]; A = [m.get("content") or "" for m in T if m["role"] == "assistant"]
    gold_w = any(t in (r["meta"].get("crud_types") or []) for t in WRITE)
    agent_w = [s["sql"] for s in r["sql_log"] if s["phase"] == "agent" and s["type"] in WRITE and not s["error"]]
    bodies = [b for a in A for b in RESULT.findall(a)]
    norm = [re.sub(r"\s+", " ", a).strip() for a in A]
    f = set()
    if any(SQL_THEN_RESULT.search(a) for a in A): f.add("halluc_paper_def")
    if any(SQL_BODY.search(b) for b in bodies): f.add("result_tag_as_sql_wrapper")
    if any(b.strip() and not SQL_BODY.search(b) for b in bodies): f.add("fabricated_result_data")
    if any(m["role"] == "assistant" and wrong_fabricated_read(T, i) for i, m in enumerate(T)): f.add("fabricated_read_value_wrong")
    real_nums = set(NUM.findall(" ".join(m.get("content") or "" for m in T if m["role"] == "user")))
    fab_nums = {x for b in bodies if not SQL_BODY.search(b) for x in NUM.findall(b)} - real_nums
    if any(set(NUM.findall(re.sub(r"--[^\n]*", "", w))) & fab_nums for w in agent_w): f.add("fabricated_number_written")
    if any(repeated_line(a) for a in A): f.add("repeat_within_msg")
    if any(norm[i] and norm[i] == norm[i + 1] == norm[i + 2] for i in range(len(norm) - 2)): f.add("repeat_3_same_msgs")
    if r["meta"]["termination"] != "user_stop": f.add("abnormal_term:" + r["meta"]["termination"])
    if gold_w and not agent_w:
        if any(REFUSE.search(a) for a in A): f.add("gave_up:refuse_no_write")
        if any(ESCALATE.search(a) for a in A): f.add("gave_up:escalate_no_write")
        if any((REFUSE.search(a) or ESCALATE.search(a)) and AUTH.search(a) for a in A): f.add("gave_up:auth_no_write")
    return f

def pct(a, b): return f"{100 * a / b:5.1f}%" if b else "   - "

def report(d):
    rs = load(d); n = len(rs); P = [r for r in rs if r["reward"] >= 1]; F = [r for r in rs if r["reward"] < 1]
    fl = {id(r): flags(r) for r in rs}
    print(f"\n### {d.rstrip('/').split('/')[-1]}  n={n}  pass^1={pct(len(P), n)}")
    print(f"{'mode':34s} {'runs':>5s} {'rate':>7s} {'pass|mode':>9s} {'pass|~mode':>10s} {'%fails':>7s}")
    keys = sorted(set().union(*fl.values()))
    for k in keys:
        w = [r for r in rs if k in fl[id(r)]]; wo = [r for r in rs if k not in fl[id(r)]]
        print(f"{k:34s} {len(w):5d} {pct(len(w), n):>7s} {pct(sum(r['reward'] >= 1 for r in w), len(w)):>9s} "
              f"{pct(sum(r['reward'] >= 1 for r in wo), len(wo)):>10s} {pct(sum(k in fl[id(r)] for r in F), len(F)):>7s}")
    # paper VI-E: dialogue length and SQL-error counts
    tok = lambda xs: sorted(r["meta"]["agent_completion_tokens"] for r in xs)
    q = lambda xs, p: xs[min(len(xs) - 1, int(p * len(xs)))] if xs else 0
    for lab, xs in (("pass", tok(P)), ("fail", tok(F))):
        print(f"agent tokens {lab}: p20={q(xs, .2)} median={q(xs, .5)} p80={q(xs, .8)} max={xs[-1] if xs else 0}")
    by_err = Counter(); by_err_pass = Counter()
    for r in rs:
        e = min(r["meta"]["n_sql_errors"], 3); by_err[e] += 1; by_err_pass[e] += r["reward"] >= 1
    print("sql errors per run -> share of runs / pass rate: " + "  ".join(
        f"{'3+' if e == 3 else e}: {pct(by_err[e], n).strip()} / {pct(by_err_pass[e], by_err[e]).strip()}" for e in sorted(by_err)))

for d in sys.argv[1:]: report(d)
