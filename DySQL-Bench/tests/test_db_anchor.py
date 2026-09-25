# tests/test_db_anchor.py
from dysql_bench.db_select import profile_db, declared_fks, validate_fks, infer_fks, row_key
from dysql_bench.db_anchor import (updatable_cols, update_targets, anchor_kind, reachable_down, anchors,
                                   entity_rank)
from tests._sqlite_fixtures import make_db as _db, rows as _rows, SHOP

def _keys(p):
    return {t["name"]: row_key(t) for t in p["tables"] if row_key(t)}

def _anchors(p, fks, min_rows=5):
    return {a["table"]: a for a in anchors(p, fks, _keys(p), update_targets(p, _keys(p), 200), min_rows)}

# --- Task 6: update targets ---

def test_updatable_cols_allow_fks_but_not_own_key_guid_empty_or_long(tmp_path):
    p = profile_db(_db(tmp_path, "u", """
        CREATE TABLE orders (order_id INTEGER PRIMARY KEY, customer_id INTEGER, qty INTEGER, note TEXT,
                             rowguid TEXT, html TEXT, gone TEXT);
    """ + _rows("orders", 10, lambda i: f"{i},{i},1,'n','g{i}','{'x' * 300}',NULL")))
    assert updatable_cols(p["tables"][0], "order_id", max_avg_len=200) == ["customer_id", "qty", "note"]

def test_update_targets_need_a_row_and_an_updatable_column(tmp_path):
    p = profile_db(_db(tmp_path, "t", SHOP + """
        CREATE TABLE playlist_track (playlist_id INTEGER, track_id INTEGER, PRIMARY KEY (playlist_id, track_id));
        INSERT INTO playlist_track VALUES (1,1),(1,2);
        CREATE TABLE orders_archive (order_id INTEGER PRIMARY KEY, qty INTEGER);"""))
    assert update_targets(p, _keys(p), 200) == {"customers": ["first_name", "last_name"], "products": ["name", "price"],
                                                "orders": ["customer_id", "product_id", "qty"]}

# --- Task 7: anchors ---

def test_anchor_kind():
    assert anchor_kind("customers", ["id", "email"]) == "person_id_only"
    assert anchor_kind("customers", ["id", "first_name", "last_name"]) == "person_named"
    assert anchor_kind("Wrestlers", ["id", "name"]) == "person_named"
    assert anchor_kind("Player", ["id", "player_name"]) == "person_named"
    assert anchor_kind("superhero", ["id", "superhero_name", "full_name"]) == "person_named"
    assert anchor_kind("congress", ["cognress_rep_id", "first_name", "last_name"]) == "person_named"
    assert anchor_kind("users", ["userid", "age", "u_gender"]) == "person_id_only"
    assert anchor_kind("Recipe", ["recipe_id", "title"]) == "entity"
    assert anchor_kind("Team", ["id", "team_name"]) == "entity"

def test_anchors_shop(tmp_path):
    p = profile_db(_db(tmp_path, "shop", SHOP))
    a = _anchors(p, validate_fks(p, declared_fks(p)))
    assert set(a) == {"customers", "products"}
    assert a["customers"] == {"table": "customers", "key": "customer_id", "kind": "person_named", "rows": 60,
                              "names": ["first_name", "last_name"], "down": ["orders"], "up": ["products"],
                              "update_targets": ["customers", "orders", "products"]}
    assert a["products"]["kind"] == "entity" and a["products"]["names"] == ["name"] and a["products"]["up"] == ["customers"]

def test_entity_anchor_needs_a_child(tmp_path):
    # cookbook-like: Recipe is an entity anchor because Quantity hangs off it; so is the lookup table Unit,
    # which is why entity anchors are ranked (entity_rank) and confirmed by a human for entity-only DBs
    p = profile_db(_db(tmp_path, "cook", """
        CREATE TABLE Recipe (recipe_id INTEGER PRIMARY KEY, title TEXT);
        CREATE TABLE Unit (unit_id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE Quantity (quantity_id INTEGER PRIMARY KEY, recipe_id INTEGER REFERENCES Recipe(recipe_id),
                               unit_id INTEGER, amount REAL);
    """ + _rows("Recipe", 60, lambda i: f"{i},'r{i}'") + _rows("Unit", 8, lambda i: f"{i},'u{i}'")
          + _rows("Quantity", 120, lambda i: f"{i},{i%60},{i%8},1.0")))
    a = _anchors(p, validate_fks(p, declared_fks(p) + infer_fks(p)))
    assert a["Recipe"]["down"] == ["Quantity"] and a["Recipe"]["names"] == ["title"] and a["Recipe"]["up"] == ["Unit"]
    assert [x["table"] for x in sorted(a.values(), key=entity_rank)] == ["Recipe", "Unit"]
    p2 = profile_db(_db(tmp_path, "lookup", """
        CREATE TABLE Recipe (recipe_id INTEGER PRIMARY KEY, title TEXT);
        CREATE TABLE Unit (unit_id INTEGER PRIMARY KEY, name TEXT);
    """ + _rows("Recipe", 60, lambda i: f"{i},'r{i}'") + _rows("Unit", 8, lambda i: f"{i},'u{i}'")))
    assert _anchors(p2, []) == {}

def test_named_person_may_be_its_own_target_but_id_only_may_not(tmp_path):
    p = profile_db(_db(tmp_path, "hr", """
        CREATE TABLE employees (employee_id INTEGER PRIMARY KEY, first_name TEXT, salary REAL);
        CREATE TABLE users (userid INTEGER PRIMARY KEY, age INTEGER);
    """ + _rows("employees", 60, lambda i: f"{i},'e{i}',100.0") + _rows("users", 60, lambda i: f"{i},30")))
    a = _anchors(p, [])
    assert [(x["table"], x["kind"], x["update_targets"]) for x in a.values()] == \
        [("employees", "person_named", ["employees"])]

def test_anchor_two_hops_and_only_given_fks_are_followed(tmp_path):
    p = profile_db(_db(tmp_path, "hops", """
        CREATE TABLE customers (customer_id INTEGER PRIMARY KEY, first_name TEXT);
        CREATE TABLE invoices (invoice_id INTEGER PRIMARY KEY, customer_id INTEGER REFERENCES customers(customer_id));
        CREATE TABLE invoice_items (item_id INTEGER PRIMARY KEY, invoice_id INTEGER REFERENCES invoices(invoice_id), qty INTEGER);
    """ + _rows("customers", 60, lambda i: f"{i},'c{i}'") + _rows("invoices", 60, lambda i: f"{i},{i}")
          + _rows("invoice_items", 100, lambda i: f"{i},{i%60},1")))
    fks = validate_fks(p, declared_fks(p))
    assert _anchors(p, fks)["customers"]["down"] == ["invoices", "invoice_items"]
    assert _anchors(p, [f for f in fks if f["table"] == "invoices"])["customers"]["down"] == ["invoices"]

def test_anchor_self_reference_does_not_loop(tmp_path):
    p = profile_db(_db(tmp_path, "self", """
        CREATE TABLE employees (employee_id INTEGER PRIMARY KEY, first_name TEXT,
                                manager_id INTEGER REFERENCES employees(employee_id));
    """ + _rows("employees", 60, lambda i: f"{i},'e{i}',{(i+1)%60}")))
    fks = validate_fks(p, declared_fks(p))
    assert reachable_down(fks, "employees", 2) == []
    a = _anchors(p, fks)["employees"]
    assert a["down"] == [] and a["up"] == []

def test_entity_label_from_one_to_one_table(tmp_path):
    # cars: price(ID, price) has no name; data(ID -> price.ID, car_name) does
    p = profile_db(_db(tmp_path, "cars", """
        CREATE TABLE price (ID INTEGER PRIMARY KEY, price REAL);
        CREATE TABLE data (ID INTEGER PRIMARY KEY REFERENCES price(ID), mpg REAL, car_name TEXT);
        CREATE TABLE production (ID INTEGER REFERENCES price(ID), model_year INTEGER, country INTEGER,
                                 PRIMARY KEY (ID, model_year));
    """ + _rows("price", 60, lambda i: f"{i},1000.0") + _rows("data", 60, lambda i: f"{i},20.0,'car {i}'")
          + _rows("production", 100, lambda i: f"{i%60},{70 + i//60},1")))
    a = _anchors(p, validate_fks(p, declared_fks(p)))
    assert set(a) == {"price"} and a["price"]["names"] == ["data.car_name"] and a["price"]["down"] == ["data", "production"]
