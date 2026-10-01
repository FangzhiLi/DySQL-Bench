# tests/test_taskgen_check_diff.py
import importlib.util, os

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
