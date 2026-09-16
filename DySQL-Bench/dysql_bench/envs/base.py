# Copyright Sierra

import os
import time
import shutil
import random
import sqlparse
from hashlib import sha256
from typing import Any, Callable, Dict, List, Type, Optional, Set, Union, Tuple

from dysql_bench.envs.user import load_user, UserStrategy
from dysql_bench.analysis import diff_table_hashes, table_row_diff
from dysql_bench.types import (
    Action,
    Task,
    EnvInfo,
    EnvResetResponse,
    EnvResponse,
    RewardResult,
    RewardOutputInfo,
    RewardActionInfo,
    RESPOND_ACTION_NAME,
    SQL_ACTION_NAME
)

import re

VOLATILE_COL_RE = re.compile(
    r"(?i)^(last_?update|updated_?at|update_?time|modified(_at)?|modification_?time|create(d)?_?at|timestamp)$"
)
IGNORE_TABLES = {"sqlite_sequence", "sqlite_stat1"}
ROW_DIFF_LIMIT = 20  # max rows kept per side per mismatched table in reward info


ToHashable = Union[
    str, int, float, Dict[str, "ToHashable"], List["ToHashable"], Set["ToHashable"], tuple["ToHashable"]
]
Hashable = Union[str, int, float, Tuple["Hashable"], Tuple[Tuple[str, "Hashable"]]]


def to_hashable(item: ToHashable) -> Hashable:
    if isinstance(item, dict):
        return tuple((key, to_hashable(value)) for key, value in sorted(item.items()))
    elif isinstance(item, list):
        return tuple(to_hashable(element) for element in item)
    elif isinstance(item, set):
        return tuple(sorted(to_hashable(element) for element in item))
    else:
        return item


def consistent_hash(
    value: Hashable,
) -> str:
    return sha256(str(value).encode("utf-8")).hexdigest()


class Env(object):
    def __init__(
        self,
        data_load_func: Callable[[], Dict[str, Any]],
        table_names: List[str],
        tasks: List[Task],
        wiki: str,
        user_strategy: Union[str, UserStrategy],
        user_model: str,
        user_model_api: str,
        task_index: Optional[int] = None,
        thread_id: Optional[int] = None
    ) -> None:
        super().__init__()
        self.data_load_func = data_load_func
        self.conn, self.cursor, self.sql_folder_path = data_load_func(thread_id)
        self.thread_id = thread_id
        self.user_model_api = user_model_api

        self.tasks = tasks
        if task_index is not None:
            self.task_index = task_index
        else:
            self.task_index = random.randint(0, len(tasks) - 1)
        self.task = tasks[self.task_index]
        # self.tasks = self.tasks[:5]         # DEBUG: 只跑前5个任务
        self.table_names = table_names

        self.wiki = wiki
        self.user = load_user(
            api=self.user_model_api, user_strategy=user_strategy, model=user_model
        )
        self.actions: List[Action] = []
        self.sql_log: List[Dict[str, Any]] = []   # analysis only: every executed statement
        self._phase = "agent"

    def reset(self, task_index: Optional[int] = None) -> EnvResetResponse:
        if task_index is None:
            task_index = random.randint(0, len(self.tasks))
        self.task_index = task_index

        self.conn, self.cursor, self.sql_folder_path = self.data_load_func(self.thread_id)
        self.task = self.tasks[task_index]
        self.actions = []
        self.sql_log = []
        self._phase = "agent"
        initial_observation = self.user.reset(instruction=self.task.instruction)
        return EnvResetResponse(
            observation=initial_observation, info=EnvInfo(task=self.task, source="user")
        )

    def step(self, action: Action) -> EnvResponse:
        self.actions.append(action)

        info = EnvInfo(task=self.task)
        reward = 0
        done = False
        
        if action.name == RESPOND_ACTION_NAME: 
            observation = self.user.step(action.kwargs["content"])
            info.source = "user"
            done = "###STOP###" in observation
        elif action.name == SQL_ACTION_NAME:
            sql_start_time = time.time()
            observation = ""
            try:
                sql_code = action.kwargs["sql"]
                sql_list = sqlparse.split(sql_code) 
                for sql in sql_list:
                    sql = sql.strip()
                    # analysis-only log entry; observation strings and commit/rollback are unchanged
                    entry = {"phase": self._phase, "step": len(self.actions), "sql": sql,
                             "type": None, "rowcount": None, "error": None, "duration_s": None}
                    t0 = time.time()
                    try:
                        sql_type = sqlparse.parse(sql)[0].get_type().upper()
                        entry["type"] = sql_type
                        self.cursor.execute(sql)
                        if sql_type == "SELECT":
                            rows = self.cursor.fetchall()
                            entry["rowcount"] = len(rows)
                            observation += f"<result>{rows}</result>\n"
                        else:
                            entry["rowcount"] = self.cursor.rowcount
                            observation += f"<result>SQL execution Successfully!</result>\n"
                            self.conn.commit()
                    except Exception as e:
                        entry["error"] = str(e)
                        raise
                    finally:
                        entry["duration_s"] = round(time.time() - t0, 4)
                        self.sql_log.append(entry)
                sql_end_time = time.time()
                print(f"SQL execution successful time: {sql_end_time - sql_start_time:.2f}s")

            except Exception as e:
                observation += f"<result>Error: {e}\n</result>"
                print(observation)
                self.conn.rollback()
                sql_end_time = time.time()
                print(f"SQL rollback time: {sql_end_time - sql_start_time:.2f}s")
            info.source = action.name
        else:
            observation = f"Unknown action {action.name}"
            info.source = action.name

        if done:
            calculate_reward_start_time = time.time()
            reward_res = self.calculate_reward()
            reward = reward_res.reward
            info.reward_info = reward_res
            self.delete_db()
            calculate_reward_end_time = time.time()
            print(f"Calculate reward time: {calculate_reward_end_time - calculate_reward_start_time:.2f}s")
            
        return EnvResponse(observation=observation, reward=reward, done=done, info=info)

    def _collect_table_data(self) -> list:
        """
        Read all data from all tables.
        It is necessary to read all the data; otherwise, the target table might be correctly modified by the model in the end,
        but other tables could have been incorrectly modified during the search process.
        """
        all_data = []
        self.cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        all_tables = {row[0] for row in self.cursor.fetchall()} - IGNORE_TABLES

        for table in self.table_names:
            if table not in all_tables:
                continue

            self.cursor.execute(f'PRAGMA table_info("{table}")')
            cols = [c[1] for c in self.cursor.fetchall()]

            if not cols:
                all_data.append((table, ()))
                continue

            # Ignore volatile columns
            stable_cols = [c for c in cols if not VOLATILE_COL_RE.match(c)]

            if stable_cols:
                sel = ", ".join(f'"{c}"' for c in stable_cols)
                # Add rowid to ensure stable order
                self.cursor.execute(f'SELECT {sel} FROM "{table}" ORDER BY {sel}, rowid')
                all_data.append((table, tuple(self.cursor.fetchall())))
            else:
                self.cursor.execute(f'SELECT COUNT(*) FROM "{table}"')
                n = self.cursor.fetchone()[0]
                all_data.append((table, ("__ONLY_ROWCOUNT__", n)))

        return all_data

    def get_table_hashes(self) -> Dict[str, str]:
        """Per-table hashes, for analysis only (which tables differ from gold)."""
        return {t: consistent_hash(to_hashable(rows)) for t, rows in self._collect_table_data()}

    def get_data_hash(self) -> str:
        """Overall hash over all table data. Evaluation semantics unchanged."""
        return consistent_hash(to_hashable(self._collect_table_data()))

    def calculate_reward(self) -> RewardResult:
        # one full read of the agent-side DB: overall hash (the judgement) + per-table data (analysis)
        agent_data = self._collect_table_data()
        data_hash = consistent_hash(to_hashable(agent_data))
        agent_tables = {t: consistent_hash(to_hashable(rows)) for t, rows in agent_data}
        self.conn.close()

        reward = 1.0
        actions = [
            action for action in self.task.actions if action.name != RESPOND_ACTION_NAME
        ]

        self.conn, self.cursor, reward_sql_folder_path = self.data_load_func(self.thread_id)
        
        assert self.sql_folder_path == reward_sql_folder_path, "Different sqlite database when calculating reward!"

        # If the task contains ground truth sql statements, use them, otherwise you need to rewrite them
        self._phase = "gold"
        try:
            for action in self.task.actions:
                self.step(action)
        finally:
            self._phase = "agent"

        gold_data = self._collect_table_data()
        gt_data_hash = consistent_hash(to_hashable(gold_data))
        gt_tables = {t: consistent_hash(to_hashable(rows)) for t, rows in gold_data}

        # Calculate reward complete
        self.conn.close()

        mismatched = diff_table_hashes(agent_tables, gt_tables)
        info = RewardActionInfo(
            r_actions=data_hash == gt_data_hash,
            gt_data_hash=gt_data_hash,
            mismatched_tables=mismatched,
            row_diff=table_row_diff(dict(agent_data), dict(gold_data), mismatched, limit=ROW_DIFF_LIMIT),
        )
        if not info.r_actions:
            reward = 0.0
        else:
            print("hash_check:", data_hash, " and ", gt_data_hash)
            
        return RewardResult(reward=reward, info=info, actions=actions)

    def delete_db(self):
        shutil.rmtree(self.sql_folder_path)