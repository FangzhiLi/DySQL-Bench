# tests/test_agent_logging.py
import types
from dysql_bench.agents import sql_calling_agent as sca
from dysql_bench.types import EnvResetResponse, EnvResponse, EnvInfo, Task

class FakeEnv:
    def __init__(self):
        self.task = Task(user_id="1", instruction="i", actions=[])
        self.calls = 0
    def reset(self, task_index=None):
        return EnvResetResponse(observation="hi", info=EnvInfo(task=self.task, source="user"))
    def step(self, action):
        self.calls += 1
        return EnvResponse(observation="###STOP###", reward=1.0, done=True, info=EnvInfo(task=self.task))

def _fake_post(url, headers=None, json=None):
    assert json["model"] == "m"
    for m in json["messages"]:
        assert "reasoning_content" not in m
        assert "usage" not in m and "latency_s" not in m and "finish_reason" not in m
    body = {"choices": [{"message": {"content": "Sure.", "reasoning_content": "thinking..."},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 3}}
    return types.SimpleNamespace(json=lambda: body)

def test_agent_logs_turn_fields(monkeypatch):
    monkeypatch.setattr(sca.requests, "post", _fake_post)
    agent = sca.SQLCallingAgent(api="http://x", wiki="w", model="m")
    res = agent.solve(FakeEnv(), task_index=0, max_num_steps=5)
    a = [m for m in res.messages if m["role"] == "assistant"][0]
    assert a["reasoning_content"] == "thinking..."
    assert a["finish_reason"] == "stop"
    assert a["usage"] == {"prompt_tokens": 10, "completion_tokens": 3}
    assert a["latency_s"] >= 0
    assert res.info["termination"] == "user_stop"
    assert res.info["n_steps"] == 1

def test_agent_max_steps(monkeypatch):
    monkeypatch.setattr(sca.requests, "post", _fake_post)
    class NeverDone(FakeEnv):
        def step(self, action):
            return EnvResponse(observation="more?", reward=0.0, done=False, info=EnvInfo(task=self.task))
    res = sca.SQLCallingAgent(api="http://x", wiki="w", model="m").solve(NeverDone(), 0, max_num_steps=2)
    assert res.info["termination"] == "max_steps"
    assert res.info["n_steps"] == 2

def test_inline_think_tag_still_parsed(monkeypatch):
    """If the server does not split reasoning, <think> inline in content must still be stripped."""
    def _post(url, headers=None, json=None):
        body = {"choices": [{"message": {"content": "<think>hmm</think>\nSure."},
                             "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1}}
        return types.SimpleNamespace(json=lambda: body)
    monkeypatch.setattr(sca.requests, "post", _post)
    res = sca.SQLCallingAgent(api="http://x", wiki="w", model="m").solve(FakeEnv(), 0, max_num_steps=1)
    a = [m for m in res.messages if m["role"] == "assistant"][0]
    assert a["reasoning_content"] == "hmm" and a["content"] == "Sure."
