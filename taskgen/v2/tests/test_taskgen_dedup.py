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


def test_per_db_cap_and_determinism():
    recs = [rec(i, i, f"t{i % 7}") for i in range(100)]
    a = dedup.select(recs, random.Random(1), per_db=20)
    b = dedup.select(recs, random.Random(1), per_db=20)
    assert len(a) == 20 and [r["id"] for r in a] == [r["id"] for r in b]
