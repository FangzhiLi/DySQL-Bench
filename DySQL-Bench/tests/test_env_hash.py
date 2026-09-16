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
    cur.execute("INSERT INTO a VALUES (1,'x')"); cur.execute("INSERT INTO a VALUES (2,'keep')")
    cur.execute("INSERT INTO b VALUES (1)"); c.commit()
    return c, cur, dirpath

def _env(tmp, gold_sql="UPDATE a SET v='y' WHERE id=1"):
    task = Task(user_id="1", instruction="i",
                actions=[Action(name="sql", kwargs={"sql": gold_sql})])
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
        # row-level diff: only the changed row shows up on each side, row 2 does not
        d = res.info.row_diff["a"]
        assert d["only_agent"] == [[1, "wrong"]] and d["only_gold"] == [[1, "y"]]
        assert d["n_only_agent"] == 1 and d["n_only_gold"] == 1
        assert "b" not in res.info.row_diff

def test_row_diff_on_delete_vs_update(monkeypatch):
    """Agent deleted where gold updated: agent side has nothing, gold side has the updated row."""
    with tempfile.TemporaryDirectory() as tmp:
        env = _env(tmp)
        env.cursor.execute("DELETE FROM a WHERE id=1"); env.conn.commit()
        monkeypatch.setattr(env, "delete_db", lambda: None)
        res = env.calculate_reward()
        d = res.info.row_diff["a"]
        assert d["only_agent"] == [] and d["only_gold"] == [[1, "y"]]

def test_match_has_empty_diff(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        env = _env(tmp)
        env.cursor.execute("UPDATE a SET v='y' WHERE id=1"); env.conn.commit()
        monkeypatch.setattr(env, "delete_db", lambda: None)
        res = env.calculate_reward()
        assert res.reward == 1.0 and res.info.mismatched_tables == [] and res.info.row_diff == {}

def test_overall_hash_unchanged_by_refactor():
    """get_data_hash must still hash the full data tuple, not the per-table hashes."""
    with tempfile.TemporaryDirectory() as tmp:
        env = _env(tmp)
        from dysql_bench.envs.base import consistent_hash, to_hashable
        expected = consistent_hash(to_hashable(env._collect_table_data()))
        assert env.get_data_hash() == expected

def test_sql_log_records_rowcount_and_errors(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        env = _env(tmp)
        env.step(Action(name="sql", kwargs={"sql": "SELECT * FROM a"}))
        env.step(Action(name="sql", kwargs={"sql": "UPDATE a SET v='z' WHERE id=99"}))   # 0 rows
        env.step(Action(name="sql", kwargs={"sql": "UPDATE a SET v='y' WHERE id=1; DELETE FROM b"}))  # 2 stmts
        env.step(Action(name="sql", kwargs={"sql": "SELECT * FROM nope"}))
        log = env.sql_log
        assert [e["type"] for e in log] == ["SELECT", "UPDATE", "UPDATE", "DELETE", "SELECT"]
        assert [e["rowcount"] for e in log] == [2, 0, 1, 1, None]
        assert log[-1]["error"].startswith("no such table")
        assert all(e["phase"] == "agent" for e in log)
        assert all("duration_s" in e and e["step"] >= 1 for e in log)
        # gold replay during reward is logged too, tagged 'gold'
        monkeypatch.setattr(env, "delete_db", lambda: None)
        env.calculate_reward()
        gold = [e for e in env.sql_log if e["phase"] == "gold"]
        assert len(gold) == 1 and gold[0]["type"] == "UPDATE" and gold[0]["rowcount"] == 1

def test_sql_log_reset_on_reset():
    with tempfile.TemporaryDirectory() as tmp:
        env = _env(tmp)
        env.step(Action(name="sql", kwargs={"sql": "SELECT 1"}))
        assert len(env.sql_log) == 1
        env.user.reset = lambda instruction=None: "hi"   # avoid stdin in HumanUser
        env.reset(task_index=0)
        assert env.sql_log == []
