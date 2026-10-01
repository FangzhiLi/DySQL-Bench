# tests/test_taskgen_convert_env.py
import json, os
from taskgen_common.testing import make_db, SHOP
from taskgen_v2 import convert, io
from dysql_bench.envs import get_env
from dysql_bench.envs.gen import GenEnv, load_tasks
from dysql_bench.types import Action

REC = {"id": "test:shop:customers:5:0", "db": "shop", "source": "test", "anchor_table": "customers", "anchor_key": "customer_id",
       "key_value": 5, "instruction": "I am a5 b5. Set qty of my order 5 to 3.", "actions": [{"sql": "UPDATE orders SET qty = 3 WHERE order_id = 5"}],
       "plan": {"task_type": "1_self"}, "task_type": "1_self", "template": "1_self|UPDATE orders",
       "difficulty": {"score": 0, "level": "easy"}, "gen_model": "g", "verify_model": "v",
       "votes": [{"verdict": "yes"}, {"verdict": "yes"}, {"verdict": "no"}]}


def setup(tmp_path):
    db = make_db(tmp_path, "shop", SHOP)
    rec = {"source": "test", "db": "shop", "path": db, "anchors": [], "fks": []}
    tasks = str(tmp_path / "data" / "shop" / "tasks.jsonl"); manifest = str(tmp_path / "manifest.json")
    n = convert.write_tasks(rec, [REC], tasks)
    convert.update_manifest(manifest, "shop", db, tasks, "test:shop")
    return db, tasks, manifest, n


def test_write_tasks_and_manifest(tmp_path):
    db, tasks, manifest, n = setup(tmp_path)
    row = io.read_jsonl(tasks)[0]
    assert n == 1 and row["user_id"] == "0" and row["actions"] == [{"name": "sql", "kwargs": {"sql": "UPDATE orders SET qty = 3 WHERE order_id = 5"}}]
    assert row["meta"]["task_type"] == "1_self" and row["meta"]["verify_votes"] == ["yes", "yes", "no"] and row["meta"]["difficulty"]["level"] == "easy"
    m = json.load(open(manifest))["shop"]
    assert m["db_key"] == "test:shop" and m["sqlite"] == db and m["tasks"] == os.path.join("data", "shop", "tasks.jsonl")   # relative to the manifest


def test_gen_env_loads_tasks_ddl_and_scores_gold(tmp_path, monkeypatch):
    db, tasks, manifest, _ = setup(tmp_path)
    env = GenEnv("shop", user_strategy="human", user_model="", user_model_api="", task_index=0, manifest=manifest)
    assert env.table_names == ["customers", "products", "orders"] and "CREATE TABLE customers" in env.wiki
    assert env.wiki.startswith("# Agent policy") and env.task.instruction.startswith("I am a5 b5")
    env.step(Action(name="sql", kwargs={"sql": "UPDATE orders SET qty = 3 WHERE order_id = 5"}))
    monkeypatch.setattr(env, "delete_db", lambda: None)
    assert env.calculate_reward().reward == 1.0
    env2 = GenEnv("shop", user_strategy="human", user_model="", user_model_api="", task_index=0, manifest=manifest)
    env2.step(Action(name="sql", kwargs={"sql": "UPDATE orders SET qty = 9 WHERE order_id = 5"}))
    monkeypatch.setattr(env2, "delete_db", lambda: None)
    assert env2.calculate_reward().reward == 0.0


def test_get_env_dispatches_gen_prefix(tmp_path, monkeypatch):
    db, tasks, manifest, _ = setup(tmp_path)
    monkeypatch.setenv("TASKGEN_MANIFEST", manifest)
    env = get_env("gen:shop", user_strategy="human", user_model="", user_model_api="", task_split="train", task_index=0)
    assert isinstance(env, GenEnv) and len(env.tasks) == 1
