# 选库筛选器修复：实施计划

> 2026-10-01 目录重组后，文中的代码、脚本和文档路径都是重组前的旧路径，新旧对照见 [taskgen/README.md](../../README.md)。正文保持原样，作为当时的记录。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把选库规则从"必须有人物表"改成"有锚点实体，且锚点范围内有可更新的表"。外键一律先用真实数据验证再使用。然后重跑，得到新的候选库清单，以及给建树脚本用的锚点记录。

**Architecture:**
- `dysql_bench/db_select.py` 负责剖析、键、外键推断与验证、泄漏比对、评估和去重。
- 新增的 `dysql_bench/db_anchor.py` 负责更新目标、锚点、锚点类型和锚点范围。
- 所有外键都要算命中率：声明的、按名字推断的、按取值推断的、人工补充的都一样。命中率低于阈值的不参与任何规则；子表没有值可查的记为"未验证"，保留。
- `scripts/select_dbs.py` 是 CLI，输出 CSV 和锚点 JSON。
- `scripts/render_candidates_md.py` 从 CSV 生成 `docs/data_gen/candidate_dbs.md`。

**Tech Stack:** Python 3.11（conda env `dysql`）、标准库 `sqlite3`、pytest。测试一律在 `DySQL-Bench/` 目录下跑：`~/miniconda3/envs/dysql/bin/python -m pytest -q tests/...`。

**Spec:** `docs/2026-09-24-data-gen-db-selection.md`。规则 A、C、D 不变，规则 B 由 Task 12 改写。

**规则依据（2026-09-25 实测）：**
- **任务类型：** `docs/data_gen/dysql_task_types.md`。1062 个任务分 7 类：
  - 说话人是库里真人的占 67%，而且几乎都报名字。
  - 22.6% 是库外的人改库里人物的数据（代办）。
  - 7.8% 只改实体数据（car/cookbook）。
  - 19% 的任务会改公共数据，即产品、成本、歌单这类不属于任何人的行。
- **写入覆盖：** 用本计划的代码（已在临时目录跑通），DySQL 标准答案的 2434 条写语句里：
  - 写的是库里存在的表的有 2432 条，全部落在某个锚点的范围内。
  - 其中 UPDATE 的目标全部是更新目标。
  - 另外 2 条写的是库里不存在的表。
- **旧规则的问题：**
  - 旧的"可写表"定义（≥ 50 行、非键非外键列）会漏掉 21% 的真实写语句。
  - 旧定义把外键列排除在可修改列之外，但 37% 的 UPDATE 改的正是外键列（`SET AgentID = 2`）。
- **外键阈值：**
  - DySQL 自己的 retail 库里，`sales/costs.prod_id → products` 的命中率只有 31–33%（products 只留了 72 个产品中的 24 个）。
  - 但 DySQL 仍在 products 上出了 25 个 UPDATE 任务。所以阈值定 0.3。
  - 错误外键的命中率在 0–11%。

## Global Constraints

- 分支 `isa/data-gen`。每个 Task 单独 commit，commit message 以 `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>` 结尾。
- 原始库在 `~/Documents/Isa/text2sql_bench`（布局见该目录的 README.md）。DySQL 自己的 13 个库在 `DySQL-Bench/dysql_bench/envs/*/data/*.sqlite`。
- SQL 里的表名、列名一律用 `_q()` 包成 `"…"`。真实库里有 `Sales Orders`、`voice-actors` 这种名字。
- 打开库一律只读：`sqlite3.connect(f"file:{path}?mode=ro", uri=True)`。
- 空串 `''` 按 NULL 处理（AdventureWorks 把空值存成了 `''`）。
- 阈值：
  - `fk_min_hit=0.3`，`anchor_min_rows=5`，`long_text_avg_len=200`。
  - 尺寸规则不变：表数 3–20，列数 ≤ 250，总行数 200–3,000,000，文件 ≤ 300 MB，可用外键 ≥ 2，最大连通分量 ≥ 60% 的表，泄漏包含度阈值 0.6。
- `db_anchor.py` 不得 import `db_select`（`db_select` import 它）。
- `tests/test_db_select.py` 里被新规则取代的测试要改写或替换，不能只删不补。

## Review Focus

1. **子表的外键列没有任何非空值**（空的归档表、全是 NULL 的列）：命中率应为 None（未验证），外键保留并列出，不能算成 0 而被丢掉。对应 Task 1 的 `test_fk_hit_rate_without_child_values_is_unverified`。
2. **`id` 这种通用键名**：永远不作为推断外键的依据。EU_soccer 的 `Match.id` 和 `Player_Attributes.id` 都是从 1 开始的自增编号，小表的值天然包含在大表里。对应 Task 2 的 `test_infer_fk_skips_generic_id_columns`。
3. **表名、列名带空格或连字符**：剖析和列统计都不能出错。对应 Task 5 的 `test_col_stats_on_quoted_names`。
4. **按取值推断时，小整数 ID 同时落在好几张表的键里**：必须因为有歧义而拒绝。对应 Task 3 的 `test_infer_by_value_rejects_ambiguous_match`。
5. **自引用外键**（`employees.manager_id → employees`）：向下遍历不能死循环，`down` 和 `up` 里都不能包含锚点自己。对应 Task 7 的 `test_anchor_self_reference_does_not_loop`。

---

### Task 1: 外键命中率验证

**Files:**
- Create: `DySQL-Bench/tests/_sqlite_fixtures.py`, `DySQL-Bench/tests/__init__.py`（空文件，如已存在则跳过）
- Modify: `DySQL-Bench/dysql_bench/db_select.py`
- Modify: `DySQL-Bench/tests/test_db_select.py`

**Interfaces:**
- Produces:
  - `_q(name) -> str`
  - `_open(path) -> sqlite3.Connection`
  - `declared_fks(p) -> list[dict]`
  - `fk_hit_rate(c, fk, p) -> float | None`
  - `validate_fks(p, fks) -> list[dict]`
- fk dict 的统一格式：`{"table", "cols", "ref_table", "ref_cols", "source", "hit"}`。
  - `source` 取值：`declared` / `name` / `value` / `extra`。
  - `hit` 是保留 3 位小数的 float，或 None（未验证）。

- [ ] **Step 1: 把测试 fixture 抽到共享文件**

创建 `DySQL-Bench/tests/_sqlite_fixtures.py`：

```python
# tests/_sqlite_fixtures.py
import sqlite3


def make_db(tmp_path, name, script):
    p = tmp_path / f"{name}.sqlite"
    c = sqlite3.connect(p); c.executescript("BEGIN;" + script + "COMMIT;"); c.close()
    return str(p)


def rows(table, n, fmt):
    return "".join(f"INSERT INTO {table} VALUES ({fmt(i)});" for i in range(n))


SHOP = """
CREATE TABLE customers (customer_id INTEGER PRIMARY KEY, first_name TEXT, last_name TEXT);
CREATE TABLE products (product_id INTEGER PRIMARY KEY, name TEXT, price REAL);
CREATE TABLE orders (order_id INTEGER PRIMARY KEY, customer_id INTEGER REFERENCES customers(customer_id),
                     product_id INTEGER REFERENCES products(product_id), qty INTEGER);
""" + rows("customers", 60, lambda i: f"{i},'a{i}','b{i}'") \
    + rows("products", 60, lambda i: f"{i},'p{i}',1.0") \
    + rows("orders", 100, lambda i: f"{i},{i%60},{i%60},1")
```

在 `tests/test_db_select.py` 顶部删掉 `_db`、`_rows`、`SHOP` 三个定义，换成：

```python
from tests._sqlite_fixtures import make_db as _db, rows as _rows, SHOP
```

- [ ] **Step 2: 确认迁移没有破坏现有测试**

Run: `cd DySQL-Bench && ~/miniconda3/envs/dysql/bin/python -m pytest -q tests/test_db_select.py`
Expected: 18 passed

- [ ] **Step 3: 写失败测试**

在 `tests/test_db_select.py` 的 import 行加上 `declared_fks, validate_fks`，文件末尾追加：

```python
# --- Task 1: FK hit rate ---

def test_validate_fks_hit_rate_counts_non_empty_child_values(tmp_path):
    p = profile_db(_db(tmp_path, "half", """
        CREATE TABLE customers (customer_id INTEGER PRIMARY KEY);
        CREATE TABLE orders (order_id INTEGER PRIMARY KEY, customer_id INTEGER REFERENCES customers(customer_id));
        INSERT INTO customers VALUES (1),(2);
        INSERT INTO orders VALUES (1,1),(2,2),(3,9),(4,8),(5,NULL),(6,'');"""))
    assert validate_fks(p, declared_fks(p)) == [{"table": "orders", "cols": ["customer_id"], "ref_table": "customers",
                                                 "ref_cols": ["customer_id"], "source": "declared", "hit": 0.5}]

def test_fk_hit_rate_without_child_values_is_unverified(tmp_path):
    p = profile_db(_db(tmp_path, "empty", """
        CREATE TABLE customers (customer_id INTEGER PRIMARY KEY);
        CREATE TABLE orders (order_id INTEGER PRIMARY KEY, customer_id INTEGER REFERENCES customers(customer_id));
        CREATE TABLE archive (order_id INTEGER PRIMARY KEY, customer_id INTEGER REFERENCES customers(customer_id));
        INSERT INTO customers VALUES (1);
        INSERT INTO orders VALUES (1,NULL),(2,'');"""))
    assert [f["hit"] for f in validate_fks(p, declared_fks(p))] == [None, None]

def test_fk_hit_rate_resolves_ref_table_case_insensitively(tmp_path):
    p = profile_db(_db(tmp_path, "case", """
        CREATE TABLE customers (customer_id INTEGER PRIMARY KEY);
        CREATE TABLE orders (order_id INTEGER PRIMARY KEY, customer_id INTEGER REFERENCES Customers(customer_id));
        INSERT INTO customers VALUES (1);
        INSERT INTO orders VALUES (1,1);"""))
    f = validate_fks(p, declared_fks(p))[0]
    assert f["ref_table"] == "customers" and f["hit"] == 1.0

def test_fk_hit_rate_fills_omitted_ref_column_with_pk(tmp_path):
    p = profile_db(_db(tmp_path, "omit", """
        CREATE TABLE customers (customer_id INTEGER PRIMARY KEY);
        CREATE TABLE orders (order_id INTEGER PRIMARY KEY, customer_id INTEGER REFERENCES customers);
        INSERT INTO customers VALUES (1);
        INSERT INTO orders VALUES (1,1),(2,2);"""))
    f = validate_fks(p, declared_fks(p))[0]
    assert f["ref_cols"] == ["customer_id"] and f["hit"] == 0.5
```

- [ ] **Step 4: 确认测试失败**

Run: `cd DySQL-Bench && ~/miniconda3/envs/dysql/bin/python -m pytest -q tests/test_db_select.py -k "validate_fks or fk_hit_rate"`
Expected: ImportError（`declared_fks` 不存在）

- [ ] **Step 5: 实现**

在 `dysql_bench/db_select.py` 的 `UNIQUE_SCAN_MAX_ROWS` 下面加：

```python
def _q(name):
    return '"' + name.replace('"', '""') + '"'


def _open(path):
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)
```

`profile_db` 整个换成下面的版本。只改了打开方式和引号，逻辑不变：

```python
def profile_db(path):
    c = _open(path)
    names = [r[0] for r in c.execute("select name from sqlite_master where type='table' "
                                     "and name not like 'sqlite_%' order by rowid")]
    tables = []
    for t in names:
        info = c.execute(f"pragma table_info({_q(t)})").fetchall()
        cols = [i[1] for i in info]
        fks = {}
        for r in c.execute(f"pragma foreign_key_list({_q(t)})").fetchall():
            f = fks.setdefault(r[0], {"cols": [], "ref_table": r[2], "ref_cols": []})
            f["cols"].append(r[3]); f["ref_cols"].append(r[4])
        pk = [i[1] for i in sorted(info, key=lambda i: i[5]) if i[5] > 0]
        rows = c.execute(f"select count(*) from {_q(t)}").fetchone()[0]
        scan = 0 < rows <= UNIQUE_SCAN_MAX_ROWS
        unique = [x for x in cols if ID_LIKE.search(x) and c.execute(
            f"select count(distinct {_q(x)}) = count(*) and count({_q(x)}) = count(*) from {_q(t)}").fetchone()[0]] \
            if not pk and scan else []
        tables.append({"name": t, "cols": cols, "pk": pk, "unique_keys": unique,
                       "fks": list(fks.values()), "rows": rows})
    c.close()
    return {"db": os.path.splitext(os.path.basename(path))[0], "path": path,
            "size_mb": os.path.getsize(path) / 2**20, "tables": tables}
```

在 `infer_fks` 前面加：

```python
def declared_fks(p):
    """Flatten the per-table PRAGMA foreign keys into the common fk dict format."""
    return [{"table": t["name"], "cols": f["cols"], "ref_table": f["ref_table"], "ref_cols": f["ref_cols"],
             "source": "declared"} for t in p["tables"] for f in t["fks"]]


def _resolve_ref_cols(ref, ref_cols):
    """Fill ref columns omitted in the DDL (`REFERENCES customers`) with the referenced table's PK."""
    if all(rc is None for rc in ref_cols) and len(ref["pk"]) == len(ref_cols):
        return list(ref["pk"])
    return [rc or (ref["pk"][0] if len(ref["pk"]) == 1 else None) for rc in ref_cols]


def fk_hit_rate(c, fk, p):
    """Share of the child's non-null, non-empty key values found in the referenced table.
    None when there is nothing to check (empty child, or every value empty): unverified, not wrong."""
    tables = {t["name"].lower(): t for t in p["tables"]}
    ref = tables.get(fk["ref_table"].lower())
    if not ref or any(rc is None for rc in fk["ref_cols"]):
        return 0.0
    cols = ", ".join(_q(x) for x in fk["cols"])
    rcols = ", ".join(_q(x) for x in fk["ref_cols"])
    notnull = " AND ".join(f"{_q(x)} IS NOT NULL AND {_q(x)} != ''" for x in fk["cols"])
    n, hit = c.execute(f"SELECT count(*), coalesce(sum(({cols}) IN (SELECT {rcols} FROM {_q(ref['name'])})), 0) "
                       f"FROM {_q(fk['table'])} WHERE {notnull}").fetchone()
    return hit / n if n else None


def validate_fks(p, fks):
    """Resolve ref table names/columns and attach the data-checked hit rate (None = unverified) to every fk."""
    tables = {t["name"].lower(): t for t in p["tables"]}
    c = _open(p["path"])
    out = []
    for f in fks:
        ref = tables.get(f["ref_table"].lower())
        g = {**f, "ref_table": ref["name"] if ref else f["ref_table"],
             "ref_cols": _resolve_ref_cols(ref, f["ref_cols"]) if ref else f["ref_cols"]}
        h = fk_hit_rate(c, g, p)
        g["hit"] = None if h is None else round(h, 3)
        out.append(g)
    c.close()
    return out
```

- [ ] **Step 6: 确认测试通过**

Run: `cd DySQL-Bench && ~/miniconda3/envs/dysql/bin/python -m pytest -q tests/test_db_select.py`
Expected: 22 passed

- [ ] **Step 7: Commit**

```bash
git add DySQL-Bench/tests/_sqlite_fixtures.py DySQL-Bench/tests/__init__.py DySQL-Bench/tests/test_db_select.py DySQL-Bench/dysql_bench/db_select.py
git commit -m "feat(db_select): validate every FK by data hit rate; empty children stay unverified

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: 按名字推断外键的规则修正

**Files:**
- Create: `DySQL-Bench/dysql_bench/db_anchor.py`（先只放三个常量）
- Modify: `DySQL-Bench/dysql_bench/db_select.py`（常量区、`infer_fks`）
- Modify: `DySQL-Bench/tests/test_db_select.py`

**Interfaces:**
- Produces:
  - `db_anchor.PERSON`、`db_anchor.NAME_COLS`、`db_anchor.GUID`：从 `db_select` 搬过来，`db_select` 改为从这里 import。
  - `db_select.GENERIC_KEYS`
  - `db_select._fk_candidate(col) -> bool`
- `infer_fks(p)` 输出的每条 fk 带 `"source": "name"`。
- 规则：
  - 跳过：声明过的列、guid 列、非 ID 类列、通用键名（`id`/`rowid`/`pk`/`key`/`code`）。
  - 本表自己的行键（单列主键或检测出的唯一键）只能引用**行数严格更多**的表，即 1:1 扩展表。
  - 复合主键的成员列是普通候选。

- [ ] **Step 1: 写失败测试**

把 `tests/test_db_select.py` 里三个现有测试的期望值加上 `"source": "name"`：`test_infer_fk_from_matching_pk_name`、`test_infer_fk_from_table_name_plus_id`、`test_infer_fk_uses_unique_key_when_ref_has_no_pk`。例如第一个改为：

```python
    assert infer_fks(p) == [{"table": "orders", "cols": ["customer_id"],
                             "ref_table": "customers", "ref_cols": ["customer_id"], "source": "name"}]
```

文件末尾追加：

```python
# --- Task 2: name-based inference ---

def test_infer_fk_ignores_guid_columns(tmp_path):
    # AdventureWorks: a table whose only unique id-like column is rowguid makes every other rowguid 'reference' it
    p = profile_db(_db(tmp_path, "guid", """
        CREATE TABLE product (productid INTEGER PRIMARY KEY, rowguid TEXT);
        CREATE TABLE salesorderdetail (salesorderdetailid INTEGER PRIMARY KEY, productid INTEGER, rowguid TEXT);
        CREATE TABLE productmodelculture (productmodelid INTEGER, cultureid TEXT, rowguid TEXT);
        INSERT INTO product VALUES (1,'g1'),(2,'g2');
        INSERT INTO salesorderdetail VALUES (1,1,'g3'),(2,2,'g4');
        INSERT INTO productmodelculture VALUES (1,'en','g5'),(1,'en','g6');"""))
    assert [(f["table"], f["cols"][0], f["ref_table"]) for f in infer_fks(p)] == \
        [("salesorderdetail", "productid", "product")]

def test_infer_fk_skips_generic_id_columns(tmp_path):
    # both ids run 1..N, so the smaller one is 'contained' in the larger by coincidence (EU_soccer Match/Player_Attributes)
    p = profile_db(_db(tmp_path, "gen", """
        CREATE TABLE Match (id INTEGER PRIMARY KEY, season TEXT);
        CREATE TABLE Player_Attributes (id INTEGER PRIMARY KEY, rating INTEGER);
    """ + _rows("Match", 5, lambda i: f"{i},'s'") + _rows("Player_Attributes", 10, lambda i: f"{i},1")))
    assert infer_fks(p) == []

def test_infer_fk_from_composite_pk_member(tmp_path):
    # BowlingLeague: the archive's BowlerID is part of its PK and still points at Bowlers
    p = profile_db(_db(tmp_path, "bowl", """
        CREATE TABLE Bowlers (BowlerID INTEGER PRIMARY KEY, BowlerLastName TEXT);
        CREATE TABLE Bowler_Scores_Archive (MatchID INTEGER, GameNumber INTEGER, BowlerID INTEGER, RawScore INTEGER,
                                            PRIMARY KEY (MatchID, GameNumber, BowlerID));"""))
    assert [(f["table"], f["cols"][0], f["ref_table"]) for f in infer_fks(p)] == \
        [("Bowler_Scores_Archive", "BowlerID", "Bowlers")]

def test_infer_fk_one_to_one_extension_needs_larger_parent(tmp_path):
    # complex_oracle: supplementary_demographics.cust_id is its own PK and references customers (55,500 > 4,500 rows)
    p = profile_db(_db(tmp_path, "ext", """
        CREATE TABLE customers (cust_id INTEGER PRIMARY KEY, cust_first_name TEXT);
        CREATE TABLE supplementary_demographics (cust_id INTEGER PRIMARY KEY, occupation TEXT);
    """ + _rows("customers", 3, lambda i: f"{i},'c{i}'") + _rows("supplementary_demographics", 2, lambda i: f"{i},'o'")))
    assert [(f["table"], f["cols"][0], f["ref_table"]) for f in infer_fks(p)] == \
        [("supplementary_demographics", "cust_id", "customers")]
```

- [ ] **Step 2: 确认测试失败**

Run: `cd DySQL-Bench && ~/miniconda3/envs/dysql/bin/python -m pytest -q tests/test_db_select.py -k infer`
Expected: 5 failed, 2 passed。
- 失败的 5 个：
  - 三个旧测试：输出里还没有 `source`。
  - `test_infer_fk_ignores_guid_columns`：旧代码推断出了两条指向 `productmodelculture.rowguid` 的伪外键。
  - `test_infer_fk_one_to_one_extension_needs_larger_parent`：cust_id 是本表主键，被跳过了。
- 通过的 2 个：`test_infer_fk_skips_generic_id_columns` 和 `test_infer_fk_from_composite_pk_member`。旧代码本来就对，它们是给新的 1:1 规则设的回归护栏。

- [ ] **Step 3: 实现**

创建 `dysql_bench/db_anchor.py`：

```python
"""Anchors and update targets: the structure a DySQL-style task needs.
A task is anchored on a row (a person, or an entity such as a car or a recipe) and writes rows in the anchor's
scope: the anchor, the tables below it (<= 2 FK hops) and their parent tables.
Evidence: docs/data_gen/dysql_task_types.md. This module must not import db_select (db_select imports it)."""
import re

PERSON = re.compile(r"customer|client|employee|staff|member|player|user|student|patient|person|people|"
                    r"author|driver|agent|bowler|entertainer|actor|athlete|teacher|faculty|professor|"
                    r"instructor|doctor|physician|nurse|cyclist|voter|owner|guest|visitor|passenger|"
                    r"seller|buyer|investor|pilot|legislator|contact|coach|manager|artist|singer|"
                    r"wrestler|reviewer|donor|officer|swimmer|gymnast|scientist|musician|editor|journalist|candidate")
NAME_COLS = {"firstname", "lastname", "fname", "lname", "fullname", "first", "last",
             "surname", "givenname", "familyname", "forename"}
GUID = re.compile(r"guid|uuid", re.I)
```

在 `dysql_bench/db_select.py` 里：
- 删掉 `PERSON = ...` 和 `NAME_COLS = ...` 两个定义。
- 在 import 行下面加 `from dysql_bench.db_anchor import PERSON, NAME_COLS, GUID`。
- 在 `ID_LIKE` 下面加：

```python
GENERIC_KEYS = {"id", "rowid", "pk", "key", "code"}  # never FK evidence: Match.id vs Player_Attributes.id both run 1..N
```

在 `row_key` 后面加：

```python
def _fk_candidate(col):
    return bool(ID_LIKE.search(col)) and not GUID.search(col) and _norm(col) not in GENERIC_KEYS
```

`infer_fks` 换成：

```python
def infer_fks(p):
    """Join keys implied by column names, for DBs that declare few FKs (e.g. Kaggle CSV imports).
    A column that is its table's own row key may only reference a strictly larger table (1:1 extension,
    e.g. supplementary_demographics.cust_id -> customers); composite-PK members are ordinary candidates."""
    keys = {t["name"]: row_key(t) for t in p["tables"] if row_key(t)}
    rows = {t["name"]: t["rows"] for t in p["tables"]}
    out = []
    for t in p["tables"]:
        declared = {c.lower() for f in t["fks"] for c in f["cols"]}
        own = keys.get(t["name"])
        for col in t["cols"]:
            lc = col.lower()
            if lc in declared or not _fk_candidate(col):
                continue
            cands = [r for r, k in keys.items() if r != t["name"] and k.lower() == lc]
            if not cands:
                cands = [r for r in keys if r != t["name"] and
                         re.sub(r"_?id$", "", lc) in {r.lower(), _norm(r)}]
            if col == own:
                cands = [r for r in cands if rows[r] > t["rows"]]
            if len(cands) == 1:
                out.append({"table": t["name"], "cols": [col], "ref_table": cands[0],
                            "ref_cols": [keys[cands[0]]], "source": "name"})
    return out
```

- [ ] **Step 4: 确认测试通过**

Run: `cd DySQL-Bench && ~/miniconda3/envs/dysql/bin/python -m pytest -q tests/test_db_select.py`
Expected: 26 passed

- [ ] **Step 5: Commit**

```bash
git add DySQL-Bench/dysql_bench/db_anchor.py DySQL-Bench/dysql_bench/db_select.py DySQL-Bench/tests/test_db_select.py
git commit -m "fix(db_select): FK name inference skips guid/generic ids, allows composite-PK members and 1:1 extensions

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: 按取值推断以角色命名的外键

**Files:**
- Modify: `DySQL-Bench/dysql_bench/db_select.py`
- Modify: `DySQL-Bench/tests/_sqlite_fixtures.py`（加 `WWE`）
- Modify: `DySQL-Bench/tests/test_db_select.py`

**Interfaces:**
- Consumes: `_open`、`_q`、`_fk_candidate`、`row_key`。
- Produces:
  - `SAMPLE_ROWS = 5000`
  - `infer_fks_by_value(p, covered, min_hit=0.99, min_distinct=20) -> list[dict]`，输出 `source="value"`。
  - 参数 `covered` 是 `{(table, col_lower)}`，即已被声明或按名字推断覆盖的列。

- [ ] **Step 1: 加 fixture，写失败测试**

在 `tests/_sqlite_fixtures.py` 末尾追加：

```python
# 200 wrestlers but only 40 cards: winner/loser ids 0..199 fit Wrestlers only (TEXT ids, like the real WWE DB);
# `champion` is a role-named FK without an id suffix, supplied manually in the tests
WWE = """
CREATE TABLE Wrestlers (id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE Cards (id INTEGER PRIMARY KEY, title TEXT);
CREATE TABLE Matches (id INTEGER PRIMARY KEY, card_id INTEGER, winner_id TEXT, loser_id TEXT, champion INTEGER);
""" + rows("Wrestlers", 200, lambda i: f"{i},'w{i}'") + rows("Cards", 40, lambda i: f"{i},'c{i}'") \
    + rows("Matches", 200, lambda i: f"{i},{i%40},'{i%200}','{(i+1)%200}',{i%200}")
```

`tests/test_db_select.py` 的 fixture import 改为 `from tests._sqlite_fixtures import make_db as _db, rows as _rows, SHOP, WWE`，函数 import 加 `infer_fks_by_value`，末尾追加：

```python
# --- Task 3: value-based inference ---

def test_infer_by_value_finds_role_named_fks(tmp_path):
    p = profile_db(_db(tmp_path, "wwe", WWE))
    covered = {(f["table"], f["cols"][0].lower()) for f in infer_fks(p)}   # card_id -> Cards by name
    got = sorted((f["table"], f["cols"][0], f["ref_table"], f["source"]) for f in infer_fks_by_value(p, covered))
    assert got == [("Matches", "loser_id", "Wrestlers", "value"), ("Matches", "winner_id", "Wrestlers", "value")]

def test_infer_by_value_rejects_ambiguous_match(tmp_path):
    # winner_id values 0..39 exist in both Wrestlers.id and Cards.id -> two candidates -> no FK
    p = profile_db(_db(tmp_path, "amb", """
        CREATE TABLE Wrestlers (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE Cards (id INTEGER PRIMARY KEY, title TEXT);
        CREATE TABLE Matches (id INTEGER PRIMARY KEY, winner_id INTEGER);
    """ + _rows("Wrestlers", 40, lambda i: f"{i},'w{i}'") + _rows("Cards", 40, lambda i: f"{i},'c{i}'")
          + _rows("Matches", 200, lambda i: f"{i},{i%40}")))
    assert infer_fks_by_value(p, set()) == []

def test_infer_by_value_needs_enough_distinct_values(tmp_path):
    p = profile_db(_db(tmp_path, "few", """
        CREATE TABLE Wrestlers (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE Matches (id INTEGER PRIMARY KEY, winner_id INTEGER, note TEXT);
    """ + _rows("Wrestlers", 40, lambda i: f"{i},'w{i}'") + _rows("Matches", 200, lambda i: f"{i},{i%3},'x'")))
    assert infer_fks_by_value(p, set()) == []
```

- [ ] **Step 2: 确认测试失败**

Run: `cd DySQL-Bench && ~/miniconda3/envs/dysql/bin/python -m pytest -q tests/test_db_select.py -k infer_by_value`
Expected: ImportError

- [ ] **Step 3: 实现**

在 `infer_fks` 后面加：

```python
SAMPLE_ROWS = 5000  # rows sampled per column when inferring FKs by value


def infer_fks_by_value(p, covered, min_hit=0.99, min_distinct=20):
    """Role-named FKs (winner_id, loser_id, *_order_id) that no name rule catches: an id-like column whose
    sampled non-empty values (almost) all fall inside exactly one other table's key. `covered` holds
    (table, col_lower) pairs already explained by declared or name-inferred FKs."""
    keys = {t["name"]: row_key(t) for t in p["tables"] if row_key(t)}
    rows = {t["name"]: t["rows"] for t in p["tables"]}
    c = _open(p["path"])
    out = []
    for t in p["tables"]:
        own = keys.get(t["name"])
        for col in t["cols"]:
            if (t["name"], col.lower()) in covered or col == own or not _fk_candidate(col):
                continue
            distinct = c.execute(f"SELECT count(DISTINCT {_q(col)}) FROM {_q(t['name'])}").fetchone()[0]
            if distinct < min_distinct:
                continue
            hits = []
            for ref, k in keys.items():
                if ref == t["name"] or rows[ref] < distinct:
                    continue
                n, h = c.execute(
                    f"SELECT count(*), coalesce(sum({_q(col)} IN (SELECT {_q(k)} FROM {_q(ref)})), 0) FROM "
                    f"(SELECT {_q(col)} FROM {_q(t['name'])} WHERE {_q(col)} IS NOT NULL AND {_q(col)} != '' "
                    f"LIMIT {SAMPLE_ROWS})").fetchone()
                if n and h / n >= min_hit:
                    hits.append(ref)
            if len(hits) == 1:
                out.append({"table": t["name"], "cols": [col], "ref_table": hits[0],
                            "ref_cols": [keys[hits[0]]], "source": "value"})
    c.close()
    return out
```

- [ ] **Step 4: 确认测试通过**

Run: `cd DySQL-Bench && ~/miniconda3/envs/dysql/bin/python -m pytest -q tests/test_db_select.py`
Expected: 29 passed

- [ ] **Step 5: Commit**

```bash
git add DySQL-Bench/dysql_bench/db_select.py DySQL-Bench/tests/_sqlite_fixtures.py DySQL-Bench/tests/test_db_select.py
git commit -m "feat(db_select): infer role-named FKs by value (winner_id/loser_id)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: 复合自然键

**Files:**
- Modify: `DySQL-Bench/dysql_bench/db_select.py`（`profile_db`，新增 `_composite_key`、`is_keyed`）
- Modify: `DySQL-Bench/tests/test_db_select.py`

**Interfaces:**
- Produces:
  - 每个 table dict 新增 `composite_key: list[str]`：两列，或空列表。只对没有主键、没有单列唯一键、行数在 1 到 3M 之间的表计算。
  - `is_keyed(t) -> bool`

- [ ] **Step 1: 写失败测试**

import 加 `is_keyed`，末尾追加：

```python
# --- Task 4: composite keys ---

def test_profile_finds_two_column_composite_key(tmp_path):
    p = profile_db(_db(tmp_path, "ck", """
        CREATE TABLE movie_cast (movie_id INTEGER, person_id INTEGER, role TEXT);
        INSERT INTO movie_cast VALUES (1,1,'a'),(1,2,'b'),(2,1,'c');"""))
    t = p["tables"][0]
    assert t["unique_keys"] == [] and t["composite_key"] == ["movie_id", "person_id"] and is_keyed(t)

def test_composite_key_rejects_duplicates_and_nulls(tmp_path):
    p = profile_db(_db(tmp_path, "nock", """
        CREATE TABLE a (x_id INTEGER, y_id INTEGER, v TEXT);
        INSERT INTO a VALUES (1,1,'a'),(1,1,'b');
        CREATE TABLE b (x_id INTEGER, y_id INTEGER, v TEXT);
        INSERT INTO b VALUES (1,NULL,'a'),(1,2,'b');"""))
    assert [t["composite_key"] for t in p["tables"]] == [[], []]
    assert not is_keyed(p["tables"][0])

def test_single_pk_table_has_no_composite_key(tmp_path):
    p = profile_db(_db(tmp_path, "shop", SHOP))
    assert all(t["composite_key"] == [] for t in p["tables"])
```

- [ ] **Step 2: 确认测试失败**

Run: `cd DySQL-Bench && ~/miniconda3/envs/dysql/bin/python -m pytest -q tests/test_db_select.py -k "composite or single_pk"`
Expected: ImportError

- [ ] **Step 3: 实现**

在 `profile_db` 前面加：

```python
def _composite_key(c, t, cols):
    """First pair of id-like columns that is unique and non-null together (tables without any single key)."""
    ids = [x for x in cols if ID_LIKE.search(x) and not GUID.search(x)][:6]
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            a, b = ids[i], ids[j]
            nulls = c.execute(f"SELECT count(*) FROM {_q(t)} WHERE {_q(a)} IS NULL OR {_q(b)} IS NULL").fetchone()[0]
            dup = c.execute(f"SELECT count(*) FROM (SELECT 1 FROM {_q(t)} GROUP BY {_q(a)}, {_q(b)} "
                            f"HAVING count(*) > 1)").fetchone()[0]
            if not nulls and not dup:
                return [a, b]
    return []
```

在 `profile_db` 里：
- 在 `unique = ...` 后面加 `composite = _composite_key(c, t, cols) if not pk and not unique and scan else []`。
- `tables.append({...})` 里加 `"composite_key": composite`。

在 `row_key` 前面加：

```python
def is_keyed(t):
    return bool(t["pk"] or t["unique_keys"] or t["composite_key"])
```

- [ ] **Step 4: 确认测试通过**

Run: `cd DySQL-Bench && ~/miniconda3/envs/dysql/bin/python -m pytest -q tests/test_db_select.py`
Expected: 32 passed

- [ ] **Step 5: Commit**

```bash
git add DySQL-Bench/dysql_bench/db_select.py DySQL-Bench/tests/test_db_select.py
git commit -m "feat(db_select): detect two-column composite natural keys

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: 列统计

**Files:**
- Modify: `DySQL-Bench/dysql_bench/db_select.py`（`profile_db`，新增 `_col_stats`）
- Modify: `DySQL-Bench/tests/test_db_select.py`

**Interfaces:**
- Produces: 每个 table dict 新增 `stats: {col: {"empty": int, "blank": int, "avg_len": float}}`。
  - `empty`：NULL 或 `''` 的行数。
  - `blank`：恰好是 `''` 的行数。
  - `avg_len`：非空、非 `''` 值的平均 `length()`。
  - 行数为 0 或超过 3M 时，`stats == {}`。

- [ ] **Step 1: 写失败测试**

末尾追加：

```python
# --- Task 5: column stats ---

def test_col_stats_empty_blank_and_avg_len(tmp_path):
    p = profile_db(_db(tmp_path, "st", """
        CREATE TABLE t (id INTEGER PRIMARY KEY, note TEXT, html TEXT);
        INSERT INTO t VALUES (1,'ab',NULL),(2,'',NULL),(3,NULL,'xxxxxxxxxx');"""))
    s = p["tables"][0]["stats"]
    assert s["note"] == {"empty": 2, "blank": 1, "avg_len": 2.0}
    assert s["html"] == {"empty": 2, "blank": 0, "avg_len": 10.0}
    assert s["id"]["empty"] == 0

def test_col_stats_on_quoted_names(tmp_path):
    p = profile_db(_db(tmp_path, "sp", """
        CREATE TABLE "Sales Orders" ("Order Number" TEXT PRIMARY KEY, "Sales Channel" TEXT);
        CREATE TABLE "voice-actors" ("voice-actor" TEXT, movie TEXT);
        INSERT INTO "Sales Orders" VALUES ('o1','web');
        INSERT INTO "voice-actors" VALUES ('Joan','Chicken Little');"""))
    t = {x["name"]: x for x in p["tables"]}
    assert t["Sales Orders"]["stats"]["Sales Channel"]["avg_len"] == 3.0
    assert t["voice-actors"]["stats"]["voice-actor"]["empty"] == 0

def test_col_stats_skipped_for_empty_table(tmp_path):
    p = profile_db(_db(tmp_path, "e", "CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT);"))
    assert p["tables"][0]["stats"] == {}
```

- [ ] **Step 2: 确认测试失败**

Run: `cd DySQL-Bench && ~/miniconda3/envs/dysql/bin/python -m pytest -q tests/test_db_select.py -k col_stats`
Expected: KeyError: 'stats'

- [ ] **Step 3: 实现**

在 `profile_db` 前面加：

```python
def _col_stats(c, t, cols):
    """Per column: rows that are NULL or '', rows that are exactly '', average length of non-empty values."""
    out = {}
    for i in range(0, len(cols), 200):  # SQLite caps result columns at 2000
        part = cols[i:i + 200]
        sel = ", ".join(f"sum({_q(x)} IS NULL OR {_q(x)} = ''), sum({_q(x)} = ''), avg(nullif(length({_q(x)}), 0))"
                        for x in part)
        r = c.execute(f"SELECT {sel} FROM {_q(t)}").fetchone()
        out.update({x: {"empty": r[3 * j] or 0, "blank": r[3 * j + 1] or 0, "avg_len": float(r[3 * j + 2] or 0.0)}
                    for j, x in enumerate(part)})
    return out
```

在 `profile_db` 里：
- 在 `composite = ...` 后面加 `stats = _col_stats(c, t, cols) if scan else {}`。
- `tables.append({...})` 里加 `"stats": stats`。

- [ ] **Step 4: 确认测试通过**

Run: `cd DySQL-Bench && ~/miniconda3/envs/dysql/bin/python -m pytest -q tests/test_db_select.py`
Expected: 35 passed

- [ ] **Step 5: Commit**

```bash
git add DySQL-Bench/dysql_bench/db_select.py DySQL-Bench/tests/test_db_select.py
git commit -m "feat(db_select): per-column empty share and average length in profiles

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: 更新目标

**Files:**
- Modify: `DySQL-Bench/dysql_bench/db_anchor.py`
- Create: `DySQL-Bench/tests/test_db_anchor.py`

**Interfaces:**
- Consumes: Task 4、5 的 table dict（`pk`、`unique_keys`、`composite_key`、`stats`、`rows`、`cols`），以及 `keys = {table: row_key}`。
- Produces:
  - `own_key_cols(t, key) -> set`
  - `updatable_cols(t, key, max_avg_len) -> list[str]`
  - `update_targets(p, keys, max_avg_len) -> dict[str, list[str]]`
- 规则：
  - **可修改列：** 排除本行自己的键、guid 列、全空的列、长文本列。**外键列算可修改列。**
  - **更新目标：** 至少 1 行，并且至少有 1 个可修改列。没有更高的行数下限。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_db_anchor.py`：

```python
# tests/test_db_anchor.py
from dysql_bench.db_select import profile_db, declared_fks, validate_fks, infer_fks, row_key
from dysql_bench.db_anchor import updatable_cols, update_targets
from tests._sqlite_fixtures import make_db as _db, rows as _rows, SHOP

def _keys(p):
    return {t["name"]: row_key(t) for t in p["tables"] if row_key(t)}

# --- Task 6: update targets ---

def test_updatable_cols_allow_fks_but_not_own_key_guid_empty_or_long(tmp_path):
    p = profile_db(_db(tmp_path, "u", """
        CREATE TABLE orders (order_id INTEGER PRIMARY KEY, customer_id INTEGER, qty INTEGER, note TEXT,
                             rowguid TEXT, html TEXT, gone TEXT);
    """ + _rows("orders", 10, lambda i: f"{i},{i},1,'n','g{i}','{'x' * 300}',NULL")))
    assert updatable_cols(p["tables"][0], "order_id", max_avg_len=200) == ["customer_id", "qty", "note"]

def test_update_targets_need_a_row_and_an_updatable_column(tmp_path):
    p = profile_db(_db(tmp_path, "t", SHOP + """
        CREATE TABLE playlist_track (playlist_id INTEGER, track_id INTEGER, PRIMARY KEY (playlist_id, track_id));
        INSERT INTO playlist_track VALUES (1,1),(1,2);
        CREATE TABLE orders_archive (order_id INTEGER PRIMARY KEY, qty INTEGER);"""))
    assert update_targets(p, _keys(p), 200) == {"customers": ["first_name", "last_name"], "products": ["name", "price"],
                                                "orders": ["customer_id", "product_id", "qty"]}
```

- [ ] **Step 2: 确认测试失败**

Run: `cd DySQL-Bench && ~/miniconda3/envs/dysql/bin/python -m pytest -q tests/test_db_anchor.py`
Expected: ImportError（`updatable_cols` 不存在）

- [ ] **Step 3: 实现**

在 `dysql_bench/db_anchor.py` 的常量下面追加：

```python
LABEL = re.compile(r"(name|title|label)$", re.I)


def _norm(name):
    s = re.sub(r"[^a-z0-9]", "", name.lower())
    return s[:-1] if s.endswith("s") else s


def own_key_cols(t, key):
    """Columns that identify the row itself: declared PK, else the chosen single key, else the composite key."""
    return set(t["pk"]) or ({key} if key else set(t["composite_key"]))


def updatable_cols(t, key, max_avg_len):
    """Columns an UPDATE can set: anything but the row's own key, guid columns, all-empty and long-text columns.
    FK columns count: 37% of DySQL's gold UPDATEs reassign an FK (SET AgentID = 2)."""
    own = own_key_cols(t, key)
    out = []
    for col in t["cols"]:
        s = t["stats"].get(col)
        if col in own or GUID.search(col) or s is None:
            continue
        if s["empty"] >= t["rows"] or s["avg_len"] > max_avg_len:
            continue
        out.append(col)
    return out


def update_targets(p, keys, max_avg_len):
    """Tables an UPDATE can hit: >= 1 row and >= 1 updatable column, as name -> updatable columns.
    No larger row minimum: DySQL updates tables of 4-46 rows (Agents 9, position 4)."""
    out = {}
    for t in p["tables"]:
        if t["rows"] < 1:
            continue
        cols = updatable_cols(t, keys.get(t["name"]), max_avg_len)
        if cols:
            out[t["name"]] = cols
    return out
```

- [ ] **Step 4: 确认测试通过**

Run: `cd DySQL-Bench && ~/miniconda3/envs/dysql/bin/python -m pytest -q tests/test_db_anchor.py tests/test_db_select.py`
Expected: 37 passed

- [ ] **Step 5: Commit**

```bash
git add DySQL-Bench/dysql_bench/db_anchor.py DySQL-Bench/tests/test_db_anchor.py
git commit -m "feat(db_anchor): update targets; FK columns count as updatable

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: 锚点、锚点类型与范围

**Files:**
- Modify: `DySQL-Bench/dysql_bench/db_anchor.py`（下面给出完整文件）
- Modify: `DySQL-Bench/tests/test_db_anchor.py`

**Interfaces:**
- Consumes: Task 6 的 `update_targets`，以及 Task 1 格式的 fk 列表（只传可用的外键）。
- Produces:
  - `anchor_kind(name, cols) -> "person_named" | "person_id_only" | "entity"`
  - `name_cols(cols)`
  - `label_cols(p, table, fks)`：实体的名称列。锚点表自己没有时，到"单列主键引用锚点"的 1:1 表里找，写作 `表.列`。
  - `reachable_down(fks, start, max_hops) -> list[str]`：沿外键反方向（被引用表 → 引用它的表）BFS，不含 start。
  - `parents(fks, names) -> list[str]`：`names` 引用的表，不含 `names` 自己。
  - `anchors(p, fks, keys, targets, min_rows, max_hops=2) -> list[dict]`，每项为 `{"table", "key", "kind", "rows", "names", "down", "up", "update_targets"}`。
  - `entity_rank(a)`：实体锚点的排序键。
- 锚点条件：
  - 有单列键，行数 ≥ min_rows。
  - `down` 非空；或者没有下游但类型是 `person_named`，这时它自己就是写入目标，比如"改我的工资"。
  - 范围（锚点 + down + up）里至少有一个更新目标。
- 范围包括 `up`，因为 DySQL 有 19% 的任务改公共数据（`docs/data_gen/dysql_task_types.md` 第 2、3 类）。

- [ ] **Step 1: 写失败测试**

`tests/test_db_anchor.py` 的 db_anchor import 改为：

```python
from dysql_bench.db_anchor import (updatable_cols, update_targets, anchor_kind, reachable_down, anchors,
                                   entity_rank)
```

在 `_keys` 下面加：

```python
def _anchors(p, fks, min_rows=5):
    return {a["table"]: a for a in anchors(p, fks, _keys(p), update_targets(p, _keys(p), 200), min_rows)}
```

末尾追加：

```python
# --- Task 7: anchors ---

def test_anchor_kind():
    assert anchor_kind("customers", ["id", "email"]) == "person_id_only"
    assert anchor_kind("customers", ["id", "first_name", "last_name"]) == "person_named"
    assert anchor_kind("Wrestlers", ["id", "name"]) == "person_named"
    assert anchor_kind("Player", ["id", "player_name"]) == "person_named"
    assert anchor_kind("superhero", ["id", "superhero_name", "full_name"]) == "person_named"
    assert anchor_kind("congress", ["cognress_rep_id", "first_name", "last_name"]) == "person_named"
    assert anchor_kind("users", ["userid", "age", "u_gender"]) == "person_id_only"
    assert anchor_kind("Recipe", ["recipe_id", "title"]) == "entity"
    assert anchor_kind("Team", ["id", "team_name"]) == "entity"

def test_anchors_shop(tmp_path):
    p = profile_db(_db(tmp_path, "shop", SHOP))
    a = _anchors(p, validate_fks(p, declared_fks(p)))
    assert set(a) == {"customers", "products"}
    assert a["customers"] == {"table": "customers", "key": "customer_id", "kind": "person_named", "rows": 60,
                              "names": ["first_name", "last_name"], "down": ["orders"], "up": ["products"],
                              "update_targets": ["customers", "orders", "products"]}
    assert a["products"]["kind"] == "entity" and a["products"]["names"] == ["name"] and a["products"]["up"] == ["customers"]

def test_entity_anchor_needs_a_child(tmp_path):
    # cookbook-like: Recipe is an entity anchor because Quantity hangs off it; so is the lookup table Unit,
    # which is why entity anchors are ranked (entity_rank) and confirmed by a human for entity-only DBs
    p = profile_db(_db(tmp_path, "cook", """
        CREATE TABLE Recipe (recipe_id INTEGER PRIMARY KEY, title TEXT);
        CREATE TABLE Unit (unit_id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE Quantity (quantity_id INTEGER PRIMARY KEY, recipe_id INTEGER REFERENCES Recipe(recipe_id),
                               unit_id INTEGER, amount REAL);
    """ + _rows("Recipe", 60, lambda i: f"{i},'r{i}'") + _rows("Unit", 8, lambda i: f"{i},'u{i}'")
          + _rows("Quantity", 120, lambda i: f"{i},{i%60},{i%8},1.0")))
    a = _anchors(p, validate_fks(p, declared_fks(p) + infer_fks(p)))
    assert a["Recipe"]["down"] == ["Quantity"] and a["Recipe"]["names"] == ["title"] and a["Recipe"]["up"] == ["Unit"]
    assert [x["table"] for x in sorted(a.values(), key=entity_rank)] == ["Recipe", "Unit"]
    p2 = profile_db(_db(tmp_path, "lookup", """
        CREATE TABLE Recipe (recipe_id INTEGER PRIMARY KEY, title TEXT);
        CREATE TABLE Unit (unit_id INTEGER PRIMARY KEY, name TEXT);
    """ + _rows("Recipe", 60, lambda i: f"{i},'r{i}'") + _rows("Unit", 8, lambda i: f"{i},'u{i}'")))
    assert _anchors(p2, []) == {}

def test_named_person_may_be_its_own_target_but_id_only_may_not(tmp_path):
    p = profile_db(_db(tmp_path, "hr", """
        CREATE TABLE employees (employee_id INTEGER PRIMARY KEY, first_name TEXT, salary REAL);
        CREATE TABLE users (userid INTEGER PRIMARY KEY, age INTEGER);
    """ + _rows("employees", 60, lambda i: f"{i},'e{i}',100.0") + _rows("users", 60, lambda i: f"{i},30")))
    a = _anchors(p, [])
    assert [(x["table"], x["kind"], x["update_targets"]) for x in a.values()] == \
        [("employees", "person_named", ["employees"])]

def test_anchor_two_hops_and_only_given_fks_are_followed(tmp_path):
    p = profile_db(_db(tmp_path, "hops", """
        CREATE TABLE customers (customer_id INTEGER PRIMARY KEY, first_name TEXT);
        CREATE TABLE invoices (invoice_id INTEGER PRIMARY KEY, customer_id INTEGER REFERENCES customers(customer_id));
        CREATE TABLE invoice_items (item_id INTEGER PRIMARY KEY, invoice_id INTEGER REFERENCES invoices(invoice_id), qty INTEGER);
    """ + _rows("customers", 60, lambda i: f"{i},'c{i}'") + _rows("invoices", 60, lambda i: f"{i},{i}")
          + _rows("invoice_items", 100, lambda i: f"{i},{i%60},1")))
    fks = validate_fks(p, declared_fks(p))
    assert _anchors(p, fks)["customers"]["down"] == ["invoices", "invoice_items"]
    assert _anchors(p, [f for f in fks if f["table"] == "invoices"])["customers"]["down"] == ["invoices"]

def test_anchor_self_reference_does_not_loop(tmp_path):
    p = profile_db(_db(tmp_path, "self", """
        CREATE TABLE employees (employee_id INTEGER PRIMARY KEY, first_name TEXT,
                                manager_id INTEGER REFERENCES employees(employee_id));
    """ + _rows("employees", 60, lambda i: f"{i},'e{i}',{(i+1)%60}")))
    fks = validate_fks(p, declared_fks(p))
    assert reachable_down(fks, "employees", 2) == []
    a = _anchors(p, fks)["employees"]
    assert a["down"] == [] and a["up"] == []

def test_entity_label_from_one_to_one_table(tmp_path):
    # cars: price(ID, price) has no name; data(ID -> price.ID, car_name) does
    p = profile_db(_db(tmp_path, "cars", """
        CREATE TABLE price (ID INTEGER PRIMARY KEY, price REAL);
        CREATE TABLE data (ID INTEGER PRIMARY KEY REFERENCES price(ID), mpg REAL, car_name TEXT);
        CREATE TABLE production (ID INTEGER REFERENCES price(ID), model_year INTEGER, country INTEGER,
                                 PRIMARY KEY (ID, model_year));
    """ + _rows("price", 60, lambda i: f"{i},1000.0") + _rows("data", 60, lambda i: f"{i},20.0,'car {i}'")
          + _rows("production", 100, lambda i: f"{i%60},{70 + i//60},1")))
    a = _anchors(p, validate_fks(p, declared_fks(p)))
    assert set(a) == {"price"} and a["price"]["names"] == ["data.car_name"] and a["price"]["down"] == ["data", "production"]
```

- [ ] **Step 2: 确认测试失败**

Run: `cd DySQL-Bench && ~/miniconda3/envs/dysql/bin/python -m pytest -q tests/test_db_anchor.py`
Expected: ImportError（`anchor_kind` 不存在）

- [ ] **Step 3: 实现（完整文件）**

`dysql_bench/db_anchor.py` 的最终内容：

```python
"""Anchors and update targets: the structure a DySQL-style task needs.
A task is anchored on a row (a person, or an entity such as a car or a recipe) and writes rows in the anchor's
scope: the anchor, the tables below it (<= 2 FK hops) and their parent tables.
Evidence: docs/data_gen/dysql_task_types.md. This module must not import db_select (db_select imports it)."""
import re
from collections import deque

PERSON = re.compile(r"customer|client|employee|staff|member|player|user|student|patient|person|people|"
                    r"author|driver|agent|bowler|entertainer|actor|athlete|teacher|faculty|professor|"
                    r"instructor|doctor|physician|nurse|cyclist|voter|owner|guest|visitor|passenger|"
                    r"seller|buyer|investor|pilot|legislator|contact|coach|manager|artist|singer|"
                    r"wrestler|reviewer|donor|officer|swimmer|gymnast|scientist|musician|editor|journalist|candidate")
NAME_COLS = {"firstname", "lastname", "fname", "lname", "fullname", "first", "last",
             "surname", "givenname", "familyname", "forename"}
GUID = re.compile(r"guid|uuid", re.I)
LABEL = re.compile(r"(name|title|label)$", re.I)


def _norm(name):
    s = re.sub(r"[^a-z0-9]", "", name.lower())
    return s[:-1] if s.endswith("s") else s


def own_key_cols(t, key):
    """Columns that identify the row itself: declared PK, else the chosen single key, else the composite key."""
    return set(t["pk"]) or ({key} if key else set(t["composite_key"]))


def updatable_cols(t, key, max_avg_len):
    """Columns an UPDATE can set: anything but the row's own key, guid columns, all-empty and long-text columns.
    FK columns count: 37% of DySQL's gold UPDATEs reassign an FK (SET AgentID = 2)."""
    own = own_key_cols(t, key)
    out = []
    for col in t["cols"]:
        s = t["stats"].get(col)
        if col in own or GUID.search(col) or s is None:
            continue
        if s["empty"] >= t["rows"] or s["avg_len"] > max_avg_len:
            continue
        out.append(col)
    return out


def update_targets(p, keys, max_avg_len):
    """Tables an UPDATE can hit: >= 1 row and >= 1 updatable column, as name -> updatable columns.
    No larger row minimum: DySQL updates tables of 4-46 rows (Agents 9, position 4)."""
    out = {}
    for t in p["tables"]:
        if t["rows"] < 1:
            continue
        cols = updatable_cols(t, keys.get(t["name"]), max_avg_len)
        if cols:
            out[t["name"]] = cols
    return out


def anchor_kind(name, cols):
    """person_named: a person-like table with a name column, or any table with first/last/full-name columns;
    person_id_only: person-like table without names; entity: everything else (car, recipe, team)."""
    norm = [_norm(c) for c in cols]
    person = bool(PERSON.search(name.lower()))
    if any(c in NAME_COLS for c in norm) or (person and any(c.endswith("name") for c in norm)):
        return "person_named"
    return "person_id_only" if person else "entity"


def name_cols(cols):
    return [c for c in cols if _norm(c) in NAME_COLS or _norm(c).endswith("name")]


def label_cols(p, table, fks):
    """How an entity is referred to: its own name/title columns, else those of a 1:1 table whose single-column
    PK references it (cars: price has no name, data.car_name does)."""
    tables = {t["name"]: t for t in p["tables"]}
    own = [c for c in tables[table]["cols"] if LABEL.search(c)]
    if own:
        return own
    out = []
    for f in fks:
        child = tables.get(f["table"])
        if f["ref_table"] == table and child and child["pk"] == f["cols"]:
            out += [f"{child['name']}.{c}" for c in child["cols"] if LABEL.search(c)]
    return out


def reachable_down(fks, start, max_hops):
    """Tables that reference `start` directly or through up to max_hops FK edges (child direction), BFS order."""
    children = {}
    for f in fks:
        if f["table"] != f["ref_table"]:
            children.setdefault(f["ref_table"], []).append(f["table"])
    seen, q = {start: 0}, deque([start])
    while q:
        x = q.popleft()
        if seen[x] >= max_hops:
            continue
        for y in children.get(x, []):
            if y not in seen:
                seen[y] = seen[x] + 1
                q.append(y)
    return [x for x in seen if x != start]


def parents(fks, names):
    """Tables referenced by any of `names`, excluding `names` themselves (the 'public' rows a task may also edit)."""
    return sorted({f["ref_table"] for f in fks if f["table"] in names} - set(names))


def anchors(p, fks, keys, targets, min_rows, max_hops=2):
    """Rows a task can be anchored on: a single-column key, >= min_rows rows, at least one table below it
    (a named person may instead be its own write target: 'update my salary'), and an update target in scope."""
    out = []
    for t in p["tables"]:
        key = keys.get(t["name"])
        if not key or t["rows"] < min_rows:
            continue
        kind = anchor_kind(t["name"], t["cols"])
        down = reachable_down(fks, t["name"], max_hops)
        if not down and kind != "person_named":
            continue
        up = parents(fks, [t["name"]] + down)
        upd = [x for x in [t["name"]] + down + up if x in targets]
        if not upd:
            continue
        names = name_cols(t["cols"]) if kind != "entity" else label_cols(p, t["name"], fks)
        out.append({"table": t["name"], "key": key, "kind": kind, "rows": t["rows"], "names": names,
                    "down": down, "up": up, "update_targets": upd})
    return out


def entity_rank(a):
    """Sort key for entity anchors: those with a name/title first, then more tables below, then more rows."""
    return (not a["names"], -len(a["down"]), -a["rows"])
```

- [ ] **Step 4: 确认测试通过**

Run: `cd DySQL-Bench && ~/miniconda3/envs/dysql/bin/python -m pytest -q tests/test_db_anchor.py tests/test_db_select.py`
Expected: 44 passed

- [ ] **Step 5: Commit**

```bash
git add DySQL-Bench/dysql_bench/db_anchor.py DySQL-Bench/tests/test_db_anchor.py
git commit -m "feat(db_anchor): anchors with kind, names/labels, down/up scope and update targets

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: 重写 evaluate，让 CLI 跟上

**Files:**
- Modify: `DySQL-Bench/dysql_bench/db_select.py`（下面给出完整文件）
- Modify: `DySQL-Bench/tests/test_db_select.py`（下面给出完整文件）
- Modify: `DySQL-Bench/scripts/select_dbs.py`（`CFG`、`COLS`、`write`）

**Interfaces:**
- Consumes: Task 1–7 的全部函数。
- Produces:
  - `all_fks(p, extra=()) -> list[dict]`
  - `is_fragmented(p, fks, min_share)`：只用传入的扁平 fk 列表建图。
  - `evaluate(p, cfg, extra_fks=()) -> dict`。
- cfg 的键：
  - 新增：`fk_min_hit`、`anchor_min_rows`、`long_text_avg_len`。
  - 删除：`txn_min_rows`、`require_person`。
- 输出字段：
  - 基本信息：`db, n_tables, n_cols, total_rows, size_mb`。
  - 外键：`n_fks_declared, n_fks_inferred, n_fks_valid, invalid_fks, unverified_fks`。
  - 锚点：`has_person_named, anchor_kinds, person_anchors, entity_anchors, anchors`（完整 dict 列表，给 JSON 用）。
  - 质量标记：`update_targets, targets_no_key, composite_key_tables, long_text_cols, empty_string_cols, fragmented`。
  - 泄漏与结果：`leak_match, max_leak_overlap, table_names, schema, fail_reasons, pass`。
- 字段格式：
  - `invalid_fks` 元素为 `"orders.customer_id->customers 0.0"`；`unverified_fks` 元素为 `"returns.order_id->orders"`。
  - `person_anchors` / `entity_anchors` 元素为 `"customers[first_name,last_name]"`。人物锚点按先有名字、再行数多排序；实体锚点按 `entity_rank` 排序。
  - `n_fks_valid` 只数命中率 ≥ 阈值的外键。规则里用的"可用外键"= 有效外键 + 未验证外键。
- `fail_reasons` 取值：`leak, tables, cols, rows, size, fks, no_update_target, no_anchor, fragmented`。
- 删除 `transaction_tables`、`is_person_table`。

- [ ] **Step 1: 写测试（完整文件）**

`tests/test_db_select.py` 的最终内容。和 Task 5 结束时相比：
- **删除：** `test_person_table_by_name_or_name_columns`、`test_transaction_tables_need_outgoing_fk_and_rows`、`test_evaluate_requires_person_table_only_when_configured`。
- **改写：** `test_fragmented_when_fk_graph_splits`、`test_evaluate_passes_shop`、`test_evaluate_reports_every_failed_rule`，以及 `CFG`。
- **新增：** 5 个 Task 8 测试。

```python
# tests/test_db_select.py
from dysql_bench.db_select import (profile_db, row_key, infer_fks, infer_fks_by_value, declared_fks, validate_fks,
                                   all_fks, is_keyed, schema_items, containment, is_fragmented, evaluate, dedup)
from tests._sqlite_fixtures import make_db as _db, rows as _rows, SHOP, WWE

def test_profile_db_reads_tables_rows_pk_fk(tmp_path):
    p = profile_db(_db(tmp_path, "shop", SHOP))
    t = {x["name"]: x for x in p["tables"]}
    assert set(t) == {"customers", "products", "orders"}
    assert t["orders"]["rows"] == 100
    assert t["orders"]["pk"] == ["order_id"]
    assert sorted(f["cols"][0] for f in t["orders"]["fks"]) == ["customer_id", "product_id"]
    assert t["orders"]["fks"][0]["ref_table"] in {"customers", "products"}

def test_infer_fk_from_matching_pk_name(tmp_path):
    p = profile_db(_db(tmp_path, "nofk", """
        CREATE TABLE customers (customer_id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE orders (order_id INTEGER PRIMARY KEY, customer_id INTEGER, amount REAL);"""))
    assert infer_fks(p) == [{"table": "orders", "cols": ["customer_id"],
                             "ref_table": "customers", "ref_cols": ["customer_id"], "source": "name"}]

def test_infer_fk_from_table_name_plus_id(tmp_path):
    p = profile_db(_db(tmp_path, "nofk2", """
        CREATE TABLE customer (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE orders (id INTEGER PRIMARY KEY, customer_id INTEGER);"""))
    assert infer_fks(p) == [{"table": "orders", "cols": ["customer_id"],
                             "ref_table": "customer", "ref_cols": ["id"], "source": "name"}]

def test_infer_fk_skips_declared_and_own_pk(tmp_path):
    p = profile_db(_db(tmp_path, "shop", SHOP))
    assert infer_fks(p) == []

def test_schema_items_normalize_case_underscore_plural(tmp_path):
    p = profile_db(_db(tmp_path, "n", "CREATE TABLE Invoice_Lines (Invoice_Id INT, Qty INT);"))
    assert schema_items(p) == {"invoiceline.invoiceid", "invoiceline.qty"}

def test_schema_items_strip_prefix_shared_by_most_tables(tmp_path):
    p = profile_db(_db(tmp_path, "olist", """
        CREATE TABLE olist_orders (order_id TEXT); CREATE TABLE olist_customers (customer_id TEXT);
        CREATE TABLE translation (name TEXT);"""))
    assert schema_items(p) == {"order.orderid", "customer.customerid", "translation.name"}

def test_containment_is_relative_to_smaller_schema():
    small, big = {"a.x", "a.y"}, {"a.x", "a.y", "b.z", "c.w"}
    assert containment(small, big) == 1.0 == containment(big, small)
    assert containment({"a.x", "b.y"}, {"a.x", "c.z", "d.w"}) == 0.5

def test_profile_finds_unique_id_column_when_no_pk(tmp_path):
    p = profile_db(_db(tmp_path, "k", """
        CREATE TABLE olist_orders (order_id TEXT, customer_id TEXT, status TEXT);
        INSERT INTO olist_orders VALUES ('o1','c1','x'),('o2','c1','y');"""))
    assert p["tables"][0]["unique_keys"] == ["order_id"]

def test_row_key_prefers_unique_column_naming_the_table():
    t = {"name": "olist_order_reviews", "pk": [], "unique_keys": ["order_id", "review_id"]}
    assert row_key(t) == "review_id"
    assert row_key({**t, "pk": ["id"]}) == "id"

def test_infer_fk_uses_unique_key_when_ref_has_no_pk(tmp_path):
    p = profile_db(_db(tmp_path, "k2", """
        CREATE TABLE olist_customers (customer_id TEXT, city TEXT);
        CREATE TABLE olist_orders (order_id TEXT, customer_id TEXT);
        INSERT INTO olist_customers VALUES ('c1','a'),('c2','b');
        INSERT INTO olist_orders VALUES ('o1','c1'),('o2','c1');"""))
    assert infer_fks(p) == [{"table": "olist_orders", "cols": ["customer_id"],
                             "ref_table": "olist_customers", "ref_cols": ["customer_id"], "source": "name"}]

def test_fragmented_when_fk_graph_splits(tmp_path):
    p = profile_db(_db(tmp_path, "mix", """
        CREATE TABLE a (a_id INTEGER PRIMARY KEY); CREATE TABLE b (b_id INTEGER PRIMARY KEY, a_id INTEGER);
        CREATE TABLE x (x_id INTEGER PRIMARY KEY); CREATE TABLE y (y_id INTEGER PRIMARY KEY, x_id INTEGER);"""))
    assert is_fragmented(p, infer_fks(p), min_share=0.6)
    q = profile_db(_db(tmp_path, "shop", SHOP))
    assert not is_fragmented(q, all_fks(q), min_share=0.6)

CFG = dict(tables=(3, 20), max_cols=250, rows=(200, 3_000_000), max_mb=100, min_fks=2, fk_min_hit=0.3,
           anchor_min_rows=5, long_text_avg_len=200, min_component_share=0.6,
           leak_names=set(), overlap=0.6, leak_ref={})

def test_evaluate_passes_shop(tmp_path):
    r = evaluate(profile_db(_db(tmp_path, "shop", SHOP)), CFG)
    assert r["pass"], r["fail_reasons"]
    assert r["n_fks_declared"] == 2 and r["n_fks_valid"] == 2 and r["invalid_fks"] == [] == r["unverified_fks"]
    assert r["has_person_named"] and r["anchor_kinds"] == ["entity", "person_named"]
    assert r["person_anchors"] == ["customers[first_name,last_name]"] and r["entity_anchors"] == ["products[name]"]
    assert r["update_targets"] == ["customers", "products", "orders"]

def test_evaluate_reports_every_failed_rule(tmp_path):
    p = profile_db(_db(tmp_path, "tiny", """
        CREATE TABLE a (id INTEGER PRIMARY KEY); INSERT INTO a VALUES (1);"""))
    r = evaluate(p, CFG)
    assert not r["pass"]
    assert {"tables", "rows", "fks", "no_update_target", "no_anchor"} <= set(r["fail_reasons"])

def test_evaluate_flags_leak_by_name_and_by_schema_overlap(tmp_path):
    p = profile_db(_db(tmp_path, "shop", SHOP))
    assert "leak" in evaluate(p, {**CFG, "leak_names": {"shop"}})["fail_reasons"]
    ref = {"customer.customerid", "customer.firstname", "product.productid", "order.orderid"}
    r = evaluate(p, {**CFG, "leak_ref": {"chinook": ref}})
    assert "leak" in r["fail_reasons"] and r["leak_match"] == "chinook"

def test_dedup_keeps_preferred_source():
    f1 = ["race.raceid", "race.year", "driver.driverid", "result.resultid"]
    rows = [dict(source="spider1", db="formula_1", **{"pass": True}, schema=f1),
            dict(source="bird", db="formula_1", **{"pass": True}, schema=f1 + ["sprint.id"]),
            dict(source="bird", db="shop", **{"pass": True}, schema=["order.orderid", "customer.customerid"])]
    out = dedup(rows, order=["bird", "spider2", "spider1"], threshold=0.6)
    assert [r["dup_of"] for r in out] == ["bird:formula_1", None, None]

# --- Task 1: FK hit rate ---

def test_validate_fks_hit_rate_counts_non_empty_child_values(tmp_path):
    p = profile_db(_db(tmp_path, "half", """
        CREATE TABLE customers (customer_id INTEGER PRIMARY KEY);
        CREATE TABLE orders (order_id INTEGER PRIMARY KEY, customer_id INTEGER REFERENCES customers(customer_id));
        INSERT INTO customers VALUES (1),(2);
        INSERT INTO orders VALUES (1,1),(2,2),(3,9),(4,8),(5,NULL),(6,'');"""))
    assert validate_fks(p, declared_fks(p)) == [{"table": "orders", "cols": ["customer_id"], "ref_table": "customers",
                                                 "ref_cols": ["customer_id"], "source": "declared", "hit": 0.5}]

def test_fk_hit_rate_without_child_values_is_unverified(tmp_path):
    p = profile_db(_db(tmp_path, "empty", """
        CREATE TABLE customers (customer_id INTEGER PRIMARY KEY);
        CREATE TABLE orders (order_id INTEGER PRIMARY KEY, customer_id INTEGER REFERENCES customers(customer_id));
        CREATE TABLE archive (order_id INTEGER PRIMARY KEY, customer_id INTEGER REFERENCES customers(customer_id));
        INSERT INTO customers VALUES (1);
        INSERT INTO orders VALUES (1,NULL),(2,'');"""))
    assert [f["hit"] for f in validate_fks(p, declared_fks(p))] == [None, None]

def test_fk_hit_rate_resolves_ref_table_case_insensitively(tmp_path):
    p = profile_db(_db(tmp_path, "case", """
        CREATE TABLE customers (customer_id INTEGER PRIMARY KEY);
        CREATE TABLE orders (order_id INTEGER PRIMARY KEY, customer_id INTEGER REFERENCES Customers(customer_id));
        INSERT INTO customers VALUES (1);
        INSERT INTO orders VALUES (1,1);"""))
    f = validate_fks(p, declared_fks(p))[0]
    assert f["ref_table"] == "customers" and f["hit"] == 1.0

def test_fk_hit_rate_fills_omitted_ref_column_with_pk(tmp_path):
    p = profile_db(_db(tmp_path, "omit", """
        CREATE TABLE customers (customer_id INTEGER PRIMARY KEY);
        CREATE TABLE orders (order_id INTEGER PRIMARY KEY, customer_id INTEGER REFERENCES customers);
        INSERT INTO customers VALUES (1);
        INSERT INTO orders VALUES (1,1),(2,2);"""))
    f = validate_fks(p, declared_fks(p))[0]
    assert f["ref_cols"] == ["customer_id"] and f["hit"] == 0.5

# --- Task 2: name-based inference ---

def test_infer_fk_ignores_guid_columns(tmp_path):
    # AdventureWorks: a table whose only unique id-like column is rowguid makes every other rowguid 'reference' it
    p = profile_db(_db(tmp_path, "guid", """
        CREATE TABLE product (productid INTEGER PRIMARY KEY, rowguid TEXT);
        CREATE TABLE salesorderdetail (salesorderdetailid INTEGER PRIMARY KEY, productid INTEGER, rowguid TEXT);
        CREATE TABLE productmodelculture (productmodelid INTEGER, cultureid TEXT, rowguid TEXT);
        INSERT INTO product VALUES (1,'g1'),(2,'g2');
        INSERT INTO salesorderdetail VALUES (1,1,'g3'),(2,2,'g4');
        INSERT INTO productmodelculture VALUES (1,'en','g5'),(1,'en','g6');"""))
    assert [(f["table"], f["cols"][0], f["ref_table"]) for f in infer_fks(p)] == \
        [("salesorderdetail", "productid", "product")]

def test_infer_fk_skips_generic_id_columns(tmp_path):
    # both ids run 1..N, so the smaller one is 'contained' in the larger by coincidence (EU_soccer Match/Player_Attributes)
    p = profile_db(_db(tmp_path, "gen", """
        CREATE TABLE Match (id INTEGER PRIMARY KEY, season TEXT);
        CREATE TABLE Player_Attributes (id INTEGER PRIMARY KEY, rating INTEGER);
    """ + _rows("Match", 5, lambda i: f"{i},'s'") + _rows("Player_Attributes", 10, lambda i: f"{i},1")))
    assert infer_fks(p) == []

def test_infer_fk_from_composite_pk_member(tmp_path):
    # BowlingLeague: the archive's BowlerID is part of its PK and still points at Bowlers
    p = profile_db(_db(tmp_path, "bowl", """
        CREATE TABLE Bowlers (BowlerID INTEGER PRIMARY KEY, BowlerLastName TEXT);
        CREATE TABLE Bowler_Scores_Archive (MatchID INTEGER, GameNumber INTEGER, BowlerID INTEGER, RawScore INTEGER,
                                            PRIMARY KEY (MatchID, GameNumber, BowlerID));"""))
    assert [(f["table"], f["cols"][0], f["ref_table"]) for f in infer_fks(p)] == \
        [("Bowler_Scores_Archive", "BowlerID", "Bowlers")]

def test_infer_fk_one_to_one_extension_needs_larger_parent(tmp_path):
    # complex_oracle: supplementary_demographics.cust_id is its own PK and references customers (55,500 > 4,500 rows)
    p = profile_db(_db(tmp_path, "ext", """
        CREATE TABLE customers (cust_id INTEGER PRIMARY KEY, cust_first_name TEXT);
        CREATE TABLE supplementary_demographics (cust_id INTEGER PRIMARY KEY, occupation TEXT);
    """ + _rows("customers", 3, lambda i: f"{i},'c{i}'") + _rows("supplementary_demographics", 2, lambda i: f"{i},'o'")))
    assert [(f["table"], f["cols"][0], f["ref_table"]) for f in infer_fks(p)] == \
        [("supplementary_demographics", "cust_id", "customers")]

# --- Task 3: value-based inference ---

def test_infer_by_value_finds_role_named_fks(tmp_path):
    p = profile_db(_db(tmp_path, "wwe", WWE))
    covered = {(f["table"], f["cols"][0].lower()) for f in infer_fks(p)}   # card_id -> Cards by name
    got = sorted((f["table"], f["cols"][0], f["ref_table"], f["source"]) for f in infer_fks_by_value(p, covered))
    assert got == [("Matches", "loser_id", "Wrestlers", "value"), ("Matches", "winner_id", "Wrestlers", "value")]

def test_infer_by_value_rejects_ambiguous_match(tmp_path):
    # winner_id values 0..39 exist in both Wrestlers.id and Cards.id -> two candidates -> no FK
    p = profile_db(_db(tmp_path, "amb", """
        CREATE TABLE Wrestlers (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE Cards (id INTEGER PRIMARY KEY, title TEXT);
        CREATE TABLE Matches (id INTEGER PRIMARY KEY, winner_id INTEGER);
    """ + _rows("Wrestlers", 40, lambda i: f"{i},'w{i}'") + _rows("Cards", 40, lambda i: f"{i},'c{i}'")
          + _rows("Matches", 200, lambda i: f"{i},{i%40}")))
    assert infer_fks_by_value(p, set()) == []

def test_infer_by_value_needs_enough_distinct_values(tmp_path):
    p = profile_db(_db(tmp_path, "few", """
        CREATE TABLE Wrestlers (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE Matches (id INTEGER PRIMARY KEY, winner_id INTEGER, note TEXT);
    """ + _rows("Wrestlers", 40, lambda i: f"{i},'w{i}'") + _rows("Matches", 200, lambda i: f"{i},{i%3},'x'")))
    assert infer_fks_by_value(p, set()) == []

# --- Task 4: composite keys ---

def test_profile_finds_two_column_composite_key(tmp_path):
    p = profile_db(_db(tmp_path, "ck", """
        CREATE TABLE movie_cast (movie_id INTEGER, person_id INTEGER, role TEXT);
        INSERT INTO movie_cast VALUES (1,1,'a'),(1,2,'b'),(2,1,'c');"""))
    t = p["tables"][0]
    assert t["unique_keys"] == [] and t["composite_key"] == ["movie_id", "person_id"] and is_keyed(t)

def test_composite_key_rejects_duplicates_and_nulls(tmp_path):
    p = profile_db(_db(tmp_path, "nock", """
        CREATE TABLE a (x_id INTEGER, y_id INTEGER, v TEXT);
        INSERT INTO a VALUES (1,1,'a'),(1,1,'b');
        CREATE TABLE b (x_id INTEGER, y_id INTEGER, v TEXT);
        INSERT INTO b VALUES (1,NULL,'a'),(1,2,'b');"""))
    assert [t["composite_key"] for t in p["tables"]] == [[], []]
    assert not is_keyed(p["tables"][0])

def test_single_pk_table_has_no_composite_key(tmp_path):
    p = profile_db(_db(tmp_path, "shop", SHOP))
    assert all(t["composite_key"] == [] for t in p["tables"])

# --- Task 5: column stats ---

def test_col_stats_empty_blank_and_avg_len(tmp_path):
    p = profile_db(_db(tmp_path, "st", """
        CREATE TABLE t (id INTEGER PRIMARY KEY, note TEXT, html TEXT);
        INSERT INTO t VALUES (1,'ab',NULL),(2,'',NULL),(3,NULL,'xxxxxxxxxx');"""))
    s = p["tables"][0]["stats"]
    assert s["note"] == {"empty": 2, "blank": 1, "avg_len": 2.0}
    assert s["html"] == {"empty": 2, "blank": 0, "avg_len": 10.0}
    assert s["id"]["empty"] == 0

def test_col_stats_on_quoted_names(tmp_path):
    p = profile_db(_db(tmp_path, "sp", """
        CREATE TABLE "Sales Orders" ("Order Number" TEXT PRIMARY KEY, "Sales Channel" TEXT);
        CREATE TABLE "voice-actors" ("voice-actor" TEXT, movie TEXT);
        INSERT INTO "Sales Orders" VALUES ('o1','web');
        INSERT INTO "voice-actors" VALUES ('Joan','Chicken Little');"""))
    t = {x["name"]: x for x in p["tables"]}
    assert t["Sales Orders"]["stats"]["Sales Channel"]["avg_len"] == 3.0
    assert t["voice-actors"]["stats"]["voice-actor"]["empty"] == 0

def test_col_stats_skipped_for_empty_table(tmp_path):
    p = profile_db(_db(tmp_path, "e", "CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT);"))
    assert p["tables"][0]["stats"] == {}

# --- Task 8: evaluate ---

def test_all_fks_merges_sources_and_validates(tmp_path):
    p = profile_db(_db(tmp_path, "wwe", WWE))
    fks = all_fks(p, extra=[{"table": "Matches", "cols": ["champion"], "ref_table": "Wrestlers", "ref_cols": ["id"]}])
    assert sorted((f["cols"][0], f["source"], f["hit"]) for f in fks) == \
        [("card_id", "name", 1.0), ("champion", "extra", 1.0), ("loser_id", "value", 1.0), ("winner_id", "value", 1.0)]

def test_evaluate_drops_invalid_fks_and_reports_them(tmp_path):
    p = profile_db(_db(tmp_path, "bad", """
        CREATE TABLE customers (customer_id INTEGER PRIMARY KEY, first_name TEXT);
        CREATE TABLE products (product_id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE orders (order_id INTEGER PRIMARY KEY, customer_id INTEGER REFERENCES customers(customer_id),
                             product_id INTEGER REFERENCES products(product_id), qty INTEGER);
    """ + _rows("customers", 60, lambda i: f"{i},'c{i}'") + _rows("products", 60, lambda i: f"{i},'p{i}'")
          + _rows("orders", 100, lambda i: f"{i},{i%60 + 1000},{i%60},1")))
    r = evaluate(p, CFG)
    assert r["invalid_fks"] == ["orders.customer_id->customers 0.0"] and r["n_fks_valid"] == 1
    assert "fks" in r["fail_reasons"] and "customers[first_name]" in r["person_anchors"]

def test_evaluate_keeps_unverified_fk_on_empty_table(tmp_path):
    p = profile_db(_db(tmp_path, "arch", SHOP + """
        CREATE TABLE returns (return_id INTEGER PRIMARY KEY, order_id INTEGER REFERENCES orders(order_id), reason TEXT);"""))
    r = evaluate(p, CFG)
    assert r["unverified_fks"] == ["returns.order_id->orders"] and r["n_fks_valid"] == 2 and r["pass"]

def test_evaluate_id_only_person_with_link_tables_passes(tmp_path):
    # computer_student-like: no names, advisedBy/taughtBy are pure link tables; the rule lets it through and the
    # anchor list shows a human what kind of tasks it can carry
    p = profile_db(_db(tmp_path, "cs", """
        CREATE TABLE person (p_id INTEGER PRIMARY KEY, professor INTEGER, student INTEGER);
        CREATE TABLE course (course_id INTEGER PRIMARY KEY, courseLevel TEXT);
        CREATE TABLE advisedBy (p_id INTEGER REFERENCES person(p_id), p_id_dummy INTEGER REFERENCES person(p_id),
                                PRIMARY KEY (p_id, p_id_dummy));
        CREATE TABLE taughtBy (course_id INTEGER REFERENCES course(course_id), p_id INTEGER REFERENCES person(p_id),
                               PRIMARY KEY (course_id, p_id));
    """ + _rows("person", 60, lambda i: f"{i},{i%2},{(i+1)%2}") + _rows("course", 60, lambda i: f"{i},'L{i%3}'")
          + _rows("advisedBy", 60, lambda i: f"{i},{(i+1)%60}") + _rows("taughtBy", 60, lambda i: f"{i},{i}")))
    r = evaluate(p, CFG)
    assert r["pass"], r["fail_reasons"]
    assert r["anchor_kinds"] == ["entity", "person_id_only"] and not r["has_person_named"]
    assert r["person_anchors"] == ["person[]"]

def test_evaluate_quality_flags(tmp_path):
    p = profile_db(_db(tmp_path, "q", """
        CREATE TABLE customers (customer_id INTEGER PRIMARY KEY, first_name TEXT, note TEXT);
        CREATE TABLE products (product_id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE orders (order_id INTEGER PRIMARY KEY, customer_id INTEGER REFERENCES customers(customer_id),
                             product_id INTEGER REFERENCES products(product_id), html TEXT);
    """ + _rows("customers", 60, lambda i: f"{i},'c{i}',''") + _rows("products", 60, lambda i: f"{i},'p{i}'")
          + _rows("orders", 100, lambda i: f"{i},{i%60},{i%60},'{'x' * 500}'")))
    r = evaluate(p, CFG)
    assert r["long_text_cols"] == ["orders.html"] and r["empty_string_cols"] == ["customers.note"]
```

- [ ] **Step 2: 确认测试失败**

Run: `cd DySQL-Bench && ~/miniconda3/envs/dysql/bin/python -m pytest -q tests/test_db_select.py`
Expected: ImportError（`all_fks` 不存在）

- [ ] **Step 3: 实现（完整文件）**

`dysql_bench/db_select.py` 的最终内容：

```python
"""Filter candidate SQLite DBs for DySQL-style task generation.
Criteria are documented in docs/2026-09-24-data-gen-db-selection.md."""
import os, re, sqlite3
from dysql_bench.db_anchor import GUID, update_targets, anchors, entity_rank

ID_LIKE = re.compile(r"(id|_key|_code)$", re.I)
GENERIC_KEYS = {"id", "rowid", "pk", "key", "code"}  # never FK evidence: Match.id vs Player_Attributes.id both run 1..N
UNIQUE_SCAN_MAX_ROWS = 3_000_000  # skip COUNT(DISTINCT) on huge tables; they fail the size filter anyway
SAMPLE_ROWS = 5000  # rows sampled per column when inferring FKs by value


def _q(name):
    return '"' + name.replace('"', '""') + '"'


def _open(path):
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def _composite_key(c, t, cols):
    """First pair of id-like columns that is unique and non-null together (tables without any single key)."""
    ids = [x for x in cols if ID_LIKE.search(x) and not GUID.search(x)][:6]
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            a, b = ids[i], ids[j]
            nulls = c.execute(f"SELECT count(*) FROM {_q(t)} WHERE {_q(a)} IS NULL OR {_q(b)} IS NULL").fetchone()[0]
            dup = c.execute(f"SELECT count(*) FROM (SELECT 1 FROM {_q(t)} GROUP BY {_q(a)}, {_q(b)} "
                            f"HAVING count(*) > 1)").fetchone()[0]
            if not nulls and not dup:
                return [a, b]
    return []


def _col_stats(c, t, cols):
    """Per column: rows that are NULL or '', rows that are exactly '', average length of non-empty values."""
    out = {}
    for i in range(0, len(cols), 200):  # SQLite caps result columns at 2000
        part = cols[i:i + 200]
        sel = ", ".join(f"sum({_q(x)} IS NULL OR {_q(x)} = ''), sum({_q(x)} = ''), avg(nullif(length({_q(x)}), 0))"
                        for x in part)
        r = c.execute(f"SELECT {sel} FROM {_q(t)}").fetchone()
        out.update({x: {"empty": r[3 * j] or 0, "blank": r[3 * j + 1] or 0, "avg_len": float(r[3 * j + 2] or 0.0)}
                    for j, x in enumerate(part)})
    return out


def profile_db(path):
    c = _open(path)
    names = [r[0] for r in c.execute("select name from sqlite_master where type='table' "
                                     "and name not like 'sqlite_%' order by rowid")]
    tables = []
    for t in names:
        info = c.execute(f"pragma table_info({_q(t)})").fetchall()
        cols = [i[1] for i in info]
        fks = {}
        for r in c.execute(f"pragma foreign_key_list({_q(t)})").fetchall():
            f = fks.setdefault(r[0], {"cols": [], "ref_table": r[2], "ref_cols": []})
            f["cols"].append(r[3]); f["ref_cols"].append(r[4])
        pk = [i[1] for i in sorted(info, key=lambda i: i[5]) if i[5] > 0]
        rows = c.execute(f"select count(*) from {_q(t)}").fetchone()[0]
        scan = 0 < rows <= UNIQUE_SCAN_MAX_ROWS
        unique = [x for x in cols if ID_LIKE.search(x) and c.execute(
            f"select count(distinct {_q(x)}) = count(*) and count({_q(x)}) = count(*) from {_q(t)}").fetchone()[0]] \
            if not pk and scan else []
        composite = _composite_key(c, t, cols) if not pk and not unique and scan else []
        stats = _col_stats(c, t, cols) if scan else {}
        tables.append({"name": t, "cols": cols, "pk": pk, "unique_keys": unique, "composite_key": composite,
                       "fks": list(fks.values()), "rows": rows, "stats": stats})
    c.close()
    return {"db": os.path.splitext(os.path.basename(path))[0], "path": path,
            "size_mb": os.path.getsize(path) / 2**20, "tables": tables}


def is_keyed(t):
    return bool(t["pk"] or t["unique_keys"] or t["composite_key"])


def _norm(name):
    s = re.sub(r"[^a-z0-9]", "", name.lower())
    return s[:-1] if s.endswith("s") else s


def row_key(t):
    """Column that identifies a row: single-column PK, else a unique id-like column (prefer one naming the table)."""
    if len(t["pk"]) == 1:
        return t["pk"][0]
    stem = _norm(re.split(r"[^A-Za-z0-9]", t["name"])[-1])
    return next((k for k in t["unique_keys"] if stem and stem in _norm(k)), (t["unique_keys"] or [None])[0])


def _fk_candidate(col):
    return bool(ID_LIKE.search(col)) and not GUID.search(col) and _norm(col) not in GENERIC_KEYS


def declared_fks(p):
    """Flatten the per-table PRAGMA foreign keys into the common fk dict format."""
    return [{"table": t["name"], "cols": f["cols"], "ref_table": f["ref_table"], "ref_cols": f["ref_cols"],
             "source": "declared"} for t in p["tables"] for f in t["fks"]]


def infer_fks(p):
    """Join keys implied by column names, for DBs that declare few FKs (e.g. Kaggle CSV imports).
    A column that is its table's own row key may only reference a strictly larger table (1:1 extension,
    e.g. supplementary_demographics.cust_id -> customers); composite-PK members are ordinary candidates."""
    keys = {t["name"]: row_key(t) for t in p["tables"] if row_key(t)}
    rows = {t["name"]: t["rows"] for t in p["tables"]}
    out = []
    for t in p["tables"]:
        declared = {c.lower() for f in t["fks"] for c in f["cols"]}
        own = keys.get(t["name"])
        for col in t["cols"]:
            lc = col.lower()
            if lc in declared or not _fk_candidate(col):
                continue
            cands = [r for r, k in keys.items() if r != t["name"] and k.lower() == lc]
            if not cands:
                cands = [r for r in keys if r != t["name"] and
                         re.sub(r"_?id$", "", lc) in {r.lower(), _norm(r)}]
            if col == own:
                cands = [r for r in cands if rows[r] > t["rows"]]
            if len(cands) == 1:
                out.append({"table": t["name"], "cols": [col], "ref_table": cands[0],
                            "ref_cols": [keys[cands[0]]], "source": "name"})
    return out


def infer_fks_by_value(p, covered, min_hit=0.99, min_distinct=20):
    """Role-named FKs (winner_id, loser_id, *_order_id) that no name rule catches: an id-like column whose
    sampled non-empty values (almost) all fall inside exactly one other table's key. `covered` holds
    (table, col_lower) pairs already explained by declared or name-inferred FKs."""
    keys = {t["name"]: row_key(t) for t in p["tables"] if row_key(t)}
    rows = {t["name"]: t["rows"] for t in p["tables"]}
    c = _open(p["path"])
    out = []
    for t in p["tables"]:
        own = keys.get(t["name"])
        for col in t["cols"]:
            if (t["name"], col.lower()) in covered or col == own or not _fk_candidate(col):
                continue
            distinct = c.execute(f"SELECT count(DISTINCT {_q(col)}) FROM {_q(t['name'])}").fetchone()[0]
            if distinct < min_distinct:
                continue
            hits = []
            for ref, k in keys.items():
                if ref == t["name"] or rows[ref] < distinct:
                    continue
                n, h = c.execute(
                    f"SELECT count(*), coalesce(sum({_q(col)} IN (SELECT {_q(k)} FROM {_q(ref)})), 0) FROM "
                    f"(SELECT {_q(col)} FROM {_q(t['name'])} WHERE {_q(col)} IS NOT NULL AND {_q(col)} != '' "
                    f"LIMIT {SAMPLE_ROWS})").fetchone()
                if n and h / n >= min_hit:
                    hits.append(ref)
            if len(hits) == 1:
                out.append({"table": t["name"], "cols": [col], "ref_table": hits[0],
                            "ref_cols": [keys[hits[0]]], "source": "value"})
    c.close()
    return out


def _resolve_ref_cols(ref, ref_cols):
    """Fill ref columns omitted in the DDL (`REFERENCES customers`) with the referenced table's PK."""
    if all(rc is None for rc in ref_cols) and len(ref["pk"]) == len(ref_cols):
        return list(ref["pk"])
    return [rc or (ref["pk"][0] if len(ref["pk"]) == 1 else None) for rc in ref_cols]


def fk_hit_rate(c, fk, p):
    """Share of the child's non-null, non-empty key values found in the referenced table.
    None when there is nothing to check (empty child, or every value empty): unverified, not wrong."""
    tables = {t["name"].lower(): t for t in p["tables"]}
    ref = tables.get(fk["ref_table"].lower())
    if not ref or any(rc is None for rc in fk["ref_cols"]):
        return 0.0
    cols = ", ".join(_q(x) for x in fk["cols"])
    rcols = ", ".join(_q(x) for x in fk["ref_cols"])
    notnull = " AND ".join(f"{_q(x)} IS NOT NULL AND {_q(x)} != ''" for x in fk["cols"])
    n, hit = c.execute(f"SELECT count(*), coalesce(sum(({cols}) IN (SELECT {rcols} FROM {_q(ref['name'])})), 0) "
                       f"FROM {_q(fk['table'])} WHERE {notnull}").fetchone()
    return hit / n if n else None


def validate_fks(p, fks):
    """Resolve ref table names/columns and attach the data-checked hit rate (None = unverified) to every fk."""
    tables = {t["name"].lower(): t for t in p["tables"]}
    c = _open(p["path"])
    out = []
    for f in fks:
        ref = tables.get(f["ref_table"].lower())
        g = {**f, "ref_table": ref["name"] if ref else f["ref_table"],
             "ref_cols": _resolve_ref_cols(ref, f["ref_cols"]) if ref else f["ref_cols"]}
        h = fk_hit_rate(c, g, p)
        g["hit"] = None if h is None else round(h, 3)
        out.append(g)
    c.close()
    return out


def all_fks(p, extra=()):
    """Declared + name-inferred + value-inferred + manually supplied FKs, each with a data hit rate."""
    base = declared_fks(p) + infer_fks(p)
    covered = {(f["table"], c.lower()) for f in base for c in f["cols"]}
    fks = base + infer_fks_by_value(p, covered) + [{**f, "source": "extra"} for f in extra]
    return validate_fks(p, fks)


def schema_items(p):
    """Normalized table.column items; a prefix shared by >= half the tables (e.g. `olist_`) is dropped."""
    heads = [m.group(1).lower() for t in p["tables"] if (m := re.match(r"([A-Za-z0-9]+)_", t["name"]))]
    top = max(set(heads), key=heads.count) if heads else None
    strip = top if top and heads.count(top) >= max(2, len(p["tables"]) / 2) else None
    def tname(n):
        return n[len(strip) + 1:] if strip and n.lower().startswith(strip + "_") else n
    return {f"{_norm(tname(t['name']))}.{_norm(c)}" for t in p["tables"] for c in t["cols"]}


def containment(a, b):
    """Share of the smaller schema's table.column items found in the other (catches subset/superset copies)."""
    a, b = set(a), set(b)
    return len(a & b) / min(len(a), len(b)) if a and b else 0.0


def is_fragmented(p, fks, min_share):
    """True when the largest FK-connected component covers < min_share of tables (grab-bag DBs)."""
    names = [t["name"] for t in p["tables"]]
    if not names:
        return False
    lower = {n.lower(): n for n in names}
    parent = {n: n for n in names}
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    for f in fks:
        a, b = lower.get(f["table"].lower()), lower.get(f["ref_table"].lower())
        if a and b:
            parent[find(a)] = find(b)
    sizes = {}
    for n in names:
        sizes[find(n)] = sizes.get(find(n), 0) + 1
    return max(sizes.values()) / len(names) < min_share


def _fmt_fk(f):
    return f"{f['table']}.{','.join(f['cols'])}->{f['ref_table']}"


def evaluate(p, cfg, extra_fks=()):
    T = p["tables"]
    fks = all_fks(p, extra_fks)
    usable = [f for f in fks if f["hit"] is None or f["hit"] >= cfg["fk_min_hit"]]
    keys = {t["name"]: row_key(t) for t in T if row_key(t)}
    targets = update_targets(p, keys, cfg["long_text_avg_len"])
    anc = anchors(p, usable, keys, targets, cfg["anchor_min_rows"])
    person = sorted([a for a in anc if a["kind"] != "entity"], key=lambda a: (a["kind"] != "person_named", -a["rows"]))
    entity = sorted([a for a in anc if a["kind"] == "entity"], key=entity_rank)
    n_cols = sum(len(t["cols"]) for t in T)
    rows = sum(t["rows"] for t in T)
    items = schema_items(p)
    leak_j = {k: containment(items, v) for k, v in cfg["leak_ref"].items()}
    leak_match = max(leak_j, key=leak_j.get) if leak_j else None
    fragmented = is_fragmented(p, usable, cfg["min_component_share"])
    keyed = {t["name"]: is_keyed(t) for t in T}
    fail = []
    if p["db"] in cfg["leak_names"] or (leak_match and leak_j[leak_match] >= cfg["overlap"]):
        fail.append("leak")
    lo, hi = cfg["tables"]
    if not lo <= len(T) <= hi: fail.append("tables")
    if n_cols > cfg["max_cols"]: fail.append("cols")
    lo, hi = cfg["rows"]
    if not lo <= rows <= hi: fail.append("rows")
    if p["size_mb"] > cfg["max_mb"]: fail.append("size")
    if len(usable) < cfg["min_fks"]: fail.append("fks")
    if not targets: fail.append("no_update_target")
    if not anc: fail.append("no_anchor")
    if fragmented: fail.append("fragmented")
    return {"db": p["db"], "n_tables": len(T), "n_cols": n_cols, "total_rows": rows,
            "size_mb": round(p["size_mb"], 1),
            "n_fks_declared": sum(f["source"] == "declared" for f in fks),
            "n_fks_inferred": sum(f["source"] != "declared" for f in fks),
            "n_fks_valid": sum(f["hit"] is not None and f["hit"] >= cfg["fk_min_hit"] for f in fks),
            "invalid_fks": [f"{_fmt_fk(f)} {f['hit']}" for f in fks if f["hit"] is not None and f["hit"] < cfg["fk_min_hit"]],
            "unverified_fks": [_fmt_fk(f) for f in fks if f["hit"] is None],
            "has_person_named": any(a["kind"] == "person_named" for a in anc),
            "anchor_kinds": sorted({a["kind"] for a in anc}),
            "person_anchors": [f"{a['table']}[{','.join(a['names'])}]" for a in person],
            "entity_anchors": [f"{a['table']}[{','.join(a['names'])}]" for a in entity],
            "anchors": anc,
            "update_targets": list(targets), "targets_no_key": [t for t in targets if not keyed[t]],
            "composite_key_tables": [t["name"] for t in T if t["composite_key"]],
            "long_text_cols": [f"{t['name']}.{c}" for t in T for c, s in t["stats"].items()
                               if s["avg_len"] > cfg["long_text_avg_len"]],
            "empty_string_cols": [f"{t['name']}.{c}" for t in T for c, s in t["stats"].items()
                                  if t["rows"] and s["blank"] >= 0.1 * t["rows"]],
            "fragmented": fragmented,
            "leak_match": leak_match if leak_match and leak_j[leak_match] >= cfg["overlap"] else None,
            "max_leak_overlap": round(leak_j[leak_match], 2) if leak_match else 0.0,
            "table_names": [t["name"] for t in T], "schema": sorted(items), "fail_reasons": fail, "pass": not fail}


def dedup(rows, order, threshold):
    """Mark passing DBs whose schema overlaps an already-kept DB from a preferred source."""
    rank = {s: i for i, s in enumerate(order)}
    kept, dup = [], {}
    for i in sorted(range(len(rows)), key=lambda i: rank.get(rows[i]["source"], len(order))):
        r = rows[i]
        if not r["pass"]:
            continue
        hit = next((k for k in kept if containment(r["schema"], k["schema"]) >= threshold), None)
        if hit:
            dup[i] = f'{hit["source"]}:{hit["db"]}'
        else:
            kept.append(r)
    return [{**r, "dup_of": dup.get(i)} for i, r in enumerate(rows)]
```

`scripts/select_dbs.py` 做三处改动，保证 CLI 仍能跑（Task 10 再加新参数）：

```python
CFG = dict(tables=(3, 20), max_cols=250, rows=(200, 3_000_000), max_mb=300, min_fks=2, fk_min_hit=0.3,
           anchor_min_rows=5, long_text_avg_len=200, min_component_share=0.6, overlap=0.6)
COLS = ["source", "db", "pass", "dup_of", "fail_reasons", "n_tables", "n_cols", "total_rows", "size_mb",
        "n_fks_declared", "n_fks_inferred", "n_fks_valid", "invalid_fks", "unverified_fks", "has_person_named",
        "anchor_kinds", "person_anchors", "entity_anchors", "update_targets", "targets_no_key",
        "composite_key_tables", "long_text_cols", "empty_string_cols", "fragmented", "leak_match",
        "max_leak_overlap", "table_names"]
```

`write()` 里那一行改为先过滤字段。`anchors` 是 dict 列表，不能拿去做 `"; ".join`：

```python
                w.writerow({k: "; ".join(v) if isinstance(v, list) else v for k, v in r.items() if k in COLS})
```

- [ ] **Step 4: 确认全部测试通过**

Run: `cd DySQL-Bench && ~/miniconda3/envs/dysql/bin/python -m pytest -q`
Expected: 76 passed（test_db_select 37 + test_db_anchor 9 + 其他 30）

- [ ] **Step 5: Commit**

```bash
git add DySQL-Bench/dysql_bench/db_select.py DySQL-Bench/tests/test_db_select.py DySQL-Bench/scripts/select_dbs.py
git commit -m "feat(db_select): anchor + update-target rule replaces the person-table rule; only usable FKs count

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: DySQL 13 库验收与外键阈值标定

**Files:**
- Create: `DySQL-Bench/tests/test_dysql_acceptance.py`
- Create: `DySQL-Bench/scripts/fk_report.py`
- Create: `docs/data_gen/fk_calibration.md`

**Interfaces:**
- Consumes: `profile_db`、`evaluate`、`all_fks`。
- Produces: `scripts/fk_report.py <sqlite...>`。每行输出 `db  source  table.cols -> ref.cols  hit`，按命中率升序，未验证的排在最前。

- [ ] **Step 1: 写验收测试**

```python
# tests/test_dysql_acceptance.py
"""DySQL-Bench's own 13 DBs define what 'usable' means: every table their gold SQL writes must sit in some
anchor's scope, every UPDATE target must be an update target, and cars/cookbook are the only entity-only DBs.
Size rules are not asserted (human_resources has 37 rows)."""
import ast, glob, os, re
from collections import Counter
import pytest
from dysql_bench.db_select import profile_db, evaluate

ENVS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dysql_bench", "envs")
DBS = sorted(glob.glob(f"{ENVS}/*/data/*.sqlite"))
CFG = dict(tables=(1, 50), max_cols=10_000, rows=(0, 10**9), max_mb=10_000, min_fks=0, fk_min_hit=0.3,
           anchor_min_rows=5, long_text_avg_len=200, min_component_share=0.0,
           leak_names=set(), overlap=0.6, leak_ref={})
ENTITY_ONLY = {"cars", "cookbook"}
WRITE = re.compile(r'(?is)^\s*(insert(?:\s+or\s+\w+)?\s+into|update(?:\s+or\s+\w+)?|delete\s+from|replace\s+into)'
                   r'\s+["`\[]?([\w ]+?)["`\]]?[\s(]')

def gold_writes(tasks_file):
    """(op, table) for every write statement in the gold actions, read with ast (no import of the env)."""
    for node in ast.walk(ast.parse(open(tasks_file, encoding="utf-8").read())):
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and k.value == "sql" and isinstance(v, ast.Constant):
                    for st in v.value.split(";"):
                        m = WRITE.match(st + " ")
                        if m:
                            yield m.group(1).split()[0].upper(), m.group(2).strip()

@pytest.mark.skipif(not DBS, reason="DySQL env DBs not present")
@pytest.mark.parametrize("path", DBS, ids=[os.path.basename(p)[:-7] for p in DBS])
def test_dysql_anchors_cover_every_gold_write(path):
    p = profile_db(path)
    r = evaluate(p, CFG)
    lower = {t["name"].lower(): t["name"] for t in p["tables"]}
    scope = {x for a in r["anchors"] for x in [a["table"], *a["down"], *a["up"]]}
    miss = Counter()
    for op, tb in gold_writes(os.path.join(os.path.dirname(os.path.dirname(path)), "tasks_test.py")):
        name = lower.get(tb.lower())
        if name is None:
            continue  # 2 gold statements write tables that do not exist (agentnotes, corrections)
        if name not in scope or (op == "UPDATE" and name not in r["update_targets"]):
            miss[(op, name)] += 1
    assert not miss, dict(miss)
    if r["db"] in ENTITY_ONLY:
        assert r["anchor_kinds"] == ["entity"], r["anchors"]
    else:
        assert r["has_person_named"], r["person_anchors"]
```

- [ ] **Step 2: 跑验收测试**

Run: `cd DySQL-Bench && ~/miniconda3/envs/dysql/bin/python -m pytest -q tests/test_dysql_acceptance.py -v`
Expected: 13 passed（约 5 秒）。已在临时目录用同一份代码跑通。

如果某个库失败，看断言打印的 `miss`：
- 某张表不在范围内：先用 `scripts/fk_report.py`（Step 3）看它和锚点之间的外键是否被推断出来、命中率是否过了阈值，再回到 Task 2/3 补测试后修规则。
- 某个 UPDATE 目标不算更新目标：检查 `updatable_cols` 是否把它唯一的业务列当成了自己的键。

**不要为了让测试通过去调低阈值，也不要改这个测试。**

- [ ] **Step 3: 写外键报告脚本**

```python
#!/usr/bin/env python3
"""Print the data-checked hit rate of every declared/inferred FK in the given SQLite files, lowest first.
Usage (from DySQL-Bench/): ~/miniconda3/envs/dysql/bin/python scripts/fk_report.py dysql_bench/envs/*/data/*.sqlite"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dysql_bench.db_select import profile_db, all_fks

rows = []
for path in sys.argv[1:]:
    p = profile_db(path)
    for f in all_fks(p):
        rows.append((f["hit"] is not None, f["hit"] or 0.0, p["db"], f["source"],
                     f"{f['table']}.{','.join(f['cols'])}", f"{f['ref_table']}.{','.join(map(str, f['ref_cols']))}"))
for _, hit, db, src, child, ref in sorted(rows):
    print(f"{db:24s} {src:8s} {child} -> {ref}  {'unverified' if not _ else f'{hit:.3f}'}")
```

- [ ] **Step 4: 核对标定数据并写文档**

Run: `cd DySQL-Bench && ~/miniconda3/envs/dysql/bin/python scripts/fk_report.py dysql_bench/envs/*/data/*.sqlite | head -12`

核对输出前几行与下面文档里"DySQL 13 库"一节一致，然后创建 `docs/data_gen/fk_calibration.md`：

````markdown
# 外键命中率标定（2026-09-25）

命中率 = 子表外键列的非空值中，能在被引用表里找到的比例。子表没有任何非空值时记为"未验证"：外键保留，但单独列出。

## DySQL 13 库（声明的外键，共 128 条）

| 命中率 | 外键 |
|---|---|
| 未验证 | BowlingLeague `Bowler_Scores_Archive.(MatchID, GameNumber) → Match_Games_Archive`（空表） |
| 未验证 | BowlingLeague `Tourney_Matches_Archive.TourneyID → Tournaments_Archive`（空表） |
| 未验证 | Pagila `film.original_language_id → language`（全为 NULL） |
| 0.314 | complex_oracle `costs.prod_id → products` |
| 0.332 | complex_oracle `sales.prod_id → products` |
| 0.955 | law_episode `Award.person_id → Person` |
| 1.000 | 其余 122 条 |

complex_oracle 的 products 表只保留了 72 个产品中的 24 个，但 DySQL 仍在上面出了 25 个 UPDATE products 任务。数据不全的外键照样能出题：出题只会用到能连上的那部分行。

## 候选库里低于阈值的外键（2026-09-25 预跑）

| 命中率 | 外键 |
|---|---|
| 0.000 | synthea `claims.ENCOUNTER → encounters` |
| 0.081 | disney `movies_total_gross.movie_title → characters` |
| 0.091 | thrombosis_prediction `Examination.ID → Patient` |
| 0.107 | retail_complains `events."Complaint ID" → callcenterlogs` |
| 0.202 | synthea `conditions.DESCRIPTION → all_prevalences` |

## 阈值

`fk_min_hit = 0.3`：
- 取 0.3 能保住 DySQL 所有有数据的声明外键，其中最低的是 0.314。
- 同时能排除上表中命中率在 0–0.2 的外键，这类外键是错的，或者几乎连不上。

这个阈值要排除的是"错的外键"，不是"数据不全的外键"。
````

- [ ] **Step 5: Commit**

```bash
git add DySQL-Bench/tests/test_dysql_acceptance.py DySQL-Bench/scripts/fk_report.py docs/data_gen/fk_calibration.md
git commit -m "test(db_select): DySQL's 13 DBs as the acceptance set (every gold write in an anchor scope); FK threshold 0.3

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: CLI 新参数、人工外键、重跑

**Files:**
- Modify: `DySQL-Bench/scripts/select_dbs.py`（下面给出完整文件）
- Create: `docs/data_gen/fk_extra.json`
- Modify: `docs/data_gen/candidate_dbs.csv`、`DySQL-Bench/results/db_select/db_select_all.csv`（重跑输出）
- Create: `docs/data_gen/candidate_anchors.json`（重跑输出）、`docs/data_gen/2026-09-26-candidate-diff.md`

**Interfaces:**
- Consumes: Task 8 的 `evaluate(p, cfg, extra_fks)`。
- Produces:
  - 新参数 `--fk-extra <json>`、`--anchors-json <json>`。
  - CSV 新增 `split`、`path` 两列。
  - `fk_extra.json` 格式：`{"<source>:<db>": [{"table", "cols", "ref_table", "ref_cols"}]}`。
  - `candidate_anchors.json` 格式：`{"<source>:<db>": [anchor dict, ...]}`，给建树脚本用。

- [ ] **Step 1: 人工外键**

`docs/data_gen/fk_extra.json`。IPL 的这几列不带 id，自动规则不会碰；实测命中率 98.7–99.0%：

```json
{
  "spider2:IPL": [
    {"table": "ball_by_ball", "cols": ["striker"], "ref_table": "player", "ref_cols": ["player_id"]},
    {"table": "ball_by_ball", "cols": ["non_striker"], "ref_table": "player", "ref_cols": ["player_id"]},
    {"table": "ball_by_ball", "cols": ["bowler"], "ref_table": "player", "ref_cols": ["player_id"]},
    {"table": "wicket_taken", "cols": ["player_out"], "ref_table": "player", "ref_cols": ["player_id"]}
  ]
}
```

- [ ] **Step 2: 按用户的决定处理 Spider 的 Student 模板**

activity_1 和 college_3 的 Student 表，与 Spider dev 的 pets_1（CoSQL/SParC 评测库）同模板，包含度都是 0.57，差一点到 0.6 的阈值。两种处理：

- **都排除（推荐）：** `LEAK["spider1"]` 加 `"activity_1", "college_3"`。两个都要加：college_3 原本是作为 activity_1 的重复库被去掉的，只排除 activity_1 的话它会回来。
- **都保留：** 不改代码，在 Task 11 的 `db_notes.csv` 备注里写"与 Spider dev 的 pets_1 同模板，包含度 0.57"。

- [ ] **Step 3: 替换 CLI（完整文件）**

`scripts/select_dbs.py` 的最终内容（LEAK 按 Step 2 的决定调整）：

```python
#!/usr/bin/env python3
"""Apply the data-gen DB filters (docs/2026-09-24-data-gen-db-selection.md) to candidate SQLite DBs.
Usage (data layout: ~/Documents/Isa/text2sql_bench/README.md), from DySQL-Bench/:
  T=~/Documents/Isa/text2sql_bench
  ~/miniconda3/envs/dysql/bin/python scripts/select_dbs.py \
    --source "bird=$T/bird/train/train_databases/*/*.sqlite" --source "bird=$T/bird/dev/dev_databases/*/*.sqlite" \
    --source "spider2=$T/spider2_lite/sqlite/*.sqlite" --source "spider1=$T/spider1/test_database/*/*.sqlite" \
    --source "synsql=$T/synsql/databases/*/*.sqlite" \
    --holdout "spider1=$T/spider1/dev.json" --holdout "spider1=$T/spider1/test.json" \
    --fk-extra ../docs/data_gen/fk_extra.json \
    --out results/db_select/db_select_all.csv --candidates ../docs/data_gen/candidate_dbs.csv \
    --anchors-json ../docs/data_gen/candidate_anchors.json
Source names used for leak lists and dedup order: bird, spider2, spider1, synsql.
--holdout marks every db_id in an eval question file as excluded (Spider dev/test = CoSQL/SParC eval DBs).
--fk-extra adds hand-checked FKs the inference rules miss: {"source:db": [{table, cols, ref_table, ref_cols}]}.
Any DB whose schema overlaps an excluded DB (DySQL, LEAK, holdout) by >= CFG["overlap"] is excluded too."""
import argparse, csv, glob, json, os, sys
from collections import Counter
from multiprocessing import Pool
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dysql_bench.db_select import profile_db, evaluate, dedup, schema_items

ENVS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dysql_bench", "envs")
# DySQL's own DBs plus known same-origin copies (Chinook, Sakila/Pagila, EU soccer, Northwind),
# and the Ergast F1 data, which BIRD-Interact-full ships as `sports_events` (renamed columns, same rows).
LEAK = {"spider1": {"chinook_1", "store_1", "sakila_1", "soccer_1", "formula_1"},
        "bird": {"movie_3", "european_football_2", "law_episode", "ice_hockey_draft", "cookbook",
                 "retail_world", "cars", "human_resources", "formula_1"},
        "spider2": {"sqlite-sakila", "northwind", "EU_soccer", "complex_oracle", "BowlingLeague",
                    "EntertainmentAgency", "Pagila", "chinook", "music", "f1"}}
# fk_min_hit 0.3: DySQL's own retail DB keeps sales/costs -> products at 31-33% (products trimmed to 24 of 72
# ids) and still has 25 tasks updating products; wrong FKs sit at 0-20%. See docs/data_gen/fk_calibration.md.
CFG = dict(tables=(3, 20), max_cols=250, rows=(200, 3_000_000), max_mb=300, min_fks=2, fk_min_hit=0.3,
           anchor_min_rows=5, long_text_avg_len=200, min_component_share=0.6, overlap=0.6)
DEDUP_ORDER = ["bird", "spider2", "spider1", "synsql"]
COLS = ["source", "split", "db", "pass", "dup_of", "fail_reasons", "n_tables", "n_cols", "total_rows", "size_mb",
        "n_fks_declared", "n_fks_inferred", "n_fks_valid", "invalid_fks", "unverified_fks", "has_person_named",
        "anchor_kinds", "person_anchors", "entity_anchors", "update_targets", "targets_no_key",
        "composite_key_tables", "long_text_cols", "empty_string_cols", "fragmented", "leak_match",
        "max_leak_overlap", "table_names", "path"]

def _profile(a):
    source, path = a
    try:
        return source, profile_db(path)
    except Exception as e:
        return source, {"db": os.path.splitext(os.path.basename(path))[0], "path": path, "error": str(e)}

def _split(source, path):
    return "dev" if "/dev/" in path else ("test" if source == "spider2" else "train")

def _anchor_type(r):
    return "named" if r["has_person_named"] else ("id_only" if "person_id_only" in r["anchor_kinds"] else "entity")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", action="append", required=True, help="name=glob")
    ap.add_argument("--out", required=True)
    ap.add_argument("--candidates")
    ap.add_argument("--anchors-json", help="full anchor records of the kept candidates (input for the tree builder)")
    ap.add_argument("--holdout", action="append", default=[], help="source=eval question json (db_id fields)")
    ap.add_argument("--fk-extra", help="json: {'source:db': [fk, ...]} hand-checked FKs the inference rules miss")
    ap.add_argument("--workers", type=int, default=16)
    a = ap.parse_args()
    excluded = {k: set(v) for k, v in LEAK.items()}
    for h in a.holdout:
        name, path = h.split("=", 1)
        excluded.setdefault(name, set()).update(ex["db_id"] for ex in json.load(open(path)))
    extra = json.load(open(a.fk_extra)) if a.fk_extra else {}
    jobs = [(name, f) for s in a.source for name, pat in [s.split("=", 1)] for f in sorted(glob.glob(pat))]
    with Pool(a.workers) as p:
        profiles = p.map(_profile, jobs, chunksize=16)
    # reference schemas: DySQL's DBs plus every explicitly excluded DB, so copies of them are caught too
    leak_ref = {f"dysql:{os.path.basename(f)[:-7]}": schema_items(profile_db(f))
                for f in glob.glob(f"{ENVS}/*/data/*.sqlite")}
    leak_ref.update({f"{s}:{p['db']}": schema_items(p) for s, p in profiles
                     if "error" not in p and p["db"] in excluded.get(s, ())})
    rows = []
    for s, p in profiles:
        if "error" in p:
            rows.append({"source": s, "split": _split(s, p["path"]), "db": p["db"], "path": p["path"], "pass": False,
                         "fail_reasons": [f"error: {p['error']}"], "table_names": [], "schema": []})
            continue
        own = f"{s}:{p['db']}"
        cfg = {**CFG, "leak_names": excluded.get(s, set()),
               "leak_ref": {k: v for k, v in leak_ref.items() if k != own}}
        rows.append({"source": s, "split": _split(s, p["path"]), "path": p["path"],
                     **evaluate(p, cfg, extra.get(own, ()))})
    rows = dedup(rows, DEDUP_ORDER, threshold=CFG["overlap"])
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    def write(path, rs):
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, COLS); w.writeheader()
            for r in rs:
                w.writerow({k: "; ".join(v) if isinstance(v, list) else v for k, v in r.items() if k in COLS})
    write(a.out, rows)
    keep = [r for r in rows if r["pass"] and not r["dup_of"]]
    if a.candidates:
        os.makedirs(os.path.dirname(os.path.abspath(a.candidates)), exist_ok=True)
        write(a.candidates, keep)
    if a.anchors_json:
        with open(a.anchors_json, "w", encoding="utf-8") as f:
            json.dump({f"{r['source']}:{r['db']}": r["anchors"] for r in keep}, f, ensure_ascii=False, indent=1)
    print(f"{'source':8s} {'total':>6s} {'pass':>5s} {'dup':>4s} {'keep':>5s}  top fail reasons")
    for s in dict.fromkeys(r["source"] for r in rows):
        rs = [r for r in rows if r["source"] == s]
        fr = Counter(x for r in rs for x in r["fail_reasons"])
        print(f"{s:8s} {len(rs):6d} {sum(r['pass'] for r in rs):5d} {sum(bool(r['dup_of']) for r in rs):4d} "
              f"{sum(r in keep for r in rs):5d}  {dict(fr.most_common(6))}")
    print(f"keep={len(keep)}  by anchor type: {dict(Counter(_anchor_type(r) for r in keep))}")

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 重跑**

```bash
T=~/Documents/Isa/text2sql_bench; cd DySQL-Bench && ~/miniconda3/envs/dysql/bin/python scripts/select_dbs.py \
  --source "bird=$T/bird/train/train_databases/*/*.sqlite" --source "bird=$T/bird/dev/dev_databases/*/*.sqlite" \
  --source "spider2=$T/spider2_lite/sqlite/*.sqlite" --source "spider1=$T/spider1/test_database/*/*.sqlite" \
  --source "synsql=$T/synsql/databases/*/*.sqlite" \
  --holdout "spider1=$T/spider1/dev.json" --holdout "spider1=$T/spider1/test.json" \
  --fk-extra ../docs/data_gen/fk_extra.json \
  --out results/db_select/db_select_all.csv --candidates ../docs/data_gen/candidate_dbs.csv \
  --anchors-json ../docs/data_gen/candidate_anchors.json
```

用时约 5 分钟，其中 BIRD 的 movie_platform 一个库约 95 秒。

预期结果（2026-09-25 用同一份代码在临时目录预跑）：
- **两个库都保留时**：keep = 56（BIRD 41、Spider2 8、Spider1 7）。按锚点类型：named 24、id_only 10、entity 22。
- **按 Step 2 排除 activity_1 和 college_3 时**：keep = 55（BIRD 41、Spider2 8、Spider1 6）；按锚点类型：named 23、id_only 10、entity 22。和上一种情况相比只少了 activity_1，college_3 也没有回来。

- [ ] **Step 5: 与旧清单对比，写 diff 文档**

```bash
cd /home/wmd3i/Documents/Isa/DySQL-Bench && git show 4bdf1cd:docs/data_gen/candidate_dbs.csv > /tmp/old_candidates.csv
~/miniconda3/envs/dysql/bin/python - <<'EOF'
import csv
old = {(r["source"], r["db"]) for r in csv.DictReader(open("/tmp/old_candidates.csv"))}
allr = {(r["source"], r["db"]): r for r in csv.DictReader(open("DySQL-Bench/results/db_select/db_select_all.csv"))}
new = {(r["source"], r["db"]): r for r in csv.DictReader(open("docs/data_gen/candidate_dbs.csv"))}
for k in sorted(old - set(new)):
    r = allr[k]; print("OUT", k, r["fail_reasons"], r["dup_of"], r["invalid_fks"])
for k in sorted(set(new) - old):
    r = new[k]; print("IN ", k, r["person_anchors"], "|", r["entity_anchors"][:80])
EOF
```

（`4bdf1cd` 是生成旧 34 个候选的 commit。）

写 `docs/data_gen/2026-09-26-candidate-diff.md`，结构如下：

```markdown
# 候选库变化（旧 34 → 新 N）

规则变化：
- 人物表硬条件改为"锚点 + 范围内有更新目标"。
- 外键按命中率验证，阈值 0.3；没有值可查的外键记为未验证并保留。
- 推断修正：guid 列、通用 id、复合主键成员、1:1 扩展表、按取值推断。
- 新增复合键识别。

## 退出（M 个）
| 来源 | 库 | 原因 |
|---|---|---|

## 进入（K 个）
| 来源 | 库 | 锚点类型 | 人物锚点 | 实体锚点（前 3） |
|---|---|---|---|---|

## 预期核对
- 预跑的退出项：
  - superstore（no_anchor）：people 按地区重复，没有单列键。
  - thrombosis_prediction（fks）：Examination → Patient 命中率 0.091。
  - college_3：两个都保留时，是 activity_1 的重复库。
- 预跑的新增项：
  - movies_4、delivery_center。
  - 之前"没有人物表"的库，以实体锚点进入：airline、california_schools、card_games、chicago_crime、citeseer、college_completion、food_inspection、genes、mental_health_survey、menu、restaurant、shakespeare、shooting、toxicology、university、video_games、bike_1、flight_4、wine_1、Airlines、imdb_movies。
- 仍然退出的：Db-IMDB（fragmented）。M_Cast.PID 带前导空格，连不上 Person 表。这是数据本身的问题。
- 与预期不符的每一项：写明实际的 fail_reasons / anchors，并判断是规则问题还是库本身的问题。
```

规则问题要回到对应的 Task，先补测试再改。不要为了凑预期数字去调阈值。

- [ ] **Step 6: Commit**

```bash
git add DySQL-Bench/scripts/select_dbs.py docs/data_gen/fk_extra.json docs/data_gen/candidate_dbs.csv docs/data_gen/candidate_anchors.json DySQL-Bench/results/db_select/db_select_all.csv docs/data_gen/2026-09-26-candidate-diff.md
git commit -m "feat(select_dbs): anchor-based rerun with FK extras and anchor JSON; diff vs the 34-DB list

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 11: 从 CSV 生成候选库 md

**Files:**
- Create: `DySQL-Bench/scripts/render_candidates_md.py`、`DySQL-Bench/tests/test_render_candidates_md.py`
- Create: `docs/data_gen/db_notes.csv`
- Modify: `docs/data_gen/candidate_dbs.md`（生成）

**Interfaces:**
- Consumes: Task 10 的 `candidate_dbs.csv`；`docs/data_gen/db_topics.csv`（`source, db, topic`，316 个库的中文主题）。
- Produces:
  - `render(candidates_csv, notes_csv) -> str`
  - `db_notes.csv`，列为 `source, db, topic, note, entity_anchors_ok`。
    - `entity_anchors_ok`：只对没有人物锚点的库填写，内容是人工确认过有意义的实体锚点，例如 `Recipe`；字典表不填。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_render_candidates_md.py
import csv, importlib.util, os
spec = importlib.util.spec_from_file_location("render_candidates_md", os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "render_candidates_md.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

def _csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, list(rows[0])); w.writeheader(); w.writerows(rows)

ROW = dict(n_fks_declared=14, n_fks_inferred=0, n_fks_valid=14, invalid_fks="", long_text_cols="")

def test_render_counts_anchor_types_and_lists_anchors(tmp_path):
    cand, notes = tmp_path / "c.csv", tmp_path / "n.csv"
    _csv(cand, [
        {**ROW, "source": "bird", "split": "train", "db": "books", "n_tables": 15, "n_cols": 50, "total_rows": 84337,
         "size_mb": 4.1, "has_person_named": "True", "anchor_kinds": "entity; person_named",
         "person_anchors": "customer[first_name,last_name]; author[author_name]",
         "entity_anchors": "book[title]; publisher[publisher_name]; country[country_name]; cust_order[]"},
        {**ROW, "source": "spider2", "split": "test", "db": "Airlines", "n_tables": 8, "n_cols": 40, "total_rows": 1000,
         "size_mb": 30.0, "has_person_named": "False", "anchor_kinds": "entity", "person_anchors": "",
         "entity_anchors": "flights[]", "long_text_cols": "boarding_passes.seat_no"}])
    _csv(notes, [{"source": "bird", "db": "books", "topic": "网上书店订单", "note": "customer 2,000 人", "entity_anchors_ok": ""},
                 {"source": "spider2", "db": "Airlines", "topic": "", "note": "", "entity_anchors_ok": "flights"}])
    md = mod.render(str(cand), str(notes))
    assert "| BIRD | 1 | 1 | 0 | 0 |" in md and "| Spider2-lite（SQLite） | 1 | 0 | 0 | 1 |" in md
    assert "| **合计** | **2** | **1** | **0** | **1** |" in md
    assert "## BIRD（1 个）" in md and "| books | train | 网上书店订单 | 15 | 50 | 84,337 | 4.1 | 14/14/0 |" in md
    assert "customer[first_name,last_name], author[author_name]" in md
    assert "book[title], publisher[publisher_name], country[country_name] 等 4 个" in md
    assert "| Airlines | test |  |" in md and "boarding_passes.seat_no | 确认锚点：flights |" in md
```

- [ ] **Step 2: 确认测试失败**

Run: `cd DySQL-Bench && ~/miniconda3/envs/dysql/bin/python -m pytest -q tests/test_render_candidates_md.py`
Expected: FileNotFoundError（脚本不存在）

- [ ] **Step 3: 实现**

```python
#!/usr/bin/env python3
"""Render docs/data_gen/candidate_dbs.md from the selector CSV plus hand-written topics/notes (db_notes.csv).
Usage (from DySQL-Bench/):
  python scripts/render_candidates_md.py ../docs/data_gen/candidate_dbs.csv ../docs/data_gen/db_notes.csv \
    > ../docs/data_gen/candidate_dbs.md"""
import csv, sys

SOURCES = {"bird": "BIRD", "spider2": "Spider2-lite（SQLite）", "spider1": "Spider 1.0", "synsql": "SynSQL"}
HEAD = ("| 数据库 | 划分 | 主题 | 表 | 列 | 总行数 | MB | FK 有效/声明/推断 | 人物锚点（姓名列） | 实体锚点（名称列） "
        "| 无效外键 | 长文本列 | 备注 |\n|---|---|---|---|---|---|---|---|---|---|---|---|---|")


def _items(s):
    return [x for x in (s or "").split("; ") if x]


def _list(s, limit=None):
    xs = _items(s)
    if limit and len(xs) > limit:
        return ", ".join(xs[:limit]) + f" 等 {len(xs)} 个"
    return ", ".join(xs)


def _kind(r):
    kinds = set(_items(r["anchor_kinds"]))
    return "named" if r["has_person_named"] == "True" else ("id_only" if "person_id_only" in kinds else "entity")


def render(candidates_csv, notes_csv):
    rows = list(csv.DictReader(open(candidates_csv, encoding="utf-8")))
    notes = {(n["source"], n["db"]): n for n in csv.DictReader(open(notes_csv, encoding="utf-8"))}
    out = [f"# 候选库清单（{len(rows)} 个）\n",
           "由 `DySQL-Bench/scripts/render_candidates_md.py` 从 `docs/data_gen/candidate_dbs.csv`（筛选器输出）和 "
           "`docs/data_gen/db_notes.csv`（人工主题与备注）生成，不要手改。规则见 `docs/2026-09-24-data-gen-db-selection.md`。\n",
           "锚点写作 `表[姓名或名称列]`。人物锚点里有姓名列的是带名字的人，方括号为空的是只有 ID 的人；"
           "实体锚点按 有名称列 > 下游表多 > 行数多 排序，只列前 3 个。\n",
           "| 来源 | 候选数 | 有带名字的人物锚点 | 只有 ID 的人物锚点 | 只有实体锚点 |", "|---|---|---|---|---|"]
    tot = [0, 0, 0, 0]
    for s, label in SOURCES.items():
        rs = [r for r in rows if r["source"] == s]
        if not rs:
            continue
        k = [_kind(r) for r in rs]
        c = [len(rs), k.count("named"), k.count("id_only"), k.count("entity")]
        tot = [a + b for a, b in zip(tot, c)]
        out.append(f"| {label} | " + " | ".join(map(str, c)) + " |")
    out.append("| **合计** | " + " | ".join(f"**{x}**" for x in tot) + " |\n")
    for s, label in SOURCES.items():
        rs = [r for r in rows if r["source"] == s]
        if not rs:
            continue
        out.append(f"## {label}（{len(rs)} 个）\n\n{HEAD}")
        for r in rs:
            n = notes.get((s, r["db"]), {})
            note = n.get("note", "")
            if n.get("entity_anchors_ok"):
                note = (note + "；" if note else "") + f"确认锚点：{n['entity_anchors_ok']}"
            out.append(f"| {r['db']} | {r['split']} | {n.get('topic', '')} | {r['n_tables']} | {r['n_cols']} | "
                       f"{int(r['total_rows']):,} | {r['size_mb']} | "
                       f"{r['n_fks_valid']}/{r['n_fks_declared']}/{r['n_fks_inferred']} | "
                       f"{_list(r['person_anchors'])} | {_list(r['entity_anchors'], 3)} | {_list(r['invalid_fks'])} | "
                       f"{_list(r['long_text_cols'])} | {note} |")
        out.append("")
    return "\n".join(out)


if __name__ == "__main__":
    sys.stdout.write(render(sys.argv[1], sys.argv[2]))
```

- [ ] **Step 4: 确认测试通过**

Run: `cd DySQL-Bench && ~/miniconda3/envs/dysql/bin/python -m pytest -q tests/test_render_candidates_md.py`
Expected: 1 passed

- [ ] **Step 5: 生成 db_notes.csv 初稿**

从 `docs/data_gen/db_topics.csv` 取主题。旧 md（HEAD 版的 `candidate_dbs.md`）里对旧 34 个库的人工备注，只保留仍然成立的几条：规模、同名、重复、编号名、长文本，其余由新列自动表达。

```bash
cd /home/wmd3i/Documents/Isa/DySQL-Bench && ~/miniconda3/envs/dysql/bin/python - <<'EOF'
import csv
topics = {(r["source"], r["db"]): r["topic"] for r in csv.DictReader(open("docs/data_gen/db_topics.csv", encoding="utf-8"))}
keep_notes = {
    ("bird", "car_retails"): "customers 是公司（带联系人姓名）；44/122 个联系人姓名与 Northwind/retail_world 相同",
    ("bird", "student_loan"): "名字是 student1…student1000（编号）",
    ("bird", "superhero"): "虚构角色；full_name 有 247/750 为空或 '-'",
    ("bird", "regional_sales"): "Customers 是 50 家公司；人名在 Sales Team 表",
    ("bird", "shipping"): "规模小：driver 11 人、customer 100",
    ("bird", "student_club"): "规模小：member 33 人",
    ("spider1", "college_2"): "学生名是单个姓氏，有重名",
    ("spider2", "school_scheduling"): "规模小：全库 811 行",
    ("spider2", "Brazilian_E_Commerce"): "customer_id 每单一个，真正的人是 customer_unique_id（32 位哈希）",
    ("spider2", "AdventureWorks"): "NULL 存成空串；只有 salesperson 一张无名字的人物表",
}
rows = []
for r in csv.DictReader(open("docs/data_gen/candidate_dbs.csv", encoding="utf-8")):
    k = (r["source"], r["db"])
    rows.append({"source": k[0], "db": k[1], "topic": topics.get(k, ""), "note": keep_notes.get(k, ""),
                 "entity_anchors_ok": ""})
with open("docs/data_gen/db_notes.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, ["source", "db", "topic", "note", "entity_anchors_ok"]); w.writeheader(); w.writerows(rows)
print(len(rows), "rows;", sum(1 for r in rows if not r["topic"]), "without topic")
EOF
```

Expected：行数等于候选数，`without topic` 为 0。不为 0 时，查 `db_topics.csv` 里这个库名的拼写。

- [ ] **Step 6: 人工确认实体锚点**

对 `has_person_named == False` 且 `anchor_kinds` 只有 `entity` 的库（预跑是 22 个），逐个看 `entity_anchors`，把有意义的实体锚点填进 `entity_anchors_ok`：
- 可以当作"某人拥有或负责"的对象才算，例如 Recipe、game、university、Menu、cards。
- country、genre、platform 这类字典表不算。
- 一个也没有的库，在 note 里写"无合适实体锚点"，交给用户决定去留。

先由执行者给出建议，**用户确认后**再写入文件。

- [ ] **Step 7: 生成 md 并检查**

```bash
cd /home/wmd3i/Documents/Isa/DySQL-Bench/DySQL-Bench && ~/miniconda3/envs/dysql/bin/python scripts/render_candidates_md.py ../docs/data_gen/candidate_dbs.csv ../docs/data_gen/db_notes.csv > ../docs/data_gen/candidate_dbs.md
```

打开 md 检查：
- 标题里的候选数等于 CSV 行数。
- 汇总表的合计等于各来源之和。
- 每个库都有主题。

- [ ] **Step 8: Commit**

```bash
git add DySQL-Bench/scripts/render_candidates_md.py DySQL-Bench/tests/test_render_candidates_md.py docs/data_gen/db_notes.csv docs/data_gen/candidate_dbs.md
git commit -m "docs(data_gen): candidate_dbs.md rendered from CSV + db_notes.csv, with person/entity anchors

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 12: 更新选库规则文档

**Files:**
- Modify: `docs/2026-09-24-data-gen-db-selection.md`：`### B. 结构要求`、`## 自动筛选结果`、`## 已决定事项与备注` 三节。
- Delete: `docs/data_gen/person_named_dbs.csv`：已被锚点记录取代；它从未 commit，直接删除文件即可。

- [ ] **Step 1: 改写规则 B**

把 `### B. 结构要求` 整节替换为：

```markdown
### B. 结构要求（2026-09-26 起：锚点 + 更新目标）

DySQL 的任务都是"围绕某个锚点行，修改它范围内的数据"。锚点多数是人，也可以是车、菜谱这类实体。依据是 `docs/data_gen/dysql_task_types.md` 对 1062 个任务的实测：
- 说话人是库里真人的占 67%，而且几乎都报名字。
- 22.6% 是库外的人代办、改库里人物的数据。
- 7.8% 是库外的人改实体数据（car/cookbook，库里没有人物表）。
- 19% 的任务会同时改不属于任何人的公共数据（产品、成本、歌单）。

打分只比较 DB 状态，人名和身份核对都不参与。所以硬条件是结构：

- **外键先验证再使用。**
  - 声明的、按名字推断的、按取值推断的（`winner_id`/`loser_id` 这类角色命名列）、人工补充的（`docs/data_gen/fk_extra.json`）外键，都要用数据算命中率。
  - 命中率低于 0.3 的外键不参与任何规则，只列在 `invalid_fks`。
  - 子表没有值可查的记为未验证（`unverified_fks`），照常使用。
  - 阈值依据见 `docs/data_gen/fk_calibration.md`。
- **更新目标：** 至少 1 行，并且至少有 1 个可修改列。
  - 可修改列：排除本行自己的键、guid 列、全空的列、平均长度超过 200 的列。**外键列算可修改列**：DySQL 37% 的 UPDATE 改的是外键列，例如换经纪人。
  - 不设更高的行数下限：DySQL 在 4–46 行的小表上大量写入。
- **锚点：**
  - 有单列键，行数 ≥ 5，沿有效外键向下 2 步以内有子表。有名字的人物可以没有子表，以自己为写入目标，例如"改我的工资"。
  - 范围 = 锚点 + 下游子表 + 这些表引用的父表，范围内至少有一个更新目标。
  - 父表算进范围，是因为 DySQL 有 19% 的任务改公共数据。
  - DySQL 自己的 13 个库，全部 2432 条写入现存表的标准答案语句都落在锚点范围内（`tests/test_dysql_acceptance.py`）。
- **锚点类型只标注、不淘汰：**
  - `person_named`：人物表，有姓名列。
  - `person_id_only`：人物表，只有 ID。
  - `entity`：车、菜谱、球队等。
  - 实体锚点里混有字典表（country、genre），所以没有人物锚点的库，要人工在 `db_notes.csv` 的 `entity_anchors_ok` 里确认哪些实体锚点有意义。
- **有效外键 + 未验证外键 ≥ 2**；只用这些外键建图时，最大连通分量 ≥ 60% 的表。
- **只记录、不淘汰的质量标记：**
  - `targets_no_key`：没有键的更新目标，gold SQL 要用多列 WHERE。
  - `long_text_cols`、`empty_string_cols`（把 `''` 当 NULL 用的列）、`composite_key_tables`。
```

- [ ] **Step 2: 更新结果和备注**

- **`## 自动筛选结果`：**
  - 标题改为 `## 自动筛选结果（2026-09-26 更新：锚点规则）`。
  - 表格替换成 `docs/data_gen/candidate_dbs.md` 的汇总表。
  - 正文一句话指向 `docs/data_gen/2026-09-26-candidate-diff.md`。
- **`## 已决定事项与备注`：**
  - **注 3**（14 个无人物表的库）改为：它们在锚点规则下重新参与了筛选，进入和未进入的结果见 diff 文档；不再有"第二阶段"。
  - **注 4** 整条替换为：

```markdown
4. **任务类型与生成阶段的比例控制（选库阶段只标注锚点类型）。** `docs/data_gen/dysql_task_types.md` 把 DySQL 的 1062 个任务按"谁在说话 × 改谁的数据"分为 7 类：
   - 真人改自己的数据 40.3%
   - 真人改自己的 + 公共数据 14.5%
   - 真人只改公共数据 4.7%
   - 真人改别人的数据 5.4%
   - 库外说话人改人物数据 22.6%
   - 库外说话人改实体数据 7.8%
   - 标准答案不改库 4.7%

   生成阶段要做到：
   - 按任务选"说话人 + 写入范围"，并参照这个比例配。一个任务经常同时涉及几个锚点，例如客户 + 产品、经纪人 + 乐队。
   - 只报 ID 的说话方式在评测里几乎不存在（<1%）。只有 ID 的人物库可以用，但比例要控制。
   - 最后一类"标准答案不改库"要过滤掉：标准答案至少要改一行。
```

  - **新增注 5**：给建树脚本的接口。
    - `docs/data_gen/candidate_anchors.json` 里每个锚点有这些字段：`table`（根）、`key`（用户报的 ID）、`kind`、`names`（姓名或名称列）、`down`（子表，写入目标）、`up`（父表，背景信息和公共数据，对应 DySQL 数据池里的产品详情、负责员工）、`update_targets`。
    - 建树脚本另开计划。

- [ ] **Step 3: Commit**

```bash
rm -f docs/data_gen/person_named_dbs.csv
git add docs/2026-09-24-data-gen-db-selection.md
git commit -m "docs(db-selection): rule B is anchor + update targets; task taxonomy; tree-builder interface

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

## 后续（不在本计划内）

**建树脚本。** 用来替代 DySQL 没有放出来的那部分：生成 `lean_tree_v2.jsonl`、`tree_music.jsonl`、`tree_EU_soccer_team.jsonl` 的代码。
- **输入：** `candidate_anchors.json`，以及有效外键。
- **做法：** 对每个锚点行，沿外键向下抽样子表的行，向上取父表的名称和描述列。
- **输出：** 与 `data_pipeline_shell/generate_sqlbench_multiTurn_qa.py` 读取格式一致的 JSONL。
- **生成阶段的比例：** 按 `docs/data_gen/dysql_task_types.md` 控制说话人类型和写入范围的比例，并过滤"标准答案不改库"的任务。
