# tests/test_env_hash.py
import sqlite3, os, tempfile
from dysql_bench.envs.base import Env
from dysql_bench.types import Task, Action

def _make_db(dirpath):
    """Mimic the real data_load_func: a fresh copy of the source DB on every call."""
    p = os.path.join(dirpath, "t.sqlite")
    if os.path.exists(p):
        os.remove(p)
    c = sqlite3.connect(p); cur = c.cursor()
    cur.execute("CREATE TABLE a(id INTEGER, v TEXT)"); cur.execute("CREATE TABLE b(id INTEGER)")
    cur.execute("INSERT INTO a VALUES (1,'x')"); cur.execute("INSERT INTO b VALUES (1)"); c.commit()
    return c, cur, dirpath

def _env(tmp):
    task = Task(user_id="1", instruction="i",
                actions=[Action(name="sql", kwargs={"sql": "UPDATE a SET v='y' WHERE id=1"})])
    return Env(data_load_func=lambda tid: _make_db(tmp), table_names=["a", "b"], tasks=[task],
               wiki="w", user_strategy="human", user_model="", user_model_api="", task_index=0)

def test_table_hashes_and_mismatch(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        env = _env(tmp)
        h = env.get_table_hashes()
        assert set(h) == {"a", "b"}
        env.cursor.execute("UPDATE a SET v='wrong' WHERE id=1"); env.conn.commit()
        monkeypatch.setattr(env, "delete_db", lambda: None)
        res = env.calculate_reward()
        assert res.reward == 0.0
        assert res.info.mismatched_tables == ["a"]

def test_overall_hash_unchanged_by_refactor():
    """get_data_hash must still hash the full data tuple, not the per-table hashes."""
    with tempfile.TemporaryDirectory() as tmp:
        env = _env(tmp)
        from dysql_bench.envs.base import consistent_hash, to_hashable
        expected = consistent_hash(to_hashable(env._collect_table_data()))
        assert env.get_data_hash() == expected
