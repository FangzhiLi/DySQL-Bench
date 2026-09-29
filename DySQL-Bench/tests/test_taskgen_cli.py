# tests/test_taskgen_cli.py
import json, os, subprocess, sys
from tests._sqlite_fixtures import make_db
from tests.test_taskgen_trees import SHOP2, FKS, CUSTOMER
from dysql_bench.taskgen import io

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "taskgen.py")


def run(*args):
    return subprocess.run([sys.executable, SCRIPT, *args], check=True, capture_output=True, text=True).stdout


def test_trees_check_dedup_convert_without_a_model(tmp_path):
    db = make_db(tmp_path, "shop2", SHOP2)
    anchors = tmp_path / "anchors.json"
    anchors.write_text(json.dumps({"test:shop2": {"source": "test", "db": "shop2", "path": db, "anchors": [CUSTOMER], "fks": FKS}}))
    out = tmp_path / "res"
    run("trees", "--db", "test:shop2", "--anchors", str(anchors), "--out-dir", str(out), "--n", "3", "--seed", "0")
    trees = io.read_jsonl(out / "trees.jsonl")
    assert len(trees) == 3 and all(t["down"].get("orders") for t in trees) and len(json.load(open(out / "others.json"))["customers"]) >= 3
    # a hand-written candidate stands in for the model
    t = trees[0]
    io.append_jsonl(out / "candidates.jsonl", [{"id": "test:shop2:customers:%s:0" % t["key_value"], "db": "shop2", "source": "test",
        "anchor_table": "customers", "anchor_key": "customer_id", "key_value": t["key_value"], "anchor_name": t["anchor_name"],
        "plan": {"task_type": "1_self", "difficulty": "easy"}, "instruction": f"I am {t['anchor_name']}. Set qty of my order {t['down']['orders'][0]['order_id']} to 3.",
        "actions": [{"sql": f"UPDATE orders SET qty = 3 WHERE order_id = {t['down']['orders'][0]['order_id']}"}], "outputs": [], "error": None}])
    run("check", "--db", "test:shop2", "--anchors", str(anchors), "--out-dir", str(out))
    chk = io.read_jsonl(out / "check.jsonl")
    assert len(chk) == 1 and chk[0]["ok"] and chk[0]["template"] == "1_self|UPDATE orders"
    io.append_jsonl(out / "verify.jsonl", [{"id": chk[0]["id"], "votes": [{"verdict": "yes"}] * 3, "yes": 3, "no": 0, "pass": True, "verify_model": "fake"}])
    run("dedup", "--db", "test:shop2", "--anchors", str(anchors), "--out-dir", str(out))
    assert len(io.read_jsonl(out / "selected.jsonl")) == 1
    manifest = tmp_path / "manifest.json"; tasks = tmp_path / "tasks.jsonl"
    run("convert", "--db", "test:shop2", "--anchors", str(anchors), "--out-dir", str(out), "--tasks", str(tasks), "--manifest", str(manifest))
    assert io.read_jsonl(tasks)[0]["meta"]["template"] == "1_self|UPDATE orders" and json.load(open(manifest))["shop2"]["db_key"] == "test:shop2"
    text = run("stats", "--db", "test:shop2", "--anchors", str(anchors), "--out-dir", str(out))
    assert "n_selected" in text and "| 1 |" in text
