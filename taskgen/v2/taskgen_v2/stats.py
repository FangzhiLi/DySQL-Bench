# taskgen/v2/taskgen_v2/stats.py
"""Pilot acceptance numbers (spec §10) from the step files of one database."""
from collections import Counter


def _majority(votes):
    votes = [v for v in votes if "error" not in v]
    y = sum(v["verdict"] == "yes" for v in votes)
    return y > len(votes) - y


def summarize(cands, checks, verifies, selected):
    chk = {c["id"]: c for c in checks}
    ver = {v["id"]: v for v in verifies}
    passed = [c for c in cands if chk.get(c["id"], {}).get("ok")]
    d = {"n_candidates": len(cands), "n_parse_error": sum(1 for c in cands if not c.get("instruction")),
         "n_check_pass": len(passed), "check_reasons": Counter(x.split(":")[0] for c in checks for x in c["reasons"]),
         "n_verify_pass": sum(1 for v in verifies if v["pass"]), "n_selected": len(selected)}
    good = [chk[c["id"]] for c in passed]
    d["type_mix"] = dict(Counter(g["task_type"] for g in good))
    d["difficulty_mix"] = dict(Counter(g["difficulty"]["level"] for g in good))
    tmpl = Counter(g["template"] for g in good)
    d["templates"] = len(tmpl)
    d["top1_share"] = (tmpl.most_common(1)[0][1] / len(good)) if good else 0.0
    per_person = Counter((c["anchor_table"], str(c["key_value"])) for c in passed)
    d["per_person_mean"] = (sum(per_person.values()) / len(per_person)) if per_person else 0.0
    f = [g["difficulty"]["features"] for g in good]
    d["patterns"] = {"multi_write": sum(x["multi_write"] for x in f), "subquery": sum(x["subquery"] for x in f),
                     "archive": sum(x["archive"] for x in f), "public": sum(x["public_or_other"] for x in f)}
    five = [v for v in verifies if len(v["votes"]) >= 5]
    d["vote_agreement"] = (sum(_majority(v["votes"][:3]) != _majority(v["votes"][:5]) for v in five) / len(five)) if five else None
    d["unanimous_share"] = (sum(len({x["verdict"] for x in v["votes"]}) == 1 for v in verifies) / len(verifies)) if verifies else None
    return d


def render(d):
    rows = [("n_candidates", d["n_candidates"]), ("n_parse_error", d["n_parse_error"]), ("n_check_pass", d["n_check_pass"]),
            ("check_reasons", ", ".join(f"{k} {v}" for k, v in d["check_reasons"].most_common())),
            ("n_verify_pass", d["n_verify_pass"]), ("n_selected", d["n_selected"]),
            ("type_mix", d["type_mix"]), ("difficulty_mix", d["difficulty_mix"]), ("templates", d["templates"]),
            ("top1_share", f"{d['top1_share']:.2f}"), ("per_person_mean", f"{d['per_person_mean']:.2f}"),
            ("patterns", d["patterns"]),
            ("vote_agreement (3 vs 5 votes disagree)", "n/a" if d["vote_agreement"] is None else f"{d['vote_agreement']:.2f}"),
            ("unanimous_share", "n/a" if d["unanimous_share"] is None else f"{d['unanimous_share']:.2f}")]
    return "| metric | value |\n|---|---|\n" + "\n".join(f"| {k} | {v} |" for k, v in rows)
