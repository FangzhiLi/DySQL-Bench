# tests/test_taskgen_cli.py
import json, os, subprocess, sys
from taskgen_common.testing import make_db
from v2_fixtures import SHOP2, FKS, CUSTOMER, STAFF, SHOP_PROFILE
from taskgen_v2 import db_profile, io

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "taskgen.py")


def run(*args, check=True):
    return subprocess.run([sys.executable, SCRIPT, *args], check=check, capture_output=True, text=True)


def setup(tmp_path, confirmed=True):
    db = make_db(tmp_path, "shop2", SHOP2)
    anchors = tmp_path / "anchors.json"
    anchors.write_text(json.dumps({"test:shop2": {"source": "test", "db": "shop2", "path": db, "anchors": [CUSTOMER, STAFF], "fks": FKS}}))
    profiles = tmp_path / "profiles.json"
    db_profile.save({"test:shop2": {**SHOP_PROFILE, "confirmed": confirmed}}, str(profiles))
    return ["--db", "test:shop2", "--anchors", str(anchors), "--profiles", str(profiles), "--out-dir", str(tmp_path / "res")]


def test_trees_check_dedup_convert_without_a_model(tmp_path):
    args = setup(tmp_path)
    out = tmp_path / "res"
    run("trees", *args, "--n", "3", "--seed", "0")
    run("trees", *args, "--n", "3", "--seed", "0")
    trees = io.read_jsonl(out / "trees.jsonl")
    assert len(trees) == 3 and all(t["anchor_table"] == "customers" and t["events"][0]["rows"] for t in trees)   # a rerun adds nothing
    assert not os.path.exists(out / "others.json")
    t = trees[0]
    oid = t["events"][0]["rows"][0]["row"]["order_id"]
    io.append_jsonl(out / "candidates.jsonl", [{"id": "test:shop2:customers:%s:0" % t["key_value"], "db": "shop2", "source": "test",
        "anchor_table": "customers", "anchor_key": "customer_id", "key_value": t["key_value"], "anchor_name": t["anchor_name"],
        "plan": {"task_type": "1_self", "difficulty": "easy"}, "instruction": f"I am {t['anchor_name']}. Set qty of my order {oid} to 3.",
        "actions": [{"sql": f"UPDATE orders SET qty = 3 WHERE order_id = {oid}"}], "outputs": [], "error": None}])
    run("check", *args)
    chk = io.read_jsonl(out / "check.jsonl")
    assert len(chk) == 1 and chk[0]["ok"] and chk[0]["template"] == "1_self|UPDATE orders"
    io.append_jsonl(out / "verify.jsonl", [{"id": chk[0]["id"], "votes": [{"verdict": "yes"}] * 3, "yes": 3, "no": 0, "pass": True, "verify_model": "fake"}])
    run("dedup", *args)
    assert len(io.read_jsonl(out / "selected.jsonl")) == 1
    manifest = tmp_path / "manifest.json"; tasks = tmp_path / "tasks.jsonl"
    run("convert", *args, "--tasks", str(tasks), "--manifest", str(manifest))
    assert io.read_jsonl(tasks)[0]["meta"]["template"] == "1_self|UPDATE orders" and json.load(open(manifest))["shop2"]["db_key"] == "test:shop2"
    assert "n_selected" in run("stats", *args).stdout


def test_trees_and_check_refuse_an_unconfirmed_profile(tmp_path):
    args = setup(tmp_path, confirmed=False)
    for cmd in ("trees", "check"):
        r = run(cmd, *args, check=False)
        assert r.returncode == 1 and "not confirmed" in r.stderr
