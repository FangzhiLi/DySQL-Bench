# taskgen/v1/taskgen_v1/convert.py
"""Final output: tasks.jsonl in Task shape (+ meta) and the manifest GenEnv reads."""
import json, os
from taskgen_v1 import io


def to_task_row(i, r):
    meta = {k: r.get(k) for k in ("id", "db", "source", "anchor_table", "anchor_key", "key_value", "task_type",
                                   "difficulty", "template", "plan", "gen_model", "verify_model")}
    meta["verify_votes"] = [v["verdict"] for v in r.get("votes", [])]
    return {"user_id": str(i), "instruction": r["instruction"],
            "actions": [{"name": "sql", "kwargs": {"sql": a["sql"]}} for a in r["actions"]], "meta": meta}


def write_tasks(db_rec, records, tasks_path):
    rows = [to_task_row(i, r) for i, r in enumerate(records)]
    if os.path.exists(tasks_path):
        os.remove(tasks_path)
    io.append_jsonl(tasks_path, rows)
    return len(rows)


def update_manifest(manifest_path, db, sqlite_path, tasks_path, db_key):
    """sqlite is stored relative to TEXT2SQL_BENCH and tasks relative to the manifest's folder when they live there
    (that is how GenEnv resolves them, so the whole output folder can move), else as given."""
    m = json.load(open(manifest_path, encoding="utf-8")) if os.path.exists(manifest_path) else {}
    rel = os.path.relpath(sqlite_path, io.DATA_ROOT)
    t = os.path.relpath(os.path.abspath(tasks_path), os.path.dirname(os.path.abspath(manifest_path)))
    m[db] = {"db_key": db_key, "sqlite": sqlite_path if rel.startswith("..") else rel,
             "tasks": tasks_path if t.startswith("..") else t}
    os.makedirs(os.path.dirname(os.path.abspath(manifest_path)), exist_ok=True)
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=1)
