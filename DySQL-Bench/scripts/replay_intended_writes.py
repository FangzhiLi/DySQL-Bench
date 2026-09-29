#!/usr/bin/env python3
"""Offline replay of agent writes on a fresh DB copy, judged with the env's own hash-vs-gold reward.
Answers "how much SQL skill hides behind the protocol wall": what would each run score if every write the agent
*wrote down* had been executed, whatever wrapper it used (```sql, <sql>, <action>, <query>, <result>, extra blocks)?

Modes per run:
  executed  the agent-phase statements in sql_log, in order  -> sanity check, should reproduce the original reward
  intended  every UPDATE/INSERT/DELETE found anywhere in the agent's messages, in order, exact duplicates dropped

Caveat for `intended`: the agent never saw results for SQL the env ignored, so values it guessed stay guessed; a write it
wrote down but would have revised later is still applied. It is an estimate, not a re-run.

Usage (from DySQL-Bench/):
  ~/miniconda3/envs/dysql/bin/python scripts/replay_intended_writes.py --out results/replay/replay.json \
      --run 32b=results/full_qwen3_32b_think_on_c12 --run 4b=results/full_qwen3_4b_think_on_c16 ... [--procs 6]"""
import argparse, glob, json, os, re, shutil, sys, time
from multiprocessing import Pool

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import dysql_bench.envs.base as base
base.load_user = lambda **kw: None  # no user simulator needed offline
from dysql_bench.envs import get_env
from dysql_bench.types import Action, SQL_ACTION_NAME

WRITE_RE = re.compile(r"\b(?:UPDATE\s+[\w\"`\[\].]+\s+SET\b|INSERT\s+(?:OR\s+\w+\s+)?INTO\b|REPLACE\s+INTO\b|DELETE\s+FROM\b)"
                      r".*?(?=;|```|</|\n\s*\n|$)", re.I | re.S)
WRITE_TYPES = ("UPDATE", "INSERT", "DELETE", "REPLACE")

def intended_writes(traj):
    out, seen = [], set()
    for m in traj:
        if m["role"] != "assistant": continue
        for s in WRITE_RE.findall(m.get("content") or ""):
            s = s.strip(); k = re.sub(r"\s+", " ", s).lower()
            if k not in seen: seen.add(k); out.append(s)
    return out

def executed_writes(r):
    return [s["sql"] for s in r["sql_log"] if s["phase"] == "agent" and (s["type"] or "").upper() in WRITE_TYPES]

class Replayer:
    def __init__(self, env_name):
        self.env = get_env(env_name, user_strategy="llm", user_model="none", user_model_api=None,
                           task_split="test", thread_id="replay")
        self.env.conn.close(); shutil.rmtree(self.env.sql_folder_path, ignore_errors=True)
        self._initial = None

    def _hash_after(self, stmts):
        e = self.env
        e.conn, e.cursor, e.sql_folder_path = e.data_load_func("replay")
        e.actions, e.sql_log = [], []
        try:
            for s in stmts: e.step(Action(name=SQL_ACTION_NAME, kwargs={"sql": s}))
            return e.get_data_hash()
        finally:
            e.conn.close(); shutil.rmtree(e.sql_folder_path, ignore_errors=True)

    def hash_after(self, stmts):
        if not stmts:
            if self._initial is None: self._initial = self._hash_after([])
            return self._initial
        return self._hash_after(stmts)

    def gold_hash(self, idx):
        t = self.env.tasks[idx]
        return self._hash_after([a.kwargs["sql"] for a in t.actions if a.name == SQL_ACTION_NAME]), t.instruction

def job(args):
    env_name, idx, runs = args  # runs: {model: record-subset}
    t0 = time.time(); rp = Replayer(env_name)
    gold, instr = rp.gold_hash(idx)
    out = {"env": env_name, "task_id": idx, "models": {}}
    import contextlib, io
    for model, r in runs.items():
        if r["instruction"] and r["instruction"] != instr:
            out["models"][model] = {"error": "instruction mismatch"}; continue
        res = {"reward": r["reward"]}
        with contextlib.redirect_stdout(io.StringIO()):
            for mode, stmts in (("executed", r["executed"]), ("intended", r["intended"])):
                res[mode] = int(rp.hash_after(stmts) == gold); res["n_" + mode] = len(stmts)
        out["models"][model] = res
    out["wall_s"] = round(time.time() - t0, 1)
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="append", required=True, help="label=result_dir")
    ap.add_argument("--out", required=True); ap.add_argument("--procs", type=int, default=6)
    ap.add_argument("--envs", default="", help="comma list to restrict")
    a = ap.parse_args()
    tasks = {}
    for spec in a.run:
        label, d = spec.split("=", 1)
        for f in glob.glob(d + "/*.json"):
            if f.endswith("config.json"): continue
            for r in json.load(open(f)):
                if "n_steps" not in r["meta"]: continue  # traj_lost
                key = (r["meta"]["env"], r["task_id"])
                tasks.setdefault(key, {})[label] = {
                    "reward": r["reward"], "instruction": ((r["info"].get("task") or {}).get("instruction") or ""),
                    "executed": executed_writes(r), "intended": intended_writes(r["traj"])}
    keys = sorted(tasks, key=lambda k: (k[0] != "eu_soccer", k[0] != "retail", k))  # big DBs first
    if a.envs: keys = [k for k in keys if k[0] in a.envs.split(",")]
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    res = []
    with Pool(a.procs) as p:
        for i, o in enumerate(p.imap_unordered(job, [(e, i, tasks[(e, i)]) for e, i in keys])):
            res.append(o)
            if (i + 1) % 50 == 0: print(f"{i + 1}/{len(keys)}", flush=True)
    json.dump(res, open(a.out, "w"))
    print("done", len(res))

if __name__ == "__main__":
    main()
