# tests/test_taskgen_owners.py
import sqlite3
import pytest
from taskgen_common.testing import make_db
from v2_fixtures import SHOP2, FKS, CUSTOMER, STAFF, SHOP_PROFILE, SCHOOL, SCHOOL_FKS, SCHOOL_COMPOSITE, SCHOOL_PROFILE
from taskgen_v2 import owners

SHOP_REC = {"source": "test", "db": "shop2", "anchors": [CUSTOMER, STAFF], "fks": FKS}
SCHOOL_REC = {"source": "test", "db": "school", "anchors": [], "fks": SCHOOL_FKS, "fks_composite": SCHOOL_COMPOSITE}


@pytest.fixture
def shop(tmp_path):
    return sqlite3.connect(make_db(tmp_path, "shop2", SHOP2))


@pytest.fixture
def school(tmp_path):
    return sqlite3.connect(make_db(tmp_path, "school", SCHOOL))


def test_from_rec_traces_like_v1(shop):
    t = owners.Tracer.from_rec(SHOP_REC, shop)
    assert t.persons == {"customers": "customer_id", "staff": "staff_id"}
    item = {"item_id": 5, "order_id": 65, "note": "n5"}                     # order 65 belongs to customer 5
    assert t.trace("order_items", item) == {("customers", "5")}
    assert t.trace("products", {"product_id": 5}) == set()
    assert t.canon("ORDERS") == "orders" and t.canon("nope") == "nope"


def test_from_profile_follows_profile_edges_composite_keys_and_text_ids(school):
    t = owners.Tracer.from_profile(SCHOOL_PROFILE, SCHOOL_REC, school)
    # advisor.s_id -> "Student List".sid is only in the profile, and its TEXT '3' finds the INTEGER 3
    assert t.trace("advisor", {"s_id": "3", "t_id": 0}) == {("Student List", "3"), ("teacher", "0")}
    assert t.trace("takes", {"sid": 2, "course": "c1", "sec": 1, "grade": "A"}) == {("Student List", "2")}
    assert t.trace("section", {"course": "c1", "sec": 1, "title": "Algebra"}) == set()
    assert t.canon("student list") == "Student List"


def test_labels_name_the_other_person(school):
    t = owners.Tracer.from_profile(SCHOOL_PROFILE, SCHOOL_REC, school)
    me = {("Student List", "3")}
    assert t.label("advisor", {"s_id": "3", "t_id": 0}, me) == "own"
    assert t.label("advisor", {"s_id": "4", "t_id": 1}, me) == "other:s4"
    assert t.label("teacher", {"tid": 0, "name": "t0"}, me) == "other:t0"
    assert t.label("dept", {"dept_name": "d0", "building": "B0"}, me) == "public"


def test_self_references_say_nothing_about_ownership(tmp_path):
    c = sqlite3.connect(make_db(tmp_path, "e", "CREATE TABLE emp (id INTEGER PRIMARY KEY, name TEXT, boss INTEGER REFERENCES emp(id));"
                                               "INSERT INTO emp VALUES (1, 'a', NULL), (2, 'b', 1);"))
    rec = {"anchors": [{"table": "emp", "key": "id", "kind": "person_named", "names": ["name"]}],
           "fks": [{"table": "emp", "col": "boss", "ref_table": "emp", "ref_col": "id"}]}
    t = owners.Tracer.from_rec(rec, c)
    assert t.up == {} and t.trace("emp", {"id": 2, "name": "b", "boss": 1}) == {("emp", "2")}
