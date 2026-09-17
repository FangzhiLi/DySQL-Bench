# tests/test_summarize.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from summarize import summarize, to_markdown

def _r(task, trial, reward, env="pagila", length="short", term="user_stop", fab=0, tables=()):
    return {"task_id": task, "trial": trial, "reward": reward, "info": {}, "traj": [],
            "meta": {"env": env, "length": length, "termination": term, "n_steps": 3,
                     "wall_s": 10.0, "agent_completion_tokens": 100, "user_completion_tokens": 20,
                     "n_fabricated_results": fab, "mismatched_tables": list(tables),
                     "n_sql_errors": 1 if fab else 0, "confirmed_before_write": True if task == 1 else None,
                     "last_prompt_tokens": 5000 + 1000 * task,
                     "n_extra_sql_blocks": 2 if fab else 0, "n_zero_row_writes": 1 if task == 0 else 0}}

def test_summarize_pass_hat_k_and_counts():
    rs = [_r(0, 0, 1), _r(0, 1, 0), _r(1, 0, 1), _r(1, 1, 1, length="long", fab=1, tables=("a",))]
    s = summarize(rs)
    assert s["overall"]["n_tasks"] == 2 and s["overall"]["n_runs"] == 4
    assert abs(s["overall"]["pass_hat_k"][1] - 0.75) < 1e-9
    assert abs(s["overall"]["pass_hat_k"][2] - 0.5) < 1e-9
    assert s["overall"]["fabricated_rate"] == 0.25
    assert s["overall"]["termination_counts"] == {"user_stop": 4}
    assert s["overall"]["top_mismatched_tables"][0] == ("a", 1)
    assert s["overall"]["sql_error_rate"] == 0.25
    assert s["overall"]["confirm_rate"] == 1.0   # only runs with a write are counted
    assert s["overall"]["last_prompt_p50"] == 5500 and s["overall"]["last_prompt_max"] == 6000
    assert s["overall"]["multi_sql_rate"] == 0.25
    assert s["overall"]["zero_row_write_rate"] == 0.5
    assert set(s["by_env"]) == {"pagila"}
    assert set(s["by_length"]) == {"short", "long"}

def test_markdown_renders_with_error_runs():
    """Runs with termination=error have sparse meta; the table must still render."""
    rs = [_r(0, 0, 1), {"task_id": 1, "trial": 0, "reward": 0.0, "info": {"error": "x"}, "traj": [],
                        "meta": {"env": "pagila", "termination": "error", "wall_s": 1.0}}]
    md = to_markdown(summarize(rs))
    assert "overall" in md and "error" in md

def test_same_task_id_in_different_envs_are_different_tasks():
    rs = [_r(0, 0, 1, env="pagila"), _r(0, 0, 0, env="retail")]
    s = summarize(rs)
    assert s["overall"]["n_tasks"] == 2 and s["overall"]["pass_hat_k"] == {1: 0.5}
