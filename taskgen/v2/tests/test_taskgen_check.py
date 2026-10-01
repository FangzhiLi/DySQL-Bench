# tests/test_taskgen_check.py
import sqlite3
import pytest
from taskgen_common.testing import make_db, SHOP, rows
from test_taskgen_trees import SHOP2, FKS, CUSTOMER
from taskgen_v2 import check

STAFF_ANCHOR = {"table": "staff", "key": "staff_id", "kind": "person_named", "rows": 5, "names": ["name"],
                "down": [], "up": [], "update_targets": ["staff"]}


@pytest.fixture
def db(tmp_path):
    path = make_db(tmp_path, "shop2", SHOP2)
    return {"source": "test", "db": "shop2", "path": path, "anchors": [CUSTOMER, STAFF_ANCHOR], "fks": FKS}


def cand(instruction, sqls, task_type="1_self", key_value=5):
    return {"id": "t", "anchor_table": "customers", "anchor_key": "customer_id", "key_value": key_value,
            "plan": {"task_type": task_type}, "instruction": instruction, "actions": [{"sql": s} for s in sqls]}


AUTH = "SELECT * FROM customers WHERE first_name = 'a5' AND last_name = 'b5'"


def test_good_task_passes_with_labels_template_and_difficulty(db):
    r = check.run_check(db, cand("I am a5 b5 (customer 5). Set the qty of my order 5 to 3.",
                                 [AUTH, "UPDATE orders SET qty = 3 WHERE order_id = 5 AND customer_id = 5"]))
    assert r["ok"] and r["reasons"] == []
    assert r["writes"] == [{"op": "UPDATE", "table": "orders", "rows": 1, "label": "own"}]
    assert r["task_type"] == "1_self" and r["template"] == "1_self|UPDATE orders"
    assert r["difficulty"] == {"score": 0, "level": "easy", "features": {"multi_write": False, "multi_table": False,
                                                                          "subquery": False, "archive": False, "public_or_other": False}}


def test_literal_missing_fails_but_anchor_values_are_allowed(db):
    r = check.run_check(db, cand("I am a5 b5. Set the qty of my order 5 to 3.",
                                 [AUTH, "UPDATE orders SET qty = 4 WHERE order_id = 5 AND customer_id = 5"]))
    assert not r["ok"] and r["reasons"] == ["literal_missing: '4' in UPDATE orders"]
    r = check.run_check(db, cand("I am a5 b5. Set the qty of order 5 to 3.",   # customer_id 5 not in the text: it's the anchor key
                                 ["UPDATE orders SET qty = 3 WHERE order_id = 5 AND customer_id = 5"]))
    assert r["ok"]


def test_literal_quotes_unicode_numbers(db):
    ins = "I'm a5 b5. Rename product 5 to O'Brien Café and set its price to 3.50."
    r = check.run_check(db, cand(ins, ["UPDATE products SET name = 'O''Brien Café', price = 3.5 WHERE product_id = 5"]))
    assert r["ok"], r["reasons"]


def test_noop_bulk_error_and_no_write(db):
    assert check.run_check(db, cand("set qty to 1 on order 999", ["UPDATE orders SET qty = 1 WHERE order_id = 999"]))["reasons"] == ["noop_write: UPDATE orders"]
    assert check.run_check(db, cand("qty 1", ["UPDATE orders SET qty = 1"]))["reasons"][0].startswith("bulk: 100 rows in UPDATE orders")
    assert check.run_check(db, cand("x", ["UPDATE nope SET a = 1"]))["reasons"][0].startswith("sql_error:")
    assert check.run_check(db, cand("x", [AUTH]))["reasons"] == ["no_write"]
    assert check.run_check(db, {**cand("x", [AUTH]), "instruction": None})["reasons"] == ["no_instruction"]


def test_multi_statement_action_is_split(db):
    r = check.run_check(db, cand("I am a5 b5. Set qty of order 5 to 3 and delete order 65.",
                                 ["UPDATE orders SET qty = 3 WHERE order_id = 5; DELETE FROM orders WHERE order_id = 65;"]))
    assert r["ok"] and [w["op"] for w in r["writes"]] == ["UPDATE", "DELETE"] and r["template"] == "1_self|DELETE orders+UPDATE orders"
    assert r["difficulty"]["features"]["multi_write"] and r["difficulty"]["level"] == "medium"


def test_types_public_other_and_proxy(db):
    r = check.run_check(db, cand("I am a5 b5. Set price of product 5 to 2.0 and qty of order 5 to 3.",
                                 ["UPDATE products SET price = 2.0 WHERE product_id = 5", "UPDATE orders SET qty = 3 WHERE order_id = 5"]))
    assert r["task_type"] == "2_self_and_public" and r["difficulty"]["features"]["public_or_other"] and r["difficulty"]["level"] == "hard"
    r = check.run_check(db, cand("I am a5 b5. Set qty of order 9 to 3.", ["UPDATE orders SET qty = 3 WHERE order_id = 9"]))
    assert r["task_type"] == "4_other_person" and r["writes"][0]["label"] == "other"
    r = check.run_check(db, cand("I am Pat, an analyst. Set qty of order 5 to 3.", ["UPDATE orders SET qty = 3 WHERE order_id = 5"], task_type="5_proxy"))
    assert r["task_type"] == "5_proxy" and r["writes"][0]["label"] == "person_obj"


def test_subquery_and_archive_features(db):
    r = check.run_check(db, cand("I am a5 b5. Set qty of my order 5 to 3.",
                                 ["UPDATE orders SET qty = 3 WHERE order_id = 5 AND customer_id = (SELECT customer_id FROM customers WHERE first_name = 'a5' AND last_name = 'b5')"]))
    assert r["ok"] and r["difficulty"]["features"]["subquery"]
    r = check.run_check(db, cand("I am a5 b5. Archive order item 5 as a note copy then delete it.",
                                 ["INSERT INTO order_items (order_id, note) SELECT order_id, note FROM order_items WHERE item_id = 5",
                                  "DELETE FROM order_items WHERE item_id = 5"]))
    assert r["ok"] and r["difficulty"]["features"]["archive"]


def test_source_db_is_untouched(db):
    check.run_check(db, cand("I am a5 b5. Set qty of my order 5 to 3.", ["UPDATE orders SET qty = 3 WHERE order_id = 5"]))
    c = sqlite3.connect(db["path"])
    assert c.execute("SELECT qty FROM orders WHERE order_id = 5").fetchone()[0] == 1


def test_zero_row_insert_select_counts_as_no_write(db):
    r = check.run_check(db, cand("I am a5 b5. Copy order 999 notes.",
                                 ["INSERT INTO order_items (order_id, note) SELECT order_id, note FROM order_items WHERE item_id = 999"]))
    assert r["reasons"] == ["no_write"]


def test_scope_is_the_union_of_the_databases_anchor_scopes(db):
    # a customer editing a public table that only another anchor's scope reaches (DySQL: customers editing playlist_track)
    r = check.run_check(db, cand("I am a5 b5. Rename staff 2 to Zed.", ["UPDATE staff SET name = 'Zed' WHERE staff_id = 2"]))
    assert not any(x.startswith("out_of_scope") for x in r["reasons"])
    no_staff = {**db, "anchors": [a for a in db["anchors"] if a["table"] != "staff"]}
    r = check.run_check(no_staff, cand("I am a5 b5. Rename staff 2 to Zed.", ["UPDATE staff SET name = 'Zed' WHERE staff_id = 2"]))
    assert r["reasons"] == ["out_of_scope: staff"]


def test_zero_and_one_need_not_appear_in_the_instruction(db):
    r = check.run_check(db, cand("I am a5 b5. Add product 7 to my order list as a new order 500.",
                                 ["INSERT INTO orders (order_id, customer_id, product_id, qty) VALUES (500, 5, 7, 1)"]))
    assert r["ok"], r["reasons"]


def test_several_speaker_ids_count_as_own(db):
    # calibration only: DySQL's classifier can match more than one person row (same-name customers)
    c = {**cand("I am a5 b5. Set qty of order 9 to 3.", ["UPDATE orders SET qty = 3 WHERE order_id = 9"], key_value=None),
         "speaker_ids": [["customers", "5"], ["customers", "9"]]}
    r = check.run_check(db, c)
    assert r["task_type"] == "1_self" and r["writes"][0]["label"] == "own"


def test_literal_formats_dates_booleans_words_and_strftime():
    ok = check.literal_ok
    assert ok("2024-06-19", "book it for June 19, 2024 please", set())
    assert ok("2024-06-19 19:00:00", "on 19 June 2024 at 19:00", set())
    assert ok("true", "mark the credit as credited", set()) and ok("FALSE", "x", set())
    assert ok("3", "my three most recent rentals", set())
    assert ok("%Y", "matches played in 1999", set())
    assert not ok("2024-06-20", "book it for June 19, 2024", set())
    assert not ok("52000", "start him at a good salary", set())


# --- final review fixes ---

def test_trailing_comment_statement_is_checked(db):
    r = check.run_check(db, cand("I am a5 b5. Set qty of my order 5 to 3.", ["UPDATE orders SET qty = 3 WHERE order_id = 5 -- my order"]))
    assert r["ok"] and r["writes"][0]["rows"] == 1


def test_transaction_control_is_rejected_without_crashing(db):
    r = check.run_check(db, cand("I am a5 b5. Set qty of my order 5 to 3.", ["BEGIN; UPDATE orders SET qty = 3 WHERE order_id = 5; COMMIT;"]))
    assert not r["ok"] and any(x.startswith("txn_control") for x in r["reasons"])


def test_run_check_safe_records_a_crash():
    r = check.run_check_safe({"anchors": []}, {"id": "x", "instruction": "i", "actions": [{"sql": "UPDATE a SET b = 1"}], "anchor_table": "t"})
    assert r["id"] == "x" and not r["ok"] and r["reasons"][0].startswith("crash:")


def test_write_after_leading_comment_or_cte_is_a_write(db):
    r = check.run_check(db, cand("I am a5 b5. Set qty of my order 5 to 3.", ["/* fix */ UPDATE orders SET qty = 3 WHERE order_id = 5"]))
    assert r["ok"] and r["writes"][0]["table"] == "orders"
    r = check.run_check(db, cand("I am a5 b5. Set qty of my order 5 to 3.",
                                 ["WITH x AS (SELECT 5 AS id) UPDATE orders SET qty = 3 WHERE order_id IN (SELECT id FROM x)"]))
    assert r["ok"] and r["writes"] == [{"op": "UPDATE", "table": "orders", "rows": 1, "label": "own"}]


def test_insert_values_with_subquery_is_not_archive(db):
    r = check.run_check(db, cand("I am a5 b5. Add a note to order 5 copying item 5's note.",
                                 ["INSERT INTO order_items (order_id, note) VALUES (5, (SELECT note FROM order_items WHERE item_id = 5))"]))
    assert r["ok"] and not r["difficulty"]["features"]["archive"]
    r = check.run_check(db, cand("I am a5 b5. Copy order item 5, keep the original.",
                                 ["INSERT INTO order_items (order_id, note) SELECT order_id, note FROM order_items WHERE item_id = 5"]))
    assert not r["difficulty"]["features"]["archive"]     # nothing changed in the source afterwards
