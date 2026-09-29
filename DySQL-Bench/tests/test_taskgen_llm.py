# tests/test_taskgen_llm.py
import pytest
from dysql_bench.taskgen import llm


class FakeResp:
    def __init__(self, status, body): self.status_code, self._body, self.text = status, body, str(body)
    def json(self): return self._body


class FakeSession:
    def __init__(self, responses): self.responses, self.calls = list(responses), []
    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "json": json})
        return self.responses.pop(0)


OK = FakeResp(200, {"model": "glm-5.3", "usage": {"prompt_tokens": 5, "completion_tokens": 7},
                    "choices": [{"message": {"content": "hi", "reasoning_content": "think"}, "finish_reason": "stop"}]})


def client(responses, **kw):
    return llm.ChatClient("https://x/v4", "k", "glm-5.3", session=FakeSession(responses), backoff=0.0, **kw)


def test_chat_parses_content_reasoning_usage_and_sends_auth():
    c = client([OK])
    r = c.chat([{"role": "user", "content": "q"}], temperature=0.5, max_tokens=99)
    assert r == {"content": "hi", "reasoning": "think", "usage": {"prompt_tokens": 5, "completion_tokens": 7}, "model": "glm-5.3"}
    call = c.session.calls[0]
    assert call["url"] == "https://x/v4/chat/completions" and call["headers"]["Authorization"] == "Bearer k"
    assert call["json"]["temperature"] == 0.5 and call["json"]["max_tokens"] == 99 and call["json"]["model"] == "glm-5.3"


def test_retries_on_429_then_succeeds():
    c = client([FakeResp(429, {"error": "slow down"}), FakeResp(503, {"error": "busy"}), OK])
    assert c.chat([{"role": "user", "content": "q"}])["content"] == "hi" and len(c.session.calls) == 3


def test_gives_up_after_max_retries():
    c = client([FakeResp(429, {})] * 3, max_retries=2)
    with pytest.raises(llm.LLMError, match="429"):
        c.chat([{"role": "user", "content": "q"}])


def test_client_error_is_not_retried():
    c = client([FakeResp(400, {"error": {"message": "bad request"}}), OK])
    with pytest.raises(llm.LLMError, match="400"):
        c.chat([{"role": "user", "content": "q"}])
    assert len(c.session.calls) == 1


def test_pmap_keeps_order_and_captures_exceptions():
    def f(x):
        if x == 2: raise ValueError("two")
        return x * 10
    out = llm.pmap(f, [1, 2, 3], workers=3)
    assert out[0] == 10 and out[2] == 30 and isinstance(out[1], ValueError)


def test_client_from_env(monkeypatch):
    monkeypatch.setenv("TASKGEN_GEN_BASE_URL", "https://x/v4/"); monkeypatch.setenv("TASKGEN_GEN_API_KEY", "k")
    monkeypatch.setenv("TASKGEN_GEN_MODEL", "m")
    c = llm.client_from_env("GEN")
    assert c.base_url == "https://x/v4" and c.model == "m"
