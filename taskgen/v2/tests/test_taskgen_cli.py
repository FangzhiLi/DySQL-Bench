# tests/test_taskgen_cli.py
import json, os, subprocess, sys
from taskgen_common.testing import make_db
from test_taskgen_trees import SHOP2, FKS, CUSTOMER, STAFF
from taskgen_v2 import io

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "taskgen.py")


def run(*args):
    return subprocess.run([sys.executable, SCRIPT, *args], check=True, capture_output=True, text=True).stdout


def test_trees_check_dedup_convert_without_a_model(tmp_path):
    db = make_db(tmp_path, "shop2", SHOP2)
    import sqlite3
    c = sqlite3.connect(db)   # >15 items per order, so build_tree samples with the rng (as on real DBs)
    c.executemany("INSERT INTO order_items (order_id, note) VALUES (?, 'x')", [(i % 100,) for i in range(3000)]); c.commit(); c.close()
    anchors = tmp_path / "anchors.json"
    anchors.write_text(json.dumps({"test:shop2": {"source": "test", "db": "shop2", "path": db, "anchors": [CUSTOMER, STAFF], "fks": FKS}}))
    out = tmp_path / "res"
    run("trees", "--db", "test:shop2", "--anchors", str(anchors), "--out-dir", str(out), "--n", "3", "--seed", "0")
    run("trees", "--db", "test:shop2", "--anchors", str(anchors), "--out-dir", str(out), "--n", "3", "--seed", "0")
    all_trees = io.read_jsonl(out / "trees.jsonl")
    assert len(all_trees) == 6                                   # a rerun adds nothing
    trees = [t for t in all_trees if t["anchor_table"] == "customers"]
    assert len(trees) == 3 and all(t["down"].get("orders") for t in trees)
    others = json.load(open(out / "others.json"))["customers"]
    assert len(others) >= 3 and not ({o["key_value"] for o in others} & {t["key_value"] for t in trees})   # not the speakers
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
