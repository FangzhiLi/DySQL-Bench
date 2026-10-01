# tests/test_taskgen_prompt.py
import random
from collections import Counter
from taskgen_v1 import prompt

ANCHOR = {"table": "customers", "key": "customer_id", "kind": "person_named", "rows": 60, "names": ["first_name", "last_name"],
          "down": ["orders"], "up": ["products"], "update_targets": ["customers", "orders", "products"]}
DB = {"source": "test", "db": "shop", "path": "x", "anchors": [ANCHOR], "fks": []}
TREE = {"anchor_table": "customers", "anchor_key": "customer_id", "key_value": 5, "anchor_name": "a5 b5",
        "anchor_row": {"customer_id": 5, "first_name": "a5", "last_name": "b5"},
        "down": {"orders": [{"order_id": 5, "customer_id": 5, "product_id": 5, "qty": 1}]},
        "up": {"products": [{"product_id": 5, "name": "p5", "price": 1.0}]}}
OTHERS = [{"key_value": 9, "name": "a9 b9"}]


def test_examples_cover_every_type_with_at_least_two():
    ex = prompt.load_examples()
    assert set(ex) == set(prompt.CFG["TYPE_MIX"]) and all(len(v) >= 2 for v in ex.values())


def test_feasible_types_need_up_rows_and_others():
    assert prompt.feasible_types(TREE, ANCHOR, OTHERS) == ["1_self", "2_self_and_public", "3_public_only", "4_other_person", "5_proxy"]
    assert prompt.feasible_types({**TREE, "up": {}}, ANCHOR, []) == ["1_self", "5_proxy"]


def test_sample_plan_follows_the_mix_and_shapes():
    rng = random.Random(0)
    plans = [prompt.sample_plan(rng, TREE, ANCHOR, OTHERS) for _ in range(4000)]
    types, diffs = Counter(p["task_type"] for p in plans), Counter(p["difficulty"] for p in plans)
    assert abs(types["1_self"] / 4000 - 0.46) < 0.04 and abs(types["5_proxy"] / 4000 - 0.29) < 0.04
    assert abs(diffs["hard"] / 4000 - 0.29) < 0.04
    assert abs(sum(p["write_tables"] is None for p in plans) / 4000 - 0.30) < 0.04
    for p in plans:
        s = p["shape"]
        if p["difficulty"] == "easy" and p["task_type"] != "2_self_and_public":   # type 2 always needs two tables
            assert s["n_writes"] == 1 and s["n_tables"] == 1 and not s["ownership_subquery"] and not s["archive"]
        if p["difficulty"] == "hard":
            assert s["n_writes"] >= 2 and s["n_tables"] >= 2
        if p["task_type"] == "4_other_person":
            assert p["other"] == OTHERS[0]
        if p["task_type"] in ("2_self_and_public", "3_public_only"):
            assert s["public_table"]
        assert p["example"] in prompt.load_examples()[p["task_type"]]


def test_build_messages_names_data_blocks_and_type_text():
    plan = {"task_type": "5_proxy", "difficulty": "medium", "example": "EX",
            "shape": {"n_writes": 2, "n_tables": 1, "ownership_subquery": True, "archive": False, "public_table": False},
            "write_tables": ["orders"], "other": None}
    msgs = prompt.build_messages(DB, ANCHOR, TREE, plan, "A shop.", "CREATE TABLE customers (...)")
    assert msgs[0]["role"] == "system" and "## Instruction Example\nEX" in msgs[0]["content"]
    u = msgs[1]["content"]
    assert "## customers record" in u and "## orders records" in u and "## products records (shared" in u
    assert "NOT in the database" in u and "a5 b5" in u and "customer_id = 5" in u
    assert "exactly 2 write statements" in u and "subquery" in u and "Write to these tables: orders" in u
    assert "CREATE TABLE customers" in u and "A shop." in u


def test_build_messages_free_tables_and_other_person():
    plan = {"task_type": "4_other_person", "difficulty": "easy", "example": "EX",
            "shape": {"n_writes": 1, "n_tables": 1, "ownership_subquery": False, "archive": False, "public_table": False},
            "write_tables": None, "other": OTHERS[0]}
    u = prompt.build_messages(DB, ANCHOR, TREE, plan, "A shop.", "DDL")[1]["content"]
    assert "ANOTHER person: a9 b9 (customer_id = 9)" in u and "Choose freely" in u


def test_system_requires_quoted_table_names():
    plan = {"task_type": "1_self", "difficulty": "easy", "example": "EX", "style": {"opener": "O", "name": None, "role": None},
            "shape": {"n_writes": 1, "n_tables": 1, "ownership_subquery": False, "archive": False, "public_table": False},
            "write_tables": None, "other": None}
    s = prompt.build_messages(DB, ANCHOR, TREE, plan, "A shop.", "DDL")[0]["content"]
    assert 'Wrap every table name in double quotes' in s and '"transaction"' in s


def test_user_lists_next_ids_for_scope_tables_only():
    plan = {"task_type": "1_self", "difficulty": "easy", "example": "EX", "style": {"opener": "O", "name": None, "role": None},
            "shape": {"n_writes": 1, "n_tables": 1, "ownership_subquery": False, "archive": False, "public_table": False},
            "write_tables": None, "other": None}
    u = prompt.build_messages(DB, ANCHOR, TREE, plan, "A shop.", "DDL", next_ids={"orders": ("order_id", 101), "products": ("product_id", 61), "unrelated": ("id", 9)})[1]["content"]
    assert "## Next unused primary keys" in u and "orders.order_id = 101" in u and "products.product_id = 61" in u and "unrelated" not in u
    # no next_ids -> section absent
    assert "Next unused" not in prompt.build_messages(DB, ANCHOR, TREE, plan, "A shop.", "DDL")[1]["content"]


def test_sample_plan_style_varies_names_roles_and_openers():
    rng = random.Random(1)
    plans = [prompt.sample_plan(rng, TREE, ANCHOR, OTHERS) for _ in range(400)]
    proxies = [p for p in plans if p["task_type"] == "5_proxy"]
    assert len({p["style"]["name"] for p in proxies}) > 30 and len({p["style"]["role"] for p in proxies}) >= 8
    assert all(p["style"]["name"] is None for p in plans if p["task_type"] != "5_proxy")
    assert len({p["style"]["opener"] for p in plans}) >= 6
    p = next(p for p in proxies)
    u = prompt.build_messages(DB, ANCHOR, TREE, p, "A shop.", "DDL")[1]["content"]
    assert f"The speaker is {p['style']['name']}, {p['style']['role']}" in u and p["style"]["opener"] in u
