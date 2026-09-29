# tests/test_taskgen_verify.py
from dysql_bench.taskgen import verify, io

CAND = {"id": "c1", "instruction": "I am a5 b5. Set qty of order 5 to 3.", "actions": [{"sql": "UPDATE orders SET qty = 3 WHERE order_id = 5"}]}
YES = "step 1 ok ... Verification: Is the answer correct (Yes/No)? Yes"
NO = "the id is missing ... Verification: Is the answer correct (Yes/No)? No"


class FakeClient:
    model = "fake-verifier"
    def __init__(self, contents): self.contents, self.calls = list(contents), 0
    def chat(self, messages, **kw):
        self.calls += 1
        return {"content": self.contents.pop(0), "reasoning": "r" * 10, "usage": {}, "model": "fake-verifier"}


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


def test_run_votes_majority_and_resumes(tmp_path):
    out = str(tmp_path / "verify.jsonl")
    c = FakeClient([YES, NO, YES])
    s = verify.run([CAND], c, out, votes=3, workers=1)
    r = io.read_jsonl(out)[0]
    assert s == {"verified": 1, "passed": 1, "skipped": 0} and r["yes"] == 2 and r["no"] == 1 and r["pass"] and len(r["votes"]) == 3
    assert r["votes"][0]["reasoning_chars"] == 10
    s2 = verify.run([CAND], FakeClient([YES]), out, votes=3)
    assert s2["skipped"] == 1 and len(io.read_jsonl(out)) == 1


def test_run_tops_up_votes(tmp_path):
    out = str(tmp_path / "verify.jsonl")
    verify.run([CAND], FakeClient([YES, YES, NO]), out, votes=3)
    c = FakeClient([NO, NO])
    verify.run([CAND], c, out, votes=5)
    r = io.read_jsonl(out)
    assert len(r) == 1 and len(r[0]["votes"]) == 5 and r[0]["yes"] == 2 and r[0]["no"] == 3 and not r[0]["pass"] and c.calls == 2


def test_unparsed_counts_as_no(tmp_path):
    out = str(tmp_path / "v.jsonl")
    verify.run([CAND], FakeClient([YES, "garbage", "garbage"]), out, votes=3)
    r = io.read_jsonl(out)[0]
    assert r["yes"] == 1 and r["no"] == 2 and not r["pass"]


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
        verify.run([CAND, c2], Dies([YES, YES, NO]), out, votes=3, workers=1)
    except Crash:
        pass
    rows = io.read_jsonl(out)
    assert [r["id"] for r in rows] == ["c1"] and rows[0]["yes"] == 2       # c1's three votes survived the crash
    c = FakeClient([NO, NO, NO])
    s = verify.run([CAND, c2], c, out, votes=3, workers=1)
    assert s["skipped"] == 1 and c.calls == 3 and [r["id"] for r in io.read_jsonl(out)] == ["c1", "c2"]


def test_short_verdict_line_is_accepted():
    assert verify.parse_verdict("... all fine.\n\nVerification: Yes") == "yes"
    assert verify.parse_verdict("Verification: **No**") == "no"
