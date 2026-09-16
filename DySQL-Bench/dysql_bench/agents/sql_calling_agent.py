# Calling SQL code to complete user instruction.

import re
import copy
import json
import time
import requests
from typing import List, Optional, Dict, Any

from dysql_bench.agents.base import Agent
from dysql_bench.envs.base import Env
from dysql_bench.types import SolveResult, Action, RESPOND_ACTION_NAME, SQL_ACTION_NAME


class SQLCallingAgent(Agent):
    def __init__(
        self,
        api: str,
        wiki: str,
        model: str,
        temperature: float = 0.6,
        max_tokens: int = 8192,
        top_p: float = 0.95,
        top_k: int = 20,
        min_p: float = 0.0,
    ):
        self.wiki = wiki
        self.model = model
        self.temperature = temperature
        self.api = api
        self.max_tokens = max_tokens
        self.top_p = top_p
        self.top_k = top_k
        self.min_p = min_p

    def _api_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Strip logging-only fields before sending history back to the model."""
        keep = ("role", "content", "name")
        return [{k: m[k] for k in keep if k in m} for m in messages]

    def solve(
        self, env: Env, task_index: Optional[int] = None, max_num_steps: int = 30
    ) -> SolveResult:
        env_reset_res = env.reset(task_index=task_index)
        obs = env_reset_res.observation
        info = env_reset_res.info.model_dump()
        reward = 0.0
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": self.wiki},
            {"role": "user", "content": obs},
        ]
        termination, n_steps = "max_steps", 0
        for _ in range(max_num_steps):
            t0 = time.time()
            response = requests.post(
                self.api + "/v1/chat/completions",
                headers={"Content-Type": "application/json"},
                json={
                    "model": self.model,
                    "messages": self._api_messages(messages),
                    "max_tokens": self.max_tokens,
                    "temperature": self.temperature,
                    "top_p": self.top_p,
                    "top_k": self.top_k,
                    "min_p": self.min_p,
                },
            ).json()
            latency = time.time() - t0

            choice = response["choices"][0]
            next_message = self.parse_response(choice["message"]["content"])
            # vLLM --reasoning-parser puts thinking in a separate field ("reasoning_content" in older
            # builds, "reasoning" in v0.19+); keep it if inline <think> parse found none
            server_reasoning = choice["message"].get("reasoning_content") or choice["message"].get("reasoning")
            if server_reasoning and not next_message["reasoning_content"]:
                next_message["reasoning_content"] = server_reasoning
            next_message["finish_reason"] = choice.get("finish_reason")
            u = response.get("usage") or {}
            next_message["usage"] = {
                "prompt_tokens": u.get("prompt_tokens"),
                "completion_tokens": u.get("completion_tokens"),
            }
            next_message["latency_s"] = round(latency, 3)
            n_steps += 1

            action = message_to_action(next_message)
            env_response = env.step(action)
            reward = env_response.reward
            info = {**info, **env_response.info.model_dump()}
            if action.name != RESPOND_ACTION_NAME:
                messages.extend(
                    [
                        next_message,
                        {
                            "role": "user",
                            "name": "sql",
                            "content": env_response.observation,
                        },
                    ]
                )
            else:
                messages.extend(
                    [
                        next_message,
                        {"role": "user", "content": env_response.observation},
                    ]
                )
            if env_response.done:
                termination = "user_stop"
                break
        info["termination"] = termination
        info["n_steps"] = n_steps
        return SolveResult(
            reward=reward,
            info=info,
            messages=messages,
        )
    
    def parse_response(self, text):

        think_pattern = r'<think>(.*?)</think>'
        think_match = re.search(think_pattern, text, re.DOTALL)
        reasoning_content = think_match.group(1).strip() if think_match else None

        clean_text = text
        clean_text = re.sub(think_pattern, '', clean_text, flags=re.DOTALL)
        content = clean_text.strip()
    
        return {
            'role': 'assistant',
            'reasoning_content': reasoning_content,
            'content': content
        }

def message_to_action(
    message: Dict[str, Any],
) -> Action:

    if "```sql" in message["content"]:
        sql_pattern = r"```sql(.*?)```"
        matches = re.findall(sql_pattern, message["content"], re.DOTALL)[0]
        return Action(name=SQL_ACTION_NAME, kwargs={"content": message["content"], "sql": matches})
    elif "<sql>" in message["content"]:
        sql_pattern = r"<sql>(.*?)</sql>"
        matches = re.findall(sql_pattern, message["content"], re.DOTALL)[0]     # 如果有多个sql调用, 只保留第一个
        return Action(name=SQL_ACTION_NAME, kwargs={"content": message["content"], "sql": matches})
    else:
        return Action(name=RESPOND_ACTION_NAME, kwargs={"content": message["content"]})