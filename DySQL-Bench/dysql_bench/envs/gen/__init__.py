# dysql_bench/envs/gen/__init__.py
"""Generic environment for generated task sets (gen:<db>). A task set is described by a manifest,
{db: {"sqlite": ..., "tasks": ...}}, that a task-generation version writes (taskgen/v1/output/manifest.json, ...);
it is passed as `manifest` or through the TASKGEN_MANIFEST env var. Relative task paths resolve against the
manifest's folder, relative sqlite paths against TEXT2SQL_BENCH. The agent policy is the header shared by the 13
DySQL envs plus this database's DDL, and the per-thread DB copy works exactly like the other envs' load_sql_data.
Independent of the generation code (taskgen/), so every version's output runs here unchanged."""
import json, os, shutil, sqlite3
from typing import Optional, Union
from dysql_bench.envs.base import Env
from dysql_bench.envs.user import UserStrategy
from dysql_bench.types import Task, Action

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_ROOT = os.path.expanduser(os.environ.get("TEXT2SQL_BENCH", "~/Documents/Isa/text2sql_bench"))
HEADER = open(os.path.join(HERE, "agent_policy_header.md"), encoding="utf-8").read()
TIMEOUT = 10


def read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def resolve_db_path(p):
    return p if os.path.isabs(p) else os.path.join(DATA_ROOT, p)


def ddl(db_path):
    c = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return "\n".join(r[0] for r in c.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND sql IS NOT NULL ORDER BY rowid"))
    finally:
        c.close()


def load_tasks(path):
    return [Task(user_id=r["user_id"], instruction=r["instruction"], actions=[Action(**a) for a in r["actions"]])
            for r in read_jsonl(path)]


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
        manifest = manifest or os.environ.get("TASKGEN_MANIFEST")
        if not manifest:
            raise ValueError("gen:<db> needs a task-set manifest: set TASKGEN_MANIFEST (e.g. taskgen/v1/output/manifest.json)")
        with open(manifest, encoding="utf-8") as f:
            m = json.load(f)[db]
        sqlite_path = resolve_db_path(m["sqlite"])
        tasks_path = m["tasks"] if os.path.isabs(m["tasks"]) else os.path.join(os.path.dirname(os.path.abspath(manifest)), m["tasks"])
        super().__init__(data_load_func=make_loader(sqlite_path, db), table_names=table_names(sqlite_path),
                         tasks=load_tasks(tasks_path), wiki=HEADER.rstrip("\n") + "\n" + ddl(sqlite_path),
                         user_strategy=user_strategy, user_model=user_model, user_model_api=user_model_api,
                         task_index=task_index, thread_id=thread_id)
