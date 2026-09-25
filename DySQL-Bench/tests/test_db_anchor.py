# tests/test_db_anchor.py
from dysql_bench.db_select import profile_db, declared_fks, validate_fks, infer_fks, row_key
from dysql_bench.db_anchor import updatable_cols, update_targets
from tests._sqlite_fixtures import make_db as _db, rows as _rows, SHOP

def _keys(p):
    return {t["name"]: row_key(t) for t in p["tables"] if row_key(t)}

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
