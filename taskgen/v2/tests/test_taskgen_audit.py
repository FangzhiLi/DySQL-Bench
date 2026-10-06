# tests/test_taskgen_audit.py -- the audit of finished tasks (2026-10-06)
import pytest
from taskgen_common.testing import make_db, rows
from taskgen_v2 import audit, check

SHOP = """
CREATE TABLE customers (customer_id INTEGER PRIMARY KEY, first_name TEXT, last_name TEXT, status TEXT);
CREATE TABLE orders (order_id INTEGER PRIMARY KEY, customer_id INTEGER REFERENCES customers(customer_id), status TEXT,
                     order_date TEXT, amount REAL);
CREATE TABLE lines (line_id INTEGER PRIMARY KEY, order_id INTEGER REFERENCES orders(order_id), qty INTEGER);
INSERT INTO customers VALUES (1, 'Ann', 'Lee', 'active'), (2, 'Bob', 'Ray', 'active'), (3, 'Ann', 'Lee', 'closed');
INSERT INTO orders VALUES (110, 1, 'Pending', '2020-01-05', 50.0), (111, 1, 'Pending', '2020-01-06', 60.0),
                          (112, 2, 'Shipped', '2020-01-07', 70.0);
INSERT INTO lines VALUES (1, 110, 2), (2, 111, 1), (3, 112, 5);
CREATE TABLE colour (id INTEGER PRIMARY KEY, colour_name TEXT);
INSERT INTO colour VALUES (1, 'Red'), (2, 'Silver'), (3, 'Blue');
CREATE TABLE tickets (ticket_no TEXT, book TEXT);
CREATE TABLE segs (ticket_no TEXT REFERENCES tickets(ticket_no), flight INTEGER);
INSERT INTO tickets VALUES ('T1', 'A'), ('T2', 'B'); INSERT INTO segs VALUES ('T1', 7), ('T2', 8);
CREATE TABLE dup (id INTEGER PRIMARY KEY, v TEXT);
INSERT INTO dup VALUES (1, 'a'), (2, 'a'), (3, 'b');
""" + rows("customers", 30, lambda i: f"{i + 10},'f{i}','g{i}','{['active', 'closed'][i % 2]}'") \
    + rows("orders", 40, lambda i: f"{i + 200},{10 + i % 30},'{['Shipped', 'Pending'][i % 2]}','2020-02-{i % 28 + 1:02d}',10.0")


@pytest.fixture
def shop(tmp_path):
    return audit.DbAudit(make_db(tmp_path, "shop", SHOP))


def kinds(flags):
    return sorted({f["k"] for f in flags})


def test_where_terms_split_at_top_level_and_keep_between_whole():
    st = "UPDATE t SET a = 'x AND y' WHERE x = 1 AND y BETWEEN 2 AND 3 AND z IN (SELECT q FROM r WHERE s = 1 AND u = 2)"
    assert audit.where_conjuncts(st) == ["x = 1", "y BETWEEN 2 AND 3", "z IN (SELECT q FROM r WHERE s = 1 AND u = 2)"]
    assert audit.where_conjuncts("DELETE FROM t WHERE a = 1 OR b = 2") == ["a = 1 OR b = 2"]
    assert audit.where_conjuncts("UPDATE t SET a = 1") is None


def test_claims_take_the_value_a_record_is_said_to_hold_now():
    assert audit.claims("lower the booking total from 51,600 to 48300") == ["51600"]
    assert audit.claims("ticket 0005432646197 currently shows passport '5740 173123', a typo") == ["5740 173123"]
    assert audit.claims("set the S18_1129 line from line 13 to line 12") == ["13"]
    assert audit.claims("delete flight 318 from ticket 0005433570752") == []
    assert audit.claims("my grade shows 71.09 instead of the 78.40 on my transcript") == ["71.09"]
    assert audit.claims("my role is listed as Deacon 'Deke' Kaye, but it should be Deacon Kaye") == []
    assert audit.claims("the age should read 30 instead of 29") == ["29"]
    assert audit.claims("country 85 currently reads 'Guinea' and should be recorded as 'Republic of Guinea'") == ["Guinea"]
    assert audit.claims("the page title should read 'Rebel in the Rye' instead, and the source says 'X'") == []
    assert audit.claims("update my account so addressLine1 reads 'Erling 80' instead of the old street") == []
    assert audit.claims("set the description to 'Models produced from 1910 to 1960.' please") == []


def test_copy_order_is_reported_only_when_the_instruction_lists_rows_the_other_way():
    assert audit.order_mismatch(["10152", "10174"], "copy orders 10174 and 10152") == ["10152", "10174"]
    assert audit.order_mismatch(["10152", "10174"], "copy orders 10152 and 10174") is None
    assert audit.order_mismatch(["10152", "10174"], "copy all my orders") is None


def test_given_values_that_select_more_rows_than_the_gold_changes(shop):
    flags, stats = shop.run("Ann Lee, customer 1: please cancel my pending order.",
                            ["UPDATE orders SET status = 'Shipped' WHERE customer_id = 1 AND status = 'Pending' AND order_id = 110"],
                            allowed={"1", "ann", "lee", "active"})
    f = next(x for x in flags if x["k"] == "instr_matches_more")
    assert (f["given"], f["gold"]) == (2, 1)
    assert stats["stmts_with_where"] == 1 and "stmts_self_contained" not in stats


def test_a_self_contained_statement_is_not_flagged(shop):
    flags, stats = shop.run("Customer 1 here: order 110 should be marked Shipped.",
                            ["UPDATE orders SET status = 'Shipped' WHERE customer_id = 1 AND order_id = 110"], allowed={"1"})
    assert flags == [] and stats["stmts_self_contained"] == 1


def test_where_broader_than_the_key_the_instruction_names(shop):
    flags, _ = shop.run("Customer 2 here: order 112 should be marked Pending.",
                        ["UPDATE orders SET status = 'Pending' WHERE customer_id = 2"], allowed={"2"})
    assert kinds(flags) == ["where_broader"] and flags[0]["values"] == ["112"]


def test_a_new_row_that_points_nowhere(shop):
    flags, _ = shop.run("Add a line of 1 to order 999.", ["INSERT INTO lines (order_id, qty) VALUES (999, 1)"])
    assert kinds(flags) == ["dangling_fk"] and flags[0]["parent"] == "orders"


def test_a_row_inserted_and_deleted_again_does_not_dangle(shop):
    flags, _ = shop.run("x", ["INSERT INTO lines (line_id, order_id, qty) VALUES (50, 999, 1)", "DELETE FROM lines WHERE line_id = 50"])
    assert flags == []


def test_a_whole_number_in_a_real_column_is_not_a_type_mismatch(shop):
    assert shop.run("Order 110 costs 75.", ["UPDATE orders SET amount = 75 WHERE order_id = 110"])[0] == []


def test_a_stated_current_value_the_record_does_not_hold(shop):
    sql = ["UPDATE orders SET amount = 65 WHERE order_id = 110"]
    assert kinds(shop.run("Change the amount on order 110 from 55 to 65.", sql)[0]) == ["claim_not_found"]
    assert shop.run("Change the amount on order 110 from 50 to 65.", sql)[0] == []


def test_written_values_unlike_the_column(shop):
    flags, _ = shop.run("Customer 2: set my status to Active.", ["UPDATE customers SET status = 'Active' WHERE customer_id = 2"])
    assert kinds(flags) == ["case_mismatch"]
    flags, _ = shop.run("Order 110's date is 05/01/2020.", ["UPDATE orders SET order_date = '05/01/2020' WHERE order_id = 110"])
    assert kinds(flags) == ["format_shape"]


def test_copies_numbered_in_another_order_than_the_instruction_lists(shop):
    st = ("INSERT INTO orders (customer_id, status, order_date, amount) "
          "SELECT customer_id, status, order_date, amount FROM orders WHERE order_id IN (110, 111)")
    flags, _ = shop.run("Customer 1: copy orders 111 and 110 as new orders.", [st])
    assert kinds(flags) == ["copy_order"]
    assert shop.run("Customer 1: copy orders 110 and 111 as new orders.", [st])[0] == []


def test_the_database_is_unchanged_after_a_task(shop):
    shop.run("x", ["DELETE FROM lines WHERE line_id = 1", "UPDATE orders SET amount = 1 WHERE order_id = 110"])
    assert shop.conn.execute("SELECT COUNT(*), SUM(qty) FROM lines").fetchone() == (3, 8)
    assert shop.conn.execute("SELECT amount FROM orders WHERE order_id = 110").fetchone() == (50.0,)


def test_identity_missing_ambiguous_or_another_persons_name(shop):
    idx = audit.name_index(shop.conn, "customers", ["first_name", "last_name"])
    ident = lambda kv, text: kinds(audit.identity(shop.conn, "customers", "customer_id", kv, ["first_name", "last_name"], text, idx))
    assert ident(3, "Ann Lee here, please close my account.") == ["identity_ambiguous"]
    assert ident(1, "I'm Bob Ray, customer 1, close my account.") == ["identity_other_name"]
    assert ident(2, "Please close my account.") == ["identity_missing"]
    assert ident(2, "Bob Ray, customer 2: close my account.") == []


def test_a_key_renumbered_onto_one_another_row_holds(shop):
    flags, _ = shop.run("Booking A: renumber ticket T1 to T2.", ["UPDATE tickets SET ticket_no = 'T2' WHERE ticket_no = 'T1'"])
    assert kinds(flags) == ["key_collision"] and flags[0]["value"] == "T2"


def test_an_update_that_changes_nothing(shop):
    flags, _ = shop.run("Customer 1: my status is wrong, set it to active.", ["UPDATE customers SET status = 'active' WHERE customer_id = 1"])
    assert kinds(flags) == ["noop_update"]


def test_a_name_a_lookup_already_holds(shop):
    flags, _ = shop.run("Add the colour silver.", ["INSERT INTO colour (colour_name) VALUES ('silver')"])
    assert kinds(flags) == ["duplicate_name"]
    assert shop.run("Add the colour Green.", ["INSERT INTO colour (colour_name) VALUES ('Green')"])[0] == []
    assert shop.run("Re-enter Silver.", ["DELETE FROM colour WHERE id = 2", "INSERT INTO colour (colour_name) VALUES ('Silver')"])[0] == []


def test_a_row_updated_then_deleted(shop):
    flags, _ = shop.run("x", ["UPDATE lines SET qty = 9 WHERE line_id = 1", "DELETE FROM lines WHERE line_id = 1"])
    assert kinds(flags) == ["update_then_delete"]


def test_copies_of_identical_rows_have_no_order(shop):
    st = "INSERT INTO dup (v) SELECT v FROM dup WHERE id IN ({})"
    assert shop.run("Copy rows 2 and 1.", [st.format("1, 2")])[0] == []
    assert kinds(shop.run("Copy rows 3 and 1.", [st.format("1, 3")])[0]) == ["copy_order"]
