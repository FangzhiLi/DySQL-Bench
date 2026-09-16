# Copyright Sierra

import os
import json
import time
import random
import threading
import traceback
import subprocess
from math import comb
from tqdm import tqdm
from typing import List
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

from dysql_bench.envs import get_env
from dysql_bench.agents.base import Agent
from dysql_bench.types import EnvRunResult, RunConfig
from dysql_bench.envs.user import UserStrategy
from dysql_bench.analysis import (classify_task, count_fabricated_results,
                                  count_sql_errors, confirmed_before_write,
                                  count_extra_sql_blocks)

MAX_NUM_STEPS = 30


def load_done(path):
    """(task_id, trial) pairs already present in an existing results file."""
    if not path or not os.path.exists(path):
        return set()
    with open(path) as f:
        return {(r["task_id"], r["trial"]) for r in json.load(f)}


def _sum_completion(traj):
    return sum((m.get("usage") or {}).get("completion_tokens") or 0
               for m in traj if m.get("role") == "assistant")


def _last_prompt(traj):
    pts = [(m.get("usage") or {}).get("prompt_tokens") for m in traj if m.get("role") == "assistant"]
    pts = [p for p in pts if p is not None]
    return pts[-1] if pts else None


_WRITE_TYPES = {"INSERT", "UPDATE", "DELETE"}


def _zero_row_writes(sql_log, phase):
    return sum(1 for e in sql_log or [] if e.get("phase") == phase
               and e.get("type") in _WRITE_TYPES and e.get("rowcount") == 0)


def build_meta(env_name, task, info, traj, user_traj, wall_s, sql_log=None):
    """Analysis-only metadata attached to each EnvRunResult. Does not affect reward."""
    ri = (info.get("reward_info") or {}).get("info") or {}
    return {"env": env_name, **classify_task(task),
            "termination": info.get("termination"), "n_steps": info.get("n_steps"),
            "n_fabricated_results": count_fabricated_results(traj),
            "n_extra_sql_blocks": count_extra_sql_blocks(traj),
            "n_sql_errors": count_sql_errors(traj),
            "n_zero_row_writes": _zero_row_writes(sql_log, "agent"),      # agent write that matched no row
            "gold_zero_row_writes": _zero_row_writes(sql_log, "gold"),    # >0 means the gold itself is suspect
            "confirmed_before_write": confirmed_before_write(traj),
            "mismatched_tables": ri.get("mismatched_tables", []),
            "wall_s": round(wall_s, 2),
            "agent_completion_tokens": _sum_completion(traj),
            "user_completion_tokens": _sum_completion(user_traj),
            "last_prompt_tokens": _last_prompt(traj)}


def _git_commit():
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"],
                                       cwd=os.path.dirname(os.path.abspath(__file__)),
                                       stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return None


def _probe_server(api):
    """Best-effort: vLLM's /version and served model ids. Never raises."""
    import requests
    out = {}
    try:
        out["version"] = requests.get(f"{api}/version", timeout=5).json()
    except Exception as e:
        out["version"] = f"unavailable: {type(e).__name__}"
    try:
        out["models"] = [m["id"] for m in requests.get(f"{api}/v1/models", timeout=5).json()["data"]]
    except Exception as e:
        out["models"] = f"unavailable: {type(e).__name__}"
    return out


def write_run_config(ckpt_path, config, server_probe=_probe_server):
    """Sidecar <ckpt>.config.json so every results file carries how it was produced."""
    side = ckpt_path[:-5] + ".config.json" if ckpt_path.endswith(".json") else ckpt_path + ".config.json"
    payload = {"started_at": datetime.now().isoformat(timespec="seconds"),
               "git_commit": _git_commit(),
               "max_num_steps": MAX_NUM_STEPS,
               "run_config": config.model_dump(),
               "agent_server": server_probe(config.model_api),
               "user_server": server_probe(config.user_model_api)}
    with open(side, "w") as f:
        json.dump(payload, f, indent=2)
    return side

def run(config: RunConfig) -> List[EnvRunResult]:
    assert config.env in ["retail", "eu_soccer", "music", "bowling", "entertainment", "pagila", "chinook", "car", "cookbook", "human_resources", "ice_hockey", "law_episode", "retail_world"], f"Only retail, eu_soccer, music, bowling, entertainment, pagila, chinook, car, cookbook, human_resources, ice_hockey, law_episode, retail_world envs are supported"
    assert config.agent_strategy in ["sql"], "Invalid agent strategy"  # TODO: add other agent strategies in the future
    assert config.task_split in ["test"], "Invalid task split"   # TODO: add other task splits in the future
    assert config.user_strategy in [item.value for item in UserStrategy], "Invalid user strategy"

    random.seed(config.seed)
    time_str = datetime.now().strftime("%m%d%H%M%S")
    ckpt_path = f"{config.log_dir}/{config.env}-{config.agent_strategy}-agent-{config.model.split('/')[-1]}-{config.temperature}_range_{config.start_index}-{config.end_index}_user-{config.user_model.split('/')[-1]}-{config.user_strategy}_{time_str}.json"
    if not os.path.exists(config.log_dir):
        os.makedirs(config.log_dir)
    done = set()
    prior_results: List[EnvRunResult] = []
    if config.resume:
        ckpt_path = config.resume
        done = load_done(ckpt_path)
        if os.path.exists(ckpt_path):
            with open(ckpt_path) as f:
                prior_results = [EnvRunResult(**r) for r in json.load(f)]
        print(f"Resuming from {ckpt_path}: {len(done)} (task, trial) pairs already done")
    if not config.resume or not os.path.exists(ckpt_path[:-5] + ".config.json"):
        write_run_config(ckpt_path, config)

    print(f"Loading user with strategy: {config.user_strategy}")
    env = get_env(              
        config.env,             
        user_strategy=config.user_strategy,
        user_model=config.user_model,
        user_model_api=config.user_model_api,
        task_split=config.task_split,
        thread_id=None
    )
    agent = agent_factory(
        api=config.model_api,
        wiki=env.wiki,
        config=config,
    )
    end_index = (
        len(env.tasks) if config.end_index == -1 else min(config.end_index, len(env.tasks))
    )
    results: List[EnvRunResult] = list(prior_results)
    lock = threading.Lock()  
    if config.task_ids and len(config.task_ids) > 0:
        print(f"Running tasks {config.task_ids} (checkpoint path: {ckpt_path})")
    else:
        print(
            f"Running tasks {config.start_index} to {end_index} (checkpoint path: {ckpt_path})"
    )
    for i in range(config.num_trials):
        if config.task_ids and len(config.task_ids) > 0:
            idxs = config.task_ids
        else:
            idxs = list(range(config.start_index, end_index))
        if config.shuffle:
            random.shuffle(idxs)
        idxs = [idx for idx in idxs if (idx, i) not in done]
        if not idxs:
            print(f"Trial {i+1}/{config.num_trials}: nothing left to run")
            continue

        def _run(idx: int) -> EnvRunResult:
            run_start_time = time.time()
            print(f"idx:{idx}, _run start time: {run_start_time:.2f}")
            thread_id = threading.get_ident()  
            print(f"Thread ID: {thread_id} processing index {idx}")
            isolated_env = get_env(
                env_name=config.env,
                user_strategy=config.user_strategy,
                user_model=config.user_model,
                user_model_api=config.user_model_api,
                task_split=config.task_split,
                task_index=idx,
                thread_id=thread_id
            )

            print(f"Running task {idx}")
            try:
                res = agent.solve(
                    env=isolated_env,
                    task_index=idx,
                    max_num_steps=MAX_NUM_STEPS
                )
                user_traj = getattr(isolated_env.user, "messages", [])
                sql_log = getattr(isolated_env, "sql_log", [])
                result = EnvRunResult(
                    task_id=idx,
                    reward=res.reward,
                    info=res.info,
                    traj=res.messages,
                    trial=i,
                    user_traj=user_traj,
                    sql_log=sql_log,
                    meta=build_meta(config.env, isolated_env.task, res.info, res.messages,
                                    user_traj, time.time() - run_start_time, sql_log=sql_log),
                )
            except Exception as e:
                result = EnvRunResult(
                    task_id=idx,
                    reward=0.0,
                    info={"error": str(e), "traceback": traceback.format_exc()},
                    traj=[],
                    trial=i,
                    user_traj=getattr(isolated_env.user, "messages", []),
                    sql_log=getattr(isolated_env, "sql_log", []),
                    meta={"env": config.env, "termination": "error",
                          "wall_s": round(time.time() - run_start_time, 2)},
                )
            print(
                "✅" if result.reward == 1 else "❌",
                f"task_id={idx}",
                result.info,
            )
            print("-----")
            run_end_time = time.time()
            print(f"idx:{idx}, _run agent.solve finish needs time: {(run_end_time - run_start_time): .2f}")
            with lock:
                lock_start_time = time.time()
                print(f"idx:{idx}, lock wait time: {(lock_start_time - run_end_time): .2f}")
                data = []
                if os.path.exists(ckpt_path):
                    with open(ckpt_path, "r") as f:
                        data = json.load(f)
                with open(ckpt_path, "w") as f:
                    json.dump(data + [result.model_dump()], f, indent=2)
                print(f"idx:{idx}, lock write time: {(time.time() - lock_start_time): .2f}")
            return result

        with ThreadPoolExecutor(max_workers=config.max_concurrency) as executor:
            res = list(tqdm(executor.map(_run, idxs), total=len(idxs), desc=f"Trial {i+1}/{config.num_trials}"))
            results.extend(res)

    if results:
        display_metrics(results)

    with open(ckpt_path, "w") as f:
        json.dump([result.model_dump() for result in results], f, indent=2)
        print(f"\n📄 Results saved to {ckpt_path}\n")
    return results


def agent_factory(
    api: str, 
    wiki, 
    config: RunConfig
) -> Agent:
    if config.agent_strategy == "sql":
        from dysql_bench.agents.sql_calling_agent import SQLCallingAgent

        temperature = getattr(config, "temperature", 0.6) 
        max_tokens = getattr(config, "max_tokens", 8192)
        top_p = getattr(config, "top_p", 0.95)
        top_k = getattr(config, "top_k", 20)
        min_p = getattr(config, "min_p", 0.0)

        return SQLCallingAgent(
            api=api,
            wiki=wiki,
            model=config.model,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=top_p,
            top_k=top_k,
            min_p=min_p,
        )

    else:
        raise ValueError(f"Unknown agent strategy: {config.agent_strategy}")


def display_metrics(results: List[EnvRunResult]) -> None:
    def is_successful(reward: float) -> bool:
        return (1 - 1e-6) <= reward <= (1 + 1e-6)

    num_trials = len(set([r.trial for r in results]))
    rewards = [r.reward for r in results]
    avg_reward = sum(rewards) / len(rewards)
    # c from https://arxiv.org/pdf/2406.12045
    c_per_task_id: dict[int, int] = {}
    for result in results:
        if result.task_id not in c_per_task_id:
            c_per_task_id[result.task_id] = 1 if is_successful(result.reward) else 0
        else:
            c_per_task_id[result.task_id] += 1 if is_successful(result.reward) else 0
    pass_hat_ks: dict[int, float] = {}
    for k in range(1, num_trials + 1):
        sum_task_pass_hat_k = 0
        for c in c_per_task_id.values():
            sum_task_pass_hat_k += comb(c, k) / comb(num_trials, k)
        pass_hat_ks[k] = sum_task_pass_hat_k / len(c_per_task_id)
    print(f"🏆 Average reward: {avg_reward}")
    print("📈 Pass^k")
    for k, pass_hat_k in pass_hat_ks.items():
        print(f"  k={k}: {pass_hat_k}")
