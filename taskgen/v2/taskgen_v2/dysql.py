# taskgen/v2/taskgen_v2/dysql.py
"""DySQL-Bench's own 13 databases and 1062 gold tasks, shaped like generated candidates. The check's calibration
(scripts/calibrate_check.py) and the DySQL column of the task-set metrics (metrics.py) both read them from here."""
import csv, glob, importlib, os
from taskgen_common.db_select import profile_db, all_fks, row_key
from taskgen_common.db_anchor import update_targets, anchors
from taskgen_common.paths import DATA, DYSQL_ENVS

TYPES_CSV = os.path.join(DATA, "dysql_task_types.csv")
ENVS = sorted(os.path.basename(os.path.dirname(os.path.dirname(f))) for f in glob.glob(f"{DYSQL_ENVS}/*/data/*.sqlite"))


def db_rec(env):
    path = glob.glob(f"{DYSQL_ENVS}/{env}/data/*.sqlite")[0]
    p = profile_db(path)
    fks = [f for f in all_fks(p) if f["hit"] is None or f["hit"] >= 0.3]
    keys = {t["name"]: row_key(t) for t in p["tables"] if row_key(t)}
    anc = anchors(p, fks, keys, update_targets(p, keys, 200), 5)
    return {"source": "dysql", "db": env, "path": path, "anchors": anc,
            "fks": [{"table": f["table"], "col": f["cols"][0], "ref_table": f["ref_table"], "ref_col": f["ref_cols"][0],
                     "hit": f["hit"], "source": f["source"]} for f in fks if len(f["cols"]) == 1 and f["ref_cols"][0]]}


def _rows(env):
    with open(TYPES_CSV, encoding="utf-8") as f:
        return {int(r["idx"]): r for r in csv.DictReader(f) if r["env"] == env}


def candidates(env):
    tasks = importlib.import_module(f"dysql_bench.envs.{env}.tasks_test").TASKS_TEST
    rec = db_rec(env)
    meta = _rows(env)
    out = []
    for i, t in enumerate(tasks):
        m = meta[i]
        ids = [x.split(":", 1) for x in m["speaker_ids"].split(";") if ":" in x]
        anchor_table, kv = None, None
        if m["speaker"] == "db_person" and ids:
            anchor_table, kv = ids[0]
            kv = int(kv) if kv.lstrip("-").isdigit() else kv
        if anchor_table is None or not any(a["table"] == anchor_table for a in rec["anchors"]):
            written = {w.split(" ", 1)[1].split(":")[0] for w in m["writes"].split(" | ") if " " in w}
            a = next((a for a in rec["anchors"] if written <= {a["table"], *a["down"], *a["up"]}), rec["anchors"][0])
            anchor_table, kv = a["table"], None
        out.append({"id": f"dysql:{env}:{i}", "anchor_table": anchor_table, "key_value": kv, "group": m["group"],
                    "speaker_ids": [[t, k] for t, k in ids] if m["speaker"] == "db_person" else None,
                    "speaker_in_db": m["speaker"] == "db_person", "instruction": t.instruction,
                    "actions": [{"sql": a.kwargs["sql"]} for a in t.actions if a.name == "sql"]})
    return out
