# dysql_bench/envs/gen/__init__.py
"""Generic environment for generated tasks: database path and task file come from data/taskgen/manifest.json
(env var TASKGEN_MANIFEST overrides), the agent policy is the header shared by the 13 DySQL envs plus this
database's DDL, and the per-thread DB copy works exactly like the other envs' load_sql_data."""
import json, os, shutil, sqlite3
from typing import Optional, Union
from dysql_bench.envs.base import Env
from dysql_bench.envs.user import UserStrategy
from dysql_bench.types import Task, Action
from dysql_bench.taskgen import io, schema

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MANIFEST = os.path.join(io.ROOT, "data", "taskgen", "manifest.json")
HEADER = open(os.path.join(HERE, "agent_policy_header.md"), encoding="utf-8").read()
TIMEOUT = 10


def load_tasks(path):
    return [Task(user_id=r["user_id"], instruction=r["instruction"], actions=[Action(**a) for a in r["actions"]])
            for r in io.read_jsonl(path)]


def make_loader(sqlite_path, db):
    def load_sql_data(thread_id):
        folder = os.path.join(HERE, "tmp", db, f"thread_{os.getpid()}_{thread_id}")
        os.makedirs(folder, exist_ok=True)
        target = os.path.join(folder, os.path.basename(sqlite_path))
        shutil.copy(sqlite_path, target)
        conn = sqlite3.connect(target, timeout=TIMEOUT)
        return conn, conn.cursor(), folder
    return load_sql_data


def table_names(sqlite_path):
    c = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
    try:
        return [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY rowid")]
    finally:
        c.close()


class GenEnv(Env):
    def __init__(self, db: str, user_strategy: Union[str, UserStrategy] = UserStrategy.LLM, user_model: str = "gpt-4o",
                 user_model_api: str = None, task_split: str = "train", task_index: Optional[int] = None,
                 thread_id: int = None, manifest: Optional[str] = None):
        manifest = manifest or os.environ.get("TASKGEN_MANIFEST") or DEFAULT_MANIFEST
        with open(manifest, encoding="utf-8") as f:
            m = json.load(f)[db]
        sqlite_path = io.resolve_db_path(m["sqlite"])
        tasks_path = m["tasks"] if os.path.isabs(m["tasks"]) else os.path.join(io.ROOT, m["tasks"])
        super().__init__(data_load_func=make_loader(sqlite_path, db), table_names=table_names(sqlite_path),
                         tasks=load_tasks(tasks_path), wiki=HEADER.rstrip("\n") + "\n" + schema.ddl(sqlite_path),
                         user_strategy=user_strategy, user_model=user_model, user_model_api=user_model_api,
                         task_index=task_index, thread_id=thread_id)
