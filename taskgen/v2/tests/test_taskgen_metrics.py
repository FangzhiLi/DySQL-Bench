# tests/test_taskgen_metrics.py
import os, subprocess, sys
import pytest
from taskgen_v2 import io, metrics

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "task_stats.py")


def rec(instruction, sqls, type_="1_self", level="easy", writes=(("orders", 1),), template="1_self|UPDATE orders"):
    return {"db": "shop", "instruction": instruction, "actions": [{"sql": s} for s in sqls], "type": type_,
            "difficulty": {"level": level}, "template": template,
            "writes": [{"op": "UPDATE", "table": t, "rows": n, "label": "own"} for t, n in writes]}


def results_dir(tmp_path):
    d = tmp_path / "res" / "shop"
    d.mkdir(parents=True)
    io.append_jsonl(str(d / "candidates.jsonl"), [
        {"id": "a", "instruction": "x", "actions": [{"sql": "UPDATE t SET v = 1"}]},
        {"id": "b", "instruction": "y", "actions": [{"sql": "UPDATE t SET v = 2"}]},
        {"id": "c", "instruction": None, "actions": None}])
    io.append_jsonl(str(d / "check.jsonl"), [
        {"id": "a", "ok": True, "reasons": [], "writes": [{"op": "UPDATE", "table": "t", "rows": 1, "label": "own"}],
         "task_type": "1_self", "template": "1_self|UPDATE t", "difficulty": {"level": "easy"}},
        {"id": "b", "ok": False, "reasons": ["noop_write: UPDATE t"], "writes": [], "task_type": None, "template": None, "difficulty": None},
        {"id": "c", "ok": False, "reasons": ["no_instruction"], "writes": [], "task_type": None, "template": None, "difficulty": None}])
    return tmp_path / "res"


def test_write_statements_are_counted_per_statement_not_per_action():
    r = rec("x", ["SELECT 1", "UPDATE a SET b = 1; DELETE FROM a WHERE b = 2", "INSERT INTO a VALUES (1)"])
    assert metrics.write_count(r) == 3


def test_compute_on_a_small_set():
    recs = [rec("Hi, I'm Ann (CustomerID 5). Before you change anything, tell me what my balance is.", ["UPDATE a SET b = 1"]),
            rec("I am Bo, bo@x.com. Set my qty to 3.", ["UPDATE a SET b = 1", "UPDATE c SET d = (SELECT 1)", "DELETE FROM a WHERE b = 1"],
                type_="2_self_and_public", level="hard", writes=(("a", 12), ("c", 1)), template="t2"),
            rec("Change my order please, it was paid.", ["UPDATE a SET b = 1", "UPDATE a SET b = 2"], type_="5_proxy", level="medium")]
    m = metrics.compute(recs)
    assert m["tasks"] == "3"
    assert m["write statements 0/1/2/3/4/≥5"] == "0.0% / 33.3% / 33.3% / 33.3% / 0.0% / 0.0%"
    assert m["write statements mean / median"] == "2.00 / 2"
    assert m["≥3 write statements"] == "33.3%"
    assert m["statements with a subquery"] == "16.7%"
    assert m["read-only ask"] == "33.3%"
    assert m["ID/email in first 25 words"] == "66.7%"            # 'CustomerID' and an email; 'paid' is not an ID
    assert m["type 1/2/3/4/5/6/other"] == "33.3% / 33.3% / 0.0% / 0.0% / 33.3% / 0.0% / 0.0%"
    assert m["difficulty easy/medium/hard"] == "33.3% / 33.3% / 33.3%"
    assert m["≥2 tables written"] == "33.3%" and m[">10 rows changed"] == "33.3%"
    assert m["templates / largest share"] == "2 / 66.7%"


def test_empty_sets_unlabelled_tasks_and_missing_folders():
    assert metrics.compute([]) == {"tasks": "0"}
    m = metrics.compute([{**rec("x", ["UPDATE a SET b = 1"]), "writes": None}])     # nothing labelled by the check
    assert m["type 1/2/3/4/5/6/other"] == "- / - / - / - / - / - / -" and m["templates / largest share"] == "0 / -"
    with pytest.raises(FileNotFoundError):
        metrics.from_results("/nonexistent/results")


def test_from_results_keeps_checked_candidates_only(tmp_path):
    recs = metrics.from_results(str(results_dir(tmp_path)))
    assert [r["instruction"] for r in recs] == ["x"] and recs[0]["db"] == "shop" and recs[0]["type"] == "1_self"


def test_from_dysql_labels_with_the_check_and_types_with_the_classifier(tmp_path):
    cache = str(tmp_path / "dysql.jsonl")
    recs = metrics.from_dysql(cache, envs=("music",))
    assert len(recs) == 21 and {r["db"] for r in recs} == {"music"}
    assert {r["type"] for r in recs} <= {"1_self", "2_self_and_public", "3_public_only", "4_other_person", "5_proxy",
                                          "6_entity", "7_no_change"}
    assert sum(bool(r["writes"]) for r in recs) >= 18
    assert metrics.from_dysql(cache, envs=("music",)) == recs      # the second call reads the cache


def test_render_puts_sets_side_by_side():
    text = metrics.render({"DySQL": metrics.compute([rec("x", ["UPDATE a SET b = 1"])]), "v2": {"tasks": "0"}})
    lines = text.splitlines()
    assert lines[:2] == ["| metric | DySQL | v2 |", "|---|---|---|"]
    assert "| tasks | 1 | 0 |" in lines and "| read-only ask | 0.0% |  |" in lines


def test_task_stats_cli(tmp_path):
    out = subprocess.run([sys.executable, SCRIPT, "--no-dysql", "--set", f"x={results_dir(tmp_path)}"],
                         check=True, capture_output=True, text=True).stdout
    assert out.splitlines()[0] == "| metric | x |" and "| tasks | 1 |" in out
