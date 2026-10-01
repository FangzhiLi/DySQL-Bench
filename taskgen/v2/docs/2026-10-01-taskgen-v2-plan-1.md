# 训练任务生成 v2：实施计划 1（骨架、任务集统计、执行检查）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立 `taskgen/v2/`（v1 的纯复制），加一个和 DySQL 并排比较的任务集统计工具，并按设计 §4.5 修好执行检查里不依赖库档案的四处，最后证明每一处判决变化都来自这些改动。

**Architecture:** v2 是 v1 的目录级复制，包名 `taskgen_v2`，v1（tag `taskgen-v1`）一行不动。顺序是：复制改名（设计阶段 A）→ 统计工具（阶段 G）→ 执行检查四处改动（阶段 E）→ 用 v1 冻结的检查和 v2 的检查在同一批候选上逐条对比。依赖库档案的检查改动（范围、归属、`same_as`、`no_insert`）放到计划 2。

**Tech Stack:** Python 3.11（conda env `dysql`），标准库 `sqlite3`、`re`、`json`；已装的 `sqlparse`、`pytest`；`dysql_bench`（已 editable 安装在 `dysql` 环境里，只用来读 DySQL 的金标准任务和评测的 volatile 列正则）。不加新依赖。

**Spec:** [2026-10-01-taskgen-v2-design.md](2026-10-01-taskgen-v2-design.md)。阈值、规则以它为准；本计划改动的地方会同步改它。

## Global Constraints

- 分支 `isa/data-gen`。每个 Task 单独 commit，commit message 以 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` 结尾。不要 push（用户自己 push）。
- `taskgen/v1/` 冻结：本计划不改其中任何文件，只读。
- 生成的任务不进 git：`taskgen/*/results/`、`taskgen/*/output/` 已在 `.gitignore`。每次 commit 前跑 `git diff --cached --name-only`，不能出现 `results/` 或 `output/`。文档里可以写候选 id 和计数，不摘录题目内容。
- 秘密只在仓库根目录 `.env`；不打印 key；测试不联网。
- 命令约定：`REPO=/home/wmd3i/Documents/Isa/DySQL-Bench`，`P=~/miniconda3/envs/dysql/bin/python`，临时文件放 `S=/tmp/claude-1000/-home-wmd3i-Documents-Isa-DySQL-Bench/3cc9a46f-e1e3-4468-b1b8-b1054479803f/scratchpad/v2-plan1`（`mkdir -p $S`）。
- 测试按目录跑：`cd $REPO/taskgen/v2 && $P -m pytest -q`。不要在一个 pytest 进程里同时跑 v1 和 v2 的测试（文件同名）。
- SQL 里的表名、列名用 `taskgen_common.db_select._q()` 加引号：真实库里有 `Sales Orders`、`historical-terms`。
- 评测哈希的口径（`DySQL-Bench/dysql_bench/envs/base.py`）：跳过 `sqlite_sequence`、`sqlite_stat1` 两张表，跳过名字匹配 `VOLATILE_COL_RE` 的列（`last_update`、`updated_at`、`created_at`、`timestamp` 等）。
- 文档用中文。

## Review Focus

1. **要加引号的表名**（`Sales Orders`、`historical-terms`）进入新写的主键分类和非确定性快照：应正常工作，不报 SQLite 错误。→ Task 4、Task 5 的测试。
2. **SQL 里的表名大小写和库里不一致**（`INSERT INTO "ORDERS"`）：自动分配主键的判断要照样生效。→ Task 4 的测试。
3. **紧挨标点或所有格的字面量**（`O'Brien's`、`C00003174,`、`'$5 million'`）：改成整词匹配后仍要能匹配上。→ Task 3 的测试。
4. **读时钟的 gold 里另有一条语句报错**：不重跑、不崩溃，只报 `sql_error`。→ Task 5 的测试。
5. **空的任务集、没有标签的任务、不存在的结果目录**：统计工具不崩溃；目录不存在时明确报错，而不是给出一列空值。→ Task 2 的测试。

---

### Task 1: 从 v1 复制出 v2，只改名

**Files:**
- Create: `taskgen/v2/taskgen_v2/`（复制自 `taskgen/v1/taskgen_v1/`）、`taskgen/v2/scripts/`、`taskgen/v2/tests/`、`taskgen/v2/data/`、`taskgen/v2/conftest.py`、`taskgen/v2/pytest.ini`（都复制自 v1）
- Create: `taskgen/v2/README.md`
- Modify: `taskgen/README.md`（目录结构、测试命令、v2 链接）

**Interfaces:**
- Consumes: v1 的全部代码（tag `taskgen-v1`）。
- Produces: 包 `taskgen_v2`，模块和函数与 `taskgen_v1` 完全相同；`taskgen_v2.io.RESULTS`、`OUTPUT`、`DATA` 指向 `taskgen/v2/` 下。

- [ ] **Step 1: 复制**

```bash
cd $REPO/taskgen
mkdir -p v2
cp -r v1/taskgen_v1 v2/taskgen_v2
cp -r v1/scripts v1/tests v1/data v1/conftest.py v1/pytest.ini v2/
find v2 -name __pycache__ -type d -prune -exec rm -rf {} +
ls v2
```
Expected: `conftest.py  data  docs  pytest.ini  scripts  taskgen_v2  tests`（`docs/` 是已提交的设计和本计划）。

- [ ] **Step 2: 改名**

```bash
cd $REPO/taskgen/v2
grep -rl taskgen_v1 --include=*.py --include=*.sh . | xargs -r sed -i 's/taskgen_v1/taskgen_v2/g'
sed -i 's/\bV1\b/V2/g' taskgen_v2/io.py scripts/taskgen.py scripts/calibrate_check.py
grep -rl 'taskgen/v1' --include=*.py --include=*.sh . | xargs -r sed -i 's#taskgen/v1#taskgen/v2#g'
grep -rn 'taskgen_v1\|taskgen/v1\|\bV1\b' --include=*.py --include=*.sh . ; echo "leftovers_exit=$?"
```
Expected: 最后一条 grep 没有输出，`leftovers_exit=1`。

- [ ] **Step 3: 写 `taskgen/v2/README.md`**

```markdown
# 训练任务生成 v2（进行中）

v2 从 v1 原样复制起步（tag `taskgen-v1`，61c8133）。复制的那个 commit 只改了包名（`taskgen_v1` → `taskgen_v2`）和路径（`taskgen/v1/` → `taskgen/v2/`），逻辑没动。之后每处改动单独提交，并在下面的改动记录里记一行。

- **设计：** [docs/2026-10-01-taskgen-v2-design.md](docs/2026-10-01-taskgen-v2-design.md)
- **实施计划 1（骨架、任务集统计、执行检查）：** [docs/2026-10-01-taskgen-v2-plan-1.md](docs/2026-10-01-taskgen-v2-plan-1.md)
- **怎么跑：** 和 v1 相同（[../v1/README.md](../v1/README.md) §3），命令在 `taskgen/v2/` 下运行。中间文件写到 `taskgen/v2/results/`，最终任务写到 `taskgen/v2/output/`，都不进 git。
- **测试：** `cd taskgen/v2 && ~/miniconda3/envs/dysql/bin/python -m pytest -q`

## 改动记录

| 改动 | 设计条目 |
|---|---|
| 从 v1 复制，只改名 | §4.0 |
```

- [ ] **Step 4: 改 `taskgen/README.md`**

三处替换（每处先给原文，再给新文本）：

1. 原文：
```markdown
- **v1（通用规则版）的全流程：** 见 [v1/README.md](v1/README.md)。
```
新文本：
```markdown
- **v1（通用规则版）的全流程：** 见 [v1/README.md](v1/README.md)。
- **v2（论文做法 + v1 的规则，进行中）：** 见 [v2/README.md](v2/README.md)。
```
2. 原文（目录图里的一行）：
```
  v2/                 之后从 v1 复制起步
```
新文本：
```
  v2/                 从 v1 复制起步，进行中
    README.md         起点说明和改动记录
    taskgen_v2/  scripts/  tests/  docs/  data/
    results/  output/ （不进 git）
```
3. 原文：
```markdown
- **测试按目录跑：** `cd taskgen/common && pytest`，`cd taskgen/v1 && pytest`。
```
新文本：
```markdown
- **测试按目录跑：** `cd taskgen/common && pytest`，`cd taskgen/v1 && pytest`，`cd taskgen/v2 && pytest`。
```

- [ ] **Step 5: 验证"只改了名"**

```bash
mkdir -p $S && cd $REPO/taskgen
diff -r -x __pycache__ v1/taskgen_v1 v2/taskgen_v2 > $S/pkg.diff
for d in scripts tests data; do diff -r -x __pycache__ v1/$d v2/$d; done > $S/rest.diff
diff v1/conftest.py v2/conftest.py >> $S/rest.diff; diff v1/pytest.ini v2/pytest.ini >> $S/rest.diff
cat $S/pkg.diff $S/rest.diff | grep -E '^Only in'; echo "only_in_exit=$?"
cat $S/pkg.diff $S/rest.diff | grep '^[<>]' | grep -vE 'taskgen_v[12]|\bV[12]\b|taskgen/v[12]'; echo "other_changes_exit=$?"
```
Expected: `only_in_exit=1`、`other_changes_exit=1`（两条 grep 都没有输出）。

- [ ] **Step 6: 四套测试**

```bash
cd $REPO/taskgen/v2 && $P -m pytest -q 2>&1 | tail -1
cd $REPO/taskgen/v1 && $P -m pytest -q 2>&1 | tail -1
cd $REPO/taskgen/common && $P -m pytest -q 2>&1 | tail -1
cd $REPO/DySQL-Bench && $P -m pytest -q 2>&1 | tail -1
```
Expected: `71 passed`、`71 passed`、`65 passed`、`33 passed`。

- [ ] **Step 7: 同一个 seed 下 v1 和 v2 的树和 prompt 逐字节相同，且 v2 不写 v1 的目录**

```bash
cd $REPO/taskgen && rm -rf $S/eq && mkdir -p $S/eq && touch $S/eq/start
$P v1/scripts/taskgen.py trees --db bird:beer_factory --n 20 --seed 0 --out-dir $S/eq/v1
$P v2/scripts/taskgen.py trees --db bird:beer_factory --n 20 --seed 0 --out-dir $S/eq/v2
cmp $S/eq/v1/trees.jsonl $S/eq/v2/trees.jsonl && cmp $S/eq/v1/others.json $S/eq/v2/others.json && echo TREES_SAME
cat > $S/eq/prompts.py <<'EOF'
import json, os, random, sys
T = "/home/wmd3i/Documents/Isa/DySQL-Bench/taskgen"
sys.path[:0] = [f"{T}/v1", f"{T}/v2", f"{T}/common"]
from taskgen_v1 import generate as g1, io as io1, schema as s1
from taskgen_v2 import generate as g2, io as io2, schema as s2


class Recorder:
    """Stands in for the model: keeps every prompt, answers nothing (the candidates become parse errors)."""
    def __init__(self):
        self.msgs = []

    def chat(self, msgs, **kw):
        self.msgs.append(msgs)
        return {"content": "", "usage": {}, "model": "fake"}


def prompts(g, io, schema, d):
    rec = io.load_db_recs()["bird:beer_factory"]
    path = io.resolve_db_path(rec["path"])
    desc = json.load(open(os.path.join(io.DATA, "db_descriptions.json")))["bird:beer_factory"]
    trees, others = io.read_jsonl(f"{d}/trees.jsonl"), json.load(open(f"{d}/others.json"))
    client = Recorder()
    for anchor in io.person_anchors(rec):
        g.run(rec, anchor, [t for t in trees if t["anchor_table"] == anchor["table"]], others.get(anchor["table"], []),
              client, f"{d}/candidates.jsonl", random.Random(f"0:{anchor['table']}"), workers=1,
              db_description=desc, schema_text=schema.schema_block(path), next_ids=schema.next_ids(path))
    return client.msgs


a = prompts(g1, io1, s1, f"{sys.argv[1]}/v1")
b = prompts(g2, io2, s2, f"{sys.argv[1]}/v2")
print(len(a), "prompts;", "PROMPTS_SAME" if json.dumps(a) == json.dumps(b) else "PROMPTS_DIFFER")
EOF
$P $S/eq/prompts.py $S/eq
$P -c "import sys; sys.path[:0] = ['v2', 'common']; from taskgen_v2 import io; print(io.RESULTS); print(io.OUTPUT); print(io.DATA)"
find v1/results v1/output -newer $S/eq/start | head -3; echo "v1_untouched_exit=$?"
```
Expected：`TREES_SAME`；`20 prompts; PROMPTS_SAME`；三行路径都以 `/home/wmd3i/Documents/Isa/DySQL-Bench/taskgen/v2/` 开头；`find` 没有输出。

- [ ] **Step 8: Commit**

```bash
cd $REPO
git add taskgen/v2 taskgen/README.md
git diff --cached --name-only | grep -E 'results/|output/'; echo "no_data_exit=$?"
git commit -q -F - <<'EOF'
chore(taskgen): start v2 as a copy of v1 (tag taskgen-v1), renames only

taskgen/v2/ is taskgen/v1/ with the package renamed to taskgen_v2 and paths to taskgen/v2/; no logic changes.
Checked: diff -r shows only rename lines, all four test suites pass, and with seed 0 the trees and generation
prompts for beer_factory are byte-identical to v1's. Later v2 changes are measured against this commit.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
git log --oneline -1
```
Expected: `no_data_exit=1`；commit 成功。

---

### Task 2: 任务集统计工具（和 DySQL 并排）

**Files:**
- Create: `taskgen/v2/taskgen_v2/dysql.py`（从 `scripts/calibrate_check.py` 挪出 DySQL 金标准的读取）
- Create: `taskgen/v2/taskgen_v2/metrics.py`
- Create: `taskgen/v2/scripts/task_stats.py`
- Create: `taskgen/v2/tests/test_taskgen_metrics.py`
- Modify: `taskgen/v2/scripts/calibrate_check.py`（改用 `taskgen_v2.dysql`）
- Modify: `taskgen/v2/tests/test_taskgen_check_dysql.py`（改用 `taskgen_v2.dysql`）
- Modify: `taskgen/v2/docs/2026-10-01-taskgen-v2-design.md`（§3 两行、§5 G 行）、`taskgen/v2/README.md`（改动记录）

**Interfaces:**
- Consumes: `taskgen_v2.check.split_statements(sql) -> list[str]`、`check.write_target(stmt) -> (op, table) | None`、`check.run_check_safe(db_rec, cand) -> dict`；`taskgen_v2.io.read_jsonl`、`append_jsonl`、`RESULTS`。
- Produces:
  - `dysql.ENVS: list[str]`；`dysql.db_rec(env) -> dict`（check 用的库记录）；`dysql.candidates(env) -> list[dict]`（键：`id`、`anchor_table`、`key_value`、`group`、`speaker_ids`、`speaker_in_db`、`instruction`、`actions`）。
  - 任务记录 `rec = {"db", "instruction", "actions": [{"sql"}], "type", "difficulty", "writes", "template"}`。
  - `metrics.write_count(rec) -> int`；`metrics.compute(recs) -> dict[str, str]`（有序，指标名 → 格式化后的值）；`metrics.render(cols: dict[str, dict]) -> str`（markdown 表）；`metrics.from_results(results_dir) -> list[rec]`；`metrics.from_dysql(cache_path, envs=None) -> list[rec]`。
  - 脚本 `scripts/task_stats.py [--set NAME=RESULTS_DIR]... [--no-dysql] [--refresh-dysql] [--out FILE]`。

- [ ] **Step 1: 写失败的测试 `tests/test_taskgen_metrics.py`**

```python
# tests/test_taskgen_metrics.py
import os, subprocess, sys
import pytest
from taskgen_v2 import io, metrics

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "task_stats.py")


def rec(instruction, sqls, type_="1_self", level="easy", writes=(("orders", 1),), template="1_self|UPDATE orders"):
    return {"db": "shop", "instruction": instruction, "actions": [{"sql": s} for s in sqls], "type": type_,
            "difficulty": {"level": level}, "template": template,
            "writes": [{"op": "UPDATE", "table": t, "rows": n, "label": "own"} for t, n in writes]}


def results_dir(tmp_path):
    d = tmp_path / "res" / "shop"
    d.mkdir(parents=True)
    io.append_jsonl(str(d / "candidates.jsonl"), [
        {"id": "a", "instruction": "x", "actions": [{"sql": "UPDATE t SET v = 1"}]},
        {"id": "b", "instruction": "y", "actions": [{"sql": "UPDATE t SET v = 2"}]},
        {"id": "c", "instruction": None, "actions": None}])
    io.append_jsonl(str(d / "check.jsonl"), [
        {"id": "a", "ok": True, "reasons": [], "writes": [{"op": "UPDATE", "table": "t", "rows": 1, "label": "own"}],
         "task_type": "1_self", "template": "1_self|UPDATE t", "difficulty": {"level": "easy"}},
        {"id": "b", "ok": False, "reasons": ["noop_write: UPDATE t"], "writes": [], "task_type": None, "template": None, "difficulty": None},
        {"id": "c", "ok": False, "reasons": ["no_instruction"], "writes": [], "task_type": None, "template": None, "difficulty": None}])
    return tmp_path / "res"


def test_write_statements_are_counted_per_statement_not_per_action():
    r = rec("x", ["SELECT 1", "UPDATE a SET b = 1; DELETE FROM a WHERE b = 2", "INSERT INTO a VALUES (1)"])
    assert metrics.write_count(r) == 3


def test_compute_on_a_small_set():
    recs = [rec("Hi, I'm Ann (CustomerID 5). Before you change anything, tell me what my balance is.", ["UPDATE a SET b = 1"]),
            rec("I am Bo, bo@x.com. Set my qty to 3.", ["UPDATE a SET b = 1", "UPDATE c SET d = (SELECT 1)", "DELETE FROM a WHERE b = 1"],
                type_="2_self_and_public", level="hard", writes=(("a", 12), ("c", 1)), template="t2"),
            rec("Change my order please, it was paid.", ["UPDATE a SET b = 1", "UPDATE a SET b = 2"], type_="5_proxy", level="medium")]
    m = metrics.compute(recs)
    assert m["tasks"] == "3"
    assert m["write statements 0/1/2/3/4/≥5"] == "0.0% / 33.3% / 33.3% / 33.3% / 0.0% / 0.0%"
    assert m["write statements mean / median"] == "2.00 / 2"
    assert m["≥3 write statements"] == "33.3%"
    assert m["statements with a subquery"] == "16.7%"
    assert m["read-only ask"] == "33.3%"
    assert m["ID/email in first 25 words"] == "66.7%"            # 'CustomerID' and an email; 'paid' is not an ID
    assert m["type 1/2/3/4/5/other"] == "33.3% / 33.3% / 0.0% / 0.0% / 33.3% / 0.0%"
    assert m["difficulty easy/medium/hard"] == "33.3% / 33.3% / 33.3%"
    assert m["≥2 tables written"] == "33.3%" and m[">10 rows changed"] == "33.3%"
    assert m["templates / largest share"] == "2 / 66.7%"


def test_empty_sets_unlabelled_tasks_and_missing_folders():
    assert metrics.compute([]) == {"tasks": "0"}
    m = metrics.compute([{**rec("x", ["UPDATE a SET b = 1"]), "writes": None}])     # nothing labelled by the check
    assert m["type 1/2/3/4/5/other"] == "- / - / - / - / - / -" and m["templates / largest share"] == "0 / -"
    with pytest.raises(FileNotFoundError):
        metrics.from_results("/nonexistent/results")


def test_from_results_keeps_checked_candidates_only(tmp_path):
    recs = metrics.from_results(str(results_dir(tmp_path)))
    assert [r["instruction"] for r in recs] == ["x"] and recs[0]["db"] == "shop" and recs[0]["type"] == "1_self"


def test_from_dysql_labels_with_the_check_and_types_with_the_classifier(tmp_path):
    cache = str(tmp_path / "dysql.jsonl")
    recs = metrics.from_dysql(cache, envs=("music",))
    assert len(recs) == 21 and {r["db"] for r in recs} == {"music"}
    assert {r["type"] for r in recs} <= {"1_self", "2_self_and_public", "3_public_only", "4_other_person", "5_proxy",
                                          "6_entity", "7_no_change"}
    assert sum(bool(r["writes"]) for r in recs) >= 18
    assert metrics.from_dysql(cache, envs=("music",)) == recs      # the second call reads the cache


def test_render_puts_sets_side_by_side():
    text = metrics.render({"DySQL": metrics.compute([rec("x", ["UPDATE a SET b = 1"])]), "v2": {"tasks": "0"}})
    lines = text.splitlines()
    assert lines[:2] == ["| metric | DySQL | v2 |", "|---|---|---|"]
    assert "| tasks | 1 | 0 |" in lines and "| read-only ask | 0.0% |  |" in lines


def test_task_stats_cli(tmp_path):
    out = subprocess.run([sys.executable, SCRIPT, "--no-dysql", "--set", f"x={results_dir(tmp_path)}"],
                         check=True, capture_output=True, text=True).stdout
    assert out.splitlines()[0] == "| metric | x |" and "| tasks | 1 |" in out
```

- [ ] **Step 2: 跑测试，确认失败**

Run: `cd $REPO/taskgen/v2 && $P -m pytest -q tests/test_taskgen_metrics.py`
Expected: FAIL，`ImportError: cannot import name 'metrics' from 'taskgen_v2'`。

- [ ] **Step 3: 新建 `taskgen_v2/dysql.py`（代码从 `scripts/calibrate_check.py` 原样挪过来，函数改名）**

```python
# taskgen/v2/taskgen_v2/dysql.py
"""DySQL-Bench's own 13 databases and 1062 gold tasks, shaped like generated candidates. The check's calibration
(scripts/calibrate_check.py) and the DySQL column of the task-set metrics (metrics.py) both read them from here."""
import csv, glob, importlib, os
from taskgen_common.db_select import profile_db, all_fks, row_key
from taskgen_common.db_anchor import update_targets, anchors
from taskgen_common.paths import DATA, DYSQL_ENVS

TYPES_CSV = os.path.join(DATA, "dysql_task_types.csv")
ENVS = sorted(os.path.basename(os.path.dirname(os.path.dirname(f))) for f in glob.glob(f"{DYSQL_ENVS}/*/data/*.sqlite"))


def db_rec(env):
    path = glob.glob(f"{DYSQL_ENVS}/{env}/data/*.sqlite")[0]
    p = profile_db(path)
    fks = [f for f in all_fks(p) if f["hit"] is None or f["hit"] >= 0.3]
    keys = {t["name"]: row_key(t) for t in p["tables"] if row_key(t)}
    anc = anchors(p, fks, keys, update_targets(p, keys, 200), 5)
    return {"source": "dysql", "db": env, "path": path, "anchors": anc,
            "fks": [{"table": f["table"], "col": f["cols"][0], "ref_table": f["ref_table"], "ref_col": f["ref_cols"][0],
                     "hit": f["hit"], "source": f["source"]} for f in fks if len(f["cols"]) == 1 and f["ref_cols"][0]]}


def _rows(env):
    with open(TYPES_CSV, encoding="utf-8") as f:
        return {int(r["idx"]): r for r in csv.DictReader(f) if r["env"] == env}


def candidates(env):
    tasks = importlib.import_module(f"dysql_bench.envs.{env}.tasks_test").TASKS_TEST
    rec = db_rec(env)
    meta = _rows(env)
    out = []
    for i, t in enumerate(tasks):
        m = meta[i]
        ids = [x.split(":", 1) for x in m["speaker_ids"].split(";") if ":" in x]
        anchor_table, kv = None, None
        if m["speaker"] == "db_person" and ids:
            anchor_table, kv = ids[0]
            kv = int(kv) if kv.lstrip("-").isdigit() else kv
        if anchor_table is None or not any(a["table"] == anchor_table for a in rec["anchors"]):
            written = {w.split(" ", 1)[1].split(":")[0] for w in m["writes"].split(" | ") if " " in w}
            a = next((a for a in rec["anchors"] if written <= {a["table"], *a["down"], *a["up"]}), rec["anchors"][0])
            anchor_table, kv = a["table"], None
        out.append({"id": f"dysql:{env}:{i}", "anchor_table": anchor_table, "key_value": kv, "group": m["group"],
                    "speaker_ids": [[t, k] for t, k in ids] if m["speaker"] == "db_person" else None,
                    "speaker_in_db": m["speaker"] == "db_person", "instruction": t.instruction,
                    "actions": [{"sql": a.kwargs["sql"]} for a in t.actions if a.name == "sql"]})
    return out
```

- [ ] **Step 4: `scripts/calibrate_check.py` 改用 `taskgen_v2.dysql`**

把文件开头到 `dysql_candidates` 函数结束（`def main():` 之前）整段换成：

```python
#!/usr/bin/env python3
"""Run taskgen.check on DySQL-Bench's 1062 gold tasks and report the pass rate outside class 7 (spec §7: >= 90%).
Usage (from taskgen/v2/):
  ~/miniconda3/envs/dysql/bin/python scripts/calibrate_check.py --out docs/<date>-check-calibration.md"""
import argparse, os, sys
from collections import Counter
V2 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [V2, os.path.join(os.path.dirname(V2), "common")]   # taskgen_v2, taskgen_common
from taskgen_v2 import check
from taskgen_v2.dysql import ENVS, db_rec as dysql_db_rec, candidates as dysql_candidates


```

`main()` 和 `if __name__ == "__main__":` 不动。

- [ ] **Step 5: `tests/test_taskgen_check_dysql.py` 改用 `taskgen_v2.dysql`**

整个文件换成：

```python
# tests/test_taskgen_check_dysql.py
"""Calibration of check.py on DySQL's own gold tasks (spec §7): outside the known no-op class, >= 90% must pass.
The full 13-env report is scripts/calibrate_check.py; this test runs two small envs so it stays fast."""
from collections import Counter
from taskgen_v2 import check, dysql


def test_chinook_and_music_gold_tasks_mostly_pass():
    total, ok, reasons = 0, 0, Counter()
    for env in ("chinook", "music"):
        rec = dysql.db_rec(env)
        for cand in dysql.candidates(env):
            if cand["group"] == "7_no_change":
                continue
            r = check.run_check(rec, cand)
            total += 1; ok += r["ok"]
            for x in r["reasons"]:
                reasons[x.split(":")[0]] += 1
    assert total >= 60 and ok / total >= 0.85, (ok, total, reasons.most_common())
```

- [ ] **Step 6: 新建 `taskgen_v2/metrics.py`**

```python
# taskgen/v2/taskgen_v2/metrics.py
"""Task-set metrics for comparing a generated set with DySQL-Bench (design §3). A record is
{"db", "instruction", "actions": [{"sql"}], "type", "difficulty", "writes", "template"}; the last four come from the
execution check (writes is empty or None when the check produced no write). from_results reads a results folder
(<db>/candidates.jsonl + <db>/check.jsonl), from_dysql DySQL's own gold tasks."""
import glob, os, re, statistics as st
from collections import Counter
from taskgen_v2 import check, dysql, io

# "before you change anything, tell me what ... currently ..." -- a read-only request the reward never checks
ASK = re.compile(r"before (you|we|any|making|touching|applying)|can you (tell|confirm|let me know|report)|"
                 r"(tell|let) me (what|which|the)|what .{0,40}(currently|on file|right now)|report back|confirm (the|what|which)", re.I)
# an identifier the speaker hands over: 'id 129924', 'player_api_id', 'CustomerID', 'my email', '@', 'SSN', '#575041'
ID_RE = re.compile(r"(?i:\bids?\b|_id\b|\bssn\b|\be-?mail\b|@|#\s?\d)|[a-z]I[Dd]\b")
SUBQ = re.compile(r"\(\s*select\b", re.I)
TYPES = ("1_self", "2_self_and_public", "3_public_only", "4_other_person", "5_proxy")


def statements(rec):
    return [s for a in rec["actions"] for s in check.split_statements(a["sql"])]


def write_count(rec):
    return sum(1 for s in statements(rec) if check.write_target(s))


def _pct(n, d):
    return f"{100 * n / d:.1f}%" if d else "-"


def _q(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p * len(xs)))]


def compute(recs):
    if not recs:
        return {"tasks": "0"}
    m, n = {}, len(recs)
    m["tasks"] = str(n)
    wc = [write_count(r) for r in recs]
    c = Counter(min(x, 5) for x in wc)
    m["write statements 0/1/2/3/4/≥5"] = " / ".join(_pct(c[i], n) for i in range(6))
    m["write statements mean / median"] = f"{st.mean(wc):.2f} / {st.median(wc):g}"
    m["≥3 write statements"] = _pct(sum(x >= 3 for x in wc), n)
    stm = [s for r in recs for s in statements(r)]
    m["statements with a subquery"] = _pct(sum(bool(SUBQ.search(s)) for s in stm), len(stm))
    w = [len(r["instruction"].split()) for r in recs]
    m["instruction words mean / median / p90"] = f"{st.mean(w):.0f} / {st.median(w):g} / {_q(w, .9)}"
    m["read-only ask"] = _pct(sum(bool(ASK.search(r["instruction"])) for r in recs), n)
    m["ID/email in first 25 words"] = _pct(sum(bool(ID_RE.search(" ".join(r["instruction"].split()[:25]))) for r in recs), n)
    lab = [r for r in recs if r.get("writes")]
    k = len(lab)
    ty = Counter(r["type"] for r in lab)
    m["type 1/2/3/4/5/other"] = " / ".join(_pct(ty[t], k) for t in TYPES) + " / " + _pct(k - sum(ty[t] for t in TYPES), k)
    lv = Counter(r["difficulty"]["level"] for r in lab if r.get("difficulty"))
    m["difficulty easy/medium/hard"] = " / ".join(_pct(lv[x], k) for x in ("easy", "medium", "hard"))
    m["≥2 tables written"] = _pct(sum(len({x["table"] for x in r["writes"]}) >= 2 for r in lab), k)
    m[">10 rows changed"] = _pct(sum(sum(x["rows"] for x in r["writes"]) > 10 for r in lab), k)
    tpl = Counter(r["template"] for r in lab if r.get("template"))
    m["templates / largest share"] = f"{len(tpl)} / {_pct(tpl.most_common(1)[0][1], k)}" if tpl else "0 / -"
    return m


def render(cols):
    names = list(cols)
    keys = list(dict.fromkeys(k for c in cols.values() for k in c))
    out = ["| metric | " + " | ".join(names) + " |", "|" + "---|" * (len(names) + 1)]
    out += [f"| {k} | " + " | ".join(cols[c].get(k, "") for c in names) + " |" for k in keys]
    return "\n".join(out)


def from_results(results_dir):
    """Check-passed candidates of every database folder under results_dir."""
    if not os.path.isdir(results_dir):
        raise FileNotFoundError(results_dir)
    recs = []
    for f in sorted(glob.glob(os.path.join(results_dir, "*", "check.jsonl"))):
        d = os.path.dirname(f)
        chk = {r["id"]: r for r in io.read_jsonl(f)}
        for c in io.read_jsonl(os.path.join(d, "candidates.jsonl")):
            r = chk.get(c["id"])
            if r and r["ok"] and c.get("instruction"):
                recs.append({"db": os.path.basename(d), "instruction": c["instruction"], "actions": c["actions"],
                             "type": r["task_type"], "difficulty": r["difficulty"], "writes": r["writes"], "template": r["template"]})
    return recs


def from_dysql(cache_path, envs=None):
    """All DySQL gold tasks, labelled by this version's check. The type comes from the DySQL classifier
    (taskgen/common/data/dysql_task_types.csv): its own/other tracing is the reference (design D6). Cached: delete
    the cache after the check changes."""
    if os.path.exists(cache_path):
        return io.read_jsonl(cache_path)
    recs = []
    for env in envs or dysql.ENVS:
        rec = dysql.db_rec(env)
        for c in dysql.candidates(env):
            r = check.run_check_safe(rec, c)
            recs.append({"db": env, "instruction": c["instruction"], "actions": c["actions"], "type": c["group"],
                         "difficulty": r["difficulty"], "writes": r["writes"], "template": r["template"]})
    io.append_jsonl(cache_path, recs)
    return recs
```

- [ ] **Step 7: 新建 `scripts/task_stats.py`**

```python
#!/usr/bin/env python3
"""Compare task sets with DySQL-Bench on the design §3 metrics; one column per set.
Usage (from taskgen/v2/):
  P=~/miniconda3/envs/dysql/bin/python
  $P scripts/task_stats.py --set v1=../v1/results --set v2=results [--refresh-dysql] [--out FILE]
The DySQL column is cached in results/dysql_metrics.jsonl; pass --refresh-dysql after changing the check."""
import argparse, os, sys
V2 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [V2, os.path.join(os.path.dirname(V2), "common")]   # taskgen_v2, taskgen_common
from taskgen_v2 import io, metrics


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--set", action="append", default=[], metavar="NAME=RESULTS_DIR")
    ap.add_argument("--no-dysql", action="store_true")
    ap.add_argument("--refresh-dysql", action="store_true")
    ap.add_argument("--out")
    a = ap.parse_args()
    cols = {}
    if not a.no_dysql:
        cache = os.path.join(io.RESULTS, "dysql_metrics.jsonl")
        if a.refresh_dysql and os.path.exists(cache):
            os.remove(cache)
        cols["DySQL"] = metrics.compute(metrics.from_dysql(cache))
    for s in a.set:
        name, path = s.split("=", 1)
        cols[name] = metrics.compute(metrics.from_results(path))
    text = metrics.render(cols)
    print(text)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")


if __name__ == "__main__":
    main()
```

- [ ] **Step 8: 跑全部 v2 测试**

Run: `cd $REPO/taskgen/v2 && $P -m pytest -q 2>&1 | tail -1`
Expected: `78 passed`（71 + 7）。

- [ ] **Step 9: 在真实数据上复算 §3 的数字**

```bash
cd $REPO/taskgen/v2 && mkdir -p $S
$P scripts/calibrate_check.py --env music | tail -1
$P scripts/task_stats.py --set v1=../v1/results --out $S/stats.md
```
Expected: calibrate 的合计行能打出来（music 一个库）；统计表和下面完全一致（第一次运行要建 DySQL 缓存，约 1 分钟）：

| metric | DySQL | v1 |
|---|---|---|
| tasks | 1062 | 3816 |
| write statements 0/1/2/3/4/≥5 | 0.3% / 33.1% / 46.6% / 12.1% / 4.8% / 3.1% | 0.0% / 38.1% / 47.5% / 14.4% / 0.0% / 0.0% |
| write statements mean / median | 2.29 / 2 | 1.76 / 2 |
| ≥3 write statements | 20.0% | 14.4% |
| statements with a subquery | 5.9% | 44.6% |
| instruction words mean / median / p90 | 57 / 54 / 80 | 102 / 98 / 146 |
| read-only ask | 4.2% | 73.4% |
| ID/email in first 25 words | 92.4% | 36.9% |
| type 1/2/3/4/5/other | 40.4% / 14.5% / 4.7% / 5.4% / 22.7% / 12.3% | 45.6% / 9.4% / 3.1% / 12.2% / 29.5% / 0.2% |
| difficulty easy/medium/hard | 26.3% / 45.3% / 28.4% | 21.3% / 42.5% / 36.2% |
| ≥2 tables written | 56.8% | 46.2% |
| >10 rows changed | 6.2% | 0.7% |
| templates / largest share | 421 / 6.6% | 1404 / 1.4% |

任何一格不同都先查原因（用 superpowers:systematic-debugging），不要改期望值。

- [ ] **Step 10: 同步设计文档和 README**

设计文档 `docs/2026-10-01-taskgen-v2-design.md` 三处替换（每处先给原文，再给新文本）：

1. 原文：
```markdown
| ≥3 条写语句的题 | 20.0%（212/1062；论文的 Long 47% 是连 SELECT 一起数的） | 14.5% | 18–24% |
```
新文本：
```markdown
| ≥3 条写语句的题 | 20.0%（212/1062；论文的 Long 47% 是连 SELECT 一起数的） | 14.4% | 18–24% |
```
2. 原文：
```markdown
| 说话人前 25 词内给 ID/邮箱 | 70% | 28% | 50–80% |
```
新文本：
```markdown
| 前 25 词内出现 ID、邮箱、SSN 或 #编号（`metrics.ID_RE`） | 92.4% | 36.9% | ≥80% |
```
3. 原文：
```markdown
| G 统计工具 | `taskgen/common/scripts/task_stats.py`：任意任务集 vs DySQL 的指标表（§3 的指标） | DySQL 和 v1 两列都复算出 §3 的数字 |
```
新文本：
```markdown
| G 统计工具 | `taskgen/v2/scripts/task_stats.py` + `taskgen_v2/metrics.py`：任意任务集 vs DySQL 的指标表（§3 的指标）。放在 v2 而不是 common：DySQL 一列要用本版本的执行检查打标签，common 不能 import 版本包 | DySQL 和 v1 两列都复算出 §3 的数字 |
```

`README.md` 改动记录表加一行：
```markdown
| 任务集统计：`scripts/task_stats.py` 和 DySQL 并排比 §3 的指标；DySQL 金标准的读取挪到 `taskgen_v2/dysql.py` | §3、§5 G |
```

- [ ] **Step 11: Commit**

```bash
cd $REPO
git add taskgen/v2
git diff --cached --name-only | grep -E 'results/|output/'; echo "no_data_exit=$?"
git commit -q -F - <<'EOF'
feat(taskgen v2): task-set metrics side by side with DySQL (scripts/task_stats.py)

metrics.compute gives the design §3 numbers for any results folder; the DySQL column runs this version's check on
the 1062 gold tasks (cached) and takes the task type from the DySQL classifier. Reading DySQL's gold tasks moves
from calibrate_check.py into taskgen_v2/dysql.py so both use it. Reproduces the §3 table for DySQL and v1.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```
Expected: `no_data_exit=1`；commit 成功。

---

### Task 3: 字面量按整词匹配，序数词算数字

**Files:**
- Modify: `taskgen/v2/taskgen_v2/check.py`（`text_forms`、`literal_ok`，新增 `ORDINALS`、`_contains`）
- Test: `taskgen/v2/tests/test_taskgen_check.py`（文件末尾追加）
- Modify: `taskgen/v2/README.md`（改动记录）

**Interfaces:**
- Consumes: `check.norm_literal(s)`、`check.text_forms(instruction)`、`check.literal_ok(lit, instruction, allowed)`。
- Produces: `check.ORDINALS: dict[str, str]`；`check._contains(text, n) -> bool`；`literal_ok` 签名不变。

- [ ] **Step 1: 写失败的测试（追加到 `tests/test_taskgen_check.py` 末尾）**

```python
# --- v2: whole-token literals, ordinal words ---

def test_literal_must_be_a_whole_token():
    ok = check.literal_ok
    assert not ok("203", "card 2030 has the wrong date", set())
    assert not ok("2", "in the 2016 season", set())
    assert not ok("ann", "my name is joanna", set())
    assert ok("2030", "card 2030 has the wrong date", set())


def test_ordinal_words_count_as_numbers():
    ok = check.literal_ok
    assert ok("2", "the run out in the second innings", set())
    assert ok("3", "my third order", set())
    assert ok("3", "the 3rd over", set())          # a digit with a suffix was already read as a number


def test_literals_next_to_punctuation_still_match():
    ok = check.literal_ok
    assert ok("o'brien", "change the owner to O'Brien's brother", set())
    assert ok("C00003174", "client C00003174, please", set())
    assert ok("Bozeman", "move him to Bozeman.", set())
    assert ok("$5 million", "set my net worth to '$5 million'", set())
```

- [ ] **Step 2: 跑测试，确认失败**

Run: `cd $REPO/taskgen/v2 && $P -m pytest -q tests/test_taskgen_check.py -k "whole_token or ordinal or punctuation"`
Expected: `test_literal_must_be_a_whole_token` 和 `test_ordinal_words_count_as_numbers` FAIL（`assert not ok("203", ...)` 为 True；`"second"` 不认）；punctuation 那条已经 PASS。

- [ ] **Step 3: 实现**

在 `WORDS = {...}` 定义之后加：

```python
ORDINALS = {w: str(i + 1) for i, w in enumerate(["first", "second", "third", "fourth", "fifth", "sixth", "seventh",
                                                 "eighth", "ninth", "tenth", "eleventh", "twelfth"])}
```

`text_forms` 里把

```python
    extra += [WORDS[w] for w in re.findall(r"[a-z]+", text) if w in WORDS]
```

换成

```python
    words = re.findall(r"[a-z]+", text)
    extra += [WORDS[w] for w in words if w in WORDS] + [ORDINALS[w] for w in words if w in ORDINALS]
```

在 `literal_ok` 前面加：

```python
def _contains(text, n):
    """n occurs in text as a whole token: '203' is not in '2030', 'ann' is not in 'joanna'."""
    return re.search(r"(?<!\w)" + re.escape(n) + r"(?!\w)", text) is not None
```

`literal_ok` 里把 `if n in text:` 换成 `if _contains(text, n):`，把 `if m and m.group(1) in text:` 换成 `if m and _contains(text, m.group(1)):`。

- [ ] **Step 4: 跑全部 v2 测试**

Run: `cd $REPO/taskgen/v2 && $P -m pytest -q 2>&1 | tail -1`
Expected: `81 passed`。

- [ ] **Step 5: README 改动记录加一行，commit**

```markdown
| 执行检查：字面量按整词匹配（`203` 不再匹配 `2030`），first…twelfth 算数字 | §4.5 |
```

```bash
cd $REPO && git add taskgen/v2
git diff --cached --name-only | grep -E 'results/|output/'; echo "no_data_exit=$?"
git commit -q -F - <<'EOF'
fix(taskgen v2): literals must match whole tokens; ordinal words count as numbers

Substring matching let '203' match '2030' and '2' match '2016' (20 v1 candidates passed only that way).
'second innings' now supplies 2.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 4: SQLite 会自动分配的新主键不必出现在 instruction 里

**Files:**
- Modify: `taskgen/v2/taskgen_v2/schema.py`（新增 `pk_info`）
- Modify: `taskgen/v2/taskgen_v2/check.py`（`run_check` 用 `pk_info`）
- Test: `taskgen/v2/tests/test_taskgen_schema.py`、`taskgen/v2/tests/test_taskgen_check.py`
- Modify: 设计文档 §4.5 一行、`taskgen/v2/README.md`

**Interfaces:**
- Consumes: `taskgen_common.db_select._q(name) -> str`。
- Produces: `schema.pk_info(conn) -> {table: {"cols": list[str], "rowid_alias": bool, "omittable": bool, "next": int | None}}`。`omittable` 为真当且仅当主键是 rowid 别名（单列、声明类型恰好是 `INTEGER`、不是 `WITHOUT ROWID` 表），并且没有 AUTOINCREMENT 或 `sqlite_sequence.seq <= MAX`；这时 `next = MAX + 1`（空表为 1），否则 `None`。计划 2 的 prompt 会用同一个函数给主键分类。

- [ ] **Step 1: 写失败的测试**

`tests/test_taskgen_schema.py` 顶部 import 改成：

```python
import json, os, sqlite3
from taskgen_common.testing import make_db, rows, SHOP
from taskgen_v2 import schema
```

文件末尾追加：

```python
def test_pk_info_classifies_primary_keys(tmp_path):
    path = make_db(tmp_path, "keys", """
CREATE TABLE plain (id INTEGER PRIMARY KEY, v TEXT);
CREATE TABLE auto_ok (id INTEGER PRIMARY KEY AUTOINCREMENT, v TEXT);
CREATE TABLE auto_ahead (id INTEGER PRIMARY KEY AUTOINCREMENT, v TEXT);
CREATE TABLE int_key (id INT PRIMARY KEY, v TEXT);
CREATE TABLE text_key (code TEXT PRIMARY KEY, v TEXT);
CREATE TABLE pair (a INTEGER, b INTEGER, PRIMARY KEY (a, b));
CREATE TABLE no_rowid (id INTEGER PRIMARY KEY, v TEXT) WITHOUT ROWID;
CREATE TABLE "Sales Orders" (id INTEGER PRIMARY KEY, v TEXT);
CREATE TABLE empty (id INTEGER PRIMARY KEY, v TEXT);
CREATE TABLE nokey (v TEXT);
""" + rows("plain", 5, lambda i: f"{i + 1},'x'") + rows("auto_ok", 5, lambda i: f"{i + 1},'x'")
        + rows("auto_ahead", 5, lambda i: f"{i + 1},'x'") + "INSERT INTO auto_ahead VALUES (10, 'y'); DELETE FROM auto_ahead WHERE id = 10;"
        + rows('"Sales Orders"', 3, lambda i: f"{i + 1},'x'"))
    info = schema.pk_info(sqlite3.connect(path))
    assert info["plain"] == {"cols": ["id"], "rowid_alias": True, "omittable": True, "next": 6}
    assert info["auto_ok"]["omittable"] and info["auto_ok"]["next"] == 6
    assert info["auto_ahead"] == {"cols": ["id"], "rowid_alias": True, "omittable": False, "next": None}   # sequence at 10 (WWE)
    for t in ("int_key", "text_key", "pair", "no_rowid", "nokey"):
        assert not info[t]["omittable"] and info[t]["next"] is None, t
    assert info["pair"]["cols"] == ["a", "b"] and info["nokey"]["cols"] == []
    assert info["Sales Orders"]["next"] == 4 and info["empty"]["next"] == 1
```

`tests/test_taskgen_check.py` 末尾追加：

```python
# --- v2: keys SQLite would assign need not be spoken ---

def test_auto_assigned_key_need_not_be_spoken(db):
    # orders are 0..99, so SQLite would give a new order 100; the item that refers to the new order may say 100 too
    r = check.run_check(db, cand("I am a5 b5. Place a new order of product 7, qty 2, with the note gift.",
                                 ["INSERT INTO orders (order_id, customer_id, product_id, qty) VALUES (100, 5, 7, 2)",
                                  "INSERT INTO order_items (order_id, note) VALUES (100, 'gift')"]))
    assert r["ok"], r["reasons"]


def test_a_key_sqlite_would_not_assign_must_be_spoken(db):
    r = check.run_check(db, cand("I am a5 b5. Place a new order of product 7, qty 2.",
                                 ["INSERT INTO orders (order_id, customer_id, product_id, qty) VALUES (150, 5, 7, 2)"]))
    assert r["reasons"] == ["literal_missing: '150' in INSERT orders"]


def test_auto_key_lookup_ignores_table_name_case(db):
    r = check.run_check(db, cand("I am a5 b5. Place a new order of product 7, qty 2.",
                                 ['INSERT INTO "ORDERS" (order_id, customer_id, product_id, qty) VALUES (100, 5, 7, 2)']))
    assert r["ok"], r["reasons"]


def test_several_new_rows_get_consecutive_auto_keys(db):
    r = check.run_check(db, cand("I am a5 b5. Add two new orders of product 7 for me.",
                                 ["INSERT INTO orders (order_id, customer_id, product_id, qty) VALUES (100, 5, 7, 1), (101, 5, 7, 1)"]))
    assert r["ok"], r["reasons"]
```

- [ ] **Step 2: 跑测试，确认失败**

Run: `cd $REPO/taskgen/v2 && $P -m pytest -q tests/test_taskgen_schema.py tests/test_taskgen_check.py -k "pk_info or auto"`
Expected: `test_pk_info_classifies_primary_keys` FAIL（`AttributeError: module 'taskgen_v2.schema' has no attribute 'pk_info'`）；三条 auto 测试 FAIL（`literal_missing: '100' in INSERT orders` 等）；`test_a_key_sqlite_would_not_assign_must_be_spoken` 已经 PASS。

- [ ] **Step 3: 在 `schema.py` 实现 `pk_info`**

import 行改成：

```python
import csv, glob, json, os, re, sqlite3
from taskgen_common.db_select import _q
```

文件末尾加：

```python
def pk_info(conn):
    """{table: {"cols", "rowid_alias", "omittable", "next"}} for every table of an open connection.
    omittable: an INSERT may leave the key out and SQLite assigns MAX + 1 -- the key is a rowid alias (one column
    declared exactly INTEGER, rowid table) and, with AUTOINCREMENT, sqlite_sequence has not run ahead of MAX (it has
    in 8 WWE tables). next is that MAX + 1 (1 for an empty table) for omittable tables, else None."""
    seq = {}
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'sqlite_sequence'").fetchone():
        seq = dict(conn.execute("SELECT name, seq FROM sqlite_sequence").fetchall())
    out = {}
    for name, sql in conn.execute("SELECT name, sql FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'").fetchall():
        pk = sorted((r for r in conn.execute(f"PRAGMA table_info({_q(name)})") if r[5]), key=lambda r: r[5])
        cols = [r[1] for r in pk]
        rowid_alias = (len(pk) == 1 and (pk[0][2] or "").upper() == "INTEGER"
                       and not re.search(r"(?i)\bwithout\s+rowid\b", sql or ""))
        nxt = None
        if rowid_alias:
            (mx,) = conn.execute(f"SELECT MAX({_q(cols[0])}) FROM {_q(name)}").fetchone()
            autoinc = re.search(r"(?i)\bautoincrement\b", sql or "") is not None
            if not autoinc or (seq.get(name) or 0) <= (mx or 0):
                nxt = (mx or 0) + 1
        out[name] = {"cols": cols, "rowid_alias": rowid_alias, "omittable": nxt is not None, "next": nxt}
    return out
```

- [ ] **Step 4: `check.py` 用它**

import 行 `from taskgen_v2 import prompt, trees` 改成 `from taskgen_v2 import prompt, schema, trees`。

`run_check` 里，在 `tracer = Tracer(db_rec, db)` 这一行后面加：

```python
    pks = schema.pk_info(db)
    auto_next = {t.lower(): v["next"] for t, v in pks.items() if v["omittable"]}
    auto_col = {t.lower(): v["cols"][0] for t, v in pks.items() if v["omittable"]}
```

循环里，在 `stmts.append(st)` 这一行后面加：

```python
                key = table.lower()
                if op == "INSERT" and key in auto_next:
                    # keys SQLite would assign anyway: an agent may leave them out, so the user need not say them,
                    # here or in a later statement that refers to the new row
                    for r in rs:
                        v = dict(zip(rcols, r)).get(auto_col[key])
                        if v != auto_next[key]:
                            break
                        allowed.add(norm_literal(v)); auto_next[key] += 1
```

- [ ] **Step 5: 跑全部 v2 测试**

Run: `cd $REPO/taskgen/v2 && $P -m pytest -q 2>&1 | tail -1`
Expected: `86 passed`。

- [ ] **Step 6: 同步设计文档，README 记一行，commit**

设计文档 §4.5 替换一行。原文：
```markdown
- next id 作为隐含字面量，限"可省 ID"的表的主键列（§4.3）；其余表的新 ID 仍必须在 instruction 里。往 `no_insert` 的表 INSERT 算拒绝。
```
新文本：
```markdown
- **SQLite 会自动分配的新主键算隐含字面量：** 表是"可省 ID"的（`schema.pk_info`，§4.3），INSERT 写的主键正好是 SQLite 会分配的下一个值（多行时依次加一）。这个值在这条 INSERT 和之后引用新行的语句里都不必出现在 instruction 里。其余表的新 ID 仍必须在 instruction 里。往 `no_insert` 的表 INSERT 算拒绝（要档案，计划 2）。
```

README 改动记录：
```markdown
| 执行检查：SQLite 会自动分配的新主键不必出现在 instruction 里；`schema.pk_info` 给每张表的主键分类 | D9、§4.3、§4.5 |
```

```bash
cd $REPO && git add taskgen/v2
git diff --cached --name-only | grep -E 'results/|output/'; echo "no_data_exit=$?"
git commit -q -F - <<'EOF'
fix(taskgen v2): keys SQLite would assign need not appear in the instruction

schema.pk_info classifies primary keys; for a rowid-alias key whose sequence is not ahead of MAX, an INSERT that
writes exactly the next key (and later statements referring to it) no longer fails literal_missing. 66 of v1's
75 rejected INSERT numbers were such keys. Other new keys must still be spoken.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 5: 读时钟或随机数的 gold 执行两遍

**Files:**
- Modify: `taskgen/v2/taskgen_v2/check.py`（新增 `NONDET`、`VOLATILE_COL_RE`、`RERUN_GAP_S`、`snapshot`、`rerun_changes`；`run_check` 调用）
- Test: `taskgen/v2/tests/test_taskgen_check.py`
- Modify: 设计文档 D5、§3 一行、§4.5 两处；`taskgen/v2/README.md`

**Interfaces:**
- Consumes: `check.write_target`、`Tracer.canon`、`_q`。
- Produces: `check.snapshot(db, tables) -> {table: rows | (count,)}`；`check.rerun_changes(db, stmts, tables) -> str`（不一致的表名，逗号分隔；一致时为空串）；新的拒绝原因 `nondeterministic: <表名>` 或 `nondeterministic: rerun failed: <错误>`。

- [ ] **Step 1: 写失败的测试（追加到 `tests/test_taskgen_check.py` 末尾）**

```python
# --- v2: gold that reads the clock or random() ---

RENTAL = """
CREATE TABLE customers (customer_id INTEGER PRIMARY KEY, first_name TEXT, last_name TEXT);
CREATE TABLE rental (rental_id INTEGER PRIMARY KEY, customer_id INTEGER REFERENCES customers(customer_id),
                     return_date TEXT, last_update TEXT);
""" + rows("customers", 10, lambda i: f"{i},'a{i}','b{i}'") + rows("rental", 20, lambda i: f"{i},{i % 10},NULL,'2006-02-15'")
RENTAL_FKS = [{"table": "rental", "col": "customer_id", "ref_table": "customers", "ref_col": "customer_id", "hit": 1.0, "source": "declared"}]
RENTAL_CUSTOMER = {**CUSTOMER, "rows": 10, "down": ["rental"], "up": [], "update_targets": ["customers", "rental"]}


@pytest.fixture
def rental(tmp_path):
    return {"source": "test", "db": "rental", "path": make_db(tmp_path, "rental", RENTAL), "anchors": [RENTAL_CUSTOMER], "fks": RENTAL_FKS}


def test_clock_value_in_a_compared_column_is_rejected(rental):
    r = check.run_check(rental, cand("I am a5 b5. Mark my rental 5 as returned right now.",
                                     ["UPDATE rental SET return_date = CURRENT_TIMESTAMP WHERE rental_id = 5"]))
    assert r["reasons"] == ["nondeterministic: rental"]


def test_clock_value_in_a_volatile_column_passes(rental):     # the eval hash skips last_update (pagila)
    r = check.run_check(rental, cand("I am a5 b5. Set the return date of my rental 5 to 2024-01-02.",
                                     ["UPDATE rental SET return_date = '2024-01-02', last_update = CURRENT_TIMESTAMP WHERE rental_id = 5"]))
    assert r["ok"], r["reasons"]


def test_date_only_clock_value_passes(rental):                # same value all day (fails only across UTC midnight)
    r = check.run_check(rental, cand("I am a5 b5. Mark my rental 5 as returned today.",
                                     ["UPDATE rental SET return_date = CURRENT_DATE WHERE rental_id = 5"]))
    assert r["ok"], r["reasons"]


def test_random_value_is_rejected(rental):
    r = check.run_check(rental, cand("I am a5 b5. Give my rental 5 a random return code.",
                                     ["UPDATE rental SET return_date = abs(random()) WHERE rental_id = 5"]))
    assert r["reasons"] == ["nondeterministic: rental"]


def test_clock_value_with_a_failing_statement_is_not_rerun(rental):
    r = check.run_check(rental, cand("I am a5 b5. Mark my rental 5 as returned right now.",
                                     ["UPDATE rental SET return_date = CURRENT_TIMESTAMP WHERE rental_id = 5", "UPDATE nope SET a = 1"]))
    assert any(x.startswith("sql_error") for x in r["reasons"]) and not any(x.startswith("nondeterministic") for x in r["reasons"])


def test_snapshot_quotes_names_and_skips_volatile_columns(tmp_path):
    c = sqlite3.connect(make_db(tmp_path, "s", 'CREATE TABLE "Sales Orders" (id INTEGER PRIMARY KEY, "Order Date" TEXT, last_update TEXT);'
                                              "INSERT INTO \"Sales Orders\" VALUES (2, 'b', 'x'), (1, 'a', 'y');"))
    assert check.snapshot(c, {"Sales Orders"}) == {"Sales Orders": [(1, "a"), (2, "b")]}


def test_volatile_columns_match_the_eval():
    from dysql_bench.envs.base import VOLATILE_COL_RE
    assert check.VOLATILE_COL_RE.pattern == VOLATILE_COL_RE.pattern
```

- [ ] **Step 2: 跑测试，确认失败**

Run: `cd $REPO/taskgen/v2 && $P -m pytest -q tests/test_taskgen_check.py -k "clock or random or snapshot or volatile"`
Expected: `test_clock_value_in_a_compared_column_is_rejected`、`test_random_value_is_rejected` FAIL（reasons 为空）；snapshot、volatile 两条 FAIL（`AttributeError`）；其余 PASS。

- [ ] **Step 3: 实现**

import 行 `import json, re, sqlite3, unicodedata` 改成 `import json, re, sqlite3, time, unicodedata`。

在 `ARCHIVE_SRC = ...` 之后加：

```python
# gold that reads the clock or random(): run it twice and compare what the eval hash compares
NONDET = re.compile(r"(?i)\bcurrent_(?:timestamp|time|date)\b|'now'|\brandom(?:blob)?\s*\(|\bunixepoch\s*\(")
# columns the eval hash skips, copied from DySQL-Bench/dysql_bench/envs/base.py (test_volatile_columns_match_the_eval)
VOLATILE_COL_RE = re.compile(
    r"(?i)^(last_?update|updated_?at|update_?time|modified(_at)?|modification_?time|create(d)?_?at|timestamp)$")
RERUN_GAP_S = 1.1   # CURRENT_TIMESTAMP has one-second resolution; date-only values agree within a day and pass
```

在 `_memory_copy` 前面加：

```python
def snapshot(db, tables):
    """Per table, what the eval hash compares: the non-volatile columns of every row, in a stable order."""
    out = {}
    for t in sorted(tables):
        cols = [r[1] for r in db.execute(f"PRAGMA table_info({_q(t)})")]
        keep = ", ".join(_q(c) for c in cols if not VOLATILE_COL_RE.match(c))
        out[t] = (db.execute(f"SELECT {keep} FROM {_q(t)} ORDER BY {keep}").fetchall() if keep
                  else db.execute(f"SELECT COUNT(*) FROM {_q(t)}").fetchone())
    return out


def rerun_changes(db, stmts, tables):
    """Run the write statements again, RERUN_GAP_S later, from the same starting state. The caller's open
    transaction holds the first run. Returns the tables whose compared columns differ, '' when the runs agree."""
    first = snapshot(db, tables)
    db.execute("ROLLBACK"); time.sleep(RERUN_GAP_S); db.execute("BEGIN")
    try:
        for s in stmts:
            db.execute(s).fetchall()
    except sqlite3.Error as e:
        return f"rerun failed: {e}"
    second = snapshot(db, tables)
    return ", ".join(t for t in sorted(tables) if first[t] != second[t])
```

`run_check` 里，`for a in cand["actions"]:` 循环结束之后、`finally:` 之前（缩进和 `for` 同级）加：

```python
        if any(NONDET.search(s) for s in stmts) and not any(x.startswith("sql_error") for x in out["reasons"]):
            changed = rerun_changes(db, stmts, {tracer.canon(write_target(s)[1]) for s in stmts})
            if changed:
                out["reasons"].append("nondeterministic: " + changed)
```

- [ ] **Step 4: 跑全部 v2 测试**

Run: `cd $REPO/taskgen/v2 && $P -m pytest -q 2>&1 | tail -1`
Expected: `93 passed`。

- [ ] **Step 5: 同步设计文档，README 记一行，commit**

设计文档四处替换（每处先给原文，再给新文本）：

1. D5 一行里的片段。原文：`13 条用了时间函数`；新文本：`约 3 条把当前时间写进评测会比较的列`。
2. §3 `执行检查通过率` 一行里的片段。原文：`（时间函数约 13 条等）`；新文本：`（时间函数约 3 条等）`。
3. §4.5 的一行。原文：
```markdown
- 拒绝 `CURRENT_TIMESTAMP`、`CURRENT_DATE`、`date('now')`、`random()`；gold 在两份副本上各跑一遍比整库哈希，不一致拒。
```
新文本：
```markdown
- **非确定性：** gold 里有读时钟或随机数的函数（`CURRENT_TIMESTAMP`、`'now'`、`random()` 等）时，间隔 1.1 秒执行两遍，比较评测哈希会比较的列（去掉 `last_update` 这类 volatile 列，正则和评测一致）；不一致就拒（`nondeterministic`）。只精确到日的值（`CURRENT_DATE`、`date('now')`）同一天内一致，放行；写进 volatile 列的时间也放行（pagila 的 `last_update = CURRENT_TIMESTAMP`）。不含这些函数的 gold 不重跑：同一个库上执行同样的语句，SQLite 的结果是确定的。
```
4. §4.5 最后一条里的片段。原文：
```markdown
（时间函数约 13 条：pagila 10、retail_world 2、entertainment 1）
```
新文本：
```markdown
（时间函数里会被拒的约 3 条：pagila 把 `CURRENT_TIMESTAMP` 写进 return_date、payment_date；其余写的是 last_update，或只精确到日）
```

README 改动记录：
```markdown
| 执行检查：读时钟或随机数的 gold 间隔 1.1 秒执行两遍，评测会比较的列不一致就拒 | §4.5 |
```

```bash
cd $REPO && git add taskgen/v2
git diff --cached --name-only | grep -E 'results/|output/'; echo "no_data_exit=$?"
git commit -q -F - <<'EOF'
fix(taskgen v2): reject gold whose result depends on the clock or random()

Gold containing a clock or random function runs twice, 1.1 s apart, and the columns the eval hash compares must
agree (volatile columns such as last_update are skipped with the eval's own regex). Date-only values pass.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 6: 说话人登记的新人物行不算"别人"

**Files:**
- Modify: `taskgen/v2/taskgen_v2/check.py`（`run_check` 的标签、`task_group`）
- Test: `taskgen/v2/tests/test_taskgen_check.py`
- Modify: 设计文档 §4.5 一处；`taskgen/v2/README.md`

**Interfaces:**
- Consumes: `Tracer.persons`（人物表 → 主键列）。
- Produces: `writes[i]["label"]` 新值 `"new_person"`；`task_group` 把它当 `"public"`。

- [ ] **Step 1: 写失败的测试（追加到 `tests/test_taskgen_check.py` 末尾）**

```python
# --- v2: a new person row is nobody's data yet ---

def test_new_person_row_is_not_another_persons_data(db):
    r = check.run_check(db, cand("I am a5 b5. Please register my friend Zoe Quinn as a customer.",
                                 ["INSERT INTO customers (customer_id, first_name, last_name) VALUES (60, 'Zoe', 'Quinn')"]))
    assert r["ok"], r["reasons"]
    assert r["writes"][0]["label"] == "new_person" and r["task_type"] == "3_public_only"
    r = check.run_check(db, cand("I am a5 b5. Register my friend Zoe Quinn as a customer and set qty of my order 5 to 3.",
                                 ["INSERT INTO customers (customer_id, first_name, last_name) VALUES (60, 'Zoe', 'Quinn')",
                                  "UPDATE orders SET qty = 3 WHERE order_id = 5"]))
    assert r["task_type"] == "2_self_and_public"


def test_proxy_registering_a_person_is_unchanged(db):
    r = check.run_check(db, cand("I am Pat, an analyst. Register Zoe Quinn as a customer.",
                                 ["INSERT INTO customers (customer_id, first_name, last_name) VALUES (60, 'Zoe', 'Quinn')"],
                                 task_type="5_proxy"))
    assert r["writes"][0]["label"] == "person_obj" and r["task_type"] == "5_proxy"
```

- [ ] **Step 2: 跑测试，确认失败**

Run: `cd $REPO/taskgen/v2 && $P -m pytest -q tests/test_taskgen_check.py -k "new_person or registering"`
Expected: `test_new_person_row_is_not_another_persons_data` FAIL（label 是 `other`，类型 `4_other_person`）；proxy 那条 PASS。

- [ ] **Step 3: 实现**

`run_check` 里把

```python
                elif speaker_in_db:
                    lab = "own" if owners & speaker_ids else ("other" if owners else "public")
```

换成

```python
                elif speaker_in_db:
                    if owners & speaker_ids:
                        lab = "own"
                    elif op == "INSERT" and table in tracer.persons:
                        lab = "new_person"   # a person row that did not exist before is nobody else's data yet
                    else:
                        lab = "other" if owners else "public"
```

`task_group` 第一行

```python
    core = sorted({x for x in labels if x not in ("noop",)})
```

换成

```python
    core = sorted({"public" if x == "new_person" else x for x in labels if x != "noop"})
```

- [ ] **Step 4: 跑全部 v2 测试**

Run: `cd $REPO/taskgen/v2 && $P -m pytest -q 2>&1 | tail -1`
Expected: `95 passed`。

- [ ] **Step 5: 同步设计文档，README 记一行，commit**

设计文档 §4.5 替换一行。原文：
```markdown
- **新插入的人物行**不再算"别人"：INSERT 进人物表且不是说话人的行，标 `new_person`，按公共数据处理（v1 里造成 54 条类型不一致，也是 DySQL 被算出 17.6% 第 4 类的来源之一）。
```
新文本：
```markdown
- **新插入的人物行**不再算"别人"：说话人在库里时，INSERT 进人物表、又追不到说话人的行标 `new_person`，算类型时按公共数据处理（v1 里造成 54 条类型不一致，也是 DySQL 被算出 17.6% 第 4 类的来源之一）。库外说话人（第 5 类）登记新的人，仍算 `person_obj`，不变。
```

README 改动记录：
```markdown
| 执行检查：说话人登记的新人物行标 `new_person`，算类型时按公共数据 | §4.5 |
```

```bash
cd $REPO && git add taskgen/v2
git diff --cached --name-only | grep -E 'results/|output/'; echo "no_data_exit=$?"
git commit -q -F - <<'EOF'
fix(taskgen v2): a person row the speaker inserts is new, not another person's data

Labelled new_person and counted as public when computing the task type; it made 54 v1 candidates "type 4" and
inflated DySQL's type-4 share under the check's rules. A proxy registering a person stays person_obj.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 7: 重新校准：v1 和 v2 的检查逐条对比

**Files:**
- Create: `taskgen/v2/scripts/check_diff.py`
- Create: `taskgen/v2/tests/test_taskgen_check_diff.py`
- Create: `taskgen/v2/docs/<执行当天日期>-check-recalibration.md`（脚本生成，再加一段结论）
- Modify: 设计文档 §3 `执行检查通过率` 一行；`taskgen/v2/README.md`

**Interfaces:**
- Consumes: `taskgen_v1.check.run_check_safe`（冻结的 v1）、`taskgen_v2.check.run_check_safe`、`taskgen_v2.dysql.ENVS/db_rec/candidates`、`taskgen_v2.io.load_db_recs/read_jsonl`。
- Produces: `check_diff.kinds(result) -> set[str]`；`check_diff.section(title, pairs) -> list[str]`，`pairs = [(id, v1_result, v2_result)]`。

- [ ] **Step 1: 写失败的测试 `tests/test_taskgen_check_diff.py`**

```python
# tests/test_taskgen_check_diff.py
import importlib.util, os

_P = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "check_diff.py")
_S = importlib.util.spec_from_file_location("check_diff", _P)
cd = importlib.util.module_from_spec(_S); _S.loader.exec_module(cd)


def r(ok, reasons=(), t="1_self"):
    return {"ok": ok, "reasons": list(reasons), "task_type": t}


def test_section_counts_transitions_and_groups_the_changes():
    pairs = [("a", r(True), r(True)),
             ("b", r(True), r(False, ["nondeterministic: rental"])),
             ("c", r(False, ["literal_missing: '100' in INSERT orders"]), r(True)),
             ("d", r(False, ["noop_write: UPDATE t"]), r(False, ["noop_write: UPDATE t", "literal_missing: 'x' in UPDATE t"])),
             ("e", r(True, t="4_other_person"), r(True, t="3_public_only"))]
    text = "\n".join(cd.section("demo", pairs))
    for row in ("| 通过 | 通过 | 2 |", "| 通过 | 拒绝 | 1 |", "| 拒绝 | 通过 | 1 |", "| 拒绝 | 拒绝 | 1 |"):
        assert row in text, row
    assert "- 通过 → 拒绝：nondeterministic（1）：b" in text
    assert "- 拒绝 → 通过：v1 的原因 literal_missing（1）：c" in text
    assert "- 仍拒绝、原因变了：noop_write → literal_missing+noop_write（1）：d" in text
    assert "- 4_other_person → 3_public_only：1" in text
```

- [ ] **Step 2: 跑测试，确认失败**

Run: `cd $REPO/taskgen/v2 && $P -m pytest -q tests/test_taskgen_check_diff.py`
Expected: FAIL（`FileNotFoundError`：脚本还不存在）。

- [ ] **Step 3: 新建 `scripts/check_diff.py`**

```python
#!/usr/bin/env python3
"""Run v1's frozen check and this version's check on the same candidates and attribute every changed verdict.
Sets: DySQL's 1062 gold tasks, and every candidate under --results (default: v1's full run, ../v1/results).
Only candidate ids and counts go into the report, never task text.
Usage (from taskgen/v2/):
  ~/miniconda3/envs/dysql/bin/python scripts/check_diff.py --out docs/<date>-check-recalibration.md"""
import argparse, glob, os, sys
from collections import Counter, defaultdict
V2 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TASKGEN = os.path.dirname(V2)
sys.path[:0] = [V2, os.path.join(TASKGEN, "v1"), os.path.join(TASKGEN, "common")]   # taskgen_v2, taskgen_v1, taskgen_common
from taskgen_v1 import check as old_check
from taskgen_v2 import check as new_check, dysql, io

YES = {True: "通过", False: "拒绝"}


def kinds(result):
    return {x.split(":")[0] for x in result["reasons"]}


def section(title, pairs):
    trans = Counter((o["ok"], n["ok"]) for _, o, n in pairs)
    groups, relabel = defaultdict(list), Counter()
    for cid, o, n in pairs:
        ko, kn = kinds(o), kinds(n)
        if o["ok"] and not n["ok"]:
            groups["通过 → 拒绝：" + "+".join(sorted(kn))].append(cid)
        elif n["ok"] and not o["ok"]:
            groups["拒绝 → 通过：v1 的原因 " + "+".join(sorted(ko))].append(cid)
        elif not o["ok"] and ko != kn:
            groups["仍拒绝、原因变了：" + "+".join(sorted(ko)) + " → " + "+".join(sorted(kn))].append(cid)
        if o["task_type"] and n["task_type"] and o["task_type"] != n["task_type"]:
            relabel[f"{o['task_type']} → {n['task_type']}"] += 1
    lines = [f"## {title}（{len(pairs)} 条）", "", "| v1 | v2 | 条数 |", "|---|---|---|"]
    lines += [f"| {YES[a]} | {YES[b]} | {trans[(a, b)]} |" for a in (True, False) for b in (True, False)]
    lines += ["", "### 判决变化", ""]
    lines += [f"- {k}（{len(v)}）：" + ", ".join(v[:10]) + (" …" if len(v) > 10 else "") for k, v in sorted(groups.items())] or ["- 无"]
    lines += ["", "### 类型变化（两边都算出了类型的）", ""]
    lines += [f"- {k}：{v}" for k, v in relabel.most_common()] or ["- 无"]
    return lines


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results", default=os.path.join(TASKGEN, "v1", "results"))
    ap.add_argument("--out")
    a = ap.parse_args()
    pairs = []
    for env in dysql.ENVS:
        rec = dysql.db_rec(env)
        for c in dysql.candidates(env):
            pairs.append((c["id"], old_check.run_check_safe(rec, c), new_check.run_check_safe(rec, c)))
    lines = ["# 执行检查重新校准：v1 vs v2", "",
             "`scripts/check_diff.py` 生成：同一批候选分别跑 v1（tag `taskgen-v1`，冻结）和 v2 的 `check.run_check_safe`，逐条比较。"
             "只列候选 id，不摘录题目内容。", ""] + section("DySQL 金标准", pairs)
    recs = {v["db"]: v for v in io.load_db_recs().values()}
    pairs = []
    for f in sorted(glob.glob(os.path.join(a.results, "*", "candidates.jsonl"))):
        rec = recs[os.path.basename(os.path.dirname(f))]
        for c in io.read_jsonl(f):
            pairs.append((c["id"], old_check.run_check_safe(rec, c), new_check.run_check_safe(rec, c)))
    lines += [""] + section(f"候选：{os.path.relpath(a.results, V2)}", pairs)
    text = "\n".join(lines)
    print(text)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 跑全部 v2 测试**

Run: `cd $REPO/taskgen/v2 && $P -m pytest -q 2>&1 | tail -1`
Expected: `96 passed`。

- [ ] **Step 5: 在真实数据上跑，逐组核对**

```bash
cd $REPO/taskgen/v2
D=$(date +%F)
$P scripts/check_diff.py --out docs/$D-check-recalibration.md > /dev/null && sed -n 1,200p docs/$D-check-recalibration.md
```

每一组判决变化都必须能归到 Task 3–6 的某一处改动。预期：

| 组 | 预期来源 | 预期规模 |
|---|---|---|
| DySQL：通过 → 拒绝：nondeterministic | Task 5：pagila 把 `CURRENT_TIMESTAMP` 写进 return_date、payment_date | 2–3 条 |
| 任一集合：通过 → 拒绝：literal_missing | Task 3：只靠子串匹配放行的字面量 | v1 候选 ≤ 20 条；DySQL 少量 |
| 任一集合：拒绝 → 通过：v1 的原因 literal_missing | Task 3 序数词、Task 4 自动分配的主键 | v1 候选最多约 66 条 |
| 类型变化 4_other_person → 3_public_only / 2_self_and_public | Task 6 | v1 候选约 50 条；DySQL 约 30 条 |

出现上表以外的组，或规模差得很远：停下来，用 superpowers:systematic-debugging 查清，修代码或在报告里写明原因；不要直接改预期。对每一组抽 2–3 个 id 看 v2 的 `reasons`，确认原因说得通。

- [ ] **Step 6: 报告加结论段，同步设计文档和 README**

在报告标题下面加一段"结论"（3–5 行）：两个集合各自的通过数（v1 → v2），每组变化对应哪处改动，有没有没解释的变化。

设计文档 §3 `执行检查通过率` 一行的 v2 目标格，在原有文字后面补一句实测结果，格式如下（四个数字和日期 `<D>` 按报告实际填）：
```markdown
；实测 DySQL 908 → <v2 通过数>，v1 候选 3816 → <v2 通过数>，见 `docs/<D>-check-recalibration.md`
```
（908、3816 是 v1 的通过数；若报告里 v1 一列不是这两个数，以报告为准，并在结论段说明差异。）

README 改动记录：
```markdown
| 执行检查重新校准：v1 和 v2 的检查在 DySQL 金标准和 v1 全部候选上逐条对比（`scripts/check_diff.py`），报告 `docs/<D>-check-recalibration.md` | §5 E |
```

- [ ] **Step 7: 四套测试再跑一遍**

```bash
cd $REPO/taskgen/v2 && $P -m pytest -q 2>&1 | tail -1
cd $REPO/taskgen/v1 && $P -m pytest -q 2>&1 | tail -1
cd $REPO/taskgen/common && $P -m pytest -q 2>&1 | tail -1
cd $REPO/DySQL-Bench && $P -m pytest -q 2>&1 | tail -1
cd $REPO && git status --short taskgen/v1    # 必须为空：v1 没被改
```
Expected: `96 passed`、`71 passed`、`65 passed`、`33 passed`；`git status` 对 `taskgen/v1` 没有输出。

- [ ] **Step 8: Commit**

```bash
cd $REPO && git add taskgen/v2
git diff --cached --name-only | grep -E 'results/|output/'; echo "no_data_exit=$?"
git commit -q -F - <<'EOF'
test(taskgen v2): recalibrate the check against v1's on DySQL gold and all v1 candidates

scripts/check_diff.py runs the frozen v1 check and the v2 check on the same candidates and groups every changed
verdict by reason; each group is attributed to one of the four check changes in the report.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

## 之后的计划（这份完成后再写）

- **计划 2：** 库档案（阶段 B，含你确认 23 份）和嵌套建树（阶段 C）；执行检查改读档案（范围、归属、`same_as`、`no_insert`）。
- **计划 3：** 出题（阶段 D）：主键三类进 prompt、写语句数分布、去掉 outputs 和只读提问、说话人 ID、few-shot。
- **计划 4：** 校验（阶段 F）：模型列表配置、三组样本校准、标注集。
- **计划 5：** 试点、全量、对照、收尾（阶段 H–K）。
