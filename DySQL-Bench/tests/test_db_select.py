# tests/test_db_select.py
from dysql_bench.db_select import (profile_db, row_key, infer_fks, infer_fks_by_value, declared_fks, validate_fks,
                                   all_fks, is_keyed, schema_items, containment, is_fragmented, evaluate, dedup)
from tests._sqlite_fixtures import make_db as _db, rows as _rows, SHOP, WWE

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
                             "ref_table": "customers", "ref_cols": ["customer_id"], "source": "name"}]

def test_infer_fk_from_table_name_plus_id(tmp_path):
    p = profile_db(_db(tmp_path, "nofk2", """
        CREATE TABLE customer (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE orders (id INTEGER PRIMARY KEY, customer_id INTEGER);"""))
    assert infer_fks(p) == [{"table": "orders", "cols": ["customer_id"],
                             "ref_table": "customer", "ref_cols": ["id"], "source": "name"}]

def test_infer_fk_skips_declared_and_own_pk(tmp_path):
    p = profile_db(_db(tmp_path, "shop", SHOP))
    assert infer_fks(p) == []

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
                             "ref_table": "olist_customers", "ref_cols": ["customer_id"], "source": "name"}]

def test_fragmented_when_fk_graph_splits(tmp_path):
    p = profile_db(_db(tmp_path, "mix", """
        CREATE TABLE a (a_id INTEGER PRIMARY KEY); CREATE TABLE b (b_id INTEGER PRIMARY KEY, a_id INTEGER);
        CREATE TABLE x (x_id INTEGER PRIMARY KEY); CREATE TABLE y (y_id INTEGER PRIMARY KEY, x_id INTEGER);"""))
    assert is_fragmented(p, infer_fks(p), min_share=0.6)
    q = profile_db(_db(tmp_path, "shop", SHOP))
    assert not is_fragmented(q, all_fks(q), min_share=0.6)

CFG = dict(tables=(3, 20), max_cols=250, rows=(200, 3_000_000), max_mb=100, min_fks=2, fk_min_hit=0.3,
           anchor_min_rows=5, long_text_avg_len=200, min_component_share=0.6,
           leak_names=set(), overlap=0.6, leak_ref={})

def test_evaluate_passes_shop(tmp_path):
    r = evaluate(profile_db(_db(tmp_path, "shop", SHOP)), CFG)
    assert r["pass"], r["fail_reasons"]
    assert r["n_fks_declared"] == 2 and r["n_fks_valid"] == 2 and r["invalid_fks"] == [] == r["unverified_fks"]
    assert r["has_person_named"] and r["anchor_kinds"] == ["entity", "person_named"]
    assert r["person_anchors"] == ["customers[first_name,last_name]"] and r["entity_anchors"] == ["products[name]"]
    assert r["update_targets"] == ["customers", "products", "orders"]

def test_evaluate_reports_every_failed_rule(tmp_path):
    p = profile_db(_db(tmp_path, "tiny", """
        CREATE TABLE a (id INTEGER PRIMARY KEY); INSERT INTO a VALUES (1);"""))
    r = evaluate(p, CFG)
    assert not r["pass"]
    assert {"tables", "rows", "fks", "no_update_target", "no_anchor"} <= set(r["fail_reasons"])

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

# --- Task 2: name-based inference ---

def test_infer_fk_ignores_guid_columns(tmp_path):
    # AdventureWorks: a table whose only unique id-like column is rowguid makes every other rowguid 'reference' it
    p = profile_db(_db(tmp_path, "guid", """
        CREATE TABLE product (productid INTEGER PRIMARY KEY, rowguid TEXT);
        CREATE TABLE salesorderdetail (salesorderdetailid INTEGER PRIMARY KEY, productid INTEGER, rowguid TEXT);
        CREATE TABLE productmodelculture (productmodelid INTEGER, cultureid TEXT, rowguid TEXT);
        INSERT INTO product VALUES (1,'g1'),(2,'g2');
        INSERT INTO salesorderdetail VALUES (1,1,'g3'),(2,2,'g4');
        INSERT INTO productmodelculture VALUES (1,'en','g5'),(1,'en','g6');"""))
    assert [(f["table"], f["cols"][0], f["ref_table"]) for f in infer_fks(p)] == \
        [("salesorderdetail", "productid", "product")]

def test_infer_fk_skips_generic_id_columns(tmp_path):
    # both ids run 1..N, so the smaller one is 'contained' in the larger by coincidence (EU_soccer Match/Player_Attributes)
    p = profile_db(_db(tmp_path, "gen", """
        CREATE TABLE Match (id INTEGER PRIMARY KEY, season TEXT);
        CREATE TABLE Player_Attributes (id INTEGER PRIMARY KEY, rating INTEGER);
    """ + _rows("Match", 5, lambda i: f"{i},'s'") + _rows("Player_Attributes", 10, lambda i: f"{i},1")))
    assert infer_fks(p) == []

def test_infer_fk_from_composite_pk_member(tmp_path):
    # BowlingLeague: the archive's BowlerID is part of its PK and still points at Bowlers
    p = profile_db(_db(tmp_path, "bowl", """
        CREATE TABLE Bowlers (BowlerID INTEGER PRIMARY KEY, BowlerLastName TEXT);
        CREATE TABLE Bowler_Scores_Archive (MatchID INTEGER, GameNumber INTEGER, BowlerID INTEGER, RawScore INTEGER,
                                            PRIMARY KEY (MatchID, GameNumber, BowlerID));"""))
    assert [(f["table"], f["cols"][0], f["ref_table"]) for f in infer_fks(p)] == \
        [("Bowler_Scores_Archive", "BowlerID", "Bowlers")]

def test_infer_fk_one_to_one_extension_needs_larger_parent(tmp_path):
    # complex_oracle: supplementary_demographics.cust_id is its own PK and references customers (55,500 > 4,500 rows)
    p = profile_db(_db(tmp_path, "ext", """
        CREATE TABLE customers (cust_id INTEGER PRIMARY KEY, cust_first_name TEXT);
        CREATE TABLE supplementary_demographics (cust_id INTEGER PRIMARY KEY, occupation TEXT);
    """ + _rows("customers", 3, lambda i: f"{i},'c{i}'") + _rows("supplementary_demographics", 2, lambda i: f"{i},'o'")))
    assert [(f["table"], f["cols"][0], f["ref_table"]) for f in infer_fks(p)] == \
        [("supplementary_demographics", "cust_id", "customers")]

# --- Task 3: value-based inference ---

def test_infer_by_value_finds_role_named_fks(tmp_path):
    p = profile_db(_db(tmp_path, "wwe", WWE))
    covered = {(f["table"], f["cols"][0].lower()) for f in infer_fks(p)}   # card_id -> Cards by name
    got = sorted((f["table"], f["cols"][0], f["ref_table"], f["source"]) for f in infer_fks_by_value(p, covered))
    assert got == [("Matches", "loser_id", "Wrestlers", "value"), ("Matches", "winner_id", "Wrestlers", "value")]

def test_infer_by_value_rejects_ambiguous_match(tmp_path):
    # winner_id values 0..39 exist in both Wrestlers.id and Cards.id -> two candidates -> no FK
    p = profile_db(_db(tmp_path, "amb", """
        CREATE TABLE Wrestlers (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE Cards (id INTEGER PRIMARY KEY, title TEXT);
        CREATE TABLE Matches (id INTEGER PRIMARY KEY, winner_id INTEGER);
    """ + _rows("Wrestlers", 40, lambda i: f"{i},'w{i}'") + _rows("Cards", 40, lambda i: f"{i},'c{i}'")
          + _rows("Matches", 200, lambda i: f"{i},{i%40}")))
    assert infer_fks_by_value(p, set()) == []

def test_infer_by_value_needs_the_child_to_cover_part_of_the_ref_keys(tmp_path):
    # complex_oracle: 60 calendar_month_id values all fall inside customers.cust_id 1..55,500 by coincidence;
    # a real role FK (winner_id -> Wrestlers) covers most of the referenced keys
    p = profile_db(_db(tmp_path, "cov", """
        CREATE TABLE customers (cust_id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE times (time_id INTEGER PRIMARY KEY, calendar_month_id INTEGER);
    """ + _rows("customers", 1000, lambda i: f"{i},'c{i}'") + _rows("times", 300, lambda i: f"{i},{i%60}")))
    assert infer_fks_by_value(p, set()) == []

def test_infer_by_value_needs_enough_distinct_values(tmp_path):
    p = profile_db(_db(tmp_path, "few", """
        CREATE TABLE Wrestlers (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE Matches (id INTEGER PRIMARY KEY, winner_id INTEGER, note TEXT);
    """ + _rows("Wrestlers", 40, lambda i: f"{i},'w{i}'") + _rows("Matches", 200, lambda i: f"{i},{i%3},'x'")))
    assert infer_fks_by_value(p, set()) == []

# --- Task 4: composite keys ---

def test_profile_finds_two_column_composite_key(tmp_path):
    p = profile_db(_db(tmp_path, "ck", """
        CREATE TABLE movie_cast (movie_id INTEGER, person_id INTEGER, role TEXT);
        INSERT INTO movie_cast VALUES (1,1,'a'),(1,2,'b'),(2,1,'c');"""))
    t = p["tables"][0]
    assert t["unique_keys"] == [] and t["composite_key"] == ["movie_id", "person_id"] and is_keyed(t)

def test_composite_key_rejects_duplicates_and_nulls(tmp_path):
    p = profile_db(_db(tmp_path, "nock", """
        CREATE TABLE a (x_id INTEGER, y_id INTEGER, v TEXT);
        INSERT INTO a VALUES (1,1,'a'),(1,1,'b');
        CREATE TABLE b (x_id INTEGER, y_id INTEGER, v TEXT);
        INSERT INTO b VALUES (1,NULL,'a'),(1,2,'b');"""))
    assert [t["composite_key"] for t in p["tables"]] == [[], []]
    assert not is_keyed(p["tables"][0])

def test_single_pk_table_has_no_composite_key(tmp_path):
    p = profile_db(_db(tmp_path, "shop", SHOP))
    assert all(t["composite_key"] == [] for t in p["tables"])

# --- Task 5: column stats ---

def test_col_stats_empty_blank_and_avg_len(tmp_path):
    p = profile_db(_db(tmp_path, "st", """
        CREATE TABLE t (id INTEGER PRIMARY KEY, note TEXT, html TEXT);
        INSERT INTO t VALUES (1,'ab',NULL),(2,'',NULL),(3,NULL,'xxxxxxxxxx');"""))
    s = p["tables"][0]["stats"]
    assert s["note"] == {"empty": 2, "blank": 1, "avg_len": 2.0}
    assert s["html"] == {"empty": 2, "blank": 0, "avg_len": 10.0}
    assert s["id"]["empty"] == 0

def test_col_stats_on_quoted_names(tmp_path):
    p = profile_db(_db(tmp_path, "sp", """
        CREATE TABLE "Sales Orders" ("Order Number" TEXT PRIMARY KEY, "Sales Channel" TEXT);
        CREATE TABLE "voice-actors" ("voice-actor" TEXT, movie TEXT);
        INSERT INTO "Sales Orders" VALUES ('o1','web');
        INSERT INTO "voice-actors" VALUES ('Joan','Chicken Little');"""))
    t = {x["name"]: x for x in p["tables"]}
    assert t["Sales Orders"]["stats"]["Sales Channel"]["avg_len"] == 3.0
    assert t["voice-actors"]["stats"]["voice-actor"]["empty"] == 0

def test_col_stats_skipped_for_empty_table(tmp_path):
    p = profile_db(_db(tmp_path, "e", "CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT);"))
    assert p["tables"][0]["stats"] == {}

# --- Task 8: evaluate ---

def test_all_fks_merges_sources_and_validates(tmp_path):
    p = profile_db(_db(tmp_path, "wwe", WWE))
    fks = all_fks(p, extra=[{"table": "Matches", "cols": ["champion"], "ref_table": "Wrestlers", "ref_cols": ["id"]}])
    assert sorted((f["cols"][0], f["source"], f["hit"]) for f in fks) == \
        [("card_id", "name", 1.0), ("champion", "extra", 1.0), ("loser_id", "value", 1.0), ("winner_id", "value", 1.0)]

def test_evaluate_drops_invalid_fks_and_reports_them(tmp_path):
    p = profile_db(_db(tmp_path, "bad", """
        CREATE TABLE customers (customer_id INTEGER PRIMARY KEY, first_name TEXT);
        CREATE TABLE products (product_id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE orders (order_id INTEGER PRIMARY KEY, customer_id INTEGER REFERENCES customers(customer_id),
                             product_id INTEGER REFERENCES products(product_id), qty INTEGER);
    """ + _rows("customers", 60, lambda i: f"{i},'c{i}'") + _rows("products", 60, lambda i: f"{i},'p{i}'")
          + _rows("orders", 100, lambda i: f"{i},{i%60 + 1000},{i%60},1")))
    r = evaluate(p, CFG)
    assert r["invalid_fks"] == ["orders.customer_id->customers 0.0"] and r["n_fks_valid"] == 1
    assert "fks" in r["fail_reasons"] and "customers[first_name]" in r["person_anchors"]

def test_evaluate_keeps_unverified_fk_on_empty_table(tmp_path):
    p = profile_db(_db(tmp_path, "arch", SHOP + """
        CREATE TABLE returns (return_id INTEGER PRIMARY KEY, order_id INTEGER REFERENCES orders(order_id), reason TEXT);"""))
    r = evaluate(p, CFG)
    assert r["unverified_fks"] == ["returns.order_id->orders"] and r["n_fks_valid"] == 2 and r["pass"]

def test_evaluate_id_only_person_with_link_tables_passes(tmp_path):
    # computer_student-like: no names, advisedBy/taughtBy are pure link tables; the rule lets it through and the
    # anchor list shows a human what kind of tasks it can carry
    p = profile_db(_db(tmp_path, "cs", """
        CREATE TABLE person (p_id INTEGER PRIMARY KEY, professor INTEGER, student INTEGER);
        CREATE TABLE course (course_id INTEGER PRIMARY KEY, courseLevel TEXT);
        CREATE TABLE advisedBy (p_id INTEGER REFERENCES person(p_id), p_id_dummy INTEGER REFERENCES person(p_id),
                                PRIMARY KEY (p_id, p_id_dummy));
        CREATE TABLE taughtBy (course_id INTEGER REFERENCES course(course_id), p_id INTEGER REFERENCES person(p_id),
                               PRIMARY KEY (course_id, p_id));
    """ + _rows("person", 60, lambda i: f"{i},{i%2},{(i+1)%2}") + _rows("course", 60, lambda i: f"{i},'L{i%3}'")
          + _rows("advisedBy", 60, lambda i: f"{i},{(i+1)%60}") + _rows("taughtBy", 60, lambda i: f"{i},{i}")))
    r = evaluate(p, CFG)
    assert r["pass"], r["fail_reasons"]
    assert r["anchor_kinds"] == ["entity", "person_id_only"] and not r["has_person_named"]
    assert r["person_anchors"] == ["person[]"]

def test_evaluate_quality_flags(tmp_path):
    p = profile_db(_db(tmp_path, "q", """
        CREATE TABLE customers (customer_id INTEGER PRIMARY KEY, first_name TEXT, note TEXT);
        CREATE TABLE products (product_id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE orders (order_id INTEGER PRIMARY KEY, customer_id INTEGER REFERENCES customers(customer_id),
                             product_id INTEGER REFERENCES products(product_id), html TEXT);
    """ + _rows("customers", 60, lambda i: f"{i},'c{i}',''") + _rows("products", 60, lambda i: f"{i},'p{i}'")
          + _rows("orders", 100, lambda i: f"{i},{i%60},{i%60},'{'x' * 500}'")))
    r = evaluate(p, CFG)
    assert r["long_text_cols"] == ["orders.html"] and r["empty_string_cols"] == ["customers.note"]

# --- Final review fixes ---

def test_invalid_declared_fk_does_not_block_inference(tmp_path):
    # computer_student: advisedBy declares FOREIGN KEY (p_id, p_id_dummy) REFERENCES person (p_id, p_id), which
    # matches nothing; the column-level FK advisedBy.p_id -> person must still be found by name
    p = profile_db(_db(tmp_path, "cs", """
        CREATE TABLE person (p_id INTEGER PRIMARY KEY, professor INTEGER);
        CREATE TABLE advisedBy (p_id INTEGER, p_id_dummy INTEGER, PRIMARY KEY (p_id, p_id_dummy),
                                FOREIGN KEY (p_id, p_id_dummy) REFERENCES person (p_id, p_id));
    """ + _rows("person", 60, lambda i: f"{i},{i%2}") + _rows("advisedBy", 60, lambda i: f"{i},{(i+1)%60}")))
    got = {(f["table"], tuple(f["cols"]), f["source"], f["hit"]) for f in all_fks(p)}
    assert ("advisedBy", ("p_id", "p_id_dummy"), "declared", 0.0) in got
    assert ("advisedBy", ("p_id",), "name", 1.0) in got
