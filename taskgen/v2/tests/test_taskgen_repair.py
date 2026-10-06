# tests/test_taskgen_repair.py -- orphan tasks repaired by a cascade (2026-10-05)
import pytest
from taskgen_common.testing import make_db
from v2_fixtures import MENUS, MENUS_FKS, MENUS_PROFILE
from taskgen_v2 import check, owners, repair


@pytest.fixture
def menus(tmp_path):
    return {"source": "test", "db": "menus", "path": make_db(tmp_path, "menus", MENUS), "anchors": [], "fks": MENUS_FKS}


def run(menus, sqls, **kw):
    db = check._memory_copy(menus["path"])
    return repair.cascade(db, owners.Tracer.from_profile(MENUS_PROFILE, menus, db), sqls, **kw)


def mcand(instruction, sqls):
    return {"id": "m", "anchor_table": "menu", "anchor_key": "menu_id", "key_value": 3,
            "plan": {"task_type": "6_entity", "style": {"speaker": "none"}}, "instruction": instruction,
            "actions": [{"sql": s} for s in sqls]}


def test_a_delete_first_removes_the_rows_that_point_at_it(menus):
    out = run(menus, ["DELETE FROM page WHERE page_id = 13"])
    assert out == ['DELETE FROM "item" WHERE "page_id" IN (SELECT "page_id" FROM "page" WHERE page_id = 13)',
                   "DELETE FROM page WHERE page_id = 13"]
    r = check.run_check(menus, mcand("Menu ID 3: delete page 13 and every item on it.", out), profile=MENUS_PROFILE)
    assert r["ok"], r["reasons"]


def test_a_root_delete_cascades_deepest_first(menus):
    out = run(menus, ["DELETE FROM menu WHERE menu_id = 3"])
    assert out[-1] == "DELETE FROM menu WHERE menu_id = 3" and out[0].startswith('DELETE FROM "item" WHERE "page_id" IN (SELECT "page_id" FROM "page"')
    assert {s.split('"')[1] for s in out[:-1]} == {"item", "page", "menu_stats", "menu_venue"}
    r = check.run_check(menus, mcand("Menu ID 3: delete it with its pages, items, yearly views and venue.", out), profile=MENUS_PROFILE)
    assert not any(x.startswith("orphans") for x in r["reasons"]), r["reasons"]


def test_a_renumbered_key_carries_its_children_along(menus):
    out = run(menus, ["UPDATE page SET page_id = 99 WHERE page_id = 13"])
    assert out == ["UPDATE page SET page_id = 99 WHERE page_id = 13", 'UPDATE "item" SET "page_id" = 99 WHERE "page_id" = 13']
    r = check.run_check(menus, mcand("Menu ID 3: renumber page 13 as 99 and move its items along.", out), profile=MENUS_PROFILE)
    assert r["ok"], r["reasons"]


def test_no_repair_when_a_table_would_lose_too_many_rows_or_a_statement_fails(menus):
    assert run(menus, ["DELETE FROM page WHERE page_id = 13"], max_rows=2) is None      # page 13 holds 3 items
    assert run(menus, ["DELETE FROM nope WHERE x = 1"]) is None
    assert run(menus, ["UPDATE item SET price = 2 WHERE item_id = 13"]) == ["UPDATE item SET price = 2 WHERE item_id = 13"]


def test_the_rewrite_prompt_and_its_answer():
    c = mcand("Menu ID 3: delete page 13.", ["DELETE FROM page WHERE page_id = 13"])
    new = ['DELETE FROM "item" WHERE "page_id" IN (SELECT "page_id" FROM "page" WHERE page_id = 13)', "DELETE FROM page WHERE page_id = 13"]
    msgs = repair.rewrite_messages(c, new, {"description": "Historical menus."})
    u = msgs[1]["content"]
    assert "Menu ID 3: delete page 13." in u and new[0] in u and "Historical menus." in u
    assert repair.parse_rewrite('<thought>x</thought><answer>{"instruction": "Menu ID 3: delete page 13 and its items."}</answer>') == \
        "Menu ID 3: delete page 13 and its items."
    with pytest.raises(ValueError):
        repair.parse_rewrite("no json here")


def test_only_candidates_rejected_for_the_new_rules_alone_are_repaired():
    import importlib.util, os
    spec = importlib.util.spec_from_file_location("repair_tasks", os.path.join(os.path.dirname(__file__), "..", "scripts", "repair_tasks.py"))
    rt = importlib.util.module_from_spec(spec); spec.loader.exec_module(rt)
    cands = {f"k:t:{i}:0": {"instruction": "x"} for i in range(5)}
    checks = [{"id": "k:t:0:0", "ok": False, "reasons": ["orphans: page"]},
              {"id": "k:t:1:0", "ok": False, "reasons": ["net_noop"]},
              {"id": "k:t:2:0", "ok": False, "reasons": ["orphans: page", "literal_missing: '4' in UPDATE item"]},   # bad anyway
              {"id": "k:t:3:0", "ok": True, "reasons": []},
              {"id": "k:t:4:0", "ok": False, "reasons": ["orphans: page", "net_noop"]}]
    assert rt.targets(cands, checks, done=set()) == {"k:t:0:0": "cascade", "k:t:1:0": "regenerate", "k:t:4:0": "regenerate"}
    assert rt.targets(cands, checks, done={"k:t:0:0"}) == {"k:t:1:0": "regenerate", "k:t:4:0": "regenerate"}
    assert rt.new_id("k:t:0:0") == "k:t:0:1"
