# 训练任务生成 pipeline：实施计划

> 2026-10-01 目录重组后，文中的代码、脚本和文档路径都是重组前的旧路径，新旧对照见 [taskgen/README.md](../../README.md)。正文保持原样，作为当时的记录。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 `candidate_anchors.json` 驱动一条通用 pipeline，从候选库生成 DySQL 风格的多轮写操作任务：建树 → 出题（GLM-5.3）→ 执行检查 → LLM 校验（Qwen3.8-27B-NVFP4）→ 去重 → 转成 `Task` 并接入通用 `GenEnv`。先在 beer_factory 上试点，再跑 23 个有名字的人物库。

**Architecture:**
- 新包 `DySQL-Bench/dysql_bench/taskgen/`，每个步骤一个模块，步骤之间只通过 JSONL 文件传递，按 `id` 断点续跑。
- `scripts/select_dbs.py` 的锚点 JSON 改成自包含：加 sqlite 路径和有效外键的列对。建树只读 JSON 和 sqlite。
- 执行检查（`check.py`）在 LLM 校验前，同时算出任务类型、难度分、模板，这三样是去重和统计的依据。
- `dysql_bench/envs/gen/` 是通用 env，`get_env("gen:<db>")` 从 `data/taskgen/manifest.json` 读库路径和任务文件。
- LLM 调用统一走 `llm.ChatClient`（`requests` 调 OpenAI 兼容接口），测试里用假的 session 或假的 client 注入，不联网。

**Tech Stack:** Python 3.11（conda env `dysql`），标准库 `sqlite3`、`json`、`concurrent.futures`，第三方只用已装的 `requests`、`sqlparse`、`pydantic`、`pytest`。测试一律在 `DySQL-Bench/` 目录下跑：`~/miniconda3/envs/dysql/bin/python -m pytest -q tests/...`。

**Spec:** `docs/2026-09-28-task-gen-design.md`。所有比例、阈值、规则以它为准；本计划里的数字都是从它抄的。

## Global Constraints

- 分支 `isa/data-gen`。每个 Task 单独 commit，commit message 以 `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` 结尾。
- 秘密只放仓库根目录 `.env`（已在 `.gitignore`）。代码里不出现 key，测试里不联网。
- 原始库在 `~/Documents/Isa/text2sql_bench`（环境变量 `TEXT2SQL_BENCH` 可覆盖）。DySQL 的 13 个库在 `DySQL-Bench/dysql_bench/envs/*/data/*.sqlite`。
- SQL 里的表名、列名一律用 `db_select._q()` 包成 `"…"`。真实库里有 `Sales Orders`、`voice-actors`、`Air Carriers` 这种名字。
- 中间产物写 `DySQL-Bench/results/taskgen/<db>/`（`.gitignore` 已排除 `DySQL-Bench/results/`）。最终产物 `DySQL-Bench/data/taskgen/` 进 git。
- 模型调用参数（spec §3、§8）：出题 temperature 1.0、top_p 0.95、max_tokens 16384；校验 temperature 1.2、max_tokens 16384。票数默认 3，试点用 5。
- 比例（spec §4、§5）：类型 1–5 = 46 / 12 / 5 / 8 / 29；难度 简单 / 中等 / 困难 = 26 / 45 / 29；三成样本不指定写入表。封顶：每人 ≤ 2、每模板 ≤ 15、每库 ≤ 600。单条语句 > 50 行判 bulk。
- 每个任务的 JSONL 记录都带 `id`，格式 `"<source>:<db>:<anchor_table>:<key_value>:<n>"`。所有子命令重跑时跳过输出文件里已有的 `id`。

## Review Focus

按 spec 推出来、但下面任务的测试没有覆盖的输入，最可能出问题的五个。每一条已在对应任务里加了测试步骤：

1. **一个 action 里塞了多条语句。** GLM 可能把 `UPDATE …; DELETE …;` 放进一个 `sql` 字段。`check.py` 要用 `sqlparse.split` 拆开逐条执行，模板和行数按拆开后的语句算。→ Task 7 的 `test_multi_statement_action_is_split`。
2. **字面量里带引号、Unicode、前后空格。** `'O''Brien'`、`'José'`、数字 `3.50` 对 `3.5`。字面量检查按去掉外层引号、SQL 转义还原、大小写不敏感、NFKD 归一后比较；数字按 `float` 相等比较。→ Task 7 的 `test_literal_quotes_unicode_numbers`。
3. **锚点行没有子表行。** `person_named` 锚点允许没有 down 表（"改我的工资"）。建树时 down 为空不是错误，树照样产出；出题时类型 2、3 因为没有 up 表被跳过。→ Task 2 的 `test_person_without_children_still_builds_tree`。
4. **GLM 的 `<answer>` 不是合法 JSON 或缺字段。** 带 ```` ```json ```` 围栏、尾随说明文字、`actions` 里的元素是字符串而不是 `{"sql": …}`。解析失败要记录进输出文件（带 `error`），不能抛异常中断整批。→ Task 6 的 `test_parse_answer_variants` 和 `test_generate_records_parse_error_and_continues`。
5. **API 限速。** Coding Plan endpoint 返回 429 或 5xx 时要退避重试，重试用尽才记错误；不能把一个 429 变成整批失败。→ Task 4 的 `test_retries_on_429_then_succeeds`、`test_gives_up_after_max_retries`。

## 文件结构

| 文件 | 职责 |
|---|---|
| `dysql_bench/db_select.py`（改） | `evaluate()` 多返回 `fks_usable` |
| `scripts/select_dbs.py`（改） | 锚点 JSON 改成 `{key: {source, db, path, anchors, fks}}` |
| `dysql_bench/taskgen/__init__.py` | 空 |
| `dysql_bench/taskgen/io.py` | JSONL 读写、`done_ids`、`.env` 加载、`db_rec` 读取 |
| `dysql_bench/taskgen/trees.py` | 外键边、scope 核对、锚点行抽样、建树 |
| `dysql_bench/taskgen/schema.py` | DDL、BIRD 列说明、库描述（LLM 一次，缓存） |
| `dysql_bench/taskgen/llm.py` | `ChatClient`、`pmap` |
| `dysql_bench/taskgen/prompt.py` | 类型/难度/形状抽样、SYSTEM/USER 组装 |
| `dysql_bench/taskgen/examples.json` | 手写 few-shot |
| `dysql_bench/taskgen/generate.py` | 调 GLM、解析 `<answer>`、写候选 |
| `dysql_bench/taskgen/check.py` | 执行检查、字面量检查、scope 检查、类型 / 难度 / 模板 |
| `dysql_bench/taskgen/verify.py` | 校验 prompt、投票、解析 |
| `dysql_bench/taskgen/verify_wiki.md` | DySQL 的 agent policy 文本（校验 prompt 用） |
| `dysql_bench/taskgen/dedup.py` | 封顶去重 |
| `dysql_bench/taskgen/convert.py` | 写 `tasks.jsonl` 和 `manifest.json` |
| `dysql_bench/taskgen/stats.py` | 试点验收指标 |
| `dysql_bench/envs/gen/__init__.py`、`agent_policy_header.md` | `GenEnv` |
| `dysql_bench/envs/__init__.py`（改）、`run.py`（改） | `gen:<db>` 接入 |
| `scripts/taskgen.py` | CLI，子命令 = 步骤 |
| `scripts/calibrate_check.py` | 在 DySQL 1062 条上校准执行检查 |
| `scripts/serve_verifier.sh` | 起校验模型 |
| `scripts/taskgen_pilot.sh` | 试点一键脚本 |
| `tests/test_taskgen_*.py` | 每个模块一个测试文件 |

---

### Task 1: 锚点 JSON 自包含（路径 + 外键边）

**Files:**
- Modify: `DySQL-Bench/dysql_bench/db_select.py:259-311`（`evaluate`）
- Modify: `DySQL-Bench/scripts/select_dbs.py:103-105`
- Modify: `DySQL-Bench/tests/test_select_dbs_cli.py:19-22`
- Modify: `docs/2026-09-24-data-gen-db-selection.md:155`（字段说明）
- Regenerate: `docs/data_gen/candidate_anchors.json`

**Interfaces:**
- Produces: 锚点 JSON 的新形状，后面所有任务都读它：
  ```json
  {"bird:beer_factory": {"source": "bird", "db": "beer_factory", "path": "/abs/path/beer_factory.sqlite",
    "anchors": [ {table, key, kind, rows, names, down, up, update_targets} ],
    "fks": [ {"table": "transaction", "col": "CustomerID", "ref_table": "customers", "ref_col": "CustomerID", "hit": 1.0, "source": "declared"} ]}}
  ```
  `fks` 只含单列、有效（`hit` 为 `None` 或 ≥ 0.3）的外键。这个字典下文叫 `db_rec`。

- [ ] **Step 1: 改 CLI 测试，让它要求新形状**

把 `tests/test_select_dbs_cli.py` 第 19–22 行改成：

```python
    anchors = json.load(open(anc))
    assert list(anchors) == ["spider2:wwe"]
    rec = anchors["spider2:wwe"]
    assert rec["source"] == "spider2" and rec["db"] == "wwe" and rec["path"] == db
    w = next(a for a in rec["anchors"] if a["table"] == "Wrestlers")
    assert w["kind"] == "person_named" and w["down"] == ["Matches"]
    edges = {(f["table"], f["col"], f["ref_table"], f["ref_col"]) for f in rec["fks"]}
    assert ("Matches", "champion", "Wrestlers", "id") in edges     # from --fk-extra
    assert ("Matches", "winner_id", "Wrestlers", "id") in edges    # inferred by value
    assert all(f["hit"] is None or f["hit"] >= 0.3 for f in rec["fks"])
```

- [ ] **Step 2: 跑测试，确认失败**

Run: `cd DySQL-Bench && ~/miniconda3/envs/dysql/bin/python -m pytest -q tests/test_select_dbs_cli.py`
Expected: FAIL，`TypeError: list indices must be integers`（旧形状是列表）。

- [ ] **Step 3: `evaluate()` 多返回 `fks_usable`**

在 `db_select.py` 的 `evaluate()` 返回字典里、`"anchors": anc,` 一行后面加（`validate_fks` 已用 `_resolve_ref_cols` 把引用列解析成主键列；仍为空的外键这里过滤掉）：

```python
            "fks_usable": [{"table": f["table"], "col": f["cols"][0], "ref_table": f["ref_table"],
                            "ref_col": f["ref_cols"][0], "hit": f["hit"], "source": f["source"]}
                           for f in usable if len(f["cols"]) == 1 and f["ref_cols"] and f["ref_cols"][0]],
```

`COLS` 里没有这个键，CSV 不受影响。

- [ ] **Step 4: `select_dbs.py` 写新形状**

把第 103–105 行改成：

```python
    if a.anchors_json:
        with open(a.anchors_json, "w", encoding="utf-8") as f:
            json.dump({f"{r['source']}:{r['db']}": {"source": r["source"], "db": r["db"], "path": r["path"],
                                                     "anchors": r["anchors"], "fks": r["fks_usable"]}
                       for r in keep}, f, ensure_ascii=False, indent=1)
```

- [ ] **Step 5: 跑测试，确认通过**

Run: `cd DySQL-Bench && ~/miniconda3/envs/dysql/bin/python -m pytest -q tests/test_select_dbs_cli.py tests/test_db_select.py tests/test_db_anchor.py`
Expected: 全部 PASS。

- [ ] **Step 6: 重新生成 `candidate_anchors.json`**

Run（约 4 分钟，命令来自 `scripts/select_dbs.py` 开头的用法）:
```bash
cd DySQL-Bench && T=~/Documents/Isa/text2sql_bench
~/miniconda3/envs/dysql/bin/python scripts/select_dbs.py \
  --source "bird=$T/bird/train/train_databases/*/*.sqlite" --source "bird=$T/bird/dev/dev_databases/*/*.sqlite" \
  --source "spider2=$T/spider2_lite/sqlite/*.sqlite" --source "spider1=$T/spider1/test_database/*/*.sqlite" \
  --source "synsql=$T/synsql/databases/*/*.sqlite" \
  --holdout "spider1=$T/spider1/dev.json" --holdout "spider1=$T/spider1/test.json" \
  --fk-extra ../docs/data_gen/fk_extra.json \
  --out results/db_select/db_select_all.csv --candidates ../docs/data_gen/candidate_dbs.csv \
  --anchors-json ../docs/data_gen/candidate_anchors.json
git -C .. diff --stat docs/data_gen/candidate_dbs.csv
~/miniconda3/envs/dysql/bin/python -c "
import json; d=json.load(open('../docs/data_gen/candidate_anchors.json'))
print(len(d), sum(len(v['fks']) for v in d.values()), d['bird:beer_factory']['fks'][:2])"
```
Expected: `candidate_dbs.csv` 无 diff（规则没变）；打印 `55 <外键总数> [...]`，beer_factory 的 fks 里有 `transaction.CustomerID -> customers.CustomerID`。

- [ ] **Step 7: 更新选库文档的字段说明**

在 `docs/2026-09-24-data-gen-db-selection.md` 第 155 行附近（"给建树脚本的接口"一节）加一句：

```
   - 2026-09-28 起 JSON 的顶层是 `{"source:db": {source, db, path, anchors, fks}}`。`fks` 是单列有效外键的列对 `(table, col, ref_table, ref_col, hit, source)`，建树按它 join。
```

- [ ] **Step 8: Commit**

```bash
git add DySQL-Bench/dysql_bench/db_select.py DySQL-Bench/scripts/select_dbs.py DySQL-Bench/tests/test_select_dbs_cli.py docs/data_gen/candidate_anchors.json docs/2026-09-24-data-gen-db-selection.md
git commit -m "feat(select_dbs): anchors JSON carries the sqlite path and usable FK edges (tree-builder input)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: `taskgen/io.py` 与 `taskgen/trees.py`（建树）

**Files:**
- Create: `DySQL-Bench/dysql_bench/taskgen/__init__.py`（空文件）
- Create: `DySQL-Bench/dysql_bench/taskgen/io.py`
- Create: `DySQL-Bench/dysql_bench/taskgen/trees.py`
- Test: `DySQL-Bench/tests/test_taskgen_trees.py`

**Interfaces:**
- Consumes: Task 1 的 `db_rec`。
- Produces:
  - `io.read_jsonl(path) -> list[dict]`、`io.append_jsonl(path, records)`、`io.done_ids(path) -> set[str]`、`io.load_dotenv(path)`、`io.load_db_recs(json_path) -> dict[str, db_rec]`、`io.resolve_db_path(p)`。
  - `trees.fk_edges(fks) -> (down, up)`，`trees.check_scope(anchor, fks)`，`trees.anchor_key_values(conn, anchor, fks, rng, n) -> list`，`trees.build_tree(conn, anchor, fks, key_value, rng, max_down=15, max_up=3) -> dict | None`。
  - 树的形状：
    ```json
    {"anchor_table": "customers", "anchor_key": "customer_id", "key_value": 5, "anchor_name": "a5 b5",
     "anchor_row": {...}, "down": {"orders": [ {...}, ... ]}, "up": {"products": [ {...} ]}}
    ```

- [ ] **Step 1: 写测试**

`tests/test_taskgen_trees.py`：

```python
# tests/test_taskgen_trees.py
import random, sqlite3
import pytest
from tests._sqlite_fixtures import make_db, rows, SHOP
from dysql_bench.taskgen import trees

SHOP2 = SHOP + """
CREATE TABLE order_items (item_id INTEGER PRIMARY KEY, order_id INTEGER REFERENCES orders(order_id), note TEXT);
CREATE TABLE staff (staff_id INTEGER PRIMARY KEY, name TEXT);
""" + rows("order_items", 300, lambda i: f"{i},{i%100},'n{i}'") + rows("staff", 5, lambda i: f"{i},'s{i}'")

FKS = [{"table": "orders", "col": "customer_id", "ref_table": "customers", "ref_col": "customer_id", "hit": 1.0, "source": "declared"},
       {"table": "orders", "col": "product_id", "ref_table": "products", "ref_col": "product_id", "hit": 1.0, "source": "declared"},
       {"table": "order_items", "col": "order_id", "ref_table": "orders", "ref_col": "order_id", "hit": 1.0, "source": "declared"}]
CUSTOMER = {"table": "customers", "key": "customer_id", "kind": "person_named", "rows": 60,
            "names": ["first_name", "last_name"], "down": ["orders", "order_items"], "up": ["products"],
            "update_targets": ["customers", "orders", "order_items", "products"]}
STAFF = {"table": "staff", "key": "staff_id", "kind": "person_named", "rows": 5, "names": ["name"],
         "down": [], "up": [], "update_targets": ["staff"]}


@pytest.fixture
def conn(tmp_path):
    c = sqlite3.connect(make_db(tmp_path, "shop2", SHOP2)); yield c; c.close()


def test_check_scope_accepts_matching_record_and_rejects_wrong_one():
    trees.check_scope(CUSTOMER, FKS)
    with pytest.raises(ValueError, match="scope from fks"):
        trees.check_scope({**CUSTOMER, "down": ["orders"]}, FKS)


def test_build_tree_joins_two_hops_and_collects_parents(conn):
    t = trees.build_tree(conn, CUSTOMER, FKS, 5, random.Random(0))
    assert t["anchor_name"] == "a5 b5" and t["anchor_row"]["customer_id"] == 5
    assert sorted(o["order_id"] for o in t["down"]["orders"]) == [5, 65]          # i % 60 == 5
    assert {i["order_id"] for i in t["down"]["order_items"]} == {5, 65}          # joined through orders, not customers
    assert [p["product_id"] for p in t["up"]["products"]] == [5]                  # referenced by the customer's orders


def test_build_tree_caps_child_rows(conn):
    t = trees.build_tree(conn, CUSTOMER, FKS, 5, random.Random(0), max_down=1)
    assert len(t["down"]["orders"]) == 1 and len(t["down"]["order_items"]) == 1


def test_build_tree_returns_none_for_missing_key(conn):
    assert trees.build_tree(conn, CUSTOMER, FKS, 999, random.Random(0)) is None


def test_person_without_children_still_builds_tree(conn):
    t = trees.build_tree(conn, STAFF, FKS, 2, random.Random(0))
    assert t["anchor_name"] == "s2" and t["down"] == {} and t["up"] == {}
    assert sorted(trees.anchor_key_values(conn, STAFF, FKS, random.Random(0), 10)) == [0, 1, 2, 3, 4]


def test_anchor_key_values_only_rows_with_children(conn):
    conn.execute("DELETE FROM orders WHERE customer_id = 7"); conn.commit()
    vals = trees.anchor_key_values(conn, CUSTOMER, FKS, random.Random(0), 100)
    assert 7 not in vals and len(vals) == 59


def test_blob_values_are_json_safe(conn):
    conn.execute("UPDATE customers SET first_name = x'00ff' WHERE customer_id = 5"); conn.commit()
    t = trees.build_tree(conn, CUSTOMER, FKS, 5, random.Random(0))
    assert t["anchor_row"]["first_name"] == "<blob 2 bytes>"
```

- [ ] **Step 2: 跑测试，确认失败**

Run: `cd DySQL-Bench && ~/miniconda3/envs/dysql/bin/python -m pytest -q tests/test_taskgen_trees.py`
Expected: FAIL，`ModuleNotFoundError: No module named 'dysql_bench.taskgen'`。

- [ ] **Step 3: 写 `io.py`**

```python
# dysql_bench/taskgen/io.py
"""JSONL records, resume bookkeeping, .env loading, and the anchors JSON (db_rec) for the task-generation pipeline."""
import json, os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # DySQL-Bench/
REPO = os.path.dirname(ROOT)                                                          # repo root (.env, docs/)
DATA_ROOT = os.path.expanduser(os.environ.get("TEXT2SQL_BENCH", "~/Documents/Isa/text2sql_bench"))


def read_jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def append_jsonl(path, records):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")


def done_ids(path):
    return {r["id"] for r in read_jsonl(path) if "id" in r}


def load_dotenv(path=os.path.join(REPO, ".env")):
    """KEY=VALUE lines into os.environ (existing variables win). No python-dotenv dependency."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def resolve_db_path(p):
    """Absolute sqlite path: as given if absolute, else relative to TEXT2SQL_BENCH."""
    return p if os.path.isabs(p) else os.path.join(DATA_ROOT, p)


def load_db_recs(path=os.path.join(REPO, "docs", "data_gen", "candidate_anchors.json")):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def person_anchors(db_rec):
    return [a for a in db_rec["anchors"] if a["kind"] == "person_named"]
```

- [ ] **Step 4: 写 `trees.py`**

```python
# dysql_bench/taskgen/trees.py
"""Anchor trees: for one anchor row, the rows in its scope. Down tables are reached by joining FK edges
(two hops go through the intermediate table); up tables hold the parent rows the tree references
(the 'public' data a task may also edit). The scope recomputed from the edges must equal the anchor record."""
import json, sqlite3
from collections import deque
from dysql_bench.db_select import _q
from dysql_bench.db_anchor import reachable_down, parents


def fk_edges(fks):
    """down: parent -> [(child, child_col, parent_col)]; up: child -> [(child_col, parent, parent_col)]."""
    down, up = {}, {}
    for f in fks:
        if f["table"] == f["ref_table"]:
            continue
        down.setdefault(f["ref_table"], []).append((f["table"], f["col"], f["ref_col"]))
        up.setdefault(f["table"], []).append((f["col"], f["ref_table"], f["ref_col"]))
    return down, up


def check_scope(anchor, fks, max_hops=2):
    edges = [{"table": f["table"], "ref_table": f["ref_table"]} for f in fks]
    down = reachable_down(edges, anchor["table"], max_hops)
    up = parents(edges, [anchor["table"]] + down)
    if sorted(down) != sorted(anchor["down"]) or sorted(up) != sorted(anchor["up"]):
        raise ValueError(f"{anchor['table']}: scope from fks down={sorted(down)} up={sorted(up)} "
                         f"!= record down={sorted(anchor['down'])} up={sorted(anchor['up'])}")


def _safe(v):
    return f"<blob {len(v)} bytes>" if isinstance(v, (bytes, memoryview)) else v


def _rows(c, sql, params=()):
    cur = c.execute(sql, params)
    cols = [d[0] for d in cur.description]
    return [{k: _safe(v) for k, v in zip(cols, r)} for r in cur.fetchall()]


def _in(c, table, col, values):
    out = []
    for i in range(0, len(values), 500):
        chunk = values[i:i + 500]
        out += _rows(c, f'SELECT * FROM {_q(table)} WHERE {_q(col)} IN ({",".join("?" * len(chunk))})', chunk)
    return out


def anchor_key_values(c, anchor, fks, rng, n):
    """Key values of anchor rows with at least one direct child row; every row when the anchor has no down table."""
    down_e, _ = fk_edges(fks)
    kids = [(child, ccol) for child, ccol, pcol in down_e.get(anchor["table"], [])
            if child in anchor["down"] and pcol == anchor["key"]]
    key = _q(anchor["key"])
    if kids:
        sub = " UNION ".join(f"SELECT {_q(ccol)} FROM {_q(child)}" for child, ccol in kids)
        sql = f"SELECT {key} FROM {_q(anchor['table'])} WHERE {key} IN ({sub})"
    else:
        sql = f"SELECT {key} FROM {_q(anchor['table'])}"
    vals = [r[0] for r in c.execute(sql) if r[0] is not None]
    rng.shuffle(vals)
    return vals[:n]


def build_tree(c, anchor, fks, key_value, rng, max_down=15, max_up=3):
    down_e, up_e = fk_edges(fks)
    root = _rows(c, f"SELECT * FROM {_q(anchor['table'])} WHERE {_q(anchor['key'])} = ?", (key_value,))
    if not root:
        return None
    row = root[0]
    tree = {"anchor_table": anchor["table"], "anchor_key": anchor["key"], "key_value": key_value,
            "anchor_name": " ".join(str(row[n]) for n in anchor["names"] if n in row and row[n] not in (None, "")),
            "anchor_row": row, "down": {}, "up": {}}
    frontier, seen = deque([(anchor["table"], [row])]), {anchor["table"]}
    while frontier:
        t, trows = frontier.popleft()
        for child, ccol, pcol in down_e.get(t, []):
            if child in seen or child not in anchor["down"]:
                continue
            vals = sorted({r[pcol] for r in trows if r.get(pcol) not in (None, "")}, key=str)
            got = _in(c, child, ccol, vals) if vals else []
            if len(got) > max_down:
                got = rng.sample(got, max_down)
            if got:
                tree["down"][child] = got
                seen.add(child)
                frontier.append((child, got))
    for t, trows in [(anchor["table"], [row])] + list(tree["down"].items()):
        for ccol, parent, pcol in up_e.get(t, []):
            if parent not in anchor["up"]:
                continue
            vals = sorted({r[ccol] for r in trows if r.get(ccol) not in (None, "")}, key=str)[:max_up]
            if vals:
                tree["up"].setdefault(parent, []).extend(_in(c, parent, pcol, vals))
    for p, rs in tree["up"].items():
        uniq = {json.dumps(r, sort_keys=True, default=str): r for r in rs}
        tree["up"][p] = list(uniq.values())[:max_up]
    return tree


def open_ro(path):
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)
```

- [ ] **Step 5: 跑测试，确认通过**

Run: `cd DySQL-Bench && ~/miniconda3/envs/dysql/bin/python -m pytest -q tests/test_taskgen_trees.py`
Expected: 7 passed。

- [ ] **Step 6: 在 beer_factory 上冒烟**

Run:
```bash
cd DySQL-Bench && ~/miniconda3/envs/dysql/bin/python -c "
import random, json
from dysql_bench.taskgen import io, trees
rec = io.load_db_recs()['bird:beer_factory']; a = io.person_anchors(rec)[0]
trees.check_scope(a, rec['fks'])
c = trees.open_ro(io.resolve_db_path(rec['path']))
kv = trees.anchor_key_values(c, a, rec['fks'], random.Random(0), 3)
t = trees.build_tree(c, a, rec['fks'], kv[0], random.Random(0))
print(t['anchor_name'], {k: len(v) for k, v in t['down'].items()}, {k: len(v) for k, v in t['up'].items()})"
```
Expected: 打印一个客户名，down 里 `transaction` 和/或 `rootbeerreview` 的行数，up 里 `rootbeerbrand`、`rootbeer`、`location` 的行数（各 ≤ 3）。没有异常。

- [ ] **Step 7: Commit**

```bash
git add DySQL-Bench/dysql_bench/taskgen/__init__.py DySQL-Bench/dysql_bench/taskgen/io.py DySQL-Bench/dysql_bench/taskgen/trees.py DySQL-Bench/tests/test_taskgen_trees.py
git commit -m "feat(taskgen): anchor trees from the anchors JSON (FK joins, two-hop children, parent rows)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: `taskgen/schema.py`（DDL、列说明、库描述）

**Files:**
- Create: `DySQL-Bench/dysql_bench/taskgen/schema.py`
- Create: `docs/data_gen/db_descriptions.json`（由 CLI 生成，人工过一遍，进 git）
- Test: `DySQL-Bench/tests/test_taskgen_schema.py`

**Interfaces:**
- Produces: `schema.ddl(db_path) -> str`；`schema.column_descriptions(db_path) -> dict[table][col] = str`；`schema.schema_block(db_path) -> str`（DDL 加 `## Column notes`）；`schema.describe_db(db_key, db_path, client, cache_path) -> str`。
- `client` 只需要一个方法 `chat(messages, temperature=..., max_tokens=...) -> {"content": str, ...}`（Task 4 的 `ChatClient` 满足；测试用假对象）。

- [ ] **Step 1: 写测试**

```python
# tests/test_taskgen_schema.py
import json, os
from tests._sqlite_fixtures import make_db, SHOP
from dysql_bench.taskgen import schema


class FakeClient:
    def __init__(self): self.calls = 0
    def chat(self, messages, **kw):
        self.calls += 1
        return {"content": "A small web shop: customers place orders for products.", "usage": {}}


def test_ddl_lists_every_user_table(tmp_path):
    d = schema.ddl(make_db(tmp_path, "shop", SHOP))
    assert d.count("CREATE TABLE") == 3 and "sqlite_" not in d


def test_column_descriptions_from_bird_csvs(tmp_path):
    db = make_db(tmp_path, "shop", SHOP)
    dd = tmp_path / "database_description"; dd.mkdir()
    (dd / "customers.csv").write_text("original_column_name,column_name,column_description,data_format,value_description\n"
                                      "customer_id,customer id,the unique id,integer,\n"
                                      "first_name,first name,given name,text,\n", encoding="utf-8-sig")
    cd = schema.column_descriptions(db)
    assert cd == {"customers": {"customer_id": "the unique id", "first_name": "given name"}}
    block = schema.schema_block(db)
    assert "CREATE TABLE customers" in block and "customers.first_name: given name" in block


def test_column_descriptions_absent_for_spider(tmp_path):
    assert schema.column_descriptions(make_db(tmp_path, "shop", SHOP)) == {}


def test_describe_db_calls_llm_once_and_caches(tmp_path):
    db = make_db(tmp_path, "shop", SHOP); cache = tmp_path / "desc.json"; client = FakeClient()
    a = schema.describe_db("test:shop", db, client, str(cache))
    b = schema.describe_db("test:shop", db, client, str(cache))
    assert a == b == "A small web shop: customers place orders for products." and client.calls == 1
    assert json.load(open(cache)) == {"test:shop": a}
```

- [ ] **Step 2: 跑测试，确认失败**

Run: `cd DySQL-Bench && ~/miniconda3/envs/dysql/bin/python -m pytest -q tests/test_taskgen_schema.py`
Expected: FAIL，`ImportError: cannot import name 'schema'`。

- [ ] **Step 3: 写 `schema.py`**

```python
# dysql_bench/taskgen/schema.py
"""What the generation prompt says about a database: DDL, BIRD's per-column notes, and a one-paragraph description."""
import csv, glob, json, os, sqlite3

DESCRIBE_PROMPT = """Below is the DDL of a SQLite database{notes}. In two or three English sentences, say what this
database is about, who the people in it are (which tables hold persons, e.g. customers, employees, players) and what
the main transactional or fact tables record. Plain prose, no bullet points, no table names in quotes.

{ddl}"""


def ddl(db_path):
    c = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return "\n".join(r[0] for r in c.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND sql IS NOT NULL ORDER BY rowid"))
    finally:
        c.close()


def column_descriptions(db_path):
    """BIRD ships <db dir>/database_description/<table>.csv; Spider databases have none -> {}."""
    out = {}
    for f in sorted(glob.glob(os.path.join(os.path.dirname(db_path), "database_description", "*.csv"))):
        table = os.path.splitext(os.path.basename(f))[0]
        with open(f, encoding="utf-8-sig", errors="replace", newline="") as fh:
            for r in csv.DictReader(fh):
                col = (r.get("original_column_name") or "").strip()
                desc = " ".join(x for x in [(r.get("column_description") or "").strip(),
                                            (r.get("value_description") or "").strip()] if x)
                if col and desc:
                    out.setdefault(table, {})[col] = desc
    return out


def schema_block(db_path):
    text = ddl(db_path)
    cd = column_descriptions(db_path)
    if cd:
        notes = "\n".join(f"- {t}.{c}: {d}" for t, cols in cd.items() for c, d in cols.items())
        text += "\n\n## Column notes\n" + notes
    return text


def describe_db(db_key, db_path, client, cache_path):
    cache = json.load(open(cache_path, encoding="utf-8")) if os.path.exists(cache_path) else {}
    if db_key in cache:
        return cache[db_key]
    cd = column_descriptions(db_path)
    notes = " and the column notes that follow it" if cd else ""
    body = schema_block(db_path)
    text = client.chat([{"role": "user", "content": DESCRIBE_PROMPT.format(notes=notes, ddl=body)}],
                       temperature=0.3, max_tokens=1024)["content"].strip()
    cache[db_key] = text
    os.makedirs(os.path.dirname(os.path.abspath(cache_path)), exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=1)
    return text
```

- [ ] **Step 4: 跑测试，确认通过**

Run: `cd DySQL-Bench && ~/miniconda3/envs/dysql/bin/python -m pytest -q tests/test_taskgen_schema.py`
Expected: 4 passed。

- [ ] **Step 5: Commit**

```bash
git add DySQL-Bench/dysql_bench/taskgen/schema.py DySQL-Bench/tests/test_taskgen_schema.py
git commit -m "feat(taskgen): DDL, BIRD column notes and cached LLM database descriptions

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

（`docs/data_gen/db_descriptions.json` 在 Task 12 的 `describe` 子命令跑过之后才生成，那时再提交。）

---

### Task 4: `taskgen/llm.py`（OpenAI 兼容客户端，重试，并发）

**Files:**
- Create: `DySQL-Bench/dysql_bench/taskgen/llm.py`
- Test: `DySQL-Bench/tests/test_taskgen_llm.py`

**Interfaces:**
- Produces:
  - `llm.ChatClient(base_url, api_key, model, session=None, timeout=600, max_retries=6, backoff=2.0)`，方法 `chat(messages, temperature=1.0, max_tokens=8192, top_p=None, extra=None) -> {"content": str, "reasoning": str, "usage": dict, "model": str}`。失败重试用尽抛 `llm.LLMError`。
  - `llm.client_from_env(role)`：`role` 是 `"GEN"` 或 `"VERIFY"`，读 `TASKGEN_<ROLE>_BASE_URL / API_KEY / MODEL`（先 `io.load_dotenv()`）。
  - `llm.pmap(fn, items, workers) -> list`：线程池，保持顺序，每项返回 `fn(item)` 的结果或异常对象（不抛出）。

- [ ] **Step 1: 写测试**

```python
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
```

- [ ] **Step 2: 跑测试，确认失败**

Run: `cd DySQL-Bench && ~/miniconda3/envs/dysql/bin/python -m pytest -q tests/test_taskgen_llm.py`
Expected: FAIL，`ImportError: cannot import name 'llm'`。

- [ ] **Step 3: 写 `llm.py`**

```python
# dysql_bench/taskgen/llm.py
"""OpenAI-compatible chat client (requests, like the rest of the repo) with backoff and a thread-pool map."""
import os, random, time
from concurrent.futures import ThreadPoolExecutor
import requests
from dysql_bench.taskgen import io

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
                    body = r.json()
                    msg = body["choices"][0]["message"]
                    return {"content": msg.get("content") or "", "reasoning": msg.get("reasoning_content") or "",
                            "usage": body.get("usage") or {}, "model": body.get("model") or self.model}
                last = f"HTTP {r.status_code}: {r.text[:300]}"
                if r.status_code not in RETRY_STATUS:
                    raise LLMError(last)
            if attempt < self.max_retries:
                time.sleep(min(60.0, self.backoff * (2 ** attempt)) * (1 + random.random() * 0.25))
        raise LLMError(f"gave up after {self.max_retries + 1} attempts; last: {last}")


def client_from_env(role):
    io.load_dotenv()
    p = f"TASKGEN_{role.upper()}_"
    missing = [k for k in ("BASE_URL", "API_KEY", "MODEL") if not os.environ.get(p + k)]
    if missing:
        raise LLMError(f"missing env {', '.join(p + k for k in missing)} (see .env)")
    return ChatClient(os.environ[p + "BASE_URL"], os.environ[p + "API_KEY"], os.environ[p + "MODEL"])


def pmap(fn, items, workers):
    def safe(x):
        try:
            return fn(x)
        except Exception as e:  # keep the batch alive; the caller records the exception
            return e
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        return list(ex.map(safe, items))
```

- [ ] **Step 4: 跑测试，确认通过**

Run: `cd DySQL-Bench && ~/miniconda3/envs/dysql/bin/python -m pytest -q tests/test_taskgen_llm.py`
Expected: 6 passed。

- [ ] **Step 5: 真实 endpoint 冒烟（一次调用）**

Run: `cd DySQL-Bench && ~/miniconda3/envs/dysql/bin/python -c "
from dysql_bench.taskgen import llm
c = llm.client_from_env('GEN'); r = c.chat([{'role':'user','content':'Reply with exactly: OK'}], temperature=0, max_tokens=256)
print(repr(r['content']), r['usage'])"`
Expected: 打印 `'OK'` 和 usage 字典。

- [ ] **Step 6: Commit**

```bash
git add DySQL-Bench/dysql_bench/taskgen/llm.py DySQL-Bench/tests/test_taskgen_llm.py
git commit -m "feat(taskgen): OpenAI-compatible chat client with backoff, env config and a thread-pool map

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: `taskgen/prompt.py` 与 `examples.json`（类型、难度、形状、消息组装）

**Files:**
- Create: `DySQL-Bench/dysql_bench/taskgen/prompt.py`
- Create: `DySQL-Bench/dysql_bench/taskgen/examples.json`
- Test: `DySQL-Bench/tests/test_taskgen_prompt.py`

**Interfaces:**
- Consumes: Task 2 的树；`db_rec`。
- Produces:
  - `prompt.CFG`：`TYPE_MIX`、`DIFFICULTY_MIX`、`FREE_TABLE_SHARE`、`MAX_ROWS_PER_STMT = 50`。
  - `prompt.feasible_types(tree, anchor, others) -> list[str]`。
  - `prompt.sample_plan(rng, tree, anchor, others, cfg=CFG) -> dict`：
    ```json
    {"task_type": "1_self", "difficulty": "medium",
     "shape": {"n_writes": 2, "n_tables": 1, "ownership_subquery": true, "archive": false, "public_table": false},
     "write_tables": ["orders"] | null, "other": {"table": "customers", "key_value": 9, "name": "a9 b9"} | null,
     "example": "<few-shot instruction>"}
    ```
  - `prompt.build_messages(db_rec, anchor, tree, plan, db_description, schema_text) -> list[dict]`（SYSTEM + USER）。
  - `prompt.load_examples() -> dict[type, list[str]]`。
- `others`：同一人物表里其他行的 `{"key_value", "name"}` 列表（Task 6 从 `anchor_key_values` 里多抽几个得到）。

- [ ] **Step 1: 写测试**

```python
# tests/test_taskgen_prompt.py
import random
from collections import Counter
from dysql_bench.taskgen import prompt

ANCHOR = {"table": "customers", "key": "customer_id", "kind": "person_named", "rows": 60, "names": ["first_name", "last_name"],
          "down": ["orders"], "up": ["products"], "update_targets": ["customers", "orders", "products"]}
DB = {"source": "test", "db": "shop", "path": "x", "anchors": [ANCHOR], "fks": []}
TREE = {"anchor_table": "customers", "anchor_key": "customer_id", "key_value": 5, "anchor_name": "a5 b5",
        "anchor_row": {"customer_id": 5, "first_name": "a5", "last_name": "b5"},
        "down": {"orders": [{"order_id": 5, "customer_id": 5, "product_id": 5, "qty": 1}]},
        "up": {"products": [{"product_id": 5, "name": "p5", "price": 1.0}]}}
OTHERS = [{"key_value": 9, "name": "a9 b9"}]


def test_examples_cover_every_type_with_at_least_two():
    ex = prompt.load_examples()
    assert set(ex) == set(prompt.CFG["TYPE_MIX"]) and all(len(v) >= 2 for v in ex.values())


def test_feasible_types_need_up_rows_and_others():
    assert prompt.feasible_types(TREE, ANCHOR, OTHERS) == ["1_self", "2_self_and_public", "3_public_only", "4_other_person", "5_proxy"]
    assert prompt.feasible_types({**TREE, "up": {}}, ANCHOR, []) == ["1_self", "5_proxy"]


def test_sample_plan_follows_the_mix_and_shapes():
    rng = random.Random(0)
    plans = [prompt.sample_plan(rng, TREE, ANCHOR, OTHERS) for _ in range(4000)]
    types, diffs = Counter(p["task_type"] for p in plans), Counter(p["difficulty"] for p in plans)
    assert abs(types["1_self"] / 4000 - 0.46) < 0.04 and abs(types["5_proxy"] / 4000 - 0.29) < 0.04
    assert abs(diffs["hard"] / 4000 - 0.29) < 0.04
    assert abs(sum(p["write_tables"] is None for p in plans) / 4000 - 0.30) < 0.04
    for p in plans:
        s = p["shape"]
        if p["difficulty"] == "easy" and p["task_type"] != "2_self_and_public":   # type 2 always needs two tables
            assert s["n_writes"] == 1 and s["n_tables"] == 1 and not s["ownership_subquery"] and not s["archive"]
        if p["difficulty"] == "hard":
            assert s["n_writes"] >= 2 and s["n_tables"] >= 2
        if p["task_type"] == "4_other_person":
            assert p["other"] == OTHERS[0]
        if p["task_type"] in ("2_self_and_public", "3_public_only"):
            assert s["public_table"]
        assert p["example"] in prompt.load_examples()[p["task_type"]]


def test_build_messages_names_data_blocks_and_type_text():
    plan = {"task_type": "5_proxy", "difficulty": "medium", "example": "EX",
            "shape": {"n_writes": 2, "n_tables": 1, "ownership_subquery": True, "archive": False, "public_table": False},
            "write_tables": ["orders"], "other": None}
    msgs = prompt.build_messages(DB, ANCHOR, TREE, plan, "A shop.", "CREATE TABLE customers (...)")
    assert msgs[0]["role"] == "system" and "## Instruction Example\nEX" in msgs[0]["content"]
    u = msgs[1]["content"]
    assert "## customers record" in u and "## orders records" in u and "## products records (shared" in u
    assert "NOT in the database" in u and "a5 b5" in u and "customer_id = 5" in u
    assert "exactly 2 write statements" in u and "subquery" in u and "Write to these tables: orders" in u
    assert "CREATE TABLE customers" in u and "A shop." in u


def test_build_messages_free_tables_and_other_person():
    plan = {"task_type": "4_other_person", "difficulty": "easy", "example": "EX",
            "shape": {"n_writes": 1, "n_tables": 1, "ownership_subquery": False, "archive": False, "public_table": False},
            "write_tables": None, "other": OTHERS[0]}
    u = prompt.build_messages(DB, ANCHOR, TREE, plan, "A shop.", "DDL")[1]["content"]
    assert "ANOTHER person: a9 b9 (customer_id = 9)" in u and "Choose freely" in u
```

- [ ] **Step 2: 跑测试，确认失败**

Run: `cd DySQL-Bench && ~/miniconda3/envs/dysql/bin/python -m pytest -q tests/test_taskgen_prompt.py`
Expected: FAIL，`ImportError: cannot import name 'prompt'`。

- [ ] **Step 3: 写 `examples.json`（手写 few-shot，每类 3 条，场景避开候选库和 DySQL 的库）**

```json
{
  "1_self": [
    "Hi, this is Marta Kowalczyk, member number 4471 at the Riverside Gym. I signed up for the Tuesday 7pm spin class (booking 90213) but I can't make it anymore. Please cancel that booking and switch my membership plan from 'Standard' to 'Off-Peak' starting next month.",
    "My name is Daniel Osei and my patient ID is P-30982. The pharmacy has my phone number wrong on prescription RX-55120. Please update the contact phone on that prescription to 020-7946-0233 and mark the prescription as 'ready for collection'.",
    "I'm Yuki Tanaka (account 88123, email yuki.t@example.jp). I returned the two lamps from order 7731 yesterday. Please set the status of order 7731 to 'returned' and change the quantity of the lamp line in that order from 2 to 0."
  ],
  "2_self_and_public": [
    "This is Ahmed Haddad, library card 20194. I'm returning 'The Glass Hotel' (loan 66102) today, so please close that loan with return date 2024-03-18. Also, the catalogue lists that book under 'Science Fiction' but it's literary fiction; please change the book's genre to 'Literary Fiction'.",
    "Hello, Priya Raman here, customer 5120. Cancel my reservation 3390 for the 18:30 table, and while you're at it the restaurant's listed phone number on the venue record is out of date, it should be 0161 555 0170.",
    "I'm Lars Nygaard, driver ID 812 with the courier company. Please mark my delivery DL-44018 as 'delivered' and correct the depot record for depot 3: its postcode should be N1 9GU, not N1 9GT."
  ],
  "3_public_only": [
    "My name is Chloe Martin, I'm registered as supplier contact 217. The product 'Oak Dining Chair' (SKU OAK-CH-04) is listed at 89.00 but our new wholesale price is 94.50. Please update the unit price on that product.",
    "Hi, I'm Tomás Ferreira, staff ID 44 at the clinic. Room 12 is shown as 'Consultation' in the rooms table but it has been converted to a treatment room. Please change its room type to 'Treatment'.",
    "This is Hannah Lee, guest 3021. The hotel's 'Deluxe King' room type still shows 2 max guests; it should be 3 now that the sofa beds are in. Please update that room type's max occupancy to 3."
  ],
  "4_other_person": [
    "I'm Sofia Bianchi, team manager (staff ID 17). Our new hire Marco Conti (employee 402) has been assigned to the wrong department. Please move him from department 5 to department 8 and set his start date to 2024-04-01.",
    "This is Grace Okafor, guardian of student 1187 (Emeka Okafor). Please update his emergency contact phone to 07700 900123 and withdraw him from the after-school chess club (enrolment 5561).",
    "Hi, Nikolai Petrov here, agent number 9 at the talent agency. My client Elena Vidal (performer 233) is raising her booking fee: set her rate to 850 and change her availability status to 'weekends only'."
  ],
  "5_proxy": [
    "Hello, I'm Rachel Green, a data analyst with the league office. Player Jonas Berg (player ID 5583) was listed with the wrong height; please update his height to 188 cm and his preferred foot to 'left'.",
    "This is Omar Siddiqui from the billing team. Customer Isabel Torres (customer 2210) was double-charged on invoice INV-90031. Please delete the duplicate payment record 41877 and set that invoice's balance to 0.",
    "I'm Wei Zhang, a records coordinator at the hospital. Patient Alan Reid (MRN 77120) has been discharged; please set his admission record 5502 to status 'discharged' with discharge date 2024-02-11 and free bed B-14 by marking it 'available'."
  ]
}
```

- [ ] **Step 4: 写 `prompt.py`**

```python
# dysql_bench/taskgen/prompt.py
"""Task plan sampling (type x difficulty x shape) and the generation prompt.
SYSTEM is DySQL's generation prompt (data_pipeline_shell/generate_sqlbench_multiTurn_qa.py) with one example
instruction chosen by task type; the USER message is built from the anchor tree, so the data blocks are named after
the real tables instead of the hand-edited 'User Data / Trading Data' headings."""
import json, os, random
from dysql_bench.db_select import _q

CFG = {
    "TYPE_MIX": {"1_self": 0.46, "2_self_and_public": 0.12, "3_public_only": 0.05, "4_other_person": 0.08, "5_proxy": 0.29},
    "DIFFICULTY_MIX": {"easy": 0.26, "medium": 0.45, "hard": 0.29},
    "FREE_TABLE_SHARE": 0.30,
    "MAX_ROWS_PER_STMT": 50,
}
EXAMPLES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "examples.json")

SYSTEM = """Generate a NEW task instruction that mimics realistic human users and their intentions, such as with different personality and goals. The task instruction should be followed by 'actions' which is a list of the sql to be taken to solve this task and 'outputs' which is a list of the answers to specific information requests made by the user. Think step by step to come up with the action(s) and the corresponding sql(s) translating this thought that would be necessary to fulfill the user's request or solve their intentions. The new user instruction should have all the parameters for the SQL calls in Actions.

## Guidelines for generating NEW task instruction and Groundtruth Actions
1. You must generate a new user instruction according to the <Input Database>.
2. The main focus is to generate actions that can modify the underlying database.
3. For actions that do not modify the database like specific information requests, scan the provided data directly and append only the answer in 'outputs'. Do not make separate sql calls for this in 'actions'.
4. Include multiple SQL calls when the scenario requires multiple steps or modifications. Put exactly one SQL statement in each action.
5. Provide precise SQL calls with all necessary parameters for each action according to the given Dataset Schema, and ALL the parameters should be explicitly given in the new user instruction.
6. Every UPDATE or DELETE must match at least one existing row of the provided data, and no single statement may change more than {max_rows} rows.
7. Write standard SQLite. Quote identifiers that contain spaces or punctuation with double quotes.

## Principles for generating SQL calls
- At the beginning of the conversation, you have to authenticate the user identity by locating their user.
- Once the user has been authenticated, you can provide the user with information, e.g. help the user look up order id.
- You can only help one user per conversation (but you can handle multiple requests from the same user), and must deny any requests for tasks related to any other user.
- You should not make up any information or knowledge or procedures not provided from the user, or give subjective recommendations or comments.
- You should at most make one sql call at a time, and if you take a sql call, you should not respond to the user at the same time. If you respond to the user, you should not make a sql call.
- You should transfer the user to a human agent if and only if the request cannot be handled within the scope of your actions.

## Output Format
Generate your response according to the following <Instruction Example> and <Format Example> format. Enclose the thought process within '<thought></thought>' tags, and the final structured response within '<answer></answer>' tags. The structured response should be in strict JSON format, without any additional comments or explanations.

## Instruction Example
{example_instruction}

## Format Example (only for reference)
{{
    "instruction": "...",
    "actions": [
        {{
            "sql": "..."
        }},
        {{
            "sql": "..."
        }}
    ],
    "outputs": []
}}

The new user instruction must have all the parameters for the SQL calls in Actions. Do not directly copy the instruction or the action patterns from the example. Ground the generation in the provided data."""

USER = """## Instructions
Generate a NEW task instruction that mimics realistic human users and their intentions, such as with different personality and goals. The task instruction should be followed by 'actions' which is a list of the sql to be taken to solve this task and 'outputs' which is a list of the answers to specific information requests made by the user. ALL SQL parameters in Actions MUST be explicitly given in the new user instruction.

# <Input Database>
{db_description}

{data_blocks}

## Dataset Schema
The available Dataset schema in DDL format is as follows:
{schema}

## Task type
{type_text}

## Task shape
{shape_text}

> Every literal value used in the SQL (ids, names, amounts, dates, new values) must appear verbatim in the instruction, except the values that identify the person's own row ({id_fields}), which the agent can look up.
> Each UPDATE/DELETE must match at least one row shown above; no statement may change more than {max_rows} rows.
> Confirm the generated instruction has all the parameters in the SQL calls. Generate the task now."""

TYPE_TEXT = {
    "1_self": "The speaker is {name} ({key} = {kv}), a person in table {t}. They introduce themselves by name (optionally with one identifying field such as an email or the {key}). Every write must change rows that belong to this person: their own row in {t} or rows in {down} linked to it.",
    "2_self_and_public": "The speaker is {name} ({key} = {kv}), a person in table {t}. The writes must change at least one row that belongs to this person AND at least one row in a shared table ({up}) that belongs to nobody (reference data such as products, brands, locations).",
    "3_public_only": "The speaker is {name} ({key} = {kv}), a person in table {t}. They introduce themselves by name, but the writes change ONLY rows in shared tables ({up}) that belong to nobody; the person's own rows stay unchanged.",
    "4_other_person": "The speaker is {name} ({key} = {kv}), a person in table {t}. The writes change rows belonging to ANOTHER person: {other_name} ({key} = {other_kv}) or rows in {down} linked to that person. Give a plausible reason for the authority (manager, agent, guardian, colleague).",
    "5_proxy": "The speaker is NOT in the database. Invent a realistic full name and a job role related to {t} (for example a data analyst, account manager, records coordinator). They introduce themselves with name and role, then ask to change the data of {name} ({key} = {kv}) or rows in {down} linked to that person. Do not pretend to be that person.",
}


def load_examples():
    with open(EXAMPLES_PATH, encoding="utf-8") as f:
        return json.load(f)


def _weighted(rng, weights):
    keys, w = zip(*weights.items())
    return rng.choices(keys, weights=w, k=1)[0]


def feasible_types(tree, anchor, others):
    out = ["1_self"]
    if tree["up"]:
        out += ["2_self_and_public", "3_public_only"]
    if others:
        out.append("4_other_person")
    out.append("5_proxy")
    return out


def _shape(rng, difficulty, task_type, tree):
    s = {"n_writes": 1, "n_tables": 1, "ownership_subquery": False, "archive": False,
         "public_table": task_type in ("2_self_and_public", "3_public_only")}
    n_scope = 1 + len(tree["down"]) + len(tree["up"])
    if difficulty == "medium":
        pick = rng.choice(["two_writes", "two_tables", "subquery"])
        if pick == "two_writes" or (pick == "two_tables" and n_scope < 2):
            s["n_writes"] = 2
        elif pick == "two_tables":
            s.update(n_writes=2, n_tables=2)
        else:
            s["ownership_subquery"] = True
    elif difficulty == "hard":
        s.update(n_writes=rng.choice([2, 3]), n_tables=2 if n_scope >= 2 else 1, ownership_subquery=True)
        if rng.random() < 0.25 and tree["down"]:
            s["archive"] = True
    if s["public_table"] and s["n_tables"] < 2 and task_type == "2_self_and_public":
        s.update(n_writes=max(s["n_writes"], 2), n_tables=2)
    return s


def sample_plan(rng, tree, anchor, others, cfg=CFG):
    ok = feasible_types(tree, anchor, others)
    task_type = _weighted(rng, {k: v for k, v in cfg["TYPE_MIX"].items() if k in ok})
    difficulty = _weighted(rng, cfg["DIFFICULTY_MIX"])
    shape = _shape(rng, difficulty, task_type, tree)
    scope = [anchor["table"]] + list(tree["down"]) + list(tree["up"])
    if task_type == "3_public_only":
        pool = list(tree["up"])
    elif task_type == "2_self_and_public":
        pool = [anchor["table"]] + list(tree["down"])
    else:
        pool = [anchor["table"]] + list(tree["down"])
    free = rng.random() < cfg["FREE_TABLE_SHARE"]
    write_tables = None
    if not free:
        k = min(shape["n_tables"], len(pool)) if task_type != "2_self_and_public" else min(shape["n_tables"] - 1, len(pool))
        write_tables = rng.sample(pool, max(1, k))
        if task_type == "2_self_and_public":
            write_tables.append(rng.choice(list(tree["up"])))
    other = rng.choice(others) if task_type == "4_other_person" else None
    return {"task_type": task_type, "difficulty": difficulty, "shape": shape, "write_tables": write_tables,
            "other": other, "example": rng.choice(load_examples()[task_type]), "scope": scope}


def _block(title, rows):
    return f"## {title}\n" + "\n".join(json.dumps(r, ensure_ascii=False, default=str) for r in rows)


def data_blocks(anchor, tree, plan):
    who = "the speaker's own row" if plan["task_type"] != "5_proxy" else "the person the request is about"
    blocks = [_block(f"{anchor['table']} record ({who})", [tree["anchor_row"]])]
    blocks += [_block(f"{t} records", rs) for t, rs in tree["down"].items()]
    blocks += [_block(f"{t} records (shared reference data, owned by nobody)", rs) for t, rs in tree["up"].items()]
    if plan.get("other"):
        blocks.append(_block(f"Another person in {anchor['table']}", [{anchor["key"]: plan["other"]["key_value"], "name": plan["other"]["name"]}]))
    return "\n\n".join(blocks)


def shape_text(anchor, tree, plan):
    s, lines = plan["shape"], []
    lines.append(f"- Use exactly {s['n_writes']} write statement{'s' if s['n_writes'] > 1 else ''} (INSERT/UPDATE/DELETE) touching {s['n_tables']} distinct table{'s' if s['n_tables'] > 1 else ''}.")
    if s["ownership_subquery"]:
        lines.append(f"- Locate the rows to change through their owner with a subquery on {anchor['table']} (e.g. WHERE {anchor['key']} = (SELECT {anchor['key']} FROM {anchor['table']} WHERE ...)) instead of hard-coding the {anchor['key']}.")
    if s["archive"]:
        lines.append("- First copy the affected row(s) into another table in scope with INSERT ... SELECT, then change or delete the original row(s).")
    if s["public_table"]:
        lines.append(f"- At least one write must change a shared table: {', '.join(tree['up'])}.")
    scope = [anchor["table"]] + list(tree["down"]) + list(tree["up"])
    if plan["write_tables"]:
        lines.append(f"- Write to these tables: {', '.join(plan['write_tables'])}.")
    else:
        lines.append(f"- Choose freely which tables in scope to write ({', '.join(scope)}); prefer a combination that is not the obvious one.")
    lines.append(f"- Target difficulty: {plan['difficulty']}. Read-only questions (if any) go into 'outputs', not 'actions'.")
    return "\n".join(lines)


def build_messages(db_rec, anchor, tree, plan, db_description, schema_text, cfg=CFG):
    fmt = {"name": tree["anchor_name"] or f"the row with {anchor['key']} = {tree['key_value']}", "key": anchor["key"],
           "kv": tree["key_value"], "t": anchor["table"], "down": ", ".join(tree["down"]) or "(none)",
           "up": ", ".join(tree["up"]) or "(none)",
           "other_name": (plan.get("other") or {}).get("name", ""), "other_kv": (plan.get("other") or {}).get("key_value", "")}
    user = USER.format(db_description=db_description, data_blocks=data_blocks(anchor, tree, plan), schema=schema_text,
                       type_text=TYPE_TEXT[plan["task_type"]].format(**fmt), shape_text=shape_text(anchor, tree, plan),
                       id_fields=", ".join(anchor["names"] + [anchor["key"]]), max_rows=cfg["MAX_ROWS_PER_STMT"])
    system = SYSTEM.format(example_instruction=plan["example"], max_rows=cfg["MAX_ROWS_PER_STMT"])
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]
```

- [ ] **Step 5: 跑测试，确认通过**

Run: `cd DySQL-Bench && ~/miniconda3/envs/dysql/bin/python -m pytest -q tests/test_taskgen_prompt.py`
Expected: 5 passed。如果 `test_sample_plan_follows_the_mix_and_shapes` 的比例断言差在 0.04 边缘，把样本数从 4000 提到 8000，不放宽阈值。

- [ ] **Step 6: Commit**

```bash
git add DySQL-Bench/dysql_bench/taskgen/prompt.py DySQL-Bench/dysql_bench/taskgen/examples.json DySQL-Bench/tests/test_taskgen_prompt.py
git commit -m "feat(taskgen): task plan sampling (type, difficulty, shape) and the generation prompt

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: `taskgen/generate.py`（调出题模型，解析，写候选）

**Files:**
- Create: `DySQL-Bench/dysql_bench/taskgen/generate.py`
- Test: `DySQL-Bench/tests/test_taskgen_generate.py`

**Interfaces:**
- Consumes: `trees.build_tree`、`prompt.sample_plan`、`prompt.build_messages`、`llm.ChatClient.chat`、`io.append_jsonl`、`io.done_ids`。
- Produces:
  - `generate.parse_answer(text) -> dict`，返回 `{"instruction": str, "actions": [{"sql": str}, ...], "outputs": list}`；失败抛 `generate.ParseError`。
  - `generate.make_candidate(db_rec, anchor, tree, plan, resp) -> dict`。
  - `generate.run(db_rec, anchor, trees_list, others, client, out_path, rng, workers=8, cfg=prompt.CFG) -> dict(stats)`。
  - 候选记录（`candidates.jsonl` 每行）：
    ```json
    {"id": "bird:beer_factory:customers:17:0", "db": "beer_factory", "source": "bird", "anchor_table": "customers",
     "anchor_key": "CustomerID", "key_value": 17, "anchor_name": "…", "plan": {…},
     "instruction": "…", "actions": [{"sql": "…"}], "outputs": [], "gen_model": "glm-5.3", "usage": {…},
     "raw": "<thought>…</thought><answer>…</answer>", "error": null}
    ```
    解析失败的记录 `instruction` 为 `null`，`error` 写原因。`id` 末尾的序号是这棵树的第几次出题。

- [ ] **Step 1: 写测试**

```python
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
```

- [ ] **Step 2: 跑测试，确认失败**

Run: `cd DySQL-Bench && ~/miniconda3/envs/dysql/bin/python -m pytest -q tests/test_taskgen_generate.py`
Expected: FAIL，`ImportError: cannot import name 'generate'`。

- [ ] **Step 3: 写 `generate.py`**

```python
# dysql_bench/taskgen/generate.py
"""Call the generation model once per (tree, plan) and write candidate tasks. Parse failures and API failures are
recorded as candidates with instruction=None so the batch never stops and the failure rate is visible."""
import json, re
from dysql_bench.taskgen import io, llm, prompt

GEN_TEMPERATURE, GEN_TOP_P, GEN_MAX_TOKENS = 1.0, 0.95, 16384


class ParseError(ValueError):
    pass


def _json_candidates(text):
    m = re.search(r"<answer>(.*?)(</answer>|$)", text, re.S)
    body = m.group(1) if m else text
    body = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", body.strip(), flags=re.S)
    yield body
    for mm in reversed(list(re.finditer(r"\{.*\}", text, re.S))):   # greedy last {...}
        yield mm.group(0)
    depth, start = 0, None                                             # balanced scan for the last object
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0: start = i
            depth += 1
        elif ch == "}" and depth:
            depth -= 1
            if depth == 0 and start is not None:
                yield text[start:i + 1]


def parse_answer(text):
    last = None
    for cand in _json_candidates(text or ""):
        try:
            obj = json.loads(cand)
        except json.JSONDecodeError as e:
            last = e; continue
        if not isinstance(obj, dict):
            continue
        ins = (obj.get("instruction") or "").strip()
        acts = obj.get("actions")
        if not ins or not isinstance(acts, list) or not acts:
            raise ParseError("missing/empty instruction or actions")
        norm = []
        for a in acts:
            sql = a.get("sql") if isinstance(a, dict) else a
            if not isinstance(sql, str) or not sql.strip():
                raise ParseError("action without sql")
            norm.append({"sql": sql.strip()})
        return {"instruction": ins, "actions": norm, "outputs": obj.get("outputs") or []}
    raise ParseError(f"no JSON object with instruction/actions: {last}")


def make_candidate(db_rec, anchor, tree, plan, idx, resp, parsed, error):
    return {"id": f"{db_rec['source']}:{db_rec['db']}:{anchor['table']}:{tree['key_value']}:{idx}",
            "db": db_rec["db"], "source": db_rec["source"], "anchor_table": anchor["table"], "anchor_key": anchor["key"],
            "key_value": tree["key_value"], "anchor_name": tree["anchor_name"], "plan": plan,
            "instruction": parsed["instruction"] if parsed else None, "actions": parsed["actions"] if parsed else None,
            "outputs": parsed["outputs"] if parsed else None,
            "gen_model": (resp or {}).get("model"), "usage": (resp or {}).get("usage"),
            "raw": (resp or {}).get("content"), "error": error}


def run(db_rec, anchor, trees_list, others, client, out_path, rng, workers=8, per_tree=1, cfg=prompt.CFG,
        db_description="", schema_text=""):
    done = io.done_ids(out_path)
    jobs = []
    for tree in trees_list:
        for idx in range(per_tree):
            cid = f"{db_rec['source']}:{db_rec['db']}:{anchor['table']}:{tree['key_value']}:{idx}"
            if cid in done:
                continue
            plan = prompt.sample_plan(rng, tree, anchor, [o for o in others if o["key_value"] != tree["key_value"]], cfg)
            jobs.append((tree, idx, plan))

    def one(job):
        tree, idx, plan = job
        msgs = prompt.build_messages(db_rec, anchor, tree, plan, db_description, schema_text, cfg)
        return client.chat(msgs, temperature=GEN_TEMPERATURE, max_tokens=GEN_MAX_TOKENS, top_p=GEN_TOP_P)

    stats = {"written": 0, "errors": 0, "skipped": len(trees_list) * per_tree - len(jobs)}
    for job, resp in zip(jobs, llm.pmap(one, jobs, workers)):
        tree, idx, plan = job
        parsed, error = None, None
        if isinstance(resp, Exception):
            error, resp = f"{type(resp).__name__}: {resp}", None
        else:
            try:
                parsed = parse_answer(resp["content"])
            except ParseError as e:
                error = f"ParseError: {e}"
        stats["errors"] += bool(error)
        io.append_jsonl(out_path, [make_candidate(db_rec, anchor, tree, plan, idx, resp, parsed, error)])
        stats["written"] += 1
    return stats
```

- [ ] **Step 4: 跑测试，确认通过**

Run: `cd DySQL-Bench && ~/miniconda3/envs/dysql/bin/python -m pytest -q tests/test_taskgen_generate.py`
Expected: 4 passed。

- [ ] **Step 5: Commit**

```bash
git add DySQL-Bench/dysql_bench/taskgen/generate.py DySQL-Bench/tests/test_taskgen_generate.py
git commit -m "feat(taskgen): generation step with robust <answer> parsing and resumable candidate output

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: `taskgen/check.py`（执行检查、字面量、scope、类型 / 难度 / 模板）

**Files:**
- Create: `DySQL-Bench/dysql_bench/taskgen/check.py`
- Test: `DySQL-Bench/tests/test_taskgen_check.py`

**Interfaces:**
- Consumes: Task 6 的候选记录；`db_rec`（anchors、fks、path）。
- Produces:
  - `check.run_check(db_rec, cand, anchor=None, cfg=prompt.CFG) -> dict`：
    ```json
    {"id": "...", "ok": true, "reasons": [],
     "writes": [{"op": "UPDATE", "table": "orders", "rows": 1, "label": "own"}],
     "task_type": "1_self", "template": "1_self|UPDATE orders",
     "difficulty": {"score": 0, "level": "easy", "features": {"multi_write": false, "multi_table": false, "subquery": false, "archive": false, "public_or_other": false}}}
    ```
    `anchor` 为 `None` 时按 `cand["anchor_table"]` 从 `db_rec` 里找。`cand["plan"]["task_type"]` 决定说话人是否在库里（`5_proxy` 不在）；没有 `plan` 时（DySQL 校准）由 `cand["speaker_in_db"]` 决定。
  - `check.split_statements(sql) -> list[str]`、`check.write_target(stmt) -> (op, table) | None`、`check.literals(stmt) -> list[str]`、`check.norm_literal(s) -> str`。
  - 失败原因字符串前缀：`no_instruction`、`no_actions`、`sql_error:`、`no_write`、`noop_write:`、`bulk:`、`out_of_scope:`、`literal_missing:`。
- 说明：类型标签算法照搬 `scripts/classify_dysql_tasks.py` 的 `trace / task_group`：写到的行沿外键向上追到人物表（≤ 3 跳），相对锚点标为 own / other / public；说话人不在库里时标 person_obj / public。

- [ ] **Step 1: 写测试**

```python
# tests/test_taskgen_check.py
import sqlite3
import pytest
from tests._sqlite_fixtures import make_db, SHOP, rows
from tests.test_taskgen_trees import SHOP2, FKS, CUSTOMER
from dysql_bench.taskgen import check

STAFF_ANCHOR = {"table": "staff", "key": "staff_id", "kind": "person_named", "rows": 5, "names": ["name"],
                "down": [], "up": [], "update_targets": ["staff"]}


@pytest.fixture
def db(tmp_path):
    path = make_db(tmp_path, "shop2", SHOP2)
    return {"source": "test", "db": "shop2", "path": path, "anchors": [CUSTOMER, STAFF_ANCHOR], "fks": FKS}


def cand(instruction, sqls, task_type="1_self", key_value=5):
    return {"id": "t", "anchor_table": "customers", "anchor_key": "customer_id", "key_value": key_value,
            "plan": {"task_type": task_type}, "instruction": instruction, "actions": [{"sql": s} for s in sqls]}


AUTH = "SELECT * FROM customers WHERE first_name = 'a5' AND last_name = 'b5'"


def test_good_task_passes_with_labels_template_and_difficulty(db):
    r = check.run_check(db, cand("I am a5 b5 (customer 5). Set the qty of my order 5 to 3.",
                                 [AUTH, "UPDATE orders SET qty = 3 WHERE order_id = 5 AND customer_id = 5"]))
    assert r["ok"] and r["reasons"] == []
    assert r["writes"] == [{"op": "UPDATE", "table": "orders", "rows": 1, "label": "own"}]
    assert r["task_type"] == "1_self" and r["template"] == "1_self|UPDATE orders"
    assert r["difficulty"] == {"score": 0, "level": "easy", "features": {"multi_write": False, "multi_table": False,
                                                                          "subquery": False, "archive": False, "public_or_other": False}}


def test_literal_missing_fails_but_anchor_values_are_allowed(db):
    r = check.run_check(db, cand("I am a5 b5. Set the qty of my order 5 to 3.",
                                 [AUTH, "UPDATE orders SET qty = 4 WHERE order_id = 5 AND customer_id = 5"]))
    assert not r["ok"] and r["reasons"] == ["literal_missing: '4' in UPDATE orders"]
    r = check.run_check(db, cand("I am a5 b5. Set the qty of order 5 to 3.",   # customer_id 5 not in the text: it's the anchor key
                                 ["UPDATE orders SET qty = 3 WHERE order_id = 5 AND customer_id = 5"]))
    assert r["ok"]


def test_literal_quotes_unicode_numbers(db):
    ins = "I'm a5 b5. Rename product 5 to O'Brien Café and set its price to 3.50."
    r = check.run_check(db, cand(ins, ["UPDATE products SET name = 'O''Brien Café', price = 3.5 WHERE product_id = 5"]))
    assert r["ok"], r["reasons"]


def test_noop_bulk_error_and_no_write(db):
    assert check.run_check(db, cand("set qty to 1 on order 999", ["UPDATE orders SET qty = 1 WHERE order_id = 999"]))["reasons"] == ["noop_write: UPDATE orders"]
    assert check.run_check(db, cand("qty 1", ["UPDATE orders SET qty = 1"]))["reasons"][0].startswith("bulk: 100 rows in UPDATE orders")
    assert check.run_check(db, cand("x", ["UPDATE nope SET a = 1"]))["reasons"][0].startswith("sql_error:")
    assert check.run_check(db, cand("x", [AUTH]))["reasons"] == ["no_write"]
    assert check.run_check(db, {**cand("x", [AUTH]), "instruction": None})["reasons"] == ["no_instruction"]


def test_out_of_scope_table(db):
    r = check.run_check(db, cand("I am a5 b5. Rename staff 2 to Zed.", ["UPDATE staff SET name = 'Zed' WHERE staff_id = 2"]))
    assert r["reasons"] == ["out_of_scope: staff"]


def test_multi_statement_action_is_split(db):
    r = check.run_check(db, cand("I am a5 b5. Set qty of order 5 to 3 and delete order 65.",
                                 ["UPDATE orders SET qty = 3 WHERE order_id = 5; DELETE FROM orders WHERE order_id = 65;"]))
    assert r["ok"] and [w["op"] for w in r["writes"]] == ["UPDATE", "DELETE"] and r["template"] == "1_self|DELETE orders+UPDATE orders"
    assert r["difficulty"]["features"]["multi_write"] and r["difficulty"]["level"] == "medium"


def test_types_public_other_and_proxy(db):
    r = check.run_check(db, cand("I am a5 b5. Set price of product 5 to 2.0 and qty of order 5 to 3.",
                                 ["UPDATE products SET price = 2.0 WHERE product_id = 5", "UPDATE orders SET qty = 3 WHERE order_id = 5"]))
    assert r["task_type"] == "2_self_and_public" and r["difficulty"]["features"]["public_or_other"] and r["difficulty"]["level"] == "hard"
    r = check.run_check(db, cand("I am a5 b5. Set qty of order 9 to 3.", ["UPDATE orders SET qty = 3 WHERE order_id = 9"]))
    assert r["task_type"] == "4_other_person" and r["writes"][0]["label"] == "other"
    r = check.run_check(db, cand("I am Pat, an analyst. Set qty of order 5 to 3.", ["UPDATE orders SET qty = 3 WHERE order_id = 5"], task_type="5_proxy"))
    assert r["task_type"] == "5_proxy" and r["writes"][0]["label"] == "person_obj"


def test_subquery_and_archive_features(db):
    r = check.run_check(db, cand("I am a5 b5. Set qty of my order 5 to 3.",
                                 ["UPDATE orders SET qty = 3 WHERE order_id = 5 AND customer_id = (SELECT customer_id FROM customers WHERE first_name = 'a5' AND last_name = 'b5')"]))
    assert r["ok"] and r["difficulty"]["features"]["subquery"]
    r = check.run_check(db, cand("I am a5 b5. Archive order item 5 as a note copy then delete it.",
                                 ["INSERT INTO order_items (order_id, note) SELECT order_id, note FROM order_items WHERE item_id = 5",
                                  "DELETE FROM order_items WHERE item_id = 5"]))
    assert r["ok"] and r["difficulty"]["features"]["archive"]


def test_source_db_is_untouched(db):
    check.run_check(db, cand("I am a5 b5. Set qty of my order 5 to 3.", ["UPDATE orders SET qty = 3 WHERE order_id = 5"]))
    c = sqlite3.connect(db["path"])
    assert c.execute("SELECT qty FROM orders WHERE order_id = 5").fetchone()[0] == 1
```

- [ ] **Step 2: 跑测试，确认失败**

Run: `cd DySQL-Bench && ~/miniconda3/envs/dysql/bin/python -m pytest -q tests/test_taskgen_check.py`
Expected: FAIL，`ImportError: cannot import name 'check'`。

- [ ] **Step 3: 写 `check.py`**

```python
# dysql_bench/taskgen/check.py
"""Execution check of a candidate task on an in-memory copy of its database, plus the derived labels
(task type, difficulty, template) that dedup and the pilot statistics use. Nothing here calls a model."""
import json, re, sqlite3, unicodedata
import sqlparse
from sqlparse import tokens as T
from dysql_bench.db_select import _q
from dysql_bench.taskgen import prompt, trees

WRITE = re.compile(r"(?is)^\s*(insert|update|delete|replace)\b")
TARGET = re.compile(r'(?is)^\s*(?:insert\s+(?:or\s+\w+\s+)?into|replace\s+into|update(?:\s+or\s+\w+)?|delete\s+from)\s+'
                    r'(?:"([^"]+)"|\[([^\]]+)\]|`([^`]+)`|([\w$]+))')
SUBQ = re.compile(r"(?is)\(\s*select\b")
INS_SEL = re.compile(r"(?is)^\s*insert\b.*?\bselect\b")


def split_statements(sql):
    return [s.strip().rstrip(";").strip() for s in sqlparse.split(sql or "") if s.strip().rstrip(";").strip()]


def write_target(stmt):
    m = TARGET.match(stmt)
    if not m:
        return None
    op = stmt.split(None, 1)[0].upper()
    return ("INSERT" if op == "REPLACE" else op), next(g for g in m.groups() if g)


def norm_literal(s):
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", s).strip().lower()


def literals(stmt):
    out = []
    for tok in sqlparse.parse(stmt)[0].flatten():
        if tok.ttype in T.Literal.String.Single:
            out.append(tok.value[1:-1].replace("''", "'"))
        elif tok.ttype in T.Literal.Number:
            out.append(tok.value)
    return out


def _num(s):
    try:
        return float(str(s).replace(",", ""))
    except ValueError:
        return None


def literal_ok(lit, instruction, allowed):
    n = norm_literal(lit)
    if not n or n in allowed:
        return True
    text = norm_literal(instruction)
    if n in text:
        return True
    v = _num(lit)
    if v is not None:
        if any(_num(a) == v for a in allowed):
            return True
        return any(_num(m) == v for m in re.findall(r"-?\d[\d,]*\.?\d*", text))
    return False


class Tracer:
    """Owner lookup for written rows: child -> parent along FK edges (<= 3 hops) to the person tables."""

    def __init__(self, db_rec, conn):
        self.conn = conn
        _, self.up = trees.fk_edges(db_rec["fks"])
        self.persons = {a["table"]: a["key"] for a in db_rec["anchors"] if a["kind"].startswith("person")}
        self.tables = {a["table"].lower(): a["table"] for a in db_rec["anchors"]}
        self.tables.update({f[k].lower(): f[k] for f in db_rec["fks"] for k in ("table", "ref_table")})

    def canon(self, table):
        return self.tables.get(table.lower(), table)

    def trace(self, table, row, depth=0, acc=None):
        acc = set() if acc is None else acc
        if table in self.persons:
            v = row.get(self.persons[table])
            if v is not None:
                acc.add((table, str(v)))
        if depth >= 3:
            return acc
        for col, parent, pcol in self.up.get(table, []):
            v = row.get(col)
            if v in (None, ""):
                continue
            try:
                cur = self.conn.execute(f"SELECT * FROM {_q(parent)} WHERE {_q(pcol)} = ? LIMIT 3", (v,))
            except sqlite3.Error:
                continue
            cols = [d[0] for d in cur.description]
            for r in cur.fetchall():
                self.trace(parent, dict(zip(cols, r)), depth + 1, acc)
        return acc


def task_group(speaker_in_db, labels):
    core = sorted({x for x in labels if x not in ("noop",)})
    if not core:
        return "7_no_change"
    pattern = "+".join(core)
    if speaker_in_db:
        return {"own": "1_self", "own+public": "2_self_and_public", "public": "3_public_only"}.get(pattern, "4_other_person")
    return "5_proxy" if "person_obj" in pattern else "6_entity"


def difficulty(writes, task_type, stmts):
    f = {"multi_write": len(writes) >= 2, "multi_table": len({w["table"] for w in writes}) >= 2,
         "subquery": any(SUBQ.search(s) for s in stmts), "archive": any(INS_SEL.match(s) for s in stmts),
         "public_or_other": task_type in ("2_self_and_public", "4_other_person")}
    score = sum(f.values())
    return {"score": score, "level": "easy" if score == 0 else "medium" if score <= 2 else "hard", "features": f}


def _memory_copy(path):
    src = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    db = sqlite3.connect(":memory:", isolation_level=None)
    src.backup(db); src.close()
    return db


def run_check(db_rec, cand, anchor=None, cfg=prompt.CFG):
    out = {"id": cand.get("id"), "ok": False, "reasons": [], "writes": [], "task_type": None, "template": None, "difficulty": None}
    if not cand.get("instruction"):
        out["reasons"].append("no_instruction"); return out
    if not cand.get("actions"):
        out["reasons"].append("no_actions"); return out
    anchor = anchor or next(a for a in db_rec["anchors"] if a["table"] == cand["anchor_table"])
    scope = {anchor["table"], *anchor["down"], *anchor["up"]}
    speaker_in_db = (cand.get("plan") or {}).get("task_type", "1_self") != "5_proxy" if "plan" in cand else cand.get("speaker_in_db", True)
    db = _memory_copy(db_rec["path"])
    tracer = Tracer(db_rec, db)
    row = db.execute(f"SELECT * FROM {_q(anchor['table'])} WHERE {_q(anchor['key'])} = ?", (cand["key_value"],)).fetchone()
    allowed = {norm_literal(v) for v in (row or ()) if v not in (None, "")}
    anchor_id = (anchor["table"], str(cand["key_value"]))
    # capture pre-update FK/key values, like classify_dysql_tasks.py: 'move my order to product 9' is still 'own'
    db.execute("CREATE TEMP TABLE _old (tbl TEXT, j TEXT)")
    for t in scope:
        need = {c for c, _, _ in tracer.up.get(t, [])} | ({tracer.persons[t]} if t in tracer.persons else set())
        if need:
            obj = ", ".join(f"'{c}', OLD.{_q(c)}" for c in sorted(need))
            db.execute(f"CREATE TEMP TRIGGER {_q('_u_' + t)} BEFORE UPDATE ON main.{_q(t)} BEGIN "
                       f"INSERT INTO _old VALUES ('{t}', json_object({obj})); END")
    stmts, labels = [], []
    db.execute("BEGIN")
    try:
        for a in cand["actions"]:
            for st in split_statements(a["sql"]):
                wt = write_target(st) if WRITE.match(st) else None
                try:
                    if not wt:
                        db.execute(st).fetchall(); continue
                    cur = db.execute(st + " RETURNING *")
                    rcols = [d[0] for d in cur.description]
                    rs = cur.fetchall()
                except sqlite3.Error as e:
                    out["reasons"].append(f"sql_error: {e} in {st[:80]}"); continue
                op, table = wt[0], tracer.canon(wt[1])
                stmts.append(st)
                if table not in scope:
                    out["reasons"].append(f"out_of_scope: {table}")
                for lit in literals(st):
                    if not literal_ok(lit, cand["instruction"], allowed):
                        out["reasons"].append(f"literal_missing: '{lit}' in {op} {table}"); break
                owners = set()
                for r in rs[:50]:
                    owners |= tracer.trace(table, dict(zip(rcols, r)))
                for (j,) in db.execute("SELECT j FROM _old WHERE tbl = ? LIMIT 50", (table,)).fetchall():
                    owners |= tracer.trace(table, json.loads(j))
                db.execute("DELETE FROM _old")
                if not rs:
                    lab = "noop"
                    if op != "INSERT":
                        out["reasons"].append(f"noop_write: {op} {table}")
                elif speaker_in_db:
                    lab = "own" if anchor_id in owners else ("other" if owners else "public")
                else:
                    lab = "person_obj" if owners else "public"
                if len(rs) > cfg["MAX_ROWS_PER_STMT"]:
                    out["reasons"].append(f"bulk: {len(rs)} rows in {op} {table}")
                labels.append(lab)
                out["writes"].append({"op": op, "table": table, "rows": len(rs), "label": lab})
    finally:
        db.execute("ROLLBACK"); db.close()
    if not out["writes"]:
        out["reasons"].append("no_write")
    elif all(w["rows"] == 0 for w in out["writes"]):
        out["reasons"].append("no_write")
    out["task_type"] = task_group(speaker_in_db, labels) if out["writes"] else None
    if out["task_type"]:
        out["template"] = out["task_type"] + "|" + "+".join(sorted(f"{w['op']} {w['table']}" for w in out["writes"]))
        out["difficulty"] = difficulty(out["writes"], out["task_type"], stmts)
    out["ok"] = not out["reasons"]
    return out
```

- [ ] **Step 4: 跑测试，确认通过**

Run: `cd DySQL-Bench && ~/miniconda3/envs/dysql/bin/python -m pytest -q tests/test_taskgen_check.py`
Expected: 10 passed。`test_multi_statement_action_is_split` 里 DELETE 的 `65` 要出现在 instruction 里（已写 "delete order 65"）。

- [ ] **Step 5: Commit**

```bash
git add DySQL-Bench/dysql_bench/taskgen/check.py DySQL-Bench/tests/test_taskgen_check.py
git commit -m "feat(taskgen): execution check with literal/scope rules and derived type, difficulty, template

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: 在 DySQL 的 1062 条任务上校准执行检查

**Files:**
- Create: `DySQL-Bench/scripts/calibrate_check.py`
- Create: `docs/data_gen/2026-09-28-check-calibration.md`（脚本输出，人工加两句结论）
- Test: `DySQL-Bench/tests/test_taskgen_check_dysql.py`

**Interfaces:**
- Consumes: `check.run_check`（`anchor` 参数、`speaker_in_db` 字段）；`docs/data_gen/dysql_task_types.csv`（`env, idx, group, speaker, speaker_ids`）；`db_select.profile_db / all_fks`、`db_anchor.update_targets / anchors`（构造 DySQL 库的 `db_rec`）。
- Produces: `calibrate_check.dysql_db_rec(env) -> db_rec`、`calibrate_check.dysql_candidates(env) -> list[cand]`（每条带 `speaker_in_db`、`group`、`anchor_table`、`key_value`；说话人不在库里或匹配到多个人物时，锚点取写入表 scope 内的第一个人物锚点，`key_value` 取 `None`）。
- 说明：`key_value=None` 时 `run_check` 里 `row` 为空，`allowed` 只剩空集；scope 检查仍按锚点算。这是校准所需，生成的候选永远有 `key_value`。

- [ ] **Step 1: 写测试（快速子集）**

```python
# tests/test_taskgen_check_dysql.py
"""Calibration of check.py on DySQL's own gold tasks (spec §7): outside the known no-op class, >= 90% must pass.
The full 13-env report is scripts/calibrate_check.py; this test runs two small envs so it stays fast."""
import importlib.util, os
from collections import Counter
from dysql_bench.taskgen import check

_SPEC = importlib.util.spec_from_file_location("calibrate_check", os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "calibrate_check.py"))
cc = importlib.util.module_from_spec(_SPEC); _SPEC.loader.exec_module(cc)


def test_chinook_and_music_gold_tasks_mostly_pass():
    total, ok, reasons = 0, 0, Counter()
    for env in ("chinook", "music"):
        rec = cc.dysql_db_rec(env)
        for cand in cc.dysql_candidates(env):
            if cand["group"] == "7_no_change":
                continue
            r = check.run_check(rec, cand)
            total += 1; ok += r["ok"]
            for x in r["reasons"]:
                reasons[x.split(":")[0]] += 1
    assert total >= 60 and ok / total >= 0.85, (ok, total, reasons.most_common())
```

- [ ] **Step 2: 跑测试，确认失败**

Run: `cd DySQL-Bench && ~/miniconda3/envs/dysql/bin/python -m pytest -q tests/test_taskgen_check_dysql.py`
Expected: FAIL，`FileNotFoundError`（`scripts/calibrate_check.py` 还不存在，`exec_module` 读不到文件）。

- [ ] **Step 3: 写 `scripts/calibrate_check.py`**

```python
#!/usr/bin/env python3
"""Run taskgen.check on DySQL-Bench's 1062 gold tasks and report the pass rate outside class 7 (spec §7: >= 90%).
Usage (from DySQL-Bench/):
  ~/miniconda3/envs/dysql/bin/python scripts/calibrate_check.py --out ../docs/data_gen/2026-09-28-check-calibration.md"""
import argparse, csv, glob, importlib, os, sys
from collections import Counter, defaultdict
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from dysql_bench.db_select import profile_db, all_fks, row_key
from dysql_bench.db_anchor import update_targets, anchors
from dysql_bench.taskgen import check

TYPES_CSV = os.path.join(os.path.dirname(ROOT), "docs", "data_gen", "dysql_task_types.csv")
ENVS = sorted(os.path.basename(os.path.dirname(os.path.dirname(f))) for f in glob.glob(f"{ROOT}/dysql_bench/envs/*/data/*.sqlite"))


def dysql_db_rec(env):
    path = glob.glob(f"{ROOT}/dysql_bench/envs/{env}/data/*.sqlite")[0]
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


def dysql_candidates(env):
    tasks = importlib.import_module(f"dysql_bench.envs.{env}.tasks_test").TASKS_TEST
    rec = dysql_db_rec(env)
    meta = _rows(env)
    out = []
    for i, t in enumerate(tasks):
        m = meta[i]
        ids = [x for x in m["speaker_ids"].split(";") if ":" in x]
        anchor_table, kv = None, None
        if m["speaker"] == "db_person" and len(ids) == 1:
            anchor_table, kv = ids[0].split(":", 1)
            kv = int(kv) if kv.lstrip("-").isdigit() else kv
        if anchor_table is None or not any(a["table"] == anchor_table for a in rec["anchors"]):
            written = {w.split(" ", 1)[1].split(":")[0] for w in m["writes"].split(" | ") if " " in w}
            a = next((a for a in rec["anchors"] if written <= {a["table"], *a["down"], *a["up"]}), rec["anchors"][0])
            anchor_table, kv = a["table"], None
        out.append({"id": f"dysql:{env}:{i}", "anchor_table": anchor_table, "key_value": kv, "group": m["group"],
                    "speaker_in_db": m["speaker"] == "db_person", "instruction": t.instruction,
                    "actions": [{"sql": a.kwargs["sql"]} for a in t.actions if a.name == "sql"]})
    return out


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--out"); ap.add_argument("--env", action="append")
    a = ap.parse_args()
    lines = ["# 执行检查在 DySQL 1062 条任务上的校准", "", "| env | 非第7类任务 | 通过 | 通过率 | 主要失败原因 | 类型一致 | 难度 简单/中等/困难 |", "|---|---|---|---|---|---|---|"]
    T = O = agree = 0; levels = Counter(); all_reasons = Counter()
    for env in a.env or ENVS:
        rec = dysql_db_rec(env); n = ok = ag = 0; reasons = Counter(); lv = Counter()
        for cand in dysql_candidates(env):
            r = check.run_check(rec, cand)
            if cand["group"] == "7_no_change":
                continue
            n += 1; ok += r["ok"]; ag += (r["task_type"] == cand["group"])
            if r["difficulty"]: lv[r["difficulty"]["level"]] += 1
            for x in r["reasons"]: reasons[x.split(":")[0]] += 1
        T += n; O += ok; agree += ag; levels += lv; all_reasons += reasons
        lines.append(f"| {env} | {n} | {ok} | {ok / n:.0%} | {', '.join(f'{k} {v}' for k, v in reasons.most_common(3))} | {ag / n:.0%} | {lv['easy']}/{lv['medium']}/{lv['hard']} |")
    lines.append(f"| **合计** | {T} | {O} | **{O / T:.0%}** | {', '.join(f'{k} {v}' for k, v in all_reasons.most_common(4))} | {agree / T:.0%} | {levels['easy']}/{levels['medium']}/{levels['hard']} |")
    text = "\n".join(lines)
    print(text)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 跑测试**

Run: `cd DySQL-Bench && ~/miniconda3/envs/dysql/bin/python -m pytest -q tests/test_taskgen_check_dysql.py`
Expected: PASS。如果通过率低于 0.85，看 `reasons` 里最多的一项，按 spec §7 调规则（调 `check.py`，不调任务），常见的两种：
- `literal_missing` 占多数：多半是 gold SQL 用了 instruction 里以另一种写法出现的值（日期格式、大小写、千分位）。在 `literal_ok` 里加对应的归一化，加测试。
- `out_of_scope` 占多数：说话人匹配失败导致锚点选错。在 `dysql_candidates` 里改锚点选择（按写入表的 scope 匹配），不是改 `check.py`。

- [ ] **Step 5: 跑全量报告**

Run: `cd DySQL-Bench && ~/miniconda3/envs/dysql/bin/python scripts/calibrate_check.py --out ../docs/data_gen/2026-09-28-check-calibration.md`
Expected: 合计通过率 ≥ 90%；类型一致率 ≥ 85%（和 `dysql_task_types.csv` 的 `group` 比）；难度分布接近 26 / 45 / 29。不满足就回到 Step 4 调规则，改完重跑；在报告末尾手写两行：规则改了什么、最终数字。

- [ ] **Step 6: Commit**

```bash
git add DySQL-Bench/scripts/calibrate_check.py DySQL-Bench/tests/test_taskgen_check_dysql.py docs/data_gen/2026-09-28-check-calibration.md DySQL-Bench/dysql_bench/taskgen/check.py DySQL-Bench/tests/test_taskgen_check.py
git commit -m "test(taskgen): calibrate the execution check on DySQL's gold tasks (>= 90% pass outside class 7)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 9: `taskgen/verify.py`（LLM 校验，投票）

**Files:**
- Create: `DySQL-Bench/dysql_bench/taskgen/verify.py`
- Create: `DySQL-Bench/dysql_bench/taskgen/verify_wiki.md`（从 `data_pipeline_shell/verify_sql_wiki.md` 原样复制）
- Test: `DySQL-Bench/tests/test_taskgen_verify.py`

**Interfaces:**
- Consumes: 通过 `check` 的候选（候选记录 + `check` 结果）；`llm.ChatClient`。
- Produces:
  - `verify.build_messages(cand, ddl_text) -> list[dict]`。
  - `verify.parse_verdict(text) -> "yes" | "no" | "unparsed"`。
  - `verify.run(cands, client, out_path, votes=3, workers=4, ddl_text="") -> dict(stats)`。输出记录：
    ```json
    {"id": "...", "votes": [{"verdict": "yes", "content": "…", "reasoning_chars": 1234, "usage": {…}}], "yes": 2, "no": 1, "pass": true, "verify_model": "…"}
    ```
    重跑时：`id` 已有且票数 ≥ `votes` 的跳过；票数不足的补到 `votes`（记录整行重写：先读旧票，再追加新票，写到一个新文件后替换）。

- [ ] **Step 1: 写测试**

```python
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
    assert m[0]["role"] == "system" and "authenticate the user identity" in m[0]["content"]
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
```

- [ ] **Step 2: 跑测试，确认失败**

Run: `cd DySQL-Bench && ~/miniconda3/envs/dysql/bin/python -m pytest -q tests/test_taskgen_verify.py`
Expected: FAIL，`ImportError: cannot import name 'verify'`。

- [ ] **Step 3: 复制 wiki，写 `verify.py`**

Run: `cp data_pipeline_shell/verify_sql_wiki.md DySQL-Bench/dysql_bench/taskgen/verify_wiki.md`（在仓库根目录执行）。

```python
# dysql_bench/taskgen/verify.py
"""LLM verification by majority vote. The prompt is DySQL's verify_qa_voting_request.py with two added principles
(parameter completeness, solvability without seeing the SQL) and the DDL of the database in the user message."""
import json, os, re
from dysql_bench.taskgen import io, llm

VERIFY_TEMPERATURE, VERIFY_MAX_TOKENS = 1.2, 16384
WIKI = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "verify_wiki.md"), encoding="utf-8").read()
FINAL = "Verification: Is the answer correct (Yes/No)?"

SYSTEM = """Please help me to verify whether the assistant has solved the user's problem based on the provided user and assistant interactions.
The user has outlined specific requirements, and the assistant's response should address all of these needs.
The output should indicate whether the assistant has fully addressed the user's request, with a detailed check of the Agent Policy and assistant's sql call validity, correctness of invocation.

{domain_rules}

You have six principles to do this.
1. [Verification] The output should thoroughly verify whether the assistant's responses and tool calls have correctly addressed all of the user's requests step by step.
2. [SQL Call Accuracy] The output should check whether the assistant used the appropriate sql calls, with correct invocation and parameters, to solve the user's task.
3. [Consistency Check] The output should ensure that the data provided by the user is consistent throughout the interaction, without any discrepancies or hallucinations.
4. [Correctness] The verification should confirm if all of the user's requirements have been fully addressed and that no crucial aspect of the problem was overlooked.
5. [Completeness of parameters] Every value the SQL uses (ids, names, amounts, dates, new values) must be stated in the user's requirements, except values that identify the user's own record, which the assistant can look up after authentication.
6. [Solvability] A person who can only read the user's requirements and query the database, without seeing these SQL calls, must be able to arrive at exactly the same database changes.

## Response format
The response should include reasoning process step by step, and ending with: "Verification: Is the answer correct (Yes/No)?" followed by "Yes" or "No".
"""

USER = """Here is the user's requirements:
{user_requirements}

Here is the assistant's response (the SQL calls, in order):
{action_outputs}

Here is the database schema (DDL):
{ddl}
"""


def build_messages(cand, ddl_text):
    return [{"role": "system", "content": SYSTEM.format(domain_rules=WIKI)},
            {"role": "user", "content": USER.format(user_requirements=cand["instruction"],
                                                    action_outputs=json.dumps(cand["actions"], ensure_ascii=False, indent=1),
                                                    ddl=ddl_text)}]


def parse_verdict(text):
    if FINAL not in (text or ""):
        return "unparsed"
    tail = re.sub(r"[*_`\s]", "", text.split(FINAL)[-1]).lower()
    if tail.startswith("yes"):
        return "yes"
    if tail.startswith("no"):
        return "no"
    return "unparsed"


def _vote(client, msgs):
    r = client.chat(msgs, temperature=VERIFY_TEMPERATURE, max_tokens=VERIFY_MAX_TOKENS)
    return {"verdict": parse_verdict(r["content"]), "content": r["content"], "reasoning_chars": len(r.get("reasoning") or ""),
            "usage": r.get("usage")}


def _finish(rec, model):
    rec["yes"] = sum(v["verdict"] == "yes" for v in rec["votes"])
    rec["no"] = len(rec["votes"]) - rec["yes"]           # unparsed counts as no
    rec["pass"] = rec["yes"] > rec["no"]
    rec["verify_model"] = model
    return rec


def run(cands, client, out_path, votes=3, workers=4, ddl_text=""):
    existing = {r["id"]: r for r in io.read_jsonl(out_path)}
    todo = [(c, votes - len(existing.get(c["id"], {}).get("votes", []))) for c in cands]
    todo = [(c, n) for c, n in todo if n > 0]
    jobs = [(c, i) for c, n in todo for i in range(n)]
    results = llm.pmap(lambda j: _vote(client, build_messages(j[0], ddl_text)), jobs, workers)
    new_votes = {}
    for (c, _), r in zip(jobs, results):
        if isinstance(r, Exception):
            r = {"verdict": "unparsed", "content": f"{type(r).__name__}: {r}", "reasoning_chars": 0, "usage": None}
        new_votes.setdefault(c["id"], []).append(r)
    model = getattr(client, "model", None)
    updated, appended = {}, []
    for c, _ in todo:
        rec = existing.get(c["id"]) or {"id": c["id"], "votes": []}
        rec = _finish({**rec, "votes": rec["votes"] + new_votes.get(c["id"], [])}, model)
        if c["id"] in existing:
            updated[c["id"]] = rec
        else:
            appended.append(rec)
    if updated:  # rewrite the file with the topped-up records in place
        rows = [updated.get(r["id"], r) for r in io.read_jsonl(out_path)]
        tmp = out_path + ".tmp"
        if os.path.exists(tmp): os.remove(tmp)
        io.append_jsonl(tmp, rows); os.replace(tmp, out_path)
    io.append_jsonl(out_path, appended)
    return {"verified": len(todo), "passed": sum(r["pass"] for r in list(updated.values()) + appended),
            "skipped": len(cands) - len(todo)}
```

- [ ] **Step 4: 跑测试，确认通过**

Run: `cd DySQL-Bench && ~/miniconda3/envs/dysql/bin/python -m pytest -q tests/test_taskgen_verify.py`
Expected: 5 passed。

- [ ] **Step 5: Commit**

```bash
git add DySQL-Bench/dysql_bench/taskgen/verify.py DySQL-Bench/dysql_bench/taskgen/verify_wiki.md DySQL-Bench/tests/test_taskgen_verify.py
git commit -m "feat(taskgen): majority-vote LLM verification with DySQL's prompt plus parameter/solvability checks

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 10: `taskgen/dedup.py`（按人物行、模板、库封顶）

**Files:**
- Create: `DySQL-Bench/dysql_bench/taskgen/dedup.py`
- Test: `DySQL-Bench/tests/test_taskgen_dedup.py`

**Interfaces:**
- Consumes: 合并后的记录（候选 + `check` 结果 + `verify` 结果，Task 12 的 CLI 负责合并；这里只要求每条有 `id`、`anchor_table`、`key_value`、`template`）。
- Produces: `dedup.select(records, rng, per_person=2, per_template=15, per_db=600) -> list[dict]`。稀有模板优先（模板出现次数升序，同频随机），贪心过三个上限。

- [ ] **Step 1: 写测试**

```python
# tests/test_taskgen_dedup.py
import random
from collections import Counter
from dysql_bench.taskgen import dedup


def rec(i, person, template):
    return {"id": f"x:{i}", "anchor_table": "customers", "key_value": person, "template": template}


def test_caps_per_template_and_per_person():
    recs = [rec(i, i, "A") for i in range(40)] + [rec(100 + i, 999, "B") for i in range(5)] + [rec(200, 1, "C")]
    out = dedup.select(recs, random.Random(0))
    c = Counter(r["template"] for r in out)
    assert c["A"] == 15 and c["B"] == 2 and c["C"] == 1
    assert Counter(r["key_value"] for r in out)[999] == 2 and Counter(r["key_value"] for r in out)[1] <= 2


def test_rare_templates_are_kept_before_common_ones():
    recs = [rec(i, i, "common") for i in range(30)] + [rec(50 + i, 50 + i, f"rare{i}") for i in range(10)]
    out = dedup.select(recs, random.Random(0), per_db=12)
    assert sum(r["template"].startswith("rare") for r in out) == 10 and len(out) == 12


def test_per_db_cap_and_determinism():
    recs = [rec(i, i, f"t{i % 7}") for i in range(100)]
    a = dedup.select(recs, random.Random(1), per_db=20)
    b = dedup.select(recs, random.Random(1), per_db=20)
    assert len(a) == 20 and [r["id"] for r in a] == [r["id"] for r in b]
```

- [ ] **Step 2: 跑测试，确认失败**

Run: `cd DySQL-Bench && ~/miniconda3/envs/dysql/bin/python -m pytest -q tests/test_taskgen_dedup.py`
Expected: FAIL，`ImportError: cannot import name 'dedup'`。

- [ ] **Step 3: 写 `dedup.py`**

```python
# dysql_bench/taskgen/dedup.py
"""Diversity caps (spec §5): at most `per_person` tasks per anchor row, `per_template` per template, `per_db` per
database. Rare templates are taken first so the long tail survives the per-db cap."""
from collections import Counter


def select(records, rng, per_person=2, per_template=15, per_db=600):
    freq = Counter(r["template"] for r in records)
    order = list(records)
    rng.shuffle(order)
    order.sort(key=lambda r: freq[r["template"]])          # stable: ties keep the shuffled order
    seen_person, seen_template, out = Counter(), Counter(), []
    for r in order:
        person = (r["anchor_table"], str(r["key_value"]))
        if seen_person[person] >= per_person or seen_template[r["template"]] >= per_template:
            continue
        seen_person[person] += 1; seen_template[r["template"]] += 1
        out.append(r)
        if len(out) >= per_db:
            break
    return out
```

- [ ] **Step 4: 跑测试，确认通过**

Run: `cd DySQL-Bench && ~/miniconda3/envs/dysql/bin/python -m pytest -q tests/test_taskgen_dedup.py`
Expected: 3 passed。

- [ ] **Step 5: Commit**

```bash
git add DySQL-Bench/dysql_bench/taskgen/dedup.py DySQL-Bench/tests/test_taskgen_dedup.py
git commit -m "feat(taskgen): diversity caps per person, template and database

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 11: `taskgen/convert.py` 与通用 `GenEnv`

**Files:**
- Create: `DySQL-Bench/dysql_bench/taskgen/convert.py`
- Create: `DySQL-Bench/dysql_bench/envs/gen/__init__.py`
- Create: `DySQL-Bench/dysql_bench/envs/gen/agent_policy_header.md`
- Modify: `DySQL-Bench/dysql_bench/envs/__init__.py`（`get_env` 开头加 `gen:` 分支）
- Modify: `DySQL-Bench/run.py:13`（`--env` 去掉 `choices`）
- Test: `DySQL-Bench/tests/test_taskgen_convert_env.py`

**Interfaces:**
- Produces:
  - `convert.write_tasks(db_rec, records, tasks_path) -> int`：每行 `{"user_id": "0", "instruction", "actions": [{"name": "sql", "kwargs": {"sql": ...}}], "meta": {...}}`。`meta` 含 `id, db, source, anchor_table, anchor_key, key_value, task_type, difficulty, template, plan, verify_votes(每票 verdict 列表), gen_model, verify_model`。
  - `convert.update_manifest(manifest_path, db, sqlite_rel_or_abs, tasks_path)`：`manifest.json` 形如 `{"beer_factory": {"db_key": "bird:beer_factory", "sqlite": "bird/train/train_databases/beer_factory/beer_factory.sqlite", "tasks": "data/taskgen/beer_factory/tasks.jsonl"}}`。`sqlite` 是相对 `TEXT2SQL_BENCH` 的路径（绝对路径原样存），`tasks` 相对 `DySQL-Bench/`。
  - `envs.gen.GenEnv(db, user_strategy, user_model, user_model_api, task_split="train", task_index=None, thread_id=None, manifest=None)`；`envs.gen.load_tasks(path) -> list[Task]`。
  - `get_env("gen:<db>", ...)` 返回 `GenEnv`。
- `agent_policy_header.md` 的内容：`dysql_bench/envs/chinook/agent_policy.md` 从开头到 "I will provide the DDL … understand the structure of the database." 这一行为止（13 个 env 这段完全相同），后面接 DDL。

- [ ] **Step 1: 写测试**

```python
# tests/test_taskgen_convert_env.py
import json, os
from tests._sqlite_fixtures import make_db, SHOP
from dysql_bench.taskgen import convert, io
from dysql_bench.envs import get_env
from dysql_bench.envs.gen import GenEnv, load_tasks
from dysql_bench.types import Action

REC = {"id": "test:shop:customers:5:0", "db": "shop", "source": "test", "anchor_table": "customers", "anchor_key": "customer_id",
       "key_value": 5, "instruction": "I am a5 b5. Set qty of my order 5 to 3.", "actions": [{"sql": "UPDATE orders SET qty = 3 WHERE order_id = 5"}],
       "plan": {"task_type": "1_self"}, "task_type": "1_self", "template": "1_self|UPDATE orders",
       "difficulty": {"score": 0, "level": "easy"}, "gen_model": "g", "verify_model": "v",
       "votes": [{"verdict": "yes"}, {"verdict": "yes"}, {"verdict": "no"}]}


def setup(tmp_path):
    db = make_db(tmp_path, "shop", SHOP)
    rec = {"source": "test", "db": "shop", "path": db, "anchors": [], "fks": []}
    tasks = str(tmp_path / "data" / "shop" / "tasks.jsonl"); manifest = str(tmp_path / "manifest.json")
    n = convert.write_tasks(rec, [REC], tasks)
    convert.update_manifest(manifest, "shop", db, tasks, "test:shop")
    return db, tasks, manifest, n


def test_write_tasks_and_manifest(tmp_path):
    db, tasks, manifest, n = setup(tmp_path)
    row = io.read_jsonl(tasks)[0]
    assert n == 1 and row["user_id"] == "0" and row["actions"] == [{"name": "sql", "kwargs": {"sql": "UPDATE orders SET qty = 3 WHERE order_id = 5"}}]
    assert row["meta"]["task_type"] == "1_self" and row["meta"]["verify_votes"] == ["yes", "yes", "no"] and row["meta"]["difficulty"]["level"] == "easy"
    m = json.load(open(manifest))["shop"]
    assert m["db_key"] == "test:shop" and m["sqlite"] == db and m["tasks"] == tasks


def test_gen_env_loads_tasks_ddl_and_scores_gold(tmp_path, monkeypatch):
    db, tasks, manifest, _ = setup(tmp_path)
    env = GenEnv("shop", user_strategy="human", user_model="", user_model_api="", task_index=0, manifest=manifest)
    assert env.table_names == ["customers", "products", "orders"] and "CREATE TABLE customers" in env.wiki
    assert env.wiki.startswith("# Agent policy") and env.task.instruction.startswith("I am a5 b5")
    env.step(Action(name="sql", kwargs={"sql": "UPDATE orders SET qty = 3 WHERE order_id = 5"}))
    monkeypatch.setattr(env, "delete_db", lambda: None)
    assert env.calculate_reward().reward == 1.0
    env2 = GenEnv("shop", user_strategy="human", user_model="", user_model_api="", task_index=0, manifest=manifest)
    env2.step(Action(name="sql", kwargs={"sql": "UPDATE orders SET qty = 9 WHERE order_id = 5"}))
    monkeypatch.setattr(env2, "delete_db", lambda: None)
    assert env2.calculate_reward().reward == 0.0


def test_get_env_dispatches_gen_prefix(tmp_path, monkeypatch):
    db, tasks, manifest, _ = setup(tmp_path)
    monkeypatch.setenv("TASKGEN_MANIFEST", manifest)
    env = get_env("gen:shop", user_strategy="human", user_model="", user_model_api="", task_split="train", task_index=0)
    assert isinstance(env, GenEnv) and len(env.tasks) == 1
```

- [ ] **Step 2: 跑测试，确认失败**

Run: `cd DySQL-Bench && ~/miniconda3/envs/dysql/bin/python -m pytest -q tests/test_taskgen_convert_env.py`
Expected: FAIL，`ImportError: cannot import name 'convert'`。

- [ ] **Step 3: 写 `convert.py`**

```python
# dysql_bench/taskgen/convert.py
"""Final output: tasks.jsonl in Task shape (+ meta) and the manifest GenEnv reads."""
import json, os
from dysql_bench.taskgen import io


def to_task_row(i, r):
    meta = {k: r.get(k) for k in ("id", "db", "source", "anchor_table", "anchor_key", "key_value", "task_type",
                                   "difficulty", "template", "plan", "gen_model", "verify_model")}
    meta["verify_votes"] = [v["verdict"] for v in r.get("votes", [])]
    return {"user_id": str(i), "instruction": r["instruction"],
            "actions": [{"name": "sql", "kwargs": {"sql": a["sql"]}} for a in r["actions"]], "meta": meta}


def write_tasks(db_rec, records, tasks_path):
    rows = [to_task_row(i, r) for i, r in enumerate(records)]
    if os.path.exists(tasks_path):
        os.remove(tasks_path)
    io.append_jsonl(tasks_path, rows)
    return len(rows)


def update_manifest(manifest_path, db, sqlite_path, tasks_path, db_key):
    """sqlite is stored relative to TEXT2SQL_BENCH when it lives there (portable), else as given."""
    m = json.load(open(manifest_path, encoding="utf-8")) if os.path.exists(manifest_path) else {}
    rel = os.path.relpath(sqlite_path, io.DATA_ROOT)
    m[db] = {"db_key": db_key, "sqlite": sqlite_path if rel.startswith("..") else rel, "tasks": tasks_path}
    os.makedirs(os.path.dirname(os.path.abspath(manifest_path)), exist_ok=True)
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=1)
```

- [ ] **Step 4: 写 `agent_policy_header.md` 和 `envs/gen/__init__.py`**

Run: `cd DySQL-Bench && sed -n '1,/I will provide the DDL/p' dysql_bench/envs/chinook/agent_policy.md > dysql_bench/envs/gen/agent_policy_header.md && tail -1 dysql_bench/envs/gen/agent_policy_header.md`
Expected: 最后一行是 "- I will provide the DDL … understand the structure of the database."

```python
# dysql_bench/envs/gen/__init__.py
"""Generic environment for generated tasks: database path and task file come from data/taskgen/manifest.json
(env var TASKGEN_MANIFEST overrides), the agent policy is the header shared by the 13 DySQL envs plus this
database's DDL, and the per-thread DB copy works exactly like the other envs' load_sql_data."""
import json, os, shutil, sqlite3
from typing import Optional, Union
from dysql_bench.envs.base import Env
from dysql_bench.envs.user import UserStrategy
from dysql_bench.types import Task, Action
from dysql_bench.taskgen import io, schema

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MANIFEST = os.path.join(io.ROOT, "data", "taskgen", "manifest.json")
HEADER = open(os.path.join(HERE, "agent_policy_header.md"), encoding="utf-8").read()
TIMEOUT = 10


def load_tasks(path):
    return [Task(user_id=r["user_id"], instruction=r["instruction"], actions=[Action(**a) for a in r["actions"]])
            for r in io.read_jsonl(path)]


def make_loader(sqlite_path, db):
    def load_sql_data(thread_id):
        folder = os.path.join(HERE, "tmp", db, f"thread_{os.getpid()}_{thread_id}")
        os.makedirs(folder, exist_ok=True)
        target = os.path.join(folder, os.path.basename(sqlite_path))
        shutil.copy(sqlite_path, target)
        conn = sqlite3.connect(target, timeout=TIMEOUT)
        return conn, conn.cursor(), folder
    return load_sql_data


def table_names(sqlite_path):
    c = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
    try:
        return [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY rowid")]
    finally:
        c.close()


class GenEnv(Env):
    def __init__(self, db: str, user_strategy: Union[str, UserStrategy] = UserStrategy.LLM, user_model: str = "gpt-4o",
                 user_model_api: str = None, task_split: str = "train", task_index: Optional[int] = None,
                 thread_id: int = None, manifest: Optional[str] = None):
        manifest = manifest or os.environ.get("TASKGEN_MANIFEST") or DEFAULT_MANIFEST
        with open(manifest, encoding="utf-8") as f:
            m = json.load(f)[db]
        sqlite_path = io.resolve_db_path(m["sqlite"])
        tasks_path = m["tasks"] if os.path.isabs(m["tasks"]) else os.path.join(io.ROOT, m["tasks"])
        super().__init__(data_load_func=make_loader(sqlite_path, db), table_names=table_names(sqlite_path),
                         tasks=load_tasks(tasks_path), wiki=HEADER.rstrip("\n") + "\n" + schema.ddl(sqlite_path),
                         user_strategy=user_strategy, user_model=user_model, user_model_api=user_model_api,
                         task_index=task_index, thread_id=thread_id)
```

- [ ] **Step 5: 接入 `get_env` 和 `run.py`**

在 `dysql_bench/envs/__init__.py` 的 `get_env` 函数体开头（`if env_name == "retail":` 之前）加：

```python
    if env_name.startswith("gen:"):
        from dysql_bench.envs.gen import GenEnv
        return GenEnv(env_name[4:], user_strategy=user_strategy, user_model=user_model, user_model_api=user_model_api,
                      task_split=task_split, task_index=task_index, thread_id=thread_id)
```

`run.py` 第 13 行的 `--env` 去掉 `choices=[...]`，改成 `type=str, default="retail", help="one of the 13 DySQL envs, or gen:<db> for a generated task set (data/taskgen/manifest.json)"`。

`run.py` 的 `build_meta` 调 `classify_task(task)`，它只看 `task.actions`，对 `GenEnv` 的任务同样适用，不用改。

- [ ] **Step 6: 跑测试，确认通过**

Run: `cd DySQL-Bench && ~/miniconda3/envs/dysql/bin/python -m pytest -q tests/test_taskgen_convert_env.py tests/test_env_hash.py`
Expected: 全部 PASS。`test_gen_env_loads_tasks_ddl_and_scores_gold` 的 reward 断言依赖 `calculate_reward` 在 gold 副本上重放 `task.actions`，和 `test_env_hash.py` 的用法一致。

- [ ] **Step 7: 清理和忽略**

`envs/gen/tmp/` 由根 `.gitignore` 的 `tmp/` 规则覆盖。确认：`cd DySQL-Bench && git check-ignore -v dysql_bench/envs/gen/tmp/x`，Expected: 输出 `.gitignore:…:tmp/`。

- [ ] **Step 8: Commit**

```bash
git add DySQL-Bench/dysql_bench/taskgen/convert.py DySQL-Bench/dysql_bench/envs/gen DySQL-Bench/dysql_bench/envs/__init__.py DySQL-Bench/run.py DySQL-Bench/tests/test_taskgen_convert_env.py
git commit -m "feat(envs): generic GenEnv for generated task sets (gen:<db> via data/taskgen/manifest.json)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 12: `scripts/taskgen.py` CLI 与 `taskgen/stats.py`

**Files:**
- Create: `DySQL-Bench/dysql_bench/taskgen/stats.py`
- Create: `DySQL-Bench/scripts/taskgen.py`
- Test: `DySQL-Bench/tests/test_taskgen_cli.py`、`DySQL-Bench/tests/test_taskgen_stats.py`

**Interfaces:**
- 子命令（都带 `--db <key>`，如 `bird:beer_factory`；`--anchors` 默认 `docs/data_gen/candidate_anchors.json`；`--out-dir` 默认 `results/taskgen/<db>/`）：
  - `trees --n N --seed S [--anchor TABLE]`：`check_scope` 后写 `trees.jsonl`（每行一棵树，多加 `anchor_table` 已在树里；`others` 另存 `others.json`：同表另外 20 个 `{key_value, name}`）。默认对每个 `person_named` 锚点各抽 `N` 行。
  - `describe`：调出题模型写 `docs/data_gen/db_descriptions.json`（有缓存就不调）。
  - `generate --workers W --per-tree K`：读 `trees.jsonl`，写 `candidates.jsonl`。
  - `check`：读 `candidates.jsonl`，写 `check.jsonl`（`check.run_check` 的结果，一行一条）。
  - `verify --votes V --workers W [--all-dbs]`：读通过 `check` 的候选，写 `verify.jsonl`。`--all-dbs` 循环 `results/taskgen/*/`。
  - `dedup`：合并三个文件，`verify.pass` 为真的记录过 `dedup.select`，写 `selected.jsonl`。
  - `convert`：`selected.jsonl` → `data/taskgen/<db>/tasks.jsonl`，更新 `data/taskgen/manifest.json`。
  - `stats`：打印 §10 的验收指标（见 `stats.py`）。
- `stats.summarize(cands, checks, verifies, selected) -> dict`，键：`n_candidates, n_parse_error, n_check_pass, check_reasons(Counter), n_verify_pass, n_selected, type_mix, difficulty_mix, templates, top1_share, per_person_mean, patterns(multi_write, subquery, archive, public), vote_agreement(3 票与 5 票结论不同的比例，仅当票数 ≥ 5), unanimous_share`。`stats.render(d) -> str` 输出 markdown 表。
- 所有子命令按 `id` 续跑；`generate` 和 `verify` 打印 token 用量合计。

- [ ] **Step 1: 写测试**

```python
# tests/test_taskgen_stats.py
from dysql_bench.taskgen import stats

def c(i, t="1_self", lvl="easy", tmpl="1_self|UPDATE orders", person=1, feats=None):
    return ({"id": f"x:{i}", "anchor_table": "customers", "key_value": person, "instruction": "i", "plan": {"task_type": t}},
            {"id": f"x:{i}", "ok": True, "reasons": [], "task_type": t, "template": tmpl,
             "difficulty": {"level": lvl, "features": feats or {"multi_write": False, "subquery": False, "archive": False, "public_or_other": False}}})

def test_summarize_counts_and_ratios():
    pairs = [c(0), c(1, person=2), c(2, "5_proxy", "hard", "5_proxy|DELETE orders+UPDATE orders", 3, {"multi_write": True, "subquery": True, "archive": False, "public_or_other": False})]
    cands, checks = [p[0] for p in pairs], [p[1] for p in pairs]
    cands.append({"id": "x:9", "instruction": None, "error": "ParseError: x", "plan": {"task_type": "1_self"}, "anchor_table": "customers", "key_value": 9})
    checks.append({"id": "x:9", "ok": False, "reasons": ["no_instruction"], "task_type": None, "template": None, "difficulty": None})
    verifies = [{"id": "x:0", "votes": [{"verdict": v} for v in "yes yes no yes no".split()], "pass": True},
                {"id": "x:1", "votes": [{"verdict": v} for v in "no no yes yes yes".split()], "pass": True},
                {"id": "x:2", "votes": [{"verdict": "no"}] * 5, "pass": False}]
    d = stats.summarize(cands, checks, verifies, [cands[0], cands[1]])
    assert d["n_candidates"] == 4 and d["n_parse_error"] == 1 and d["n_check_pass"] == 3 and d["n_verify_pass"] == 2 and d["n_selected"] == 2
    assert d["type_mix"] == {"1_self": 2, "5_proxy": 1} and d["difficulty_mix"] == {"easy": 2, "hard": 1}
    assert d["templates"] == 2 and abs(d["top1_share"] - 2 / 3) < 1e-9 and d["per_person_mean"] == 1.0
    assert d["patterns"] == {"multi_write": 1, "subquery": 1, "archive": 0, "public": 0}
    assert abs(d["vote_agreement"] - 1 / 3) < 1e-9 and abs(d["unanimous_share"] - 1 / 3) < 1e-9   # x:1 flips between 3 and 5 votes
    assert "top1_share" in stats.render(d)
```

```python
# tests/test_taskgen_cli.py
import json, os, subprocess, sys
from tests._sqlite_fixtures import make_db
from tests.test_taskgen_trees import SHOP2, FKS, CUSTOMER
from dysql_bench.taskgen import io

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "taskgen.py")


def run(*args):
    return subprocess.run([sys.executable, SCRIPT, *args], check=True, capture_output=True, text=True).stdout


def test_trees_check_dedup_convert_without_a_model(tmp_path):
    db = make_db(tmp_path, "shop2", SHOP2)
    anchors = tmp_path / "anchors.json"
    anchors.write_text(json.dumps({"test:shop2": {"source": "test", "db": "shop2", "path": db, "anchors": [CUSTOMER], "fks": FKS}}))
    out = tmp_path / "res"
    run("trees", "--db", "test:shop2", "--anchors", str(anchors), "--out-dir", str(out), "--n", "3", "--seed", "0")
    trees = io.read_jsonl(out / "trees.jsonl")
    assert len(trees) == 3 and all(t["down"].get("orders") for t in trees) and len(json.load(open(out / "others.json"))["customers"]) >= 3
    # a hand-written candidate stands in for the model
    t = trees[0]
    io.append_jsonl(out / "candidates.jsonl", [{"id": "test:shop2:customers:%s:0" % t["key_value"], "db": "shop2", "source": "test",
        "anchor_table": "customers", "anchor_key": "customer_id", "key_value": t["key_value"], "anchor_name": t["anchor_name"],
        "plan": {"task_type": "1_self", "difficulty": "easy"}, "instruction": f"I am {t['anchor_name']}. Set qty of my order {t['down']['orders'][0]['order_id']} to 3.",
        "actions": [{"sql": f"UPDATE orders SET qty = 3 WHERE order_id = {t['down']['orders'][0]['order_id']}"}], "outputs": [], "error": None}])
    run("check", "--db", "test:shop2", "--anchors", str(anchors), "--out-dir", str(out))
    chk = io.read_jsonl(out / "check.jsonl")
    assert len(chk) == 1 and chk[0]["ok"] and chk[0]["template"] == "1_self|UPDATE orders"
    io.append_jsonl(out / "verify.jsonl", [{"id": chk[0]["id"], "votes": [{"verdict": "yes"}] * 3, "yes": 3, "no": 0, "pass": True, "verify_model": "fake"}])
    run("dedup", "--db", "test:shop2", "--anchors", str(anchors), "--out-dir", str(out))
    assert len(io.read_jsonl(out / "selected.jsonl")) == 1
    manifest = tmp_path / "manifest.json"; tasks = tmp_path / "tasks.jsonl"
    run("convert", "--db", "test:shop2", "--anchors", str(anchors), "--out-dir", str(out), "--tasks", str(tasks), "--manifest", str(manifest))
    assert io.read_jsonl(tasks)[0]["meta"]["template"] == "1_self|UPDATE orders" and json.load(open(manifest))["shop2"]["db_key"] == "test:shop2"
    text = run("stats", "--db", "test:shop2", "--anchors", str(anchors), "--out-dir", str(out))
    assert "n_selected" in text and "| 1 |" in text
```

- [ ] **Step 2: 跑测试，确认失败**

Run: `cd DySQL-Bench && ~/miniconda3/envs/dysql/bin/python -m pytest -q tests/test_taskgen_stats.py tests/test_taskgen_cli.py`
Expected: FAIL，`ImportError: cannot import name 'stats'`；CLI 测试 `FileNotFoundError`。

- [ ] **Step 3: 写 `stats.py`**

```python
# dysql_bench/taskgen/stats.py
"""Pilot acceptance numbers (spec §10) from the step files of one database."""
from collections import Counter


def _majority(votes):
    y = sum(v["verdict"] == "yes" for v in votes)
    return y > len(votes) - y


def summarize(cands, checks, verifies, selected):
    chk = {c["id"]: c for c in checks}
    ver = {v["id"]: v for v in verifies}
    passed = [c for c in cands if chk.get(c["id"], {}).get("ok")]
    d = {"n_candidates": len(cands), "n_parse_error": sum(1 for c in cands if not c.get("instruction")),
         "n_check_pass": len(passed), "check_reasons": Counter(x.split(":")[0] for c in checks for x in c["reasons"]),
         "n_verify_pass": sum(1 for v in verifies if v["pass"]), "n_selected": len(selected)}
    good = [chk[c["id"]] for c in passed]
    d["type_mix"] = dict(Counter(g["task_type"] for g in good))
    d["difficulty_mix"] = dict(Counter(g["difficulty"]["level"] for g in good))
    tmpl = Counter(g["template"] for g in good)
    d["templates"] = len(tmpl)
    d["top1_share"] = (tmpl.most_common(1)[0][1] / len(good)) if good else 0.0
    per_person = Counter((c["anchor_table"], str(c["key_value"])) for c in passed)
    d["per_person_mean"] = (sum(per_person.values()) / len(per_person)) if per_person else 0.0
    f = [g["difficulty"]["features"] for g in good]
    d["patterns"] = {"multi_write": sum(x["multi_write"] for x in f), "subquery": sum(x["subquery"] for x in f),
                     "archive": sum(x["archive"] for x in f), "public": sum(x["public_or_other"] for x in f)}
    five = [v for v in verifies if len(v["votes"]) >= 5]
    d["vote_agreement"] = (sum(_majority(v["votes"][:3]) != _majority(v["votes"][:5]) for v in five) / len(five)) if five else None
    d["unanimous_share"] = (sum(len({x["verdict"] for x in v["votes"]}) == 1 for v in verifies) / len(verifies)) if verifies else None
    return d


def render(d):
    rows = [("n_candidates", d["n_candidates"]), ("n_parse_error", d["n_parse_error"]), ("n_check_pass", d["n_check_pass"]),
            ("check_reasons", ", ".join(f"{k} {v}" for k, v in d["check_reasons"].most_common())),
            ("n_verify_pass", d["n_verify_pass"]), ("n_selected", d["n_selected"]),
            ("type_mix", d["type_mix"]), ("difficulty_mix", d["difficulty_mix"]), ("templates", d["templates"]),
            ("top1_share", f"{d['top1_share']:.2f}"), ("per_person_mean", f"{d['per_person_mean']:.2f}"),
            ("patterns", d["patterns"]),
            ("vote_agreement (3 vs 5 votes disagree)", "n/a" if d["vote_agreement"] is None else f"{d['vote_agreement']:.2f}"),
            ("unanimous_share", "n/a" if d["unanimous_share"] is None else f"{d['unanimous_share']:.2f}")]
    return "| metric | value |\n|---|---|\n" + "\n".join(f"| {k} | {v} |" for k, v in rows)
```

- [ ] **Step 4: 写 `scripts/taskgen.py`**

```python
#!/usr/bin/env python3
"""Task-generation pipeline, one sub-command per step; every step resumes by record id.
Usage (from DySQL-Bench/), pilot on beer_factory:
  P=~/miniconda3/envs/dysql/bin/python; DB=bird:beer_factory
  $P scripts/taskgen.py trees    --db $DB --n 50 --seed 0
  $P scripts/taskgen.py describe --db $DB
  $P scripts/taskgen.py generate --db $DB --workers 8
  $P scripts/taskgen.py check    --db $DB
  $P scripts/taskgen.py verify   --db $DB --votes 5 --workers 4
  $P scripts/taskgen.py dedup    --db $DB
  $P scripts/taskgen.py convert  --db $DB
  $P scripts/taskgen.py stats    --db $DB
Files: results/taskgen/<db>/{trees,candidates,check,verify,selected}.jsonl, others.json; data/taskgen/<db>/tasks.jsonl."""
import argparse, glob, json, os, random, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dysql_bench.taskgen import io, trees, schema, llm, prompt, generate, check, verify, dedup, convert, stats

DESC_PATH = os.path.join(io.REPO, "docs", "data_gen", "db_descriptions.json")


def rec_and_dir(a):
    rec = io.load_db_recs(a.anchors)[a.db]
    out = a.out_dir or os.path.join(io.ROOT, "results", "taskgen", rec["db"])
    os.makedirs(out, exist_ok=True)
    return rec, out


def cmd_trees(a):
    rec, out = rec_and_dir(a)
    rng = random.Random(a.seed)
    c = trees.open_ro(io.resolve_db_path(rec["path"]))
    done = {(t["anchor_table"], str(t["key_value"])) for t in io.read_jsonl(f"{out}/trees.jsonl")}
    others = json.load(open(f"{out}/others.json")) if os.path.exists(f"{out}/others.json") else {}
    for anchor in io.person_anchors(rec):
        if a.anchor and anchor["table"] != a.anchor:
            continue
        trees.check_scope(anchor, rec["fks"])
        kvs = trees.anchor_key_values(c, anchor, rec["fks"], rng, a.n + 20)
        built = [t for kv in kvs[:a.n] if (anchor["table"], str(kv)) not in done
                 and (t := trees.build_tree(c, anchor, rec["fks"], kv, rng))]
        io.append_jsonl(f"{out}/trees.jsonl", built)
        # candidate 'other people' for type 4: the 20 rows after the sampled ones, names only
        extra = [trees.build_tree(c, anchor, rec["fks"], kv, rng, max_down=0, max_up=0) for kv in kvs[a.n:]]
        others[anchor["table"]] = [{"key_value": t["key_value"], "name": t["anchor_name"]} for t in built + extra if t][:20]
        print(f"{anchor['table']}: {len(built)} trees written")
    json.dump(others, open(f"{out}/others.json", "w"), ensure_ascii=False, default=str)


def cmd_describe(a):
    rec, _ = rec_and_dir(a)
    print(schema.describe_db(a.db, io.resolve_db_path(rec["path"]), llm.client_from_env("GEN"), DESC_PATH))


def cmd_generate(a):
    rec, out = rec_and_dir(a)
    path = io.resolve_db_path(rec["path"])
    desc = json.load(open(DESC_PATH)).get(a.db, "") if os.path.exists(DESC_PATH) else ""
    if not desc:
        sys.exit("run `describe` first")
    client = llm.client_from_env("GEN")
    all_trees = io.read_jsonl(f"{out}/trees.jsonl")
    others = json.load(open(f"{out}/others.json"))
    t0, total = time.time(), {"written": 0, "errors": 0, "skipped": 0}
    for anchor in io.person_anchors(rec):
        ts = [t for t in all_trees if t["anchor_table"] == anchor["table"]]
        s = generate.run(rec, anchor, ts, others.get(anchor["table"], []), client, f"{out}/candidates.jsonl",
                         random.Random(a.seed), workers=a.workers, per_tree=a.per_tree,
                         db_description=desc, schema_text=schema.schema_block(path))
        total = {k: total[k] + s[k] for k in total}
    usage = sum((c.get("usage") or {}).get("total_tokens", 0) for c in io.read_jsonl(f"{out}/candidates.jsonl"))
    print(f"{total} in {time.time() - t0:.0f}s; total tokens so far {usage}")


def cmd_check(a):
    rec, out = rec_and_dir(a)
    done = io.done_ids(f"{out}/check.jsonl")
    todo = [c for c in io.read_jsonl(f"{out}/candidates.jsonl") if c["id"] not in done]
    res = [check.run_check(rec, c) for c in todo]
    io.append_jsonl(f"{out}/check.jsonl", res)
    print(f"checked {len(res)}, passed {sum(r['ok'] for r in res)}")


def cmd_verify(a):
    dbs = [a.db] if not a.all_dbs else [k for k in io.load_db_recs(a.anchors) if os.path.exists(
        os.path.join(io.ROOT, "results", "taskgen", k.split(":", 1)[1], "check.jsonl"))]
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


def merged(out):
    chk = {r["id"]: r for r in io.read_jsonl(f"{out}/check.jsonl")}
    ver = {r["id"]: r for r in io.read_jsonl(f"{out}/verify.jsonl")}
    rows = []
    for c in io.read_jsonl(f"{out}/candidates.jsonl"):
        k, v = chk.get(c["id"]), ver.get(c["id"])
        if k and k["ok"] and v and v["pass"]:
            rows.append({**c, "task_type": k["task_type"], "template": k["template"], "difficulty": k["difficulty"],
                         "writes": k["writes"], "votes": v["votes"], "verify_model": v.get("verify_model")})
    return rows


def cmd_dedup(a):
    rec, out = rec_and_dir(a)
    sel = dedup.select(merged(out), random.Random(a.seed), a.per_person, a.per_template, a.per_db)
    if os.path.exists(f"{out}/selected.jsonl"):
        os.remove(f"{out}/selected.jsonl")
    io.append_jsonl(f"{out}/selected.jsonl", sel)
    print(f"selected {len(sel)}")


def cmd_convert(a):
    rec, out = rec_and_dir(a)
    tasks = a.tasks or os.path.join(io.ROOT, "data", "taskgen", rec["db"], "tasks.jsonl")
    manifest = a.manifest or os.path.join(io.ROOT, "data", "taskgen", "manifest.json")
    n = convert.write_tasks(rec, io.read_jsonl(f"{out}/selected.jsonl"), tasks)
    convert.update_manifest(manifest, rec["db"], io.resolve_db_path(rec["path"]),
                            tasks if a.tasks else os.path.relpath(tasks, io.ROOT), a.db)
    print(f"wrote {n} tasks to {tasks}")


def cmd_stats(a):
    rec, out = rec_and_dir(a)
    d = stats.summarize(io.read_jsonl(f"{out}/candidates.jsonl"), io.read_jsonl(f"{out}/check.jsonl"),
                        io.read_jsonl(f"{out}/verify.jsonl"), io.read_jsonl(f"{out}/selected.jsonl"))
    print(stats.render(d))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    def common(p):
        p.add_argument("--db", required=True); p.add_argument("--anchors", default=os.path.join(io.REPO, "docs", "data_gen", "candidate_anchors.json"))
        p.add_argument("--out-dir"); p.add_argument("--seed", type=int, default=0)
    p = sub.add_parser("trees"); common(p); p.add_argument("--n", type=int, default=50); p.add_argument("--anchor"); p.set_defaults(f=cmd_trees)
    p = sub.add_parser("describe"); common(p); p.set_defaults(f=cmd_describe)
    p = sub.add_parser("generate"); common(p); p.add_argument("--workers", type=int, default=8); p.add_argument("--per-tree", type=int, default=1); p.set_defaults(f=cmd_generate)
    p = sub.add_parser("check"); common(p); p.set_defaults(f=cmd_check)
    p = sub.add_parser("verify"); common(p); p.add_argument("--votes", type=int, default=3); p.add_argument("--workers", type=int, default=4); p.add_argument("--all-dbs", action="store_true"); p.set_defaults(f=cmd_verify)
    p = sub.add_parser("dedup"); common(p); p.add_argument("--per-person", type=int, default=2); p.add_argument("--per-template", type=int, default=15); p.add_argument("--per-db", type=int, default=600); p.set_defaults(f=cmd_dedup)
    p = sub.add_parser("convert"); common(p); p.add_argument("--tasks"); p.add_argument("--manifest"); p.set_defaults(f=cmd_convert)
    p = sub.add_parser("stats"); common(p); p.set_defaults(f=cmd_stats)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
```

`verify --all-dbs` 时 `--db` 仍是必填，随便传一个已有的 key 即可；执行时被循环覆盖。`verify.run` 的 `TASKGEN_VERIFY_VOTES` 环境变量不单独实现，票数只从 `--votes` 来（spec 里的名字保留给 shell 脚本用：`--votes ${TASKGEN_VERIFY_VOTES:-3}`）。

- [ ] **Step 5: 跑测试，确认通过**

Run: `cd DySQL-Bench && ~/miniconda3/envs/dysql/bin/python -m pytest -q tests/test_taskgen_stats.py tests/test_taskgen_cli.py`
Expected: 2 passed。

- [ ] **Step 6: 跑全部 taskgen 测试和原有测试**

Run: `cd DySQL-Bench && ~/miniconda3/envs/dysql/bin/python -m pytest -q tests/`
Expected: 全部 PASS（`test_dysql_acceptance.py` 等原有测试不受影响）。

- [ ] **Step 7: 生成 beer_factory 的树和库描述（第一次真实调用）**

Run:
```bash
cd DySQL-Bench && P=~/miniconda3/envs/dysql/bin/python
$P scripts/taskgen.py trees --db bird:beer_factory --n 100 --seed 0
$P scripts/taskgen.py describe --db bird:beer_factory
git -C .. add docs/data_gen/db_descriptions.json
```
Expected: `customers: 100 trees written`；打印一段两三句的英文库描述；人读一遍，说得不对就手改 JSON。

- [ ] **Step 8: Commit**

```bash
git add DySQL-Bench/dysql_bench/taskgen/stats.py DySQL-Bench/scripts/taskgen.py DySQL-Bench/tests/test_taskgen_stats.py DySQL-Bench/tests/test_taskgen_cli.py docs/data_gen/db_descriptions.json
git commit -m "feat(taskgen): CLI with one sub-command per step, pilot statistics, beer_factory description

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 13: 部署校验模型 `scripts/serve_verifier.sh`

**Files:**
- Create: `DySQL-Bench/scripts/serve_verifier.sh`
- Modify: `docs/gb10_serving_notes.md`（追加一节：校验模型的启动参数和实测吞吐）

**Interfaces:**
- 端口 8003，served name `qwen3.8-27b-nvfp4`，对应 `.env` 里的 `TASKGEN_VERIFY_*`。
- 这是手工步骤，没有单元测试；验收是 `curl` 冒烟和 `tests/test_taskgen_llm.py` 之外的一次真实 `client_from_env("VERIFY").chat`。

- [ ] **Step 1: 下载模型（约 15 GB，用镜像里的 hf，和 `docs/gb10_serving_notes.md` 的做法一致）**

Run: `docker run --rm -v ~/.cache/huggingface:/root/.cache/huggingface --entrypoint hf vllm/vllm-openai:cu130-nightly download nvidia/Qwen3.8-27B-NVFP4`
Expected: 结束时 `~/.cache/huggingface/hub/models--nvidia--Qwen3.8-27B-NVFP4/snapshots/*/` 下有 `config.json` 和 safetensors。

- [ ] **Step 2: 写 `serve_verifier.sh`**

```bash
#!/usr/bin/env bash
# scripts/serve_verifier.sh -- vLLM server for the task-verification model (spec §3). Same image and flags as serve_agent.sh.
#   MODEL        default nvidia/Qwen3.8-27B-NVFP4      SERVED_NAME default qwen3.8-27b-nvfp4 (must match .env TASKGEN_VERIFY_MODEL)
#   PORT         default 8003                          CONTAINER   default dysql-verifier
#   MAX_LEN      default 32768                         MAX_SEQS    default 16
#   GPU_UTIL     default 0.30 (NVFP4 weights ~15 GB; raise if the profiler refuses)
#   DRY_RUN=1    print the docker command and exit
set -euo pipefail
MODEL="${MODEL:-nvidia/Qwen3.8-27B-NVFP4}"; SERVED_NAME="${SERVED_NAME:-qwen3.8-27b-nvfp4}"
PORT="${PORT:-8003}"; CONTAINER="${CONTAINER:-dysql-verifier}"
MAX_LEN="${MAX_LEN:-32768}"; MAX_SEQS="${MAX_SEQS:-16}"; GPU_UTIL="${GPU_UTIL:-0.30}"
CMD=(docker run -d --name "$CONTAINER" --restart unless-stopped
  --gpus all --ipc host --shm-size 64gb -p "$PORT:$PORT"
  -v "$HOME/.cache/huggingface:/root/.cache/huggingface"
  vllm/vllm-openai:cu130-nightly "$MODEL" --served-model-name "$SERVED_NAME"
  --host 0.0.0.0 --port "$PORT" --max-model-len "$MAX_LEN" --max-num-seqs "$MAX_SEQS"
  --gpu-memory-utilization "$GPU_UTIL" --enable-prefix-caching --reasoning-parser qwen3
  --default-chat-template-kwargs '{"enable_thinking": true}')
if [ "${DRY_RUN:-0}" = "1" ]; then printf '%q ' "${CMD[@]}"; echo; exit 0; fi
docker rm -f "$CONTAINER" 2>/dev/null || true
"${CMD[@]}"
echo "$CONTAINER ($SERVED_NAME) starting on :$PORT; wait with: scripts/wait_ready.sh $PORT; logs: docker logs -f $CONTAINER"
```

- [ ] **Step 3: 启动并冒烟**

先看 `docker ps`：8000 / 8001 / 8002 上现在跑着 1.7B agent、72B 用户模拟器、4B agent。校验期间停掉 1.7B 的容器（`docker stop dysql-agent-1.7b`）腾显存；按 `docs/gb10_serving_notes.md` 的"sequential container start"规则，等它停干净再起校验模型。

Run:
```bash
cd DySQL-Bench && bash scripts/serve_verifier.sh && bash scripts/wait_ready.sh 8003
curl -s http://127.0.0.1:8003/v1/models | python3 -c "import sys,json; print([m['id'] for m in json.load(sys.stdin)['data']])"
~/miniconda3/envs/dysql/bin/python -c "
from dysql_bench.taskgen import llm
r = llm.client_from_env('VERIFY').chat([{'role':'user','content':'Is 17 prime? End with: Verification: Is the answer correct (Yes/No)? Yes'}], max_tokens=2048)
print(repr(r['content'][-80:]), len(r['reasoning']), r['usage'])"
```
Expected: 模型列表含 `qwen3.8-27b-nvfp4`；返回的 `content` 以 "Yes" 结尾，`reasoning` 非空（reasoning parser 生效），usage 有数。

如果 NVFP4 加载失败（kernel 不支持或 OOM），按 spec 退回 `MODEL=Qwen/Qwen3.8-27B-FP8 SERVED_NAME=qwen3.8-27b-fp8 GPU_UTIL=0.45`，并把 `.env` 的 `TASKGEN_VERIFY_MODEL` 改成 `qwen3.8-27b-fp8`。把实际用的记进 `docs/gb10_serving_notes.md`。

- [ ] **Step 4: 记录并提交**

在 `docs/gb10_serving_notes.md` 末尾加一节"Verifier (task generation)"：模型、GPU_UTIL、是否需要停别的容器、单条请求耗时。

```bash
git add DySQL-Bench/scripts/serve_verifier.sh docs/gb10_serving_notes.md
git commit -m "ops: vLLM launch script for the task-verification model (Qwen3.8-27B-NVFP4 on :8003)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 14: 试点 beer_factory（100 条，串行）

**Files:**
- Create: `DySQL-Bench/scripts/taskgen_pilot.sh`
- Create: `docs/data_gen/2026-09-28-pilot-beer-factory.md`（结果记录）

**Interfaces:**
- 消耗 Task 12 的 CLI；产出 `results/taskgen/beer_factory/*.jsonl`、`data/taskgen/beer_factory/tasks.jsonl`、`data/taskgen/manifest.json`。

- [ ] **Step 1: 写 `taskgen_pilot.sh`**

```bash
#!/usr/bin/env bash
# scripts/taskgen_pilot.sh <db_key> [n_trees] [votes] -- run every pipeline step for one database and print the stats.
# Verifier must be up on :8003 (scripts/serve_verifier.sh); GLM key in ../.env.
set -euo pipefail
DB="${1:?usage: taskgen_pilot.sh <source:db> [n_trees] [votes]}"; N="${2:-100}"; VOTES="${3:-${TASKGEN_VERIFY_VOTES:-5}}"
P=~/miniconda3/envs/dysql/bin/python
cd "$(dirname "$0")/.."
START=$(date +%s)
$P scripts/taskgen.py trees    --db "$DB" --n "$N" --seed 0
$P scripts/taskgen.py describe --db "$DB"
$P scripts/taskgen.py generate --db "$DB" --workers 8
$P scripts/taskgen.py check    --db "$DB"
T0=$(date +%s)
$P scripts/taskgen.py verify   --db "$DB" --votes "$VOTES" --workers 4
echo "verify_wall_s $(( $(date +%s) - T0 ))"
$P scripts/taskgen.py dedup    --db "$DB"
$P scripts/taskgen.py convert  --db "$DB"
$P scripts/taskgen.py stats    --db "$DB"
echo "pilot_wall_s $(( $(date +%s) - START ))"
```

- [ ] **Step 2: 跑试点**

Run: `cd DySQL-Bench && bash scripts/taskgen_pilot.sh bird:beer_factory 100 5 2>&1 | tee results/taskgen/beer_factory/pilot.log`
Expected: 各步不报错；`stats` 表打印出来。`generate` 若大量 429，把 `--workers` 降到 4 重跑（续跑不会重复出题）。

- [ ] **Step 3: 对照 spec §10 的验收标准，写记录**

`docs/data_gen/2026-09-28-pilot-beer-factory.md` 至少包含：
- `stats` 的表原样贴入。
- 逐项判定：
  - `n_selected ≥ 50`；
  - `type_mix` 各类与 46 / 12 / 5 / 8 / 29 的偏差 ≤ 10 个百分点；`7_no_change` 为 0（`check` 已过滤，确认 `check_reasons` 里 `noop_write` 的数量）；
  - `templates`、`top1_share`、`per_person_mean` 落在 DySQL 区间（模板数按库 9–76，top1 12%–55%，每人 1.0–2.6）；
  - `difficulty_mix` 三档都有；`patterns` 四项都 > 0；
  - `vote_agreement`（3 票 vs 5 票不一致率）< 5% 则全量用 3 票；
  - 校验吞吐：`verify_wall_s` 换算成每票秒数，乘以全量估算的候选数（23 库 × 平均树数 × 票数）得到全量天数；> 3 天则启用 spec 的两层方案（先出 `Qwen3.6-35B-A3B` 初筛，另开任务）。
- 人工核对 20 条：从 `selected.jsonl` 随机抽 20（`seed 0`），每条记录 "instruction 是否可做 / SQL 是否符合 / 校验结论是否同意"，算和校验结论的一致率。
- 发现的问题和对 prompt 的修改（改 `prompt.py` 的 `TYPE_TEXT` / `shape_text` / `SYSTEM`，每次修改后把 `candidates.jsonl`、`check.jsonl`、`verify.jsonl` 移到 `results/taskgen/beer_factory/round1/` 再跑第二轮）。

- [ ] **Step 4: Commit（试点脚本、记录、beer_factory 的任务文件）**

```bash
git add DySQL-Bench/scripts/taskgen_pilot.sh docs/data_gen/2026-09-28-pilot-beer-factory.md DySQL-Bench/data/taskgen/beer_factory/tasks.jsonl DySQL-Bench/data/taskgen/manifest.json
git commit -m "data(taskgen): beer_factory pilot tasks and acceptance record

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 15: 用 Qwen3-4B 跑试点任务（难度合理性）

**Files:**
- Modify: `docs/data_gen/2026-09-28-pilot-beer-factory.md`（追加 agent 通过率一节）

**Interfaces:**
- 消耗 Task 11 的 `gen:beer_factory` 和现有 `run.py`、`scripts/summarize.py`。

- [ ] **Step 1: 起服务**

校验模型可以先停（`docker stop dysql-verifier`），按 `docs/gb10_serving_notes.md` 的顺序起 4B agent（8002）和用户模拟器（8001）；两者本来在跑就跳过。

- [ ] **Step 2: 跑全部试点任务**

Run:
```bash
cd DySQL-Bench && OUT=results/taskgen/beer_factory/agent_4b && mkdir -p $OUT
conda run -n dysql --no-capture-output python run.py --env gen:beer_factory --task-split train --num-trials 1 \
  --model qwen3-4b --model-api http://127.0.0.1:8002 \
  --user-model qwen2.5-72b-awq --user-model-api http://127.0.0.1:8001 \
  --user-strategy llm --max-concurrency 8 --log-dir $OUT 2>&1 | tee $OUT/run.log
conda run -n dysql python scripts/summarize.py "$OUT/*.json" | tee $OUT/summary.md
```
Expected: 跑完 `n_selected` 条，`summary.md` 有 overall 一行；`--model qwen3-4b` 要和 8002 上的 served name 一致（看 `docker ps` 或 `docs/gb10_serving_notes.md`）。如果 `run.py` 因为 `--env` 的值报错，回到 Task 11 Step 5 确认 `choices` 已去掉。

- [ ] **Step 3: 判定并记录**

Expected（spec §10）: overall pass^1 在 20%–50% 之间。另外按 `meta.difficulty.level` 分三档算通过率（用 `results` JSON 里的 `task_id` 对回 `tasks.jsonl` 的行号），困难档应低于简单档。把这两张表追加到试点记录。
- 高于 50%：题太简单，回到 Task 14 Step 3 调 `DIFFICULTY_MIX` 或形状规则，再来一轮。
- 低于 20%：先看 `summary.md` 的 `sql err` 和 `0-row write` 列，再抽 10 条失败轨迹看是 instruction 缺信息（回 prompt）还是 agent 本身弱（正常）。

- [ ] **Step 4: Commit**

```bash
git add docs/data_gen/2026-09-28-pilot-beer-factory.md
git commit -m "docs(taskgen): 4B agent pass rate on the beer_factory pilot

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## 试点之后（不在本计划的任务里，按 spec §6"运行方式"执行）

1. `bash scripts/taskgen_pilot.sh bird:books 150 3`：15 张表的大 schema 验证，验收同 Task 14。
2. 其余 21 个库：进程 A 逐库 `trees → describe → generate → check`（`--n` 取 `min(600, 该库人物行数)`，`--per-tree 1`），进程 B `verify --all-dbs --votes 3` 循环；前 5 个库跑完看 `stats` 的 `n_check_pass / n_candidates` 和 `n_verify_pass / n_check_pass`，比 beer_factory 低 15 个百分点以上就停下看失败原因。
3. 每库 `dedup → convert`，最后一次性提交 `data/taskgen/`，并在 `docs/data_gen/` 写全量统计（每库产出数、类型 / 难度分布、模板数）。

## 自检

- **Spec 覆盖：** §1 范围（Task 12 的 `person_anchors` 只取 `person_named`，实体和 ID-only 不进）；§2 表格每一行有对应任务（建树 2、描述 3、few-shot 5、类型难度 5+7、执行检查 7+8、校验 9、去重 10、输出 11）；§3 模型与接口（4、13）；§4 类型与角色（5）；§5 模板、封顶、难度（7、10）；§6 模块与运行方式（12、试点之后）；§7（7、8）；§8（9）；§9（5）；§10（14、15）。
- **占位符：** 无 TBD。Task 13、14、15 的"Expected"是实测判定标准，数值来自 spec。
- **接口一致性：** `db_rec` 字段（Task 1）在 2、7、8、12 里用法一致；树字段（Task 2）在 5、6、12 一致；候选字段（Task 6）在 7、9、10、11、12 一致；`check` 结果字段在 10、11、12 一致；`verify` 记录在 11、12 一致；`GenEnv` 的 manifest 字段在 11、12 一致。
- **Review Focus 覆盖：** 1 → Task 7 `test_multi_statement_action_is_split`；2 → Task 7 `test_literal_quotes_unicode_numbers`；3 → Task 2 `test_person_without_children_still_builds_tree`；4 → Task 6 两个测试；5 → Task 4 两个测试。
