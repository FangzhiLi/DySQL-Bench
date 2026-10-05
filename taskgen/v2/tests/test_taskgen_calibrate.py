# tests/test_taskgen_calibrate.py
import random
from taskgen_common.testing import make_db
from v2_fixtures import SHOP2, FKS, CUSTOMER, STAFF, SHOP_PROFILE
from taskgen_v2 import calibrate, check, corrupt, io


def votes(*vs):
    return {"votes": [{"verdict": "error", "error": "Truncated: x"} if v == "err" else {"verdict": v} for v in vs]}


def item(i, s, **kw):
    return {"id": i, "set": s, **kw}


def test_verdict_takes_the_first_k_real_votes():
    r = votes("yes", "err", "no", "yes")
    assert calibrate.verdict(r, 1) == "pass" and calibrate.verdict(r, 2) == "fail" and calibrate.verdict(r, 3) == "pass"
    assert calibrate.verdict(votes("yes"), 2) is None and calibrate.verdict(None, 1) is None
    assert calibrate.verdict(votes("unparsed", "yes", "yes"), 3) == "pass" and calibrate.verdict(votes("unparsed"), 1) == "fail"


def test_a_rule_is_decided_as_soon_as_more_votes_cannot_change_it():
    # Ollama's plan is small: two votes each, a third only when they split, gives all three rules
    assert calibrate.verdict(votes("yes", "yes"), 3) == "pass" and calibrate.verdict(votes("no", "unparsed"), 3) == "fail"
    assert calibrate.verdict(votes("yes", "no"), 3) is None and calibrate.verdict(votes("no"), 2) == "fail"
    assert calibrate.verdict(votes("err", "no"), 2) == "fail" and calibrate.verdict(votes("yes", "err"), 2) is None
    items = [item(x, "positives") for x in "abcd"]
    v = {"a": votes("yes", "yes"), "b": votes("yes", "no"), "c": votes("yes", "no", "no"), "d": votes("yes")}
    assert [i["id"] for i in calibrate.undecided(items, v)] == ["b", "d"]


def test_metrics_per_rule_and_the_rule_choice():
    items = ([item(f"p{i}", "positives") for i in range(20)]
             + [item(f"n{i}", "negatives", source="dysql", kind="where") for i in range(10)]
             + [item("g", "labeled"), item("b", "labeled"), item("u", "labeled")])
    v = {f"p{i}": votes("yes", "yes", "yes") for i in range(19)}
    v["p19"] = votes("yes", "no", "yes")                                   # passes with one or three votes, not two
    v.update({f"n{i}": votes("no", "no", "no") for i in range(5)})
    v.update({f"n{i}": votes("yes", "no", "no") for i in range(5, 8)})     # caught by two and three votes only
    v.update({f"n{i}": votes("yes", "yes", "yes") for i in range(8, 10)})
    v.update(g=votes("yes", "yes", "yes"), b=votes("no", "no", "yes"), u=votes("yes", "yes", "yes"))
    labels = {"g": {"label": "good"}, "b": {"label": "bad"}}               # u is not labeled yet
    m = calibrate.metrics(items, v, labels)
    assert m["1 vote"]["positives_pass"] == (1.0, 20, 20) and m["2 votes, both Yes"]["positives_pass"] == (0.95, 19, 20)
    assert m["1 vote"]["negatives_reject"] == (0.5, 5, 10) and m["2 votes, both Yes"]["negatives_reject"] == (0.8, 8, 10)
    assert m["3 votes, 2 Yes"]["negatives_by_kind"] == {("dysql", "where"): (0.8, 8, 10)}
    assert m["3 votes, 2 Yes"]["labeled_good_pass"] == (1.0, 1, 1)
    assert m["3 votes, 2 Yes"]["labeled_bad_reject"] == (1.0, 1, 1) and m["3 votes, 2 Yes"]["labeled_precision"] == (1.0, 1, 1)
    assert calibrate.choose_rule(m) == "2 votes, both Yes"                 # as many negatives as three votes, fewer calls
    assert calibrate.choose_rule(m, floor=0.99) == "3 votes, 2 Yes"        # two votes lose a good task
    v["g"] = votes("no", "no", "no")
    assert calibrate.choose_rule(calibrate.metrics(items, v, labels)) is None


def test_the_users_label_replaces_claudes_and_disagreements_are_shown():
    rows = [{"id": "a", "label": "good", "by": "claude"}, {"id": "b", "label": "bad", "reason": "unclear", "by": "claude"},
            {"id": "c", "label": "good", "unsure": True, "by": "claude"}, {"id": "a", "label": "bad", "reason": "extra", "by": "user"}]
    labels = calibrate.final_labels(rows)
    assert labels["a"]["by"] == "user" and labels["a"]["label"] == "bad"
    items = [item(x, "labeled") for x in "abcd"]
    v = {"a": votes("no", "no", "no"), "b": votes("yes", "yes", "no"), "c": votes("yes", "yes", "yes"), "d": votes("no", "no", "no")}
    assert [i["id"] for i in calibrate.disagreements(items, v, labels)] == ["b", "c"]   # a agrees now, d has no label


def shop_dbs(tmp_path):
    db = make_db(tmp_path, "shop2", SHOP2)
    rec = {"source": "test", "db": "shop2", "path": db, "anchors": [CUSTOMER, STAFF], "fks": FKS}
    return calibrate.Databases({"test:shop2": rec}, {"test:shop2": SHOP_PROFILE}), db


def cand(i, sql, instruction):
    return {"id": f"test:shop2:customers:5:{i}", "db": "test:shop2", "set": "labeled", "anchor_table": "customers",
            "key_value": 5, "plan": {"task_type": "1_self"}, "instruction": instruction, "actions": [{"sql": sql}]}


def test_negatives_still_pass_the_check_and_end_elsewhere(tmp_path):
    dbs, path = shop_dbs(tmp_path)
    items = [cand(0, "UPDATE orders SET qty = 3 WHERE order_id = 5 AND customer_id = 5", "I am a5 b5, customer 5. Set qty of my order 5 to 3."),
             cand(1, "UPDATE orders SET qty = 2 WHERE order_id = 65", "I am a5 b5, customer 5. Set qty of my order 65 to 2.")]
    assert all(dbs.check(i)["ok"] for i in items)
    neg = calibrate.negatives(items, dbs, 5, random.Random(0), "v2")
    assert {n["kind"] for n in neg} == {"literal", "where", "set_column"}   # one write each: no drop_last
    for n in neg:
        gold = next(i for i in items if i["id"] == n["of"])
        assert n["id"] == f"{gold['id']}#{n['kind']}" and n["set"] == "negatives" and n["source"] == "v2"
        assert dbs.check(n)["ok"] and check.final_state(path, corrupt.statements(n)) != check.final_state(path, corrupt.statements(gold))
    assert not any(n["kind"] == "swap_values" for n in neg)   # every swap here misses its row: the check rejects it
    assert len(calibrate.negatives(items, dbs, 1, random.Random(0), "v2")) <= len(corrupt.KINDS)


def test_v2_items_are_the_checked_candidates_keyed_by_database(tmp_path):
    d = tmp_path / "run" / "shop2"
    d.mkdir(parents=True)
    io.append_jsonl(d / "candidates.jsonl", [{"id": "test:shop2:customers:5:0", "db": "shop2"}, {"id": "test:shop2:customers:6:0", "db": "shop2"}])
    io.append_jsonl(d / "check.jsonl", [{"id": "test:shop2:customers:5:0", "ok": True}, {"id": "test:shop2:customers:6:0", "ok": False}])
    assert calibrate.v2_items([str(tmp_path / "run")]) == [{"id": "test:shop2:customers:5:0", "db": "test:shop2", "set": "labeled"}]


def test_a_rule_that_cannot_judge_every_voted_item_is_not_chosen():
    # one vote each after the second votes stopped: a 2-vote rule judged only the items a single No settles, and
    # looked better than it is on that biased part
    items = ([item(f"p{i}", "positives") for i in range(20)] + [item("g", "labeled"), item("z", "positives")]
             + [item(f"n{i}", "negatives", source="dysql", kind="where") for i in range(10)])
    v = {f"p{i}": votes("yes", "yes") for i in range(20)}
    v.update({f"n{i}": votes("yes", "no") for i in range(5)})   # 1 vote: passed; 2 votes: rejected
    v.update({f"n{i}": votes("yes") for i in range(5, 10)})     # 1 vote: passed; 2 votes: not judged yet
    v.update(g=votes("yes", "yes"), z=votes("err"))             # z has no real vote: no rule judges it
    m = calibrate.metrics(items, v, {"g": {"label": "good"}})
    assert m["1 vote"]["undecided"] == 0 and m["2 votes, both Yes"]["undecided"] == 5 and m["3 votes, 2 Yes"]["undecided"] == 10
    assert m["2 votes, both Yes"]["negatives_reject"] == (1.0, 5, 5)          # the biased part
    assert calibrate.choose_rule(m) == "1 vote" and calibrate.unvoted(items, v) == ["z"]


def test_v2_items_reads_database_folders_or_their_parent(tmp_path):
    d = tmp_path / "menu"
    d.mkdir()
    io.append_jsonl(str(d / "candidates.jsonl"), [{"id": "bird:menu:Menu:5:0", "instruction": "x", "actions": []},
                                                  {"id": "bird:menu:Menu:6:0"}])
    io.append_jsonl(str(d / "check.jsonl"), [{"id": "bird:menu:Menu:5:0", "ok": True}, {"id": "bird:menu:Menu:6:0", "ok": False}])
    for root in (str(tmp_path), str(d)):
        assert [(i["id"], i["db"]) for i in calibrate.v2_items([root])] == [("bird:menu:Menu:5:0", "bird:menu")]


def test_dysql_entity_databases_get_the_entity_note():
    from taskgen_v2 import verify
    dbs = calibrate.Databases()
    assert dbs.get("dysql:car")["notes"] == [verify.ENTITY_NOTE.format(label="car")]
    assert dbs.get("dysql:chinook")["notes"] == []
