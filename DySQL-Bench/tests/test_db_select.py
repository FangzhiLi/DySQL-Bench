# tests/test_db_select.py
from dysql_bench.db_select import (profile_db, row_key, infer_fks, is_person_table, transaction_tables,
                                   schema_items, containment, is_fragmented, evaluate, dedup, declared_fks,
                                   validate_fks)
from tests._sqlite_fixtures import make_db as _db, rows as _rows, SHOP

def test_profile_db_reads_tables_rows_pk_fk(tmp_path):
    p = profile_db(_db(tmp_path, "shop", SHOP))
    t = {x["name"]: x for x in p["tables"]}
    assert set(t) == {"customers", "products", "orders"}
    assert t["orders"]["rows"] == 100
    assert t["orders"]["pk"] == ["order_id"]
    assert sorted(f["cols"][0] for f in t["orders"]["fks"]) == ["customer_id", "product_id"]
    assert t["orders"]["fks"][0]["ref_table"] in {"customers", "products"}

def test_infer_fk_from_matching_pk_name(tmp_path):
    p = profile_db(_db(tmp_path, "nofk", """
        CREATE TABLE customers (customer_id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE orders (order_id INTEGER PRIMARY KEY, customer_id INTEGER, amount REAL);"""))
    assert infer_fks(p) == [{"table": "orders", "cols": ["customer_id"],
                             "ref_table": "customers", "ref_cols": ["customer_id"]}]

def test_infer_fk_from_table_name_plus_id(tmp_path):
    p = profile_db(_db(tmp_path, "nofk2", """
        CREATE TABLE customer (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE orders (id INTEGER PRIMARY KEY, customer_id INTEGER);"""))
    assert infer_fks(p) == [{"table": "orders", "cols": ["customer_id"],
                             "ref_table": "customer", "ref_cols": ["id"]}]

def test_infer_fk_skips_declared_and_own_pk(tmp_path):
    p = profile_db(_db(tmp_path, "shop", SHOP))
    assert infer_fks(p) == []

def test_person_table_by_name_or_name_columns():
    assert is_person_table("Customers", ["id"])
    assert is_person_table("tbl_bowlers", ["id"])
    assert is_person_table("people_info", ["id"])
    assert is_person_table("x", ["id", "FirstName", "LastName"])
    assert not is_person_table("products", ["id", "name"])

def test_transaction_tables_need_outgoing_fk_and_rows(tmp_path):
    p = profile_db(_db(tmp_path, "shop", SHOP))
    assert transaction_tables(p, min_rows=50) == ["orders"]
    assert transaction_tables(p, min_rows=500) == []

def test_schema_items_normalize_case_underscore_plural(tmp_path):
    p = profile_db(_db(tmp_path, "n", "CREATE TABLE Invoice_Lines (Invoice_Id INT, Qty INT);"))
    assert schema_items(p) == {"invoiceline.invoiceid", "invoiceline.qty"}

def test_schema_items_strip_prefix_shared_by_most_tables(tmp_path):
    p = profile_db(_db(tmp_path, "olist", """
        CREATE TABLE olist_orders (order_id TEXT); CREATE TABLE olist_customers (customer_id TEXT);
        CREATE TABLE translation (name TEXT);"""))
    assert schema_items(p) == {"order.orderid", "customer.customerid", "translation.name"}

def test_containment_is_relative_to_smaller_schema():
    small, big = {"a.x", "a.y"}, {"a.x", "a.y", "b.z", "c.w"}
    assert containment(small, big) == 1.0 == containment(big, small)
    assert containment({"a.x", "b.y"}, {"a.x", "c.z", "d.w"}) == 0.5

def test_profile_finds_unique_id_column_when_no_pk(tmp_path):
    p = profile_db(_db(tmp_path, "k", """
        CREATE TABLE olist_orders (order_id TEXT, customer_id TEXT, status TEXT);
        INSERT INTO olist_orders VALUES ('o1','c1','x'),('o2','c1','y');"""))
    assert p["tables"][0]["unique_keys"] == ["order_id"]

def test_row_key_prefers_unique_column_naming_the_table():
    t = {"name": "olist_order_reviews", "pk": [], "unique_keys": ["order_id", "review_id"]}
    assert row_key(t) == "review_id"
    assert row_key({**t, "pk": ["id"]}) == "id"

def test_infer_fk_uses_unique_key_when_ref_has_no_pk(tmp_path):
    p = profile_db(_db(tmp_path, "k2", """
        CREATE TABLE olist_customers (customer_id TEXT, city TEXT);
        CREATE TABLE olist_orders (order_id TEXT, customer_id TEXT);
        INSERT INTO olist_customers VALUES ('c1','a'),('c2','b');
        INSERT INTO olist_orders VALUES ('o1','c1'),('o2','c1');"""))
    assert infer_fks(p) == [{"table": "olist_orders", "cols": ["customer_id"],
                             "ref_table": "olist_customers", "ref_cols": ["customer_id"]}]

def test_fragmented_when_fk_graph_splits(tmp_path):
    p = profile_db(_db(tmp_path, "mix", """
        CREATE TABLE a (a_id INTEGER PRIMARY KEY); CREATE TABLE b (b_id INTEGER PRIMARY KEY, a_id INTEGER);
        CREATE TABLE x (x_id INTEGER PRIMARY KEY); CREATE TABLE y (y_id INTEGER PRIMARY KEY, x_id INTEGER);"""))
    assert is_fragmented(p, infer_fks(p), min_share=0.6)
    q = profile_db(_db(tmp_path, "shop", SHOP))
    assert not is_fragmented(q, [], min_share=0.6)

CFG = dict(tables=(3, 20), max_cols=250, rows=(200, 3_000_000), max_mb=100, min_fks=2,
           txn_min_rows=50, min_component_share=0.6, leak_names=set(), overlap=0.6, leak_ref={})

def test_evaluate_passes_shop(tmp_path):
    r = evaluate(profile_db(_db(tmp_path, "shop", SHOP)), CFG)
    assert r["pass"], r["fail_reasons"]
    assert r["has_person"] and r["txn_tables"] == ["orders"] and r["n_fks_declared"] == 2

def test_evaluate_requires_person_table_only_when_configured(tmp_path):
    depot = SHOP.replace("customers", "depots").replace("customer_id", "depot_id") \
                .replace("first_name", "label").replace("last_name", "code")
    p = profile_db(_db(tmp_path, "depot", depot))
    assert evaluate(p, CFG)["pass"]
    r = evaluate(p, {**CFG, "require_person": True})
    assert r["fail_reasons"] == ["no_person"]
    assert evaluate(profile_db(_db(tmp_path, "shop", SHOP)), {**CFG, "require_person": True})["pass"]

def test_evaluate_reports_every_failed_rule(tmp_path):
    p = profile_db(_db(tmp_path, "tiny", """
        CREATE TABLE a (id INTEGER PRIMARY KEY); INSERT INTO a VALUES (1);"""))
    r = evaluate(p, CFG)
    assert not r["pass"]
    assert {"tables", "rows", "fks", "txn_table"} <= set(r["fail_reasons"])

def test_evaluate_flags_leak_by_name_and_by_schema_overlap(tmp_path):
    p = profile_db(_db(tmp_path, "shop", SHOP))
    assert "leak" in evaluate(p, {**CFG, "leak_names": {"shop"}})["fail_reasons"]
    ref = {"customer.customerid", "customer.firstname", "product.productid", "order.orderid"}
    r = evaluate(p, {**CFG, "leak_ref": {"chinook": ref}})
    assert "leak" in r["fail_reasons"] and r["leak_match"] == "chinook"

def test_dedup_keeps_preferred_source():
    f1 = ["race.raceid", "race.year", "driver.driverid", "result.resultid"]
    rows = [dict(source="spider1", db="formula_1", **{"pass": True}, schema=f1),
            dict(source="bird", db="formula_1", **{"pass": True}, schema=f1 + ["sprint.id"]),
            dict(source="bird", db="shop", **{"pass": True}, schema=["order.orderid", "customer.customerid"])]
    out = dedup(rows, order=["bird", "spider2", "spider1"], threshold=0.6)
    assert [r["dup_of"] for r in out] == ["bird:formula_1", None, None]

# --- Task 1: FK hit rate ---

def test_validate_fks_hit_rate_counts_non_empty_child_values(tmp_path):
    p = profile_db(_db(tmp_path, "half", """
        CREATE TABLE customers (customer_id INTEGER PRIMARY KEY);
        CREATE TABLE orders (order_id INTEGER PRIMARY KEY, customer_id INTEGER REFERENCES customers(customer_id));
        INSERT INTO customers VALUES (1),(2);
        INSERT INTO orders VALUES (1,1),(2,2),(3,9),(4,8),(5,NULL),(6,'');"""))
    assert validate_fks(p, declared_fks(p)) == [{"table": "orders", "cols": ["customer_id"], "ref_table": "customers",
                                                 "ref_cols": ["customer_id"], "source": "declared", "hit": 0.5}]

def test_fk_hit_rate_without_child_values_is_unverified(tmp_path):
    p = profile_db(_db(tmp_path, "empty", """
        CREATE TABLE customers (customer_id INTEGER PRIMARY KEY);
        CREATE TABLE orders (order_id INTEGER PRIMARY KEY, customer_id INTEGER REFERENCES customers(customer_id));
        CREATE TABLE archive (order_id INTEGER PRIMARY KEY, customer_id INTEGER REFERENCES customers(customer_id));
        INSERT INTO customers VALUES (1);
        INSERT INTO orders VALUES (1,NULL),(2,'');"""))
    assert [f["hit"] for f in validate_fks(p, declared_fks(p))] == [None, None]

def test_fk_hit_rate_resolves_ref_table_case_insensitively(tmp_path):
    p = profile_db(_db(tmp_path, "case", """
        CREATE TABLE customers (customer_id INTEGER PRIMARY KEY);
        CREATE TABLE orders (order_id INTEGER PRIMARY KEY, customer_id INTEGER REFERENCES Customers(customer_id));
        INSERT INTO customers VALUES (1);
        INSERT INTO orders VALUES (1,1);"""))
    f = validate_fks(p, declared_fks(p))[0]
    assert f["ref_table"] == "customers" and f["hit"] == 1.0

def test_fk_hit_rate_fills_omitted_ref_column_with_pk(tmp_path):
    p = profile_db(_db(tmp_path, "omit", """
        CREATE TABLE customers (customer_id INTEGER PRIMARY KEY);
        CREATE TABLE orders (order_id INTEGER PRIMARY KEY, customer_id INTEGER REFERENCES customers);
        INSERT INTO customers VALUES (1);
        INSERT INTO orders VALUES (1,1),(2,2);"""))
    f = validate_fks(p, declared_fks(p))[0]
    assert f["ref_cols"] == ["customer_id"] and f["hit"] == 0.5
