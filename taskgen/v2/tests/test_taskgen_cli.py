# tests/test_taskgen_cli.py
import json, os, subprocess, sys, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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
    p = {**SHOP_PROFILE, "confirmed": confirmed}
    if not confirmed:
        del p["confirmed_version"]
    db_profile.save({"test:shop2": p}, str(profiles))
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
        "profile_version": t["profile_version"], "plan": {"task_type": "1_self", "difficulty": "easy"},
        "instruction": f"I am {t['anchor_name']}. Set qty of my order {oid} to 3.",
        "actions": [{"sql": f"UPDATE orders SET qty = 3 WHERE order_id = {oid}"}], "error": None}])
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


def test_an_edit_after_confirming_needs_a_new_confirmation(tmp_path):
    args = setup(tmp_path, confirmed=False)
    db, anchors, profiles = args[1], args[3], args[5]
    common = ["--anchors", anchors, "--profiles", profiles]
    run("profile", "confirm", *common, "--db", db)
    p = db_profile.load(profiles)[db]
    assert p["confirmed_version"] == db_profile.version(p)
    db_profile.save({db: {**p, "quirks": ["qty is never 0."]}}, profiles)   # a hand edit leaves confirmed: true
    assert "test:shop2: ok, changed since confirmed" in run("profile", "check", *common).stdout
    page = tmp_path / "review.md"
    run("profile", "render", *common, "--out", str(page))
    assert "## test:shop2　确认后改过　校验通过" in page.read_text()
    for cmd in ("trees", "generate", "check"):
        r = run(cmd, *args, check=False)
        assert r.returncode == 1 and "changed after it was confirmed" in r.stderr


def test_steps_refuse_records_built_from_another_profile_version(tmp_path):
    # a prompt built from the old labels must not meet a check that reads the new profile
    args = setup(tmp_path)
    out, profiles = tmp_path / "res", args[5]
    run("trees", *args, "--n", "2", "--seed", "0")
    p = db_profile.load(profiles)["test:shop2"]
    db_profile.save({"test:shop2": db_profile.confirm({**p, "quirks": ["qty is never 0."]})}, profiles)   # edited, confirmed again
    for cmd in ("trees", "generate"):
        r = run(cmd, *args, check=False)
        assert r.returncode == 1 and "trees.jsonl holds trees from profile version" in r.stderr
    os.remove(out / "trees.jsonl")
    io.append_jsonl(out / "candidates.jsonl", [{"id": "test:shop2:customers:1:0", "profile_version": "0123456789"}])
    for cmd in ("generate", "check"):
        r = run(cmd, *args, check=False)
        assert r.returncode == 1 and "candidates.jsonl holds candidates from profile version 0123456789" in r.stderr


def test_profile_check_render_and_confirm(tmp_path):
    args = setup(tmp_path, confirmed=False)
    db, anchors, profiles = args[1], args[3], args[5]
    common = ["--anchors", anchors, "--profiles", profiles]
    r = run("profile", "check", *common)
    assert r.returncode == 0 and "test:shop2: ok, not confirmed" in r.stdout
    page, sample = tmp_path / "review.md", tmp_path / "trees.md"
    run("profile", "render", *common, "--out", str(page), "--trees-out", str(sample))
    assert "## test:shop2　未确认　校验通过" in page.read_text()
    assert sample.read_text().startswith("# test:shop2 · customers ") and "## orders: orders records" in sample.read_text()
    run("profile", "confirm", *common, "--db", db)
    assert db_profile.load(profiles)[db]["confirmed"] is True
    broken = {**SHOP_PROFILE, "public": [], "confirmed": False}                      # products hangs under orders, now without a role
    db_profile.save({db: broken}, profiles)
    r = run("profile", "check", *common, check=False)
    assert r.returncode == 1 and "products hangs under orders but is not public" in r.stdout
    r = run("profile", "confirm", *common, "--db", db, check=False)
    assert r.returncode == 1 and db_profile.load(profiles)[db]["confirmed"] is False


class FakeVerifier(BaseHTTPRequestHandler):
    """An OpenAI-style endpoint that answers Yes and keeps every request body."""
    seen = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeVerifier.seen.append(body)
        out = json.dumps({"model": body["model"], "usage": {"completion_tokens": 9}, "choices": [
            {"message": {"content": "Fine. Verification: Is the answer correct (Yes/No)? Yes"}, "finish_reason": "stop"}]}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out))); self.end_headers(); self.wfile.write(out)

    def log_message(self, *a):
        pass


def test_verify_sees_precapped_candidates_with_the_profile_quirks(tmp_path):
    args = setup(tmp_path)
    profiles = args[args.index("--profiles") + 1]
    ps = db_profile.load(profiles)
    ps["test:shop2"] = db_profile.confirm({**ps["test:shop2"], "quirks": ["qty counts boxes, not items."]})
    db_profile.save(ps, profiles)
    out = tmp_path / "res"
    run("trees", *args, "--n", "3", "--seed", "0")
    rows = []
    for t in io.read_jsonl(out / "trees.jsonl"):
        oid = t["events"][0]["rows"][0]["row"]["order_id"]
        rows.append({"id": "test:shop2:customers:%s:0" % t["key_value"], "db": "shop2", "source": "test",
                     "anchor_table": "customers", "anchor_key": "customer_id", "key_value": t["key_value"],
                     "anchor_name": t["anchor_name"], "profile_version": t["profile_version"],
                     "plan": {"task_type": "1_self", "difficulty": "easy"},
                     "instruction": f"I am {t['anchor_name']}. Set qty of my order {oid} to 3.",
                     "actions": [{"sql": f"UPDATE orders SET qty = 3 WHERE order_id = {oid}"}], "error": None})
    io.append_jsonl(out / "candidates.jsonl", rows)
    run("check", *args)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeVerifier)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    env = {**os.environ, "TASKGEN_VERIFY_BASE_URL": f"http://127.0.0.1:{srv.server_port}/v1",
           "TASKGEN_VERIFY_API_KEY": "k", "TASKGEN_VERIFY_MODELS": "m1:2"}
    try:
        subprocess.run([sys.executable, SCRIPT, "verify", *args, "--precap-template", "2", "--workers", "1"],
                       check=True, capture_output=True, text=True, env=env)
    finally:
        srv.shutdown()
    v = io.read_jsonl(out / "verify.jsonl")
    assert len(v) == 2 and all(r["models"] == {"m1": {"yes": 2, "no": 0, "pass": True}} and r["pass"] for r in v)  # 3 checked, 2 per template
    assert len(FakeVerifier.seen) == 4 and {b["model"] for b in FakeVerifier.seen} == {"m1"}
    u = FakeVerifier.seen[0]["messages"][1]["content"]
    assert "- qty counts boxes, not items." in u and "CREATE TABLE orders" in u


class Refuses(BaseHTTPRequestHandler):
    """An endpoint whose quota is gone: every call fails."""
    calls = 0

    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        Refuses.calls += 1
        out = b'{"error": "weekly usage limit reached"}'
        self.send_response(400); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out))); self.end_headers(); self.wfile.write(out)

    def log_message(self, *a):
        pass


def test_verify_pauses_when_every_call_fails(tmp_path):
    args = setup(tmp_path)
    out = tmp_path / "res"
    run("trees", *args, "--n", "3", "--seed", "0")
    io.append_jsonl(out / "candidates.jsonl", [
        {"id": "test:shop2:customers:%s:0" % t["key_value"], "db": "shop2", "source": "test", "anchor_table": "customers",
         "anchor_key": "customer_id", "key_value": t["key_value"], "anchor_name": t["anchor_name"],
         "profile_version": t["profile_version"], "plan": {"task_type": "1_self", "difficulty": "easy"},
         "instruction": f"I am {t['anchor_name']}. Set qty of my order {t['events'][0]['rows'][0]['row']['order_id']} to 3.",
         "actions": [{"sql": f"UPDATE orders SET qty = 3 WHERE order_id = {t['events'][0]['rows'][0]['row']['order_id']}"}],
         "error": None} for t in io.read_jsonl(out / "trees.jsonl")])
    run("check", *args)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Refuses)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    env = {**os.environ, "TASKGEN_VERIFY_BASE_URL": f"http://127.0.0.1:{srv.server_port}/v1",
           "TASKGEN_VERIFY_API_KEY": "k", "TASKGEN_VERIFY_MODELS": "m1:3"}
    try:
        r = subprocess.run([sys.executable, SCRIPT, "verify", *args, "--workers", "1", "--max-failures", "2"],
                           capture_output=True, text=True, env=env)
    finally:
        srv.shutdown()
    assert r.returncode == 3 and "paused" in r.stderr and Refuses.calls == 2
    assert all(not v["pass"] and v["unvoted"] for v in io.read_jsonl(out / "verify.jsonl"))
