# taskgen/v2/taskgen_v2/metrics.py
"""Task-set metrics for comparing a generated set with DySQL-Bench (design §3). A record is
{"db", "instruction", "actions": [{"sql"}], "type", "difficulty", "writes", "template"}; the last four come from the
execution check (writes is empty or None when the check produced no write). from_results reads a results folder
(<db>/candidates.jsonl + <db>/check.jsonl), from_dysql DySQL's own gold tasks."""
import glob, os, re, statistics as st
from collections import Counter
from taskgen_v2 import check, dysql, io

# "before you change anything, tell me what ... currently ..." -- a read-only request the reward never checks
ASK = re.compile(r"before (you|we|any|making|touching|applying)|can you (tell|confirm|let me know|report)|"
                 r"(tell|let) me (what|which|the)|what .{0,40}(currently|on file|right now)|report back|confirm (the|what|which)", re.I)
# an identifier the speaker hands over: 'id 129924', 'player_api_id', 'CustomerID', 'my email', '@', 'SSN', '#575041'
ID_RE = re.compile(r"(?i:\bids?\b|_id\b|\bssn\b|\be-?mail\b|@|#\s?\d)|[a-z]I[Dd]\b")
SUBQ = re.compile(r"\(\s*select\b", re.I)
TYPES = ("1_self", "2_self_and_public", "3_public_only", "4_other_person", "5_proxy", "6_entity")


def statements(rec):
    return [s for a in rec["actions"] for s in check.split_statements(a["sql"])]


def write_count(rec):
    return sum(1 for s in statements(rec) if check.write_target(s))


def _pct(n, d):
    return f"{100 * n / d:.1f}%" if d else "-"


def _q(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p * len(xs)))]


def compute(recs):
    if not recs:
        return {"tasks": "0"}
    m, n = {}, len(recs)
    m["tasks"] = str(n)
    wc = [write_count(r) for r in recs]
    c = Counter(min(x, 5) for x in wc)
    m["write statements 0/1/2/3/4/≥5"] = " / ".join(_pct(c[i], n) for i in range(6))
    m["write statements mean / median"] = f"{st.mean(wc):.2f} / {st.median(wc):g}"
    m["≥3 write statements"] = _pct(sum(x >= 3 for x in wc), n)
    stm = [s for r in recs for s in statements(r)]
    m["statements with a subquery"] = _pct(sum(bool(SUBQ.search(s)) for s in stm), len(stm))
    w = [len(r["instruction"].split()) for r in recs]
    m["instruction words mean / median / p90"] = f"{st.mean(w):.0f} / {st.median(w):g} / {_q(w, .9)}"
    m["read-only ask"] = _pct(sum(bool(ASK.search(r["instruction"])) for r in recs), n)
    m["ID/email in first 25 words"] = _pct(sum(bool(ID_RE.search(" ".join(r["instruction"].split()[:25]))) for r in recs), n)
    lab = [r for r in recs if r.get("writes")]
    k = len(lab)
    ty = Counter(r["type"] for r in lab)
    m["type 1/2/3/4/5/6/other"] = " / ".join(_pct(ty[t], k) for t in TYPES) + " / " + _pct(k - sum(ty[t] for t in TYPES), k)
    lv = Counter(r["difficulty"]["level"] for r in lab if r.get("difficulty"))
    m["difficulty easy/medium/hard"] = " / ".join(_pct(lv[x], k) for x in ("easy", "medium", "hard"))
    m["≥2 tables written"] = _pct(sum(len({x["table"] for x in r["writes"]}) >= 2 for r in lab), k)
    m[">10 rows changed"] = _pct(sum(sum(x["rows"] for x in r["writes"]) > 10 for r in lab), k)
    tpl = Counter(r["template"] for r in lab if r.get("template"))
    m["templates / largest share"] = f"{len(tpl)} / {_pct(tpl.most_common(1)[0][1], k)}" if tpl else "0 / -"
    return m


def render(cols):
    names = list(cols)
    keys = list(dict.fromkeys(k for c in cols.values() for k in c))
    out = ["| metric | " + " | ".join(names) + " |", "|" + "---|" * (len(names) + 1)]
    out += [f"| {k} | " + " | ".join(cols[c].get(k, "") for c in names) + " |" for k in keys]
    return "\n".join(out)


def from_results(results_dir):
    """Check-passed candidates of every database folder under results_dir."""
    if not os.path.isdir(results_dir):
        raise FileNotFoundError(results_dir)
    recs = []
    for f in sorted(glob.glob(os.path.join(results_dir, "*", "check.jsonl"))):
        d = os.path.dirname(f)
        chk = {r["id"]: r for r in io.read_jsonl(f)}
        for c in io.read_jsonl(os.path.join(d, "candidates.jsonl")):
            r = chk.get(c["id"])
            if r and r["ok"] and c.get("instruction"):
                recs.append({"db": os.path.basename(d), "instruction": c["instruction"], "actions": c["actions"],
                             "type": r["task_type"], "difficulty": r["difficulty"], "writes": r["writes"], "template": r["template"]})
    return recs


def from_dysql(cache_path, envs=None):
    """All DySQL gold tasks, labelled by this version's check. The type comes from the DySQL classifier
    (taskgen/common/data/dysql_task_types.csv): its own/other tracing is the reference (design D6). Cached: delete
    the cache after the check changes."""
    if os.path.exists(cache_path):
        return io.read_jsonl(cache_path)
    recs = []
    for env in envs or dysql.ENVS:
        rec = dysql.db_rec(env)
        for c in dysql.candidates(env):
            r = check.run_check_safe(rec, c)
            recs.append({"db": env, "instruction": c["instruction"], "actions": c["actions"], "type": c["group"],
                         "difficulty": r["difficulty"], "writes": r["writes"], "template": r["template"]})
    io.append_jsonl(cache_path, recs)
    return recs
