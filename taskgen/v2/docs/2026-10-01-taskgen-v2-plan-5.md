# 训练任务生成 v2：实施计划 5（试点和全量）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成设计的阶段 H（试点，并进全量：beer_factory 先校验，Qwen3-4B 试跑当关卡）和阶段 I（23 个库全量产出训练任务）。开跑之前先补上全量需要的几处代码。

**Architecture:**
- `verify.py`：
  - 默认 3 票多数，按轮投票，结论定了就停：两票一致不投第三票。
  - 定不下来的题记为"没投上票"，下次运行再补。
  - 连续失败的调用到上限就暂停（额度用完）；`taskgen.py verify` 退出码 3，同一条命令续跑。
- `check.py`：
  - 新规则 `archive_split`：同一张表有两条以上由 SQLite 给副本编号的 `INSERT … SELECT`，就拒。
  - 复数词尾只给 3 个字母以上的词。
  - 双引号的 `"now"`（`datetime("now")`）也算读时钟。
- `prompt.py`：archive 要求一条语句复制全部行；只有两行的批量一律"整组全改"。
- `trees.py`：`lookup` 不用和主键相同的名字列。
- `dedup.py`：近重复过滤（设计 §4.7）。
- `taskgen.py dedup`：跳过抽检排除的题（`excluded.jsonl`）。
- 之后跑全量出题和检查；beer_factory 先校验，Qwen3-4B 试跑当关卡（试点）；过关再校验其余 22 个库；最后抽检。

**Tech Stack:**
- Python 3.11（`~/miniconda3/envs/dysql`）、sqlite3、sqlparse、requests、pytest。
- GLM-5.3 出题，并发 ≤5。
- ollama.com 上的 `deepseek-v4.1-flash` 校验，并发 ≤3。
- GB10 上已在运行的两个 vLLM 服务：用户模拟器 `qwen2.5-72b-awq`（:8001），agent `qwen3-4b`（:8002）。

**Spec:** `taskgen/v2/docs/2026-10-01-taskgen-v2-design.md`（§5 H、I，§4.6、§4.7，D11）。

## 本计划新定的事（设计里没写到，请审阅时确认）

1. **全量校验每条 3 票、多数通过**（你定的）。
   - 按轮投：先投两票，一致就定；不一致再投第三票。结果和每条都投满 3 票完全一样。
   - 计划 4 校准时两票一致的比例是 118/119，所以平均约 2.05 票一条。
   - 一条题在本次运行里没能定下结论的，记为 `unvoted`：可能是每次调用都失败或被截断，也可能是分歧后第三票失败了。这类题不算通过，也不算拒绝，再跑一次 `verify` 只补缺的票。
2. **额度用完时暂停。**
   - 连续 20 次调用失败（思考被截断不算），本次运行就停下，已投的票都保存好。`taskgen.py verify` 打印 `paused …`，退出码 3，不再处理后面的库。
   - 这时你去申请更大的套餐，之后用同一条命令接着跑。
3. **新检查规则 `archive_split`**，按你"挡住肯定错的、少量误杀没关系"的原则。
   - 起因：计划 4 唯一被校验放过的坏题。同一张表有两条以上 `INSERT … SELECT`，副本的键又由 SQLite 编号时，副本的键取决于语句顺序；agent 用一条语句一次复制，编号就会对调。
   - SQL 自己写明副本键的，不受影响。
   - 出题 prompt 同时改为要求一条语句复制全部行。
   - 写计划时重新校准：DySQL 金标准 895 → 894（只有 dysql:chinook:13 被拒），v1 候选 3872 → 3872；计划 3、4 的 480 条候选里只拒 food_inspection_2 employee:117743:0，就是那条坏题。
4. **复数规则收紧**：只有 3 个字母以上的词才认复数词尾，`'M'` 不再匹配 "Ms"。重新校准没有任何判决变化。
5. **双引号的 `"now"` 也算读时钟**（你定的）。没有叫 now 的列时，SQLite 把 `"now"` 当字符串 `'now'`，`datetime("now")` 照样取当前时间；原来的检查只认单引号，写入当前时间的题能过检查，agent 却永远对不上。现在和 `'now'` 一样在两个固定时刻重跑。DySQL 金标准和 v1 候选里都没有这种写法，重新校准判决不变。
6. **近重复过滤**（设计 §4.7）。同一个库里，instruction 的词级 3-gram Jaccard ≥0.6 的只留第一条，在终封顶之前做。计划 3、4 的 480 条候选里，同一个库内两两之间最高只有 0.11，预计几乎删不到题；这一步是兜底。
7. **抽检**（D11："每库抽 30 条人工看"）。
   - 全量产出后，每个库随机抽 30 条（不足 30 条的全看），共约 690 条。
   - 由 Claude 分 5 批交给子代理看，标准和计划 4 相同（只看得到 instruction、能查库的 agent，能不能留下和 SQL 一样的库）。子代理判为坏或拿不准的，Claude 逐条复核。
   - 确认是坏题的写进 `results/<db>/excluded.jsonl`，`dedup` 时去掉，再重新 `convert`。抽检结果只记计数和 id。
8. **试点并进全量**（阶段 H，你定的）。
   - 不另出试点题。23 个库的出题和检查先做完（只花 GLM），再只校验 beer_factory（约 400 票，全量本来就要投），转换后用 GB10 上已在运行的两个服务，让 Qwen3-4B 随机跑其中 60 条（`--task-ids`，`random.Random(0)` 抽）。
   - 关卡：通过率在 20–50% 之间（v1 试点 23.2%，4B 在 DySQL 上是 29.8%；60 条的误差约 ±12 个百分点）。过了才校验其余 22 个库，关卡挡在约 6,600 票前面。另外记下第一票和最终结论不同的题数，只作记录，你已定 3 票。
   - 检查阶段的统计（拒绝原因、指标）在花任何 ollama 票之前就能看到，异常先停。
   - 代价：如果试点发现出题本身有问题，GLM 那 8–9 小时出的题可能要重出。出题这部分计划 3、4 已在 GLM 上验证过（481 条，过检查 98.8%，要求类型和算出类型不一致 0）。
9. **全量**（阶段 I）。
   - 23 个库，`--n 200 --seed 0`。200 是上限，8 个小库不足：book_publishing_company 23、student_club 33、school_scheduling 46、regional_sales 50、food_inspection_2 75、shipping 100、hr_1 107、car_retails 122。合计约 3,556 棵树。
   - 建树、出题、检查在 Task 5 做（GLM 约 8–9 小时）；关卡过了再 `verify --all-dbs` 校验其余 22 个库（约 6,600 票、约 6.5 小时，可能分几次跑完），最后逐库去重封顶和转换，写出 `output/manifest.json`。
   - 设计估计最后留下约 2,300–2,700 条任务。
10. **这次不做的**（放计划 6，你定的）：
   - 阶段 J（v1 对照集）和 K（收尾）。
   - 和 DySQL 的两处差别：库外的人改实体数据（DySQL 约 8%，主要是 car、cookbook）v2 没有覆盖；写语句里 INSERT 偏少（v2 约 10%，DySQL 15%），原因待查。
   - 计划 4 留下的统计类 minor 仍记在 memory 里。
11. **时间和额度**：GLM 约 8–9 小时（试点不另出题）；ollama 约 7,000 票（试点不另花）；GB10 上 4B 关卡约 35 分钟。
12. **档案文字在本计划之前修正过**（你定的）。2026-10-01 对 23 个库的描述和数据怪异点做了事实核对，16 个库的 description 和 quirks 按查库结果改过，你确认后单独提交（66ea236），在本计划文档之前。根、人物表、事件、公共表都没动，所以检查的判决不受影响。试点和全量用的是改过的档案；WWE 保留，只改文字（多数选手条目是组合、每场比赛存了 7 份）。

## Global Constraints

- 生成的候选、校验、抽检、产出（`taskgen/v2/results/`、`taskgen/v2/output/`、`DySQL-Bench/results/`）**不进 git、不公开**。文档只写计数和 id，不摘录题目内容。每次 commit 前看 `git diff --cached --name-only`。
- `.env` 里有 API key：不打印、不提交，只能显示 `BASE_URL` / `MODEL` 行。
- GLM 并发 ≤5（`--workers 5`）；ollama.com 并发 ≤3（`--workers 3`）。
- GB10 的 8001、8002 两个服务已经在运行，不重启。如果不在了，按 `docs/gb10_serving_notes.md` 一次起一个，等 `/v1/models` 返回 200 再起下一个。
- `taskgen/v1/` 冻结；`data/db_profiles.json` 只由用户确认，本计划不改。
- 推送由用户自己做；只推分支，不开 PR。
- 命令里 `REPO=/home/wmd3i/Documents/Isa/DySQL-Bench`，`P=~/miniconda3/envs/dysql/bin/python`，`S=` 本次的 scratchpad 目录。

## Review Focus

1. **暂停发生在一轮投票中间**：已返回的票都保存；用同一条命令续跑，只补缺的票，不会重复计票。→ Task 1 的 `test_a_long_run_of_failed_calls_pauses_the_run`（后半段续跑）。
2. **第三票调用失败**：题保持 `unvoted`，不算通过；下次运行只补第三票。→ Task 1 的 `test_failed_votes_are_not_counted_and_are_retried`。
3. **SQL 自己写明副本键**（键恰好等于 MAX+1、MAX+2）：不能被 `archive_split` 拒。→ Task 2 的 `test_two_archive_copies_numbered_by_sqlite_are_rejected`（第三种情况）。
4. **名字列就是主键的人**（student_loan）：`lookup` 为空，不出子查询的形状。→ Task 3 的 `test_lookup_skips_a_name_column_that_is_the_key`。
5. **抽检排除的题**：`dedup` 后不再出现；没有 `excluded.jsonl` 时什么都不排除。→ Task 4 的 `test_dedup_leaves_out_the_tasks_a_review_excluded`（其余 CLI 测试都没有这个文件）。

---

### Task 1: 校验：3 票多数、结论定了就停，额度用完就暂停

**Files:**
- Modify: `taskgen/v2/taskgen_v2/verify.py`（新函数 `settled`、`needed`、`_keep`；`tally(rec, models)`；`run` 按轮投票、带 `max_failures`；`DEFAULT_VOTES = 3`；`import threading`）
- Modify: `taskgen/v2/scripts/taskgen.py`（`verify` 暂停时退出码 3；`--max-failures`）
- Test: `taskgen/v2/tests/test_taskgen_verify.py`（整个换掉）、`taskgen/v2/tests/test_taskgen_cli.py`

**Interfaces:**
- Consumes: 计划 4 的 `verify.run(cands, models, out_path, workers, context)`、`_vote_safe`、`_real`。
- Produces:
  - `verify.settled(votes, k) -> "pass" | "fail" | None`：一个模型的真票（前 k 张）在 k 票多数规则下是否已定。
  - `verify.needed(votes, k) -> int`：现在再要几票才可能定下（3 票时：开始 2，分歧后 1，定了 0）。
  - `verify.tally(rec, models)`：`models` 是 `[(name, k)]`。每个模型的 `pass` 是 `True` / `False` / `None`（未定）；`rec["unvoted"]` 表示有模型未定。
  - `verify.run(..., max_failures=20) -> {"verified", "passed", "skipped", "unvoted", "paused"}`。`skipped` 是开跑前已经定了的题。
  - `verify.DEFAULT_VOTES = 3`。
  - `taskgen.py verify --max-failures N`：暂停时打印 `paused after N failed calls in a row; run verify again later`，退出码 3。

- [ ] **Step 1: 写失败的测试**

`tests/test_taskgen_verify.py` 整个换成：

```python
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
```

`tests/test_taskgen_cli.py` 末尾加：

```python
class Refuses(BaseHTTPRequestHandler):
    """An endpoint whose quota is gone: every call fails."""
    calls = 0

    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        Refuses.calls += 1
        out = b'{"error": "weekly usage limit reached"}'
        self.send_response(400); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out))); self.end_headers(); self.wfile.write(out)

    def log_message(self, *a):
        pass


def test_verify_pauses_when_every_call_fails(tmp_path):
    args = setup(tmp_path)
    out = tmp_path / "res"
    run("trees", *args, "--n", "3", "--seed", "0")
    io.append_jsonl(out / "candidates.jsonl", [
        {"id": "test:shop2:customers:%s:0" % t["key_value"], "db": "shop2", "source": "test", "anchor_table": "customers",
         "anchor_key": "customer_id", "key_value": t["key_value"], "anchor_name": t["anchor_name"],
         "profile_version": t["profile_version"], "plan": {"task_type": "1_self", "difficulty": "easy"},
         "instruction": f"I am {t['anchor_name']}. Set qty of my order {t['events'][0]['rows'][0]['row']['order_id']} to 3.",
         "actions": [{"sql": f"UPDATE orders SET qty = 3 WHERE order_id = {t['events'][0]['rows'][0]['row']['order_id']}"}],
         "error": None} for t in io.read_jsonl(out / "trees.jsonl")])
    run("check", *args)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Refuses)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    env = {**os.environ, "TASKGEN_VERIFY_BASE_URL": f"http://127.0.0.1:{srv.server_port}/v1",
           "TASKGEN_VERIFY_API_KEY": "k", "TASKGEN_VERIFY_MODELS": "m1:3"}
    try:
        r = subprocess.run([sys.executable, SCRIPT, "verify", *args, "--workers", "1", "--max-failures", "2"],
                           capture_output=True, text=True, env=env)
    finally:
        srv.shutdown()
    assert r.returncode == 3 and "paused" in r.stderr and Refuses.calls == 2
    assert all(not v["pass"] and v["unvoted"] for v in io.read_jsonl(out / "verify.jsonl"))
```

- [ ] **Step 2: 跑测试，确认失败**

```bash
cd $REPO/taskgen/v2 && $P -m pytest -q tests/test_taskgen_verify.py tests/test_taskgen_cli.py 2>&1 | tail -n 3
```
Expected：`11 failed, 15 passed`。失败的是：
- `test_run_votes_majority_and_resumes`
- `test_run_tops_up_votes`
- `test_finished_candidates_are_written_before_a_crash`
- `test_failed_votes_are_not_counted_and_are_retried`
- `test_a_vote_cut_off_while_thinking_is_not_a_no_and_is_asked_again`
- `test_a_task_without_any_vote_is_unvoted_not_rejected`
- `test_three_votes_stop_once_two_agree`
- `test_settled_and_needed`
- `test_a_long_run_of_failed_calls_pauses_the_run`
- `test_a_vote_cut_off_while_thinking_does_not_count_toward_a_pause`
- `test_verify_pauses_when_every_call_fails`

- [ ] **Step 3: 实现**

`taskgen_v2/verify.py` 里把

```python
import json, os, re
```

换成：

```python
import json, os, re, threading
```

`taskgen_v2/verify.py` 里把

```python
DEFAULT_VOTES = 1   # one vote, Yes to pass: in plan 4 it kept 98% of the good tasks and rejected every broken one
```

换成：

```python
DEFAULT_VOTES = 3   # majority of three, settled after two when they agree: the user's choice for the full run
                    # (plan 5); one vote was enough in plan 4's calibration
```

`taskgen_v2/verify.py` 里把

```python
def tally(rec, names):
    """Per model Yes/No counts and pass (Yes strictly more than No; unparsed counts as No); the task passes when
    every model passes it. A model without a single real vote (every call cut off or failed) has pass None and the
    task is 'unvoted': not passed, not rejected either, and voted again on the next run."""
    rec["models"] = {}
    for name in names:
        votes = _real(rec["votes"], name)
        yes = sum(v["verdict"] == "yes" for v in votes)
        rec["models"][name] = {"yes": yes, "no": len(votes) - yes, "pass": (yes > len(votes) - yes) if votes else None}
    rec["pass"] = all(m["pass"] is True for m in rec["models"].values())
    rec["unvoted"] = any(m["pass"] is None for m in rec["models"].values())
    rec["verify_model"] = ",".join(names)
    return rec


def run(cands, models, out_path, workers=3, context=lambda cand: ("", ())):
    """models: [(client, votes)]; context(cand) -> (ddl_text, notes). Every vote goes to one thread pool; a new
    candidate's record is appended as soon as its last vote returns, so an interrupted run keeps all finished
    candidates. Records that were topped up are rewritten in place at the end."""
    names = [getattr(c, "model", None) for c, _ in models]
    existing = {r["id"]: r for r in io.read_jsonl(out_path)}
    jobs = [(c, client) for c in cands for client, n in models
            for _ in range(n - len(_real(existing.get(c["id"], {}).get("votes", []), getattr(client, "model", None))))]
    pending = {}
    for c, _ in jobs:
        pending[c["id"]] = pending.get(c["id"], 0) + 1
    new_votes, updated, passed, unvoted = {}, {}, 0, 0
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        futs = {ex.submit(_vote_safe, client, build_messages(c, *context(c))): c["id"] for c, client in jobs}
        for f in as_completed(futs):
            cid = futs[f]
            new_votes.setdefault(cid, []).append(f.result())
            pending[cid] -= 1
            if pending[cid]:
                continue
            rec = existing.get(cid) or {"id": cid, "votes": []}
            rec = tally({**rec, "votes": rec["votes"] + new_votes.pop(cid)}, names)
            passed += rec["pass"]; unvoted += rec["unvoted"]
            if cid in existing:
                updated[cid] = rec
            else:
                io.append_jsonl(out_path, [rec])
    if updated:  # rewrite the file with the topped-up records in place
        rows = [updated.get(r["id"], r) for r in io.read_jsonl(out_path)]
        tmp = out_path + ".tmp"
        if os.path.exists(tmp):
            os.remove(tmp)
        io.append_jsonl(tmp, rows)
        os.replace(tmp, out_path)
    return {"verified": len(pending), "passed": passed, "skipped": len(cands) - len(pending), "unvoted": unvoted}
```

换成：

```python
def settled(votes, k):
    """'pass' / 'fail' for a model's real votes under its k-vote rule (the first k; Yes must outnumber No, unparsed
    counts as No) as soon as more votes cannot change it: two Yes or two No settle three votes. None until then."""
    votes = votes[:k]
    yes = sum(v["verdict"] == "yes" for v in votes)
    if yes > k / 2:
        return "pass"
    if len(votes) - yes >= k / 2:
        return "fail"
    return None


def needed(votes, k):
    """How many more votes could settle the rule now: enough for one side to reach a majority (two of three at the
    start, one after a split); 0 once settled."""
    if settled(votes, k):
        return 0
    votes = votes[:k]
    yes = sum(v["verdict"] == "yes" for v in votes)
    return k // 2 + 1 - max(yes, len(votes) - yes)


def tally(rec, models):
    """models: [(name, k)]. Per model Yes/No counts and pass (settled(), None while unsettled); the task passes when
    every model passes it. A task some model has not settled -- every call cut off or failed, or a split still
    waiting for its third vote -- is 'unvoted': not passed, not rejected either, and voted again on the next run."""
    rec["models"] = {}
    for name, k in models:
        votes = _real(rec["votes"], name)[:k]
        yes = sum(v["verdict"] == "yes" for v in votes)
        v = settled(votes, k)
        rec["models"][name] = {"yes": yes, "no": len(votes) - yes, "pass": None if v is None else v == "pass"}
    rec["pass"] = all(m["pass"] is True for m in rec["models"].values())
    rec["unvoted"] = any(m["pass"] is None for m in rec["models"].values())
    rec["verify_model"] = ",".join(name for name, _ in models)
    return rec


def run(cands, models, out_path, workers=3, context=lambda cand: ("", ()), max_failures=20):
    """models: [(client, votes)]; context(cand) -> (ddl_text, notes). Votes go out in rounds: each round asks, for
    every task and model, only the votes that could still settle it (needed()), so three votes by majority cost about
    two a task. A call that fails is not asked again in the same run. After max_failures failed calls in a row (an
    exhausted quota answers every call with an error) the run stops and returns paused=True; the same command
    resumes it. A new task's record is appended as soon as its votes of a round are in, so an interrupted run keeps
    them; records that got more votes are rewritten in place at the end."""
    names = [(getattr(c, "model", None), k) for c, k in models]
    existing = {r["id"]: r for r in io.read_jsonl(out_path)}
    in_file, dirty, voted, failed = set(existing), set(), set(), set()
    settled_before = sum(1 for c in cands if not any(
        needed(_real(existing.get(c["id"], {}).get("votes", []), getattr(cl, "model", None)), k) for cl, k in models))
    stop, lock, streak = threading.Event(), threading.Lock(), [0]

    def job(client, msgs):   # counts failures where they happen, so no call goes out after the limit
        if stop.is_set():
            return None
        v = _vote_safe(client, msgs)
        with lock:
            if "error" not in v or v["error"].startswith("Truncated"):   # cut off while thinking: the API works
                streak[0] = 0
            else:
                streak[0] += 1
                if streak[0] >= max_failures:
                    stop.set()
        return v

    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        while not stop.is_set():
            jobs = [(c, client) for c in cands for client, k in models
                    if (c["id"], getattr(client, "model", None)) not in failed
                    for _ in range(needed(_real(existing.get(c["id"], {}).get("votes", []), getattr(client, "model", None)), k))]
            if not jobs:
                break
            pending = {}
            for c, _ in jobs:
                pending[c["id"]] = pending.get(c["id"], 0) + 1
            futs = {ex.submit(job, client, build_messages(c, *context(c))): c["id"] for c, client in jobs}
            new = {}
            for f in as_completed(futs):
                cid, v = futs[f], f.result()
                pending[cid] -= 1
                if v is not None:   # None: not asked, the run is pausing
                    new.setdefault(cid, []).append(v)
                    if "error" in v:
                        failed.add((cid, v.get("model")))
                if pending[cid] == 0 and cid in new:
                    _keep(existing, in_file, dirty, out_path, cid, new.pop(cid), names); voted.add(cid)
            for cid, votes in new.items():   # cut short by a pause: keep what came back
                _keep(existing, in_file, dirty, out_path, cid, votes, names); voted.add(cid)
    if dirty:  # rewrite the file with the records that got more votes, in place
        rows = [existing[r["id"]] if r["id"] in dirty else r for r in io.read_jsonl(out_path)]
        tmp = out_path + ".tmp"
        if os.path.exists(tmp):
            os.remove(tmp)
        io.append_jsonl(tmp, rows)
        os.replace(tmp, out_path)
    recs = [existing[cid] for cid in voted]
    return {"verified": len(voted), "passed": sum(r["pass"] for r in recs), "skipped": settled_before,
            "unvoted": sum(r["unvoted"] for r in recs), "paused": stop.is_set()}


def _keep(existing, in_file, dirty, out_path, cid, votes, names):
    """Tally a task's new votes into its record: appended when the file does not have it yet, else marked for the
    rewrite at the end of the run."""
    rec = existing.get(cid) or {"id": cid, "votes": []}
    existing[cid] = rec = tally({**rec, "votes": rec["votes"] + votes}, names)
    if cid in in_file:
        dirty.add(cid)
    else:
        io.append_jsonl(out_path, [rec])
        in_file.add(cid)
```

`scripts/taskgen.py` 里把

```python
        s = verify.run(cands, models, f"{out}/verify.jsonl", workers=a.workers, context=lambda c: (ddl, quirks))
        print(f"{db}: {s} in {time.time() - t0:.0f}s")
```

换成：

```python
        s = verify.run(cands, models, f"{out}/verify.jsonl", workers=a.workers, context=lambda c: (ddl, quirks),
                       max_failures=a.max_failures)
        print(f"{db}: {s} in {time.time() - t0:.0f}s")
        if s["paused"]:   # the quota is gone (or the endpoint is down): stop here, the same command resumes
            print(f"paused after {a.max_failures} failed calls in a row; run verify again later", file=sys.stderr)
            sys.exit(3)
```

`scripts/taskgen.py` 里把

```python
    p.add_argument("--precap-template", type=int, default=25); p.add_argument("--precap-db", type=int, default=900)
```

换成：

```python
    p.add_argument("--precap-template", type=int, default=25); p.add_argument("--precap-db", type=int, default=900)
    p.add_argument("--max-failures", type=int, default=20, help="failed calls in a row before the run pauses (quota gone)")
```

- [ ] **Step 4: 跑测试，确认通过**

```bash
cd $REPO/taskgen/v2 && $P -m pytest -q tests/test_taskgen_verify.py tests/test_taskgen_cli.py 2>&1 | tail -n 3
```
Expected：`26 passed`。

- [ ] **Step 5: 跑全套**

```bash
cd $REPO/taskgen/v2 && $P -m pytest -q  2>&1 | tail -n 3
```
Expected：`185 passed`。

- [ ] **Step 6: commit**

```bash
cd $REPO
git add taskgen/v2/taskgen_v2/verify.py \
        taskgen/v2/scripts/taskgen.py \
        taskgen/v2/tests/test_taskgen_verify.py \
        taskgen/v2/tests/test_taskgen_cli.py
git diff --cached --name-only
git commit -m "feat(taskgen v2): three votes by majority, asked in rounds; a run pauses when calls keep failing

The user chose three votes for the full run. A task gets two votes, and a third only when they split, so the
majority costs about two votes a task with the same verdicts. A task some model has not settled (calls failed or
cut off, or a split still waiting) is unvoted, not rejected, and the next run asks only for what is missing. After
20 failed calls in a row -- an exhausted quota answers every call with an error -- the run stops, keeps every
vote that came back, and taskgen.py verify exits 3; the same command resumes.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```
Expected：暂存区只有这 4 个文件。

---

### Task 2: archive：一条语句复制，两条以上由 SQLite 编号的复制就拒；两行的批量整组全改

**Files:**
- Modify: `taskgen/v2/taskgen_v2/check.py`（新函数 `names_column`；`run_check` 新理由 `archive_split: <表>`）
- Modify: `taskgen/v2/taskgen_v2/prompt.py`（archive 的说明；批量组只有两行时 `all` 为真）
- Test: `taskgen/v2/tests/test_taskgen_check.py`、`taskgen/v2/tests/test_taskgen_prompt.py`

**Interfaces:**
- Consumes: 无。
- Produces:
  - `check.names_column(stmt, col) -> bool`：INSERT 是否给了 col 的值（列清单里有它，或者没有列清单）。
  - 检查理由 `archive_split: <表>`：同一张表的第二条 `INSERT … SELECT` 没给键、由 SQLite 编号时出现。
  - `prompt.sample_plan` 的批量组只有两行时 `batch["all"]` 为真；archive 的说明改为 "First copy all the <表> rows you will change, in one statement, as new rows with INSERT INTO …"

- [ ] **Step 1: 写失败的测试**

`tests/test_taskgen_prompt.py` 里把

```python
    assert 'First copy the orders rows you will change as new rows with INSERT INTO "orders" ... SELECT ... FROM "orders"' in u
```

换成：

```python
    assert ('First copy all the orders rows you will change, in one statement, as new rows with INSERT INTO "orders" ... '
            'SELECT ... FROM "orders"') in u
```

`tests/test_taskgen_prompt.py` 末尾加：

```python
def test_a_batch_of_two_rows_takes_both():
    # "by a condition" over a group of two read "it changes between 2 and 1 rows"
    two = {**TREE, "events": [{**TREE["events"][0], "count": 2, "rows": TREE["events"][0]["rows"][:2]}, TREE["events"][1]]}
    batches = [p["shape"]["batch"] for p in plans(3000, two) if p["shape"]["batch"]]
    assert batches and all(b["all"] and b["count"] == 2 for b in batches)
```

`tests/test_taskgen_check.py` 末尾加：

```python
def test_two_archive_copies_numbered_by_sqlite_are_rejected(db):
    # SQLite numbers the copies in statement order; an agent that copies both rows in one INSERT ... SELECT numbers
    # them in table order, so whether it matches the gold would hang on the order of two statements
    one = "INSERT INTO order_items (order_id, note) SELECT order_id, note FROM order_items WHERE item_id = {}"
    change = "UPDATE order_items SET note = 'x' WHERE item_id IN (5, 65)"
    ask = "I am a5 b5. Copy my order items 65 and 5, then set the note of items 5 and 65 to x."
    r = check.run_check(db, cand(ask, [one.format(65), one.format(5), change]))
    assert "archive_split: order_items" in r["reasons"]
    r = check.run_check(db, cand(ask, [one.format("65 OR item_id = 5"), change]))
    assert r["ok"], r["reasons"]
    new = sqlite3.connect(db["path"]).execute("SELECT MAX(item_id) + 1 FROM order_items").fetchone()[0]
    keyed = "INSERT INTO order_items (item_id, order_id, note) SELECT {}, order_id, note FROM order_items WHERE item_id = {}"
    r = check.run_check(db, cand(f"I am a5 b5. Copy items 65 and 5 as items {new} and {new + 1}, then set the note of items 5 and 65 to x.",
                                 [keyed.format(new, 65), keyed.format(new + 1, 5), change]))
    assert r["ok"], r["reasons"]        # the SQL states the copies' keys: nothing hangs on the order
```

- [ ] **Step 2: 跑测试，确认失败**

```bash
cd $REPO/taskgen/v2 && $P -m pytest -q tests/test_taskgen_prompt.py tests/test_taskgen_check.py 2>&1 | tail -n 3
```
Expected：`3 failed, 68 passed`。失败的是：
- `test_subquery_archive_batch_and_proxy_wording`
- `test_a_batch_of_two_rows_takes_both`
- `test_two_archive_copies_numbered_by_sqlite_are_rejected`

- [ ] **Step 3: 实现**

`taskgen_v2/prompt.py` 里把

```python
        lines.append(f"- First copy the {s['archive']} rows you will change as new rows with INSERT INTO \"{s['archive']}\" ... "
```

换成：

```python
        lines.append(f"- First copy all the {s['archive']} rows you will change, in one statement, as new rows with INSERT INTO \"{s['archive']}\" ... "
```

`taskgen_v2/prompt.py` 里把

```python
        batch = {"table": g["table"], "label": g["label"], "count": g["count"], "all": rng.random() < cfg["BATCH_ALL"]}
```

换成：

```python
        batch = {"table": g["table"], "label": g["label"], "count": g["count"],
                 "all": rng.random() < cfg["BATCH_ALL"] or g["count"] < 3}   # two rows: a condition would pick 1 of them
```

`taskgen_v2/check.py` 里把

```python
def has_archive(stmts):
```

换成：

```python
def names_column(stmt, col):
    """Whether an INSERT gives a value for col: its column list names it, or it has no column list (every column)."""
    m = re.match(r'(?is)^\s*(?:insert|replace)\s+(?:or\s+\w+\s+)?into\s+' + _NAME + r'\s*\(([^)]*)\)', stmt)
    return not m or col.lower() in [c.strip().strip('"[]`').lower() for c in m.group(5).split(",")]


def has_archive(stmts):
```

`taskgen_v2/check.py` 里把

```python
    copies = {}   # table -> rowids an INSERT ... SELECT added: the archived copies, which later writes must leave alone
```

换成：

```python
    copies = {}   # table -> rowids an INSERT ... SELECT added: the archived copies, which later writes must leave alone
    numbered = {}   # table -> INSERT ... SELECTs whose copies SQLite numbered, in statement order
```

`taskgen_v2/check.py` 里把

```python
                if nxt is not None:
                    # keys SQLite would assign anyway
```

换成：

```python
                if top is not None and key in auto and not names_column(st, auto[key][1]):
                    numbered[table] = numbered.get(table, 0) + 1
                    if numbered[table] == 2:   # one INSERT ... SELECT for all rows would number them in table order
                        out["reasons"].append(f"archive_split: {table}")
                if nxt is not None:
                    # keys SQLite would assign anyway
```

- [ ] **Step 4: 跑测试，确认通过**

```bash
cd $REPO/taskgen/v2 && $P -m pytest -q tests/test_taskgen_prompt.py tests/test_taskgen_check.py 2>&1 | tail -n 3
```
Expected：`71 passed`。

- [ ] **Step 5: 跑全套**

```bash
cd $REPO/taskgen/v2 && $P -m pytest -q  2>&1 | tail -n 3
```
Expected：`187 passed`。

- [ ] **Step 6: commit**

```bash
cd $REPO
git add taskgen/v2/taskgen_v2/check.py \
        taskgen/v2/taskgen_v2/prompt.py \
        taskgen/v2/tests/test_taskgen_check.py \
        taskgen/v2/tests/test_taskgen_prompt.py
git diff --cached --name-only
git commit -m "feat(taskgen v2): archives copy in one statement; two SQLite-numbered copies of one table are rejected

The one bad task the verifier passed in plan 4 copied two rows with two INSERT ... SELECTs: SQLite numbers the
copies in statement order, and an agent copying both in one statement numbers them in table order, so the gold
state hung on the order of two statements. The check now rejects a second INSERT ... SELECT into a table whose
copies SQLite numbers (archive_split); SQL that states the copies' keys is fine. The prompt asks for one
statement. A batch over a group of two rows now always takes both: 'by a condition' read 'between 2 and 1 rows'.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```
Expected：暂存区只有这 4 个文件。

---

### Task 3: 全量前要修的小问题：复数词尾、双引号的 `"now"`、`lookup` 和主键、缺校验模型、统计里的失败调用

**Files:**
- Modify: `taskgen/v2/taskgen_v2/check.py`（`_contains`：复数词尾只给 3 个字母以上的词；`NONDET`、`at_instant`：双引号的 `"now"` 也算读时钟）
- Modify: `taskgen/v2/taskgen_v2/trees.py`（`lookup` 不用等于主键的名字列）
- Modify: `taskgen/v2/taskgen_v2/verify.py`（`models_from_env` 两个模型变量都没有时报错）
- Modify: `taskgen/v2/taskgen_v2/stats.py`（`unanimous_share` 不算失败调用）
- Modify: `taskgen/v2/scripts/verify_calibrate.py`（`review --votes` 默认 `verify.DEFAULT_VOTES`）
- Test: `taskgen/v2/tests/test_taskgen_check.py`、`test_taskgen_trees.py`、`test_taskgen_verify.py`、`test_taskgen_stats.py`

**Interfaces:**
- Consumes: Task 1 的 `verify.DEFAULT_VOTES`。
- Produces: 无新接口。`verify.models_from_env()` 在 `TASKGEN_VERIFY_MODELS` 和 `TASKGEN_VERIFY_MODEL` 都没设、也没传 spec 时抛 `llm.LLMError`。

- [ ] **Step 1: 写失败的测试**

`tests/test_taskgen_check.py` 末尾加：

```python
def test_only_a_word_of_three_letters_or_more_takes_a_plural_ending():
    # 'M' matched "Ms" and let a gender value no one asked for pass; "cups" for 'cup' and "10g" for 'g' still match
    assert not check._contains("ms lee asked for it", "m") and not check._contains("fix its row", "it")
    assert check._contains("add 2 cups of rice", "cup") and check._contains("add 10g of salt", "g")
```

`tests/test_taskgen_check.py` 末尾加：

```python
def test_a_double_quoted_now_reads_the_clock(rental):
    # SQLite reads "now" as the string 'now' when no column has that name, so datetime("now") is the current time
    r = check.run_check(rental, cand("I am a5 b5. Mark my rental 5 as returned right now.",
                                     ['UPDATE rental SET return_date = datetime("now") WHERE rental_id = 5']))
    assert r["reasons"] == ["nondeterministic: rental"]
    assert check.at_instant("UPDATE r SET d = datetime(\"NOW\", 'localtime')", "2000-01-01 13:37:42") == (
        "UPDATE r SET d = datetime('2000-01-01 13:37:42', 'localtime')")
```

`tests/test_taskgen_trees.py` 末尾加：

```python
def test_lookup_skips_a_name_column_that_is_the_key(tmp_path):
    # student_loan's person table is just the name, which is the key: "find me by my name" found the key by the key
    conn = sqlite3.connect(make_db(tmp_path, "loans", "CREATE TABLE person (name TEXT PRIMARY KEY); INSERT INTO person VALUES ('student1');"))
    assert trees.lookup(conn, "person", {"key": "name", "name_cols": ["name"]}, {"name": "student1"}) == {}
```

`tests/test_taskgen_verify.py` 末尾加：

```python
def test_models_from_env_needs_a_model(monkeypatch):
    monkeypatch.setattr(verify.io, "load_dotenv", lambda *a, **k: None)
    for k in ("TASKGEN_VERIFY_MODELS", "TASKGEN_VERIFY_MODEL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("TASKGEN_VERIFY_BASE_URL", "https://v/1"); monkeypatch.setenv("TASKGEN_VERIFY_API_KEY", "k")
    with pytest.raises(verify.llm.LLMError, match="TASKGEN_VERIFY_MODEL"):
        verify.models_from_env()
```

`tests/test_taskgen_stats.py` 末尾加：

```python
def test_failed_calls_are_not_votes_in_the_agreement_numbers():
    cands, checks = [c(0)[0]], [c(0)[1]]
    verifies = [{"id": "x:0", "votes": [{"verdict": "yes"}, {"verdict": "error", "error": "HTTP 503"}, {"verdict": "yes"}], "pass": True}]
    assert stats.summarize(cands, checks, verifies, [])["unanimous_share"] == 1.0
```

- [ ] **Step 2: 跑测试，确认失败**

```bash
cd $REPO/taskgen/v2 && $P -m pytest -q tests/test_taskgen_check.py tests/test_taskgen_trees.py tests/test_taskgen_verify.py tests/test_taskgen_stats.py 2>&1 | tail -n 3
```
Expected：`5 failed, 84 passed`。失败的是：
- `test_only_a_word_of_three_letters_or_more_takes_a_plural_ending`
- `test_a_double_quoted_now_reads_the_clock`
- `test_lookup_skips_a_name_column_that_is_the_key`
- `test_models_from_env_needs_a_model`
- `test_failed_calls_are_not_votes_in_the_agreement_numbers`

- [ ] **Step 3: 实现**

`taskgen_v2/check.py` 里把

```python
    """n occurs in text as a whole token: '203' is not in '2030', 'ann' is not in 'joanna'. A word may take a plural
    ending ('cup' in '2 cups') and a unit may follow a number ('g' in '10g'), as in DySQL's cookbook gold."""
```

换成：

```python
    """n occurs in text as a whole token: '203' is not in '2030', 'ann' is not in 'joanna'. A word of three letters
    or more may take a plural ending ('cup' in '2 cups'; 'M' is not in 'Ms') and a unit may follow a number ('g' in
    '10g'), as in DySQL's cookbook gold."""
```

`taskgen_v2/check.py` 里把

```python
    after = r"(?:e?s)?(?!\w)" if n[-1:].isalpha() else r"(?!\w)"
```

换成：

```python
    after = r"(?:e?s)?(?!\w)" if n[-1:].isalpha() and len(n) >= 3 else r"(?!\w)"
```

`taskgen_v2/check.py` 里把

```python
# without a time value read the clock too: date(), datetime(), julianday(), strftime('%H:%M')
NONDET = re.compile(r"(?i)\bcurrent_(?:timestamp|time|date)\b|'now'|\brandom(?:blob)?\s*\(|\bunixepoch\s*\(|"
```

换成：

```python
# without a time value read the clock too: date(), datetime(), julianday(), strftime('%H:%M'); so does "now", which
# SQLite reads as the string 'now' when no column has that name
NONDET = re.compile(r"(?i)\bcurrent_(?:timestamp|time|date)\b|'now'|\"now\"|\brandom(?:blob)?\s*\(|\bunixepoch\s*\(|"
```

`taskgen_v2/check.py` 里把

```python
    """The statement with every clock reading replaced by a fixed instant: 'now', CURRENT_TIMESTAMP/DATE/TIME, and
    date functions called without a time value. A column default that reads the clock is not replaced; none of the
```

换成：

```python
    """The statement with every clock reading replaced by a fixed instant: 'now' or "now", CURRENT_TIMESTAMP/DATE/TIME,
    and date functions called without a time value. A column default that reads the clock is not replaced; none of the
```

`taskgen_v2/check.py` 里把

```python
    s = re.sub(r"(?i)'now'", f"'{instant}'", s)
```

换成：

```python
    s = re.sub(r"(?i)'now'|\"now\"", f"'{instant}'", s)
```

`taskgen_v2/trees.py` 里把

```python
    names = {c: row[c] for c in person["name_cols"] if row.get(c) not in (None, "")}
```

换成：

```python
    names = {c: row[c] for c in person["name_cols"] if row.get(c) not in (None, "") and c != person["key"]}   # student_loan: name is the key
```

`taskgen_v2/verify.py` 里把

```python
    io.load_dotenv()
    spec = spec or os.environ.get("TASKGEN_VERIFY_MODELS") or f"{os.environ.get('TASKGEN_VERIFY_MODEL', '')}:{DEFAULT_VOTES}"
```

换成：

```python
    io.load_dotenv()
    if not (spec or os.environ.get("TASKGEN_VERIFY_MODELS") or os.environ.get("TASKGEN_VERIFY_MODEL")):
        raise llm.LLMError("missing env TASKGEN_VERIFY_MODELS or TASKGEN_VERIFY_MODEL (see .env)")
    spec = spec or os.environ.get("TASKGEN_VERIFY_MODELS") or f"{os.environ['TASKGEN_VERIFY_MODEL']}:{DEFAULT_VOTES}"
```

`taskgen_v2/stats.py` 里把

```python
    d["unanimous_share"] = (sum(len({x["verdict"] for x in v["votes"]}) == 1 for v in verifies) / len(verifies)) if verifies else None
```

换成：

```python
    d["unanimous_share"] = (sum(len({x["verdict"] for x in v["votes"] if "error" not in x}) == 1 for v in verifies)
                            / len(verifies)) if verifies else None   # a failed call is not a vote
```

`scripts/verify_calibrate.py` 里把

```python
            p.add_argument("--votes", type=int, default=3, help="the rule the disagreements are judged by (calibrate.RULES)")
```

换成：

```python
            p.add_argument("--votes", type=int, default=verify.DEFAULT_VOTES, help="the rule the disagreements are judged by (calibrate.RULES)")
```

- [ ] **Step 4: 跑测试，确认通过**

```bash
cd $REPO/taskgen/v2 && $P -m pytest -q tests/test_taskgen_check.py tests/test_taskgen_trees.py tests/test_taskgen_verify.py tests/test_taskgen_stats.py 2>&1 | tail -n 3
```
Expected：`89 passed`。

- [ ] **Step 5: 跑全套**

```bash
cd $REPO/taskgen/v2 && $P -m pytest -q  2>&1 | tail -n 3
```
Expected：`192 passed`。

- [ ] **Step 6: 执行检查重新校准（Task 2、3 都改了检查）**

在 Task 1 开始前那个 commit 上和现在各跑一遍 DySQL 金标准和 v1 全部候选，逐条比判决。

```bash
cat > $S/verdicts.py <<'EOF'
# every verdict of the check in the current directory's taskgen_v2 (run from a taskgen/v2 folder): DySQL's gold
# tasks and v1's candidates, one JSON line each -- {"id", "ok", "reasons", "type"}; ids and labels only, no task text
import glob, json, os, sys
sys.path[:0] = [".", "../common"]
from taskgen_v2 import check, dysql, io

out, v1 = sys.argv[1], sys.argv[2]
recs = {v["db"]: v for v in io.load_db_recs().values()}
with open(out, "w", encoding="utf-8") as f:
    for env in dysql.ENVS:
        rec = dysql.db_rec(env)
        for c in dysql.candidates(env):
            r = check.run_check_safe(rec, c)
            f.write(json.dumps({"id": c["id"], "ok": r["ok"], "reasons": r["reasons"], "type": r["task_type"]}) + "\n")
    for p in sorted(glob.glob(os.path.join(v1, "*", "candidates.jsonl"))):
        rec = recs[os.path.basename(os.path.dirname(p))]
        for c in io.read_jsonl(p):
            r = check.run_check_safe(rec, c)
            f.write(json.dumps({"id": c["id"], "ok": r["ok"], "reasons": r["reasons"], "type": r["task_type"]}) + "\n")
EOF
cat > $S/compare_verdicts.py <<'EOF'
# two verdict dumps of verdicts.py, before and after a check change: pass counts per set, then every candidate whose
# verdict, reasons or type changed, with the reasons that went away and came in (ids and reasons only, no task text)
import json, sys

before = {r["id"]: r for r in map(json.loads, open(sys.argv[1], encoding="utf-8"))}
after = {r["id"]: r for r in map(json.loads, open(sys.argv[2], encoding="utf-8"))}
assert set(before) == set(after), "the two dumps cover different candidates"
for name, pick in (("DySQL gold", lambda i: i.startswith("dysql:")), ("v1 candidates", lambda i: not i.startswith("dysql:"))):
    ids = [i for i in before if pick(i)]
    print(f"{name}: {len(ids)} checked, passed {sum(before[i]['ok'] for i in ids)} -> {sum(after[i]['ok'] for i in ids)}")
changed = [i for i in before if (before[i]["ok"], before[i]["reasons"], before[i]["type"]) != (after[i]["ok"], after[i]["reasons"], after[i]["type"])]
print(f"changed: {len(changed)}")
for i in changed:
    b, a = before[i], after[i]
    gone = [x[:80] for x in b["reasons"] if x not in a["reasons"]]
    new = [x[:80] for x in a["reasons"] if x not in b["reasons"]]
    print(f"- {i}: ok {b['ok']} -> {a['ok']}, type {b['type']} -> {a['type']}; gone {gone}; new {new}")
EOF
cd $REPO && BASE=$(git log --format=%h --grep="plan 5, the pilot and the full run" -n 1) && rm -rf $S/before && mkdir -p $S/before && git archive $BASE taskgen/v2 taskgen/common | tar -x -C $S/before && ln -sfn $REPO/DySQL-Bench $S/before/DySQL-Bench && ln -sfn $REPO/taskgen/v1 $S/before/taskgen/v1
(cd $S/before/taskgen/v2 && $P $S/verdicts.py $S/verdicts_before.jsonl ../v1/results) &
(cd $REPO/taskgen/v2 && $P $S/verdicts.py $S/verdicts_after.jsonl ../v1/results); wait
cd $REPO/taskgen/v2 && $P $S/compare_verdicts.py $S/verdicts_before.jsonl $S/verdicts_after.jsonl
```
Expected（约 10 分钟）：
```
DySQL gold: 1062 checked, passed 895 -> 894
v1 candidates: 4159 checked, passed 3872 -> 3872
changed: 1
- dysql:chinook:13: ok True -> False, type 1_self -> 1_self; gone []; new ['archive_split: invoice_items']
```
（`$S/before` 用的是本计划文档那个 commit，即 Task 1 之前的代码。）

- [ ] **Step 7: commit**

```bash
cd $REPO
git add taskgen/v2/taskgen_v2/check.py \
        taskgen/v2/taskgen_v2/trees.py \
        taskgen/v2/taskgen_v2/verify.py \
        taskgen/v2/taskgen_v2/stats.py \
        taskgen/v2/scripts/verify_calibrate.py \
        taskgen/v2/tests/test_taskgen_check.py \
        taskgen/v2/tests/test_taskgen_trees.py \
        taskgen/v2/tests/test_taskgen_verify.py \
        taskgen/v2/tests/test_taskgen_stats.py
git diff --cached --name-only
git commit -m "fix(taskgen v2): small fixes before the full run

Only a word of three letters or more takes a plural ending in the literal rule: 'M' matched 'Ms' and let a value
nobody asked for pass (recalibrated: no verdict changes). lookup no longer uses a name column that is the key
(student_loan found the key by the key, a subquery in name only). models_from_env fails when no verifier model
is configured instead of asking a model named ':3'. unanimous_share no longer counts failed calls. review's
default vote rule follows DEFAULT_VOTES. datetime("now") with double quotes reads the clock too (SQLite takes
"now" for the string when no column has that name): the check reruns it at two instants instead of letting it
pass (no DySQL gold and no v1 candidate writes it, so no verdict changes).

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```
Expected：暂存区只有这 9 个文件。

---

### Task 4: 去重：近重复过滤，和抽检排除的题

**Files:**
- Modify: `taskgen/v2/taskgen_v2/dedup.py`（新函数 `near_duplicates`、`_shingles`；`import re`）
- Modify: `taskgen/v2/scripts/taskgen.py`（`merged` 跳过 `excluded.jsonl` 里的 id；`dedup` 先做近重复过滤再封顶）
- Test: `taskgen/v2/tests/test_taskgen_dedup.py`、`taskgen/v2/tests/test_taskgen_cli.py`

**Interfaces:**
- Consumes: 无。
- Produces:
  - `dedup.near_duplicates(records, threshold=0.6) -> list`：按原顺序保留，与已保留的某条 instruction 的词级 3-gram Jaccard ≥ threshold 的去掉。
  - `results/<db>/excluded.jsonl`：一行 `{"id", "reason", "by"}`，`taskgen.py dedup` 跳过这些 id。Task 7 的抽检写这个文件。

- [ ] **Step 1: 写失败的测试**

`tests/test_taskgen_dedup.py` 末尾加：

```python
def test_near_duplicate_instructions_keep_only_the_first():
    # design 4.7: within a database, instructions whose word 3-grams overlap by Jaccard >= 0.6 are one task
    base = "Hi, I am a5 b5, customer 5. Please set the quantity of my order 5 to 3 and leave everything else as it is."
    recs = [{"id": "x:0", "instruction": base},
            {"id": "x:1", "instruction": base.replace("to 3", "to 4")},            # one word apart: a near duplicate
            {"id": "x:2", "instruction": "It's a6 b6 (customer 6). Cancel order 66, the shipment never arrived."}]
    assert [r["id"] for r in dedup.near_duplicates(recs)] == ["x:0", "x:2"]
    assert len(dedup.near_duplicates(recs, threshold=1.01)) == 3
```

`tests/test_taskgen_cli.py` 末尾加：

```python
def test_dedup_leaves_out_the_tasks_a_review_excluded(tmp_path):
    # the full run's spot check (30 tasks a database) marks bad tasks in excluded.jsonl; convert then drops them
    args = setup(tmp_path)
    out = tmp_path / "res"
    run("trees", *args, "--n", "3", "--seed", "0")
    rows = [{"id": "test:shop2:customers:%s:0" % t["key_value"], "db": "shop2", "source": "test", "anchor_table": "customers",
             "anchor_key": "customer_id", "key_value": t["key_value"], "anchor_name": t["anchor_name"],
             "profile_version": t["profile_version"], "plan": {"task_type": "1_self", "difficulty": "easy"},
             "instruction": f"I am {t['anchor_name']}. Set qty of my order {t['events'][0]['rows'][0]['row']['order_id']} to 3.",
             "actions": [{"sql": f"UPDATE orders SET qty = 3 WHERE order_id = {t['events'][0]['rows'][0]['row']['order_id']}"}],
             "error": None} for t in io.read_jsonl(out / "trees.jsonl")]
    io.append_jsonl(out / "candidates.jsonl", rows)
    run("check", *args)
    io.append_jsonl(out / "verify.jsonl", [{"id": r["id"], "votes": [{"verdict": "yes", "model": "m"}] * 2, "pass": True,
                                            "unvoted": False, "verify_model": "m"} for r in rows])
    io.append_jsonl(out / "excluded.jsonl", [{"id": rows[0]["id"], "reason": "unclear", "by": "claude"}])
    run("dedup", *args)
    assert sorted(r["id"] for r in io.read_jsonl(out / "selected.jsonl")) == sorted(r["id"] for r in rows[1:])
```

- [ ] **Step 2: 跑测试，确认失败**

```bash
cd $REPO/taskgen/v2 && $P -m pytest -q tests/test_taskgen_dedup.py tests/test_taskgen_cli.py 2>&1 | tail -n 3
```
Expected：`2 failed, 12 passed`。失败的是：
- `test_near_duplicate_instructions_keep_only_the_first`
- `test_dedup_leaves_out_the_tasks_a_review_excluded`

- [ ] **Step 3: 实现**

`taskgen_v2/dedup.py` 里把

```python
from collections import Counter
```

换成：

```python
import re
from collections import Counter
```

`taskgen_v2/dedup.py` 末尾加：

```python
def _shingles(text):
    w = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {tuple(w[i:i + 3]) for i in range(len(w) - 2)}


def near_duplicates(records, threshold=0.6):
    """The records whose instruction is not a near duplicate of an earlier kept one (design §4.7): word 3-gram
    Jaccard >= threshold within the database. In plans 3 and 4 no two instructions of a database came above 0.11."""
    kept, seen = [], []
    for r in records:
        s = _shingles(r["instruction"])
        if not any(s and k and len(s & k) / len(s | k) >= threshold for k in seen):
            kept.append(r); seen.append(s)
    return kept
```

`scripts/taskgen.py` 里把

```python
def merged(out):
    chk = {r["id"]: r for r in io.read_jsonl(f"{out}/check.jsonl")}
    ver = {r["id"]: r for r in io.read_jsonl(f"{out}/verify.jsonl")}
    rows = []
    for c in io.read_jsonl(f"{out}/candidates.jsonl"):
        k, v = chk.get(c["id"]), ver.get(c["id"])
        if k and k["ok"] and v and v["pass"]:
            rows.append({**c, "task_type": k["task_type"], "template": k["template"], "difficulty": k["difficulty"],
```

换成：

```python
def merged(out):
    """Candidates that passed the check and the verifier, minus those a spot check excluded (excluded.jsonl:
    {"id", "reason", "by"} per line)."""
    chk = {r["id"]: r for r in io.read_jsonl(f"{out}/check.jsonl")}
    ver = {r["id"]: r for r in io.read_jsonl(f"{out}/verify.jsonl")}
    excluded = {r["id"] for r in io.read_jsonl(f"{out}/excluded.jsonl")}
    rows = []
    for c in io.read_jsonl(f"{out}/candidates.jsonl"):
        k, v = chk.get(c["id"]), ver.get(c["id"])
        if k and k["ok"] and v and v["pass"] and c["id"] not in excluded:
            rows.append({**c, "task_type": k["task_type"], "template": k["template"], "difficulty": k["difficulty"],
```

`scripts/taskgen.py` 里把

```python
    sel = dedup.select(merged(out), random.Random(a.seed), a.per_person, a.per_template, a.per_db)
```

换成：

```python
    sel = dedup.select(dedup.near_duplicates(merged(out)), random.Random(a.seed), a.per_person, a.per_template, a.per_db)
```

- [ ] **Step 4: 跑测试，确认通过**

```bash
cd $REPO/taskgen/v2 && $P -m pytest -q tests/test_taskgen_dedup.py tests/test_taskgen_cli.py 2>&1 | tail -n 3
```
Expected：`14 passed`。

- [ ] **Step 5: 跑全套**

```bash
cd $REPO/taskgen/v2 && $P -m pytest -q  2>&1 | tail -n 3
```
Expected：`194 passed`。

- [ ] **Step 6: commit**

```bash
cd $REPO
git add taskgen/v2/taskgen_v2/dedup.py \
        taskgen/v2/scripts/taskgen.py \
        taskgen/v2/tests/test_taskgen_dedup.py \
        taskgen/v2/tests/test_taskgen_cli.py
git diff --cached --name-only
git commit -m "feat(taskgen v2): near-duplicate instructions are one task; a spot check can exclude tasks

dedup drops an instruction whose word 3-grams overlap an earlier kept one of the database by Jaccard >= 0.6
(design 4.7) before the caps; in plans 3 and 4 no two instructions of a database came above 0.11, so this is a
backstop. Tasks a spot check marks in results/<db>/excluded.jsonl are left out of dedup and so of the output.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```
Expected：暂存区只有这 4 个文件。

---

### Task 5: 阶段 H 试点，并进全量：23 个库出题和检查，beer_factory 先校验，Qwen3-4B 关卡

试点不另出题：先把 23 个库的出题和检查做完（只花 GLM），再只校验 beer_factory，转换后让 Qwen3-4B 随机跑其中 60 条当关卡。beer_factory 的票全量本来就要投，所以试点不多花 ollama；关卡挡在其余 22 个库的约 6,600 票前面。

**Files:**
- Create: `taskgen/v2/docs/<执行当天的日期>-pilot.md`（试点记录，例如 `2026-10-02-pilot.md`）
- 本地，不进 git：`taskgen/v2/results/<db>/`（23 个库）、`taskgen/v2/output/beer_factory/`、`taskgen/v2/output/manifest.json`、`DySQL-Bench/results/taskgen_v2/pilot/agent_4b/`

**Interfaces:**
- Consumes: Task 1–4 的全部改动；GB10 上 :8001（`qwen2.5-72b-awq`）和 :8002（`qwen3-4b`）。
- Produces: 23 个库的候选和检查结果；beer_factory 的校验、产出和 manifest 条目；试点记录。关卡过了才进 Task 6。

- [ ] **Step 1: 建树（23 个库，各最多 200 棵）**

```bash
cd $REPO/taskgen/v2
for DB in $($P -c "import json; print(' '.join(json.load(open('data/db_profiles.json'))))"); do
  $P scripts/taskgen.py trees --db $DB --n 200 --seed 0 || echo "FAILED $DB"
done 2>&1 | tee $S/full_trees.log | grep -c FAILED
cat results/*/trees.jsonl | wc -l
```
Expected：`0` 个失败；一共约 3,556 棵（计划 2 用同样的参数是 3,556 棵）。8 个小库不到 200：book_publishing_company 23、student_club 33、school_scheduling 46、regional_sales 50、food_inspection_2 75、shipping 100、hr_1 107、car_retails 122。

- [ ] **Step 2: 出题和检查（GLM，约 8–9 小时，放后台）**

```bash
cd $REPO/taskgen/v2
run() { $P scripts/taskgen.py generate --db $1 --workers 5 && \
        $P scripts/taskgen.py generate --db $1 --workers 5 --retry-errors && \
        $P scripts/taskgen.py check --db $1; }
{ for DB in $($P -c "import json; print(' '.join(json.load(open('data/db_profiles.json'))))"); do run $DB; done; } > $S/full_generate.log 2>&1
grep -E "^checked" $S/full_generate.log | awk '{n += $2; p += $4} END {print n, p}'
```
Expected：约 3,556 条候选，过检查约 92% 以上（计划 3 是 98.8%）。中途被打断，照原命令再跑，每一步都按 id 续跑。

- [ ] **Step 3: 检查阶段的统计（不花 ollama）**

```bash
cd $REPO/taskgen/v2 && $P -c "
import glob, json
from collections import Counter
n = ok = 0; c = Counter()
for f in glob.glob('results/*/check.jsonl'):
    for l in open(f):
        r = json.loads(l); n += 1; ok += r['ok']
        c.update({x.split(':')[0] for x in r['reasons']})
print(n, 'checked,', ok, 'passed'); print(c.most_common())"
$P scripts/task_stats.py --set full=results --out $S/check_stats.md && cat $S/check_stats.md
```
Expected：
- 过检查 ≥92%。各拒绝原因的计数里，`archive_split` 和 `archive_copy_changed` 都不多（计划 3、4 的 480 条候选里合计 1 条）。
- `$S/check_stats.md` 的指标和写计划时 475 条样本的对照（写语句数均值约 1.96、≥3 条约 20%、词数均值约 54、两张表约 59%、类型约 50/14/6/30）同量级。
- 过检查低于 92%，或者某一个原因超过候选的 3%：停下来告诉用户，先不校验。

- [ ] **Step 4: 校验 beer_factory（3 票多数，约 400 票）**

```bash
cd $REPO/taskgen/v2 && $P scripts/taskgen.py verify --db bird:beer_factory --workers 3; echo "exit $?"
```
Expected：
- 打印的字典里 `paused` 是 `False`，`exit 0`，`verified` 等于预封顶后的条数（不超过 beer_factory 过检查的条数）。
- `unvoted` 不为 0 时，照原命令再跑一次，只补缺的票。
- 退出码是 3（暂停）时：停下来告诉用户额度可能用完，等用户回复再续跑。

- [ ] **Step 5: 第一票和最终结论**

```bash
cd $REPO/taskgen/v2 && $P -c "
import json
from collections import Counter
c = Counter(); diff = []
for l in open('results/beer_factory/verify.jsonl'):
    r = json.loads(l)
    real = [v for v in r['votes'] if 'error' not in v]
    if not real or r.get('unvoted'):
        c['unvoted'] += 1; continue
    first = real[0]['verdict'] == 'yes'
    c[(first, r['pass'])] += 1
    if first != r['pass']:
        diff.append(r['id'])
print(dict(c)); print('first vote != final:', diff)"
```
Expected：`(True, True)` 占绝大多数（计划 4 两票一致 118/119），第一票和最终结论不同的只有几条。逐条读这几条（`results/beer_factory/candidates.jsonl` 里的 instruction 和 SQL），判断哪边对，只把计数和 id 写进试点记录。

- [ ] **Step 6: beer_factory 去重、封顶、转换**

```bash
cd $REPO/taskgen/v2
$P scripts/taskgen.py dedup --db bird:beer_factory
$P scripts/taskgen.py convert --db bird:beer_factory
$P scripts/taskgen.py stats --db bird:beer_factory
```
Expected：`selected N`、`wrote N tasks`，N 约等于校验通过数（一棵树一个人一题，每人上限 2、每模板 15 基本碰不到）。`stats` 的表里 `n_verify_unvoted` 是 0。产出写在全量的位置（`output/beer_factory/tasks.jsonl`、`output/manifest.json`），Task 6 不用重做这个库。

- [ ] **Step 7: Qwen3-4B 关卡：随机 60 条（GB10，约 35 分钟）**

```bash
for p in 8001 8002; do curl -s -m 5 http://127.0.0.1:$p/v1/models; echo; done
IDS=$($P -c "
import random
n = sum(1 for _ in open('$REPO/taskgen/v2/output/beer_factory/tasks.jsonl'))
print(' '.join(map(str, sorted(random.Random(0).sample(range(n), min(60, n))))))")
cd $REPO/DySQL-Bench && OUT=results/taskgen_v2/pilot/agent_4b && mkdir -p $OUT && echo "$IDS" > $OUT/task_ids.txt
TASKGEN_MANIFEST=$REPO/taskgen/v2/output/manifest.json $P run.py --env gen:beer_factory --task-split train --num-trials 1 \
  --task-ids $IDS \
  --model qwen3-4b --model-api http://127.0.0.1:8002 \
  --user-model qwen2.5-72b-awq --user-model-api http://127.0.0.1:8001 \
  --user-strategy llm --max-concurrency 8 --log-dir $OUT 2>&1 | tee $OUT/run.log | tail -n 3
$P scripts/summarize.py "$OUT/*.json" | tee $OUT/summary.md
```
Expected：
- 两个 `/v1/models` 分别列出 `qwen2.5-72b-awq` 和 `qwen3-4b`；不在的话按 Global Constraints 起服务。
- 60 条（beer_factory 不足 60 条就全跑）都跑完，`summary.md` 有 overall 一行，通过率在 20–50% 之间。v1 试点是 23.2%，4B 在 DySQL 上是 29.8%；60 条的误差约 ±12 个百分点。
- 低于 20%：先看 `summary.md` 的 `sql err` 和 `0-row write` 列，再抽 10 条失败轨迹，分清是 instruction 缺信息（回到出题 prompt），还是 agent 本身弱（正常）。
- 高于 50%：题偏简单，记下来，和用户商量要不要调形状比例再出题。
- 这两种情况都停下来告诉用户，不直接进 Task 6。

- [ ] **Step 8: 试点记录**

写 `docs/<当天日期>-pilot.md`，中文，只写计数和 id：
1. **做法**：试点并进全量；为什么这样做（不多花 ollama，关卡挡在其余 22 个库前面）。
2. **出题和检查**：23 个库的树、候选、过检查的条数，Step 3 的拒绝原因计数和 `$S/check_stats.md` 的表。
3. **beer_factory 校验**：校验了几条、通过几条、没投上票几条、平均每条几票；第一票和最终结论不同的 id，以及哪边对。
4. **Qwen3-4B**：60 条的通过率（附 `task_ids.txt` 的来源：`random.Random(0)`），按难度和类型拆开（用 `summary.md` 和任务 meta），对照 v1 试点的 23.2% 和 DySQL 的 29.8%。
5. **结论**：能不能继续校验其余 22 个库；有问题就写清楚问题和建议。

```bash
cd $REPO && git add taskgen/v2/docs/*-pilot.md && git diff --cached --name-only
git commit -m "docs(taskgen v2): stage H pilot folded into the full run

All 23 databases generated and checked first; beer_factory verified with three-vote majority and converted,
then Qwen3-4B on 60 of its tasks as the gate before the other databases are verified; counts and pass rates
only.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```
Expected：暂存区只有试点记录这 1 个文件。

---

### Task 6: 阶段 I 全量：其余 22 个库校验、23 个库转换

**Files:**
- 本地，不进 git：`taskgen/v2/results/<db>/`（23 个库）、`taskgen/v2/output/<db>/tasks.jsonl`、`taskgen/v2/output/manifest.json`

**Interfaces:**
- Consumes: Task 1–5；Task 5 的关卡结论是"可以继续"。
- Produces: 23 个库的训练任务和 manifest，交给 Task 7 抽检。本任务不改代码，没有 commit。

- [ ] **Step 1: 校验其余 22 个库（3 票多数，约 6,600 票、约 6.5 小时，放后台）**

```bash
cd $REPO/taskgen/v2 && $P scripts/taskgen.py verify --db bird:beer_factory --all-dbs --workers 3 > $S/full_verify.log 2>&1; echo "exit $?"
tail -n 25 $S/full_verify.log
```
Expected：
- 每个库一行：`verified`、`passed`、`skipped`、`unvoted`、`paused`。beer_factory 那一行 `verified` 是 0、`skipped` 等于 Task 5 Step 4 校验的条数（已定下的不再投）。
- 退出码 3：额度用完。停下来告诉用户，等用户回复（可能是申请了更大的套餐）再用同一条命令续跑，已投的票都在。
- 全部库跑完后，`unvoted` 不为 0 的话再跑一次，只补缺的票。

- [ ] **Step 2: 去重、封顶、转换（23 个库）**

```bash
cd $REPO/taskgen/v2
for DB in $($P -c "import json; print(' '.join(json.load(open('data/db_profiles.json'))))"); do
  $P scripts/taskgen.py dedup --db $DB && $P scripts/taskgen.py convert --db $DB || echo "FAILED $DB"
done 2>&1 | tee $S/full_convert.log | grep -E "FAILED|wrote" | awk '{n += $2} /FAILED/ {print} END {print "tasks", n}'
$P -c "import json; m = json.load(open('output/manifest.json')); print(len(m), 'databases in the manifest')"
```
Expected：没有 `FAILED`；manifest 里 23 个库；任务总数约 2,300–2,700（设计 §5 的估计）。beer_factory 重跑一遍得到和 Task 5 一样的产出（同一个 seed、同样的校验结果）。

- [ ] **Step 3: 能被评测加载，统计**

```bash
cd $REPO/DySQL-Bench && TASKGEN_MANIFEST=$REPO/taskgen/v2/output/manifest.json $P -c "
import json
from dysql_bench.envs import get_env
m = json.load(open('$REPO/taskgen/v2/output/manifest.json'))
n = {db: len(get_env('gen:' + db, user_strategy='human', user_model=None, user_model_api=None, task_split='train').tasks) for db in m}
print(sum(n.values()), 'tasks;', n)"
cat > $S/final_stats.py <<'EOF'
# the selected tasks (after verify, near-duplicate filter and caps) of every database under a results root, on the
# design 3 metrics next to DySQL (the cached column), plus per-database counts; ids and numbers only
import glob, os, sys
sys.path[:0] = [".", "../common"]
from taskgen_v2 import io, metrics
root = sys.argv[1]
recs, rows = [], []
for d in sorted(glob.glob(os.path.join(root, "*"))):
    if not os.path.exists(os.path.join(d, "check.jsonl")):
        continue
    n = lambda f: sum(1 for _ in io.read_jsonl(os.path.join(d, f)))
    ver = io.read_jsonl(os.path.join(d, "verify.jsonl"))
    sel = io.read_jsonl(os.path.join(d, "selected.jsonl"))
    rows.append((os.path.basename(d), n("trees.jsonl"), n("candidates.jsonl"), sum(r["ok"] for r in io.read_jsonl(os.path.join(d, "check.jsonl"))),
                 len(ver), sum(v["pass"] for v in ver), sum(v.get("unvoted", False) for v in ver),
                 sum(len([x for x in v["votes"] if "error" not in x]) for v in ver), len(sel)))
    recs += [{"db": os.path.basename(d), "instruction": r["instruction"], "actions": r["actions"], "type": r["task_type"],
              "difficulty": r["difficulty"], "writes": r["writes"], "template": r["template"]} for r in sel]
print("| 库 | 树 | 候选 | 过检查 | 校验了 | 校验通过 | 没投上票 | 票数 | 留下 |")
print("|---|---|---|---|---|---|---|---|---|")
for r in rows:
    print("| " + " | ".join(map(str, r)) + " |")
t = [sum(r[i] for r in rows) for i in range(1, 9)]
print("| 合计 | " + " | ".join(map(str, t)) + " |")
print(f"\n每条校验平均 {t[6] / max(1, t[3]):.2f} 票\n")
print(metrics.render({"DySQL": metrics.compute(metrics.from_dysql(os.path.join(io.RESULTS, "dysql_metrics.jsonl"))),
                      "final": metrics.compute(recs)}))
EOF
cd $REPO/taskgen/v2 && $P $S/final_stats.py results | tee $S/full_stats.md
```
Expected：
- 23 个库都能用 `gen:<db>` 加载，任务数和 Step 2 一致。
- `$S/full_stats.md` 有每个库的漏斗，以及最终任务对照 DySQL 的指标；每条校验平均约 2.05 票。

---

### Task 7: 抽检、写全量记录、设计写回

**Files:**
- Create: `taskgen/v2/docs/<执行当天的日期>-full-run.md`（全量记录）
- Modify: `taskgen/v2/docs/2026-10-01-taskgen-v2-design.md`（写回本计划的规则）
- Modify: `taskgen/v2/README.md`（改动记录）
- 本地，不进 git：`$S/spot/`（抽检表和标注）、`taskgen/v2/results/<db>/excluded.jsonl`

**Interfaces:**
- Consumes: Task 6 的产出；Task 4 的 `excluded.jsonl` 机制；`scripts/verify_calibrate.py` 的 `block`（标注表的格式）和 `calibrate.Databases`。
- Produces: 抽检后的最终产出；全量记录。

- [ ] **Step 1: 抽样，分成 5 份标注表**

```bash
cd $REPO/taskgen/v2 && mkdir -p $S/spot && $P -c "
import glob, os, random, sys
sys.path[:0] = ['.', '../common', 'scripts']
from taskgen_v2 import calibrate, io
import verify_calibrate as vc
dbs = calibrate.Databases()
items = []
for f in sorted(glob.glob('results/*/selected.jsonl')):
    sel = io.read_jsonl(f)
    pick = random.Random(0).sample(sel, min(30, len(sel)))
    items += [{**r, 'db': r['id'].rsplit(':', 3)[0]} for r in pick]
for b in range(5):
    part = items[b::5]
    lines = ['# 抽检第 %d 份：%d 条' % (b + 1, len(part)), '']
    for n, i in enumerate(part, 1):
        lines += vc.block(i, dbs, n) + ['']
    open(os.path.join('$S/spot', 'sheet_%d.md' % (b + 1)), 'w').write('\n'.join(lines) + '\n')
print(len(items), 'tasks in 5 sheets')"
```
Expected：约 690 条（小库不足 30 条的全看），分进 5 份表。

- [ ] **Step 2: 5 个子代理并行标注**

用 Agent 工具一次派 5 个 general-purpose 子代理，第 i 个读 `$S/spot/sheet_<i>.md`，把结果写到 `$S/spot/labels_<i>.jsonl`。给每个子代理的说明：
- 标准和计划 4 相同：只看得到 instruction、能查库的 agent，最终能不能留下和 SQL 一样的库。
- 每条写一行 `{"id", "label": "good"|"bad", "reason": "missing"|"extra"|"unclear"|"wrong_rows"|"other"|null, "unsure": bool, "note": "一句话", "by": "subagent"}`。
- 可以用 sqlite3 只读查库，库文件路径从 `taskgen/v2/data`、`io.load_db_recs()` 找。
- 不改任何文件，只写自己那份 labels。
- 报告里不摘录题目内容，只写 id 和计数。

Expected：5 份 labels，行数等于各自表里的条数。

- [ ] **Step 3: Claude 复核，排除坏题，重新转换**

逐条读子代理判为 `bad` 或 `unsure` 的题（标注表里有 instruction、SQL 和实际效果），定下好坏。

确认是坏题的，每条追加一行 `{"id", "reason", "by": "claude"}` 到 `results/<db>/excluded.jsonl`，再对这些库重跑：

```bash
cd $REPO/taskgen/v2 && for DB in $($P -c "import glob, json; print(' '.join(sorted({json.loads(open(f).readline())['id'].rsplit(':', 3)[0] for f in glob.glob('results/*/excluded.jsonl')})))"); do
  $P scripts/taskgen.py dedup --db $DB && $P scripts/taskgen.py convert --db $DB; done
```
Expected：排除的 id 不再出现在 `output/<db>/tasks.jsonl` 里。

按你"挡住肯定错的、少量误杀没关系"的原则：抽检里拿不准的也排除。

某个库的坏题超过抽检的 10%，就停下来告诉用户，因为这说明那个库的出题或档案有系统性问题，要不要整库重做由用户定。

- [ ] **Step 4: 全量记录**

写 `docs/<当天日期>-full-run.md`，中文，只写计数和 id：
1. **流程和时间**：建树、出题、检查、校验、去重、转换各一行，含每步的耗时、暂停次数。
2. **每个库的漏斗**：`$S/full_stats.md` 的表。
3. **最终任务对照 DySQL**：同上文件的指标表，逐项对照设计 §3 的目标区间。
4. **校验**：平均每条几票、没投上票的条数、第一票和最终结论不同的比例。
5. **抽检**：每库看了几条、坏了几条（按原因）、排除的 id、最终产出数。
6. **给下一步的输入**：GRPO 训练（研究计划第 4 步）用这些任务前要注意的事。

- [ ] **Step 5: 设计写回、README、commit**

```bash
cat > $S/edit_design5.py <<'EOF'
# writes plan 5's rules back into the design (run from taskgen/v2)
PATH = "docs/2026-10-01-taskgen-v2-design.md"
EDITS = [
    ("计划 4（阶段 F 校验的校准）见 `2026-10-01-taskgen-v2-plan-4.md`；运行的计划在前一份完成后再写",
     "计划 4（阶段 F 校验的校准）见 `2026-10-01-taskgen-v2-plan-4.md`，计划 5（阶段 H 试点、I 全量）见 "
     "`2026-10-01-taskgen-v2-plan-5.md`；阶段 J、K 的计划在前一份完成后再写"),
    ("（计划 4 校准后定为 1 票：好题通过 98%，改坏的题全部被拒）",
     "（计划 4 校准时 1 票就够；全量按用户的选择用 3 票多数，两票一致就不投第三票，计划 5）"),
    ("按类别报告拒绝率。DySQL 金标准和 v2 候选各改一批（每类 60 / 40 条），分开报告。",
     "按类别报告拒绝率。DySQL 金标准和 v2 候选各改一批（计划 4 实际每类 30 条），分开报告。"),
    ("- 加 instruction 近重复过滤（同库 3-gram Jaccard ≥0.6 只留一条）。",
     "- 加 instruction 近重复过滤（同库 3-gram Jaccard ≥0.6 只留一条；计划 5 实现，在终封顶之前）。抽检排除的题记在 "
     "`results/<db>/excluded.jsonl`，去重时跳过。"),
    ("| H 试点 | beer_factory 100 条走完全部步骤；与 v1 试点（82 条）和 DySQL 对比；Qwen3-4B 跑一遍 |",
     "| H 试点 | 并进全量（计划 5）：23 个库出题和检查后，beer_factory 先校验和转换，Qwen3-4B 随机跑 60 条当关卡，"
     "过了再校验其余库；与 v1 试点（82 条）和 DySQL 对比 |"),
]
text = open(PATH, encoding="utf-8").read()
for old, new in EDITS:
    assert text.count(old) == 1, (text.count(old), old)
    text = text.replace(old, new)
open(PATH, "w", encoding="utf-8").write(text)
print(f"{len(EDITS)} edits applied")
EOF
cd $REPO/taskgen/v2 && $P $S/edit_design5.py
cd $REPO
printf '%s\n' \
  '| 校验：3 票多数，按轮投、两票一致就停；没定下的题算没投上票、下次补；连续失败 20 次就暂停（额度用完），退出码 3 | §4.6 |' \
  '| 执行检查：同一张表两条以上由 SQLite 编号的 INSERT … SELECT 就拒（archive_split）；复数词尾只给 3 个字母以上的词；双引号的 "now" 也算读时钟 | §4.5 |' \
  '| 去重：instruction 近重复过滤；抽检排除的题（excluded.jsonl）不进产出 | §4.7 |' \
  '| 试点并进全量：23 个库出题检查后 beer_factory 先校验，Qwen3-4B 随机 60 条当关卡；23 个库全量产出和抽检（docs 里的 pilot、full-run 记录） | §5 H、I |' >> taskgen/v2/README.md
cd $REPO/taskgen/v2 && $P -m pytest -q 2>&1 | tail -n 1
cd $REPO && git add taskgen/v2/docs/*-full-run.md taskgen/v2/docs/2026-10-01-taskgen-v2-design.md taskgen/v2/README.md
git diff --cached --name-only
git commit -m "docs(taskgen v2): the full run, its spot check, and the design write-back

23 databases through the pipeline with three-vote majority verification; per-database funnel, the final task
set against DySQL on the design 3 metrics, and a spot check of up to 30 tasks a database with the bad ones
excluded. The design takes over plan 5's rules.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```
Expected：`5 edits applied`；测试 `194 passed`；暂存区是这 3 个文件。

- [ ] **Step 6: memory**

- `research-plan-grpo-text2sql.md`：计划 5 完成，写日期、commit 范围、最终任务数、4B 试点通过率、抽检坏题率；下一步是研究计划第 4 步（verl GRPO）和计划 6（阶段 J、K）。
- `taskgen-v2-plan4-followups.md`：标出这次做掉的（archive 多行复制、近重复过滤），剩下的写明。
- 新建 `taskgen-v2-full-run.md`：产出在哪（`taskgen/v2/output/`，只在本地）、怎么加载（`TASKGEN_MANIFEST` + `gen:<db>`）、每库任务数、抽检结论；在 `MEMORY.md` 加一行。

---

## 执行之后

- 最终复核：opus 子代理只读审查本计划的提交（`review-package` 的 base 是本计划文档之前那个 commit），对照 Review Focus 和账本里的 Ruling。
- 分支保留，用户自己推。
