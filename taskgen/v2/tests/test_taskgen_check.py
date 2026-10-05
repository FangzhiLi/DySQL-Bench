# tests/test_taskgen_check.py
import re, sqlite3, time
import pytest
from taskgen_common.testing import make_db, SHOP, rows
from test_taskgen_trees import SHOP2, FKS, CUSTOMER
from v2_fixtures import SHOP_PROFILE, SCHOOL, SCHOOL_FKS, SCHOOL_COMPOSITE, SCHOOL_PROFILE, MENUS, MENUS_FKS, MENUS_PROFILE
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


# --- v2: a new person row is nobody's data yet ---

def test_new_person_row_is_not_another_persons_data(db):
    r = check.run_check(db, cand("I am a5 b5. Please register my friend Zoe Quinn as a customer.",
                                 ["INSERT INTO customers (customer_id, first_name, last_name) VALUES (60, 'Zoe', 'Quinn')"]))
    assert r["ok"], r["reasons"]
    assert r["writes"][0]["label"] == "new_person" and r["task_type"] == "3_public_only"
    r = check.run_check(db, cand("I am a5 b5. Register my friend Zoe Quinn as a customer and set qty of my order 5 to 3.",
                                 ["INSERT INTO customers (customer_id, first_name, last_name) VALUES (60, 'Zoe', 'Quinn')",
                                  "UPDATE orders SET qty = 3 WHERE order_id = 5"]))
    assert r["task_type"] == "2_self_and_public"


def test_proxy_registering_a_person_is_unchanged(db):
    r = check.run_check(db, cand("I am Pat, an analyst. Register Zoe Quinn as a customer.",
                                 ["INSERT INTO customers (customer_id, first_name, last_name) VALUES (60, 'Zoe', 'Quinn')"],
                                 task_type="5_proxy"))
    assert r["writes"][0]["label"] == "person_obj" and r["task_type"] == "5_proxy"


# --- final review: the rerun replays every statement that ran, DDL included ---

def test_clock_value_after_ddl_in_a_volatile_column_passes(rental):
    r = check.run_check(rental, cand("I am a5 b5. Add a note column and mark my rental 5 as late.",
                                     ["ALTER TABLE rental ADD COLUMN note TEXT",
                                      "UPDATE rental SET note = 'late', last_update = CURRENT_TIMESTAMP WHERE rental_id = 5"]))
    assert r["ok"], r["reasons"]


def test_clock_value_after_ddl_in_a_compared_column_is_rejected(rental):
    r = check.run_check(rental, cand("I am a5 b5. Add a note column and stamp my rental 5 with the current time.",
                                     ["ALTER TABLE rental ADD COLUMN note TEXT",
                                      "UPDATE rental SET note = CURRENT_TIMESTAMP WHERE rental_id = 5"]))
    assert r["reasons"] == ["nondeterministic: rental"]


# --- plan 2: checks that read the database profile ---

@pytest.fixture
def school(tmp_path):
    return {"source": "test", "db": "school", "path": make_db(tmp_path, "school", SCHOOL), "anchors": [],
            "fks": SCHOOL_FKS, "fks_composite": SCHOOL_COMPOSITE}


def scand(instruction, sqls, task_type="1_self", key_value=3):
    return {"id": "s", "anchor_table": "Student List", "anchor_key": "sid", "key_value": key_value,
            "plan": {"task_type": task_type}, "instruction": instruction, "actions": [{"sql": s} for s in sqls]}


def test_profile_edges_decide_ownership(school):
    r = check.run_check(school, scand("I am s3. Drop my advisor t0.", ["DELETE FROM advisor WHERE s_id = '3'"]), profile=SCHOOL_PROFILE)
    assert r["ok"], r["reasons"]
    assert r["writes"] == [{"op": "DELETE", "table": "advisor", "rows": 1, "label": "own"}] and r["task_type"] == "1_self"


def test_profile_rejects_another_persons_data(school, db):
    r = check.run_check(school, scand("I am s3. Rename teacher 1 to Tao.", ["UPDATE teacher SET name = 'Tao' WHERE tid = 1"]),
                        profile=SCHOOL_PROFILE)
    assert r["reasons"] == ["other_person"] and r["task_type"] == "4_other_person"
    c = cand("I am a5 b5. Set qty of order 9 to 3.", ["UPDATE orders SET qty = 3 WHERE order_id = 9"])
    assert check.run_check(db, c)["ok"]                                       # without a profile, as in v1
    assert check.run_check(db, c, profile=SHOP_PROFILE)["reasons"] == ["other_person"]


def test_profile_scope_and_no_insert(school):
    r = check.run_check(school, scand("I am s3. Add the day 2024-01-03.", ["INSERT INTO calendar VALUES ('2024-01-03')"]),
                        profile=SCHOOL_PROFILE)
    assert r["reasons"] == ["out_of_scope: calendar"]
    r = check.run_check(school, scand("I am s3. Open section c2 2 called Biology.", ["INSERT INTO section VALUES ('c2', 2, 'Biology')"]),
                        profile=SCHOOL_PROFILE)
    assert r["reasons"] == ["no_insert: section"]


def test_profile_speaker_must_be_a_root(school):
    c = {**scand("I am t0.", ["UPDATE teacher SET name = 'Tao' WHERE tid = 0"]), "anchor_table": "teacher", "key_value": 0}
    assert check.run_check_safe(school, c, profile=SCHOOL_PROFILE)["reasons"][0].startswith("crash: ValueError: teacher is not a root")


def test_replacing_or_upserting_an_existing_person_is_not_a_new_person(db):
    r = check.run_check(db, cand("I am a5 b5. Customer 9 is now Zed Quinn.",
                                 ["INSERT OR REPLACE INTO customers (customer_id, first_name, last_name) VALUES (9, 'Zed', 'Quinn')"]))
    assert r["writes"][0]["label"] == "other" and r["task_type"] == "4_other_person"
    r = check.run_check(db, cand("I am a5 b5. Customer 9 is now Zed.",
                                 ["INSERT INTO customers (customer_id, first_name, last_name) VALUES (9, 'Zed', 'b9') "
                                  "ON CONFLICT(customer_id) DO UPDATE SET first_name = excluded.first_name"]))
    assert r["writes"][0]["label"] == "other"


def test_auto_key_is_what_sqlite_would_assign_at_that_point(db):
    # orders run 0..99 and order 99 is customer 39's: once it is deleted, SQLite gives a new order 99, not 100
    r = check.run_check(db, cand("I am a39 b39. Cancel my order 99 and place a new order of product 7, qty 2.",
                                 ["DELETE FROM orders WHERE order_id = 99",
                                  "INSERT INTO orders (order_id, customer_id, product_id, qty) VALUES (100, 39, 7, 2)"], key_value=39))
    assert r["reasons"] == ["literal_missing: '100' in INSERT orders"]


def test_auto_key_for_a_table_written_in_another_case(tmp_path):
    path = make_db(tmp_path, "shop3", SHOP2 + "CREATE TABLE Logs (log_id INTEGER PRIMARY KEY, note TEXT);" + rows("Logs", 3, lambda i: f"{i},'x'"))
    rec = {"source": "test", "db": "shop3", "path": path, "anchors": [CUSTOMER, STAFF_ANCHOR], "fks": FKS}
    r = check.run_check(rec, cand("I am a5 b5. Log the note hello.", ["INSERT INTO logs (log_id, note) VALUES (3, 'hello')"]))
    assert r["reasons"] == ["out_of_scope: logs"]                  # 3 is what SQLite would give: no literal is missing


def test_ctrl_c_in_the_rerun_is_not_swallowed(rental, monkeypatch):
    def interrupted(stmt, instant):
        raise KeyboardInterrupt
    monkeypatch.setattr(check, "at_instant", interrupted)
    with pytest.raises(KeyboardInterrupt):
        check.run_check_safe(rental, cand("I am a5 b5. Mark my rental 5 as returned right now.",
                                          ["UPDATE rental SET return_date = CURRENT_TIMESTAMP WHERE rental_id = 5"]))


# --- plan 3: literal rules and clock readings left over from plan 1 ---

def test_plurals_and_units_after_numbers_match():
    ok = check.literal_ok
    assert ok("cup", "add 2 cups of flour", set()) and ok("box", "ship three boxes", set())
    assert ok("g", "use 10g of salt", set()) and ok("ml", "add 20ml of lime juice", set())
    assert not ok("ml", "the html page", set()) and not ok("203", "card 12030", set())
    assert not ok("cup", "the cupboard", set())


def test_a_number_glued_to_letters_on_its_left_does_not_count():
    ok = check.literal_ok
    assert not ok("3174", "client C00003174, please", set())
    assert ok("3174", "invoice #3174, please", set()) and ok("3174", "3174kg of steel", set())


def test_clock_readings_without_a_time_value_are_nondeterministic():
    for sql in ["UPDATE r SET d = date()", "UPDATE r SET d = datetime( )", "UPDATE r SET d = julianday()",
                "UPDATE r SET d = strftime('%Y-%m-%d %H:%M')", "UPDATE r SET d = time()"]:
        assert check.NONDET.search(sql), sql
    for sql in ["UPDATE r SET d = date('2024-01-02')", "UPDATE r SET d = strftime('%Y', d)"]:
        assert not check.NONDET.search(sql), sql


def test_at_instant_replaces_every_clock_reading():
    sql = ("UPDATE r SET a = CURRENT_TIMESTAMP, b = current_date, c = CURRENT_TIME, d = datetime('now', 'localtime'), "
           "e = date(), f = strftime('%H:%M'), g = 'nowhere'")
    assert check.at_instant(sql, "2000-01-01 13:37:42") == (
        "UPDATE r SET a = '2000-01-01 13:37:42', b = '2000-01-01', c = '13:37:42', "
        "d = datetime('2000-01-01 13:37:42', 'localtime'), e = date('2000-01-01 13:37:42'), "
        "f = strftime('%H:%M', '2000-01-01 13:37:42'), g = 'nowhere'")


def test_minute_precise_clock_value_is_rejected_without_waiting(rental):
    t0 = time.time()
    r = check.run_check(rental, cand("I am a5 b5. Stamp my rental 5 with the current minute, as of now.",
                                     ["UPDATE rental SET return_date = strftime('%Y-%m-%d %H:%M', 'now') WHERE rental_id = 5"]))
    assert r["reasons"] == ["nondeterministic: rental"] and time.time() - t0 < 1
    r = check.run_check(rental, cand("I am a5 b5. Mark my rental 5 as returned today.",
                                     ["UPDATE rental SET return_date = date() WHERE rental_id = 5"]))
    assert r["ok"], r["reasons"]


def test_a_write_that_also_changes_the_archived_copy_is_rejected(db):
    # the copy is the original but for the key SQLite gives it, so a later write by any other condition hits it too;
    # an agent that leaves the copy alone would then miss the gold state
    copy = "INSERT INTO order_items (order_id, note) SELECT order_id, note FROM order_items WHERE item_id = 5"
    r = check.run_check(db, cand("I am a5 b5. Copy order item 5, then delete the original item 5.",
                                 [copy, "DELETE FROM order_items WHERE item_id = 5"]))
    assert r["ok"]
    note = sqlite3.connect(db["path"]).execute("SELECT order_id, note FROM order_items WHERE item_id = 5").fetchone()
    r = check.run_check(db, cand(f"I am a5 b5. Copy order item 5, then delete the items of order {note[0]}.",
                                 [copy, f"DELETE FROM order_items WHERE order_id = {note[0]}"]))
    assert "archive_copy_changed: DELETE order_items" in r["reasons"]
    r = check.run_check(db, cand(f"I am a5 b5. Copy order item 5, then set the note of order {note[0]}'s items to x.",
                                 [copy, f"UPDATE order_items SET note = 'x' WHERE order_id = {note[0]}"]))
    assert "archive_copy_changed: UPDATE order_items" in r["reasons"]


def test_changing_only_the_new_row_of_an_insert_select_is_fine(db):
    # v1's movie tasks build a new row from a SELECT and then edit that row by its key: on purpose, not a hit on a copy
    con = sqlite3.connect(db["path"])
    new_id = con.execute("SELECT MAX(item_id) + 1 FROM order_items").fetchone()[0]
    note = con.execute("SELECT note FROM order_items WHERE item_id = 5").fetchone()[0]
    r = check.run_check(db, cand(f"I am a5 b5. Copy order item 5 as item {new_id}, then set the note of item {new_id} to x.",
                                 [f"INSERT INTO order_items (item_id, order_id, note) SELECT {new_id}, order_id, note FROM order_items WHERE item_id = 5",
                                  f"UPDATE order_items SET note = 'x' WHERE item_id = {new_id}"]))
    assert not any(x.startswith("archive_copy_changed") for x in r["reasons"]), r["reasons"]


def test_final_state_compares_what_the_statements_leave_behind(tmp_path):
    db = make_db(tmp_path, "shop", SHOP + "CREATE TABLE tags (name TEXT, last_update TEXT); INSERT INTO tags VALUES ('a', 'x');")
    fs = lambda *s: check.final_state(db, list(s))
    assert fs("UPDATE orders SET qty = 3 WHERE order_id = 5") == fs("UPDATE orders SET qty = 3 WHERE order_id IN (5)")
    assert fs("UPDATE orders SET qty = 3 WHERE order_id = 5") != fs("UPDATE orders SET qty = 3 WHERE order_id = 6")
    assert fs("UPDATE orders SET qty = 3 WHERE order_id = 5") == {"orders": ([(5, 5, 5, 3)], [(5, 5, 5, 1)])}
    assert fs("UPDATE orders SET qty = 1 WHERE order_id = 5") == {"orders": ([], [])}          # touched, not changed
    assert fs("INSERT INTO tags VALUES ('a', 'y')") != fs("INSERT INTO tags VALUES ('a', 'y')", "INSERT INTO tags VALUES ('a', 'z')")
    assert fs("INSERT INTO tags VALUES ('b', 'y')") == fs("INSERT INTO tags VALUES ('b', 'z')")   # last_update is not compared
    assert fs("UPDATE nope SET x = 1") is None


def test_final_state_reads_the_clock_at_a_fixed_instant(tmp_path):
    db = make_db(tmp_path, "shop", SHOP + "CREATE TABLE notes (customer_id INTEGER, at TEXT);")
    a = check.final_state(db, ["INSERT INTO notes VALUES (5, CURRENT_TIMESTAMP)"])
    time.sleep(1.1)
    assert a == check.final_state(db, ["INSERT INTO notes VALUES (5, datetime('now'))"]) == {"notes": ([(5, check.INSTANTS[0])], [])}


def test_two_archive_copies_numbered_by_sqlite_are_rejected(db):
    # SQLite numbers the copies in statement order; an agent that copies both rows in one INSERT ... SELECT numbers
    # them in table order, so whether it matches the gold would hang on the order of two statements
    one = "INSERT INTO order_items (order_id, note) SELECT order_id, note FROM order_items WHERE item_id = {}"
    change = "UPDATE order_items SET note = 'x' WHERE item_id IN (5, 65)"
    ask = "I am a5 b5. Copy my order items 65 and 5, then set the note of items 5 and 65 to x."
    r = check.run_check(db, cand(ask, [one.format(65), one.format(5), change]))
    assert "archive_split: order_items" in r["reasons"]
    r = check.run_check(db, cand(ask, [one.format("65 OR item_id = 5"), change]))
    assert r["ok"], r["reasons"]
    new = sqlite3.connect(db["path"]).execute("SELECT MAX(item_id) + 1 FROM order_items").fetchone()[0]
    keyed = "INSERT INTO order_items (item_id, order_id, note) SELECT {}, order_id, note FROM order_items WHERE item_id = {}"
    r = check.run_check(db, cand(f"I am a5 b5. Copy items 65 and 5 as items {new} and {new + 1}, then set the note of items 5 and 65 to x.",
                                 [keyed.format(new, 65), keyed.format(new + 1, 5), change]))
    assert r["ok"], r["reasons"]        # the SQL states the copies' keys: nothing hangs on the order


def test_only_a_word_of_three_letters_or_more_takes_a_plural_ending():
    # 'M' matched "Ms" and let a gender value no one asked for pass; "cups" for 'cup' and "10g" for 'g' still match
    assert not check._contains("ms lee asked for it", "m") and not check._contains("fix its row", "it")
    assert check._contains("add 2 cups of rice", "cup") and check._contains("add 10g of salt", "g")


def test_a_double_quoted_now_reads_the_clock(rental):
    # SQLite reads "now" as the string 'now' when no column has that name, so datetime("now") is the current time
    r = check.run_check(rental, cand("I am a5 b5. Mark my rental 5 as returned right now.",
                                     ['UPDATE rental SET return_date = datetime("now") WHERE rental_id = 5']))
    assert r["reasons"] == ["nondeterministic: rental"]
    assert check.at_instant("UPDATE r SET d = datetime(\"NOW\", 'localtime')", "2000-01-01 13:37:42") == (
        "UPDATE r SET d = datetime('2000-01-01 13:37:42', 'localtime')")


@pytest.fixture
def menus(tmp_path):
    return {"source": "test", "db": "menus", "path": make_db(tmp_path, "menus", MENUS), "anchors": [], "fks": MENUS_FKS}


def mcand(instruction, sqls, speaker=None, key_value=3):
    style = {"tone": "x", "speaker": "name" if speaker else "none", "name": speaker, "role": None, "username": None}
    return {"id": "m", "anchor_table": "menu", "anchor_key": "menu_id", "key_value": key_value,
            "plan": {"task_type": "6_entity", "style": style}, "instruction": instruction, "actions": [{"sql": s} for s in sqls]}


def mreasons(menus, ins, sqls, profile=MENUS_PROFILE, **kw):
    return check.run_check(menus, mcand(ins, sqls, **kw), profile=profile)["reasons"]


def test_an_entity_task_on_its_own_rows_is_type_6(menus):
    r = check.run_check(menus, mcand("Menu ID 3: set the price of item 13 to 4.5 and add the year 2003 with 7 views.",
                                     ["UPDATE item SET price = 4.5 WHERE item_id = 13",
                                      "INSERT INTO menu_stats VALUES (3, 2003, 7)"]), profile=MENUS_PROFILE)
    assert r["ok"], r["reasons"]
    assert [w["label"] for w in r["writes"]] == ["own", "own"] and r["task_type"] == "6_entity"
    assert r["template"] == "6_entity|INSERT menu_stats+UPDATE item"


def test_an_entity_task_may_not_touch_another_entity_or_public_rows(menus):
    assert mreasons(menus, "Menu ID 3: set item 14 to 4.5.", ["UPDATE item SET price = 4.5 WHERE item_id = 14"]) == \
        ["other_person", "no_own_write"]                                               # item 14 is on menu 4's page
    assert mreasons(menus, "Menu ID 3: rename dish 3 to 'Tea' and set item 3 to 4.5.",
                    ["UPDATE dish SET name = 'Tea' WHERE dish_id = 3", "UPDATE item SET price = 4.5 WHERE item_id = 3"]) == \
        ["public_write: UPDATE dish"]
    assert mreasons(menus, "Menu ID 3: add menu 10 called 'New'.", ["INSERT INTO menu (menu_id, name) VALUES (10, 'New')"]) == \
        ["root_insert: menu", "no_own_write"]


def test_a_new_lookup_row_must_be_new_and_used_by_the_entity(menus):
    ok = check.run_check(menus, mcand("Menu ID 3: add the dish 'Smoked Trout' and put it on item 13.",
                                      ["INSERT INTO dish (name) VALUES ('Smoked Trout')",
                                       "UPDATE item SET dish_id = (SELECT dish_id FROM dish WHERE name = 'Smoked Trout') WHERE item_id = 13"]),
                         profile=MENUS_PROFILE)
    assert ok["ok"], ok["reasons"]
    assert [w["label"] for w in ok["writes"]] == ["public", "own"] and ok["task_type"] == "6_entity"
    assert mreasons(menus, "Menu ID 3: add the dish 'Smoked Trout' and set item 13 to 4.5.",
                    ["INSERT INTO dish (name) VALUES ('Smoked Trout')", "UPDATE item SET price = 4.5 WHERE item_id = 13"]) == \
        ["lookup_unreferenced: dish"]
    assert mreasons(menus, "Menu ID 3: add the dish 'Dish 5' and put it on item 13.",      # 'dish 5' exists
                    ["INSERT INTO dish (name) VALUES ('Dish 5')", "UPDATE item SET dish_id = 30 WHERE item_id = 13"]) == \
        ["lookup_name_taken: dish"]
    assert mreasons(menus, "Menu ID 3: add the dish 'Smoked Trout' and put it on item 13.",
                    ["INSERT INTO dish (name) VALUES ('Smoked Trout')", "UPDATE item SET dish_id = 30 WHERE item_id = 13"],
                    profile={**MENUS_PROFILE, "new_lookup": []}) == ["public_write: INSERT dish"]


def test_a_new_lookup_row_may_hang_under_the_root_itself(menus):
    # video_games game.genre_id -> genre.id: the root row is the entity's own, so it uses the new row
    r = check.run_check(menus, mcand("Menu ID 3: add the dish 'Smoked Trout' and make it the house dish.",
                                     ["INSERT INTO dish (name) VALUES ('Smoked Trout')",
                                      "UPDATE menu SET house_dish = 30 WHERE menu_id = 3"]), profile=MENUS_PROFILE)
    assert r["ok"], r["reasons"]


def test_a_sampled_speaker_name_stored_in_the_database_is_rejected(menus):
    ins, sql = "I'm {} and menu ID 3 is mine: set the price of item 13 to 4.5.", ["UPDATE item SET price = 4.5 WHERE item_id = 13"]
    assert mreasons(menus, ins.format("Grace Kim"), sql, speaker="Grace Kim") == ["speaker_name_taken"]
    assert mreasons(menus, ins.format("Grace Kimura"), sql, speaker="Grace Kimura") == []


def test_a_quoted_name_of_another_row_is_a_mismatch(menus):
    sql = ["UPDATE item SET price = 4.5 WHERE item_id = 13"]
    assert mreasons(menus, "Menu ID 3, 'Menu 3': on item 13 ('dish 13') set the price to 4.5.", sql) == []
    assert mreasons(menus, "Menu ID 3, 'Menu 3': on item 13 ('dish 14') set the price to 4.5.", sql) == ["name_mismatch: dish.name"]
    assert mreasons(menus, "Menu ID 3, 'Menu 4': set the price of item 13 to 4.5.", sql) == ["name_mismatch: menu.name"]
    # the old dish is the item's parent before the change; a new name the SQL writes is no claim about a row
    assert mreasons(menus, "Menu ID 3: on item 13, replace 'dish 13' with dish 5.", ["UPDATE item SET dish_id = 5 WHERE item_id = 13"]) == []
    assert mreasons(menus, "Menu ID 3: rename it to 'Menu 4'.", ["UPDATE menu SET name = 'Menu 4' WHERE menu_id = 3"]) == []
    assert mreasons(menus, "I'm Ann and it's menu ID 3's item 13: set its price to 4.5.", sql) == []   # apostrophes
    assert mreasons(menus, "Menu ID 3 at 'Venue 3': set the price of item 13 to 4.5.", sql) == []     # the root's attribute row
    assert mreasons(menus, "Menu ID 3: item 13 is a 'cuisine 1' dish; set its price to 4.5.", sql) == []   # item -> dish -> cuisine
    assert mreasons(menus, "Menu ID 3: item 13 is a 'cuisine 2' dish; set its price to 4.5.", sql) == ["name_mismatch: cuisine.name"]
    assert check.quoted("I'm Ann, it's 'Menu 3' and “dish 2”") == {"menu 3", "dish 2"}


def test_name_columns_are_names_and_titles_only(tmp_path):
    db = sqlite3.connect(make_db(tmp_path, "nc", "CREATE TABLE b (business_id INTEGER, name TEXT, owner_name TEXT, owner_city TEXT, "
                                 "owner_zip TEXT, name_id TEXT, LongTitle TEXT, price_name REAL);"))
    assert check.name_columns(db, ["b"]) == [("b", "name"), ("b", "owner_name"), ("b", "LongTitle")]


def test_a_row_wider_than_sqlite_function_arguments_is_still_recorded(tmp_path):
    cols = ", ".join(f"c{i} TEXT" for i in range(70))         # card_games.cards has 74 columns; a function takes 127 arguments
    path = make_db(tmp_path, "wide", f"CREATE TABLE card (id INTEGER PRIMARY KEY, name TEXT, {cols});"
                   "INSERT INTO card (id, name) VALUES (1, 'Lotus'), (2, 'Bolt');")
    prof = {"kind": "entity", "roots": [{"table": "card", "label": "card", "parents": []}],
            "persons": {"card": {"key": "id", "name_cols": ["name"], "same_as": []}}, "events": [], "attributes": [],
            "public": [], "exclude": [], "no_insert": [], "quirks": [], "description": "Cards.", "confirmed": True,
            "speaker_roles": ["a", "b", "c", "d"]}
    c = {"id": "w", "anchor_table": "card", "anchor_key": "id", "key_value": 1, "plan": {"task_type": "6_entity", "style": {}},
         "instruction": "Card ID 1, 'Lotus': set c69 to 'x1'.", "actions": [{"sql": "UPDATE card SET c69 = 'x1' WHERE id = 1"}]}
    r = check.run_check({"source": "test", "db": "wide", "path": path, "anchors": [], "fks": []}, c, profile=prof)
    assert r["ok"], r["reasons"]


def test_an_entity_task_may_not_upsert(menus):
    # REPLACE / ON CONFLICT on a shared row renames another menu's dish; on an item it takes over menu 4's item 14
    assert "upsert: dish" in mreasons(menus, "Menu ID 3: dish 5 becomes 'Owl Soup' and goes on item 13.",
                                      ["INSERT OR REPLACE INTO dish (dish_id, name) VALUES (5, 'Owl Soup')",
                                       "UPDATE item SET dish_id = 5 WHERE item_id = 13"])
    assert "upsert: item" in mreasons(menus, "Menu ID 3: item 14 goes on page 13 with dish 5 at 2.0.",
                                      ["INSERT OR REPLACE INTO item (item_id, page_id, dish_id, price) VALUES (14, 13, 5, 2.0)"])
    assert "upsert: dish" in mreasons(menus, "Menu ID 3: dish 5 becomes 'Owl Soup' and goes on item 13.",
                                      ["INSERT INTO dish (dish_id, name) VALUES (5, 'Owl Soup') ON CONFLICT (dish_id) DO UPDATE SET name = 'Owl Soup'",
                                       "UPDATE item SET dish_id = 5 WHERE item_id = 13"])


def test_moving_another_entitys_row_to_this_one_is_another_persons_data(menus):
    # item 14 is on menu 4's page 14; moving it onto menu 3's page 13 takes it from menu 4
    assert mreasons(menus, "Menu ID 3: move item 14 to page 13.", ["UPDATE item SET page_id = 13 WHERE item_id = 14"]) == ["other_person", "no_own_write"]


def test_name_mismatch_also_reads_the_profiles_own_name_columns(menus, monkeypatch):
    # Menu.sponsor, Air Carriers.Description, generalinfo.label: the root's names need not match NAME_COL
    monkeypatch.setattr(check, "NAME_COL", re.compile(r"^$"))
    assert mreasons(menus, "Menu ID 3, 'Menu 4': set the price of item 13 to 4.5.",
                    ["UPDATE item SET price = 4.5 WHERE item_id = 13"]) == ["name_mismatch: menu.name"]
    assert mreasons(menus, "Menu ID 3: item 13 is 'dish 14' now priced 4.5.",
                    ["UPDATE item SET price = 4.5 WHERE item_id = 13"]) == ["name_mismatch: dish.name"]   # a new_lookup name column
