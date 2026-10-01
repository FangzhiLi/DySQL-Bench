# tests/test_taskgen_check_diff.py
import importlib.util, os
from taskgen_common.testing import make_db
from v2_fixtures import SHOP2, FKS, CUSTOMER, STAFF, SHOP_PROFILE
from taskgen_v2 import io

_P = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "check_diff.py")
_S = importlib.util.spec_from_file_location("check_diff", _P)
cd = importlib.util.module_from_spec(_S); _S.loader.exec_module(cd)


def r(ok, reasons=(), t="1_self"):
    return {"ok": ok, "reasons": list(reasons), "task_type": t}


def test_section_counts_transitions_and_groups_the_changes():
    pairs = [("a", r(True), r(True)),
             ("b", r(True), r(False, ["nondeterministic: rental"])),
             ("c", r(False, ["literal_missing: '100' in INSERT orders"]), r(True)),
             ("d", r(False, ["noop_write: UPDATE t"]), r(False, ["noop_write: UPDATE t", "literal_missing: 'x' in UPDATE t"])),
             ("e", r(True, t="4_other_person"), r(True, t="3_public_only"))]
    text = "\n".join(cd.section("demo", pairs))
    for row in ("| 通过 | 通过 | 2 |", "| 通过 | 拒绝 | 1 |", "| 拒绝 | 通过 | 1 |", "| 拒绝 | 拒绝 | 1 |"):
        assert row in text, row
    assert "- 通过 → 拒绝：nondeterministic（1）：b" in text
    assert "- 拒绝 → 通过：v1 的原因 literal_missing（1）：c" in text
    assert "- 仍拒绝、原因变了：noop_write → literal_missing+noop_write（1）：d" in text
    assert "- 4_other_person → 3_public_only：1" in text


def test_profile_pairs_compare_root_speakers_only(tmp_path):
    rec = {"source": "test", "db": "shop2", "path": make_db(tmp_path, "shop2", SHOP2), "anchors": [CUSTOMER, STAFF], "fks": FKS}
    def c(cid, table, kv, ins, sql):
        return {"id": cid, "anchor_table": table, "key_value": kv, "plan": {"task_type": "1_self"}, "instruction": ins, "actions": [{"sql": sql}]}
    io.append_jsonl(tmp_path / "res" / "shop2" / "candidates.jsonl",
                    [c("own", "customers", 5, "I am a5 b5. Set qty of my order 5 to 3.", "UPDATE orders SET qty = 3 WHERE order_id = 5"),
                     c("theirs", "customers", 5, "I am a5 b5. Set qty of order 9 to 3.", "UPDATE orders SET qty = 3 WHERE order_id = 9"),
                     c("staff", "staff", 2, "I am s2. Rename me to Zed.", "UPDATE staff SET name = 'Zed' WHERE staff_id = 2")])
    pairs = cd.profile_pairs(str(tmp_path / "res"), {"test:shop2": rec}, {"test:shop2": SHOP_PROFILE})
    assert [(cid, o["ok"], n["ok"]) for cid, o, n in pairs] == [("own", True, True), ("theirs", True, False)]
    assert pairs[1][2]["reasons"] == ["other_person"]
    assert cd.profile_pairs(str(tmp_path / "res"), {"test:shop2": rec}, {"test:shop2": {**SHOP_PROFILE, "confirmed": False}}) == []
    edited = {**SHOP_PROFILE, "quirks": ["qty is never 0."]}   # changed after it was confirmed
    assert cd.profile_pairs(str(tmp_path / "res"), {"test:shop2": rec}, {"test:shop2": edited}) == []
    text = "\n".join(cd.section("demo", pairs, "不用档案", "用档案"))
    assert "| 不用档案 | 用档案 | 条数 |" in text and "- 通过 → 拒绝：other_person（1）：theirs" in text
