# tests/test_resume.py
import json, tempfile, os
from dysql_bench.run import load_done, build_meta
from dysql_bench.types import Task, Action

def test_load_done_reads_task_trial_pairs():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "ckpt.json")
        json.dump([{"task_id": 3, "trial": 0, "reward": 1, "info": {}, "traj": []},
                   {"task_id": 5, "trial": 1, "reward": 0, "info": {}, "traj": []}], open(p, "w"))
        assert load_done(p) == {(3, 0), (5, 1)}
    assert load_done("/nonexistent.json") == set()
    assert load_done(None) == set()

def test_build_meta():
    task = Task(user_id="1", instruction="i", actions=[Action(name="sql", kwargs={"sql": "UPDATE a SET b=1"})])
    info = {"termination": "user_stop", "n_steps": 4,
            "reward_info": {"info": {"mismatched_tables": ["a"]}}}
    traj = [{"role": "assistant", "content": "<result>fake</result>",
             "usage": {"prompt_tokens": 4000, "completion_tokens": 5}},
            {"role": "user", "name": "sql", "content": "<result>Error: boom</result>"},
            {"role": "assistant", "content": "```sql\nUPDATE a SET b=1\n```",
             "usage": {"prompt_tokens": 4100, "completion_tokens": 3}}]
    user_traj = [{"role": "assistant", "content": "hi", "usage": {"completion_tokens": 7}}]
    m = build_meta("pagila", task, info, traj, user_traj, wall_s=12.5)
    assert m["length"] == "short" and m["crud_types"] == ["UPDATE"]
    assert m["termination"] == "user_stop" and m["n_steps"] == 4
    assert m["n_fabricated_results"] == 1 and m["mismatched_tables"] == ["a"]
    assert m["n_sql_errors"] == 1 and m["confirmed_before_write"] is False
    assert m["agent_completion_tokens"] == 8 and m["user_completion_tokens"] == 7
    assert m["last_prompt_tokens"] == 4100
    assert m["wall_s"] == 12.5

def test_build_meta_tolerates_missing_fields():
    task = Task(user_id="1", instruction="i", actions=[])
    m = build_meta("pagila", task, {}, [], [], wall_s=0)
    assert m["termination"] is None and m["mismatched_tables"] == []
    assert m["last_prompt_tokens"] is None and m["confirmed_before_write"] is None
