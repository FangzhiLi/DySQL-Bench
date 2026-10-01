# tests/test_taskgen_trees.py
import random, sqlite3
import pytest
from taskgen_common.testing import make_db, rows, SHOP
from taskgen_v2 import trees

SHOP2 = SHOP + """
CREATE TABLE order_items (item_id INTEGER PRIMARY KEY, order_id INTEGER REFERENCES orders(order_id), note TEXT);
CREATE TABLE staff (staff_id INTEGER PRIMARY KEY, name TEXT);
""" + rows("order_items", 300, lambda i: f"{i},{i%100},'n{i}'") + rows("staff", 5, lambda i: f"{i},'s{i}'")

FKS = [{"table": "orders", "col": "customer_id", "ref_table": "customers", "ref_col": "customer_id", "hit": 1.0, "source": "declared"},
       {"table": "orders", "col": "product_id", "ref_table": "products", "ref_col": "product_id", "hit": 1.0, "source": "declared"},
       {"table": "order_items", "col": "order_id", "ref_table": "orders", "ref_col": "order_id", "hit": 1.0, "source": "declared"}]
CUSTOMER = {"table": "customers", "key": "customer_id", "kind": "person_named", "rows": 60,
            "names": ["first_name", "last_name"], "down": ["orders", "order_items"], "up": ["products"],
            "update_targets": ["customers", "orders", "order_items", "products"]}
STAFF = {"table": "staff", "key": "staff_id", "kind": "person_named", "rows": 5, "names": ["name"],
         "down": [], "up": [], "update_targets": ["staff"]}


@pytest.fixture
def conn(tmp_path):
    c = sqlite3.connect(make_db(tmp_path, "shop2", SHOP2)); yield c; c.close()


def test_check_scope_accepts_matching_record_and_rejects_wrong_one():
    trees.check_scope(CUSTOMER, FKS)
    with pytest.raises(ValueError, match="scope from fks"):
        trees.check_scope({**CUSTOMER, "down": ["orders"]}, FKS)


def test_build_tree_joins_two_hops_and_collects_parents(conn):
    t = trees.build_tree(conn, CUSTOMER, FKS, 5, random.Random(0))
    assert t["anchor_name"] == "a5 b5" and t["anchor_row"]["customer_id"] == 5
    assert sorted(o["order_id"] for o in t["down"]["orders"]) == [5, 65]          # i % 60 == 5
    assert {i["order_id"] for i in t["down"]["order_items"]} == {5, 65}          # joined through orders, not customers
    assert [p["product_id"] for p in t["up"]["products"]] == [5]                  # referenced by the customer's orders


def test_build_tree_caps_child_rows(conn):
    t = trees.build_tree(conn, CUSTOMER, FKS, 5, random.Random(0), max_down=1)
    assert len(t["down"]["orders"]) == 1 and len(t["down"]["order_items"]) == 1


def test_build_tree_returns_none_for_missing_key(conn):
    assert trees.build_tree(conn, CUSTOMER, FKS, 999, random.Random(0)) is None


def test_person_without_children_still_builds_tree(conn):
    t = trees.build_tree(conn, STAFF, FKS, 2, random.Random(0))
    assert t["anchor_name"] == "s2" and t["down"] == {} and t["up"] == {}
    assert sorted(trees.anchor_key_values(conn, STAFF, FKS, random.Random(0), 10)) == [0, 1, 2, 3, 4]


def test_anchor_key_values_only_rows_with_children(conn):
    conn.execute("DELETE FROM orders WHERE customer_id = 7"); conn.commit()
    vals = trees.anchor_key_values(conn, CUSTOMER, FKS, random.Random(0), 100)
    assert 7 not in vals and len(vals) == 59


def test_blob_values_are_json_safe(conn):
    conn.execute("UPDATE customers SET first_name = x'00ff' WHERE customer_id = 5"); conn.commit()
    t = trees.build_tree(conn, CUSTOMER, FKS, 5, random.Random(0))
    assert t["anchor_row"]["first_name"] == "<blob 2 bytes>"


def test_check_scope_counts_composite_edges():
    comp = [{"table": "order_items", "cols": ["order_id", "note"], "ref_table": "staff", "ref_cols": ["a", "b"], "hit": 1.0}]
    with pytest.raises(ValueError):
        trees.check_scope({**CUSTOMER, "up": ["products", "staff"]}, FKS)
    trees.check_scope({**CUSTOMER, "up": ["products", "staff"]}, FKS, comp)
