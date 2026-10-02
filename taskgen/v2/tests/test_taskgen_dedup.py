# tests/test_taskgen_dedup.py
import random
from collections import Counter
from taskgen_v2 import dedup


def rec(i, person, template):
    return {"id": f"x:{i}", "anchor_table": "customers", "key_value": person, "template": template}


def test_caps_per_template_and_per_person():
    recs = [rec(i, i, "A") for i in range(40)] + [rec(100 + i, 999, "B") for i in range(5)] + [rec(200, 1, "C")]
    out = dedup.select(recs, random.Random(0))
    c = Counter(r["template"] for r in out)
    assert c["A"] == 15 and c["B"] == 2 and c["C"] == 1
    assert Counter(r["key_value"] for r in out)[999] == 2 and Counter(r["key_value"] for r in out)[1] <= 2


def test_rare_templates_are_kept_before_common_ones():
    recs = [rec(i, i, "common") for i in range(30)] + [rec(50 + i, 50 + i, f"rare{i}") for i in range(10)]
    out = dedup.select(recs, random.Random(0), per_db=12)
    assert sum(r["template"].startswith("rare") for r in out) == 10 and len(out) == 12


def test_precap_takes_checked_candidates_by_template_without_a_person_cap():
    cands = [{"id": f"x:{i}", "anchor_table": "customers", "key_value": 1} for i in range(40)]
    checks = [{"id": f"x:{i}", "ok": i != 0, "template": "A" if i < 30 else "B"} for i in range(40)]
    out = dedup.precap(cands, checks, random.Random(0), per_template=25, per_db=900)
    ids = {c["id"] for c in out}
    assert "x:0" not in ids and len(ids) == 35 and sum(1 for i in ids if int(i[2:]) < 30) == 25   # one person, 35 tasks
    assert len(dedup.precap(cands, checks, random.Random(0), per_template=25, per_db=12)) == 12
    assert [c["id"] for c in out] == [c["id"] for c in cands if c["id"] in ids]   # file order kept


def test_per_db_cap_and_determinism():
    recs = [rec(i, i, f"t{i % 7}") for i in range(100)]
    a = dedup.select(recs, random.Random(1), per_db=20)
    b = dedup.select(recs, random.Random(1), per_db=20)
    assert len(a) == 20 and [r["id"] for r in a] == [r["id"] for r in b]


def test_precap_draws_the_same_candidates_on_a_rerun():
    cands = [{"id": f"x:{i}", "anchor_table": "customers", "key_value": i} for i in range(60)]
    checks = [{"id": f"x:{i}", "ok": True, "template": f"t{i % 4}"} for i in range(60)]
    a = dedup.precap(cands, checks, random.Random(0), per_template=5, per_db=900)
    assert a == dedup.precap(cands, checks, random.Random(0), per_template=5, per_db=900) and len(a) == 20


def test_near_duplicate_instructions_keep_only_the_first():
    # design 4.7: within a database, instructions whose word 3-grams overlap by Jaccard >= 0.6 are one task
    base = "Hi, I am a5 b5, customer 5. Please set the quantity of my order 5 to 3 and leave everything else as it is."
    recs = [{"id": "x:0", "instruction": base},
            {"id": "x:1", "instruction": base.replace("to 3", "to 4")},            # one word apart: a near duplicate
            {"id": "x:2", "instruction": "It's a6 b6 (customer 6). Cancel order 66, the shipment never arrived."}]
    assert [r["id"] for r in dedup.near_duplicates(recs)] == ["x:0", "x:2"]
    assert len(dedup.near_duplicates(recs, threshold=1.01)) == 3
