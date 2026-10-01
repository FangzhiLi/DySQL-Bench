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


# --- v2: whole-token literals, ordinal words ---

def test_literal_must_be_a_whole_token():
    ok = check.literal_ok
    assert not ok("203", "card 2030 has the wrong date", set())
    assert not ok("2", "in the 2016 season", set())
    assert not ok("ann", "my name is joanna", set())
    assert ok("2030", "card 2030 has the wrong date", set())


def test_ordinal_words_count_as_numbers():
    ok = check.literal_ok
    assert ok("2", "the run out in the second innings", set())
    assert ok("3", "my third order", set())
    assert ok("3", "the 3rd over", set())          # a digit with a suffix was already read as a number


def test_literals_next_to_punctuation_still_match():
    ok = check.literal_ok
    assert ok("o'brien", "change the owner to O'Brien's brother", set())
    assert ok("C00003174", "client C00003174, please", set())
    assert ok("Bozeman", "move him to Bozeman.", set())
    assert ok("$5 million", "set my net worth to '$5 million'", set())


# --- v2: keys SQLite would assign need not be spoken ---

def test_auto_assigned_key_need_not_be_spoken(db):
    # orders are 0..99, so SQLite would give a new order 100; the item that refers to the new order may say 100 too
    r = check.run_check(db, cand("I am a5 b5. Place a new order of product 7, qty 2, with the note gift.",
                                 ["INSERT INTO orders (order_id, customer_id, product_id, qty) VALUES (100, 5, 7, 2)",
                                  "INSERT INTO order_items (order_id, note) VALUES (100, 'gift')"]))
    assert r["ok"], r["reasons"]


def test_a_key_sqlite_would_not_assign_must_be_spoken(db):
    r = check.run_check(db, cand("I am a5 b5. Place a new order of product 7, qty 2.",
                                 ["INSERT INTO orders (order_id, customer_id, product_id, qty) VALUES (150, 5, 7, 2)"]))
    assert r["reasons"] == ["literal_missing: '150' in INSERT orders"]


def test_auto_key_lookup_ignores_table_name_case(db):
    r = check.run_check(db, cand("I am a5 b5. Place a new order of product 7, qty 2.",
                                 ['INSERT INTO "ORDERS" (order_id, customer_id, product_id, qty) VALUES (100, 5, 7, 2)']))
    assert r["ok"], r["reasons"]


def test_several_new_rows_get_consecutive_auto_keys(db):
    r = check.run_check(db, cand("I am a5 b5. Add two new orders of product 7 for me.",
                                 ["INSERT INTO orders (order_id, customer_id, product_id, qty) VALUES (100, 5, 7, 1), (101, 5, 7, 1)"]))
    assert r["ok"], r["reasons"]


# --- v2: gold that reads the clock or random() ---

RENTAL = """
CREATE TABLE customers (customer_id INTEGER PRIMARY KEY, first_name TEXT, last_name TEXT);
CREATE TABLE rental (rental_id INTEGER PRIMARY KEY, customer_id INTEGER REFERENCES customers(customer_id),
                     return_date TEXT, last_update TEXT);
""" + rows("customers", 10, lambda i: f"{i},'a{i}','b{i}'") + rows("rental", 20, lambda i: f"{i},{i % 10},NULL,'2006-02-15'")
RENTAL_FKS = [{"table": "rental", "col": "customer_id", "ref_table": "customers", "ref_col": "customer_id", "hit": 1.0, "source": "declared"}]
RENTAL_CUSTOMER = {**CUSTOMER, "rows": 10, "down": ["rental"], "up": [], "update_targets": ["customers", "rental"]}


@pytest.fixture
def rental(tmp_path):
    return {"source": "test", "db": "rental", "path": make_db(tmp_path, "rental", RENTAL), "anchors": [RENTAL_CUSTOMER], "fks": RENTAL_FKS}


def test_clock_value_in_a_compared_column_is_rejected(rental):
    r = check.run_check(rental, cand("I am a5 b5. Mark my rental 5 as returned right now.",
                                     ["UPDATE rental SET return_date = CURRENT_TIMESTAMP WHERE rental_id = 5"]))
    assert r["reasons"] == ["nondeterministic: rental"]


def test_clock_value_in_a_volatile_column_passes(rental):     # the eval hash skips last_update (pagila)
    r = check.run_check(rental, cand("I am a5 b5. Set the return date of my rental 5 to 2024-01-02.",
                                     ["UPDATE rental SET return_date = '2024-01-02', last_update = CURRENT_TIMESTAMP WHERE rental_id = 5"]))
    assert r["ok"], r["reasons"]


def test_date_only_clock_value_passes(rental):                # same value all day (fails only across UTC midnight)
    r = check.run_check(rental, cand("I am a5 b5. Mark my rental 5 as returned today.",
                                     ["UPDATE rental SET return_date = CURRENT_DATE WHERE rental_id = 5"]))
    assert r["ok"], r["reasons"]


def test_random_value_is_rejected(rental):
    r = check.run_check(rental, cand("I am a5 b5. Give my rental 5 a random return code.",
                                     ["UPDATE rental SET return_date = abs(random()) WHERE rental_id = 5"]))
    assert r["reasons"] == ["nondeterministic: rental"]


def test_clock_value_with_a_failing_statement_is_not_rerun(rental):
    r = check.run_check(rental, cand("I am a5 b5. Mark my rental 5 as returned right now.",
                                     ["UPDATE rental SET return_date = CURRENT_TIMESTAMP WHERE rental_id = 5", "UPDATE nope SET a = 1"]))
    assert any(x.startswith("sql_error") for x in r["reasons"]) and not any(x.startswith("nondeterministic") for x in r["reasons"])


def test_snapshot_quotes_names_and_skips_volatile_columns(tmp_path):
    c = sqlite3.connect(make_db(tmp_path, "s", 'CREATE TABLE "Sales Orders" (id INTEGER PRIMARY KEY, "Order Date" TEXT, last_update TEXT);'
                                              "INSERT INTO \"Sales Orders\" VALUES (2, 'b', 'x'), (1, 'a', 'y');"))
    assert check.snapshot(c, {"Sales Orders"}) == {"Sales Orders": [(1, "a"), (2, "b")]}


def test_volatile_columns_match_the_eval():
    from dysql_bench.envs.base import VOLATILE_COL_RE
    assert check.VOLATILE_COL_RE.pattern == VOLATILE_COL_RE.pattern
