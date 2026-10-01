# tests/test_gen_env.py
"""GenEnv runs any generated task set from its manifest alone, without importing the generation code (taskgen/)."""
import json, sqlite3
import pytest
from dysql_bench.envs import get_env
from dysql_bench.envs.gen import GenEnv
from dysql_bench.types import Action

GOLD = "UPDATE orders SET qty = 3 WHERE order_id = 5"


def make_task_set(tmp_path):
    """shop.sqlite outside the set's folder (absolute path), tasks.jsonl inside it (path relative to the manifest)."""
    db = tmp_path / "shop.sqlite"
    c = sqlite3.connect(db)
    c.executescript("CREATE TABLE customers (customer_id INTEGER PRIMARY KEY, name TEXT);"
                    "CREATE TABLE orders (order_id INTEGER PRIMARY KEY, customer_id INTEGER REFERENCES customers, qty INTEGER);"
                    "INSERT INTO customers VALUES (5, 'Ann'); INSERT INTO orders VALUES (5, 5, 1);")
    c.commit(); c.close()
    (tmp_path / "set" / "shop").mkdir(parents=True)
    (tmp_path / "set" / "shop" / "tasks.jsonl").write_text(json.dumps(
        {"user_id": "0", "instruction": "I am Ann. Set qty of my order 5 to 3.",
         "actions": [{"name": "sql", "kwargs": {"sql": GOLD}}], "meta": {"task_type": "1_self"}}) + "\n")
    manifest = tmp_path / "set" / "manifest.json"
    manifest.write_text(json.dumps({"shop": {"db_key": "test:shop", "sqlite": str(db), "tasks": "shop/tasks.jsonl"}}))
    return str(manifest)


def env_for(manifest=None):
    return GenEnv("shop", user_strategy="human", user_model="", user_model_api="", task_index=0, manifest=manifest)


def test_task_path_resolves_against_the_manifest_folder_and_gold_scores_1(tmp_path, monkeypatch):
    env = env_for(make_task_set(tmp_path))
    assert env.table_names == ["customers", "orders"] and "CREATE TABLE orders" in env.wiki
    assert env.task.instruction.startswith("I am Ann")
    env.step(Action(name="sql", kwargs={"sql": GOLD}))
    monkeypatch.setattr(env, "delete_db", lambda: None)
    assert env.calculate_reward().reward == 1.0


def test_manifest_is_required_and_read_from_the_env_var(tmp_path, monkeypatch):
    monkeypatch.delenv("TASKGEN_MANIFEST", raising=False)
    with pytest.raises(ValueError, match="TASKGEN_MANIFEST"):
        env_for()
    monkeypatch.setenv("TASKGEN_MANIFEST", make_task_set(tmp_path))
    env = get_env("gen:shop", user_strategy="human", user_model="", user_model_api="", task_split="train", task_index=0)
    assert isinstance(env, GenEnv) and len(env.tasks) == 1
