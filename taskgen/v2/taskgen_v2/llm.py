# taskgen/v2/taskgen_v2/llm.py
"""OpenAI-compatible chat client (requests, like the rest of the repo) with backoff and a thread-pool map."""
import os, random, time
from concurrent.futures import ThreadPoolExecutor
import requests
from taskgen_v2 import io

RETRY_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


class LLMError(RuntimeError):
    pass


class ChatClient:
    def __init__(self, base_url, api_key, model, session=None, timeout=600, max_retries=6, backoff=2.0):
        self.base_url, self.api_key, self.model = base_url.rstrip("/"), api_key, model
        self.session = session or requests.Session()
        self.timeout, self.max_retries, self.backoff = timeout, max_retries, backoff

    def chat(self, messages, temperature=1.0, max_tokens=8192, top_p=None, extra=None):
        payload = {"model": self.model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
        if top_p is not None:
            payload["top_p"] = top_p
        payload.update(extra or {})
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        last = None
        for attempt in range(self.max_retries + 1):
            try:
                r = self.session.post(f"{self.base_url}/chat/completions", headers=headers, json=payload, timeout=self.timeout)
            except requests.RequestException as e:
                last = f"request error: {e}"
            else:
                if r.status_code == 200:
                    try:
                        body = r.json()
                        choice = body["choices"][0]
                        msg = choice["message"]
                    except (ValueError, KeyError, IndexError, TypeError) as e:   # a cut-off or empty body: ask again
                        last = f"HTTP 200 without a message ({type(e).__name__}): {r.text[:300]}"
                    else:
                        return {"content": msg.get("content") or "", "reasoning": msg.get("reasoning_content") or msg.get("reasoning") or "",
                                "usage": body.get("usage") or {}, "model": body.get("model") or self.model,
                                "finish_reason": choice.get("finish_reason")}
                else:
                    last = f"HTTP {r.status_code}: {r.text[:300]}"
                    if r.status_code not in RETRY_STATUS:
                        raise LLMError(last)
            if attempt < self.max_retries:
                time.sleep(min(60.0, self.backoff * (2 ** attempt)) * (1 + random.random() * 0.25))
        raise LLMError(f"gave up after {self.max_retries + 1} attempts; last: {last}")


def client_from_env(role, model=None):
    """A client for TASKGEN_<ROLE>_BASE_URL / _API_KEY and the given model, or TASKGEN_<ROLE>_MODEL."""
    io.load_dotenv()
    p = f"TASKGEN_{role.upper()}_"
    missing = [k for k in ("BASE_URL", "API_KEY") + (() if model else ("MODEL",)) if not os.environ.get(p + k)]
    if missing:
        raise LLMError(f"missing env {', '.join(p + k for k in missing)} (see .env)")
    return ChatClient(os.environ[p + "BASE_URL"], os.environ[p + "API_KEY"], model or os.environ[p + "MODEL"])


def pmap(fn, items, workers):
    def safe(x):
        try:
            return fn(x)
        except Exception as e:  # keep the batch alive; the caller records the exception
            return e
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        return list(ex.map(safe, items))
