#!/usr/bin/env python3
"""The verifier's calibration (design §4.6, D5), one sub-command per step; files under --dir (results/, not git).
Usage (from taskgen/v2/):
  P=~/miniconda3/envs/dysql/bin/python; D=results/plan4/calib
  $P scripts/verify_calibrate.py build  --dir $D --labeled results/plan4/fresh --positives 300 --per-kind-dysql 30 --per-kind-v2 30
  $P scripts/verify_calibrate.py vote   --dir $D --models deepseek-v4.1-flash:2   # votes.jsonl, resumable
  $P scripts/verify_calibrate.py vote   --dir $D --models deepseek-v4.1-flash:3 --undecided   # a third vote where two split
  $P scripts/verify_calibrate.py sheet  --dir $D                                  # label_sheet.md for Claude
  $P scripts/verify_calibrate.py review --dir $D                                  # review.md for the user
  $P scripts/verify_calibrate.py report --dir $D                                  # report.md
labels.jsonl holds one row per labeled item: {"id", "label": "good"|"bad", "reason": one of calibrate.REASONS or
null, "unsure": bool, "note", "by": "claude"|"user"}; a later row for an id replaces an earlier one."""
import argparse, json, os, random, sys, time
V2 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [V2, os.path.join(os.path.dirname(V2), "common")]   # taskgen_v2, taskgen_common
from taskgen_v2 import calibrate, check, corrupt, io, verify
from taskgen_common.db_select import _q


def load(d):
    items = io.read_jsonl(os.path.join(d, "items.jsonl"))
    votes = {r["id"]: r for r in io.read_jsonl(os.path.join(d, "votes.jsonl"))}
    labels = calibrate.final_labels(io.read_jsonl(os.path.join(d, "labels.jsonl")))
    return items, votes, labels


def cmd_build(a):
    path = os.path.join(a.dir, "items.jsonl")
    if os.path.exists(path):
        sys.exit(f"{path} exists: the sets are built once, so votes and labels keep pointing at the same items")
    os.makedirs(a.dir, exist_ok=True)
    dbs = calibrate.Databases()
    gold = calibrate.positives()
    lab = calibrate.v2_items(a.labeled)
    neg = (calibrate.negatives(gold, dbs, a.per_kind_dysql, random.Random(a.seed), "dysql")
           + calibrate.negatives(lab, dbs, a.per_kind_v2, random.Random(a.seed), "v2"))
    keep = set(map(id, random.Random(a.seed).sample(gold, min(a.positives, len(gold))))) if a.positives else set(map(id, gold))
    pos = [g for g in gold if id(g) in keep]   # a sample keeps the Ollama plan's calls down; negatives use all gold
    io.append_jsonl(path, pos + neg + lab)
    print(json.dumps(calibrate.counts(pos + neg + lab), indent=1))


def cmd_vote(a):
    items, votes, _ = load(a.dir)
    if a.set:
        items = [i for i in items if i["set"] in a.set]
    if a.undecided:   # only where the votes so far leave a rule open: two each, a third when they split
        items = calibrate.undecided(items, votes)
    dbs = calibrate.Databases()
    t0 = time.time()
    s = verify.run(items, verify.models_from_env(a.models), os.path.join(a.dir, "votes.jsonl"), workers=a.workers,
                   context=dbs.context)
    print(f"{s} in {time.time() - t0:.0f}s")


def effect(path, stmts):
    """What the statements change, table by table: rows removed (-) and added (+) with column names."""
    st = check.final_state(path, stmts)
    if st is None:
        return ["(a statement fails)"]
    db = check._memory_copy(path)
    out = []
    for t, (added, removed) in st.items():
        cols = [r[1] for r in db.execute(f"PRAGMA table_info({_q(t)})") if not check.VOLATILE_COL_RE.match(r[1])]
        for sign, rows in (("-", removed), ("+", added)):
            out += [f"{sign} {t}: " + json.dumps(dict(zip(cols, r[:len(cols)])), ensure_ascii=False, default=str)[:400]
                    for r in rows[:6]]
            if len(rows) > 6:
                out.append(f"{sign} {t}: ... {len(rows) - 6} more rows")
    db.close()
    return out


def block(i, dbs, n):
    d = dbs.get(i["db"])
    chk = dbs.check(i)
    lines = [f"## {n}. {i['id']}", f"type {chk['task_type']} | template {chk['template']}", "", "**Instruction:** " + i["instruction"], "",
             "**SQL:**", "```sql", *corrupt.statements(i), "```", "", "**Effect:**", "```", *effect(d["path"], corrupt.statements(i)), "```"]
    return lines


def cmd_sheet(a):
    items, _, _ = load(a.dir)
    dbs = calibrate.Databases()
    lab = [i for i in items if i["set"] == "labeled"]
    lines = [f"# Label sheet: {len(lab)} v2 candidates", "",
             "Label each: good, or bad with a reason (" + ", ".join(calibrate.REASONS) + "). Good means an agent that sees "
             "only the instruction and can query the database ends in the same database state as the SQL.", ""]
    for n, i in enumerate(lab, 1):
        lines += block(i, dbs, n) + [""]
    with open(os.path.join(a.dir, "label_sheet.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"wrote label_sheet.md: {len(lab)} items")


def cmd_review(a):
    items, votes, labels = load(a.dir)
    dbs = calibrate.Databases()
    show = calibrate.disagreements([i for i in items if i["set"] == "labeled"], votes, labels)
    lines = [f"# 需要你复核的 {len(show)} 条", "",
             "每条给出 Claude 的判断和校验模型的 3 票。请对每条回复 good 或 bad（bad 附原因）。", ""]
    for n, i in enumerate(show, 1):
        lab, v = labels[i["id"]], votes.get(i["id"], {})
        real = [x for x in v.get("votes", []) if "error" not in x]
        no = next((x for x in real if x["verdict"] != "yes"), None)
        lines += block(i, dbs, n) + [
            "", f"**Claude:** {lab['label']}" + (f" ({lab['reason']})" if lab.get("reason") else "")
            + (" — 拿不准" if lab.get("unsure") else "") + (f" — {lab['note']}" if lab.get("note") else ""),
            f"**校验模型:** " + " / ".join(x["verdict"] for x in real)]
        if no:
            lines += ["", "> " + no["content"][-700:].replace("\n", "\n> ")]
        lines.append("")
    with open(os.path.join(a.dir, "review.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"wrote review.md: {len(show)} items")


def pct(r):
    return "-" if r[0] is None else f"{100 * r[0]:.1f}% ({r[1]}/{r[2]})"


def cmd_report(a):
    items, votes, labels = load(a.dir)
    m = calibrate.metrics(items, votes, labels)
    rules = list(calibrate.RULES)
    lines = ["| | " + " | ".join(rules) + " |", "|---|" + "---|" * len(rules)]
    lines.append("| 正样本通过 | " + " | ".join(pct(m[r]["positives_pass"]) for r in rules) + " |")
    lines.append("| 负样本被拒（全部） | " + " | ".join(pct(m[r]["negatives_reject"]) for r in rules) + " |")
    for key in sorted(m[rules[0]]["negatives_by_kind"]):
        lines.append(f"| 负样本被拒 {key[0]} {key[1]} | " + " | ".join(pct(m[r]["negatives_by_kind"][key]) for r in rules) + " |")
    lines.append("| 标注集 好题通过 | " + " | ".join(pct(m[r]["labeled_good_pass"]) for r in rules) + " |")
    lines.append("| 标注集 坏题被拒（召回） | " + " | ".join(pct(m[r]["labeled_bad_reject"]) for r in rules) + " |")
    lines.append("| 标注集 被拒的是坏题（精度） | " + " | ".join(pct(m[r]["labeled_precision"]) for r in rules) + " |")
    allv = [x for r in votes.values() for x in r["votes"]]
    trunc = sum(x.get("error", "").startswith("Truncated") for x in allv)
    short = len(calibrate.undecided(items, votes))
    lines += ["", f"票数 {len(allv)}；思考被截断的 {trunc}；其它失败 {sum('error' in x for x in allv) - trunc}；"
              f"还判不了的条目 {short}；标注 {len(labels)} 条（用户复核 {sum(r.get('by') == 'user' for r in labels.values())}）。",
              "", f"按 calibrate.choose_rule 选出的规则：{calibrate.choose_rule(m) or '没有规则同时满足两条 95%'}"]
    text = "\n".join(lines)
    with open(os.path.join(a.dir, "report.md"), "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print(text)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("build"); p.add_argument("--dir", required=True); p.add_argument("--labeled", action="append", required=True)
    p.add_argument("--per-kind-dysql", type=int, default=60); p.add_argument("--per-kind-v2", type=int, default=40)
    p.add_argument("--positives", type=int, help="a random sample of this many DySQL gold (default: all)")
    p.add_argument("--seed", type=int, default=0); p.set_defaults(f=cmd_build)
    p = sub.add_parser("vote"); p.add_argument("--dir", required=True); p.add_argument("--models", required=True)
    p.add_argument("--set", action="append", help="positives / negatives / labeled (default: all)")
    p.add_argument("--undecided", action="store_true", help="only items some rule cannot judge yet")
    p.add_argument("--workers", type=int, default=3, help="Ollama Pro plan limit: 3 concurrent requests"); p.set_defaults(f=cmd_vote)
    for name, f in (("sheet", cmd_sheet), ("review", cmd_review), ("report", cmd_report)):
        p = sub.add_parser(name); p.add_argument("--dir", required=True); p.set_defaults(f=f)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
