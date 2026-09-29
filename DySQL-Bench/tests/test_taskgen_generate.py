# tests/test_taskgen_generate.py
import json, random
import pytest
from dysql_bench.taskgen import generate, io
from tests.test_taskgen_prompt import ANCHOR, DB, TREE, OTHERS

GOOD = '<thought>t</thought><answer>{"instruction": "I am a5 b5. Set qty of order 5 to 3.", "actions": [{"sql": "UPDATE orders SET qty = 3 WHERE order_id = 5"}], "outputs": []}</answer>'


class FakeClient:
    model = "fake"
    def __init__(self, contents): self.contents, self.calls = list(contents), 0
    def chat(self, messages, **kw):
        self.calls += 1
        return {"content": self.contents.pop(0), "reasoning": "", "usage": {"prompt_tokens": 1, "completion_tokens": 1}, "model": "fake"}


def test_parse_answer_variants():
    base = {"instruction": "x", "actions": [{"sql": "UPDATE a SET b = 1"}], "outputs": []}
    js = json.dumps(base)
    assert generate.parse_answer(f"<answer>{js}</answer>") == base
    assert generate.parse_answer(f"<answer>```json\n{js}\n```</answer> trailing words") == base
    assert generate.parse_answer(f"blah {js}") == base                         # no tag: last JSON object
    assert generate.parse_answer('<answer>{"instruction": "x", "actions": ["UPDATE a SET b = 1"]}</answer>') == base   # bare strings
    for bad in ["<answer>{not json}</answer>", '<answer>{"instruction": "x"}</answer>', '<answer>{"instruction": "", "actions": []}</answer>']:
        with pytest.raises(generate.ParseError):
            generate.parse_answer(bad)


def test_run_writes_records_and_resumes(tmp_path):
    out = str(tmp_path / "candidates.jsonl")
    client = FakeClient([GOOD, GOOD])
    stats = generate.run(DB, ANCHOR, [TREE, {**TREE, "key_value": 6}], OTHERS, client, out, random.Random(0), workers=2)
    recs = io.read_jsonl(out)
    assert stats["written"] == 2 and [r["id"] for r in recs] == ["test:shop:customers:5:0", "test:shop:customers:6:0"]
    assert recs[0]["instruction"].startswith("I am a5 b5") and recs[0]["actions"] == [{"sql": "UPDATE orders SET qty = 3 WHERE order_id = 5"}]
    assert recs[0]["plan"]["task_type"] in ("1_self", "2_self_and_public", "3_public_only", "4_other_person", "5_proxy")
    again = generate.run(DB, ANCHOR, [TREE], OTHERS, FakeClient([GOOD]), out, random.Random(0))
    assert again["written"] == 0 and again["skipped"] == 1 and len(io.read_jsonl(out)) == 2


def test_generate_records_parse_error_and_continues(tmp_path):
    out = str(tmp_path / "c.jsonl")
    client = FakeClient(["<answer>{oops</answer>", GOOD])
    stats = generate.run(DB, ANCHOR, [TREE, {**TREE, "key_value": 6}], OTHERS, client, out, random.Random(0))
    recs = io.read_jsonl(out)
    assert stats["written"] == 2 and stats["errors"] == 1
    assert recs[0]["instruction"] is None and "ParseError" in recs[0]["error"] and recs[1]["instruction"]


def test_generate_records_llm_exception(tmp_path):
    class Boom(FakeClient):
        def chat(self, messages, **kw): raise RuntimeError("HTTP 500")
    out = str(tmp_path / "c.jsonl")
    stats = generate.run(DB, ANCHOR, [TREE], OTHERS, Boom([]), out, random.Random(0))
    r = io.read_jsonl(out)[0]
    assert stats["errors"] == 1 and r["instruction"] is None and "HTTP 500" in r["error"]


def test_retry_errors_replaces_api_failures_but_keeps_parse_failures(tmp_path):
    class Boom(FakeClient):
        def chat(self, messages, **kw): raise RuntimeError("HTTP 429")
    out = str(tmp_path / "c.jsonl")
    generate.run(DB, ANCHOR, [TREE], OTHERS, Boom([]), out, random.Random(0))
    generate.run(DB, ANCHOR, [{**TREE, "key_value": 6}], OTHERS, FakeClient(["<answer>{oops</answer>"]), out, random.Random(0))
    s = generate.run(DB, ANCHOR, [TREE, {**TREE, "key_value": 6}], OTHERS, FakeClient([GOOD]), out, random.Random(0), retry_errors=True)
    recs = io.read_jsonl(out)
    assert s["written"] == 1 and len(recs) == 2                           # the 429 record was replaced, not duplicated
    by_id = {r["id"]: r for r in recs}
    assert by_id["test:shop:customers:5:0"]["instruction"].startswith("I am a5 b5")
    assert "ParseError" in by_id["test:shop:customers:6:0"]["error"]      # a model answer we could not parse is not retried


class Crash(BaseException):
    pass


def test_generate_appends_each_result_as_it_finishes(tmp_path):
    class Dies(FakeClient):
        def chat(self, messages, **kw):
            if self.calls == 1:
                raise Crash()
            return super().chat(messages, **kw)
    out = str(tmp_path / "c.jsonl")
    try:
        generate.run(DB, ANCHOR, [TREE, {**TREE, "key_value": 6}], OTHERS, Dies([GOOD, GOOD]), out, random.Random(0), workers=1)
    except Crash:
        pass
    assert [r["id"] for r in io.read_jsonl(out)] == ["test:shop:customers:5:0"]


def test_parse_answer_rejects_non_string_instruction_and_skips_unrelated_objects():
    with pytest.raises(generate.ParseError):
        generate.parse_answer('<answer>{"instruction": ["a"], "actions": [{"sql": "UPDATE a SET b = 1"}]}</answer>')
    text = 'thinking {"sql": "x"} then {"instruction": "i", "actions": [{"sql": "UPDATE a SET b = 1"}]}'
    assert generate.parse_answer(text)["instruction"] == "i"


def test_unexpected_parse_exception_is_recorded(tmp_path, monkeypatch):
    monkeypatch.setattr(generate, "parse_answer", lambda t: (_ for _ in ()).throw(AttributeError("boom")))
    out = str(tmp_path / "c.jsonl")
    s = generate.run(DB, ANCHOR, [TREE], OTHERS, FakeClient([GOOD]), out, random.Random(0))
    assert s["errors"] == 1 and "AttributeError" in io.read_jsonl(out)[0]["error"]
