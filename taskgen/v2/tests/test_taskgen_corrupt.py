# tests/test_taskgen_corrupt.py
import random, sqlite3
from taskgen_common.testing import make_db, SHOP
from taskgen_v2 import corrupt


def cand(*sqls):
    return {"id": "t", "instruction": "x", "actions": [{"sql": s} for s in sqls]}


def variants(fn, c, conn=None, n=200):
    return {tuple(corrupt.statements(b)) for s in range(n) if (b := fn(c, random.Random(s), conn))}


def test_change_literal_takes_another_value_of_the_same_kind_from_the_task():
    c = cand("UPDATE orders SET qty = 3 WHERE order_id = 5", "UPDATE customers SET first_name = 'Ann' WHERE customer_id = 7")
    second = "UPDATE customers SET first_name = 'Ann' WHERE customer_id = {}"
    first = "UPDATE orders SET qty = {} WHERE order_id = {}"
    assert variants(corrupt.change_literal, c) == {
        (first.format(5, 5), second.format(7)), (first.format(7, 5), second.format(7)),
        (first.format(3, 3), second.format(7)), (first.format(3, 7), second.format(7)),
        (first.format(3, 5), second.format(3)), (first.format(3, 5), second.format(5))}   # the one string has no partner
    assert corrupt.change_literal(cand("DELETE FROM orders WHERE order_id = 5"), random.Random(0)) is None


def test_swap_values_trades_two_literals_of_one_statement():
    c = cand("INSERT INTO orders (order_id, customer_id, product_id, qty) VALUES (500, 7, 9, 7)")
    head = "INSERT INTO orders (order_id, customer_id, product_id, qty) VALUES "
    assert variants(corrupt.swap_values, c) == {(head + v,) for v in (
        "(7, 500, 9, 7)", "(7, 7, 9, 500)", "(9, 7, 500, 7)", "(500, 9, 7, 7)", "(500, 7, 7, 9)")}   # the two 7s never trade
    assert corrupt.swap_values(cand("DELETE FROM orders WHERE order_id = 5"), random.Random(0)) is None


def test_drop_where_removes_one_condition_or_the_whole_clause():
    assert variants(corrupt.drop_where, cand("UPDATE orders SET qty = 3 WHERE order_id = 5 AND customer_id = 5")) == {
        ("UPDATE orders SET qty = 3 WHERE customer_id = 5",), ("UPDATE orders SET qty = 3 WHERE order_id = 5",)}
    assert variants(corrupt.drop_where, cand("DELETE FROM orders WHERE order_id = 5")) == {("DELETE FROM orders",)}
    for keep in ("UPDATE orders SET qty = 3 WHERE order_id = 5 OR order_id = 6",
                 "DELETE FROM orders WHERE order_id BETWEEN 5 AND 9",
                 "INSERT INTO orders (order_id, qty) SELECT 500, qty FROM orders WHERE order_id = 5"):
        assert corrupt.drop_where(cand(keep), random.Random(0)) is None


def test_set_column_writes_another_non_key_column_of_the_same_type(tmp_path):
    conn = sqlite3.connect(make_db(tmp_path, "shop", SHOP))
    assert variants(corrupt.set_column, cand("UPDATE orders SET qty = 3 WHERE order_id = 5"), conn) == {
        ('UPDATE orders SET "customer_id" = 3 WHERE order_id = 5',), ('UPDATE orders SET "product_id" = 3 WHERE order_id = 5',)}
    assert variants(corrupt.set_column, cand('UPDATE "customers" SET "first_name" = \'Z\' WHERE customer_id = 1'), conn) == {
        ('UPDATE "customers" SET "last_name" = \'Z\' WHERE customer_id = 1',)}
    assert corrupt.set_column(cand("UPDATE products SET price = 2.5 WHERE product_id = 1"), random.Random(0), conn) is None   # no other REAL


def test_drop_last_needs_two_writes():
    c = cand("SELECT 1", "UPDATE orders SET qty = 3 WHERE order_id = 5", "DELETE FROM orders WHERE order_id = 6")
    assert corrupt.statements(corrupt.drop_last(c)) == ["SELECT 1", "UPDATE orders SET qty = 3 WHERE order_id = 5"]
    assert corrupt.drop_last(cand("UPDATE orders SET qty = 3 WHERE order_id = 5")) is None


def test_a_changed_literal_keeps_its_quotes(tmp_path):
    conn = sqlite3.connect(make_db(tmp_path, "shop", SHOP))
    c = cand("UPDATE customers SET last_name = 'O''Brien' WHERE first_name = 'Ann'")
    for v in variants(corrupt.change_literal, c) | variants(corrupt.swap_values, c):
        conn.execute(v[0])   # still valid SQL
    assert ("UPDATE customers SET last_name = 'Ann' WHERE first_name = 'O''Brien'",) in variants(corrupt.swap_values, c)
