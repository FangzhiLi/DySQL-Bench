# tests/test_taskgen_verify.py
import pytest
from taskgen_v2 import verify, io

CAND = {"id": "c1", "instruction": "I am a5 b5. Set qty of order 5 to 3.", "actions": [{"sql": "UPDATE orders SET qty = 3 WHERE order_id = 5"}]}
YES = "step 1 ok ... Verification: Is the answer correct (Yes/No)? Yes"
NO = "the id is missing ... Verification: Is the answer correct (Yes/No)? No"


class FakeClient:
    def __init__(self, contents, model="fake-verifier"): self.contents, self.calls, self.model = list(contents), 0, model
    def chat(self, messages, **kw):
        self.calls += 1
        self.last = messages
        return {"content": self.contents.pop(0), "reasoning": "r" * 10, "usage": {"completion_tokens": 50}, "model": self.model,
                "finish_reason": "stop"}


def run(cands, client, out, votes=3, **kw):
    return verify.run(cands, [(client, votes)], out, workers=1, **kw)


def test_parse_verdict():
    assert verify.parse_verdict(YES) == "yes" and verify.parse_verdict(NO) == "no"
    assert verify.parse_verdict("Yes it is fine (no final line)") == "unparsed"
    assert verify.parse_verdict("Verification: Is the answer correct (Yes/No)?\n**No**") == "no"


def test_messages_contain_policy_requirements_actions_and_ddl():
    m = verify.build_messages(CAND, "CREATE TABLE orders (...)")
    assert m[0]["role"] == "system" and "not a conversation transcript" in m[0]["content"]
    assert "explicit user confirmation" not in m[0]["content"]      # conversational policy steps cannot appear in a SQL list
    assert "[Completeness of parameters]" in m[0]["content"] and "[Solvability]" in m[0]["content"]
    assert CAND["instruction"] in m[1]["content"] and "UPDATE orders SET qty = 3" in m[1]["content"] and "CREATE TABLE orders" in m[1]["content"]
    assert "Notes on this database" not in m[1]["content"]


def test_run_votes_majority_and_resumes(tmp_path):
    out = str(tmp_path / "verify.jsonl")
    c = FakeClient([YES, NO, YES])                       # two split, so a third settles it
    s = run([CAND], c, out)
    r = io.read_jsonl(out)[0]
    assert s == {"verified": 1, "passed": 1, "skipped": 0, "unvoted": 0, "paused": False}
    assert r["models"]["fake-verifier"] == {"yes": 2, "no": 1, "pass": True} and r["pass"] and len(r["votes"]) == 3
    assert r["votes"][0]["reasoning_chars"] == 10 and r["votes"][0]["model"] == "fake-verifier"
    s2 = run([CAND], FakeClient([YES]), out)
    assert s2["skipped"] == 1 and len(io.read_jsonl(out)) == 1


def test_run_tops_up_votes(tmp_path):
    out = str(tmp_path / "verify.jsonl")
    run([CAND], FakeClient([YES, YES]), out)             # settled by two
    c = FakeClient([NO, NO, NO])
    run([CAND], c, out, votes=5)                         # five need three of a kind: 2 Yes, then No until it settles
    r = io.read_jsonl(out)
    assert len(r) == 1 and len(r[0]["votes"]) == 5 and r[0]["models"]["fake-verifier"] == {"yes": 2, "no": 3, "pass": False}
    assert not r[0]["pass"] and c.calls == 3


def test_unparsed_counts_as_no(tmp_path):
    out = str(tmp_path / "v.jsonl")
    run([CAND], FakeClient([YES, "garbage", "garbage"]), out)
    r = io.read_jsonl(out)[0]
    assert r["models"]["fake-verifier"] == {"yes": 1, "no": 2, "pass": False} and not r["pass"]


class Crash(BaseException):
    """Stands in for a kill: not an Exception, so pmap-style wrappers do not swallow it."""


def test_finished_candidates_are_written_before_a_crash(tmp_path):
    out = str(tmp_path / "v.jsonl")
    c2 = {**CAND, "id": "c2"}

    class Dies(FakeClient):
        def chat(self, messages, **kw):
            if self.calls == 3:
                raise Crash()
            return super().chat(messages, **kw)

    try:
        run([CAND, c2], Dies([YES, YES, NO]), out)
    except Crash:
        pass
    rows = io.read_jsonl(out)
    assert [r["id"] for r in rows] == ["c1"] and rows[0]["models"]["fake-verifier"]["yes"] == 2   # c1's votes survived
    c = FakeClient([NO, NO])
    s = run([CAND, c2], c, out)
    assert s["skipped"] == 1 and c.calls == 2 and [r["id"] for r in io.read_jsonl(out)] == ["c1", "c2"]


def test_short_verdict_line_is_accepted():
    assert verify.parse_verdict("... all fine.\n\nVerification: Yes") == "yes"
    assert verify.parse_verdict("Verification: **No**") == "no"


def test_failed_votes_are_not_counted_and_are_retried(tmp_path):
    class Flaky(FakeClient):
        def chat(self, messages, **kw):
            if self.calls == 1:
                self.calls += 1
                raise RuntimeError("HTTP 503")
            return super().chat(messages, **kw)
    out = str(tmp_path / "v.jsonl")
    run([CAND], Flaky([YES, YES]), out)                  # one Yes, one failed call: not asked again in this run
    r = io.read_jsonl(out)[0]
    assert r["models"]["fake-verifier"] == {"yes": 1, "no": 0, "pass": None} and r["unvoted"] and not r["pass"]
    assert sum("error" in v for v in r["votes"]) == 1
    c = FakeClient([YES])
    s = run([CAND], c, out)
    r = io.read_jsonl(out)[0]
    assert c.calls == 1 and r["models"]["fake-verifier"] == {"yes": 2, "no": 0, "pass": True} and r["pass"] and s["unvoted"] == 0


def test_a_verdict_line_without_the_choice_in_brackets_is_read():
    # deepseek-v4.1-flash once wrote the question without "(Yes/No)", which the old parser counted as No
    assert verify.parse_verdict("... fine.\n\nVerification: Is the answer correct?  \nYes") == "yes"
    assert verify.parse_verdict("Verification: Is the answer correct (Yes/No)? No. The id is wrong, not yes.") == "no"


def test_a_vote_cut_off_while_thinking_is_not_a_no_and_is_asked_again(tmp_path):
    class Thinker(FakeClient):
        def chat(self, messages, **kw):
            r = super().chat(messages, **kw)
            if self.calls == 1:   # all 16384 tokens spent thinking, no answer
                return {**r, "content": "", "usage": {"completion_tokens": 16384}, "finish_reason": "length"}
            return r
    out = str(tmp_path / "v.jsonl")
    run([CAND], Thinker([YES, YES, YES]), out, votes=2)
    r = io.read_jsonl(out)[0]
    assert r["votes"][0]["verdict"] == "error" and r["votes"][0]["error"].startswith("Truncated: no verdict within 16384")
    assert r["models"]["fake-verifier"] == {"yes": 1, "no": 0, "pass": None} and r["unvoted"]
    c = FakeClient([YES])
    run([CAND], c, out, votes=2)
    assert c.calls == 1 and io.read_jsonl(out)[0]["models"]["fake-verifier"] == {"yes": 2, "no": 0, "pass": True}


def test_every_model_must_pass(tmp_path):
    out = str(tmp_path / "v.jsonl")
    a, b = FakeClient([YES, YES], model="a"), FakeClient([NO], model="b")
    s = verify.run([CAND], [(a, 2), (b, 1)], out, workers=1)
    r = io.read_jsonl(out)[0]
    assert r["models"] == {"a": {"yes": 2, "no": 0, "pass": True}, "b": {"yes": 0, "no": 1, "pass": False}}
    assert not r["pass"] and r["verify_model"] == "a,b" and s["passed"] == 0


def test_context_gives_each_candidate_its_schema_and_data_notes(tmp_path):
    c = FakeClient([YES])
    verify.run([CAND], [(c, 1)], str(tmp_path / "v.jsonl"), workers=1,
               context=lambda cand: ("CREATE TABLE congress (first_name TEXT)", ["first_name holds the surname"]))
    u = c.last[1]["content"]
    assert "CREATE TABLE congress" in u and "Notes on this database's data" in u and "- first_name holds the surname" in u


def test_model_specs():
    assert verify.parse_models("deepseek-v4.1-flash:2") == [("deepseek-v4.1-flash", 2)]
    assert verify.parse_models("a:3, qwen3:8b:1 ,b") == [("a", 3), ("qwen3:8b", 1), ("b", verify.DEFAULT_VOTES)]


def test_models_from_env(monkeypatch):
    monkeypatch.setattr(verify.io, "load_dotenv", lambda *a, **k: None)
    for k, v in {"TASKGEN_VERIFY_BASE_URL": "https://v/1", "TASKGEN_VERIFY_API_KEY": "k", "TASKGEN_VERIFY_MODEL": "m0"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("TASKGEN_VERIFY_MODELS", raising=False)
    assert [(c.model, n) for c, n in verify.models_from_env()] == [("m0", verify.DEFAULT_VOTES)]
    monkeypatch.setenv("TASKGEN_VERIFY_MODELS", "m1:2,m2:1")
    ms = verify.models_from_env()
    assert [(c.model, n) for c, n in ms] == [("m1", 2), ("m2", 1)] and ms[0][0].base_url == "https://v/1"
    assert [(c.model, n) for c, n in verify.models_from_env("m3:3")] == [("m3", 3)]


def test_a_task_without_any_vote_is_unvoted_not_rejected(tmp_path):
    # with one vote per task, a vote cut off while thinking would otherwise read as a No: the task is dropped silently
    class AlwaysThinking(FakeClient):
        def chat(self, messages, **kw):
            return {**super().chat(messages, **kw), "content": "", "finish_reason": "length", "usage": {"completion_tokens": 16384}}
    out = str(tmp_path / "v.jsonl")
    s = run([CAND], AlwaysThinking(["x"]), out, votes=1)
    r = io.read_jsonl(out)[0]
    assert r["models"]["fake-verifier"] == {"yes": 0, "no": 0, "pass": None} and r["unvoted"] and not r["pass"]
    assert s == {"verified": 1, "passed": 0, "skipped": 0, "unvoted": 1, "paused": False}
    c = FakeClient([YES])
    s = run([CAND], c, out, votes=1)
    r = io.read_jsonl(out)[0]
    assert c.calls == 1 and r["pass"] and not r["unvoted"] and s["unvoted"] == 0


def test_three_votes_stop_once_two_agree(tmp_path):
    # the full run votes three times by majority; when the first two agree the third cannot change anything
    out = str(tmp_path / "v.jsonl")
    c2, c3 = {**CAND, "id": "c2"}, {**CAND, "id": "c3"}
    c = FakeClient([YES, YES, NO, NO, YES, NO, YES])
    s = verify.run([CAND, c2, c3], [(c, 3)], out, workers=1)
    rows = {r["id"]: r for r in io.read_jsonl(out)}
    assert c.calls == 7 and [len(rows[i]["votes"]) for i in ("c1", "c2", "c3")] == [2, 2, 3]
    assert [rows[i]["pass"] for i in ("c1", "c2", "c3")] == [True, False, True] and s["passed"] == 2


def test_settled_and_needed():
    v = lambda *xs: [{"verdict": x} for x in xs]
    assert verify.settled(v("yes", "yes"), 3) == "pass" and verify.settled(v("no", "unparsed"), 3) == "fail"
    assert verify.settled(v("yes", "no"), 3) is None and verify.settled(v("yes"), 1) == "pass"
    assert [verify.needed(v(*xs), 3) for xs in [(), ("yes",), ("yes", "no"), ("yes", "yes")]] == [2, 1, 1, 0]
    assert verify.needed(v(), 1) == 1 and verify.needed(v("no"), 2) == 0 and verify.needed(v("yes"), 2) == 1


def test_a_long_run_of_failed_calls_pauses_the_run(tmp_path):
    # an exhausted quota answers every call with an error: stop instead of failing every task, resume later
    class Broke(FakeClient):
        def chat(self, messages, **kw):
            self.calls += 1
            raise RuntimeError("HTTP 429: weekly usage limit reached")
    out = str(tmp_path / "v.jsonl")
    cands = [{**CAND, "id": f"c{i}"} for i in range(40)]
    c = Broke([])
    s = verify.run(cands, [(c, 3)], out, workers=1, max_failures=5)
    assert s["paused"] and s["passed"] == 0 and c.calls == 5             # stopped after five failures in a row
    s = verify.run(cands, [(FakeClient([YES] * 80), 3)], out, workers=1)
    assert not s["paused"] and s["passed"] == 40 and s["unvoted"] == 0


def test_a_vote_cut_off_while_thinking_does_not_count_toward_a_pause(tmp_path):
    class Thinker(FakeClient):
        def chat(self, messages, **kw):
            return {**super().chat(messages, **kw), "content": "", "finish_reason": "length"}
    s = verify.run([{**CAND, "id": f"c{i}"} for i in range(10)], [(Thinker(["x"] * 20), 1)], str(tmp_path / "v.jsonl"),
                   workers=1, max_failures=3)
    assert not s["paused"] and s["unvoted"] == 10


def test_models_from_env_needs_a_model(monkeypatch):
    monkeypatch.setattr(verify.io, "load_dotenv", lambda *a, **k: None)
    for k in ("TASKGEN_VERIFY_MODELS", "TASKGEN_VERIFY_MODEL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("TASKGEN_VERIFY_BASE_URL", "https://v/1"); monkeypatch.setenv("TASKGEN_VERIFY_API_KEY", "k")
    with pytest.raises(verify.llm.LLMError, match="TASKGEN_VERIFY_MODEL"):
        verify.models_from_env()
