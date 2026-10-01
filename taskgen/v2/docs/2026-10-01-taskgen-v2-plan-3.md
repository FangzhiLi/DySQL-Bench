# 训练任务生成 v2：实施计划 3（出题 prompt 与素材）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按设计 §4.3、§4.4 重写出题：prompt 改用确认过的档案描述和数据怪异点、范围内表的 DDL 和主键说明；出题计划按 DySQL 的分布抽写语句数和形状；去掉只读提问和 `outputs`；few-shot 换成手写的 DySQL 式示例；顺带修掉计划 1 留下的字面量和时钟规则；最后在 beer_factory 上出 100 条，证明 §3 的指标进入目标区间。

**Architecture:**
- `check.py`：读时钟的 gold 改成在同一天的两个固定时刻各执行一遍再比较，不再隔 1.1 秒；不带时间参数的日期函数也算读时钟；字面量认复数词尾、紧跟数字的单位，不认左边粘着字母的数字。
- `schema.py`：只给范围内的表出 DDL 和 BIRD 列说明；每张表一行主键说明（新行的键怎么来、哪些列唯一）。
- `trees.py`：每棵树记下能单独认出说话人的列（`lookup`），给"用子查询找人"的形状用。
- `prompt.py`：出题计划改按写语句数抽，形状（两张表、子查询、批量、archive）按 DySQL 的频率抽，难度由形状推出；prompt 文字重写；`examples.json` 换成手写示例。
- `generate.py`：每库一份 prompt 素材（`context`）；回答不再带 `outputs`；JSON 容忍字符串里的控制字符；模型没给回答（思考用光了 token）时可重试。
- CLI：`generate` 读档案素材；删掉 `describe` 子命令和 `data/db_descriptions.json`。

顺序：检查规则（独立）→ schema 素材 → 树的 lookup → 出题计划与 prompt → 回答格式与清理 → 验证。

**Tech Stack:** Python 3.11（conda env `dysql`）。
- 标准库：`sqlite3`、`json`、`re`、`concurrent.futures`。
- 已装：`sqlparse`、`requests`、`pytest`。
- 出题模型：GLM-5.3（`.env` 的 `TASKGEN_GEN_*`）。

不加新依赖。

**Spec:** [2026-10-01-taskgen-v2-design.md](2026-10-01-taskgen-v2-design.md)，相关部分是 D6–D9、§3 验收指标、§4.3 schema 与素材、§4.4 出题计划与 prompt、§4.5 执行检查、§5 阶段 D。下面"本计划新定的事"补充的规则，Task 6 会写回设计文档。

**原型：** 本计划的代码和测试已在 scratchpad 的原型里全部跑通（145 个测试通过），并用 GLM 在 10 个库上试出了 300 条题（数字见"本计划新定的事"第 9 条）。计划里每一步的 Expected 都在仓库的干净副本上按步骤重放核对过。执行时仍按 TDD：先写测试、看它失败，再写实现。

## 本计划新定的事（设计里没写到，请审阅时确认）

1. **prompt 的素材换成档案。**
   - 库描述和数据怪异点取自确认过的档案。v1 的 `data/db_descriptions.json` 和 `describe` 子命令删掉：它们和 5 份确认过的档案冲突（books 说作者是人；book_publishing_company、professional_basketball、WWE、legislator 把档案排除的表当成数据介绍）。
   - DDL 和 BIRD 列说明只给档案范围内的表，排除的表不再出现在 prompt 里。
   - 怪异点原样列出，并要求"名字和值照抄，即使看起来拼错"（设计 §4.3）。
   - 官方出题 prompt 里的 "Principles for generating SQL calls" 6 条原样保留。它就是 `data_pipeline_shell/sql_wiki.md`，也是评测时 agent policy（`envs/*/agent_policy.md`）的核心，生成的题要符合它。其余规则是我们按实测问题补的。
2. **主键说明落到每张表一行**（设计 §4.3 的分类，补了两类）：
   - 可省 ID：写出 SQLite 会分配的值，新行可以不写。
   - 必须写明、给建议值：单列主键、值都是整数时（也包括存成文本的，如 college_2 的学号），建议 MAX+1。
   - **自然键**（新增）：单列、值不是整数（州代码、产品线名），新行写一个还没用过的值。
   - **外键作主键**（新增）：新行写它所属那一行的键，例如 college_2 的 `advisor.s_ID` 是学生的 ID，student_loan 的各属性表按人名作键。这里只认档案的边和库里声明的外键；v1 按列名猜的外键不可靠，会把 books 的 `address_status` 猜成指向 `order_status`。
   - 复合键：每个键列都写明，组合不能和已有的重复。
   - 不出 INSERT：档案的 `no_insert`。
   - 另外列出 UNIQUE 列（和主键相同的不列；WWE 给 INTEGER 主键又加了 UNIQUE）。
3. **说话人用主键找，子查询只用他独有的列。**
   - 根表里同名的人很多：movies_4 有 1497 组重名，legislator 732 组，olympics 659 组，college_2 的学生 356 组。计划 2 的冒烟里就有一条按名字的子查询找错了人。
   - 所以 prompt 要求 SQL 直接写 `主键 = 值`。"用子查询找人"的形状只在树有 `lookup` 时才抽：邮箱、电话、SSN 一类只有他有的值，或者库里只有他叫这个名字。
4. **出题计划的比例按 DySQL 校准。** 先量了 DySQL 金标准的任务级特征：两张表 56.8%，子查询 11.6%，archive 6.5%，碰公共或别人的数据 25.6%。再在计划 2 的 3556 棵树上模拟，定下：
   - 写语句数权重 37/41/13/6/3。第 2 类至少 2 条，所以整体落在 32/47/13/5/3（DySQL 33/47/12/5/3）。
   - 类型权重 47/17/7/29。legislator、student_loan、synthea 没有公共行，只能出第 1、5 类，所以有公共行的库要多出一些第 2、3 类，23 个库整体才落在目标 50/13/6/31 附近（模拟 50.6/13.5/5.4/30.6）。代价是单看 beer_factory，第 2 类约 17%。
   - 形状：两张表 0.85，子查询 0.13，批量 0.12（其中六成整组全改），archive 0.18。模拟出的任务级比例：两张表 56.8%，子查询 12.5%，archive 6.4%，批量 7.1%。
5. **有两项达不到 §3 的目标区间。我选择接受，不靠虚增别的形状去凑：**
   - **hard 占比：** 模拟约 22.6%，目标 25–30%。DySQL 的 hard 题里，57% 是"多条写 + 多张表 + 碰公共或别人的数据"；我们不出第 4 类（D6），少了这一块。其余特征都已对齐 DySQL。
   - **改动超过 10 行：** 估计约 2%（三轮试点实测 1.6%），目标 3–8%。批量整组全改时能超过 10 行，但多数树的事件组不到 11 行；超过 50 行的组又不能整组改（每条语句最多 50 行）。
   - 目标不改：Task 6 在设计 §3 这两行加注，验证记录写明偏差和原因。你不同意（比如宁可多出 archive 或批量去凑），审阅时说一声。
6. **难度由形状推出，不再单独抽。** 打分和执行检查一样。试点里，计划的难度和检查算出的难度 192 条中有 188 条一致。展示的事件数改按写语句数定（1 条写 3–5 个，2 条 5–8 个，3 条以上 8–12 个）。
7. **archive 的做法：** 把要改的行复制成同一张表的新行，再改或删原行。
   - 只用新行的键能省略（或没有主键）、又不在 `no_insert` 里的表，不用根表。
   - 起因：计划 2 冒烟的 4 条类型不一致里，有 3 条是 archive 往人物表或公共表复制；第二轮试点里，school_scheduling 复制复合键的行，撞上了自己。
8. **批量的做法：** 取这个人行数在 2–50 之间、行数最多的事件组。六成整组全改；其余按条件挑，条件里的值照 SQL 的写法写进 instruction。起因：试点里有一条写"2015 年的交易"，SQL 却用了 `'2015-01-01'`，被判缺字面量。
9. **试点结果。** 原型里跑了四轮，GLM-5.3，共 10 个库 300 条（每轮之后按结果调了 prompt）。前三轮 260 条：
   - 过检查 248 条（95.4%）。被拒的 12 条：1 条是模型把 token 全用在思考上、没给回答（现在可重试）；其余是模型的错，比如撞了 UNIQUE（WWE 的名字、school_scheduling 的复合键）、条件写错改了 0 行、字面量没写进 instruction。第二轮 school_scheduling 有 2 条是 archive 复制复合键的行撞了自己，第 7 条修掉之后第三轮没再出现。
   - 要求类型 ≠ 算出类型：1/248（0.4%）。计划 2 冒烟是 4/95（4.2%）。
   - 要求的写语句数 248/248 都写对了；计划推出的难度和检查算出的 192 条中 188 条一致（前两轮）。
   - 和计划 2 冒烟比：词数均值 99 → 55、p90 146 → 64；语句含子查询 41.0% → 9.1%；前 25 词有 ID 或邮箱 45.3% → 90.7%（第一轮之后改了 ID 的写法要求，第二、三轮是 98.9%、96.4%）；只读提问 70.5% → 1.2%，这 3 条全是 archive 题里 "Before you touch ..., copy ..." 被统计正则误报，实际是 0。
   - prompt token 均值约 4.2k，p90 约 6.2k。
   - 第四轮放回了官方 policy 原文（第 1 条），在 4 个库上出了 40 条：过检查 37 条，其余指标没有退步（词数均值 55、p90 66，前 25 词有 ID 100%，子查询 10.3%，只读提问 0）。
   - 四轮里的 2 条类型不一致，加上 1 条被 `other_person` 拒掉的，都是同一个原因：要求第 1 类，模型却往根表新建一行人（regional_sales 新建客户、WWE 新建摔角手、college_2 给自己再建一份学籍）。之后在第 1、5 类的类型说明里补了一句"不往根表新建行"。这一句没有再单独试点，由 Task 6 的 320 条来验证。
10. **回答格式：** 不再要 `outputs`（D7）；JSON 字符串里的原始控制字符照收（计划 2 冒烟因此丢过一条）；空回答（模型把 16384 个 token 全用在思考上）可以重试。
11. **few-shot：** 每类 4 条手写示例，40–50 词，名字加 ID 开头，没有只读提问，可省的新行 ID 不念。领域避开这 23 个库和 DySQL 的 13 个库。不用 v1 的产出（设计 §4.4），也不用 DySQL 的金标准，因为它是评测集。
12. **执行检查（计划 1 留下的）：**
    - 读时钟的 gold 改成在同一天的两个固定时刻（00:00:00 和 13:37:42）各跑一遍再比较，不再隔 1.1 秒。精确到时、分、秒的值会被拒（原来 1.1 秒内同一分钟，漏掉了），精确到日的值照样放行，检查也不用等。
    - 不带时间参数的 `date()`、`time()`、`datetime()`、`julianday()`、`strftime(格式)` 也算读时钟。
    - 字面量认复数词尾（cup / cups）和紧跟数字的单位（10g），不认左边粘着字母的数字（`C00003174` 里的 3174）。
    - 在 DySQL 金标准和 v1 全部候选上重跑：判决一条没变；只有 cookbook 的 5 条金标准改成卡在下一个字面量上。
13. **这次不做的：**
    - 每库覆盖写语句数倾向（设计 §4.4 的可选项）。
    - 试点后把校验通过的任务加进示例池（§4.4，等阶段 H）。
    - "not optional" 对应 `'No'`、`'now'` 算字面量这两条检查规则。
    - 计划 2 复核留下的 minor：M2、M4、M5、M6。

## Global Constraints

- 分支 `isa/data-gen`。每个 Task 单独 commit，commit message 以 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` 结尾。不要 push（用户自己 push）。
- `taskgen/v1/` 冻结：本计划不改其中任何文件，只读。
- 生成的任务不进 git：`taskgen/*/results/`、`taskgen/*/output/` 已在 `.gitignore`。
  - 每次 commit 前跑 `git diff --cached --name-only`，不能出现 `results/` 或 `output/`。
  - 文档里只写候选 id 和计数，不摘录题目内容。
- `examples.json` 只放手写示例：不用 v1 的产出（设计 §4.4），也不用 DySQL 的金标准（评测集）。
- 本计划不改 `data/db_profiles.json`。档案只有用户能确认；要改档案，先停下来问用户。
- 秘密只在仓库根目录的 `.env`。不打印 key，只打印 `BASE_URL`、`MODEL` 两行；测试不联网，模型一律用假客户端。
- GLM 并发不超过 5：`generate` 一律 `--workers 5`，多个库依次跑，不并行。
- 命令约定：
  - `REPO=/home/wmd3i/Documents/Isa/DySQL-Bench`
  - `P=~/miniconda3/envs/dysql/bin/python`
  - 临时文件放 `S=/tmp/claude-1000/-home-wmd3i-Documents-Isa-DySQL-Bench/3cc9a46f-e1e3-4468-b1b8-b1054479803f/scratchpad/v2-plan3`（先 `mkdir -p $S`）
  - `D=2026-10-01`（文档日期，和设计、计划 1–2 一致）
- 测试按目录跑：`cd $REPO/taskgen/v2 && $P -m pytest -q`。不要把 v1 和 v2 的测试放在同一个 pytest 进程里（文件同名）。
- SQL 里的表名、列名一律用 `taskgen_common.db_select._q()` 加引号。
- prompt 和示例用英文；文档用中文。
- 设计里的硬性规定（原文）：
  - D6：这一轮不出第 4 类（库内的人改别人的数据）；类型只抽 1、2、3、5。
  - D7：gold 里不放 SELECT；prompt 去掉 `outputs` 和只读提问。
  - D8：说话人"名字 + ID/邮箱"一起给，被改的记录直接给 ID；按归属子查询的形状降到 10% 左右。
  - D9：新行 ID 算隐含字面量、prompt 允许不写 ID，只限"可省 ID"的表。其余表的新 ID 必须出现在 instruction 里，或档案标成不出 INSERT。
  - §3 的目标（v2 列）：每题写语句数 33/45/13/6/3、均值 1.9–2.1；≥3 条 18–24%；只读提问 <5%；词数均值 50–80、p90 <110；前 25 词内有 ID 或邮箱 ≥80%；语句含子查询 <15%；写入表 ≥2 张 ≥50%；改动 >10 行 3–8%；类型 50/13/6/31 左右；难度 25–30/40–50/25–30；执行检查通过率 ≥92%；要求类型 = 算出类型 ≥97%。

## Review Focus

1. **存成文本的主键**（college_2 的学号 `'12345'`、student_loan 的 `'student123'`）：prompt 里 `主键 = 值` 要加引号，建议值按数字算。→ Task 2 的 `num_text`、Task 4 的 `sql_value`。
2. **重名的说话人**（movies_4、legislator、college_2 的学生）：子查询只能用他独有的列，默认按主键找。→ Task 3 的 `lookup`、Task 4 的 "names can repeat"。
3. **没有事件或没有公共行的树**（hr_1 的 100 个员工；legislator、student_loan、synthea）：形状要退化得合理，不出批量、archive、子查询，也不要求超出能写的表数。→ Task 4 的 `NO_EVENTS`、`feasible_types`。
4. **不能新增、或键必须写明的表**（`no_insert`、WWE 序列跑在 MAX 前面的表、复合键）：键说明要说清楚，archive 不往这些表复制。→ Task 2 的键说明测试、Task 4 的 archive 测试。
5. **模型回答的边角情况**（空正文、字符串里的控制字符、旧格式带 `outputs`）：不丢题、不崩。→ Task 5。

---

### Task 1: 执行检查：时钟和字面量规则（计划 1 留下的）

**Files:**
- Modify: `taskgen/v2/taskgen_v2/check.py`（`NONDET`、`RERUN_GAP_S` → `INSTANTS`、新函数 `at_instant`、`rerun_changes`、`_contains`、`literal_ok` 的数字回退、`run_check` 里 `finally` 的注释、`import time` 去掉）
- Test: `taskgen/v2/tests/test_taskgen_check.py`

**Interfaces:**
- Consumes: 无。
- Produces:
  - `check.INSTANTS = ("2000-01-01 00:00:00", "2000-01-01 13:37:42")`
  - `check.at_instant(stmt: str, instant: str) -> str`：把语句里读时钟的地方换成固定时刻。
  - `check.rerun_changes(db, stmts, tables) -> str`：签名不变，改成在两个时刻各跑一遍。
  - `check.RERUN_GAP_S` 删掉。

- [ ] **Step 1: 改动前，先导出现在的检查在 DySQL 金标准和 v1 全部候选上的判决**

```bash
mkdir -p $S && cat > $S/verdicts.py <<'EOF'
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
cd $REPO/taskgen/v2 && $P $S/verdicts.py $S/verdicts_before.jsonl ../v1/results && wc -l < $S/verdicts_before.jsonl
```
Expected: `5221`（DySQL 1062 条 + v1 4159 条），约 2 分钟。

- [ ] **Step 2: 写失败的测试**

`tests/test_taskgen_check.py` 第一行之后的 import 改成：

```python
import sqlite3, time
```

把原来的 `test_ctrl_c_in_the_rerun_pause_is_not_swallowed` 整个换成：

```python
def test_ctrl_c_in_the_rerun_is_not_swallowed(rental, monkeypatch):
    def interrupted(stmt, instant):
        raise KeyboardInterrupt
    monkeypatch.setattr(check, "at_instant", interrupted)
    with pytest.raises(KeyboardInterrupt):
        check.run_check_safe(rental, cand("I am a5 b5. Mark my rental 5 as returned right now.",
                                          ["UPDATE rental SET return_date = CURRENT_TIMESTAMP WHERE rental_id = 5"]))
```

文件末尾加：

```python
# --- plan 3: literal rules and clock readings left over from plan 1 ---

def test_plurals_and_units_after_numbers_match():
    ok = check.literal_ok
    assert ok("cup", "add 2 cups of flour", set()) and ok("box", "ship three boxes", set())
    assert ok("g", "use 10g of salt", set()) and ok("ml", "add 20ml of lime juice", set())
    assert not ok("ml", "the html page", set()) and not ok("203", "card 12030", set())
    assert not ok("cup", "the cupboard", set())


def test_a_number_glued_to_letters_on_its_left_does_not_count():
    ok = check.literal_ok
    assert not ok("3174", "client C00003174, please", set())
    assert ok("3174", "invoice #3174, please", set()) and ok("3174", "3174kg of steel", set())


def test_clock_readings_without_a_time_value_are_nondeterministic():
    for sql in ["UPDATE r SET d = date()", "UPDATE r SET d = datetime( )", "UPDATE r SET d = julianday()",
                "UPDATE r SET d = strftime('%Y-%m-%d %H:%M')", "UPDATE r SET d = time()"]:
        assert check.NONDET.search(sql), sql
    for sql in ["UPDATE r SET d = date('2024-01-02')", "UPDATE r SET d = strftime('%Y', d)"]:
        assert not check.NONDET.search(sql), sql


def test_at_instant_replaces_every_clock_reading():
    sql = ("UPDATE r SET a = CURRENT_TIMESTAMP, b = current_date, c = CURRENT_TIME, d = datetime('now', 'localtime'), "
           "e = date(), f = strftime('%H:%M'), g = 'nowhere'")
    assert check.at_instant(sql, "2000-01-01 13:37:42") == (
        "UPDATE r SET a = '2000-01-01 13:37:42', b = '2000-01-01', c = '13:37:42', "
        "d = datetime('2000-01-01 13:37:42', 'localtime'), e = date('2000-01-01 13:37:42'), "
        "f = strftime('%H:%M', '2000-01-01 13:37:42'), g = 'nowhere'")


def test_minute_precise_clock_value_is_rejected_without_waiting(rental):
    t0 = time.time()
    r = check.run_check(rental, cand("I am a5 b5. Stamp my rental 5 with the current minute, as of now.",
                                     ["UPDATE rental SET return_date = strftime('%Y-%m-%d %H:%M', 'now') WHERE rental_id = 5"]))
    assert r["reasons"] == ["nondeterministic: rental"] and time.time() - t0 < 1
    r = check.run_check(rental, cand("I am a5 b5. Mark my rental 5 as returned today.",
                                     ["UPDATE rental SET return_date = date() WHERE rental_id = 5"]))
    assert r["ok"], r["reasons"]
```

- [ ] **Step 3: 跑测试，确认失败**

```bash
cd $REPO/taskgen/v2 && $P -m pytest -q tests/test_taskgen_check.py 2>&1 | tail -n 8
```
Expected: 6 个失败，其余通过。
- `test_plurals_and_units_after_numbers_match`、`test_a_number_glued_to_letters_on_its_left_does_not_count`、`test_clock_readings_without_a_time_value_are_nondeterministic`：断言失败。
- `test_at_instant_replaces_every_clock_reading`、`test_ctrl_c_in_the_rerun_is_not_swallowed`：AttributeError，`taskgen_v2.check` has no attribute 'at_instant'。
- `test_minute_precise_clock_value_is_rejected_without_waiting`：1.1 秒的重跑落在同一分钟，`reasons` 是 `[]`；用时也超过 1 秒。

- [ ] **Step 4: 实现**

`check.py`：
- import 行改成 `import json, re, sqlite3, unicodedata`（`time` 只给重跑的暂停用，暂停去掉了）。
- `NONDET` 连同它上面的注释换成：

```python
# gold that reads the clock or random(): run it twice and compare what the eval hash compares. Date functions called
# without a time value read the clock too: date(), datetime(), julianday(), strftime('%H:%M')
NONDET = re.compile(r"(?i)\bcurrent_(?:timestamp|time|date)\b|'now'|\brandom(?:blob)?\s*\(|\bunixepoch\s*\(|"
                    r"\b(?:date|time|datetime|julianday)\s*\(\s*\)|\bstrftime\s*\(\s*'(?:[^']|'')*'\s*\)")
```

- `RERUN_GAP_S = 1.1 ...` 那一行换成：

```python
# the two clock readings of the rerun: the same day at two times, so values precise to the day agree and pass, and
# values precise to the hour, minute or second differ (the 1.1-second rerun of plan 1 let minutes and hours through)
INSTANTS = ("2000-01-01 00:00:00", "2000-01-01 13:37:42")
```

- `_contains` 换成：

```python
def _contains(text, n):
    """n occurs in text as a whole token: '203' is not in '2030', 'ann' is not in 'joanna'. A word may take a plural
    ending ('cup' in '2 cups') and a unit may follow a number ('g' in '10g'), as in DySQL's cookbook gold."""
    before = r"(?:(?<!\w)|(?<=\d))" if n.isalpha() else r"(?<!\w)"
    after = r"(?:e?s)?(?!\w)" if n[-1:].isalpha() else r"(?!\w)"
    return re.search(before + re.escape(n) + after, text) is not None
```

- `literal_ok` 最后的数字回退那一行换成：

```python
        return any(_num(m) == v for m in re.findall(r"(?<![\w.])-?\d[\d,]*\.?\d*", text))   # a whole number: not 3174 in 'c00003174'
```

- `rerun_changes` 整个换成下面两个函数：

```python
def at_instant(stmt, instant):
    """The statement with every clock reading replaced by a fixed instant: 'now', CURRENT_TIMESTAMP/DATE/TIME, and
    date functions called without a time value. A column default that reads the clock is not replaced; none of the
    36 databases (23 here, 13 in DySQL) has one."""
    day, tod = instant.split()
    s = re.sub(r"(?i)\bcurrent_timestamp\b", f"'{instant}'", stmt)
    s = re.sub(r"(?i)\bcurrent_date\b", f"'{day}'", s)
    s = re.sub(r"(?i)\bcurrent_time\b", f"'{tod}'", s)
    s = re.sub(r"(?i)'now'", f"'{instant}'", s)
    s = re.sub(r"(?i)\b(date|time|datetime|julianday|unixepoch)\s*\(\s*\)", rf"\1('{instant}')", s)
    return re.sub(r"(?i)\bstrftime\s*\(\s*('(?:[^']|'')*')\s*\)", rf"strftime(\1, '{instant}')", s)


def rerun_changes(db, stmts, tables):
    """Run the statements again twice, at the two INSTANTS (every statement that ran the first time, DDL included, so
    both runs start from the same state), and compare what the eval hash compares. The caller's open transaction
    holds the first run. Returns the tables whose compared columns differ, '' when the runs agree."""
    snaps = []
    for instant in INSTANTS:
        db.execute("ROLLBACK"); db.execute("BEGIN")
        try:
            for st in stmts:
                db.execute(at_instant(st, instant)).fetchall()
        except sqlite3.Error as e:
            return f"rerun failed: {e}"
        snaps.append(snapshot(db, tables))
    return ", ".join(t for t in sorted(tables) if snaps[0][t] != snaps[1][t])
```

- `run_check` 的 `finally` 里那行注释改成：

```python
        if db.in_transaction:   # a Ctrl-C between the rerun's ROLLBACK and BEGIN leaves none open; ROLLBACK would hide it
```

- [ ] **Step 5: 跑测试，确认通过**

```bash
cd $REPO/taskgen/v2 && $P -m pytest -q tests/test_taskgen_check.py 2>&1 | tail -n 1 && $P -m pytest -q 2>&1 | tail -n 1
```
Expected: `49 passed`；整套 `138 passed`，而且比原来快（几个带时钟的测试不再各等 1.1 秒）。

- [ ] **Step 6: 重新校准：改动后再导出一遍，逐条对比**

```bash
cd $REPO/taskgen/v2 && $P $S/verdicts.py $S/verdicts_after.jsonl ../v1/results && $P $S/compare_verdicts.py $S/verdicts_before.jsonl $S/verdicts_after.jsonl
```
Expected：
```
DySQL gold: 1062 checked, passed 895 -> 895
v1 candidates: 4159 checked, passed 3872 -> 3872
changed: 5
```
后面 5 行都是 DySQL 的 cookbook 金标准（8、14、34、38、39）。它们原来卡在复数或单位上（`'cup'`、`'gram'`、`'g'`、`'ml'`、`'piece'`），这些现在认了；但同一条里下一个缺的字面量冒了出来，是 instruction 里写 "not optional"、SQL 里写的 `'No'`，所以仍然拒绝。时钟规则没有改变任何判决：两组数据里都没有分钟或小时精度的时钟值，也没有不带参数的日期函数。结果和这里不同，要逐条查明原因再往下做。

- [ ] **Step 7: commit**

```bash
cd $REPO
git add taskgen/v2/taskgen_v2/check.py taskgen/v2/tests/test_taskgen_check.py
git diff --cached --name-only
git commit -m "fix(taskgen v2): clock readings at two fixed instants; plural and unit literals

The rerun of gold that reads the clock no longer waits 1.1 seconds: every clock reading is replaced by two fixed
times of the same day, so values precise to the hour or minute are caught and date-only values still pass.
Date functions called without a time value count as clock readings. Literals accept a plural ending and a unit
right after a number, and the number fallback no longer matches digits glued to letters on their left.
Re-run on DySQL's gold and v1's candidates: no verdict changes.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
Expected：暂存区只有这两个文件。

---

### Task 2: schema 素材：范围内的表、每表一行主键说明

**Files:**
- Modify: `taskgen/v2/taskgen_v2/schema.py`（`ddl`、`schema_block` 加 `tables` 参数；新增 `unique_columns`、`_next_number`、`key_notes`）
- Test: `taskgen/v2/tests/test_taskgen_schema.py`

`describe_db`、`DESCRIBE_PROMPT`、`next_ids` 这一步先留着：Task 4 换掉 generate 的调用之后，Task 5 再删。

**Interfaces:**
- Consumes: `schema.pk_info(conn)`（计划 1）。
- Produces:
  - `schema.ddl(db_path, tables=None) -> str`、`schema.schema_block(db_path, tables=None) -> str`：`tables` 是表名集合，给了就只出这些表的 DDL 和 BIRD 列说明（列说明文件名和表名大小写可能不同，按不区分大小写对）。
  - `schema.unique_columns(conn, table) -> list[tuple[str, ...]]`：UNIQUE 约束或唯一索引的列组，主键不算，排好序。
  - `schema.key_notes(conn, tables, no_insert=(), fks=None) -> dict[str, str]`：每表一行，形如 `"- orders: a new row may leave order_id out (SQLite assigns 101)"`。`fks` 是 `{表: 它的外键列}`，用来认出"以外键作主键"的表（college_2 的 `advisor.s_ID` 是学生的 ID）。

- [ ] **Step 1: 写失败的测试**

`tests/test_taskgen_schema.py`：在 `test_column_descriptions_absent_for_spider` 前面加：

```python
def test_ddl_and_notes_of_the_tables_in_scope_only(tmp_path):
    db = make_db(tmp_path, "shop", SHOP)
    dd = tmp_path / "database_description"; dd.mkdir()
    (dd / "Customers.csv").write_text("original_column_name,column_name,column_description,data_format,value_description\n"
                                      "first_name,first name,given name,text,\n", encoding="utf-8-sig")
    (dd / "products.csv").write_text("original_column_name,column_name,column_description,data_format,value_description\n"
                                     "price,price,in dollars,real,\n", encoding="utf-8-sig")
    block = schema.schema_block(db, {"customers", "orders"})
    assert "CREATE TABLE customers" in block and "CREATE TABLE orders" in block and "CREATE TABLE products" not in block
    assert "- Customers.first_name: given name" in block and "price" not in block   # BIRD names files in another case
```

文件末尾加：

```python
def test_key_notes_say_how_a_new_row_gets_its_key(tmp_path):
    conn = sqlite3.connect(make_db(tmp_path, "keys", """
CREATE TABLE plain (id INTEGER PRIMARY KEY, v TEXT);
CREATE TABLE ahead (id INTEGER PRIMARY KEY AUTOINCREMENT, v TEXT);
CREATE TABLE num_text (code TEXT PRIMARY KEY, v TEXT);
CREATE TABLE text_key (code TEXT PRIMARY KEY, v TEXT);
CREATE TABLE pair (a INTEGER, b INTEGER, PRIMARY KEY (a, b));
CREATE TABLE nokey (v TEXT);
CREATE TABLE closed (id INTEGER PRIMARY KEY, v TEXT);
CREATE TABLE named (id INTEGER PRIMARY KEY UNIQUE, name TEXT UNIQUE, code TEXT, city TEXT, UNIQUE (code, city));
CREATE TABLE extra (code TEXT PRIMARY KEY REFERENCES num_text(code), v TEXT);
CREATE TABLE profile (pid INTEGER PRIMARY KEY REFERENCES plain(id), v TEXT);
""" + rows("plain", 5, lambda i: f"{i + 1},'x'") + rows("ahead", 5, lambda i: f"{i + 1},'x'")
        + "INSERT INTO ahead VALUES (10, 'y'); DELETE FROM ahead WHERE id = 10;"
        + rows("num_text", 3, lambda i: f"'{1000 + i}','x'") + "INSERT INTO text_key VALUES ('AL', 'x'), ('AK', 'y');"))
    tables = ["plain", "ahead", "num_text", "text_key", "pair", "nokey", "closed", "named", "extra", "profile", "missing"]
    notes = schema.key_notes(conn, tables, {"closed"}, {"extra": {"code"}, "profile": {"pid"}})
    assert notes == {
        "plain": "- plain: a new row may leave id out (SQLite assigns 6)",
        "ahead": "- ahead: a new row must state id = 6, written in the instruction",       # WWE: the sequence ran ahead
        "num_text": "- num_text: a new row must state code = 1003, written in the instruction",   # college_2's text IDs
        "text_key": "- text_key: a new row must state a new code, one not used yet, written in the instruction",
        "pair": "- pair: key (a, b); a new row states every key column, in a combination not used yet",
        "nokey": "- nokey: no primary key",
        "closed": "- closed: no new rows (UPDATE or DELETE only)",
        "named": "- named: a new row may leave id out (SQLite assigns 1); unique: (code, city), name (no value used twice)",
        "extra": "- extra: a new row states code, the key of the row it belongs to, written in the instruction",
        "profile": "- profile: a new row states pid, the key of the row it belongs to, written in the instruction"}
    assert schema.unique_columns(conn, "named") == [("code", "city"), ("name",)] and schema.unique_columns(conn, "pair") == []
```

- [ ] **Step 2: 跑测试，确认失败**

```bash
cd $REPO/taskgen/v2 && $P -m pytest -q tests/test_taskgen_schema.py 2>&1 | tail -n 4
```
Expected: 2 个失败。`test_ddl_and_notes_of_the_tables_in_scope_only` 报 `TypeError: schema_block() takes 1 positional argument but 2 were given`；`test_key_notes_say_how_a_new_row_gets_its_key` 报 `AttributeError: module 'taskgen_v2.schema' has no attribute 'key_notes'`。

- [ ] **Step 3: 实现**

`schema.py`：`ddl` 和 `schema_block` 换成：

```python
def ddl(db_path, tables=None):
    """CREATE TABLE statements, of the given tables only when tables is set."""
    c = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = c.execute("SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                         "AND sql IS NOT NULL ORDER BY rowid").fetchall()
    finally:
        c.close()
    return "\n".join(sql for name, sql in rows if tables is None or name in tables)
```

```python
def schema_block(db_path, tables=None):
    """DDL plus BIRD's column notes; with tables set, only those tables (the profile's scope: excluded tables stay out
    of the prompt). BIRD names a notes file after its table, sometimes in another case."""
    text = ddl(db_path, tables)
    keep = None if tables is None else {t.lower() for t in tables}
    notes = [f"- {t}.{c}: {d}" for t, cols in column_descriptions(db_path).items() if keep is None or t.lower() in keep
             for c, d in cols.items()]
    if notes:
        text += "\n\n## Column notes\n" + "\n".join(notes)
    return text
```

文件末尾（`next_rowid` 后面）加：

```python
def unique_columns(conn, table):
    """Column groups under a UNIQUE constraint or a unique index, those equal to the primary key left out (WWE
    declares its INTEGER keys UNIQUE as well)."""
    pk = tuple(r[1] for r in sorted((r for r in conn.execute(f"PRAGMA table_info({_q(table)})") if r[5]), key=lambda r: r[5]))
    out = set()
    for idx in conn.execute(f"PRAGMA index_list({_q(table)})").fetchall():
        cols = tuple(r[2] for r in conn.execute(f"PRAGMA index_info({_q(idx[1])})"))
        if idx[2] and idx[3] != "pk" and sorted(cols) != sorted(pk):
            out.add(cols)
    return sorted(out)


def _next_number(conn, table, col):
    """MAX + 1 when every value of a one-column key is a whole number, also when stored as text (college_2's IDs)."""
    vals = [v for (v,) in conn.execute(f"SELECT {_q(col)} FROM {_q(table)}") if v is not None]
    if not vals or not all(re.fullmatch(r"-?\d+(\.0+)?", str(v)) for v in vals):
        return None
    return max(int(float(v)) for v in vals) + 1


def key_notes(conn, tables, no_insert=(), fks=None):
    """design §4.3, one line per table: how a new row gets its key -- left out (SQLite assigns it), stated with a
    suggested value, stated as a new natural value, the key of the row it belongs to, every column of a composite
    key, or no new rows at all -- and which columns must stay unique. fks: {table: its foreign-key columns}."""
    pk, notes, fks = pk_info(conn), {}, fks or {}
    for t in tables:
        info = pk.get(t)
        if info is None:
            continue
        cols = info["cols"]
        if t in no_insert:
            note = "no new rows (UPDATE or DELETE only)"
        elif len(cols) == 1 and cols[0] in fks.get(t, ()):   # college_2's advisor.s_ID is a student's ID
            note = f"a new row states {cols[0]}, the key of the row it belongs to, written in the instruction"
        elif info["omittable"]:
            note = f"a new row may leave {cols[0]} out (SQLite assigns {info['next']})"
        elif len(cols) == 1:
            n = _next_number(conn, t, cols[0])
            note = (f"a new row must state {cols[0]} = {n}, written in the instruction" if n is not None
                    else f"a new row must state a new {cols[0]}, one not used yet, written in the instruction")
        elif cols:
            note = f"key ({', '.join(cols)}); a new row states every key column, in a combination not used yet"
        else:
            note = "no primary key"
        uniq = unique_columns(conn, t)
        if uniq:
            note += "; unique: " + ", ".join(u[0] if len(u) == 1 else f"({', '.join(u)})" for u in uniq) + " (no value used twice)"
        notes[t] = f"- {t}: {note}"
    return notes
```

- [ ] **Step 4: 跑测试，确认通过**

```bash
cd $REPO/taskgen/v2 && $P -m pytest -q tests/test_taskgen_schema.py 2>&1 | tail -n 1 && $P -m pytest -q 2>&1 | tail -n 1
```
Expected: `8 passed`；整套 `140 passed`。

- [ ] **Step 5: 在真实库上看一眼**

外键列取档案的边、库里声明的外键和复合外键（Task 4 的 `generate.context` 也这样取；v1 按列名猜的外键不可靠，不用）：

```bash
cd $REPO/taskgen/v2 && $P -c "
import sqlite3, sys; sys.path[:0] = ['.', '../common']
from taskgen_v2 import db_profile, io, schema
for k in ('spider2:WWE', 'spider1:college_2', 'bird:regional_sales'):
    rec, prof = io.load_db_recs()[k], db_profile.get(k)
    fks = {}
    for e in db_profile.edges(prof):
        fks.setdefault(e.child, set()).update(e.cols)
    for f in rec['fks']:
        if f['source'] == 'declared':
            fks.setdefault(f['table'], set()).add(f['col'])
    c = sqlite3.connect(f'file:{io.resolve_db_path(rec[\"path\"])}?mode=ro', uri=True)
    print('\n'.join(schema.key_notes(c, sorted(db_profile.scope_tables(prof)), set(prof['no_insert']), fks).values()))"
```
Expected（每行都能对上设计 §4.3 的分类）：
- WWE：`Belts`、`Cards`、`Events`、`Locations`、`Match_Types`、`Promotions`、`Wrestlers` 是 `a new row must state id = …`（`sqlite_sequence` 跑在 MAX 前面）；`Matches` 是 `a new row may leave id out (SQLite assigns 540801)`；带名字的表行尾有 `unique: name (no value used twice)`，不再列出 `id`。
- college_2：`student`、`instructor`、`course` 是 `a new row must state … = …`（数字样式的 varchar）；`advisor` 是 `a new row states s_ID, the key of the row it belongs to`；`department` 是 `a new row must state a new dept_name, one not used yet`；`takes`、`section` 等是复合键。
- regional_sales：`Sales Orders` 是 `no new rows (UPDATE or DELETE only)`，`Regions` 是 `a new row must state a new StateCode, one not used yet`。

- [ ] **Step 6: commit**

```bash
cd $REPO
git add taskgen/v2/taskgen_v2/schema.py taskgen/v2/tests/test_taskgen_schema.py
git diff --cached --name-only
git commit -m "feat(taskgen v2): schema text of the tables in scope and a key note per table

The generation prompt will show only the profile's tables and say, per table, how a new row gets its key: left
out, stated with a suggested value, a new natural value, every column of a composite key, or no new rows at all,
plus the columns that must stay unique (design §4.3).

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
Expected：暂存区只有这两个文件。

---

### Task 3: 树里记下能单独认出说话人的列（`lookup`）

**Files:**
- Modify: `taskgen/v2/taskgen_v2/trees.py`（`import re`、`ID_COL`、新函数 `lookup`、`build_tree` 的返回值多一个键）
- Test: `taskgen/v2/tests/test_taskgen_trees.py`

**Interfaces:**
- Consumes: 无。
- Produces:
  - `trees.lookup(conn, table, person, row) -> dict`：`{列: 值}`，说话人在根表里独有的邮箱、电话、SSN 一类的列；没有就用姓名列（同名的只有他一个时）；都不行返回 `{}`。
  - `build_tree` 返回的树多一个键 `"lookup"`。Task 4 的出题计划只在它非空时才抽"用子查询找人"的形状。计划 2 建的旧树没有这个键，出题时按 `{}` 处理。

- [ ] **Step 1: 写失败的测试**

`tests/test_taskgen_trees.py` 的 `test_events_follow_paths_and_parents_nest`，在 `assert t["anchor_name"] == "a5 b5" ...` 那一行后面加：

```python
    assert t["lookup"] == {"first_name": "a5", "last_name": "b5"}                # no email column; the name is unique
```

文件末尾加：

```python
def test_lookup_finds_what_only_this_person_has(tmp_path):
    conn = sqlite3.connect(make_db(tmp_path, "people", """
CREATE TABLE people (pid INTEGER PRIMARY KEY, first TEXT, last TEXT, email TEXT, phone TEXT);
INSERT INTO people VALUES (1, 'Ann', 'Lee', 'ann@x.org', '555'), (2, 'Ann', 'Lee', 'ann2@x.org', '555'),
                          (3, 'Bo', 'Ng', NULL, '777'), (4, 'Cy', 'Ho', 'cy@x.org', NULL), (5, 'Cy', 'Ho', 'cy@x.org', NULL),
                          (6, 'Di', 'Wu', 'cy@x.org', NULL);
"""))
    person = {"key": "pid", "name_cols": ["first", "last"]}

    def row(pid):
        return dict(zip(["pid", "first", "last", "email", "phone"], conn.execute("SELECT * FROM people WHERE pid = ?", (pid,)).fetchone()))
    assert trees.lookup(conn, "people", person, row(1)) == {"email": "ann@x.org"}         # same name as person 2
    assert trees.lookup(conn, "people", person, row(3)) == {"phone": "777"}               # no email
    assert trees.lookup(conn, "people", person, row(6)) == {"first": "Di", "last": "Wu"}  # shared email, own name
    assert trees.lookup(conn, "people", person, row(4)) == {}                             # nothing of their own
```

- [ ] **Step 2: 跑测试，确认失败**

```bash
cd $REPO/taskgen/v2 && $P -m pytest -q tests/test_taskgen_trees.py 2>&1 | tail -n 4
```
Expected: 2 个失败。`test_events_follow_paths_and_parents_nest` 报 `KeyError: 'lookup'`；`test_lookup_finds_what_only_this_person_has` 报 `AttributeError: module 'taskgen_v2.trees' has no attribute 'lookup'`。

- [ ] **Step 3: 实现**

`trees.py`：
- import 行改成 `import json, re, sqlite3`。
- `MAX_DEPTH = 4 ...` 那一行后面加：

```python
ID_COL = re.compile(r"(?i)e-?mail|phone|ssn|social|passport|licen[cs]e|user.?name|login")   # what people identify by
```

- `build_tree` 前面加：

```python
def lookup(conn, table, person, row):
    """Columns that pick out this person's row without the key, for the subquery shape (design D8): an email-, phone-
    or SSN-like column whose value no other row shares, else the name columns when no one else has the same name.
    {} when neither holds (movies_4 has 1497 names shared by several people)."""
    for c in [c for c in row if c != person["key"] and ID_COL.search(c) and row[c] not in (None, "")]:
        if conn.execute(f"SELECT COUNT(*) FROM {_q(table)} WHERE {_q(c)} = ?", (row[c],)).fetchone()[0] == 1:
            return {c: row[c]}
    names = {c: row[c] for c in person["name_cols"] if row.get(c) not in (None, "")}
    if names and conn.execute(f"SELECT COUNT(*) FROM {_q(table)} WHERE " + " AND ".join(f"{_q(c)} = ?" for c in names),
                              tuple(names.values())).fetchone()[0] == 1:
        return names
    return {}
```

- `build_tree` 返回的字典里，`"anchor_row": row, "profile_version": ...` 那一行改成：

```python
            "anchor_row": row, "lookup": lookup(conn, t, person, row), "profile_version": db_profile.version(profile),
```

- [ ] **Step 4: 跑测试，确认通过**

```bash
cd $REPO/taskgen/v2 && $P -m pytest -q tests/test_taskgen_trees.py 2>&1 | tail -n 1 && $P -m pytest -q 2>&1 | tail -n 1
```
Expected: `9 passed`；整套 `141 passed`。

- [ ] **Step 5: 在真实库上看一眼**

```bash
cd $REPO/taskgen/v2 && $P -c "
import random, sys; sys.path[:0] = ['.', '../common']
from collections import Counter
from taskgen_v2 import db_profile, io, trees
recs, profs = io.load_db_recs(), db_profile.load()
for k in ('bird:beer_factory', 'bird:movies_4', 'spider1:college_2', 'bird:legislator', 'spider2:IPL'):
    rec, prof = recs[k], profs[k]
    c = trees.open_ro(io.resolve_db_path(rec['path']))
    for r in prof['roots']:
        person, got = prof['persons'][r['table']], Counter()
        cols = [x[1] for x in c.execute(f'PRAGMA table_info(\"{r[\"table\"]}\")')]
        for kv in trees.root_key_values(c, prof, r, random.Random(0), 50):
            row = dict(zip(cols, c.execute(f'SELECT * FROM \"{r[\"table\"]}\" WHERE \"{person[\"key\"]}\" = ?', (kv,)).fetchone()))
            got['+'.join(trees.lookup(c, r['table'], person, row)) or 'none'] += 1
        print(k, r['table'], dict(got))"
```
Expected（每个根抽 50 人）：
- beer_factory customers：`{'Email': 50}`
- movies_4 person：`{'person_name': 49, 'none': 1}`
- college_2 student：`{'none': 23, 'name': 27}`；instructor：`{'name': 50}`
- legislator historical：`{'first_name+last_name': 44, 'none': 6}`
- IPL player：`{'player_name': 50}`

重名多的库（college_2 的学生、legislator）有一部分人拿不到 `lookup`，这些人就不出子查询形状。

- [ ] **Step 6: commit**

```bash
cd $REPO
git add taskgen/v2/taskgen_v2/trees.py taskgen/v2/tests/test_taskgen_trees.py
git diff --cached --name-only
git commit -m "feat(taskgen v2): each tree records what alone identifies its person

A column only this person has (an email, phone or SSN-like column whose value no other row shares), else the
name when nobody else has it. The subquery shape will look the person up by it; names alone repeat too often
(movies_4 has 1497 shared names) and picked the wrong student in plan 2's smoke run.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
Expected：暂存区只有这两个文件。

---

### Task 4: 出题计划与 prompt

**Files:**
- Rewrite: `taskgen/v2/taskgen_v2/prompt.py`（整个文件换掉）
- Rewrite: `taskgen/v2/taskgen_v2/examples.json`（整个文件换掉）
- Modify: `taskgen/v2/taskgen_v2/generate.py`（import、新函数 `context`、`run` 的参数和两处调用）
- Modify: `taskgen/v2/scripts/taskgen.py`（`cmd_generate` 改读档案素材）
- Test: `taskgen/v2/tests/test_taskgen_prompt.py`（整个文件换掉）、`taskgen/v2/tests/test_taskgen_generate.py`

**Interfaces:**
- Consumes:
  - Task 2：`schema.schema_block(db_path, tables)`、`schema.key_notes(conn, tables, no_insert, fks)`、`schema.pk_info(conn)`。
  - Task 3：树的 `"lookup"`。
  - 计划 2：`trees.pick_events`、`trees.tables_by_label`、`trees.shown`、`trees.has_public`；`db_profile.scope_tables`、`db_profile.edges`、`db_profile.Edge`。
- Produces:
  - `generate.context(db_rec, profile) -> dict`：`{"description", "quirks", "schema", "keys": {表: 主键说明}, "no_insert": set, "fixed": {表: 主键和外键列}, "copyable": set}`。
  - `prompt.sample_plan(rng, tree, anchor, cfg=CFG, ctx=None) -> dict`：计划多了 `"scope"`（这一类型能写的表）、`"targets"`（`"表.列"`，最多 2 个），`"shape"` 多了 `"batch"`（`None` 或 `{"table", "label", "count", "all"}`），`"archive"` 由布尔值改成表名或 `None`；`"style"` 的 `"opener"` 改名 `"tone"`；`"difficulty"` 由形状推出。
  - `prompt.build_messages(db_rec, anchor, tree, plan, materials, cfg=CFG)`：`materials` 就是 `context()` 的结果。
  - `prompt.level(features) -> str`、`prompt.sql_value(v) -> str`、`prompt.rows_by_table(tree, refs) -> dict`。
  - `generate.run(db_rec, anchor, trees_list, client, out_path, rng, workers=8, per_tree=1, cfg=prompt.CFG, materials=None, retry_errors=False)`：去掉 `db_description`、`schema_text`、`next_ids`。
  - `prompt.next_ids_block`、`OPENERS`、`TYPE_TEXT["4_other_person"]`、`CFG["DIFFICULTY_MIX"]` 都删掉。

这个 Task 改的是出题的核心，所以下面先说清楚新计划怎么抽、prompt 里说什么，再给代码。

**出题计划怎么抽（`sample_plan`）：**
1. 类型按 `TYPE_MIX` 在这棵树能出的类型里抽（没有公共行的树只出 1、5）。
2. 写语句数按 `WRITES_MIX` 抽；第 2 类至少 2 条。展示的事件数按写语句数定：1 条 3–5 个，2 条 5–8 个，3 条以上 8–12 个。
3. 这一类型能写的表（`scope`）：第 1、5 类是标 own 的表，第 3 类是标 public 的表，第 2 类两者都要。
4. 形状，只在树允许时才抽：
   - **批量**（`BATCH`，不出给第 3 类）：这个人的某个事件组有 2–50 行时，挑最大的那组，一条 UPDATE/DELETE 改其中多行。其中 `BATCH_ALL` 的比例是整组全改，其余按条件挑，条件的值要照 SQL 的写法写进 instruction。
   - **archive**（`ARCHIVE`，至少 2 条写）：把某张事件表的行复制成同表的新行，再改或删原行。只用 `copyable` 的表（新行的键能省略、或者没有主键，而且不在 `no_insert` 里），不用根表；和批量同时抽中时，用批量那张表，否则不出 archive。
   - **子查询**（`SUBQUERY`，不出给第 3 类）：树有 `lookup` 时，用 `WHERE key = (SELECT key FROM 根表 WHERE lookup 列 = 值)` 找人；其余情况一律直接写 `key = 值`。
   - **两张表**（`TWO_TABLES`，至少 2 条写、能写的表不少于 2 张）；第 2 类总是两张（一张 own、一张 public）。
5. 难度由形状推出，用和执行检查同样的打分（多条写、多张表、子查询、archive、第 2 类各算一分；0 分 easy，1–2 分 medium，3 分以上 hard）。
6. "改什么"（`targets`）：在要写的表的展示行里，挑最多 2 个不是主键、不是外键、值不长的列，提示"如果 UPDATE，改这些列"。
7. 30% 的计划不指定写哪几张表，让模型在 `scope` 里自己挑。

**prompt 里说什么：**
- SYSTEM：只要改动，不要提问或让 agent 查、报、确认；SQL 用到的每个值都写进 instruction（例外：本人的标识字段、键说明里可省略的新键）；要改的记录按数据里的 id 指明；只写 INSERT/UPDATE/DELETE，条数照形状；表名加双引号；UPDATE/DELETE 必须命中展示的行，每条不超过 50 行；不改键列，新行的键按键说明来，`no new rows` 的表不 INSERT；名字和值照抄，哪怕看起来拼错；不碰别人的数据。接着原样放官方的 "Principles for generating SQL calls" 6 条（agent policy）；然后是输出格式，和一条按类型抽的手写示例。
- USER：档案的描述和数据怪异点；数据块（同计划 2）；范围内的 DDL 和列说明；这一计划能写的表的键说明；类型说明（开头一句要给名字和 ID，写法用 ID 一词或列名，例如 `CustomerID 344702` 或 `ID 344702`；第 1、5 类不往根表新建行）；形状；风格（语气、40–80 词、3–4 句、不照抄示例）。

`CFG` 里的比例是在计划 2 的 3556 棵树上模拟出来的（见"本计划新定的事"第 4 条），注释里写了来由。

- [ ] **Step 1: 写失败的测试**

`tests/test_taskgen_prompt.py` 整个换成：

```python
# tests/test_taskgen_prompt.py
import random
from collections import Counter
from taskgen_v2 import metrics, prompt

ANCHOR = {"table": "customers", "key": "customer_id", "names": ["first_name", "last_name"]}
DB = {"source": "test", "db": "shop", "path": "x", "anchors": [], "fks": []}
CTX = {"no_insert": {"reviews"}, "copyable": {"orders", "products"}, "fixed": {"orders": {"order_id", "customer_id", "product_id"}, "products": {"product_id"},
                                           "customers": {"customer_id"}, "reviews": {"review_id", "customer_id"}}}
MATERIALS = {**CTX, "description": "A small shop.", "quirks": ["qty is never 0."], "schema": "CREATE TABLE customers (...)",
             "keys": {"orders": "- orders: a new row may leave order_id out (SQLite assigns 101)",
                      "reviews": "- reviews: no new rows (UPDATE or DELETE only)", "unrelated": "- unrelated: no primary key"}}


def order(i, label="own"):
    return {"table": "orders", "row": {"order_id": i, "customer_id": 5, "product_id": i, "qty": 1}, "label": label,
            "parents": [{"table": "products", "row": {"product_id": i, "name": f"p{i}", "price": 1.0}, "label": "public", "parents": []}]}


TREE = {"anchor_table": "customers", "anchor_key": "customer_id", "key_value": 5, "anchor_name": "a5 b5",
        "anchor_row": {"customer_id": 5, "first_name": "a5", "last_name": "b5", "email": "a5@x.org"},
        "lookup": {"email": "a5@x.org"}, "profile_version": "v1",
        "parents": [{"table": "staff", "row": {"staff_id": 2, "name": "s2"}, "label": "other:s2", "parents": []}],
        "attributes": {"vip": [{"customer_id": 5, "level": 3}]},
        "events": [{"table": "orders", "label": "orders", "count": 14, "rows": [order(i) for i in range(12)]},
                   {"table": "reviews", "label": "reviews", "count": 1,
                    "rows": [{"table": "reviews", "row": {"review_id": 1, "customer_id": 5, "stars": 4}, "label": "own", "parents": []}]}]}
NO_PUBLIC = {**TREE, "events": [TREE["events"][1]]}
NO_EVENTS = {**TREE, "events": [], "parents": [], "lookup": {}}


def plans(n=3000, tree=TREE, seed=0):
    rng = random.Random(seed)
    return [prompt.sample_plan(rng, tree, ANCHOR, prompt.CFG, CTX) for _ in range(n)]


def plan_for(task_type, tree=TREE, **shape):
    rng = random.Random(0)
    while True:
        p = prompt.sample_plan(rng, tree, ANCHOR, prompt.CFG, CTX)
        if p["task_type"] == task_type and all(p["shape"][k] == v for k, v in shape.items()):
            return p


def test_examples_are_dysql_style_for_the_four_types():
    ex = prompt.load_examples()
    assert set(ex) == set(prompt.CFG["TYPE_MIX"]) == {"1_self", "2_self_and_public", "3_public_only", "5_proxy"}
    for t, xs in ex.items():
        assert len(xs) >= 3, t
        for x in xs:
            assert 40 <= len(x.split()) <= 80 and metrics.ID_RE.search(" ".join(x.split()[:25])) and not metrics.ASK.search(x), x


def test_no_type_4_and_public_types_need_a_public_row():
    assert prompt.feasible_types(TREE) == ["1_self", "2_self_and_public", "3_public_only", "5_proxy"]
    assert prompt.feasible_types(NO_PUBLIC) == ["1_self", "5_proxy"]


def test_types_and_write_counts_follow_the_mix():
    ps = plans()
    types, writes = Counter(p["task_type"] for p in ps), Counter(p["shape"]["n_writes"] for p in ps)
    assert abs(types["1_self"] / 3000 - 0.47) < 0.04 and abs(types["5_proxy"] / 3000 - 0.29) < 0.04
    assert abs(writes[1] / 3000 - 0.37 * 0.83) < 0.04 and abs(writes[2] / 3000 - 0.47) < 0.05   # type 2 never writes once
    assert abs((writes[4] + writes[5]) / 3000 - 0.09) < 0.03
    assert all(p["shape"]["n_writes"] >= 2 and p["shape"]["n_tables"] == 2 for p in ps if p["task_type"] == "2_self_and_public")


def test_each_type_writes_only_its_own_kind_of_table():
    for p in plans():
        tabs, w = p["tables"], p["write_tables"]
        pool = {"1_self": tabs["own"], "5_proxy": tabs["own"], "3_public_only": tabs["public"]}.get(p["task_type"], tabs["own"] + tabs["public"])
        assert p["scope"] == pool and p["shape"]["n_tables"] <= max(2, len(pool))
        if w:
            assert set(w) <= set(pool) and len(w) == p["shape"]["n_tables"]
            if p["task_type"] == "2_self_and_public":
                assert w[0] in tabs["own"] and w[1] in tabs["public"]


def test_shapes_only_where_the_tree_allows_them():
    ps = plans()
    batch = [p for p in ps if p["shape"]["batch"]]
    assert 0.08 < len(batch) / 3000 < 0.14 and 0.5 < sum(p["shape"]["batch"]["all"] for p in batch) / len(batch) < 0.7
    assert all({**p["shape"]["batch"], "all": 0} == {"table": "orders", "label": "orders", "count": 14, "all": 0}
               and p["task_type"] != "3_public_only" for p in batch)
    arch = [p for p in ps if p["shape"]["archive"]]
    assert arch and all(p["shape"]["n_writes"] >= 2 and p["shape"]["archive"] in ("orders", "products") for p in arch)
    assert all(p["shape"]["archive"] != "reviews" for p in arch)              # not copyable: no new rows
    sub = [p for p in ps if p["shape"]["ownership_subquery"]]
    assert 0.09 < len(sub) / 3000 < 0.15 and all(p["task_type"] != "3_public_only" for p in sub)
    for p in plans(400, NO_EVENTS):                                           # hr_1: most roots have no events
        s = p["shape"]
        assert not s["batch"] and not s["archive"] and not s["ownership_subquery"] and s["n_tables"] <= len(p["scope"])


def test_difficulty_comes_from_the_shape_like_the_check():
    for p in plans(500):
        s = p["shape"]
        feats = [s["n_writes"] >= 2, s["n_tables"] >= 2, s["ownership_subquery"], s["archive"], p["task_type"] == "2_self_and_public"]
        assert p["difficulty"] == prompt.level(feats)
        lo, hi = prompt.CFG["EVENTS_SHOWN"][min(s["n_writes"], 3)]
        assert lo <= len(p["events"]) <= hi or len(p["events"]) == sum(len(g["rows"]) for g in TREE["events"])


def test_targets_are_short_columns_that_are_not_keys():
    for p in plans(300):
        for x in p["targets"]:
            t, c = x.split(".")
            assert c not in CTX["fixed"].get(t, ()) and t in (p["write_tables"] or p["scope"])


def test_long_data_loses_events_until_it_fits():
    big = {**TREE, "events": [{**TREE["events"][0], "rows": [{**order(i), "row": {**order(i)["row"], "note": "x" * 150}} for i in range(12)]}]}
    cfg = {**prompt.CFG, "DATA_CHARS": 1200}
    p = prompt.sample_plan(random.Random(3), big, ANCHOR, cfg, CTX)
    assert 1 <= len(p["events"]) < prompt.CFG["EVENTS_SHOWN"][1][0]
    assert len(prompt.data_blocks(big, p["events"], "x", cfg)) <= 1200 or len(p["events"]) == 1


def test_data_blocks_nest_parents_and_say_whose_data_it_is():
    text = prompt.data_blocks(TREE, [[0, 0], [1, 0]], "the speaker's own row")
    assert text.startswith('## customers record (the speaker\'s own row)\n{"customer_id": 5, "first_name": "a5", "last_name": "b5"')
    assert '- vip (own): {"customer_id": 5, "level": 3}' in text
    assert '- staff (another person\'s data: s2): {"staff_id": 2, "name": "s2"}' in text
    assert "## orders: orders records (1 of 14 shown)\n- orders (own): " in text
    assert '\n  - products (public, shared reference data owned by nobody): {"product_id": 0' in text
    long = {**TREE, "anchor_row": {**TREE["anchor_row"], "bio": "y" * 500}}
    assert '"bio": "' + "y" * 200 + '... (500 chars)"' in prompt.data_blocks(long, [], "x")


def test_messages_hold_the_rules_materials_and_plan():
    p = plan_for("1_self", batch={"table": "orders", "label": "orders", "count": 14, "all": False}, ownership_subquery=False)
    sysm, u = (m["content"] for m in prompt.build_messages(DB, ANCHOR, TREE, p, MATERIALS))
    assert "only asks for changes" in sysm and "no SELECT statements" in sysm and "outputs" not in sysm
    assert "## Principles for generating SQL calls\n- At the beginning of the conversation, you have to authenticate" in sysm
    assert "must deny any requests for tasks related to any other user" in sysm   # DySQL's agent policy, verbatim
    assert "Wrap every table name in double quotes" in sysm and f"## Instruction example (for style only" in sysm and p["example"] in sysm
    assert u.startswith("# Database\nA small shop.\n\nData quirks (copy names and values exactly as stored):\n- qty is never 0.")
    assert "CREATE TABLE customers" in u and "unrelated" not in u                          # key notes of the tables in scope only
    assert ("The speaker is a5 b5, the person in customers with customer_id = 5. Their first sentence gives their name and their ID, "
            "written with the word ID or the column name (customer_id 5 or ID 5).") in u
    assert "no new row is added to customers (that would be a new person)" in u   # the pilots' type mismatches did that
    assert "changes several of the person's orders rows in orders at once (there are 14)" in u and "between 2 and 13 rows" in u
    assert "written in the instruction exactly as the SQL uses it" in u
    assert "identify the person by customer_id = 5; names can repeat" in u and "40 to 80 words" in u


def test_subquery_archive_batch_and_proxy_wording():
    p = plan_for("1_self", batch={"table": "orders", "label": "orders", "count": 14, "all": True})
    u = prompt.build_messages(DB, ANCHOR, TREE, p, MATERIALS)[1]["content"]
    assert "changes all 14 of the person's orders rows in orders at once; the instruction says it means all of them." in u
    p = plan_for("1_self", ownership_subquery=True, archive="orders")
    u = prompt.build_messages(DB, ANCHOR, TREE, p, MATERIALS)[1]["content"]
    assert "WHERE customer_id = (SELECT customer_id FROM \"customers\" WHERE email = 'a5@x.org'), instead of writing customer_id = 5." in u
    assert 'First copy the orders rows you will change as new rows with INSERT INTO "orders" ... SELECT ... FROM "orders"' in u
    p5 = plan_for("5_proxy")
    u = prompt.build_messages(DB, ANCHOR, TREE, p5, MATERIALS)[1]["content"]
    assert f"The speaker is not in the database: {p5['style']['name']}, {p5['style']['role']}." in u and "the person the request is about" in u


def test_sql_value_quotes_text():
    assert prompt.sql_value("O'Brien") == "'O''Brien'" and prompt.sql_value(42) == "42"


def test_style_varies_tones_names_and_roles():
    ps = plans(400, seed=1)
    proxies = [p for p in ps if p["task_type"] == "5_proxy"]
    assert len({p["style"]["name"] for p in proxies}) > 30 and len({p["style"]["role"] for p in proxies}) >= 8
    assert all(p["style"]["name"] is None for p in ps if p["task_type"] != "5_proxy")
    assert len({p["style"]["tone"] for p in ps}) >= 6 and not any("question" in t for t in prompt.TONES)
```

`tests/test_taskgen_generate.py`：import 部分换成：

```python
import json, random
import pytest
from taskgen_common.testing import make_db
from v2_fixtures import SHOP2, FKS, SHOP_PROFILE
from taskgen_v2 import generate, io
from test_taskgen_prompt import ANCHOR, DB, TREE
```

文件末尾加：

```python
def test_context_gathers_what_every_prompt_of_a_database_shares(tmp_path):
    rec = {"source": "test", "db": "shop2", "path": make_db(tmp_path, "shop2", SHOP2), "anchors": [], "fks": FKS}
    prof = {**SHOP_PROFILE, "no_insert": ["products"], "quirks": ["qty is never 0."]}
    ctx = generate.context(rec, prof)
    assert ctx["description"] == "A small shop." and ctx["quirks"] == ["qty is never 0."] and ctx["no_insert"] == {"products"}
    assert set(ctx["keys"]) == {"customers", "orders", "order_items", "products", "staff"}
    assert ctx["keys"]["products"] == "- products: no new rows (UPDATE or DELETE only)"
    assert ctx["keys"]["orders"] == "- orders: a new row may leave order_id out (SQLite assigns 100)"
    assert ctx["fixed"]["orders"] == {"order_id", "customer_id", "product_id"} and ctx["fixed"]["order_items"] == {"item_id", "order_id"}
    assert "CREATE TABLE orders" in ctx["schema"] and ctx["copyable"] == {"customers", "orders", "order_items", "staff"}
```

- [ ] **Step 2: 跑测试，确认失败**

```bash
cd $REPO/taskgen/v2 && $P -m pytest -q tests/test_taskgen_prompt.py tests/test_taskgen_generate.py 2>&1 | tail -n 4
```
Expected: 12 个失败，10 个通过。失败的是新 prompt 测试里的 11 个（除了 `test_no_type_4_and_public_types_need_a_public_row` 和 `test_data_blocks_nest_parents_and_say_whose_data_it_is`；旧代码没有 `level`、`sql_value`、`tone`、新的形状和措辞，报 `AttributeError`、`KeyError` 或断言不符），加上 `test_context_gathers_what_every_prompt_of_a_database_shares`（`AttributeError: module 'taskgen_v2.generate' has no attribute 'context'`）。

- [ ] **Step 3: 实现**

`taskgen_v2/prompt.py` 整个换成：

```python
# taskgen/v2/taskgen_v2/prompt.py
"""Task plan sampling (type x write count x shape) and the generation prompt (design §4.3, §4.4). The SYSTEM message
holds the rules and one hand-written example for the task type; the USER message holds the database (description,
quirks, the event tree with whose data each row is, the schema and key notes) and the plan."""
import json, os, random
from taskgen_v2 import trees

CFG = {
    # weights before a tree's feasible types are taken: legislator, student_loan and synthea have no public rows, so
    # over the 23 databases this lands near design §3's 50/13/6/31 (simulated on the plan-2 trees: 49/15/6/30)
    "TYPE_MIX": {"1_self": 0.47, "2_self_and_public": 0.17, "3_public_only": 0.07, "5_proxy": 0.29},   # no type 4 (D6)
    # write statements per task; type 2 never writes once, so overall this lands near DySQL's 33/45/13/6/3 (§4.4)
    "WRITES_MIX": {1: 0.37, 2: 0.41, 3: 0.13, 4: 0.06, 5: 0.03},
    # shape shares, set so the task-level rates over the 23 databases match DySQL's gold (simulated on the plan-2
    # trees): two tables 57%, subquery 12%, archive 6.4%, batch 7%
    "TWO_TABLES": 0.85,      # multi-write tasks that write two tables, when two are in scope
    "SUBQUERY": 0.13,        # tasks that find the person through a subquery (D8), when the tree has a lookup
    "BATCH": 0.12,           # tasks with one UPDATE/DELETE over 2-50 of the person's rows, when a group has 2 to 50
    "BATCH_ALL": 0.6,        # ... of which change all of the group's rows (DySQL: "all my invoices"), the rest by a condition
    "ARCHIVE": 0.18,         # multi-write tasks that copy rows with INSERT ... SELECT before changing them, when a table can
    "FREE_TABLE_SHARE": 0.30,
    "MAX_ROWS_PER_STMT": 50,
    "WORDS": (40, 80),       # instruction length asked for (DySQL: mean 57, p90 80)
    "EVENTS_SHOWN": {1: (3, 5), 2: (5, 8), 3: (8, 12)},   # by write count (3 = three or more), design §4.2
    "DATA_CHARS": 16000,      # data blocks longer than this lose events from the end (about 4k tokens)
    "MAX_VALUE_CHARS": 200,   # longer text values are cut in the prompt
}
PUBLIC_TYPES = ("2_self_and_public", "3_public_only")
# style pools: the pilot reused the same invented names ("Priya Raghavan" x6) and roles, so a proxy speaker gets a
# sampled name and role, and every plan a sampled tone
FIRST_NAMES = ["Aisha", "Ben", "Carlos", "Dmitri", "Elena", "Farid", "Grace", "Hiro", "Ingrid", "Jamal", "Keiko", "Luis",
               "Maren", "Nikhil", "Olu", "Petra", "Quinn", "Rosa", "Sven", "Tomasz", "Uma", "Viktor", "Wen", "Ximena",
               "Yusuf", "Zoe", "Amara", "Bastian", "Chloe", "Diego", "Esther", "Felix", "Gwen", "Hassan", "Ines", "Jonas",
               "Kwame", "Leila", "Mateo", "Noor", "Oscar", "Priya", "Rafael", "Sanjay", "Tessa", "Ulrich", "Vera", "Walter"]
LAST_NAMES = ["Abbott", "Bauer", "Castillo", "Dubois", "Eriksen", "Ferreira", "Gallagher", "Haddad", "Ivanova", "Jensen",
              "Kowalski", "Lindqvist", "Moreau", "Nakamura", "Oyelaran", "Petrov", "Quiroga", "Rossi", "Schneider",
              "Takahashi", "Underwood", "Varga", "Whitaker", "Xu", "Yilmaz", "Zimmerman", "Adeyemi", "Brennan", "Chen",
              "Delacroix", "Espinoza", "Fischer", "Goldberg", "Hoffmann", "Iqbal", "Jorgensen", "Kim", "Lopez", "Mbeki",
              "Novak", "Okafor", "Pereira", "Rahman", "Santos", "Thornton", "Vasquez", "Weber", "Yamada"]
ROLES = ["data analyst", "account manager", "support agent handling a ticket", "internal auditor", "branch supervisor",
         "intern doing data entry", "compliance officer", "sales representative", "operations coordinator",
         "customer success manager", "database administrator", "quality assurance reviewer", "regional manager",
         "billing specialist", "field technician", "office assistant"]
TONES = ["terse and businesslike, straight to the change", "friendly, with a short reason for the change",
         "formal, like a support ticket", "a little impatient because this was asked before", "a casual chat message",
         "explains that someone else asked for the change", "apologetic, fixing an earlier mistake",
         "lists the changes as numbered steps", "mentions a deadline as the reason"]
EXAMPLES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "examples.json")

SYSTEM = """You write tasks for training a database customer-service agent. A task is one user's request, written as the user would type it to the agent, and the SQL statements ('actions') that carry it out.

## The instruction
1. The speaker writes in the first person and only asks for changes: no questions, no requests to look anything up, report or confirm.
2. Every value the SQL uses appears in the instruction: ids, keys, names, amounts, dates and new values. The only exceptions are the person's own identifying fields and new keys that the key notes say may be left out.
3. Each record to change is named by its id or key as shown in the data (for example "order 7731"), never only described.

## The actions
4. Only INSERT, UPDATE or DELETE statements, one per action, exactly as many as the task shape asks; no SELECT statements.
5. Standard SQLite. Wrap every table name in double quotes ("transaction" and "order" are keywords); quote column names with spaces or punctuation.
6. Every UPDATE or DELETE matches at least one row shown in the data; no statement changes more than {max_rows} rows.
7. Never change a key column. Give new rows their keys as the key notes say, and never INSERT into a table marked "no new rows".
8. Copy table names, column names and stored values exactly, even when they look misspelled or oddly formatted.

## Principles for generating SQL calls
- At the beginning of the conversation, you have to authenticate the user identity by locating their user.
- Once the user has been authenticated, you can provide the user with information, e.g. help the user look up order id.
- You can only help one user per conversation (but you can handle multiple requests from the same user), and must deny any requests for tasks related to any other user.
- You should not make up any information or knowledge or procedures not provided from the user, or give subjective recommendations or comments.
- You should at most make one sql call at a time, and if you take a sql call, you should not respond to the user at the same time. If you respond to the user, you should not make a sql call.
- You should transfer the user to a human agent if and only if the request cannot be handled within the scope of your actions.

These are the agent's policy (DySQL's data_pipeline_shell/sql_wiki.md), so a task never changes rows marked as another person's.

## Output format
Think inside <thought></thought>, then give the final answer inside <answer></answer> as strict JSON without comments:
{{"instruction": "...", "actions": [{{"sql": "..."}}, {{"sql": "..."}}]}}

## Instruction example (for style only: do not copy its wording, its values or its actions)
{example}"""

USER = """# Database
{description}
{quirks}
{data_blocks}

## Schema
{schema}

## Key notes
{keys}

## Task type
{type_text}

## Task shape
{shape_text}

## Style
{style_text}

Generate the task now."""

TYPE_TEXT = {
    "1_self": "The speaker is {name}, the person in {t} with {key} = {kv}. Their first sentence gives their name and their ID, written with the word ID or the column name ({key} {kv} or ID {kv}). Every write changes only rows marked own: rows marked public stay unchanged, and no new row is added to {t} (that would be a new person) or to a public table.",
    "2_self_and_public": "The speaker is {name}, the person in {t} with {key} = {kv}. Their first sentence gives their name and their ID, written with the word ID or the column name ({key} {kv} or ID {kv}). At least one write changes a row marked own and at least one changes a row marked public ({up}).",
    "3_public_only": "The speaker is {name}, the person in {t} with {key} = {kv}. Their first sentence gives their name and their ID, written with the word ID or the column name ({key} {kv} or ID {kv}). The writes change only rows marked public ({up}); none of the speaker's own rows change.",
    "5_proxy": "The speaker is not in the database: {proxy}. Their first sentence gives their own name and role, and the name and ID of {name}, whose data they ask to change, written with the word ID or the column name ({key} {kv} or ID {kv}). Every write changes only rows marked own (that person's rows): rows marked public stay unchanged, and no new row is added to {t} (that would be a new person).",
}


def load_examples():
    with open(EXAMPLES_PATH, encoding="utf-8") as f:
        return json.load(f)


def _weighted(rng, weights):
    keys, w = zip(*weights.items())
    return rng.choices(keys, weights=w, k=1)[0]


def feasible_types(tree):
    """Types this tree can carry. Never 4_other_person (design D6); 2 and 3 need a public row to write."""
    return ["1_self"] + (list(PUBLIC_TYPES) if trees.has_public(tree) else []) + ["5_proxy"]


def _who(task_type):
    return "the speaker's own row" if task_type != "5_proxy" else "the person the request is about"


def rows_by_table(tree, refs):
    """{table: [row, ...]} of every row the prompt shows: the root row, its attributes and parents, and the shown
    events with their parents."""
    out = {}

    def walk(node):
        out.setdefault(node["table"], []).append(node["row"])
        for p in node["parents"]:
            walk(p)
    out[tree["anchor_table"]] = [tree["anchor_row"]]
    for t, rs in tree["attributes"].items():
        out.setdefault(t, []).extend(rs)
    for p in tree["parents"]:
        walk(p)
    for g in trees.shown(tree, refs):
        for n in g["rows"]:
            walk(n)
    return out


def _targets(rng, shown, tables, fixed, k=2):
    """Up to k 'table.column' values worth changing (design §4.4): columns of shown rows that are not keys or foreign
    keys and hold a short value, one per table where possible."""
    out = []
    for t in rng.sample(tables, len(tables)):
        cols = sorted({c for r in shown.get(t, []) for c, v in r.items()
                       if c not in fixed.get(t, ()) and v not in (None, "") and len(str(v)) <= 60})
        if cols:
            out.append(f"{t}.{rng.choice(cols)}")
        if len(out) == k:
            break
    return out


def sql_value(v):
    """A value as an SQL literal: text in single quotes (doubled inside), numbers as they are."""
    return "'" + v.replace("'", "''") + "'" if isinstance(v, str) else str(v)


def level(features):
    """check.difficulty's levels from the same features: none easy, one or two medium, three or more hard."""
    score = sum(bool(f) for f in features)
    return "easy" if score == 0 else "medium" if score <= 2 else "hard"


def sample_plan(rng, tree, anchor, cfg=CFG, ctx=None):
    """ctx: generate.context() of the database -- "fixed" {table: key and foreign-key columns}, never a change target,
    and "copyable", the tables an archive may copy rows into (keys SQLite fills in, open to INSERT)."""
    ctx = ctx or {}
    fixed, copyable = ctx.get("fixed") or {}, set(ctx.get("copyable") or ())
    task_type = _weighted(rng, {k: v for k, v in cfg["TYPE_MIX"].items() if k in feasible_types(tree)})
    n_writes = _weighted(rng, cfg["WRITES_MIX"])
    if task_type == "2_self_and_public":
        n_writes = max(n_writes, 2)
    lo, hi = cfg["EVENTS_SHOWN"][min(n_writes, 3)]
    refs = trees.pick_events(tree, rng, rng.randint(lo, hi), need_public=task_type in PUBLIC_TYPES)
    while len(refs) > 1 and len(data_blocks(tree, refs, _who(task_type), cfg)) > cfg["DATA_CHARS"]:
        refs.pop()                                           # the event a public type needs is first, so it stays
    tabs = trees.tables_by_label(tree, refs)
    pool = {"3_public_only": tabs["public"], "2_self_and_public": tabs["own"] + tabs["public"]}.get(task_type, tabs["own"])
    events = {g["table"] for g in tree["events"]}

    batch = None   # one statement over 2-50 of the person's rows of one event group: all of them, or by a condition
    groups = [g for g in tree["events"] if 2 <= g["count"] <= cfg["MAX_ROWS_PER_STMT"] and g["table"] in tabs["own"]]
    if task_type != "3_public_only" and groups and rng.random() < cfg["BATCH"]:
        g = max(groups, key=lambda g: g["count"])
        batch = {"table": g["table"], "label": g["label"], "count": g["count"], "all": rng.random() < cfg["BATCH_ALL"]}
    archive = None   # copy rows as new rows of the same table, then change the originals; with a batch, its table
    sources = [t for t in pool if t in copyable and t != anchor["table"] and (t in events or task_type == "3_public_only")]
    if n_writes >= 2 and sources and rng.random() < cfg["ARCHIVE"]:
        archive = rng.choice(sources) if not batch else batch["table"] if batch["table"] in sources else None
    subquery = bool(tree.get("lookup")) and task_type != "3_public_only" and rng.random() < cfg["SUBQUERY"]

    n_tables = 1
    if task_type == "2_self_and_public":
        n_tables = 2
    elif n_writes >= 2 and len(pool) >= 2 and rng.random() < cfg["TWO_TABLES"]:
        n_tables = 2
    must = archive or (batch and batch["table"])   # the one table a batch or an archive needs written
    write_tables = None
    if rng.random() >= cfg["FREE_TABLE_SHARE"]:
        if task_type == "2_self_and_public":
            write_tables = [must or rng.choice(tabs["own"]), rng.choice(tabs["public"])]
        else:
            rest = [t for t in pool if t != must]
            write_tables = ([must] if must else []) + rng.sample(rest, n_tables - bool(must))
    shape = {"n_writes": n_writes, "n_tables": n_tables, "ownership_subquery": subquery, "archive": archive,
             "batch": batch, "public_table": task_type in PUBLIC_TYPES}
    difficulty = level([n_writes >= 2, n_tables >= 2, subquery, archive, task_type == "2_self_and_public"])
    style = {"tone": rng.choice(TONES), "name": None, "role": None}
    if task_type == "5_proxy":
        style.update(name=f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}", role=rng.choice(ROLES))
    return {"task_type": task_type, "difficulty": difficulty, "shape": shape, "write_tables": write_tables,
            "events": refs, "tables": tabs, "scope": pool,
            "targets": _targets(rng, rows_by_table(tree, refs), write_tables or pool, fixed),
            "example": rng.choice(load_examples()[task_type]), "style": style}


def _short(row, cfg):
    """Long text (WWE keeps whole HTML pages in Cards) is cut for the prompt; nobody edits it by quoting it."""
    n = cfg["MAX_VALUE_CHARS"]
    return {k: (v[:n] + f"... ({len(v)} chars)" if isinstance(v, str) and len(v) > n else v) for k, v in row.items()}


def _label_text(label):
    if label.startswith("other:"):
        return f"another person's data: {label[6:]}"
    return {"own": "own", "public": "public, shared reference data owned by nobody"}.get(label, label)


def data_blocks(tree, refs, who, cfg=CFG):
    """The root row with its attributes and parent rows, then each shown event group; parent rows are indented under
    the row that references them, and every row says whose data it is."""
    def js(row):
        return json.dumps(_short(row, cfg), ensure_ascii=False, default=str)

    def lines(node, depth):
        out = [f"{'  ' * depth}- {node['table']} ({_label_text(node['label'])}): {js(node['row'])}"]
        for p in node["parents"]:
            out += lines(p, depth + 1)
        return out
    head = [f"## {tree['anchor_table']} record ({who})", js(tree["anchor_row"])]
    head += [f"- {t} (own): {js(r)}" for t, rs in tree["attributes"].items() for r in rs]
    head += [x for p in tree["parents"] for x in lines(p, 0)]
    blocks = ["\n".join(head)]
    for g in trees.shown(tree, refs):
        blocks.append(f"## {g['label']}: {g['table']} records ({len(g['rows'])} of {g['count']} shown)\n"
                      + "\n".join(x for n in g["rows"] for x in lines(n, 0)))
    return "\n\n".join(blocks)


def shape_text(anchor, tree, plan, cfg=CFG):
    s, lines = plan["shape"], []
    n, k = s["n_writes"], s["n_tables"]
    lines.append(f"- Exactly {n} write statement{'s' if n > 1 else ''} (INSERT, UPDATE or DELETE) on {k} table{'s' if k > 1 else ''}.")
    if plan["write_tables"]:
        lines.append(f"- Write to {', '.join(plan['write_tables'])}.")
    else:
        lines.append(f"- Choose the table{'s' if k > 1 else ''} among {', '.join(plan['scope'])}.")
    if s["public_table"]:
        lines.append(f"- At least one write changes a public table: {', '.join(plan['tables']['public'])}.")
    if s["batch"] and s["batch"]["all"]:
        b = s["batch"]
        lines.append(f"- One UPDATE or DELETE changes all {b['count']} of the person's {b['label']} rows in {b['table']} at once; "
                     f"the instruction says it means all of them.")
    elif s["batch"]:
        b = s["batch"]
        lines.append(f"- One UPDATE or DELETE changes several of the person's {b['label']} rows in {b['table']} at once (there "
                     f"are {b['count']}): select them by a condition such as a date range, a status or a value, written in the "
                     f"instruction exactly as the SQL uses it, not by listing ids; it changes between 2 and {b['count'] - 1} rows.")
    if s["archive"]:
        lines.append(f"- First copy the {s['archive']} rows you will change as new rows with INSERT INTO \"{s['archive']}\" ... "
                     f"SELECT ... FROM \"{s['archive']}\", then UPDATE or DELETE the original rows.")
    if s["ownership_subquery"]:
        cond = " AND ".join(f"{c} = {sql_value(v)}" for c, v in tree["lookup"].items())
        lines.append(f"- Find the person's rows through a subquery on {anchor['table']}, e.g. WHERE {anchor['key']} = "
                     f"(SELECT {anchor['key']} FROM \"{anchor['table']}\" WHERE {cond}), instead of writing {anchor['key']} = {sql_value(tree['key_value'])}.")
    elif plan["task_type"] != "3_public_only":
        lines.append(f"- In the SQL, identify the person by {anchor['key']} = {sql_value(tree['key_value'])}; names can repeat.")
    if plan["targets"]:
        lines.append(f"- If you UPDATE, change {' or '.join(plan['targets'])}.")
    return "\n".join(lines)


def style_text(plan, cfg=CFG):
    st, (lo, hi) = plan.get("style") or {}, cfg["WORDS"]
    return "\n".join([f"- Tone: {st.get('tone', 'natural')}.",
                      f"- {lo} to {hi} words in three or four sentences.",
                      "- Do not reuse phrases from the example, and do not open with 'Hi, this is' or 'Good morning'."])


def build_messages(db_rec, anchor, tree, plan, materials, cfg=CFG):
    """materials: generate.context() output -- the profile's description and quirks, the schema text, key notes."""
    tabs, st = plan["tables"], plan.get("style") or {}
    fmt = {"name": tree["anchor_name"] or f"the person with {anchor['key']} = {tree['key_value']}", "key": anchor["key"],
           "kv": tree["key_value"], "t": anchor["table"], "up": ", ".join(tabs["public"]) or "(none)",
           "proxy": f"{st.get('name')}, {st.get('role')}"}
    quirks = materials.get("quirks") or []
    user = USER.format(description=materials.get("description", ""),
                       quirks=("\nData quirks (copy names and values exactly as stored):\n" + "\n".join(f"- {q}" for q in quirks) + "\n") if quirks else "",
                       data_blocks=data_blocks(tree, plan["events"], _who(plan["task_type"]), cfg),
                       schema=materials.get("schema", ""),
                       keys="\n".join(materials.get("keys", {})[t] for t in plan["scope"] if t in materials.get("keys", {})) or "(none)",
                       type_text=TYPE_TEXT[plan["task_type"]].format(**fmt), shape_text=shape_text(anchor, tree, plan, cfg),
                       style_text=style_text(plan, cfg))
    system = SYSTEM.format(example=plan["example"], max_rows=cfg["MAX_ROWS_PER_STMT"])
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]
```

`taskgen_v2/examples.json` 整个换成（每类 4 条，手写；领域避开这 23 个库和 DySQL 的 13 个库；不用 v1 的产出，也不用 DySQL 的金标准，因为它是评测集）：

```json
{
  "1_self": [
    "I'm Marta Kowalczyk, member ID 4471 at Riverside Gym. Please cancel my spin class booking 90213 for Tuesday and book me into the Thursday 18:30 yoga session, class 5527, instead. My plan should also switch from 'Standard' to 'Off-Peak' from 2024-05-01, since I only come in the mornings now.",
    "Daniel Osei here, client ID 30982 at Elm Street Vets. You have my phone number wrong: it should be 020-7946-0233. I'm away the week of the 14th, so please move my dog Bruno's appointment 77120 from 2024-03-14 to 2024-03-21 at 09:40, with the same vet and the same room.",
    "This is Yuki Tanaka, account ID 88123 (yuki.t@example.jp). I'm moving, so please set the delivery address on all my laundry pickups that are still 'scheduled' to 14 Harbour Road, Kobe 650-0042. Pickups that are already done should stay as they are.",
    "Lena Brandt, student ID 20194 at the Lakeside Language School. The B1 class turned out to be too fast for me, so three changes, please: 1) withdraw me from Spanish B1, enrolment 66102; 2) enrol me in Spanish A2, course 3390, from 2024-04-08; 3) change my email to lena.brandt@mailbox.org."
  ],
  "2_self_and_public": [
    "I'm Ahmed Haddad, member ID 2201 at the Northside Allotments. I gave up plot P-17 at the end of March, so please end my tenancy 66102 with the date 2024-03-31. The plot itself should then be marked 'vacant', and its water meter reading updated to 1482.",
    "Priya Raman, guest ID 5120. My conference was moved online, so please cancel my reservation 3390 for room 214 on 2024-06-02. I also tried to call the Harbour Inn first: its record, hotel 12, still shows the old phone number, and it should be 0161 555 0170.",
    "Lars Nygaard, rider ID 812 with CityBikes. I returned bike 4471 to the Canal Street dock at 16:05 on 2024-02-11, so please close my rental 44018 with that time. Bike 4471 also has a broken bell, so set its status to 'repair'.",
    "This is Sofia Bianchi, passenger ID 1187. Please move my ferry booking 7731 from the 08:00 sailing to the 10:30 sailing, departure 902, on 2024-07-19. The 10:30 departure still lists 'Dock B', but boarding has moved to 'Dock D'; please correct it."
  ],
  "3_public_only": [
    "My name is Chloe Martin, supplier contact ID 217. Our product 'Oak Dining Chair', item 4410, is listed at 89.00, but the new wholesale price is 94.50. Please update its unit price and change its stock status from 'low' to 'in stock'.",
    "Tomás Ferreira, staff ID 44 at the physiotherapy clinic. Room 12 is still listed as 'Consultation', but it was refitted as a treatment room last week and the booking screen keeps offering it for talks. Please change its room type to 'Treatment' and its capacity from 2 to 4.",
    "This is Hannah Lee, guest ID 3021. The 'Deluxe King' room type, type 7, still says 2 guests at most; with the new sofa beds it takes 3. Please set its max occupancy to 3 and its nightly rate to 189.00.",
    "Owen Price, member ID 9081 of the allotment society. The petrol hedge trimmer, tool 315, was written off after the storm, so please delete it from the tool list. Tool 316, the electric one, is fixed now; mark it 'available'."
  ],
  "5_proxy": [
    "I'm Rachel Green from the housing office, updating the record of tenant Jonas Berg, tenant ID 5583. He moved from flat 12B to flat 4A on 2024-05-01, so please change his flat to '4A'. His old parking permit, 7710, should be cancelled from the same date.",
    "This is Omar Siddiqui from the billing team, about customer Isabel Torres, customer ID 2210. Her card was charged twice on invoice 90031 and she called us about it this morning. Please delete the duplicate payment 41877 and set that invoice's balance to 0.",
    "Sanjay Patel at the co-working front desk, writing for member Ines Moreau (member ID 6602), who asked me to sort this out while she travels. She is moving to the quiet floor: please change her desk assignment 3121 to desk 'Q-14'. Her locker rental 845 should end on 2024-06-30.",
    "I'm Grace Liu, assistant to Dr. Felix Brandt (vet ID 230) at Elm Street Vets. Three changes to his schedule: 1) cancel his 14:00 surgery slot 9921 on 2024-04-02; 2) add a 30-minute consultation for him on 2024-04-03 at 10:30 in room 2; 3) set his on-call status to 'off'."
  ]
}
```

`taskgen_v2/generate.py`：
- import 改成：

```python
import json, os, sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from taskgen_v2 import db_profile, io, llm, prompt, schema
```

- `class ParseError` 后面加：

```python
def context(db_rec, profile):
    """What every prompt of a database shares (design §4.3): the profile's description and quirks, the DDL and column
    notes of the tables in scope and a key note per table; and for plan sampling the key and foreign-key columns of
    each table ("fixed", never the target of a change) and the tables an archive may copy rows into ("copyable")."""
    path = io.resolve_db_path(db_rec["path"])
    scope = db_profile.scope_tables(profile)

    def cols_by_table(edges):
        out = {}
        for e in edges:
            out.setdefault(e.child, set()).update(e.cols)
        return out
    single = [(f, db_profile.Edge(f["table"], (f["col"],), f["ref_table"], (f["ref_col"],))) for f in db_rec.get("fks", ())]
    composite = [db_profile.Edge(f["table"], tuple(f["cols"]), f["ref_table"], tuple(f["ref_cols"])) for f in db_rec.get("fks_composite", ())]
    sure = db_profile.edges(profile) + composite + [e for f, e in single if f.get("source") == "declared"]
    fks, all_fks = cols_by_table(sure), cols_by_table(sure + [e for _, e in single])   # name-guessed keys only for targets
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        keys = schema.key_notes(conn, sorted(scope), set(profile["no_insert"]), fks)
        pk = {t: v for t, v in schema.pk_info(conn).items() if t in scope}
    finally:
        conn.close()
    fixed = {t: set(v["cols"]) | all_fks.get(t, set()) for t, v in pk.items()}
    # an archive copies rows into the same table, so the copies need keys SQLite fills in (or no key at all);
    # school_scheduling's Student_Schedules (StudentID, ClassID) would only collide with itself
    copyable = {t for t, v in pk.items() if (v["omittable"] or not v["cols"]) and t not in profile["no_insert"]}
    return {"description": profile["description"], "quirks": profile["quirks"], "schema": schema.schema_block(path, scope),
            "keys": keys, "no_insert": set(profile["no_insert"]), "fixed": fixed, "copyable": copyable}
```

- `run` 的签名和开头改成：

```python
def run(db_rec, anchor, trees_list, client, out_path, rng, workers=8, per_tree=1, cfg=prompt.CFG,
        materials=None, retry_errors=False):
    """materials: context() of this database."""
    materials = materials or {}
```

  里面两处调用改成：

```python
            plan = prompt.sample_plan(rng, tree, anchor, cfg, materials)
```

```python
        msgs = prompt.build_messages(db_rec, anchor, tree, plan, materials, cfg)
```

`scripts/taskgen.py` 的 `cmd_generate`：从 `path = io.resolve_db_path(rec["path"])` 到 `next_ids = schema.next_ids(path)` 这几行（读描述、要求先 `describe`、建客户端、算 next id）换成：

```python
    materials = generate.context(rec, prof)
    client = llm.client_from_env("GEN")
```

`generate.run(...)` 那一句的参数改成：

```python
        s = generate.run(rec, anchor, ts, client, f"{out}/candidates.jsonl",
                         random.Random(f"{a.seed}:{anchor['table']}"),   # per root: two roots must not draw the same plans
                         workers=a.workers, per_tree=a.per_tree, materials=materials, retry_errors=a.retry_errors)
```

- [ ] **Step 4: 跑测试，确认通过**

```bash
cd $REPO/taskgen/v2 && $P -m pytest -q tests/test_taskgen_prompt.py tests/test_taskgen_generate.py 2>&1 | tail -n 1 && $P -m pytest -q 2>&1 | tail -n 1
```
Expected: `22 passed`；整套 `146 passed`。

- [ ] **Step 5: 在真实库上看一份 prompt，再在 23 个库的树上模拟出题计划**

```bash
cd $REPO/taskgen/v2 && mkdir -p $S && $P scripts/taskgen.py trees --db bird:beer_factory --n 3 --seed 0 --out-dir $S/render && $P -c "
import random, sys; sys.path[:0] = ['.', '../common']
from taskgen_v2 import db_profile, generate, io, prompt
rec, prof = io.load_db_recs()['bird:beer_factory'], db_profile.get('bird:beer_factory')
mat, t = generate.context(rec, prof), io.read_jsonl('$S/render/trees.jsonl')[0]
p = prompt.sample_plan(random.Random(5), t, db_profile.root_anchor(prof, 'customers'), prompt.CFG, mat)
s, u = (m['content'] for m in prompt.build_messages(rec, db_profile.root_anchor(prof, 'customers'), t, p, mat))
print(u[u.index('## Key notes'):])"
```
Expected：输出从 `## Key notes` 开始，依次是 beer_factory 范围内各表的键说明、`## Task type`（"The speaker is John Gibson, the person in customers with CustomerID = 344702. Their first sentence gives their name and their ID ..."）、`## Task shape`、`## Style`，最后一行 `Generate the task now.`。读一遍，确认没有 `outputs`、没有只读提问的说法。

再把计划 2 的 23 个库的树拿来，每棵抽一个计划，看分布（脚本写在 `$S`）：

```bash
cat > $S/simulate_plans.py <<'EOF'
# one plan per tree of plan 2's trees of the 23 databases (results/plan2/trees, their lookup computed here, since
# those trees predate it), counted like design §3: types, write counts, difficulty, tables and shapes
import glob, os, random, sqlite3, sys
from collections import Counter
sys.path[:0] = [".", "../common"]
from taskgen_v2 import db_profile, generate, io, prompt, trees

recs, profs = io.load_db_recs(), db_profile.load()
by_db = {v["db"]: k for k, v in recs.items()}
rng, ps = random.Random(0), []
for f in sorted(glob.glob(os.path.join("results", "plan2", "trees", "*", "trees.jsonl"))):
    key = by_db[os.path.basename(os.path.dirname(f))]
    rec, prof = recs[key], profs[key]
    ctx = generate.context(rec, prof)
    conn = sqlite3.connect(f"file:{io.resolve_db_path(rec['path'])}?mode=ro", uri=True)
    for t in io.read_jsonl(f):
        t["lookup"] = trees.lookup(conn, t["anchor_table"], prof["persons"][t["anchor_table"]], t["anchor_row"])
        ps.append(prompt.sample_plan(rng, t, db_profile.root_anchor(prof, t["anchor_table"]), prompt.CFG, ctx))
n = len(ps)


def pct(c, keys):
    return " / ".join(f"{100 * c[k] / n:.1f}" for k in keys)


w = Counter(min(p["shape"]["n_writes"], 5) for p in ps)
share = lambda f: f"{100 * sum(1 for p in ps if f(p)) / n:.1f}"
print("plans", n)
print("type 1/2/3/5:", pct(Counter(p["task_type"] for p in ps), ["1_self", "2_self_and_public", "3_public_only", "5_proxy"]))
print("writes 1/2/3/4/5:", pct(w, [1, 2, 3, 4, 5]), "| >=3:", share(lambda p: p["shape"]["n_writes"] >= 3))
print("difficulty e/m/h:", pct(Counter(p["difficulty"] for p in ps), ["easy", "medium", "hard"]))
print(">=2 tables:", share(lambda p: p["shape"]["n_tables"] >= 2), "| subquery:", share(lambda p: p["shape"]["ownership_subquery"]),
      "| archive:", share(lambda p: p["shape"]["archive"]), "| batch:", share(lambda p: p["shape"]["batch"]),
      "| batch of all >10 rows:", share(lambda p: p["shape"]["batch"] and p["shape"]["batch"]["all"] and p["shape"]["batch"]["count"] > 10))
EOF
cd $REPO/taskgen/v2 && $P $S/simulate_plans.py
```
Expected（数字来自原型，同一个 seed 应当一样）：
```
plans 3556
type 1/2/3/5: 50.6 / 13.5 / 5.4 / 30.6
writes 1/2/3/4/5: 32.1 / 47.2 / 12.8 / 5.2 / 2.8 | >=3: 20.8
difficulty e/m/h: 27.9 / 49.6 / 22.6
>=2 tables: 56.8 | subquery: 12.5 | archive: 6.4 | batch: 7.1 | batch of all >10 rows: 1.8
```
和 DySQL 对照：类型目标约 50/13/6/31；写语句数 33/45/13/6/3，≥3 条约 20%；难度目标 25–30/40–50/25–30（hard 比目标低一点，原因见"本计划新定的事"第 5 条）；两张表 56.8%；子查询 11.6%；archive 6.5%。

- [ ] **Step 6: commit**

```bash
cd $REPO
git add taskgen/v2/taskgen_v2/prompt.py taskgen/v2/taskgen_v2/examples.json taskgen/v2/taskgen_v2/generate.py \
        taskgen/v2/scripts/taskgen.py taskgen/v2/tests/test_taskgen_prompt.py taskgen/v2/tests/test_taskgen_generate.py
git diff --cached --name-only
git commit -m "feat(taskgen v2): the generation plan and prompt of design 4.3 and 4.4

The prompt now reads the confirmed profile's description and quirks, the DDL and column notes of the tables in
scope and a key note per table. Plans draw the write count from DySQL's distribution and the shapes (two tables,
subquery, batch, archive) at DySQL's task-level rates, only where the tree allows them; the difficulty follows
from the shape. No outputs and no read-only questions; 40-80 words that open with the speaker's name and ID; the
person is identified by key, or by a column only they have. Hand-written DySQL-style examples, four per type.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
Expected：暂存区只有这 6 个文件。

---

### Task 5: 回答格式与清理：不要 `outputs`、容忍控制字符、空回答可重试；删掉 `describe`

**Files:**
- Modify: `taskgen/v2/taskgen_v2/generate.py`（`parse_answer`、`make_candidate`、新常量 `RETRYABLE`、`_drop_api_failures`、`run` 里认出空回答）
- Modify: `taskgen/v2/taskgen_v2/schema.py`（删 `DESCRIBE_PROMPT`、`describe_db`、`next_ids`；模块说明；`import json` 不再需要）
- Modify: `taskgen/v2/taskgen_v2/profile_draft.py`（起草档案不再读旧描述：去掉 `description` 参数）
- Modify: `taskgen/v2/scripts/taskgen.py`（删 `DESC_PATH`、`cmd_describe`、`describe` 子命令和用法里那一行；`draft_profiles` 不再读描述文件；`--retry-errors` 的过滤改用 `generate.RETRYABLE`）
- Modify: `taskgen/v2/taskgen_v2/io.py`（`DATA` 那行的注释）
- Delete: `taskgen/v2/data/db_descriptions.json`
- Test: `taskgen/v2/tests/test_taskgen_generate.py`、`taskgen/v2/tests/test_taskgen_schema.py`、`taskgen/v2/tests/test_taskgen_profile_draft.py`、`taskgen/v2/tests/test_taskgen_cli.py`

**Interfaces:**
- Consumes: Task 4 的 `generate.run(..., materials=None, retry_errors=False)`。
- Produces:
  - `generate.parse_answer(text) -> {"instruction", "actions"}`：不再带 `outputs`（D7）；JSON 字符串里的原始制表符、换行照收。
  - 候选记录不再有 `"outputs"` 键。`convert.py`、`verify.py`、`metrics.py` 都不读它（已查过）。
  - `generate.RETRYABLE = ("LLMError", "RuntimeError", "ConnectionError", "EmptyAnswer")`：`--retry-errors` 重做这几类。
  - 模型回了空正文（GLM 一次把 16384 个 token 全用在思考上）时，记录 `error = "EmptyAnswer: no answer after <N> completion tokens"`。
  - `profile_draft.messages(db_key, conn, rec, db_path, hints, examples)`、`profile_draft.draft(client, db_key, conn, rec, db_path, hints, examples)`：去掉 `description`。计划 2 起草时把 v1 的描述当参考传进去；那份描述和确认过的档案冲突，以后起草新库也不会有它。

- [ ] **Step 1: 写失败的测试**

`tests/test_taskgen_generate.py`：
- `GOOD` 去掉末尾的 `, "outputs": []`：

```python
GOOD = '<thought>t</thought><answer>{"instruction": "I am a5 b5. Set qty of order 5 to 3.", "actions": [{"sql": "UPDATE orders SET qty = 3 WHERE order_id = 5"}]}</answer>'
```

- `test_parse_answer_variants` 的开头四行换成：

```python
def test_parse_answer_variants():
    base = {"instruction": "x", "actions": [{"sql": "UPDATE a SET b = 1"}]}
    js = json.dumps(base)
    assert generate.parse_answer(f"<answer>{js}</answer>") == base
    assert generate.parse_answer(f'<answer>{json.dumps({**base, "outputs": ["old"]})}</answer>') == base   # D7: no outputs kept
    raw_tab = '<answer>{"instruction": "a\tb", "actions": [{"sql": "UPDATE a SET b = 1"}]}</answer>'   # GLM once wrote one
    assert generate.parse_answer(raw_tab)["instruction"] == "a\tb"
```

（`raw_tab` 里的 `\t` 是 Python 字符串里的真制表符，落进 JSON 字符串就是原始控制字符。）

- 文件末尾加：

```python
def test_an_empty_answer_is_retried(tmp_path):
    class Silent(FakeClient):
        def chat(self, messages, **kw):
            return {"content": "", "usage": {"completion_tokens": 16384}, "model": "fake"}
    out = str(tmp_path / "c.jsonl")
    generate.run(DB, ANCHOR, [TREE], Silent([]), out, random.Random(0))
    r = io.read_jsonl(out)[0]
    assert r["instruction"] is None and r["error"] == "EmptyAnswer: no answer after 16384 completion tokens"
    s = generate.run(DB, ANCHOR, [TREE], FakeClient([GOOD]), out, random.Random(0), retry_errors=True)
    assert s["written"] == 1 and io.read_jsonl(out)[0]["instruction"].startswith("I am a5 b5")
```

- [ ] **Step 2: 跑测试，确认失败**

```bash
cd $REPO/taskgen/v2 && $P -m pytest -q tests/test_taskgen_generate.py 2>&1 | tail -n 4
```
Expected: 2 个失败。`test_parse_answer_variants` 断言失败（解析结果还带着 `'outputs': []`）；`test_an_empty_answer_is_retried` 断言失败（`error` 是 `ParseError: ...`，不是 `EmptyAnswer: ...`）。

- [ ] **Step 3: 实现 generate.py 的改动**

- `parse_answer` 里 `obj = json.loads(cand)` 改成：

```python
            obj = json.loads(cand, strict=False)   # a raw tab or newline inside a string is fine
```

  它的 `return` 改成：

```python
        return {"instruction": ins, "actions": norm}
```

- `make_candidate` 删掉 `"outputs": parsed["outputs"] if parsed else None,` 这一行。
- `_drop_api_failures` 连同它前面换成：

```python
RETRYABLE = ("LLMError", "RuntimeError", "ConnectionError", "EmptyAnswer")


def _drop_api_failures(out_path):
    """Remove records whose model call failed (HTTP/network) or came back without an answer, so they are generated
    again. Parse failures stay: the model answered, and asking again would just resample."""
    rows = io.read_jsonl(out_path)
    keep = [r for r in rows if not (r.get("instruction") is None and (r.get("error") or "").startswith(RETRYABLE))]
```

  （函数余下的部分不变。）
- `run` 里处理结果的地方：

```python
            if isinstance(resp, Exception):
                error, resp = f"{type(resp).__name__}: {resp}", None
            elif not (resp.get("content") or "").strip():   # GLM once spent all 16384 tokens thinking
                error = f"EmptyAnswer: no answer after {(resp.get('usage') or {}).get('completion_tokens')} completion tokens"
            else:
```

- [ ] **Step 4: 跑测试，确认通过**

```bash
cd $REPO/taskgen/v2 && $P -m pytest -q tests/test_taskgen_generate.py 2>&1 | tail -n 1
```
Expected: `10 passed`。

- [ ] **Step 5: 删掉 `describe`、`next_ids` 和旧描述文件**

`describe` 和 `next_ids` 从 Task 4 起已经没人调用（generate 改读档案素材了）。旧描述文件还剩 `profile draft` 一个读者，这一步一起去掉。

- `schema.py`：
  - 删 `DESCRIBE_PROMPT`、`describe_db`、`next_ids` 三段。
  - import 行改成 `import csv, glob, os, re, sqlite3`。
  - 模块说明换成：

```python
"""What the generation prompt says about a database's tables: their DDL and BIRD's per-column notes, and how a new
row gets its key (design §4.3). The description and the data quirks come from the confirmed profile."""
```

- `tests/test_taskgen_schema.py`：删 `class FakeClient`、`test_describe_db_calls_llm_once_and_caches`、`test_next_ids_for_integer_primary_keys`；import 行改成 `import sqlite3`。
- `scripts/taskgen.py`：
  - 删 `DESC_PATH = ...` 一行、`cmd_describe` 整个函数、`p = sub.add_parser("describe"); ...` 一行，以及文件开头用法里的 `$P scripts/taskgen.py describe --db $DB` 一行。
  - `draft_profiles` 删掉 `desc = json.load(open(DESC_PATH, ...)) ...` 那一行，调用改成 `profile_draft.draft(client, k, trees.open_ro(path), rec, path, hints[k], examples)`。
  - `cmd_generate` 里 `--retry-errors` 那段的过滤条件改成：

```python
                  if c.get("instruction") is None and (c.get("error") or "").startswith(generate.RETRYABLE)}
```

- `profile_draft.py`：
  - `USER` 模板开头的 `"""# Database {key}\n{description}\n\n## Hints` 改成 `"""# Database {key}\n\n## Hints`。
  - `messages` 和 `draft` 去掉 `description` 参数；`messages` 里 `USER.format(...)` 去掉 `description=description or "",`；`draft` 里调用改成 `messages(db_key, conn, rec, db_path, hints, examples)`。
- `tests/test_taskgen_profile_draft.py`：
  - `test_messages_carry_examples_hints_and_schema` 的调用去掉 `"A school.",`，断言改成 `assert "# Database test:school\n\n## Hints from the person who will review the profile\nRoots: Student List\n- dept names are codes." in u`。
  - 两处 `profile_draft.draft(..., HINTS, "", profile_draft.load_examples())` 去掉 `"",`。
- `tests/test_taskgen_cli.py`：`test_trees_check_dedup_convert_without_a_model` 里手写的候选去掉 `"outputs": [], `。
- `io.py`：`DATA = ...` 那行行尾的注释 `# db_descriptions.json` 改成 `# db_profiles.json, profile_hints.json`。
- 删数据文件：`git rm taskgen/v2/data/db_descriptions.json`。

- [ ] **Step 6: 跑全套测试，确认没有遗留的引用**

```bash
cd $REPO/taskgen/v2 && $P -m pytest -q 2>&1 | tail -n 1
grep -rn "describe_db\|next_ids\|db_descriptions\|DESC_PATH\|DESCRIBE_PROMPT\|\"outputs\"\|description=description" taskgen_v2 scripts
```
Expected：整套 `145 passed`（加 1 个、删 2 个）；`grep` 没有输出。测试里还会出现 `outputs`，那是"旧回答带 `outputs` 也照收""prompt 里不提 `outputs`"两条断言，不在搜的范围里。

- [ ] **Step 7: commit**

```bash
cd $REPO
git add taskgen/v2/taskgen_v2/generate.py taskgen/v2/taskgen_v2/schema.py taskgen/v2/taskgen_v2/io.py \
        taskgen/v2/taskgen_v2/profile_draft.py taskgen/v2/scripts/taskgen.py taskgen/v2/tests/test_taskgen_generate.py \
        taskgen/v2/tests/test_taskgen_schema.py taskgen/v2/tests/test_taskgen_profile_draft.py taskgen/v2/tests/test_taskgen_cli.py
git diff --cached --name-only
git commit -m "feat(taskgen v2): answers without outputs, tolerant JSON, empty answers retried; drop describe

Candidates no longer carry outputs (design D7). A raw tab or newline inside a JSON string no longer fails the
parse (plan 2's smoke lost one candidate to it). An empty answer -- GLM once spent all 16384 tokens thinking --
is retried by --retry-errors. The describe step and data/db_descriptions.json are gone: the prompt reads the
confirmed profile's description since Task 4, and profile drafting no longer passes the old description along.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
Expected：暂存区是这 9 个文件加上已删除的 `taskgen/v2/data/db_descriptions.json`，共 10 个。

---

### Task 6: 验证与收尾

**Files:**
- Create: `taskgen/v2/docs/2026-10-01-prompt-and-materials.md`（验证记录）
- Modify: `taskgen/v2/docs/2026-10-01-taskgen-v2-design.md`（写回本计划定下的规则）
- Modify: `taskgen/v2/README.md`（改动记录）
- 本地，不进 git：`taskgen/v2/results/plan3/`（树、候选、检查结果）

**Interfaces:**
- Consumes: Task 1–5 的全部改动；23 份已确认的档案。
- Produces: 设计 §5 阶段 D 的完成证据；给阶段 F（校验）用的候选。

- [ ] **Step 1: 建树：beer_factory 100 棵，其余 22 个库各 10 棵**

```bash
cd $REPO/taskgen/v2
$P scripts/taskgen.py trees --db bird:beer_factory --n 100 --seed 0 --out-dir results/plan3/bf/beer_factory
for DB in $($P -c "import json; print(' '.join(k for k in json.load(open('data/db_profiles.json')) if k != 'bird:beer_factory'))"); do
  $P scripts/taskgen.py trees --db $DB --n 10 --seed 0 --out-dir results/plan3/mix/${DB#*:} || echo "FAILED $DB"
done 2>&1 | tee $S/trees.log | grep -c FAILED
```
Expected：beer_factory 打印 `customers: 100 trees written`；循环打印 `0`（没有失败）。`results/plan3/mix/` 下 22 个目录，每个 10 棵树（college_2、school_scheduling 两个根分着建，合计也是 10 棵）。

- [ ] **Step 2: 出题和检查（GLM，约 45–60 分钟）**

```bash
cd $REPO/taskgen/v2
run() { $P scripts/taskgen.py generate --db $1 --workers 5 --out-dir $2 && \
        $P scripts/taskgen.py generate --db $1 --workers 5 --out-dir $2 --retry-errors && \
        $P scripts/taskgen.py check --db $1 --out-dir $2; }
{ run bird:beer_factory results/plan3/bf/beer_factory
  for DB in $($P -c "import json; print(' '.join(k for k in json.load(open('data/db_profiles.json')) if k != 'bird:beer_factory'))"); do
    run $DB results/plan3/mix/${DB#*:}
  done; } > $S/generate.log 2>&1
grep -E "^checked" $S/generate.log | awk '{n += $2; p += $4} END {print n, p}'
```
Expected：`320` 条候选；通过数在 295 以上（试点 260 条过了 248 条，95%）。各库依次跑，并发始终是 5。

- [ ] **Step 3: 统计**

```bash
cat > $S/validate_stats.py <<'EOF'
# per database and in all: candidates, failed calls, check passes, reasons, requested vs computed type, requested
# vs written statement count, prompt tokens; then the type mismatches (ids and labels only). Run from taskgen/v2.
import glob, os, statistics as st, sys
from collections import Counter
sys.path[:0] = [".", "../common"]
from taskgen_v2 import io, metrics


def q(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p * len(xs)))] if xs else 0


print("| 库 | 候选 | 失败调用 | 过检查 | 拒绝原因 | 要求≠算出类型 | 写语句数 要求=实际 | prompt token 均值 / p90 |")
print("|---|---|---|---|---|---|---|---|")
mism, tot = [], Counter()
alltok = []
for root in sys.argv[1:]:
    for f in sorted(glob.glob(os.path.join(root, "*", "candidates.jsonl"))):
        d = os.path.dirname(f)
        cands = io.read_jsonl(f)
        chk = {r["id"]: r for r in io.read_jsonl(f"{d}/check.jsonl")}
        ok = [c for c in cands if chk.get(c["id"], {}).get("ok")]
        reasons = Counter(x.split(":")[0] for r in chk.values() for x in r["reasons"])
        bad = [(c["id"], c["plan"]["task_type"], chk[c["id"]]["task_type"]) for c in ok if c["plan"]["task_type"] != chk[c["id"]]["task_type"]]
        nw = [(c["plan"]["shape"]["n_writes"], metrics.write_count(c)) for c in ok]
        tok = [c["usage"]["prompt_tokens"] for c in cands if (c.get("usage") or {}).get("prompt_tokens")]
        mism += bad; alltok += tok
        tot.update(cands=len(cands), failed=sum(c["instruction"] is None for c in cands), ok=len(ok), bad=len(bad),
                   same=sum(a == b for a, b in nw), nw=len(nw))
        print(f"| {os.path.basename(d)} | {len(cands)} | {sum(c['instruction'] is None for c in cands)} | {len(ok)} | "
              f"{', '.join(f'{k} {v}' for k, v in reasons.most_common()) or '-'} | {len(bad)} / {len(ok)} | "
              f"{sum(a == b for a, b in nw)} / {len(nw)} | " + (f"{st.mean(tok):.0f} / {q(tok, .9)} |" if tok else "- |"))
print(f"| 合计 | {tot['cands']} | {tot['failed']} | {tot['ok']} | | {tot['bad']} / {tot['ok']} | {tot['same']} / {tot['nw']} | "
      f"{st.mean(alltok):.0f} / {q(alltok, .9)} |")
print()
for m in mism:
    print("mismatch:", *m)
EOF
cd $REPO/taskgen/v2
$P $S/validate_stats.py results/plan3/bf results/plan3/mix | tee $S/validate_stats.md
$P scripts/task_stats.py --set beer_factory=results/plan3/bf --set 22-db-sample=results/plan3/mix --out $S/task_stats.md
```
Expected（对照 §3 和"本计划新定的事"第 4、5 条）：
- 失败调用 ≤2%；过检查 ≥92%；要求类型 ≠ 算出类型 ≤3%。
- 词数均值 50–80、p90 <110；前 25 词内有 ID 或邮箱 ≥80%；语句含子查询 <15%；写入表 ≥2 张 ≥50%；写语句数均值 1.9–2.1。
- 只读提问 <5%。注意：`metrics.ASK` 会把 archive 题里 "Before you touch ..., copy ..." 这种说法算成只读提问（试点 3 条全是这种），超出 5% 时逐条看。
- 预计达不到的两项（第 5 条）：22 库样本的 hard 在 22% 左右（beer_factory 单库约 30%），改动 >10 行在 2% 左右。
- beer_factory 单库的第 2 类在 17% 左右（第 4 条：有公共行的库多出第 2 类）。

- [ ] **Step 4: 给每条拒绝和类型不一致归类**

```bash
cat > $S/classify.py <<'EOF'
# every rejected candidate with its reasons, and every requested != computed type with each write's computed label
# next to the labels the prompt showed for rows of that table (ids, tables and labels only, no task text)
import glob, os, sys
from collections import defaultdict
sys.path[:0] = [".", "../common"]
from taskgen_v2 import io


def shown_labels(tree, picked):
    out = defaultdict(set)

    def walk(node):
        out[node["table"]].add(node["label"].split(":")[0])
        for p in node.get("parents", []):
            walk(p)
    for p in tree.get("parents", []):
        walk(p)
    for gi, j in picked:
        walk(tree["events"][gi]["rows"][j])
    out[tree["anchor_table"]].add("own")
    for tb in tree.get("attributes", {}):
        out[tb].add("own")
    return out


for root in sys.argv[1:]:
    for d in sorted(glob.glob(os.path.join(root, "*"))):
        trees = {(t["anchor_table"], str(t["key_value"])): t for t in io.read_jsonl(f"{d}/trees.jsonl")}
        chk = {r["id"]: r for r in io.read_jsonl(f"{d}/check.jsonl")}
        for c in io.read_jsonl(f"{d}/candidates.jsonl"):
            r = chk.get(c["id"])
            if r and not r["ok"]:
                print(f"rejected {c['id']}: {[x[:90] for x in r['reasons'][:3]]}")
            elif r and r["task_type"] != c["plan"]["task_type"]:
                shown = shown_labels(trees[(c["anchor_table"], str(c["key_value"]))], c["plan"]["events"])
                print(f"mismatch {c['id']}: requested {c['plan']['task_type']}, computed {r['task_type']}")
                for w in r["writes"]:
                    print(f"    {w['op']} {w['table']} rows={w['rows']} label={w['label']} shown={sorted(shown.get(w['table'], [])) or '-'}")
EOF
cd $REPO/taskgen/v2 && $P $S/classify.py results/plan3/bf results/plan3/mix | tee $S/classify.txt
```
Expected：
- 拒绝原因大多是模型的错：撞了 UNIQUE（WWE 的名字、school_scheduling 的复合键）、条件写错改了 0 行、字面量没写进 instruction。逐条看，按原因归类。
- 类型不一致分两类：
  - **(a) 标签不一致**：prompt 里标 own/public 的行，写进去算出来不是 own/public。必须是 0，因为两边用同一个 `owners.Tracer`；出现了就是 bug，按 superpowers:systematic-debugging 查清、补测试、修好。
  - **(b) 模型没按类型写**：例如要求第 1 类，却新建了公共行或新登记了人物行。计入比例。

- [ ] **Step 5: 写验证记录 `docs/2026-10-01-prompt-and-materials.md`**

中文，只写计数和候选 id，不摘录题目内容。内容：
1. **这次改了什么**：一段话，引本计划。
2. **检查规则的重新校准**：Task 1 Step 6 的结果（DySQL 895 → 895，v1 3872 → 3872，5 条 cookbook 金标准改为卡在下一个字面量上）。
3. **beer_factory 100 条 vs DySQL**：`$S/task_stats.md` 的表（DySQL、beer_factory 两列），加 `$S/validate_stats.md` 里 beer_factory 那一行。逐项说明是否在 §3 的目标区间里。
4. **其余 22 个库各 10 条**：`$S/validate_stats.md` 的每库表，`$S/task_stats.md` 的 22-db-sample 一列，类型不一致的 (a)/(b) 归类（只列 id），拒绝原因的归类。
5. **和目标的差距**：hard、改动 >10 行（第 5 条的原因，附实测数字）；beer_factory 第 2 类偏多的原因（第 4 条）；只读提问的误报（如有）。
6. **给后续计划的输入**：例如 UNIQUE 撞值集中在哪些库、prompt token 的分布、`metrics.ASK` 对 archive 说法的误报、哪些库的拒绝率偏高。

- [ ] **Step 6: 设计写回**

```bash
cd $REPO/taskgen/v2 && cat > $S/edit_design.py <<'EOF'
# writes plan 3's rules back into the design (run from taskgen/v2)
PATH = "docs/2026-10-01-taskgen-v2-design.md"
EDITS = [
    ("计划 2（阶段 B、C，执行检查读档案）见 `2026-10-01-taskgen-v2-plan-2.md`；出题、校验和运行的计划在前一份完成后再写",
     "计划 2（阶段 B、C，执行检查读档案）见 `2026-10-01-taskgen-v2-plan-2.md`，计划 3（阶段 D 出题，顺带计划 1 留下的检查规则）见 "
     "`2026-10-01-taskgen-v2-plan-3.md`；校验和运行的计划在前一份完成后再写"),
    ("| 每题改动 >10 行 | 6.2% | 0.7% | 3–8% |",
     "| 每题改动 >10 行 | 6.2% | 0.7% | 3–8%（计划 3 达不到：多数树的事件组不到 11 行，实测见 `2026-10-01-prompt-and-materials.md`） |"),
    ("| 25–30 / 40–50 / 25–30，且\"难\"主要来自多语句多表 |",
     "| 25–30 / 40–50 / 25–30，且\"难\"主要来自多语句多表（不出第 4 类时 hard 偏低，计划 3 模拟约 23%，实测见 "
     "`2026-10-01-prompt-and-materials.md`） |"),
    ("- 出题时按难度抽 3–5 / 5–8 / 8–12 条事件，",
     "- 出题时按写语句数抽 3–5 / 5–8 / 8–12 条事件（1 条、2 条、3 条以上），"),
    ("- DDL + BIRD 列说明 + 档案 `description`（取代 `describe`）。",
     "- 档案范围内表的 DDL + BIRD 列说明 + 档案 `description`（取代 `describe`，`data/db_descriptions.json` 已删）；排除的表不进 prompt。"),
    ("- 每表给出 UNIQUE 列、复合键，并把主键分成三类写进 prompt：",
     "- 每表一行键说明（`schema.key_notes`）：列出 UNIQUE 列（和主键相同的不列），并把主键分成下面几类写进 prompt："),
    ("  - **ID 必须由用户给出**（WWE 那 8 张 seq ≠ MAX 的表；hr_1 的 DECIMAL 主键；college_2 这类数字样式的 VARCHAR 主键）：给 MAX+1 作建议值，instruction 里必须出现。",
     "  - **ID 必须由用户给出**（WWE 那 8 张 seq ≠ MAX 的表；hr_1 的 DECIMAL 主键；college_2 这类数字样式的 VARCHAR 主键）：给 MAX+1 作建议值，instruction 里必须出现。\n"
     "  - **自然键**（单列、值不是整数，如州代码、产品线名）：新行写一个还没用过的值。\n"
     "  - **外键作主键**（college_2 的 `advisor.s_ID`、student_loan 的属性表）：新行写它所属那一行的键；只认档案的边和库里声明的外键。\n"
     "  - **复合键**：每个键列都写明，组合不能和已有的重复。"),
    ("v1 是 38/47/14.4/0/0，差距其实不大，主要是补上 4–5 条。",
     "v1 是 38/47/14.4/0/0，差距其实不大，主要是补上 4–5 条。实际权重 37/41/13/6/3（第 2 类至少 2 条）；类型权重 47/17/7/29"
     "（三个库没有公共行），23 个库整体落在 50/13/6/31 附近。比例在计划 2 的树上模拟定下（计划 3）。"),
    ("- 说话人介绍含 ID/邮箱的比例按 §3 的目标（前 25 词内 ≥80%）；`ownership_subquery` 形状 ~10%。",
     "- 说话人第一句给名字和 ID（写出 ID 一词或列名，前 25 词内 ≥80%）；SQL 里按主键找人，名字会重。`ownership_subquery` 形状约 12%，"
     "只在树有 `lookup`（他独有的邮箱、电话一类，或只有他叫这个名字）时抽。"),
    ("- 新增批量形状 ~6%（按条件改删 2–50 行）；新增\"改什么\"：从事件行抽目标列。",
     "- 新增批量形状约 7%：取这个人行数在 2–50 的最大事件组，六成整组全改，其余按条件挑（条件的值照 SQL 写进 instruction）。"
     "archive 形状：把行复制成同表的新行再改原行，只用键可省（或没有主键）的表。两张表的比例按 DySQL 校准（约 57%）。"
     "难度由形状推出，打分和执行检查一样。新增\"改什么\"：从展示行里挑不是主键、不是外键的列。"),
    ("不写进 `examples.json`，因为生成物不进 git。",
     "不写进 `examples.json`，因为生成物不进 git。示例的领域避开这 23 个库和 DySQL 的 13 个库，也不用 DySQL 的金标准（评测集）。"),
    ("- 比例从档案或 `CFG` 读，每库可覆盖写语句数倾向（可选）。",
     "- 比例从 `CFG` 读；每库覆盖写语句数倾向（可选）没做。"),
    ("- 字面量按词边界匹配，序数词 first…twelfth → 数字。",
     "- 字面量按词边界匹配，序数词 first…twelfth → 数字；认复数词尾（cup / cups）和紧跟数字的单位（10g）；"
     "数字回退不认左边粘着字母的数字（`C00003174` 里的 3174）。"),
    ("gold 里有读时钟或随机数的函数（`CURRENT_TIMESTAMP`、`'now'`、`random()` 等）时，间隔 1.1 秒执行两遍，",
     "gold 里有读时钟或随机数的函数（`CURRENT_TIMESTAMP`、`'now'`、`random()`，以及不带时间参数的 `date()`、`datetime()`、"
     "`strftime(格式)` 等）时，把读时钟的地方换成同一天的两个固定时刻（00:00:00、13:37:42）各执行一遍，"),
]
text = open(PATH, encoding="utf-8").read()
for old, new in EDITS:
    assert text.count(old) == 1, (text.count(old), old)
    text = text.replace(old, new)
open(PATH, "w", encoding="utf-8").write(text)
print(f"{len(EDITS)} edits applied")
EOF
$P $S/edit_design.py && git -C $REPO diff --stat -- taskgen/v2/docs/2026-10-01-taskgen-v2-design.md
```
Expected：打印 `14 edits applied`；`diff --stat` 只有设计文档一个文件。

- [ ] **Step 7: 测试、README、commit**

```bash
cd $REPO/taskgen/v2 && $P -m pytest -q 2>&1 | tail -n 1
cd $REPO
printf '%s\n' \
  '| 执行检查：读时钟的 gold 在同一天的两个固定时刻各跑一遍（不再隔 1.1 秒）；不带时间参数的日期函数也算读时钟；字面量认复数词尾和紧跟数字的单位，不认左边粘着字母的数字 | §4.5 |' \
  '| 出题素材：档案的描述和数据怪异点、范围内表的 DDL 和列说明、每表一行键说明（`schema.key_notes`）；树记下能单独认出说话人的列（`lookup`） | §4.3 |' \
  '| 出题计划与 prompt：写语句数和形状（两张表、子查询、批量、archive）按 DySQL 校准，难度由形状推出；不要 `outputs` 和只读提问；40–80 词、名字加 ID 开头；手写 DySQL 式示例；删掉 `describe` 和 `data/db_descriptions.json` | §4.4 |' \
  '| 验证：beer_factory 100 条、其余 22 个库各 10 条，§3 指标对照 DySQL（`docs/2026-10-01-prompt-and-materials.md`）；设计写回计划 3 的规则 | §5 D |' >> taskgen/v2/README.md
git add taskgen/v2/docs/2026-10-01-prompt-and-materials.md taskgen/v2/docs/2026-10-01-taskgen-v2-design.md taskgen/v2/README.md
git diff --cached --name-only
git commit -m "docs(taskgen v2): plan 3 validation and design write-back

beer_factory 100 candidates and 10 from each of the other 22 databases, compared with DySQL on the design 3
metrics; every rejection and type mismatch classified. The design takes over this plan's rules: profile
materials, key notes, the calibrated plan mix, the clock and literal rules.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
Expected：测试 `145 passed`；暂存区只有这 3 个文件。

- [ ] **Step 8: memory**

- `research-plan-grpo-text2sql.md`：在计划 2 那段后面加一句：计划 3 完成，写上日期、commit 范围、beer_factory 和 22 库样本的关键指标（过检查率、类型不一致率、词数、前 25 词有 ID 的比例），下一步是计划 4（阶段 F 校验）。
- `taskgen-v2-plan2-followups.md`：标出计划 3 已做的条目（prompt 告诉模型不出 INSERT 的表、archive 和第 1 类冲突、说话人按主键找、M1 hr_1 的表数、改用档案描述）；剩下的写明归哪个计划。
- `taskgen-v2-plan1-followups.md`：时钟规则和字面量规则已在计划 3 修掉；剩下 `task_stats` 的缓存问题归计划 5。
