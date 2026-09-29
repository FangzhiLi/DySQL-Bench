# tests/test_taskgen_stats.py
from dysql_bench.taskgen import stats

def c(i, t="1_self", lvl="easy", tmpl="1_self|UPDATE orders", person=1, feats=None):
    return ({"id": f"x:{i}", "anchor_table": "customers", "key_value": person, "instruction": "i", "plan": {"task_type": t}},
            {"id": f"x:{i}", "ok": True, "reasons": [], "task_type": t, "template": tmpl,
             "difficulty": {"level": lvl, "features": feats or {"multi_write": False, "subquery": False, "archive": False, "public_or_other": False}}})

def test_summarize_counts_and_ratios():
    pairs = [c(0), c(1, person=2), c(2, "5_proxy", "hard", "5_proxy|DELETE orders+UPDATE orders", 3, {"multi_write": True, "subquery": True, "archive": False, "public_or_other": False})]
    cands, checks = [p[0] for p in pairs], [p[1] for p in pairs]
    cands.append({"id": "x:9", "instruction": None, "error": "ParseError: x", "plan": {"task_type": "1_self"}, "anchor_table": "customers", "key_value": 9})
    checks.append({"id": "x:9", "ok": False, "reasons": ["no_instruction"], "task_type": None, "template": None, "difficulty": None})
    verifies = [{"id": "x:0", "votes": [{"verdict": v} for v in "yes yes no yes no".split()], "pass": True},
                {"id": "x:1", "votes": [{"verdict": v} for v in "no no yes yes yes".split()], "pass": True},
                {"id": "x:2", "votes": [{"verdict": "no"}] * 5, "pass": False}]
    d = stats.summarize(cands, checks, verifies, [cands[0], cands[1]])
    assert d["n_candidates"] == 4 and d["n_parse_error"] == 1 and d["n_check_pass"] == 3 and d["n_verify_pass"] == 2 and d["n_selected"] == 2
    assert d["type_mix"] == {"1_self": 2, "5_proxy": 1} and d["difficulty_mix"] == {"easy": 2, "hard": 1}
    assert d["templates"] == 2 and abs(d["top1_share"] - 2 / 3) < 1e-9 and d["per_person_mean"] == 1.0
    assert d["patterns"] == {"multi_write": 1, "subquery": 1, "archive": 0, "public": 0}
    assert abs(d["vote_agreement"] - 1 / 3) < 1e-9 and abs(d["unanimous_share"] - 1 / 3) < 1e-9   # x:1 flips between 3 and 5 votes
    assert "top1_share" in stats.render(d)
