# tests/test_taskgen_prompt.py
import random
from collections import Counter
from taskgen_v2 import metrics, prompt

ANCHOR = {"table": "customers", "key": "customer_id", "names": ["first_name", "last_name"]}
DB = {"source": "test", "db": "shop", "path": "x", "anchors": [], "fks": []}
CTX = {"no_insert": {"reviews"}, "copyable": {"orders", "products"}, "pk": {"orders": ["order_id"], "products": ["product_id"]}, "fixed": {"orders": {"order_id", "customer_id", "product_id"}, "products": {"product_id"},
                                           "customers": {"customer_id"}, "reviews": {"review_id", "customer_id"}}}
MATERIALS = {**CTX, "description": "A small shop.", "quirks": ["qty is never 0."], "schema": "CREATE TABLE customers (...)",
             "keys": {"orders": "- orders: a new row may leave order_id out (SQLite assigns 101)",
                      "reviews": "- reviews: no new rows (UPDATE or DELETE only)", "unrelated": "- unrelated: no primary key"}}


def order(i, label="own"):
    return {"table": "orders", "row": {"order_id": i, "customer_id": 5, "product_id": i, "qty": 1}, "label": label,
            "parents": [{"table": "products", "row": {"product_id": i, "name": f"p{i}", "price": 1.0}, "label": "public", "parents": []}]}


TREE = {"anchor_table": "customers", "anchor_key": "customer_id", "key_value": 5, "anchor_name": "a5 b5",
        "anchor_row": {"customer_id": 5, "first_name": "a5", "last_name": "b5", "email": "a5@x.org"},
        "lookup": {"email": "a5@x.org"}, "profile_version": "v1",
        "parents": [{"table": "staff", "row": {"staff_id": 2, "name": "s2"}, "label": "other:s2", "parents": []}],
        "attributes": {"vip": [{"customer_id": 5, "level": 3}]},
        "events": [{"table": "orders", "label": "orders", "count": 14, "rows": [order(i) for i in range(12)]},
                   {"table": "reviews", "label": "reviews", "count": 1,
                    "rows": [{"table": "reviews", "row": {"review_id": 1, "customer_id": 5, "stars": 4}, "label": "own", "parents": []}]}]}
NO_PUBLIC = {**TREE, "events": [TREE["events"][1]]}
NO_EVENTS = {**TREE, "events": [], "parents": [], "lookup": {}}


def plans(n=3000, tree=TREE, seed=0):
    rng = random.Random(seed)
    return [prompt.sample_plan(rng, tree, ANCHOR, prompt.CFG, CTX) for _ in range(n)]


def plan_for(task_type, tree=TREE, **shape):
    rng = random.Random(0)
    while True:
        p = prompt.sample_plan(rng, tree, ANCHOR, prompt.CFG, CTX)
        if p["task_type"] == task_type and all(p["shape"][k] == v for k, v in shape.items()):
            return p


def test_examples_are_dysql_style_for_the_four_types():
    ex = prompt.load_examples()
    assert set(ex) == set(prompt.CFG["TYPE_MIX"]) == {"1_self", "2_self_and_public", "3_public_only", "5_proxy"}
    for t, xs in ex.items():
        assert len(xs) >= 3, t
        for x in xs:
            assert 40 <= len(x.split()) <= 80 and metrics.ID_RE.search(" ".join(x.split()[:25])) and not metrics.ASK.search(x), x


def test_no_type_4_and_public_types_need_a_public_row():
    assert prompt.feasible_types(TREE) == ["1_self", "2_self_and_public", "3_public_only", "5_proxy"]
    assert prompt.feasible_types(NO_PUBLIC) == ["1_self", "5_proxy"]


def test_types_and_write_counts_follow_the_mix():
    ps = plans()
    types, writes = Counter(p["task_type"] for p in ps), Counter(p["shape"]["n_writes"] for p in ps)
    assert abs(types["1_self"] / 3000 - 0.47) < 0.04 and abs(types["5_proxy"] / 3000 - 0.29) < 0.04
    assert abs(writes[1] / 3000 - 0.37 * 0.83) < 0.04 and abs(writes[2] / 3000 - 0.47) < 0.05   # type 2 never writes once
    assert abs((writes[4] + writes[5]) / 3000 - 0.09) < 0.03
    assert all(p["shape"]["n_writes"] >= 2 and p["shape"]["n_tables"] == 2 for p in ps if p["task_type"] == "2_self_and_public")


def test_each_type_writes_only_its_own_kind_of_table():
    for p in plans():
        tabs, w = p["tables"], p["write_tables"]
        pool = {"1_self": tabs["own"], "5_proxy": tabs["own"], "3_public_only": tabs["public"]}.get(p["task_type"], tabs["own"] + tabs["public"])
        assert p["scope"] == pool and p["shape"]["n_tables"] <= max(2, len(pool))
        if w:
            assert set(w) <= set(pool) and len(w) == p["shape"]["n_tables"]
            if p["task_type"] == "2_self_and_public":
                assert w[0] in tabs["own"] and w[1] in tabs["public"]


def test_shapes_only_where_the_tree_allows_them():
    ps = plans()
    batch = [p for p in ps if p["shape"]["batch"]]
    assert 0.08 < len(batch) / 3000 < 0.14 and 0.5 < sum(p["shape"]["batch"]["all"] for p in batch) / len(batch) < 0.7
    assert all({**p["shape"]["batch"], "all": 0} == {"table": "orders", "label": "orders", "count": 14, "all": 0}
               and p["task_type"] != "3_public_only" for p in batch)
    arch = [p for p in ps if p["shape"]["archive"]]
    assert arch and all(p["shape"]["n_writes"] >= 2 and p["shape"]["archive"] in ("orders", "products") for p in arch)
    assert all(p["shape"]["archive"] != "reviews" for p in arch)              # not copyable: no new rows
    sub = [p for p in ps if p["shape"]["ownership_subquery"]]
    assert 0.09 < len(sub) / 3000 < 0.15 and all(p["task_type"] != "3_public_only" for p in sub)
    for p in plans(400, NO_EVENTS):                                           # hr_1: most roots have no events
        s = p["shape"]
        assert not s["batch"] and not s["archive"] and not s["ownership_subquery"] and s["n_tables"] <= len(p["scope"])


def test_difficulty_comes_from_the_shape_like_the_check():
    for p in plans(500):
        s = p["shape"]
        feats = [s["n_writes"] >= 2, s["n_tables"] >= 2, s["ownership_subquery"], s["archive"], p["task_type"] == "2_self_and_public"]
        assert p["difficulty"] == prompt.level(feats)
        lo, hi = prompt.CFG["EVENTS_SHOWN"][min(s["n_writes"], 3)]
        assert lo <= len(p["events"]) <= hi or len(p["events"]) == sum(len(g["rows"]) for g in TREE["events"])


def test_targets_are_short_columns_that_are_not_keys():
    for p in plans(300):
        for x in p["targets"]:
            t, c = x.split(".")
            assert c not in CTX["fixed"].get(t, ()) and t in (p["write_tables"] or p["scope"])


def test_long_data_loses_events_until_it_fits():
    big = {**TREE, "events": [{**TREE["events"][0], "rows": [{**order(i), "row": {**order(i)["row"], "note": "x" * 150}} for i in range(12)]}]}
    cfg = {**prompt.CFG, "DATA_CHARS": 1200}
    p = prompt.sample_plan(random.Random(3), big, ANCHOR, cfg, CTX)
    assert 1 <= len(p["events"]) < prompt.CFG["EVENTS_SHOWN"][1][0]
    assert len(prompt.data_blocks(big, p["events"], "x", cfg)) <= 1200 or len(p["events"]) == 1


def test_data_blocks_nest_parents_and_say_whose_data_it_is():
    text = prompt.data_blocks(TREE, [[0, 0], [1, 0]], "the speaker's own row")
    assert text.startswith('## customers record (the speaker\'s own row)\n{"customer_id": 5, "first_name": "a5", "last_name": "b5"')
    assert '- vip (own): {"customer_id": 5, "level": 3}' in text
    assert '- staff (another person\'s data: s2): {"staff_id": 2, "name": "s2"}' in text
    assert "## orders: orders records (1 of 14 shown)\n- orders (own): " in text
    assert '\n  - products (public, shared reference data owned by nobody): {"product_id": 0' in text
    long = {**TREE, "anchor_row": {**TREE["anchor_row"], "bio": "y" * 500}}
    assert '"bio": "' + "y" * 200 + '... (500 chars)"' in prompt.data_blocks(long, [], "x")


def test_messages_hold_the_rules_materials_and_plan():
    p = plan_for("1_self", batch={"table": "orders", "label": "orders", "count": 14, "all": False}, ownership_subquery=False)
    sysm, u = (m["content"] for m in prompt.build_messages(DB, ANCHOR, TREE, p, MATERIALS))
    assert "only asks for changes" in sysm and "no SELECT statements" in sysm and "outputs" not in sysm
    assert "## Principles for generating SQL calls\n- At the beginning of the conversation, you have to authenticate" in sysm
    assert "must deny any requests for tasks related to any other user" in sysm   # DySQL's agent policy, verbatim
    assert "Wrap every table name in double quotes" in sysm and f"## Instruction example (for style only" in sysm and p["example"] in sysm
    assert u.startswith("# Database\nA small shop.\n\nData quirks (copy names and values exactly as stored):\n- qty is never 0.")
    assert "CREATE TABLE customers" in u and "unrelated" not in u                          # key notes of the tables in scope only
    assert ("The speaker is a5 b5, the person in customers with customer_id = 5. Their first sentence gives their name and their ID, "
            "written with the word ID or the column name (customer_id 5 or ID 5).") in u
    assert "no new row is added to customers (that would be a new person)" in u   # the pilots' type mismatches did that
    assert "changes several of the person's orders rows in orders at once (there are 14)" in u and "between 2 and 13 rows" in u
    assert "written in the instruction exactly as the SQL uses it" in u
    assert "identify the person by customer_id = 5; names can repeat" in u and "40 to 80 words" in u


def test_subquery_archive_batch_and_proxy_wording():
    p = plan_for("1_self", batch={"table": "orders", "label": "orders", "count": 14, "all": True})
    u = prompt.build_messages(DB, ANCHOR, TREE, p, MATERIALS)[1]["content"]
    assert "changes all 14 of the person's orders rows in orders at once; the instruction says it means all of them." in u
    p = plan_for("1_self", ownership_subquery=True, archive="orders")
    u = prompt.build_messages(DB, ANCHOR, TREE, p, MATERIALS)[1]["content"]
    assert "WHERE customer_id = (SELECT customer_id FROM \"customers\" WHERE email = 'a5@x.org'), instead of writing customer_id = 5." in u
    assert ('First copy all the orders rows you will change, in one statement, as new rows with INSERT INTO "orders" ... '
            'SELECT ... FROM "orders"') in u
    p5 = plan_for("5_proxy")
    u = prompt.build_messages(DB, ANCHOR, TREE, p5, MATERIALS)[1]["content"]
    assert f"The speaker is not in the database: {p5['style']['name']}, {p5['style']['role']}." in u and "the person the request is about" in u


def test_sql_value_quotes_text():
    assert prompt.sql_value("O'Brien") == "'O''Brien'" and prompt.sql_value(42) == "42"


def test_style_varies_tones_names_and_roles():
    ps = plans(400, seed=1)
    proxies = [p for p in ps if p["task_type"] == "5_proxy"]
    assert len({p["style"]["name"] for p in proxies}) > 30 and len({p["style"]["role"] for p in proxies}) >= 8
    assert all(p["style"]["name"] is None for p in ps if p["task_type"] != "5_proxy")
    assert len({p["style"]["tone"] for p in ps}) >= 6 and not any("question" in t for t in prompt.TONES)


def test_an_archive_leaves_a_write_for_every_other_table():
    # the copy and the change of the original are two statements on the archive's table; each other table needs one
    arch = [p for p in plans(6000) if p["shape"]["archive"]]
    assert arch and all(p["shape"]["n_writes"] >= p["shape"]["n_tables"] + 1 for p in arch)
    assert any(p["shape"]["n_tables"] == 2 for p in arch)


def test_an_archive_never_comes_with_a_batch_and_changes_the_originals_by_key():
    # a batch picks rows by a condition or takes the whole group, which matches the fresh copies as well
    ps = plans(6000)
    assert any(p["shape"]["archive"] for p in ps) and any(p["shape"]["batch"] for p in ps)
    assert not any(p["shape"]["archive"] and p["shape"]["batch"] for p in ps)
    p = plan_for("1_self", archive="orders")
    u = prompt.build_messages(DB, ANCHOR, TREE, p, MATERIALS)[1]["content"]
    assert ("then UPDATE or DELETE the original rows by their order_id values; the copies get new order_id values "
            "and stay as they are.") in u


def test_a_tree_without_events_asks_for_no_more_writes_than_it_has_tables():
    # hr_1: 100 of 107 employees have no events, so the speaker's row and its attributes are all there is to write;
    # "3 statements on 1 table" became three UPDATEs of the same row
    ps = plans(1000, NO_EVENTS)
    assert all(p["shape"]["n_writes"] <= len(p["scope"]) for p in ps)
    assert Counter(p["shape"]["n_writes"] for p in ps)[2] > 0          # the root and its vip attribute: two writes fit


def test_a_batch_of_two_rows_takes_both():
    # "by a condition" over a group of two read "it changes between 2 and 1 rows"
    two = {**TREE, "events": [{**TREE["events"][0], "count": 2, "rows": TREE["events"][0]["rows"][:2]}, TREE["events"][1]]}
    batches = [p["shape"]["batch"] for p in plans(3000, two) if p["shape"]["batch"]]
    assert batches and all(b["all"] and b["count"] == 2 for b in batches)
