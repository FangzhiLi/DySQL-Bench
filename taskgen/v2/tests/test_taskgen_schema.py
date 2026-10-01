# tests/test_taskgen_schema.py
import sqlite3
from taskgen_common.testing import make_db, rows, SHOP
from taskgen_v2 import schema


def test_ddl_lists_every_user_table(tmp_path):
    d = schema.ddl(make_db(tmp_path, "shop", SHOP))
    assert d.count("CREATE TABLE") == 3 and "sqlite_" not in d


def test_column_descriptions_from_bird_csvs(tmp_path):
    db = make_db(tmp_path, "shop", SHOP)
    dd = tmp_path / "database_description"; dd.mkdir()
    (dd / "customers.csv").write_text("original_column_name,column_name,column_description,data_format,value_description\n"
                                      "customer_id,customer id,the unique id,integer,\n"
                                      "first_name,first name,given name,text,\n", encoding="utf-8-sig")
    cd = schema.column_descriptions(db)
    assert cd == {"customers": {"customer_id": "the unique id", "first_name": "given name"}}
    block = schema.schema_block(db)
    assert "CREATE TABLE customers" in block and "customers.first_name: given name" in block


def test_ddl_and_notes_of_the_tables_in_scope_only(tmp_path):
    db = make_db(tmp_path, "shop", SHOP)
    dd = tmp_path / "database_description"; dd.mkdir()
    (dd / "Customers.csv").write_text("original_column_name,column_name,column_description,data_format,value_description\n"
                                      "first_name,first name,given name,text,\n", encoding="utf-8-sig")
    (dd / "products.csv").write_text("original_column_name,column_name,column_description,data_format,value_description\n"
                                     "price,price,in dollars,real,\n", encoding="utf-8-sig")
    block = schema.schema_block(db, {"customers", "orders"})
    assert "CREATE TABLE customers" in block and "CREATE TABLE orders" in block and "CREATE TABLE products" not in block
    assert "- Customers.first_name: given name" in block and "price" not in block   # BIRD names files in another case


def test_column_descriptions_absent_for_spider(tmp_path):
    assert schema.column_descriptions(make_db(tmp_path, "shop", SHOP)) == {}


def test_pk_info_classifies_primary_keys(tmp_path):
    path = make_db(tmp_path, "keys", """
CREATE TABLE plain (id INTEGER PRIMARY KEY, v TEXT);
CREATE TABLE auto_ok (id INTEGER PRIMARY KEY AUTOINCREMENT, v TEXT);
CREATE TABLE auto_ahead (id INTEGER PRIMARY KEY AUTOINCREMENT, v TEXT);
CREATE TABLE int_key (id INT PRIMARY KEY, v TEXT);
CREATE TABLE text_key (code TEXT PRIMARY KEY, v TEXT);
CREATE TABLE pair (a INTEGER, b INTEGER, PRIMARY KEY (a, b));
CREATE TABLE no_rowid (id INTEGER PRIMARY KEY, v TEXT) WITHOUT ROWID;
CREATE TABLE "Sales Orders" (id INTEGER PRIMARY KEY, v TEXT);
CREATE TABLE empty (id INTEGER PRIMARY KEY, v TEXT);
CREATE TABLE nokey (v TEXT);
""" + rows("plain", 5, lambda i: f"{i + 1},'x'") + rows("auto_ok", 5, lambda i: f"{i + 1},'x'")
        + rows("auto_ahead", 5, lambda i: f"{i + 1},'x'") + "INSERT INTO auto_ahead VALUES (10, 'y'); DELETE FROM auto_ahead WHERE id = 10;"
        + rows('"Sales Orders"', 3, lambda i: f"{i + 1},'x'"))
    info = schema.pk_info(sqlite3.connect(path))
    assert info["plain"] == {"cols": ["id"], "rowid_alias": True, "omittable": True, "next": 6}
    assert info["auto_ok"]["omittable"] and info["auto_ok"]["next"] == 6
    assert info["auto_ahead"] == {"cols": ["id"], "rowid_alias": True, "omittable": False, "next": None}   # sequence at 10 (WWE)
    for t in ("int_key", "text_key", "pair", "no_rowid", "nokey"):
        assert not info[t]["omittable"] and info[t]["next"] is None, t
    assert info["pair"]["cols"] == ["a", "b"] and info["nokey"]["cols"] == []
    assert info["Sales Orders"]["next"] == 4 and info["empty"]["next"] == 1


def test_key_notes_say_how_a_new_row_gets_its_key(tmp_path):
    conn = sqlite3.connect(make_db(tmp_path, "keys", """
CREATE TABLE plain (id INTEGER PRIMARY KEY, v TEXT);
CREATE TABLE ahead (id INTEGER PRIMARY KEY AUTOINCREMENT, v TEXT);
CREATE TABLE num_text (code TEXT PRIMARY KEY, v TEXT);
CREATE TABLE text_key (code TEXT PRIMARY KEY, v TEXT);
CREATE TABLE pair (a INTEGER, b INTEGER, PRIMARY KEY (a, b));
CREATE TABLE nokey (v TEXT);
CREATE TABLE closed (id INTEGER PRIMARY KEY, v TEXT);
CREATE TABLE named (id INTEGER PRIMARY KEY UNIQUE, name TEXT UNIQUE, code TEXT, city TEXT, UNIQUE (code, city));
CREATE TABLE extra (code TEXT PRIMARY KEY REFERENCES num_text(code), v TEXT);
CREATE TABLE profile (pid INTEGER PRIMARY KEY REFERENCES plain(id), v TEXT);
""" + rows("plain", 5, lambda i: f"{i + 1},'x'") + rows("ahead", 5, lambda i: f"{i + 1},'x'")
        + "INSERT INTO ahead VALUES (10, 'y'); DELETE FROM ahead WHERE id = 10;"
        + rows("num_text", 3, lambda i: f"'{1000 + i}','x'") + "INSERT INTO text_key VALUES ('AL', 'x'), ('AK', 'y');"))
    tables = ["plain", "ahead", "num_text", "text_key", "pair", "nokey", "closed", "named", "extra", "profile", "missing"]
    notes = schema.key_notes(conn, tables, {"closed"}, {"extra": {"code"}, "profile": {"pid"}})
    assert notes == {
        "plain": "- plain: a new row may leave id out (SQLite assigns 6)",
        "ahead": "- ahead: a new row must state id = 6, written in the instruction",       # WWE: the sequence ran ahead
        "num_text": "- num_text: a new row must state code = 1003, written in the instruction",   # college_2's text IDs
        "text_key": "- text_key: a new row must state a new code, one not used yet, written in the instruction",
        "pair": "- pair: key (a, b); a new row states every key column, in a combination not used yet",
        "nokey": "- nokey: no primary key",
        "closed": "- closed: no new rows (UPDATE or DELETE only)",
        "named": "- named: a new row may leave id out (SQLite assigns 1); unique: (code, city), name (no value used twice)",
        "extra": "- extra: a new row states code, the key of the row it belongs to, written in the instruction",
        "profile": "- profile: a new row states pid, the key of the row it belongs to, written in the instruction"}
    assert schema.unique_columns(conn, "named") == [("code", "city"), ("name",)] and schema.unique_columns(conn, "pair") == []
