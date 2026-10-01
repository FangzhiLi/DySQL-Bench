# 训练任务生成 v2：实施计划 4（校验模型的校准）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按设计 §4.6、D4、D5 把校验改成可配置的多模型投票，排在预封顶之后。然后用三组样本量出 `deepseek-v4.1-flash` 的准确率：DySQL 金标准、改坏的金标准、人工标注的新一批 v2 候选。按量出的结果定票数。

**Architecture:**
- `llm.py`：返回 `finish_reason`。HTTP 200 却没有消息体时重试。可以指定模型。
- `generate.py`：回答在 max_tokens 处被截断时可重试。
- `verify.py`：
  - 模型列表加每个模型的票数（`TASKGEN_VERIFY_MODELS`）。
  - 每条题附档案的数据怪异点。
  - 思考被截断的票不算票。
  - 结论行认得更宽。
- `dedup.py`：新增预封顶。
- `taskgen.py verify`：按"检查 → 预封顶 → 校验"跑。
- `check.py`：新增 `final_state`，比较两份 SQL 留下的库。
- `corrupt.py`：五种改坏。
- `calibrate.py` 和 `scripts/verify_calibrate.py`：组装三组样本、投票、给 Claude 的标注表、给用户的复核页、报告。

**Tech Stack:** Python 3.11（`~/miniconda3/envs/dysql`）、sqlite3、sqlparse、requests、pytest；GLM-5.3（出题，并发 ≤5）；ollama.com 上的 `deepseek-v4.1-flash`（校验，并发 ≤3）。

**Spec:** `taskgen/v2/docs/2026-10-01-taskgen-v2-design.md`（§3 校验两行、§4.6、§5 F、D4、D5）。

## 本计划新定的事（设计里没写到，请审阅时确认）

1. **开发集和测试集分开。**
   - 计划 3 跑出的 316 条候选是**开发集**，只用来找校验 prompt 的毛病。
   - 新出的一批 v2 候选和 DySQL 金标准是**测试集**，不拿来调 prompt。
2. **开发集摸底**（写计划时做的，每条 1 票）：316 条里 Yes 307，No 3，没给出结论 6。
   - 真坏题 1 条：beer_factory customers:442691:0，archive 的副本被后一条 UPDATE 一起改了。计划 3 最后加的 `archive_copy_changed` 已经能拦它。
   - 误杀 2 条：
     - address congress:PA-18:0 的 SQL 是对的。这个库把议员的姓存在 `first_name`（档案的数据怪异点写着），校验模型不知道。同样的 prompt 加上怪异点后，3 票从 No/No/No 变成 Yes/Yes/没结论。
     - college_2 instructor:80759:0 按名字找人。库里只有一个人叫这个名字，结果是对的，3 票里只有 1 票 No。
   - 没给出结论 6 条：
     - 5 条是思考用光了 16384 个 token，回答为空。现在算 No，等于误杀。
     - 1 条结论行写成 "Is the answer correct? Yes"，少了 "(Yes/No)"，解析器认不出。
3. **校验的三处修正**（五问的 prompt 正文不变）：
   - 附档案的数据怪异点（DySQL 的库没有档案，就不附）。
   - 思考被截断、回答为空的票记为失败，不算 No，下次运行重投。
   - 结论取最后一个 "Verification" 之后的第一个 Yes/No。
4. **一次投 3 票，同时算三种规则。** 三种规则是：1 票；2 票都要 Yes；3 票里 2 票 Yes。
   - 选法（`calibrate.choose_rule`）：正样本和标注集好题都至少 95% 通过的规则里，挑拒掉负样本最多的；一样多就用票少的。
   - 选出的票数写进 `verify.DEFAULT_VOTES`，`.env` 不用改。
   - 没有规则满足两条 95%，或者选出的规则拒掉的负样本不到 80%（§3 的目标），就停下来问你：
     - 加第二个模型（D4）；
     - 把漏的类别补成检查规则；
     - 接受现状。
5. **负样本。**
   - 五种改法，都改金标准里的写语句：
     - 改一个值：换成这道题里另一个同类的值，一个数换另一个数，一个字符串换另一个字符串，这样执行检查的字面量规则仍然通过。
     - 删一个 WHERE 条件：只有一个条件就整个 WHERE 删掉。
     - 换一个 SET 列：同表、同声明类型、不是主键。
     - 删最后一条写语句。
     - 对调同一条语句里两个不同的值。
   - 只留"仍过执行检查、而且库的最终状态变了"的，因为只有这些需要校验模型来拦。每条题每种改法最多试 3 次。
   - 来源两个：DySQL 金标准每种 60 条，新一批 v2 候选每种 40 条，各自报告。
   - 写计划时在 895 条 DySQL 金标准上试过，可用的数量都够：

     | 改法 | 可用 | 被检查拦下 | 状态没变 |
     |---|---|---|---|
     | 改一个值 | 422 | 417 | 28 |
     | 删 WHERE 条件 | 315 | 258 | 284 |
     | 换 SET 列 | 526 | 2 | 1 |
     | 删最后一条 | 578 | 0 | 9 |
     | 对调两个值 | 245 | 603 | 42 |

     "被检查拦下"的主要原因：改值、对调多半改了 0 行，删 WHERE 多半超过 50 行。
6. **人工标注集改用新出的 v2 候选，不再用 v1 试点的 93 条**（设计 D5、§4.6 原来这么写）。
   - 新出的一批：每库 7 棵树，seed 1，用修好的代码出题。过了执行检查的全部标，约 150 条。
   - 我先标，标的时候不看校验模型的票。你只复核我拿不准的、以及我和 3 票多数不一致的。
   - 开发集里真坏题只有 1/316，所以标注集里坏题会很少。它主要量"好题被误杀多少"；能不能拦住坏题，主要看第 5 条的负样本。v1 的题和 v2 差别太大（73% 带只读提问、平均 102 词），补进来也说明不了 v2。
   - 这一批同时第一次在 GLM 上检验计划 3 最后的修正：archive 的占比，以及 `archive_copy_changed` 拒了多少条。
7. **预封顶**（设计 §4.6）：检查 → 预封顶（每模板 ≤25、每库 ≤900，不限每人）→ 校验 → 终封顶（2/15/600）。同一个 seed 重跑，选中的题不变，所以校验能续跑。
8. **漏掉的类别不在本计划里补成检查规则。** 报告列出被放过的负样本和坏题，按类别给出建议，下一份计划再做，先给你看。
9. **成本。**
   - GLM 出题约 160 条，约 20 分钟。
   - 校验约 4,700 票：正样本 895×3，负样本 500×3，标注集约 150×3。开发集实测每票平均 7.5 秒，3 个并发，合计约 3–4 小时，能续跑。
10. **这次不做的：**
    - §4.7 的近重复过滤，留给计划 5。
    - 第二个校验模型，看第 4 条的结果再定。
    - 把执行效果（改了哪些行）给校验模型看。写计划时有一个没用上的草稿，第 4 条的结果里"删 WHERE 条件"拦得不好再考虑。
    - 计划 3 留下的其它 minor。

## Global Constraints

- 生成的候选、标注、投票、复核页都放 `taskgen/v2/results/`（`.gitignore` 已含 `taskgen/*/results/`），**不进 git、不公开**；文档只写计数和 id，不摘录题目内容。每次 commit 前看 `git diff --cached --name-only`。
- `.env` 里有 API key：不打印、不提交，只能显示 `BASE_URL` / `MODEL` 行。
- GLM 并发 ≤5（`--workers 5`）；ollama.com 并发 ≤3（`--workers 3`）。
- `taskgen/v1/` 冻结；`data/db_profiles.json` 只由用户确认，本计划不改。
- 推送由用户自己做；只推分支，不开 PR。
- 命令里 `REPO=/home/wmd3i/Documents/Isa/DySQL-Bench`，`P=~/miniconda3/envs/dysql/bin/python`，`S=` 本次的 scratchpad 目录（临时脚本和日志）。

## Review Focus

1. **一条题的票一直被截断或失败**：不满 3 票时规则给 `None`，既不算通过也不算拒绝，报告里单列数量。→ Task 5 的 `test_verdict_takes_the_first_k_real_votes`。
2. **读时钟的金标准**：`final_state` 在固定时刻执行，两次运行一致，不会把同一份 SQL 判成"状态变了"。→ Task 4 的 `test_final_state_reads_the_clock_at_a_fixed_instant`。
3. **字符串里带单引号的值**（`'O''Brien'`）：改值、对调之后仍是合法 SQL。→ Task 4 的 `test_a_changed_literal_keeps_its_quotes`。
4. **预封顶重跑**：同一个 seed 选中的题不变，`verify` 续跑不会换一批题。→ Task 2 的 `test_precap_draws_the_same_candidates_on_a_rerun`。
5. **模型名里带冒号**（`qwen3:8b:1`）：票数取最后一段。→ Task 3 的 `test_model_specs`。

---

### Task 1: 模型调用：截断的回答和坏响应可重试

**Files:**
- Modify: `taskgen/v2/taskgen_v2/llm.py`（`ChatClient.chat` 返回 `finish_reason`，HTTP 200 却没有消息体时重试；`client_from_env` 可指定模型）
- Modify: `taskgen/v2/taskgen_v2/generate.py`（`RETRYABLE` 加 `Truncated`；回答在 max_tokens 处截断、解析失败时记 `Truncated`）
- Test: `taskgen/v2/tests/test_taskgen_llm.py`、`taskgen/v2/tests/test_taskgen_generate.py`

**Interfaces:**
- Consumes: 无。
- Produces:
  - `llm.ChatClient.chat(...)` 的返回值多一个键 `"finish_reason"`（`"stop"`、`"length"` 或 `None`）。
  - `llm.client_from_env(role, model=None)`：`model` 给出时用它，不再要求 `TASKGEN_<ROLE>_MODEL`。Task 3 的 `verify.models_from_env` 用它给每个模型建客户端。
  - `generate.RETRYABLE` 多了 `"Truncated"`；`--retry-errors` 会重做 `error` 以 `Truncated:` 开头的候选。

- [ ] **Step 1: 写失败的测试**

`tests/test_taskgen_llm.py` 里把

```python
    assert r == {"content": "hi", "reasoning": "think", "usage": {"prompt_tokens": 5, "completion_tokens": 7}, "model": "glm-5.3"}
```

换成：

```python
    assert r == {"content": "hi", "reasoning": "think", "usage": {"prompt_tokens": 5, "completion_tokens": 7}, "model": "glm-5.3",
                 "finish_reason": "stop"}
```

`tests/test_taskgen_llm.py` 里把

```python
def test_pmap_keeps_order_and_captures_exceptions():
```

换成：

```python
class BadJSON(FakeResp):
    def json(self): raise ValueError("Expecting value: line 1 column 1")


def test_a_200_without_a_message_is_asked_again():
    c = client([BadJSON(200, "<html>gateway</html>"), FakeResp(200, {"choices": []}), OK])
    assert c.chat([{"role": "user", "content": "q"}])["content"] == "hi" and len(c.session.calls) == 3
    c = client([FakeResp(200, {"error": "overloaded"})] * 2, max_retries=1)
    with pytest.raises(llm.LLMError, match="HTTP 200 without a message"):
        c.chat([{"role": "user", "content": "q"}])


def test_client_from_env_takes_another_model(monkeypatch):
    monkeypatch.setattr(llm.io, "load_dotenv", lambda *a, **k: None)
    for k, v in {"TASKGEN_VERIFY_BASE_URL": "https://v/1", "TASKGEN_VERIFY_API_KEY": "k", "TASKGEN_VERIFY_MODEL": "m0"}.items():
        monkeypatch.setenv(k, v)
    assert llm.client_from_env("VERIFY").model == "m0" and llm.client_from_env("VERIFY", model="m1").model == "m1"
    monkeypatch.delenv("TASKGEN_VERIFY_MODEL")
    assert llm.client_from_env("VERIFY", model="m1").model == "m1"
    with pytest.raises(llm.LLMError, match="TASKGEN_VERIFY_MODEL"):
        llm.client_from_env("VERIFY")


def test_pmap_keeps_order_and_captures_exceptions():
```

`tests/test_taskgen_generate.py` 里把

```python
def test_an_archive_copies_only_into_tables_whose_copies_differ_from_the_originals(tmp_path):
```

换成：

```python
def test_an_answer_cut_off_at_max_tokens_is_retried(tmp_path):
    class Cut(FakeClient):
        def chat(self, messages, **kw):
            return {"content": GOOD[:60], "usage": {"completion_tokens": 16384}, "model": "fake", "finish_reason": "length"}
    out = str(tmp_path / "c.jsonl")
    generate.run(DB, ANCHOR, [TREE], Cut([]), out, random.Random(0))
    r = io.read_jsonl(out)[0]
    assert r["instruction"] is None and r["error"] == "Truncated: answer cut off after 16384 completion tokens"
    s = generate.run(DB, ANCHOR, [TREE], FakeClient([GOOD]), out, random.Random(0), retry_errors=True)
    assert s["written"] == 1 and io.read_jsonl(out)[0]["instruction"].startswith("I am a5 b5")


def test_an_archive_copies_only_into_tables_whose_copies_differ_from_the_originals(tmp_path):
```

- [ ] **Step 2: 跑测试，确认失败**

```bash
cd $REPO/taskgen/v2 && $P -m pytest -q tests/test_taskgen_llm.py tests/test_taskgen_generate.py 2>&1 | tail -n 3
```
Expected：`4 failed, 17 passed`。失败的是：
- `test_chat_parses_content_reasoning_usage_and_sends_auth`
- `test_a_200_without_a_message_is_asked_again`
- `test_client_from_env_takes_another_model`
- `test_an_answer_cut_off_at_max_tokens_is_retried`

- [ ] **Step 3: 实现**

`taskgen_v2/llm.py` 里把

```python
                if r.status_code == 200:
                    body = r.json()
                    msg = body["choices"][0]["message"]
                    return {"content": msg.get("content") or "", "reasoning": msg.get("reasoning_content") or msg.get("reasoning") or "",
                            "usage": body.get("usage") or {}, "model": body.get("model") or self.model}
                last = f"HTTP {r.status_code}: {r.text[:300]}"
                if r.status_code not in RETRY_STATUS:
                    raise LLMError(last)
```

换成：

```python
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
```

`taskgen_v2/llm.py` 里把

```python
def client_from_env(role):
    io.load_dotenv()
    p = f"TASKGEN_{role.upper()}_"
    missing = [k for k in ("BASE_URL", "API_KEY", "MODEL") if not os.environ.get(p + k)]
    if missing:
        raise LLMError(f"missing env {', '.join(p + k for k in missing)} (see .env)")
    return ChatClient(os.environ[p + "BASE_URL"], os.environ[p + "API_KEY"], os.environ[p + "MODEL"])
```

换成：

```python
def client_from_env(role, model=None):
    """A client for TASKGEN_<ROLE>_BASE_URL / _API_KEY and the given model, or TASKGEN_<ROLE>_MODEL."""
    io.load_dotenv()
    p = f"TASKGEN_{role.upper()}_"
    missing = [k for k in ("BASE_URL", "API_KEY") + (() if model else ("MODEL",)) if not os.environ.get(p + k)]
    if missing:
        raise LLMError(f"missing env {', '.join(p + k for k in missing)} (see .env)")
    return ChatClient(os.environ[p + "BASE_URL"], os.environ[p + "API_KEY"], model or os.environ[p + "MODEL"])
```

`taskgen_v2/generate.py` 里把

```python
RETRYABLE = ("LLMError", "RuntimeError", "ConnectionError", "EmptyAnswer")
```

换成：

```python
RETRYABLE = ("LLMError", "RuntimeError", "ConnectionError", "EmptyAnswer", "Truncated")
```

`taskgen_v2/generate.py` 里把

```python
                except ParseError as e:
                    error = f"ParseError: {e}"
```

换成：

```python
                except ParseError as e:
                    error = f"ParseError: {e}"
                    if resp.get("finish_reason") == "length":   # the answer was cut off at max_tokens: ask again
                        error = f"Truncated: answer cut off after {(resp.get('usage') or {}).get('completion_tokens')} completion tokens"
```

- [ ] **Step 4: 跑测试，确认通过**

```bash
cd $REPO/taskgen/v2 && $P -m pytest -q tests/test_taskgen_llm.py tests/test_taskgen_generate.py 2>&1 | tail -n 3
```
Expected：`21 passed`。

- [ ] **Step 5: 跑全套**

```bash
cd $REPO/taskgen/v2 && $P -m pytest -q  2>&1 | tail -n 3
```
Expected：`154 passed`。

- [ ] **Step 6: commit**

```bash
cd $REPO
git add taskgen/v2/taskgen_v2/llm.py \
        taskgen/v2/taskgen_v2/generate.py \
        taskgen/v2/tests/test_taskgen_llm.py \
        taskgen/v2/tests/test_taskgen_generate.py
git diff --cached --name-only
git commit -m "fix(taskgen v2): answers cut off at max_tokens and empty 200 bodies are asked again

The chat client returns finish_reason and retries an HTTP 200 without a message the way it retries a 503;
a client can name its model. A generated answer cut off at max_tokens is a Truncated error that
--retry-errors redoes, not a parse failure that stays.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```
Expected：暂存区只有这 4 个文件。

---

### Task 2: 预封顶：校验只看封顶后会留下的题

**Files:**
- Modify: `taskgen/v2/taskgen_v2/dedup.py`（`select` 的 `per_person=None` 表示不限每人；新函数 `precap`）
- Test: `taskgen/v2/tests/test_taskgen_dedup.py`

**Interfaces:**
- Consumes: 无。
- Produces: `dedup.precap(cands, checks, rng, per_template=25, per_db=900) -> list`：过了执行检查的候选，按 `select` 的规则（少见模板先取）每模板最多 `per_template`、一共最多 `per_db` 条，不限每人；按候选文件的原顺序返回。Task 3 的 `taskgen.py verify` 用它。

- [ ] **Step 1: 写失败的测试**

`tests/test_taskgen_dedup.py` 里把

```python
def test_per_db_cap_and_determinism():
```

换成：

```python
def test_precap_takes_checked_candidates_by_template_without_a_person_cap():
    cands = [{"id": f"x:{i}", "anchor_table": "customers", "key_value": 1} for i in range(40)]
    checks = [{"id": f"x:{i}", "ok": i != 0, "template": "A" if i < 30 else "B"} for i in range(40)]
    out = dedup.precap(cands, checks, random.Random(0), per_template=25, per_db=900)
    ids = {c["id"] for c in out}
    assert "x:0" not in ids and len(ids) == 35 and sum(1 for i in ids if int(i[2:]) < 30) == 25   # one person, 35 tasks
    assert len(dedup.precap(cands, checks, random.Random(0), per_template=25, per_db=12)) == 12
    assert [c["id"] for c in out] == [c["id"] for c in cands if c["id"] in ids]   # file order kept


def test_per_db_cap_and_determinism():
```

`tests/test_taskgen_dedup.py` 末尾加：

```python
def test_precap_draws_the_same_candidates_on_a_rerun():
    cands = [{"id": f"x:{i}", "anchor_table": "customers", "key_value": i} for i in range(60)]
    checks = [{"id": f"x:{i}", "ok": True, "template": f"t{i % 4}"} for i in range(60)]
    a = dedup.precap(cands, checks, random.Random(0), per_template=5, per_db=900)
    assert a == dedup.precap(cands, checks, random.Random(0), per_template=5, per_db=900) and len(a) == 20
```

- [ ] **Step 2: 跑测试，确认失败**

```bash
cd $REPO/taskgen/v2 && $P -m pytest -q tests/test_taskgen_dedup.py 2>&1 | tail -n 3
```
Expected：`2 failed, 3 passed`。失败的是：
- `test_precap_takes_checked_candidates_by_template_without_a_person_cap`
- `test_precap_draws_the_same_candidates_on_a_rerun`

- [ ] **Step 3: 实现**

`taskgen_v2/dedup.py` 里把

```python
database. Rare templates are taken first so the long tail survives the per-db cap."""
```

换成：

```python
database. Rare templates are taken first so the long tail survives the per-db cap. The same caps, looser and without
the per-person one, pick what the verifier sees (design §4.6: check -> pre-cap -> verify -> final cap)."""
```

`taskgen_v2/dedup.py` 里把

```python
        if seen_person[person] >= per_person or seen_template[r["template"]] >= per_template:
```

换成：

```python
        if (per_person is not None and seen_person[person] >= per_person) or seen_template[r["template"]] >= per_template:
```

`taskgen_v2/dedup.py` 末尾加：

```python
def precap(cands, checks, rng, per_template=25, per_db=900):
    """The candidates that passed the check, at most per_template per template and per_db in all: the verifier's
    calls are not spent on tasks the final cap (2/15/600) would drop anyway."""
    ok = {c["id"]: c for c in checks if c["ok"]}
    recs = [{**c, "template": ok[c["id"]]["template"]} for c in cands if c["id"] in ok]
    keep = {r["id"] for r in select(recs, rng, per_person=None, per_template=per_template, per_db=per_db)}
    return [c for c in cands if c["id"] in keep]
```

- [ ] **Step 4: 跑测试，确认通过**

```bash
cd $REPO/taskgen/v2 && $P -m pytest -q tests/test_taskgen_dedup.py 2>&1 | tail -n 3
```
Expected：`5 passed`。

- [ ] **Step 5: 跑全套**

```bash
cd $REPO/taskgen/v2 && $P -m pytest -q  2>&1 | tail -n 3
```
Expected：`156 passed`。

- [ ] **Step 6: commit**

```bash
cd $REPO
git add taskgen/v2/taskgen_v2/dedup.py \
        taskgen/v2/tests/test_taskgen_dedup.py
git diff --cached --name-only
git commit -m "feat(taskgen v2): a pre-cap picks what the verifier sees

check -> pre-cap -> verify -> final cap (design 4.6): at most 25 checked candidates per template and 900 per
database go to the verifier, rare templates first and without the per-person cap, so its calls are not spent
on tasks the final cap would drop. The same seed draws the same set, so a verify run resumes.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```
Expected：暂存区只有这 2 个文件。

---

### Task 3: 校验：几个模型、各投几票，附数据怪异点，截断的票不算

**Files:**
- Modify: `taskgen/v2/taskgen_v2/verify.py`（整个换掉：`Truncated`、`parse_models`、`models_from_env`、`build_messages` 的 `notes`、`parse_verdict`、`tally`、`run` 的新参数）
- Modify: `taskgen/v2/taskgen_v2/convert.py`（meta 按模型记每一票，加 `profile_version`）
- Modify: `taskgen/v2/scripts/taskgen.py`（`verify` 子命令：`--models`、`--precap-template`、`--precap-db`，去掉 `--votes`）
- Test: `taskgen/v2/tests/test_taskgen_verify.py`（整个换掉）、`taskgen/v2/tests/test_taskgen_convert_env.py`、`taskgen/v2/tests/test_taskgen_cli.py`

**Interfaces:**
- Consumes: Task 1 的 `llm.client_from_env(role, model=None)`、`finish_reason`；Task 2 的 `dedup.precap`。
- Produces:
  - `verify.run(cands, models, out_path, workers=3, context=lambda cand: ("", ())) -> {"verified", "passed", "skipped"}`：`models` 是 `[(client, votes)]`，`context(cand)` 给出 `(ddl_text, notes)`。
  - 记录格式：`{"id", "votes": [{"verdict", "content", "reasoning_chars", "usage", "model"} 或带 "error" 的失败票], "models": {模型: {"yes", "no", "pass"}}, "pass", "verify_model": "m1,m2"}`。
  - `verify.parse_models(spec) -> [(name, votes)]`，`verify.models_from_env(spec=None) -> [(client, votes)]`，`verify.DEFAULT_VOTES = 2`，`verify.Truncated`。
  - Task 5 的 `calibrate` 用 `verify.run` 和 `Databases.context` 投票；Task 7 可能改 `DEFAULT_VOTES`。

- [ ] **Step 1: 写失败的测试**

`tests/test_taskgen_verify.py` 整个换成：

```python
# tests/test_taskgen_verify.py
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
    c = FakeClient([YES, NO, YES])
    s = run([CAND], c, out)
    r = io.read_jsonl(out)[0]
    assert s == {"verified": 1, "passed": 1, "skipped": 0} and r["models"]["fake-verifier"] == {"yes": 2, "no": 1, "pass": True}
    assert r["pass"] and len(r["votes"]) == 3 and r["votes"][0]["reasoning_chars"] == 10 and r["votes"][0]["model"] == "fake-verifier"
    s2 = run([CAND], FakeClient([YES]), out)
    assert s2["skipped"] == 1 and len(io.read_jsonl(out)) == 1


def test_run_tops_up_votes(tmp_path):
    out = str(tmp_path / "verify.jsonl")
    run([CAND], FakeClient([YES, YES, NO]), out)
    c = FakeClient([NO, NO])
    run([CAND], c, out, votes=5)
    r = io.read_jsonl(out)
    assert len(r) == 1 and len(r[0]["votes"]) == 5 and r[0]["models"]["fake-verifier"]["no"] == 3 and not r[0]["pass"] and c.calls == 2


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
    c = FakeClient([NO, NO, NO])
    s = run([CAND, c2], c, out)
    assert s["skipped"] == 1 and c.calls == 3 and [r["id"] for r in io.read_jsonl(out)] == ["c1", "c2"]


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
    run([CAND], Flaky([YES, YES]), out)
    r = io.read_jsonl(out)[0]
    assert r["models"]["fake-verifier"] == {"yes": 2, "no": 0, "pass": True} and sum("error" in v for v in r["votes"]) == 1
    c = FakeClient([NO])
    run([CAND], c, out)
    r = io.read_jsonl(out)[0]
    assert c.calls == 1 and r["models"]["fake-verifier"] == {"yes": 2, "no": 1, "pass": True} and r["pass"]


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
    assert r["models"]["fake-verifier"] == {"yes": 1, "no": 0, "pass": True}
    c = FakeClient([YES])
    run([CAND], c, out, votes=2)
    assert c.calls == 1 and io.read_jsonl(out)[0]["models"]["fake-verifier"]["yes"] == 2


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
```

`tests/test_taskgen_convert_env.py` 里把

```python
       "difficulty": {"score": 0, "level": "easy"}, "gen_model": "g", "verify_model": "v",
       "votes": [{"verdict": "yes"}, {"verdict": "yes"}, {"verdict": "no"}]}
```

换成：

```python
       "difficulty": {"score": 0, "level": "easy"}, "gen_model": "g", "verify_model": "v,w", "profile_version": "abc",
       "votes": [{"verdict": "yes", "model": "v"}, {"verdict": "error", "error": "HTTP 503", "model": "v"},
                 {"verdict": "yes", "model": "v"}, {"verdict": "no", "model": "w"}]}
```

`tests/test_taskgen_convert_env.py` 里把

```python
row["meta"]["verify_votes"] == ["yes", "yes", "no"]
```

换成：

```python
row["meta"]["verify_votes"] == {"v": ["yes", "yes"], "w": ["no"]} and row["meta"]["profile_version"] == "abc"
```

`tests/test_taskgen_cli.py` 里把

```python
import json, os, subprocess, sys
```

换成：

```python
import json, os, subprocess, sys, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
```

`tests/test_taskgen_cli.py` 末尾加：

```python
class FakeVerifier(BaseHTTPRequestHandler):
    """An OpenAI-style endpoint that answers Yes and keeps every request body."""
    seen = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeVerifier.seen.append(body)
        out = json.dumps({"model": body["model"], "usage": {"completion_tokens": 9}, "choices": [
            {"message": {"content": "Fine. Verification: Is the answer correct (Yes/No)? Yes"}, "finish_reason": "stop"}]}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out))); self.end_headers(); self.wfile.write(out)

    def log_message(self, *a):
        pass


def test_verify_sees_precapped_candidates_with_the_profile_quirks(tmp_path):
    args = setup(tmp_path)
    profiles = args[args.index("--profiles") + 1]
    ps = db_profile.load(profiles)
    ps["test:shop2"] = db_profile.confirm({**ps["test:shop2"], "quirks": ["qty counts boxes, not items."]})
    db_profile.save(ps, profiles)
    out = tmp_path / "res"
    run("trees", *args, "--n", "3", "--seed", "0")
    rows = []
    for t in io.read_jsonl(out / "trees.jsonl"):
        oid = t["events"][0]["rows"][0]["row"]["order_id"]
        rows.append({"id": "test:shop2:customers:%s:0" % t["key_value"], "db": "shop2", "source": "test",
                     "anchor_table": "customers", "anchor_key": "customer_id", "key_value": t["key_value"],
                     "anchor_name": t["anchor_name"], "profile_version": t["profile_version"],
                     "plan": {"task_type": "1_self", "difficulty": "easy"},
                     "instruction": f"I am {t['anchor_name']}. Set qty of my order {oid} to 3.",
                     "actions": [{"sql": f"UPDATE orders SET qty = 3 WHERE order_id = {oid}"}], "error": None})
    io.append_jsonl(out / "candidates.jsonl", rows)
    run("check", *args)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeVerifier)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    env = {**os.environ, "TASKGEN_VERIFY_BASE_URL": f"http://127.0.0.1:{srv.server_port}/v1",
           "TASKGEN_VERIFY_API_KEY": "k", "TASKGEN_VERIFY_MODELS": "m1:2"}
    try:
        subprocess.run([sys.executable, SCRIPT, "verify", *args, "--precap-template", "2", "--workers", "1"],
                       check=True, capture_output=True, text=True, env=env)
    finally:
        srv.shutdown()
    v = io.read_jsonl(out / "verify.jsonl")
    assert len(v) == 2 and all(r["models"] == {"m1": {"yes": 2, "no": 0, "pass": True}} and r["pass"] for r in v)  # 3 checked, 2 per template
    assert len(FakeVerifier.seen) == 4 and {b["model"] for b in FakeVerifier.seen} == {"m1"}
    u = FakeVerifier.seen[0]["messages"][1]["content"]
    assert "- qty counts boxes, not items." in u and "CREATE TABLE orders" in u
```

- [ ] **Step 2: 跑测试，确认失败**

```bash
cd $REPO/taskgen/v2 && $P -m pytest -q tests/test_taskgen_verify.py tests/test_taskgen_convert_env.py tests/test_taskgen_cli.py 2>&1 | tail -n 3
```
Expected：`13 failed, 10 passed`。失败的是：
- `test_run_votes_majority_and_resumes`
- `test_run_tops_up_votes`
- `test_unparsed_counts_as_no`
- `test_finished_candidates_are_written_before_a_crash`
- `test_failed_votes_are_not_counted_and_are_retried`
- `test_a_verdict_line_without_the_choice_in_brackets_is_read`
- `test_a_vote_cut_off_while_thinking_is_not_a_no_and_is_asked_again`
- `test_every_model_must_pass`
- `test_context_gives_each_candidate_its_schema_and_data_notes`
- `test_model_specs`
- `test_models_from_env`
- `test_write_tasks_and_manifest`
- `test_verify_sees_precapped_candidates_with_the_profile_quirks`

- [ ] **Step 3: 实现**

`taskgen_v2/verify.py` 整个换成：

```python
# taskgen/v2/taskgen_v2/verify.py
"""LLM verification by majority vote. DySQL's verify prompt (verify_qa_voting_request.py) judged the gold SQL as an
agent transcript against the agent policy, so a 27B verifier failed every pilot task for missing confirmation turns;
this prompt judges only whether the SQL implements the request, and whether the request is complete and solvable.
Several models may vote (design §4.6, D4): each passes a task when its Yes votes outnumber its No votes, and a task
passes when every model passes it."""
import json, os, re
from concurrent.futures import ThreadPoolExecutor, as_completed
from taskgen_v2 import io, llm

VERIFY_TEMPERATURE, VERIFY_MAX_TOKENS = 1.2, 16384
DEFAULT_VOTES = 2   # with two votes both must say Yes (design §4.6)
FINAL = "Verification: Is the answer correct (Yes/No)?"

SYSTEM = """You are checking a training task for a database agent. The task has two parts: the user's request (what a
customer or staff member will ask the agent for) and the ground-truth SQL statements that a correct agent must end up
executing. The SQL list is the expected final database changes, not a conversation transcript: greetings,
authentication chat, asking the user for confirmation and answering read-only questions all happen in the dialogue and
are NOT expected in the SQL list. Do not fail the task for missing conversational steps.

Check these five things.
1. [Correctness] Executed in order on the database whose schema is given, the SQL performs exactly the changes the
   request asks for: right tables, right rows, right columns, right new values. Nothing requested is missing.
2. [No extra changes] The SQL changes nothing the request did not ask for.
3. [Completeness of parameters] Every value the SQL uses (ids, names, amounts, dates, new values) is stated in the
   request, except values that identify the requester's own record (or the record the request is about), which the
   agent can look up once it knows who or what is meant.
4. [Solvability] A competent agent that can only read the request and query the database, without seeing these SQL
   statements, would arrive at the same final database state. Ambiguous requests that allow several reasonable
   end states fail this check.
5. [Validity] The SQL is valid SQLite for the given schema.

## Response format
Reason step by step, then end with: "Verification: Is the answer correct (Yes/No)?" followed by "Yes" or "No".
"""

USER = """Here is the user's request:
{user_requirements}

Here are the ground-truth SQL statements, in order:
{action_outputs}

Here is the database schema (DDL):
{ddl}
"""

NOTES = """
Notes on this database's data (true of the stored rows; the SQL may rely on them):
{notes}
"""


class Truncated(RuntimeError):
    """The model spent its tokens thinking and gave no verdict: not a vote, asked again on the next run."""


def parse_models(spec):
    """'deepseek-v4.1-flash:2,other:1' -> [('deepseek-v4.1-flash', 2), ('other', 1)]; a model without ':n' votes
    DEFAULT_VOTES times. A model name may itself contain ':' (qwen3:8b:3), so the count is the last field."""
    out = []
    for part in (p.strip() for p in spec.split(",") if p.strip()):
        name, _, n = part.rpartition(":")
        out.append((name, int(n)) if name and n.isdigit() else (part, DEFAULT_VOTES))
    return out


def models_from_env(spec=None):
    """[(client, votes)] for spec, else TASKGEN_VERIFY_MODELS, else TASKGEN_VERIFY_MODEL with DEFAULT_VOTES; every
    model goes to TASKGEN_VERIFY_BASE_URL with TASKGEN_VERIFY_API_KEY."""
    io.load_dotenv()
    spec = spec or os.environ.get("TASKGEN_VERIFY_MODELS") or f"{os.environ.get('TASKGEN_VERIFY_MODEL', '')}:{DEFAULT_VOTES}"
    return [(llm.client_from_env("VERIFY", model=name), n) for name, n in parse_models(spec)]


def build_messages(cand, ddl_text, notes=()):
    user = USER.format(user_requirements=cand["instruction"],
                       action_outputs=json.dumps(cand["actions"], ensure_ascii=False, indent=1), ddl=ddl_text)
    if notes:   # the profile's data quirks: address stores congress surnames in first_name
        user += NOTES.format(notes="\n".join(f"- {n}" for n in notes))
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


def parse_verdict(text):
    """The first Yes or No after the last 'Verification', whatever the model did to the question
    ('Verification: Is the answer correct?  Yes', '**No**'); the first, since a reason may follow ('No, not yes')."""
    text = text or ""
    if "Verification" not in text:
        return "unparsed"
    tail = text.rsplit("Verification", 1)[1].replace("(Yes/No)", "")
    words = re.findall(r"(?i)\b(yes|no)\b", tail)
    return words[0].lower() if words else "unparsed"


def _vote(client, msgs):
    r = client.chat(msgs, temperature=VERIFY_TEMPERATURE, max_tokens=VERIFY_MAX_TOKENS)
    verdict = parse_verdict(r["content"])
    if verdict == "unparsed" and (r.get("finish_reason") == "length" or not (r["content"] or "").strip()):
        raise Truncated(f"no verdict within {(r.get('usage') or {}).get('completion_tokens')} completion tokens")
    return {"verdict": verdict, "content": r["content"], "reasoning_chars": len(r.get("reasoning") or ""),
            "usage": r.get("usage")}


def _vote_safe(client, msgs):
    model = getattr(client, "model", None)
    try:
        return {**_vote(client, msgs), "model": model}
    except Exception as e:  # an API failure is not a vote: kept for the record, ignored by counts, retried on resume
        return {"verdict": "error", "error": f"{type(e).__name__}: {e}", "content": "", "reasoning_chars": 0, "usage": None,
                "model": model}


def _real(votes, model=None):
    return [v for v in votes if "error" not in v and (model is None or v.get("model") == model)]


def tally(rec, names):
    """Per model Yes/No counts and pass (Yes strictly more than No; unparsed counts as No); the task passes when
    every model passes it."""
    rec["models"] = {}
    for name in names:
        votes = _real(rec["votes"], name)
        yes = sum(v["verdict"] == "yes" for v in votes)
        rec["models"][name] = {"yes": yes, "no": len(votes) - yes, "pass": yes > len(votes) - yes}
    rec["pass"] = all(m["pass"] for m in rec["models"].values())
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
    new_votes, updated, passed = {}, {}, 0
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
            passed += rec["pass"]
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
    return {"verified": len(pending), "passed": passed, "skipped": len(cands) - len(pending)}
```

`taskgen_v2/convert.py` 里把

```python
    meta = {k: r.get(k) for k in ("id", "db", "source", "anchor_table", "anchor_key", "key_value", "task_type",
                                   "difficulty", "template", "plan", "gen_model", "verify_model")}
    meta["verify_votes"] = [v["verdict"] for v in r.get("votes", [])]
```

换成：

```python
    meta = {k: r.get(k) for k in ("id", "db", "source", "anchor_table", "anchor_key", "key_value", "task_type",
                                   "difficulty", "template", "plan", "gen_model", "verify_model", "profile_version")}
    meta["verify_votes"] = {}   # every model's every vote (design §4.7); failed calls are not votes
    for v in r.get("votes", []):
        if "error" not in v:
            meta["verify_votes"].setdefault(v.get("model") or r.get("verify_model"), []).append(v["verdict"])
```

`scripts/taskgen.py` 里把

```python
  $P scripts/taskgen.py verify   --db $DB --votes 3 --workers 3
```

换成：

```python
  $P scripts/taskgen.py verify   --db $DB --workers 3
```

`scripts/taskgen.py` 里把

```python
def cmd_verify(a):
    dbs = [a.db] if not a.all_dbs else [k for k in io.load_db_recs(a.anchors) if os.path.exists(
        os.path.join(io.RESULTS, k.split(":", 1)[1], "check.jsonl"))]
    client = llm.client_from_env("VERIFY")
    for db in dbs:
        a.db = db
        rec, out = rec_and_dir(a)
        ok = {r["id"] for r in io.read_jsonl(f"{out}/check.jsonl") if r["ok"]}
        cands = [c for c in io.read_jsonl(f"{out}/candidates.jsonl") if c["id"] in ok]
        t0 = time.time()
        s = verify.run(cands, client, f"{out}/verify.jsonl", votes=a.votes, workers=a.workers,
                       ddl_text=schema.ddl(io.resolve_db_path(rec["path"])))
        print(f"{db}: {s} in {time.time() - t0:.0f}s")
```

换成：

```python
def cmd_verify(a):
    """check -> pre-cap -> verify (design §4.6): the candidates that passed the check, capped per template and per
    database, each judged with the database's DDL and the profile's data quirks."""
    dbs = [a.db] if not a.all_dbs else [k for k in io.load_db_recs(a.anchors) if os.path.exists(
        os.path.join(io.RESULTS, k.split(":", 1)[1], "check.jsonl"))]
    models = verify.models_from_env(a.models)
    for db in dbs:
        a.db = db
        rec, out = rec_and_dir(a)
        prof = profile_of(a)
        same_profile(f"{out}/candidates.jsonl", db_profile.version(prof), "candidates")
        cands = dedup.precap(io.read_jsonl(f"{out}/candidates.jsonl"), io.read_jsonl(f"{out}/check.jsonl"),
                             random.Random(a.seed), a.precap_template, a.precap_db)
        ddl, quirks = schema.ddl(io.resolve_db_path(rec["path"])), prof["quirks"]
        t0 = time.time()
        s = verify.run(cands, models, f"{out}/verify.jsonl", workers=a.workers, context=lambda c: (ddl, quirks))
        print(f"{db}: {s} in {time.time() - t0:.0f}s")
```

`scripts/taskgen.py` 里把

```python
    p = sub.add_parser("verify"); common(p); p.add_argument("--votes", type=int, default=3); p.add_argument("--workers", type=int, default=3, help="Ollama Pro plan limit: 3 concurrent requests"); p.add_argument("--all-dbs", action="store_true"); p.set_defaults(f=cmd_verify)
```

换成：

```python
    p = sub.add_parser("verify"); common(p); p.add_argument("--models", help="model:votes,... (default: TASKGEN_VERIFY_MODELS, else TASKGEN_VERIFY_MODEL:2)")
    p.add_argument("--precap-template", type=int, default=25); p.add_argument("--precap-db", type=int, default=900)
    p.add_argument("--workers", type=int, default=3, help="Ollama Pro plan limit: 3 concurrent requests"); p.add_argument("--all-dbs", action="store_true"); p.set_defaults(f=cmd_verify)
```

- [ ] **Step 4: 跑测试，确认通过**

```bash
cd $REPO/taskgen/v2 && $P -m pytest -q tests/test_taskgen_verify.py tests/test_taskgen_convert_env.py tests/test_taskgen_cli.py 2>&1 | tail -n 3
```
Expected：`23 passed`。

- [ ] **Step 5: 跑全套**

```bash
cd $REPO/taskgen/v2 && $P -m pytest -q  2>&1 | tail -n 3
```
Expected：`163 passed`。

- [ ] **Step 6: 用开发集确认解析器的改动**

计划 3 那 316 条的首票回答在 `$S/dev_votes.jsonl`（写计划时留下的；不在就跳过这一步，在账本里记一句）：

```bash
cd $REPO/taskgen/v2 && $P -c "
import sys, json; sys.path[:0] = ['.', '../common']
from collections import Counter
from taskgen_v2 import verify
c = Counter()
for l in open('$S/dev_votes.jsonl'):
    r = json.loads(l)
    if 'content' in r:
        c[(r['verdict'], verify.parse_verdict(r['content']))] += 1
print(c)"
```
Expected：`Counter({('yes', 'yes'): 332, ('unparsed', 'unparsed'): 5, ('no', 'no'): 3, ('unparsed', 'yes'): 1})`。只有那一条 "Is the answer correct? Yes" 变了；5 条 `unparsed` 是回答为空的，新代码会把它们记成 `Truncated`，不算票。

- [ ] **Step 7: commit**

```bash
cd $REPO
git add taskgen/v2/taskgen_v2/verify.py \
        taskgen/v2/taskgen_v2/convert.py \
        taskgen/v2/scripts/taskgen.py \
        taskgen/v2/tests/test_taskgen_verify.py \
        taskgen/v2/tests/test_taskgen_convert_env.py \
        taskgen/v2/tests/test_taskgen_cli.py
git diff --cached --name-only
git commit -m "feat(taskgen v2): several verifier models with their votes, the profile's data quirks, cut-off votes asked again

TASKGEN_VERIFY_MODELS (model:votes,...) picks the models, on TASKGEN_VERIFY_BASE_URL; each passes a task when
its Yes votes outnumber its No votes, and every model must pass it (design 4.6). The verifier now reads the
profile's data quirks: address keeps congress surnames in first_name, and without that note a correct gold was
rejected three times out of three. A vote that spent its tokens thinking is not a No but a failed call, asked
again on the next run; the verdict line is read even without "(Yes/No)". The verify command runs after the
pre-cap. Task meta records every model's votes and the profile version.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```
Expected：暂存区只有这 6 个文件。

---

### Task 4: 改坏金标准：五种改法，和比较两份 SQL 留下的库

**Files:**
- Modify: `taskgen/v2/taskgen_v2/check.py`（新函数 `final_state`，`from collections import Counter`）
- Create: `taskgen/v2/taskgen_v2/corrupt.py`
- Test: `taskgen/v2/tests/test_taskgen_check.py`、`taskgen/v2/tests/test_taskgen_corrupt.py`（新）

**Interfaces:**
- Consumes: `check.split_statements`、`check.write_target`、`check.at_instant`、`check.INSTANTS`、`check.VOLATILE_COL_RE`、`check._memory_copy`（都已存在）。
- Produces:
  - `check.final_state(db_path, stmts) -> {表名小写: (加上的行, 去掉的行)} | None`：在库的新副本上按顺序执行（时钟固定在 `INSTANTS[0]`），只比较语句碰过的行（临时触发器记 rowid），去掉评测哈希不比的列，重复的行按次数算；有语句出错返回 `None`。两份 SQL 留下的库一样，当且仅当两者的 `final_state` 相等。23 个库和 DySQL 的 13 个库都没有 WITHOUT ROWID 表（写计划时查过）。
  - `corrupt.KINDS = ("literal", "where", "set_column", "drop_last", "swap_values")`；`corrupt.corrupt(cand, kind, rng, conn) -> cand | None`（`actions` 换成改坏的语句，一条语句一个 action；改不了返回 `None`）；`corrupt.statements(cand) -> [str]`。Task 5 的 `calibrate.negatives` 用它们。

- [ ] **Step 1: 写失败的测试**

`tests/test_taskgen_check.py` 末尾加：

```python
def test_final_state_compares_what_the_statements_leave_behind(tmp_path):
    db = make_db(tmp_path, "shop", SHOP + "CREATE TABLE tags (name TEXT, last_update TEXT); INSERT INTO tags VALUES ('a', 'x');")
    fs = lambda *s: check.final_state(db, list(s))
    assert fs("UPDATE orders SET qty = 3 WHERE order_id = 5") == fs("UPDATE orders SET qty = 3 WHERE order_id IN (5)")
    assert fs("UPDATE orders SET qty = 3 WHERE order_id = 5") != fs("UPDATE orders SET qty = 3 WHERE order_id = 6")
    assert fs("UPDATE orders SET qty = 3 WHERE order_id = 5") == {"orders": ([(5, 5, 5, 3)], [(5, 5, 5, 1)])}
    assert fs("UPDATE orders SET qty = 1 WHERE order_id = 5") == {"orders": ([], [])}          # touched, not changed
    assert fs("INSERT INTO tags VALUES ('a', 'y')") != fs("INSERT INTO tags VALUES ('a', 'y')", "INSERT INTO tags VALUES ('a', 'z')")
    assert fs("INSERT INTO tags VALUES ('b', 'y')") == fs("INSERT INTO tags VALUES ('b', 'z')")   # last_update is not compared
    assert fs("UPDATE nope SET x = 1") is None
```

`tests/test_taskgen_check.py` 末尾加：

```python
def test_final_state_reads_the_clock_at_a_fixed_instant(tmp_path):
    db = make_db(tmp_path, "shop", SHOP + "CREATE TABLE notes (customer_id INTEGER, at TEXT);")
    a = check.final_state(db, ["INSERT INTO notes VALUES (5, CURRENT_TIMESTAMP)"])
    time.sleep(1.1)
    assert a == check.final_state(db, ["INSERT INTO notes VALUES (5, datetime('now'))"]) == {"notes": ([(5, check.INSTANTS[0])], [])}
```

新建 `tests/test_taskgen_corrupt.py`：

```python
# tests/test_taskgen_corrupt.py
import random, sqlite3
from taskgen_common.testing import make_db, SHOP
from taskgen_v2 import corrupt


def cand(*sqls):
    return {"id": "t", "instruction": "x", "actions": [{"sql": s} for s in sqls]}


def variants(fn, c, conn=None, n=200):
    return {tuple(corrupt.statements(b)) for s in range(n) if (b := fn(c, random.Random(s), conn))}


def test_change_literal_takes_another_value_of_the_same_kind_from_the_task():
    c = cand("UPDATE orders SET qty = 3 WHERE order_id = 5", "UPDATE customers SET first_name = 'Ann' WHERE customer_id = 7")
    second = "UPDATE customers SET first_name = 'Ann' WHERE customer_id = {}"
    first = "UPDATE orders SET qty = {} WHERE order_id = {}"
    assert variants(corrupt.change_literal, c) == {
        (first.format(5, 5), second.format(7)), (first.format(7, 5), second.format(7)),
        (first.format(3, 3), second.format(7)), (first.format(3, 7), second.format(7)),
        (first.format(3, 5), second.format(3)), (first.format(3, 5), second.format(5))}   # the one string has no partner
    assert corrupt.change_literal(cand("DELETE FROM orders WHERE order_id = 5"), random.Random(0)) is None


def test_swap_values_trades_two_literals_of_one_statement():
    c = cand("INSERT INTO orders (order_id, customer_id, product_id, qty) VALUES (500, 7, 9, 7)")
    head = "INSERT INTO orders (order_id, customer_id, product_id, qty) VALUES "
    assert variants(corrupt.swap_values, c) == {(head + v,) for v in (
        "(7, 500, 9, 7)", "(7, 7, 9, 500)", "(9, 7, 500, 7)", "(500, 9, 7, 7)", "(500, 7, 7, 9)")}   # the two 7s never trade
    assert corrupt.swap_values(cand("DELETE FROM orders WHERE order_id = 5"), random.Random(0)) is None


def test_drop_where_removes_one_condition_or_the_whole_clause():
    assert variants(corrupt.drop_where, cand("UPDATE orders SET qty = 3 WHERE order_id = 5 AND customer_id = 5")) == {
        ("UPDATE orders SET qty = 3 WHERE customer_id = 5",), ("UPDATE orders SET qty = 3 WHERE order_id = 5",)}
    assert variants(corrupt.drop_where, cand("DELETE FROM orders WHERE order_id = 5")) == {("DELETE FROM orders",)}
    for keep in ("UPDATE orders SET qty = 3 WHERE order_id = 5 OR order_id = 6",
                 "DELETE FROM orders WHERE order_id BETWEEN 5 AND 9",
                 "INSERT INTO orders (order_id, qty) SELECT 500, qty FROM orders WHERE order_id = 5"):
        assert corrupt.drop_where(cand(keep), random.Random(0)) is None


def test_set_column_writes_another_non_key_column_of_the_same_type(tmp_path):
    conn = sqlite3.connect(make_db(tmp_path, "shop", SHOP))
    assert variants(corrupt.set_column, cand("UPDATE orders SET qty = 3 WHERE order_id = 5"), conn) == {
        ('UPDATE orders SET "customer_id" = 3 WHERE order_id = 5',), ('UPDATE orders SET "product_id" = 3 WHERE order_id = 5',)}
    assert variants(corrupt.set_column, cand('UPDATE "customers" SET "first_name" = \'Z\' WHERE customer_id = 1'), conn) == {
        ('UPDATE "customers" SET "last_name" = \'Z\' WHERE customer_id = 1',)}
    assert corrupt.set_column(cand("UPDATE products SET price = 2.5 WHERE product_id = 1"), random.Random(0), conn) is None   # no other REAL


def test_drop_last_needs_two_writes():
    c = cand("SELECT 1", "UPDATE orders SET qty = 3 WHERE order_id = 5", "DELETE FROM orders WHERE order_id = 6")
    assert corrupt.statements(corrupt.drop_last(c)) == ["SELECT 1", "UPDATE orders SET qty = 3 WHERE order_id = 5"]
    assert corrupt.drop_last(cand("UPDATE orders SET qty = 3 WHERE order_id = 5")) is None


def test_a_changed_literal_keeps_its_quotes(tmp_path):
    conn = sqlite3.connect(make_db(tmp_path, "shop", SHOP))
    c = cand("UPDATE customers SET last_name = 'O''Brien' WHERE first_name = 'Ann'")
    for v in variants(corrupt.change_literal, c) | variants(corrupt.swap_values, c):
        conn.execute(v[0])   # still valid SQL
    assert ("UPDATE customers SET last_name = 'Ann' WHERE first_name = 'O''Brien'",) in variants(corrupt.swap_values, c)
```

- [ ] **Step 2: 跑测试，确认失败**

```bash
cd $REPO/taskgen/v2 && $P -m pytest -q tests/test_taskgen_check.py 2>&1 | tail -n 3
```
Expected：`2 failed, 51 passed`。失败的是：
- `test_final_state_compares_what_the_statements_leave_behind`
- `test_final_state_reads_the_clock_at_a_fixed_instant`

再跑新的测试文件：

```bash
cd $REPO/taskgen/v2 && $P -m pytest -q tests/test_taskgen_corrupt.py 2>&1 | tail -n 3
```
Expected：`1 error`。
收集出错：
- `ERROR tests/test_taskgen_corrupt.py`
（收集时就因为 `taskgen_v2.corrupt` 不存在而出错。）

- [ ] **Step 3: 实现**

`taskgen_v2/check.py` 里把

```python
import json, re, sqlite3, unicodedata
```

换成：

```python
import json, re, sqlite3, unicodedata
from collections import Counter
```

`taskgen_v2/check.py` 里把

```python
def run_check(db_rec, cand, anchor=None
```

换成：

```python
def final_state(db_path, stmts):
    """How the statements leave the tables they write, as the eval hash sees them: per table, the rows (non-volatile
    columns) added and removed against the original file, as sorted lists that keep duplicates. Run on a fresh copy
    with the clock read at INSTANTS[0]; None when a statement fails. Temporary triggers note the rowids a statement
    touches, so only those rows are compared (eu_soccer's Match has 26k rows of 115 columns)."""
    db = _memory_copy(db_path)
    try:
        db.execute("ATTACH DATABASE ? AS orig", (db_path,))
        db.execute("CREATE TEMP TABLE _touched (t TEXT, r INTEGER)")
        tables = sorted({w[1].lower() for st in stmts if (w := write_target(st))})
        for n, t in enumerate(tables):
            for ev, ref in (("INSERT", "NEW"), ("UPDATE", "OLD"), ("UPDATE", "NEW"), ("DELETE", "OLD")):
                db.execute(f"CREATE TEMP TRIGGER _f{n}_{ev}_{ref} AFTER {ev} ON main.{_q(t)} BEGIN "
                           f"INSERT INTO _touched VALUES ('{n}', {ref}.rowid); END")
        for st in stmts:
            db.execute(at_instant(st, INSTANTS[0])).fetchall()
        out = {}
        for n, t in enumerate(tables):
            cols = [r[1] for r in db.execute(f"PRAGMA main.table_info({_q(t)})")]
            keep = ", ".join(_q(c) for c in cols if not VOLATILE_COL_RE.match(c)) or "1"
            now, before = (Counter(db.execute(f"SELECT {keep} FROM {s}.{_q(t)} WHERE rowid IN "
                                              f"(SELECT r FROM _touched WHERE t = '{n}')").fetchall()) for s in ("main", "orig"))
            out[t] = (sorted((now - before).elements(), key=repr), sorted((before - now).elements(), key=repr))
        return out
    except sqlite3.Error:
        return None
    finally:
        db.close()


def run_check(db_rec, cand, anchor=None
```

新建 `taskgen_v2/corrupt.py`：

```python
# taskgen/v2/taskgen_v2/corrupt.py
"""Five ways to break a task's SQL while its instruction stays, for the verifier's calibration (design D5): change a
literal, drop a WHERE condition, change the column an UPDATE sets, drop the last write, swap two values. A broken
task counts as a negative only when it still passes the execution check and ends in another database state --
the mistakes only the verifier can catch (calibrate.negatives filters them)."""
import sqlparse
from sqlparse import sql as S, tokens as T
from taskgen_common.db_select import _q
from taskgen_v2 import check

KINDS = ("literal", "where", "set_column", "drop_last", "swap_values")


def statements(cand):
    return [st for a in cand["actions"] for st in check.split_statements(a["sql"])]


def _render(stmt, new):
    """The statement's text with some leaf tokens replaced: new is {id(token): text}."""
    return "".join(new.get(id(t), t.value) for t in stmt.flatten())


def _literal_tokens(stmt):
    return [t for t in stmt.flatten() if t.ttype in T.Literal.String.Single or t.ttype in T.Literal.Number]


def _kind(tok):
    return "str" if tok.ttype in T.Literal.String.Single else "num"


def _writes(stmts):
    return [i for i, st in enumerate(stmts) if check.write_target(st)]


def _with(cand, stmts):
    return {**cand, "actions": [{"sql": st} for st in stmts]}


def change_literal(cand, rng, conn=None):
    """One literal of a write becomes another value of the same kind that the task's writes use elsewhere (an
    amount for another amount, a name for another name), so the check's literal rule still holds."""
    stmts = statements(cand)
    parsed = {i: sqlparse.parse(stmts[i])[0] for i in _writes(stmts)}
    toks = [(i, t) for i, p in parsed.items() for t in _literal_tokens(p)]
    pairs = [(i, t, u.value) for i, t in toks for _, u in toks if _kind(u) == _kind(t) and u.value != t.value]
    if not pairs:
        return None
    i, t, v = rng.choice(pairs)
    return _with(cand, stmts[:i] + [_render(parsed[i], {id(t): v})] + stmts[i + 1:])


def swap_values(cand, rng, conn=None):
    """Two different literals of one write trade places (two new values, or a value and a key)."""
    stmts = statements(cand)
    opts = []
    for i in _writes(stmts):
        p = sqlparse.parse(stmts[i])[0]
        lits = _literal_tokens(p)
        opts += [(i, p, a, b) for x, a in enumerate(lits) for b in lits[x + 1:] if a.value != b.value]
    if not opts:
        return None
    i, p, a, b = rng.choice(opts)
    return _with(cand, stmts[:i] + [_render(p, {id(a): b.value, id(b): a.value})] + stmts[i + 1:])


def _conjuncts(where):
    """The top-level AND-ed conditions of a WHERE clause as token lists; None when it has a top-level OR or a
    BETWEEN (whose AND is not a conjunction)."""
    parts, cur = [], []
    for t in where.tokens[1:]:
        if t.ttype is T.Keyword and t.normalized in ("OR", "BETWEEN"):
            return None
        if t.ttype is T.Keyword and t.normalized == "AND":
            parts.append(cur); cur = []
        else:
            cur.append(t)
    parts.append(cur)
    return [p for p in parts if "".join(x.value for x in p).strip()]


def drop_where(cand, rng, conn=None):
    """An UPDATE or DELETE loses one of its AND-ed WHERE conditions, or its whole WHERE when it has only one."""
    stmts = statements(cand)
    opts = []
    for i in _writes(stmts):
        if check.write_target(stmts[i])[0] == "INSERT":
            continue
        p = sqlparse.parse(stmts[i])[0]
        where = next((t for t in p.tokens if isinstance(t, S.Where)), None)
        parts = _conjuncts(where) if where else None
        if parts:
            opts += [(i, p, where, parts, k) for k in range(len(parts))]
    if not opts:
        return None
    i, p, where, parts, k = rng.choice(opts)
    rest = [p for j, p in enumerate(parts) if j != k]
    clause = (" WHERE " + " AND ".join("".join(x.value for x in q).strip() for q in rest)) if rest else ""
    head = "".join(t.value for t in p.tokens[:p.tokens.index(where)]).rstrip()
    return _with(cand, stmts[:i] + [head + clause] + stmts[i + 1:])


def set_column(cand, rng, conn):
    """An UPDATE sets another column of the same table and declared type instead of the one asked for (not a key
    column, not one the statement already sets)."""
    stmts = statements(cand)
    opts = []
    for i in _writes(stmts):
        op, table = check.write_target(stmts[i])
        if op != "UPDATE":
            continue
        p = sqlparse.parse(stmts[i])[0]
        k = next((x for x, t in enumerate(p.tokens) if t.ttype is T.Keyword and t.normalized == "SET"), None)
        nxt = next((t for t in p.tokens[k + 1:] if not t.is_whitespace), None) if k is not None else None
        comps = ([c for c in nxt.get_sublists() if isinstance(c, S.Comparison)] if isinstance(nxt, S.IdentifierList)
                 else [nxt] if isinstance(nxt, S.Comparison) else [])
        info = conn.execute(f"PRAGMA table_info({_q(table)})").fetchall()
        types = {r[1].lower(): (r[2] or "").upper() for r in info}
        keys = {r[1].lower() for r in info if r[5]}
        used = {c.left.get_real_name().lower() for c in comps if c.left.get_real_name()}
        for c in comps:
            col = (c.left.get_real_name() or "").lower()
            if col not in types:
                continue
            for r in info:
                if r[1].lower() not in used | keys and (r[2] or "").upper() == types[col]:
                    opts.append((i, p, c, r[1]))
    if not opts:
        return None
    i, p, c, new = rng.choice(opts)
    leaves = list(c.left.flatten())
    return _with(cand, stmts[:i] + [_render(p, {id(leaves[0]): _q(new), **{id(x): "" for x in leaves[1:]}})] + stmts[i + 1:])


def drop_last(cand, rng=None, conn=None):
    """The last write statement is gone (tasks with two writes or more)."""
    stmts = statements(cand)
    w = _writes(stmts)
    if len(w) < 2:
        return None
    return _with(cand, stmts[:w[-1]] + stmts[w[-1] + 1:])


FUNCS = {"literal": change_literal, "where": drop_where, "set_column": set_column, "drop_last": drop_last,
         "swap_values": swap_values}


def corrupt(cand, kind, rng, conn):
    """The task with its SQL broken in the given way, or None when the SQL offers no place for it."""
    return FUNCS[kind](cand, rng, conn)
```

- [ ] **Step 4: 跑测试，确认通过**

```bash
cd $REPO/taskgen/v2 && $P -m pytest -q tests/test_taskgen_check.py tests/test_taskgen_corrupt.py 2>&1 | tail -n 3
```
Expected：`59 passed`。

- [ ] **Step 5: 跑全套**

```bash
cd $REPO/taskgen/v2 && $P -m pytest -q  2>&1 | tail -n 3
```
Expected：`171 passed`。

- [ ] **Step 6: commit**

```bash
cd $REPO
git add taskgen/v2/taskgen_v2/check.py \
        taskgen/v2/taskgen_v2/corrupt.py \
        taskgen/v2/tests/test_taskgen_check.py \
        taskgen/v2/tests/test_taskgen_corrupt.py
git diff --cached --name-only
git commit -m "feat(taskgen v2): five ways to break a gold, and the state two SQL lists leave behind

corrupt.py breaks a task's writes for the verifier's negatives (design D5): another value of the same kind
from the task, one WHERE condition dropped, another column of the same type set, the last write dropped, two
values swapped. check.final_state compares what two lists of statements leave in the tables they write, as
the eval hash sees them; temporary triggers note the touched rowids, so eu_soccer's 26k-row Match table is
compared in 0.3 s instead of 5.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```
Expected：暂存区只有这 4 个文件。

---

### Task 5: 校准工具：三组样本、投票规则、标注表、复核页、报告

**Files:**
- Create: `taskgen/v2/taskgen_v2/calibrate.py`
- Create: `taskgen/v2/scripts/verify_calibrate.py`
- Test: `taskgen/v2/tests/test_taskgen_calibrate.py`（新）

**Interfaces:**
- Consumes: Task 3 的 `verify.run`、`verify.models_from_env`；Task 4 的 `check.final_state`、`corrupt.*`；`dysql.ENVS`、`dysql.db_rec`、`dysql.candidates`；`check.run_check_safe`。
- Produces:
  - 条目（item）：候选的样子，加 `"db"`（`"dysql:<env>"` 或 db key，如 `"bird:beer_factory"`）和 `"set"`（`positives` / `negatives` / `labeled`）；负样本另有 `"kind"`、`"source"`（`dysql` / `v2`）、`"of"`（原题 id），id 是 `<原题 id>#<kind>`。
  - `calibrate.RULES = {"1 vote": 1, "2 votes, both Yes": 2, "3 votes, 2 Yes": 3}`；`calibrate.verdict(rec, k) -> "pass" | "fail" | None`；`calibrate.metrics(items, votes, labels)`；`calibrate.choose_rule(m, floor=0.95) -> 规则名 | None`。
  - `labels.jsonl` 一行一条：`{"id", "label": "good"|"bad", "reason": calibrate.REASONS 之一或 null, "unsure": bool, "note", "by": "claude"|"user"}`，同一个 id 后写的覆盖先写的。
  - `scripts/verify_calibrate.py build / vote / sheet / review / report --dir <目录>`；Task 6、7 用它。

- [ ] **Step 1: 写失败的测试**

新建 `tests/test_taskgen_calibrate.py`：

```python
# tests/test_taskgen_calibrate.py
import random
from taskgen_common.testing import make_db
from v2_fixtures import SHOP2, FKS, CUSTOMER, STAFF, SHOP_PROFILE
from taskgen_v2 import calibrate, check, corrupt, io


def votes(*vs):
    return {"votes": [{"verdict": "error", "error": "Truncated: x"} if v == "err" else {"verdict": v} for v in vs]}


def item(i, s, **kw):
    return {"id": i, "set": s, **kw}


def test_verdict_takes_the_first_k_real_votes():
    r = votes("yes", "err", "no", "yes")
    assert calibrate.verdict(r, 1) == "pass" and calibrate.verdict(r, 2) == "fail" and calibrate.verdict(r, 3) == "pass"
    assert calibrate.verdict(votes("yes"), 2) is None and calibrate.verdict(None, 1) is None
    assert calibrate.verdict(votes("unparsed", "yes", "yes"), 3) == "pass" and calibrate.verdict(votes("unparsed"), 1) == "fail"


def test_metrics_per_rule_and_the_rule_choice():
    items = ([item(f"p{i}", "positives") for i in range(20)]
             + [item(f"n{i}", "negatives", source="dysql", kind="where") for i in range(10)]
             + [item("g", "labeled"), item("b", "labeled"), item("u", "labeled")])
    v = {f"p{i}": votes("yes", "yes", "yes") for i in range(19)}
    v["p19"] = votes("yes", "no", "yes")                                   # passes with one or three votes, not two
    v.update({f"n{i}": votes("no", "no", "no") for i in range(5)})
    v.update({f"n{i}": votes("yes", "no", "no") for i in range(5, 8)})     # caught by two and three votes only
    v.update({f"n{i}": votes("yes", "yes", "yes") for i in range(8, 10)})
    v.update(g=votes("yes", "yes", "yes"), b=votes("no", "no", "yes"), u=votes("yes", "yes", "yes"))
    labels = {"g": {"label": "good"}, "b": {"label": "bad"}}               # u is not labeled yet
    m = calibrate.metrics(items, v, labels)
    assert m["1 vote"]["positives_pass"] == (1.0, 20, 20) and m["2 votes, both Yes"]["positives_pass"] == (0.95, 19, 20)
    assert m["1 vote"]["negatives_reject"] == (0.5, 5, 10) and m["2 votes, both Yes"]["negatives_reject"] == (0.8, 8, 10)
    assert m["3 votes, 2 Yes"]["negatives_by_kind"] == {("dysql", "where"): (0.8, 8, 10)}
    assert m["3 votes, 2 Yes"]["labeled_good_pass"] == (1.0, 1, 1)
    assert m["3 votes, 2 Yes"]["labeled_bad_reject"] == (1.0, 1, 1) and m["3 votes, 2 Yes"]["labeled_precision"] == (1.0, 1, 1)
    assert calibrate.choose_rule(m) == "2 votes, both Yes"                 # as many negatives as three votes, fewer calls
    assert calibrate.choose_rule(m, floor=0.99) == "3 votes, 2 Yes"        # two votes lose a good task
    v["g"] = votes("no", "no", "no")
    assert calibrate.choose_rule(calibrate.metrics(items, v, labels)) is None


def test_the_users_label_replaces_claudes_and_disagreements_are_shown():
    rows = [{"id": "a", "label": "good", "by": "claude"}, {"id": "b", "label": "bad", "reason": "unclear", "by": "claude"},
            {"id": "c", "label": "good", "unsure": True, "by": "claude"}, {"id": "a", "label": "bad", "reason": "extra", "by": "user"}]
    labels = calibrate.final_labels(rows)
    assert labels["a"]["by"] == "user" and labels["a"]["label"] == "bad"
    items = [item(x, "labeled") for x in "abcd"]
    v = {"a": votes("no", "no", "no"), "b": votes("yes", "yes", "no"), "c": votes("yes", "yes", "yes"), "d": votes("no", "no", "no")}
    assert [i["id"] for i in calibrate.disagreements(items, v, labels)] == ["b", "c"]   # a agrees now, d has no label


def shop_dbs(tmp_path):
    db = make_db(tmp_path, "shop2", SHOP2)
    rec = {"source": "test", "db": "shop2", "path": db, "anchors": [CUSTOMER, STAFF], "fks": FKS}
    return calibrate.Databases({"test:shop2": rec}, {"test:shop2": SHOP_PROFILE}), db


def cand(i, sql, instruction):
    return {"id": f"test:shop2:customers:5:{i}", "db": "test:shop2", "set": "labeled", "anchor_table": "customers",
            "key_value": 5, "plan": {"task_type": "1_self"}, "instruction": instruction, "actions": [{"sql": sql}]}


def test_negatives_still_pass_the_check_and_end_elsewhere(tmp_path):
    dbs, path = shop_dbs(tmp_path)
    items = [cand(0, "UPDATE orders SET qty = 3 WHERE order_id = 5 AND customer_id = 5", "I am a5 b5, customer 5. Set qty of my order 5 to 3."),
             cand(1, "UPDATE orders SET qty = 2 WHERE order_id = 65", "I am a5 b5, customer 5. Set qty of my order 65 to 2.")]
    assert all(dbs.check(i)["ok"] for i in items)
    neg = calibrate.negatives(items, dbs, 5, random.Random(0), "v2")
    assert {n["kind"] for n in neg} == {"literal", "where", "set_column"}   # one write each: no drop_last
    for n in neg:
        gold = next(i for i in items if i["id"] == n["of"])
        assert n["id"] == f"{gold['id']}#{n['kind']}" and n["set"] == "negatives" and n["source"] == "v2"
        assert dbs.check(n)["ok"] and check.final_state(path, corrupt.statements(n)) != check.final_state(path, corrupt.statements(gold))
    assert not any(n["kind"] == "swap_values" for n in neg)   # every swap here misses its row: the check rejects it
    assert len(calibrate.negatives(items, dbs, 1, random.Random(0), "v2")) <= len(corrupt.KINDS)


def test_v2_items_are_the_checked_candidates_keyed_by_database(tmp_path):
    d = tmp_path / "run" / "shop2"
    d.mkdir(parents=True)
    io.append_jsonl(d / "candidates.jsonl", [{"id": "test:shop2:customers:5:0", "db": "shop2"}, {"id": "test:shop2:customers:6:0", "db": "shop2"}])
    io.append_jsonl(d / "check.jsonl", [{"id": "test:shop2:customers:5:0", "ok": True}, {"id": "test:shop2:customers:6:0", "ok": False}])
    assert calibrate.v2_items([str(tmp_path / "run")]) == [{"id": "test:shop2:customers:5:0", "db": "test:shop2", "set": "labeled"}]
```

- [ ] **Step 2: 跑测试，确认失败**

```bash
cd $REPO/taskgen/v2 && $P -m pytest -q tests/test_taskgen_calibrate.py 2>&1 | tail -n 3
```
Expected：`1 error`。
收集出错：
- `ERROR tests/test_taskgen_calibrate.py`
（收集时就因为 `taskgen_v2.calibrate` 不存在而出错。）

- [ ] **Step 3: 实现**

新建 `taskgen_v2/calibrate.py`：

```python
# taskgen/v2/taskgen_v2/calibrate.py
"""The verifier's calibration (design §4.6, D5). Three sets, each item a candidate-shaped record with a "db" key that
says which database it runs on ("dysql:<env>" for DySQL-Bench's own, a db key such as "bird:beer_factory" otherwise):
- positives: DySQL gold that passes the v2 check (good tasks; DySQL was filtered with DeepSeek-R1, so this pass rate
  is an upper bound, design D5);
- negatives: good tasks broken by corrupt.py that still pass the check and end in another state (bad tasks only the
  verifier can catch), from DySQL gold and from v2 candidates;
- labeled: v2 candidates that passed the check, labeled good or bad by hand (labels.jsonl).
Every item gets three votes; RULES turn them into verdicts, so one run compares one, two and three votes."""
import glob, os, random, sqlite3
from collections import Counter, defaultdict
from taskgen_v2 import check, corrupt, db_profile, dysql, io, schema

RULES = {"1 vote": 1, "2 votes, both Yes": 2, "3 votes, 2 Yes": 3}
REASONS = ("missing", "extra", "unclear", "wrong_rows", "other")   # design §4.6: SQL misses / adds / instruction unclear / wrong rows / other


class Databases:
    """db key -> what checking and verifying an item needs: the db record, its file, its profile (None for DySQL),
    the DDL and the data notes for the verifier. Built once per database."""

    def __init__(self, recs=None, profiles=None):
        self.recs, self.profiles, self.cache = recs, profiles, {}

    def get(self, key):
        if key not in self.cache:
            if key.startswith("dysql:"):
                rec = dysql.db_rec(key.split(":", 1)[1])
                path, prof = rec["path"], None
            else:
                self.recs = self.recs or io.load_db_recs()
                self.profiles = self.profiles or db_profile.load()
                rec, prof = self.recs[key], self.profiles[key]
                path = io.resolve_db_path(rec["path"])
            self.cache[key] = {"rec": rec, "path": path, "profile": prof, "ddl": schema.ddl(path),
                               "notes": list(prof["quirks"]) if prof else []}
        return self.cache[key]

    def check(self, item):
        d = self.get(item["db"])
        return check.run_check_safe(d["rec"], item, profile=d["profile"])

    def context(self, item):
        d = self.get(item["db"])
        return d["ddl"], d["notes"]


def positives(envs=None):
    """DySQL gold that changes the database and passes the v2 check, as items."""
    out = []
    for env in envs or dysql.ENVS:
        rec = dysql.db_rec(env)
        for c in dysql.candidates(env):
            if c["group"] != "7_no_change" and check.run_check(rec, c)["ok"]:
                out.append({**c, "db": f"dysql:{env}", "set": "positives"})
    return out


def v2_items(roots):
    """The v2 candidates under roots (results/<run>/<db>/) that passed the check, as items keyed by db key (the id
    is <db key>:<root table>:<key value>:<n>)."""
    out = []
    for d in sorted(p for root in roots for p in glob.glob(os.path.join(root, "*")) if os.path.isdir(p)):
        ok = {r["id"] for r in io.read_jsonl(os.path.join(d, "check.jsonl")) if r["ok"]}
        out += [{**c, "db": c["id"].rsplit(":", 3)[0], "set": "labeled"}
                for c in io.read_jsonl(os.path.join(d, "candidates.jsonl")) if c["id"] in ok]
    return out


def negatives(items, dbs, per_kind, rng, source, tries=3):
    """Up to per_kind broken copies of the items for every corruption kind, spread over databases (round robin over
    each database's shuffled items). A copy is kept only when it still passes the check and ends in another state;
    an item gets `tries` draws per kind to find one."""
    by_db = defaultdict(list)
    for it in items:
        by_db[it["db"]].append(it)
    for v in by_db.values():
        rng.shuffle(v)
    order = [it for row in _round_robin(sorted(by_db), by_db) for it in row]
    out, conns = [], {}
    for kind in corrupt.KINDS:
        n = 0
        for it in order:
            if n >= per_kind:
                break
            d = dbs.get(it["db"])
            conn = conns.setdefault(it["db"], sqlite3.connect(f"file:{d['path']}?mode=ro", uri=True))
            gold = None
            for t in range(tries):
                bad = corrupt.corrupt(it, kind, random.Random(f"{it['id']}:{kind}:{t}"), conn)
                if bad is None:
                    break   # the SQL has no place for this kind
                gold = gold or check.final_state(d["path"], corrupt.statements(it))
                after = check.final_state(d["path"], corrupt.statements(bad))
                neg = {**bad, "id": f"{it['id']}#{kind}", "set": "negatives", "kind": kind, "source": source, "of": it["id"]}
                if after is not None and after != gold and dbs.check(neg)["ok"]:
                    out.append(neg); n += 1
                    break
    return out


def _round_robin(keys, groups):
    rows, i = [], 0
    while any(i < len(groups[k]) for k in keys):
        rows.append([groups[k][i] for k in keys if i < len(groups[k])])
        i += 1
    return rows


def verdict(rec, k):
    """'pass' / 'fail' under the k-vote rule (the first k real votes; Yes must outnumber No), None while fewer than
    k votes exist (a vote cut off while thinking is retried, not counted)."""
    votes = [v for v in (rec or {}).get("votes", []) if "error" not in v][:k]
    if len(votes) < k:
        return None
    yes = sum(v["verdict"] == "yes" for v in votes)
    return "pass" if yes > len(votes) - yes else "fail"


def _rate(xs):
    xs = [x for x in xs if x is not None]
    return (sum(xs) / len(xs), sum(xs), len(xs)) if xs else (None, 0, 0)


def metrics(items, votes, labels):
    """Per rule: positives' pass rate; negatives' rejection rate per (source, kind) and in all; on the labeled set the
    good tasks' pass rate and the bad tasks' rejection rate (recall) and the rejected tasks' share of bad (precision)."""
    out = {}
    for rule, k in RULES.items():
        v = {i["id"]: verdict(votes.get(i["id"]), k) for i in items}
        pos = [i for i in items if i["set"] == "positives"]
        neg = [i for i in items if i["set"] == "negatives"]
        lab = [i for i in items if i["set"] == "labeled" and i["id"] in labels]
        m = {"positives_pass": _rate([None if v[i["id"]] is None else v[i["id"]] == "pass" for i in pos]),
             "negatives_reject": _rate([None if v[i["id"]] is None else v[i["id"]] == "fail" for i in neg]),
             "negatives_by_kind": {}}
        for key in sorted({(i["source"], i["kind"]) for i in neg}):
            m["negatives_by_kind"][key] = _rate([None if v[i["id"]] is None else v[i["id"]] == "fail"
                                                 for i in neg if (i["source"], i["kind"]) == key])
        good = [i for i in lab if labels[i["id"]]["label"] == "good"]
        bad = [i for i in lab if labels[i["id"]]["label"] == "bad"]
        m["labeled_good_pass"] = _rate([None if v[i["id"]] is None else v[i["id"]] == "pass" for i in good])
        m["labeled_bad_reject"] = _rate([None if v[i["id"]] is None else v[i["id"]] == "fail" for i in bad])
        m["labeled_precision"] = _rate([labels[i["id"]]["label"] == "bad" for i in lab if v[i["id"]] == "fail"])
        out[rule] = m
    return out


def choose_rule(m, floor=0.95):
    """The rule to run with (design §3): of the rules whose positives and labeled good tasks both pass at >= floor,
    the one that rejects the most negatives; fewer votes on a tie. None when no rule keeps the good tasks."""
    ok = [r for r in RULES if (m[r]["positives_pass"][0] or 0) >= floor and (m[r]["labeled_good_pass"][0] or 0) >= floor]
    if not ok:
        return None
    return max(ok, key=lambda r: (m[r]["negatives_reject"][0] or 0, -RULES[r]))


def final_labels(rows):
    """labels.jsonl rows -> {id: row}; a later row for the same id (the user's review) replaces an earlier one."""
    out = {}
    for r in rows:
        out[r["id"]] = r
    return out


def disagreements(items, votes, labels, k=3):
    """Labeled items to show the user: Claude unsure, or Claude's label against the k-vote verdict."""
    out = []
    for i in items:
        lab, v = labels.get(i["id"]), verdict(votes.get(i["id"]), k)
        if lab and (lab.get("unsure") or (v is not None and (lab["label"] == "good") != (v == "pass"))):
            out.append(i)
    return out


def counts(items):
    c = Counter(i["set"] for i in items)
    c.update(f"negatives:{i['source']}:{i['kind']}" for i in items if i["set"] == "negatives")
    return dict(c)
```

新建 `scripts/verify_calibrate.py`：

```python
#!/usr/bin/env python3
"""The verifier's calibration (design §4.6, D5), one sub-command per step; files under --dir (results/, not git).
Usage (from taskgen/v2/):
  P=~/miniconda3/envs/dysql/bin/python; D=results/plan4/calib
  $P scripts/verify_calibrate.py build  --dir $D --labeled results/plan4/fresh   # items.jsonl: the three sets
  $P scripts/verify_calibrate.py vote   --dir $D --models deepseek-v4.1-flash:3   # votes.jsonl, resumable
  $P scripts/verify_calibrate.py sheet  --dir $D                                  # label_sheet.md for Claude
  $P scripts/verify_calibrate.py review --dir $D                                  # review.md for the user
  $P scripts/verify_calibrate.py report --dir $D                                  # report.md
labels.jsonl holds one row per labeled item: {"id", "label": "good"|"bad", "reason": one of calibrate.REASONS or
null, "unsure": bool, "note", "by": "claude"|"user"}; a later row for an id replaces an earlier one."""
import argparse, json, os, random, sys, time
V2 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [V2, os.path.join(os.path.dirname(V2), "common")]   # taskgen_v2, taskgen_common
from taskgen_v2 import calibrate, check, corrupt, io, verify
from taskgen_common.db_select import _q


def load(d):
    items = io.read_jsonl(os.path.join(d, "items.jsonl"))
    votes = {r["id"]: r for r in io.read_jsonl(os.path.join(d, "votes.jsonl"))}
    labels = calibrate.final_labels(io.read_jsonl(os.path.join(d, "labels.jsonl")))
    return items, votes, labels


def cmd_build(a):
    path = os.path.join(a.dir, "items.jsonl")
    if os.path.exists(path):
        sys.exit(f"{path} exists: the sets are built once, so votes and labels keep pointing at the same items")
    os.makedirs(a.dir, exist_ok=True)
    dbs = calibrate.Databases()
    pos = calibrate.positives()
    lab = calibrate.v2_items(a.labeled)
    neg = (calibrate.negatives(pos, dbs, a.per_kind_dysql, random.Random(a.seed), "dysql")
           + calibrate.negatives(lab, dbs, a.per_kind_v2, random.Random(a.seed), "v2"))
    io.append_jsonl(path, pos + neg + lab)
    print(json.dumps(calibrate.counts(pos + neg + lab), indent=1))


def cmd_vote(a):
    items, _, _ = load(a.dir)
    if a.set:
        items = [i for i in items if i["set"] in a.set]
    dbs = calibrate.Databases()
    t0 = time.time()
    s = verify.run(items, verify.models_from_env(a.models), os.path.join(a.dir, "votes.jsonl"), workers=a.workers,
                   context=dbs.context)
    print(f"{s} in {time.time() - t0:.0f}s")


def effect(path, stmts):
    """What the statements change, table by table: rows removed (-) and added (+) with column names."""
    st = check.final_state(path, stmts)
    if st is None:
        return ["(a statement fails)"]
    db = check._memory_copy(path)
    out = []
    for t, (added, removed) in st.items():
        cols = [r[1] for r in db.execute(f"PRAGMA table_info({_q(t)})") if not check.VOLATILE_COL_RE.match(r[1])]
        for sign, rows in (("-", removed), ("+", added)):
            out += [f"{sign} {t}: " + json.dumps(dict(zip(cols, r[:len(cols)])), ensure_ascii=False, default=str)[:400]
                    for r in rows[:6]]
            if len(rows) > 6:
                out.append(f"{sign} {t}: ... {len(rows) - 6} more rows")
    db.close()
    return out


def block(i, dbs, n):
    d = dbs.get(i["db"])
    chk = dbs.check(i)
    lines = [f"## {n}. {i['id']}", f"type {chk['task_type']} | template {chk['template']}", "", "**Instruction:** " + i["instruction"], "",
             "**SQL:**", "```sql", *corrupt.statements(i), "```", "", "**Effect:**", "```", *effect(d["path"], corrupt.statements(i)), "```"]
    return lines


def cmd_sheet(a):
    items, _, _ = load(a.dir)
    dbs = calibrate.Databases()
    lab = [i for i in items if i["set"] == "labeled"]
    lines = [f"# Label sheet: {len(lab)} v2 candidates", "",
             "Label each: good, or bad with a reason (" + ", ".join(calibrate.REASONS) + "). Good means an agent that sees "
             "only the instruction and can query the database ends in the same database state as the SQL.", ""]
    for n, i in enumerate(lab, 1):
        lines += block(i, dbs, n) + [""]
    with open(os.path.join(a.dir, "label_sheet.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"wrote label_sheet.md: {len(lab)} items")


def cmd_review(a):
    items, votes, labels = load(a.dir)
    dbs = calibrate.Databases()
    show = calibrate.disagreements([i for i in items if i["set"] == "labeled"], votes, labels)
    lines = [f"# 需要你复核的 {len(show)} 条", "",
             "每条给出 Claude 的判断和校验模型的 3 票。请对每条回复 good 或 bad（bad 附原因）。", ""]
    for n, i in enumerate(show, 1):
        lab, v = labels[i["id"]], votes.get(i["id"], {})
        real = [x for x in v.get("votes", []) if "error" not in x]
        no = next((x for x in real if x["verdict"] != "yes"), None)
        lines += block(i, dbs, n) + [
            "", f"**Claude:** {lab['label']}" + (f" ({lab['reason']})" if lab.get("reason") else "")
            + (" — 拿不准" if lab.get("unsure") else "") + (f" — {lab['note']}" if lab.get("note") else ""),
            f"**校验模型:** " + " / ".join(x["verdict"] for x in real)]
        if no:
            lines += ["", "> " + no["content"][-700:].replace("\n", "\n> ")]
        lines.append("")
    with open(os.path.join(a.dir, "review.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"wrote review.md: {len(show)} items")


def pct(r):
    return "-" if r[0] is None else f"{100 * r[0]:.1f}% ({r[1]}/{r[2]})"


def cmd_report(a):
    items, votes, labels = load(a.dir)
    m = calibrate.metrics(items, votes, labels)
    rules = list(calibrate.RULES)
    lines = ["| | " + " | ".join(rules) + " |", "|---|" + "---|" * len(rules)]
    lines.append("| 正样本通过 | " + " | ".join(pct(m[r]["positives_pass"]) for r in rules) + " |")
    lines.append("| 负样本被拒（全部） | " + " | ".join(pct(m[r]["negatives_reject"]) for r in rules) + " |")
    for key in sorted(m[rules[0]]["negatives_by_kind"]):
        lines.append(f"| 负样本被拒 {key[0]} {key[1]} | " + " | ".join(pct(m[r]["negatives_by_kind"][key]) for r in rules) + " |")
    lines.append("| 标注集 好题通过 | " + " | ".join(pct(m[r]["labeled_good_pass"]) for r in rules) + " |")
    lines.append("| 标注集 坏题被拒（召回） | " + " | ".join(pct(m[r]["labeled_bad_reject"]) for r in rules) + " |")
    lines.append("| 标注集 被拒的是坏题（精度） | " + " | ".join(pct(m[r]["labeled_precision"]) for r in rules) + " |")
    allv = [x for r in votes.values() for x in r["votes"]]
    trunc = sum(x.get("error", "").startswith("Truncated") for x in allv)
    short = sum(1 for i in items if calibrate.verdict(votes.get(i["id"]), 3) is None)
    lines += ["", f"票数 {len(allv)}；思考被截断的 {trunc}；其它失败 {sum('error' in x for x in allv) - trunc}；"
              f"不满 3 票的条目 {short}；标注 {len(labels)} 条（用户复核 {sum(r.get('by') == 'user' for r in labels.values())}）。",
              "", f"按 calibrate.choose_rule 选出的规则：{calibrate.choose_rule(m) or '没有规则同时满足两条 95%'}"]
    text = "\n".join(lines)
    with open(os.path.join(a.dir, "report.md"), "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print(text)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("build"); p.add_argument("--dir", required=True); p.add_argument("--labeled", action="append", required=True)
    p.add_argument("--per-kind-dysql", type=int, default=60); p.add_argument("--per-kind-v2", type=int, default=40)
    p.add_argument("--seed", type=int, default=0); p.set_defaults(f=cmd_build)
    p = sub.add_parser("vote"); p.add_argument("--dir", required=True); p.add_argument("--models", required=True)
    p.add_argument("--set", action="append", help="positives / negatives / labeled (default: all)")
    p.add_argument("--workers", type=int, default=3, help="Ollama Pro plan limit: 3 concurrent requests"); p.set_defaults(f=cmd_vote)
    for name, f in (("sheet", cmd_sheet), ("review", cmd_review), ("report", cmd_report)):
        p = sub.add_parser(name); p.add_argument("--dir", required=True); p.set_defaults(f=f)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 跑测试，确认通过**

```bash
cd $REPO/taskgen/v2 && $P -m pytest -q tests/test_taskgen_calibrate.py 2>&1 | tail -n 3
```
Expected：`5 passed`。

- [ ] **Step 5: 跑全套**

```bash
cd $REPO/taskgen/v2 && $P -m pytest -q  2>&1 | tail -n 3
```
Expected：`176 passed`。

- [ ] **Step 6: 空目录上走一遍报告**

```bash
cd $REPO/taskgen/v2 && mkdir -p $S/empty && $P scripts/verify_calibrate.py report --dir $S/empty | tail -n 3
```
Expected：表里全是 `-`，最后一行是 `按 calibrate.choose_rule 选出的规则：没有规则同时满足两条 95%`。

- [ ] **Step 7: commit**

```bash
cd $REPO
git add taskgen/v2/taskgen_v2/calibrate.py \
        taskgen/v2/scripts/verify_calibrate.py \
        taskgen/v2/tests/test_taskgen_calibrate.py
git diff --cached --name-only
git commit -m "feat(taskgen v2): the verifier's calibration sets, rules and report

calibrate.py builds the three sets of design D5 (DySQL gold that passes the check; gold and v2 candidates broken
five ways that still pass the check and end elsewhere; v2 candidates labeled by hand), turns three votes per
item into the verdicts of a one-, two- and three-vote rule, and picks the rule that keeps 95% of the good tasks
and rejects the most broken ones. scripts/verify_calibrate.py runs it: build, vote, a label sheet for Claude, a
review page with the disagreements for the user, a report.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```
Expected：暂存区只有这 3 个文件。

---

### Task 6: 新出一批 v2 候选，组装三组样本，投票

**Files:**
- 本地，不进 git：`taskgen/v2/results/plan4/fresh/`（树、候选、检查结果）、`taskgen/v2/results/plan4/calib/`（`items.jsonl`、`votes.jsonl`）

**Interfaces:**
- Consumes: Task 1–5 的全部改动；23 份已确认的档案。
- Produces: Task 7 用的 `items.jsonl`、`votes.jsonl`。本任务不改代码，没有 commit。

- [ ] **Step 1: 建树：23 个库各 7 棵，seed 1**

```bash
cd $REPO/taskgen/v2
for DB in $($P -c "import json; print(' '.join(json.load(open('data/db_profiles.json'))))"); do
  $P scripts/taskgen.py trees --db $DB --n 7 --seed 1 --out-dir results/plan4/fresh/${DB#*:} || echo "FAILED $DB"
done 2>&1 | tee $S/fresh_trees.log | grep -c FAILED
cat results/plan4/fresh/*/trees.jsonl | wc -l
```
Expected：`0` 个失败；一共 161 棵树（college_2、school_scheduling 两个根分着建，合计也是 7 棵）。

- [ ] **Step 2: 出题和检查（GLM，约 20 分钟）**

```bash
cd $REPO/taskgen/v2
run() { $P scripts/taskgen.py generate --db $1 --workers 5 --out-dir $2 && \
        $P scripts/taskgen.py generate --db $1 --workers 5 --out-dir $2 --retry-errors && \
        $P scripts/taskgen.py check --db $1 --out-dir $2; }
{ for DB in $($P -c "import json; print(' '.join(json.load(open('data/db_profiles.json'))))"); do
    run $DB results/plan4/fresh/${DB#*:}
  done; } > $S/fresh_generate.log 2>&1
grep -E "^checked" $S/fresh_generate.log | awk '{n += $2; p += $4} END {print n, p}'
```
Expected：161 条候选，过检查约 150 条（计划 3 是 98.8%）。

- [ ] **Step 3: 计划 3 最后那几处修正在 GLM 上的效果**

```bash
cd $REPO/taskgen/v2 && $P scripts/task_stats.py --set fresh=results/plan4/fresh --out $S/fresh_stats.md && cat $S/fresh_stats.md
$P -c "
import glob, json
from collections import Counter
rs = Counter(); arch = n = 0
for d in glob.glob('results/plan4/fresh/*'):
    cands = {json.loads(l)['id']: json.loads(l) for l in open(d + '/candidates.jsonl')}
    for l in open(d + '/check.jsonl'):
        r = json.loads(l)
        rs.update(x.split(':')[0] for x in r['reasons'])
        if r['ok']:
            n += 1; arch += r['difficulty']['features']['archive']
print('passed', n, '| archive', arch, f'({100 * arch / n:.1f}%)', '| reasons', dict(rs))"
```
Expected：拒绝原因里 `archive_copy_changed` 是 0 或 1 条；archive 约 6%（161 条里有 10 条上下，样本小，4–14 条都算正常）。数字记下来，Task 7 写进验证记录。

- [ ] **Step 4: 组装三组样本**

```bash
cd $REPO/taskgen/v2 && $P scripts/verify_calibrate.py build --dir results/plan4/calib --labeled results/plan4/fresh
```
Expected（约 2 分钟）：`positives` 895；`negatives:dysql:*` 五类各 60；`negatives:v2:*` 五类各 40 或接近 40（`drop_last` 只能用写两条以上的题）；`labeled` 等于 Step 2 的过检查数。

- [ ] **Step 5: 投票（每条 3 票，约 3–4 小时，并发 3）**

```bash
cd $REPO/taskgen/v2 && $P scripts/verify_calibrate.py vote --dir results/plan4/calib --models deepseek-v4.1-flash:3 --workers 3 > $S/calib_vote.log 2>&1
$P scripts/verify_calibrate.py vote --dir results/plan4/calib --models deepseek-v4.1-flash:3 --workers 3 >> $S/calib_vote.log 2>&1
tail -n 2 $S/calib_vote.log
```
放后台跑。第二遍只补第一遍失败或被截断的票。被打断了就照原命令再跑，按 id 续投。
Expected：第二遍的 `verified` 很小（只剩补票的），`passed` + 未通过 = 条目数。

**Task 6 的完成条件**：`items.jsonl`、`votes.jsonl` 都在；`report` 显示"不满 3 票的条目"不超过 1%。不满 3 票的条目再跑一遍 `vote` 也补不齐，就记进账本，Task 7 报告单列。

---

### Task 7: 标注、复核、定规则、写验证记录

**Files:**
- Create: `taskgen/v2/docs/2026-10-01-verify-calibration.md`（验证记录）
- Modify: `taskgen/v2/docs/2026-10-01-taskgen-v2-design.md`（写回本计划定下的事）
- Modify: `taskgen/v2/README.md`（改动记录）
- 可能 Modify: `taskgen/v2/taskgen_v2/verify.py`（`DEFAULT_VOTES`，见 Step 4）
- 本地，不进 git：`results/plan4/calib/label_sheet.md`、`labels.jsonl`、`review.md`、`report.md`

**Interfaces:**
- Consumes: Task 6 的 `items.jsonl`、`votes.jsonl`。
- Produces: 校验的票数规则（`DEFAULT_VOTES`）；给下一份计划的"漏掉的类别"清单。

- [ ] **Step 1: Claude 标注（不看票）**

```bash
cd $REPO/taskgen/v2 && $P scripts/verify_calibrate.py sheet --dir results/plan4/calib
```
逐条读 `results/plan4/calib/label_sheet.md`（instruction、SQL、SQL 实际改了哪些行），需要时查库。标准：只看得到 instruction、能查库的 agent，最终能不能留下和 SQL 一样的库。每条写一行到 `results/plan4/calib/labels.jsonl`：
`{"id": ..., "label": "good" 或 "bad", "reason": "missing" / "extra" / "unclear" / "wrong_rows" / "other" 或 null, "unsure": true/false, "note": "一句话", "by": "claude"}`。

- 标完之前**不打开** `votes.jsonl`，也不跑 `review`、`report`，免得被票影响。
- 拿不准就 `"unsure": true`，交给用户。
- Expected：`labels.jsonl` 的行数等于标注集条数。

- [ ] **Step 2: 生成复核页，停下来等用户**

```bash
cd $REPO/taskgen/v2 && $P scripts/verify_calibrate.py review --dir results/plan4/calib
```
Expected：`wrote review.md: N items`（N 预计 5–20）。

**停下来**：把 `results/plan4/calib/review.md` 的路径和条数告诉用户，请用户对每条回复 good 或 bad（bad 附原因）。用户回复之后，每条追加一行 `"by": "user"` 到 `labels.jsonl`（后写的覆盖先写的）。N 是 0 就跳过这一步，在账本里记一句。

- [ ] **Step 3: 报告**

```bash
cd $REPO/taskgen/v2 && $P scripts/verify_calibrate.py report --dir results/plan4/calib
```
读表：三种规则下的正样本通过率、负样本被拒率（全部、按来源和改法）、标注集的好题通过率、坏题召回、精度，以及选出的规则。另外列出：
- 每种规则下被放过的负样本 id（按来源和改法）；
- 标注为 bad 却被放过的 id；
- 标注为 good 却被拒的 id，以及拒的理由（看投 No 那票的结尾）。
这些清单只进验证记录，写 id 和类别，不摘录题目内容。

- [ ] **Step 4: 定规则**

- `choose_rule` 选出的规则用 k 票：
  - k ≠ 2：把 `taskgen_v2/verify.py` 的 `DEFAULT_VOTES = 2` 改成 k，注释改成那条规则的说法，例如 k=3 写 `# three votes, two of them Yes (calibrated in plan 4)`。改完跑全套，测试数不变。`test_models_from_env` 和 `test_model_specs` 都按 `verify.DEFAULT_VOTES` 断言，不用改。
  - k = 2：不改代码。
- 碰到以下两种情况就**停下来问用户**，把报告的表给用户，说明三个选项：加第二个模型（D4）、把漏的类别补成检查规则（下一份计划）、接受现状。
  - `choose_rule` 返回 `None`；
  - 选出的规则拒掉的负样本不到 80%。
- 用户做出决定之前，不改 `DEFAULT_VOTES`。

- [ ] **Step 5: 写验证记录 `docs/2026-10-01-verify-calibration.md`**

中文，只写计数和 id，不摘录题目内容。内容：
1. **这次改了什么**：一段话，引本计划，列 Task 1–5 的改动。
2. **开发集**："本计划新定的事"第 2 条的结果，以及修正之后（解析器重放的数字）。
3. **新出的一批**：Task 6 Step 2、3 的数字（过检查率、拒绝原因、archive 占比、`archive_copy_changed` 拒了几条），和计划 3 的验证记录对照。
4. **三组样本**：各组条数，负样本按来源和改法的条数。
5. **结果**：`report.md` 的表；思考被截断的票数和补票情况；不满 3 票的条目数。
6. **标注与复核**：Claude 标了多少 good、多少 bad（按原因），用户复核了几条、改了几条；坏题少意味着什么（召回主要看负样本）。
7. **结论**：选出的规则和理由；它对 §3 两个目标（正样本 ≥95%、负样本 ≥80%）的结果；没达到的原因。
8. **给下一份计划的输入**：被放过的负样本按改法归类，哪些类别能写成确定性的检查规则（比如删 WHERE 条件后改到的行数变多）；被误杀的好题的原因；ollama 的实测速度（每票秒数、截断比例）和全量校验的时间估计。

- [ ] **Step 6: 设计写回**

```bash
cat > $S/edit_design4.py <<'EOF'
# writes plan 4's rules back into the design (run from taskgen/v2)
PATH = "docs/2026-10-01-taskgen-v2-design.md"
EDITS = [
    ("计划 3（阶段 D 出题，顺带计划 1 留下的检查规则）见 `2026-10-01-taskgen-v2-plan-3.md`；校验和运行的计划在前一份完成后再写",
     "计划 3（阶段 D 出题，顺带计划 1 留下的检查规则）见 `2026-10-01-taskgen-v2-plan-3.md`，计划 4（阶段 F 校验的校准）见 "
     "`2026-10-01-taskgen-v2-plan-4.md`；运行的计划在前一份完成后再写"),
    ("③人工标注的真实候选 100–150 条（v1 试点的 93 条起步）",
     "③人工标注的真实候选 100–150 条（计划 4 改为用修好的代码新出的一批 v2 候选；v1 的题和 v2 差别太大）"),
    ("全部模型通过才通过。",
     "全部模型通过才通过。没设 `TASKGEN_VERIFY_MODELS` 时用 `TASKGEN_VERIFY_MODEL` 投 `verify.DEFAULT_VOTES` 票（票数由计划 4 的校准定）。"
     "思考用光 token 没给结论的票不算票，下次运行重投。"),
    ("- prompt 沿用 v1 重写的五问版。",
     "- prompt 沿用 v1 重写的五问版，另附档案的数据怪异点（计划 4：address 把议员的姓存在 first_name，不附就误判）。"),
    ("按类别报告拒绝率。",
     "按类别报告拒绝率。DySQL 金标准和 v2 候选各改一批（每类 60 / 40 条），分开报告。"),
    ("  - 人工标注集：v1 试点的 93 条起步，不够再从全量里补到 100–150 条。",
     "  - 人工标注集：用修好的代码新出的一批 v2 候选（每库 7 棵树，seed 1）里过了执行检查的全部（计划 4）。"),
]
text = open(PATH, encoding="utf-8").read()
for old, new in EDITS:
    assert text.count(old) == 1, (text.count(old), old)
    text = text.replace(old, new)
open(PATH, "w", encoding="utf-8").write(text)
print(f"{len(EDITS)} edits applied")
EOF
cd $REPO/taskgen/v2 && $P $S/edit_design4.py && git -C $REPO diff --stat -- taskgen/v2/docs/2026-10-01-taskgen-v2-design.md
```
Expected：`6 edits applied`；只有设计文档一个文件。

- [ ] **Step 7: README、测试、commit**

```bash
cd $REPO
printf '%s\n' \
  '| 模型调用：回答在 max_tokens 处截断、HTTP 200 没有消息体时重试；校验的票思考用光 token 不算票，结论行认得更宽 | §4.6 |' \
  '| 校验：`TASKGEN_VERIFY_MODELS` 配几个模型各投几票，附档案的数据怪异点；预封顶（每模板 25、每库 900）之后再校验；meta 按模型记票 | §4.6、§4.7 |' \
  '| 校准：五种改坏（`corrupt.py`）、比较两份 SQL 留下的库（`check.final_state`）、`scripts/verify_calibrate.py`；DySQL 金标准、改坏的题、新一批 v2 候选上量出票数规则（`docs/2026-10-01-verify-calibration.md`） | §5 F |' >> taskgen/v2/README.md
cd $REPO/taskgen/v2 && $P -m pytest -q 2>&1 | tail -n 1
cd $REPO
git add taskgen/v2/docs/2026-10-01-verify-calibration.md taskgen/v2/docs/2026-10-01-taskgen-v2-design.md taskgen/v2/README.md
git diff --quiet -- taskgen/v2/taskgen_v2/verify.py || git add taskgen/v2/taskgen_v2/verify.py
git diff --cached --name-only
git commit -m "docs(taskgen v2): the verifier's calibration and its vote rule

deepseek-v4.1-flash judged DySQL gold that passes the check, gold and v2 candidates broken five ways, and a
fresh batch of v2 candidates labeled by Claude and reviewed by the user, three votes each; the vote rule that
keeps 95% of the good tasks and rejects the most broken ones is the default now. The design takes over this
plan's rules: the data quirks in the verifier prompt, cut-off votes asked again, the label set from v2.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```
Expected：测试 `176 passed`；暂存区是这 3 个文件，改了 `DEFAULT_VOTES` 的话再加 `verify.py`，共 4 个。

- [ ] **Step 8: memory**

- `research-plan-grpo-text2sql.md`：计划 4 完成，写日期、commit 范围、选出的规则和三组样本的关键数字；下一步是计划 5（阶段 H 试点、I 全量）。
- `taskgen-v2-plan3-followups.md`：标出这次已做的（`finish_reason` 和坏响应可重试；archive 的修正在 GLM 上的实测）。
- 新建 `taskgen-v2-plan4-followups.md`：漏掉的类别、给检查规则的建议、没做的事（近重复过滤、第二个模型、把执行效果给校验模型看）；在 `MEMORY.md` 加一行。

---

## 执行之后

- 最终复核：opus 子代理只读审查整个分支（`review-package` 的 base 是本计划提交之前那个 commit），对照本计划的 Review Focus 和账本里的 Ruling。
- 分支保留，用户自己推。
