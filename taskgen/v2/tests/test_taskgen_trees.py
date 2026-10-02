# tests/test_taskgen_trees.py
import random, sqlite3
import pytest
from taskgen_common.testing import make_db
from v2_fixtures import SHOP2, FKS, CUSTOMER, STAFF, SHOP_PROFILE, SCHOOL, SCHOOL_FKS, SCHOOL_COMPOSITE, SCHOOL_PROFILE   # noqa: F401 (re-exported)
from taskgen_v2 import db_profile, owners, trees

SHOP_REC = {"source": "test", "db": "shop2", "anchors": [CUSTOMER, STAFF], "fks": FKS}
SCHOOL_REC = {"source": "test", "db": "school", "anchors": [], "fks": SCHOOL_FKS, "fks_composite": SCHOOL_COMPOSITE}
CUSTOMERS = SHOP_PROFILE["roots"][0]
STUDENTS = SCHOOL_PROFILE["roots"][0]


@pytest.fixture
def shop(tmp_path):
    c = sqlite3.connect(make_db(tmp_path, "shop2", SHOP2)); yield c; c.close()


@pytest.fixture
def school(tmp_path):
    c = sqlite3.connect(make_db(tmp_path, "school", SCHOOL)); yield c; c.close()


def tree(conn, profile, rec, root, key, **kw):
    return trees.build_tree(conn, profile, root, key, random.Random(0), owners.Tracer.from_profile(profile, rec, conn), **kw)


def test_root_rows_with_events_come_first(shop):
    shop.execute("DELETE FROM orders WHERE customer_id = 7"); shop.commit()
    keys = trees.root_key_values(shop, SHOP_PROFILE, CUSTOMERS, random.Random(0))
    assert len(keys) == 60 and keys[-1] == 7                        # every customer, the one without orders last
    assert trees.root_key_values(shop, SHOP_PROFILE, CUSTOMERS, random.Random(0), 5) == keys[:5]


def test_allocate_passes_unused_shares_on():
    assert trees.allocate(200, [2000, 50]) == [150, 50]
    assert trees.allocate(10, [3, 3]) == [3, 3]
    assert trees.allocate(5, [10, 10]) == [2, 3]


def test_events_follow_paths_and_parents_nest(shop):
    t = tree(shop, SHOP_PROFILE, SHOP_REC, CUSTOMERS, 5)
    assert t["anchor_name"] == "a5 b5" and t["anchor_row"]["customer_id"] == 5
    assert t["lookup"] == {"first_name": "a5", "last_name": "b5"}                # no email column; the name is unique
    assert t["profile_version"] == db_profile.version(SHOP_PROFILE) and t["parents"] == [] and t["attributes"] == {}
    orders, items = t["events"]
    assert (orders["table"], orders["count"], [n["row"]["order_id"] for n in orders["rows"]]) == ("orders", 2, [5, 65])
    assert orders["rows"][0]["label"] == "own"
    assert orders["rows"][0]["parents"] == [{"table": "products", "row": {"product_id": 5, "name": "p5", "price": 1.0},
                                            "label": "public", "parents": []}]
    # two hops (customers -> orders -> order_items): the items of orders 5 and 65 only
    assert items["count"] == 6 and {n["row"]["order_id"] for n in items["rows"]} == {5, 65}


def test_composite_parent_attribute_root_parent_and_other_person(school):
    t = tree(school, SCHOOL_PROFILE, SCHOOL_REC, STUDENTS, 3)
    assert t["parents"] == [{"table": "dept", "row": {"dept_name": "d1", "building": "B1"}, "label": "public", "parents": []}]
    assert t["attributes"] == {"flags": [{"sid": 3, "honors": 1}]}
    takes, advisor = t["events"]
    assert [n["parents"][0]["row"]["title"] for n in takes["rows"]] == ["Algebra", "Biology"]   # (course, sec) -> section
    assert advisor["rows"][0]["label"] == "own" and advisor["rows"][0]["parents"][0]["label"] == "other:t0"


def test_events_are_capped_with_one_per_group(shop):
    t = tree(shop, SHOP_PROFILE, SHOP_REC, CUSTOMERS, 5, max_events=2)
    assert [len(g["rows"]) for g in t["events"]] == [1, 1] and [g["count"] for g in t["events"]] == [2, 6]


def test_missing_key_and_empty_foreign_keys(shop):
    assert tree(shop, SHOP_PROFILE, SHOP_REC, CUSTOMERS, 999) is None
    shop.execute("UPDATE orders SET product_id = NULL WHERE order_id = 5"); shop.commit()
    t = tree(shop, SHOP_PROFILE, SHOP_REC, CUSTOMERS, 5)
    assert t["events"][0]["rows"][0]["parents"] == []


def test_blob_values_are_json_safe(shop):
    shop.execute("UPDATE customers SET first_name = x'00ff' WHERE customer_id = 5"); shop.commit()
    assert tree(shop, SHOP_PROFILE, SHOP_REC, CUSTOMERS, 5)["anchor_row"]["first_name"] == "<blob 2 bytes>"


def test_picked_events_cover_groups_and_put_a_public_one_first(shop):
    t = tree(shop, SHOP_PROFILE, SHOP_REC, CUSTOMERS, 5)
    refs = trees.pick_events(t, random.Random(1), 3, need_public=True)
    assert len(refs) == 3 and refs[0][0] == 0                     # only orders have a public parent (products)
    assert {g for g, _ in refs[:2]} == {0, 1}                       # then a row of the group not shown yet
    shown = trees.shown(t, refs)
    assert [g["table"] for g in shown] == ["orders", "order_items"] and sum(len(g["rows"]) for g in shown) == 3
    assert trees.tables_by_label(t, refs) == {"own": ["customers", "orders", "order_items"], "public": ["products"], "other": []}
    assert trees.has_public(t)
    assert not trees.has_public({**t, "events": [t["events"][1]]})


def test_lookup_finds_what_only_this_person_has(tmp_path):
    conn = sqlite3.connect(make_db(tmp_path, "people", """
CREATE TABLE people (pid INTEGER PRIMARY KEY, first TEXT, last TEXT, email TEXT, phone TEXT);
INSERT INTO people VALUES (1, 'Ann', 'Lee', 'ann@x.org', '555'), (2, 'Ann', 'Lee', 'ann2@x.org', '555'),
                          (3, 'Bo', 'Ng', NULL, '777'), (4, 'Cy', 'Ho', 'cy@x.org', NULL), (5, 'Cy', 'Ho', 'cy@x.org', NULL),
                          (6, 'Di', 'Wu', 'cy@x.org', NULL);
"""))
    person = {"key": "pid", "name_cols": ["first", "last"]}

    def row(pid):
        return dict(zip(["pid", "first", "last", "email", "phone"], conn.execute("SELECT * FROM people WHERE pid = ?", (pid,)).fetchone()))
    assert trees.lookup(conn, "people", person, row(1)) == {"email": "ann@x.org"}         # same name as person 2
    assert trees.lookup(conn, "people", person, row(3)) == {"phone": "777"}               # no email
    assert trees.lookup(conn, "people", person, row(6)) == {"first": "Di", "last": "Wu"}  # shared email, own name
    assert trees.lookup(conn, "people", person, row(4)) == {}                             # nothing of their own


def test_lookup_skips_a_name_column_that_is_the_key(tmp_path):
    # student_loan's person table is just the name, which is the key: "find me by my name" found the key by the key
    conn = sqlite3.connect(make_db(tmp_path, "loans", "CREATE TABLE person (name TEXT PRIMARY KEY); INSERT INTO person VALUES ('student1');"))
    assert trees.lookup(conn, "person", {"key": "name", "name_cols": ["name"]}, {"name": "student1"}) == {}
