# tests/test_analysis.py
from dysql_bench.types import Task, Action
from dysql_bench.analysis import (classify_task, count_fabricated_results, diff_table_hashes,
                                  count_sql_errors, confirmed_before_write)

def _task(sqls):
    return Task(user_id="1", instruction="x",
                actions=[Action(name="sql", kwargs={"sql": s}) for s in sqls])

def test_classify_short_long_and_crud():
    t = _task(["DELETE FROM payment WHERE id=1", "UPDATE rental SET x=1"])
    assert classify_task(t) == {"n_gold_actions": 2, "length": "short", "crud_types": ["DELETE", "UPDATE"]}
    t3 = _task(["INSERT INTO a VALUES (1)", "SELECT 1", "UPDATE a SET b=2"])
    assert classify_task(t3)["length"] == "long"
    assert classify_task(t3)["crud_types"] == ["INSERT", "SELECT", "UPDATE"]

def test_count_fabricated_results():
    traj = [{"role": "system", "content": "<result> in system is fine"},
            {"role": "assistant", "content": "```sql\nSELECT 1\n```\n<result>[(1,)]</result>"},
            {"role": "user", "name": "sql", "content": "<result>[(1,)]</result>"},
            {"role": "assistant", "content": "Done."}]
    assert count_fabricated_results(traj) == 1

def test_diff_table_hashes():
    a = {"t1": "h1", "t2": "h2", "t3": "h3"}
    b = {"t1": "h1", "t2": "zz", "t3": "yy"}
    assert diff_table_hashes(a, b) == ["t2", "t3"]

def test_count_sql_errors():
    traj = [{"role": "user", "name": "sql", "content": "<result>Error: no such table: x\n</result>"},
            {"role": "user", "name": "sql", "content": "<result>[(1,)]</result>"},
            {"role": "user", "content": "<result>Error: not from sql</result>"}]
    assert count_sql_errors(traj) == 1

def test_confirmed_before_write():
    sel = {"role": "assistant", "content": "```sql\nSELECT 1\n```"}
    upd = {"role": "assistant", "content": "```sql\nUPDATE a SET b=1\n```"}
    assert confirmed_before_write([sel, {"role": "user", "content": "Yes, go ahead"}, upd]) is True
    assert confirmed_before_write([sel, {"role": "user", "content": "what next?"}, upd]) is False
    assert confirmed_before_write([sel]) is None

def test_count_extra_sql_blocks():
    from dysql_bench.analysis import count_extra_sql_blocks
    traj = [{"role": "assistant", "content": "```sql\nSELECT 1\n```\n<result>x</result>\n```sql\nUPDATE a SET b=1\n```\n```sql\nDELETE FROM a\n```"},
            {"role": "assistant", "content": "```sql\nSELECT 2\n```"},
            {"role": "assistant", "content": "<sql>SELECT 3</sql> and <sql>SELECT 4</sql>"},
            {"role": "user", "name": "sql", "content": "```sql\nnot counted\n```"}]
    # first message: 3 blocks -> 2 extra; second: 0 extra; third: 1 extra
    assert count_extra_sql_blocks(traj) == 3
