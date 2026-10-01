# tests/test_taskgen_prompt.py
import random
from collections import Counter
from taskgen_v2 import prompt

ANCHOR = {"table": "customers", "key": "customer_id", "names": ["first_name", "last_name"]}
DB = {"source": "test", "db": "shop", "path": "x", "anchors": [], "fks": []}


def order(i, label="own"):
    return {"table": "orders", "row": {"order_id": i, "customer_id": 5, "product_id": i, "qty": 1}, "label": label,
            "parents": [{"table": "products", "row": {"product_id": i, "name": f"p{i}", "price": 1.0}, "label": "public", "parents": []}]}


TREE = {"anchor_table": "customers", "anchor_key": "customer_id", "key_value": 5, "anchor_name": "a5 b5",
        "anchor_row": {"customer_id": 5, "first_name": "a5", "last_name": "b5"}, "profile_version": "v1",
        "parents": [{"table": "staff", "row": {"staff_id": 2, "name": "s2"}, "label": "other:s2", "parents": []}],
        "attributes": {"vip": [{"customer_id": 5, "level": 3}]},
        "events": [{"table": "orders", "label": "orders", "count": 14, "rows": [order(i) for i in range(12)]},
                   {"table": "reviews", "label": "reviews", "count": 1,
                    "rows": [{"table": "reviews", "row": {"review_id": 1, "customer_id": 5, "stars": 4}, "label": "own", "parents": []}]}]}
NO_PUBLIC = {**TREE, "events": [TREE["events"][1]]}


def plan_for(task_type, difficulty="easy", tree=TREE, **shape):
    rng = random.Random(0)
    while True:
        p = prompt.sample_plan(rng, tree, ANCHOR)
        if p["task_type"] == task_type and p["difficulty"] == difficulty and all(p["shape"][k] == v for k, v in shape.items()):
            return p


def test_examples_cover_every_type_with_at_least_two():
    ex = prompt.load_examples()
    assert set(ex) == set(prompt.CFG["TYPE_MIX"]) and all(len(v) >= 2 for v in ex.values())


def test_no_type_4_and_public_types_need_a_public_row():
    assert prompt.feasible_types(TREE) == ["1_self", "2_self_and_public", "3_public_only", "5_proxy"]
    assert prompt.feasible_types(NO_PUBLIC) == ["1_self", "5_proxy"]


def test_sample_plan_follows_the_mix_and_shows_more_events_when_harder():
    rng = random.Random(0)
    plans = [prompt.sample_plan(rng, TREE, ANCHOR) for _ in range(3000)]
    types, diffs = Counter(p["task_type"] for p in plans), Counter(p["difficulty"] for p in plans)
    assert "4_other_person" not in types
    assert abs(types["1_self"] / 3000 - 0.46 / 0.92) < 0.04 and abs(types["5_proxy"] / 3000 - 0.29 / 0.92) < 0.04
    assert abs(diffs["hard"] / 3000 - 0.29) < 0.04
    for p in plans:
        lo, hi = prompt.CFG["EVENTS_SHOWN"][p["difficulty"]]
        assert lo <= len(p["events"]) <= hi
        if p["task_type"] in ("2_self_and_public", "3_public_only"):
            assert p["shape"]["public_table"] and p["tables"]["public"] == ["products"]
        if p["difficulty"] == "hard":
            assert p["shape"]["n_writes"] >= 2 and p["shape"]["n_tables"] >= 2
        assert p["example"] in prompt.load_examples()[p["task_type"]]
    assert {p["tables"]["own"][0] for p in plans} == {"customers"}


def test_long_data_loses_events_until_it_fits():
    big = {**TREE, "events": [{**TREE["events"][0], "rows": [{**order(i), "row": {**order(i)["row"], "note": "x" * 150}} for i in range(12)]}]}
    cfg = {**prompt.CFG, "DATA_CHARS": 1200}
    p = prompt.sample_plan(random.Random(3), big, ANCHOR, cfg)
    assert 1 <= len(p["events"]) < prompt.CFG["EVENTS_SHOWN"][p["difficulty"]][0]
    assert len(prompt.data_blocks(big, p["events"], "x", cfg)) <= 1200 or len(p["events"]) == 1


def test_data_blocks_nest_parents_and_say_whose_data_it_is():
    text = prompt.data_blocks(TREE, [[0, 0], [1, 0]], "the speaker's own row")
    assert text.startswith('## customers record (the speaker\'s own row)\n{"customer_id": 5, "first_name": "a5", "last_name": "b5"}')
    assert '- vip (own): {"customer_id": 5, "level": 3}' in text
    assert '- staff (another person\'s data: s2): {"staff_id": 2, "name": "s2"}' in text
    assert "## orders: orders records (1 of 14 shown)\n- orders (own): " in text
    assert '\n  - products (public, shared reference data owned by nobody): {"product_id": 0' in text
    assert "## reviews: reviews records (1 of 1 shown)" in text
    long = {**TREE, "anchor_row": {**TREE["anchor_row"], "bio": "y" * 500}}
    assert '"bio": "' + "y" * 200 + '... (500 chars)"' in prompt.data_blocks(long, [], "x")


def test_build_messages_fills_type_shape_and_scope():
    p = plan_for("2_self_and_public", "medium")
    msgs = prompt.build_messages(DB, ANCHOR, TREE, p, "A shop.", "CREATE TABLE customers (...)")
    assert msgs[0]["role"] == "system" and f"## Instruction Example\n{p['example']}" in msgs[0]["content"]
    u = msgs[1]["content"]
    assert "a5 b5 (customer_id = 5)" in u and "shared table (products)" in u and "At least one write must change a shared table: products." in u
    assert "## customers record" in u and "CREATE TABLE customers" in u and "A shop." in u
    p5 = plan_for("5_proxy")
    u = prompt.build_messages(DB, ANCHOR, TREE, p5, "A shop.", "DDL")[1]["content"]
    assert "NOT in the database" in u and "the person the request is about" in u
    assert f"The speaker is {p5['style']['name']}, {p5['style']['role']}" in u


def test_system_requires_quoted_table_names():
    s = prompt.build_messages(DB, ANCHOR, TREE, plan_for("1_self"), "A shop.", "DDL")[0]["content"]
    assert "Wrap every table name in double quotes" in s and '"transaction"' in s


def test_next_ids_only_for_tables_the_prompt_shows():
    p = plan_for("1_self")
    u = prompt.build_messages(DB, ANCHOR, TREE, p, "A shop.", "DDL",
                              next_ids={"orders": ("order_id", 101), "products": ("product_id", 61), "unrelated": ("id", 9)})[1]["content"]
    assert "## Next unused primary keys" in u and "orders.order_id = 101" in u and "unrelated" not in u
    assert "Next unused" not in prompt.build_messages(DB, ANCHOR, TREE, p, "A shop.", "DDL")[1]["content"]


def test_sample_plan_style_varies_names_roles_and_openers():
    rng = random.Random(1)
    plans = [prompt.sample_plan(rng, TREE, ANCHOR) for _ in range(400)]
    proxies = [p for p in plans if p["task_type"] == "5_proxy"]
    assert len({p["style"]["name"] for p in proxies}) > 30 and len({p["style"]["role"] for p in proxies}) >= 8
    assert all(p["style"]["name"] is None for p in plans if p["task_type"] != "5_proxy")
    assert len({p["style"]["opener"] for p in plans}) >= 6
