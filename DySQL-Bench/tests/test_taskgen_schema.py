# tests/test_taskgen_schema.py
import json, os
from tests._sqlite_fixtures import make_db, SHOP
from dysql_bench.taskgen import schema


class FakeClient:
    def __init__(self): self.calls = 0
    def chat(self, messages, **kw):
        self.calls += 1
        return {"content": "A small web shop: customers place orders for products.", "usage": {}}


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


def test_column_descriptions_absent_for_spider(tmp_path):
    assert schema.column_descriptions(make_db(tmp_path, "shop", SHOP)) == {}


def test_describe_db_calls_llm_once_and_caches(tmp_path):
    db = make_db(tmp_path, "shop", SHOP); cache = tmp_path / "desc.json"; client = FakeClient()
    a = schema.describe_db("test:shop", db, client, str(cache))
    b = schema.describe_db("test:shop", db, client, str(cache))
    assert a == b == "A small web shop: customers place orders for products." and client.calls == 1
    assert json.load(open(cache)) == {"test:shop": a}
