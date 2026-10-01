# 训练任务生成 v2：实施计划 2（库档案、嵌套建树、检查读档案）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 23 个库各建一份人工确认过的库档案，按档案建嵌套事件树，让出题 prompt 和执行检查读同一份档案、用同一套归属标签，并用真实出题的冒烟证明要求的类型和算出的类型对得上。

**Architecture:**
- 新模块 `db_profile.py`：档案格式、校验、写入范围、审阅页。
- 新模块 `owners.py`：归属追溯，建树打标签和执行检查共用。
- `trees.py` 改成按档案建嵌套事件树。
- `prompt.py` 改读新树：按难度展示 3–12 条事件，不再出第 4 类。
- `check.py` 带档案时按档案定范围，拒掉 `no_insert` 和算出第 4 类的候选；不带档案时照旧（用于 DySQL 金标准、v1 候选）。
- `profile_draft.py`：让 GLM 起草档案。

顺序：档案模块 → 归属模块 → 检查读档案 → 建树 → 出题 → 起草 → 起草 23 份并由你确认 → 验证。

**Tech Stack:** Python 3.11（conda env `dysql`）。
- 标准库：`sqlite3`、`json`、`hashlib`、`concurrent.futures`。
- 已装：`sqlparse`、`requests`、`pytest`。
- 出题模型：GLM-5.3（`.env` 的 `TASKGEN_GEN_*`）。

不加新依赖。

**Spec:** [2026-10-01-taskgen-v2-design.md](2026-10-01-taskgen-v2-design.md)，相关部分是 §4.1 档案、§4.2 建树、§4.5 执行检查、§5 阶段 B 和 C。下面"本计划新定的事"补充的规则，Task 8 会写回设计文档。

**原型：** 本计划的代码和测试已在 scratchpad 的原型里全部跑通：125 个测试通过，在 7 个真实库上建了树，用 GLM 起草了 3 份档案，出了 5 条题且全部过检查。执行时仍按 TDD：先写测试、看它失败，再写实现。

## 本计划新定的事（设计里没写到，请审阅时确认）

1. **用档案检查时，算出第 4 类的候选拒掉。** 新的拒绝原因是 `other_person`。
   - 理由：D6 定了这一轮不出第 4 类，但出题模型仍可能写出改别人数据的 gold。agent policy 要求拒绝这种请求，留着就是在教 agent 违反 policy。
   - 不带档案时（DySQL 金标准、v1 候选）照旧不拒。
2. **根行先抽有事件的，不够再抽没有事件的。**
   - v1 只抽有子行的人：hr_1 的 107 个员工只用上 7 个，food_inspection_2 的 75 个只用上 27 个。改后这类小库能多出题；大库不受影响，有事件的行本来就够。
   - 双根库按各自可用的行数分 `--n`，一个根的行不够，余下的名额让给另一个。
3. **档案格式的细化：**
   - 根只写 `{table, label, parents}`，身份键和姓名列只在 `persons` 里写一次。
   - 根也可以挂父行，例如客户的销售代表、学生的院系。
   - 边写成 `child.col -> parent.col`，复合外键写成 `child.(a, b) -> parent.(x, y)`。不在已知外键里的边，要有 ≥30% 的子行能在父表里找到。
   - 每张表都必须有角色，漏了就报错，逼着在 public 和 exclude 之间二选一。
   - 审阅字段 `notes`（Claude 的改动）和 `draft`（起草模型、轮数、没改掉的问题）不计入版本号。
4. **起草的输入：**
   - `data/profile_hints.json`：每库的根（设计 §4.1 定的）和已知的怪异点。
   - 两份手写的 DySQL 示例：chinook、entertainment。
   - 起草结果校验不过，就带着问题让模型重写，最多 2 次；根和提示不一致也算问题。
   - student_loan 的提示写的是"`bool` 排除、flag 表算属性表"。设计 §4.1 一处写"exclude bool 和 flag 表"，另一处又拿 flag 表当属性表的例子，这里取后者。你审档案时可以改。
5. **出题时展示的事件：**
   - 按难度抽 3–5 / 5–8 / 8–12 条。
   - 数据块超过 16000 字符，就从后往前减事件。
   - 超过 200 字符的文本值截断：WWE 的 Cards 存整页 HTML，一棵树能到 5 万字符。
   - 第 2、3 类先放一条带公共父行的事件，保证有公共数据可写。
6. **计划 1 留下的 minor，这次修掉的：**
   - INSERT OR REPLACE / UPSERT 覆盖已有的人物行，不再标 `new_person`。
   - 自动主键按每条 INSERT 执行前的状态现算，删掉最大行之后也对。
   - 重跑暂停时按 Ctrl-C 不再被吞掉。
   - `_MDY =` 的多余空白。
   - 补一个钉住表名大小写的测试。
   - 设计文档里的几处：D6 的"38 条"、D8 和 §4.4 的旧 ID 指标、14.5/14.4。

   **留给以后的：**
   - 时间函数漏网、数字左边粘着字母：计划 3 改字面量规则时一起改。
   - `task_stats` 的缓存问题：计划 5。
   - "放行的新主键值对之后任何字面量都生效"：要做 SQL 数据流分析，收益小，不做。
   - 设计 §5 阶段 B 的可选项（对 DySQL 的 13 个库也起草一遍，看根是否和论文一致）：不做。它要防的是起草出错，23 份档案都要你确认，已经覆盖了。

## Global Constraints

- 分支 `isa/data-gen`。每个 Task 单独 commit（Task 7 两个），commit message 以 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` 结尾。不要 push（用户自己 push）。
- `taskgen/v1/` 冻结：本计划不改其中任何文件，只读。
- 生成的任务不进 git：`taskgen/*/results/`、`taskgen/*/output/` 已在 `.gitignore`。
  - 每次 commit 前跑 `git diff --cached --name-only`，不能出现 `results/` 或 `output/`。
  - 文档里只写候选 id 和计数，不摘录题目内容。
  - 带库里数据行的样例树只写到 `results/`。
- 档案、提示、示例进 git，它们只有表名、列名、规则和描述：
  - 档案 `taskgen/v2/data/db_profiles.json`
  - 提示 `taskgen/v2/data/profile_hints.json`
  - 示例 `taskgen/v2/taskgen_v2/profile_examples.json`
- 档案只有用户能确认：`profile confirm` 只在用户确认之后运行（Task 7）。
- 秘密只在仓库根目录的 `.env`。不打印 key，只打印 `BASE_URL`、`MODEL` 两行；测试不联网，模型一律用假客户端。
- GLM 并发不超过 5。
- 命令约定：
  - `REPO=/home/wmd3i/Documents/Isa/DySQL-Bench`
  - `P=~/miniconda3/envs/dysql/bin/python`
  - 临时文件放 `S=/tmp/claude-1000/-home-wmd3i-Documents-Isa-DySQL-Bench/3cc9a46f-e1e3-4468-b1b8-b1054479803f/scratchpad/v2-plan2`（先 `mkdir -p $S`）
- 测试按目录跑：`cd $REPO/taskgen/v2 && $P -m pytest -q`。不要把 v1 和 v2 的测试放在同一个 pytest 进程里（文件同名）。
- SQL 里的表名、列名一律用 `taskgen_common.db_select._q()` 加引号：真实库里有 `Sales Orders`、`historical-terms`、`Customer Names`。
- 档案里的 quirks、description、label 用英文，因为它们会进英文 prompt；文档用中文。

## Review Focus

1. **带空格或连字符的表名、列名**（`Sales Orders`、`Customer Names`、`historical-terms`）出现在边、连接、校验和标签里：都要照常工作。→ Task 1、2、4 的测试（`"Student List"`）。
2. **TEXT 列里存着整数表的键**（WWE 的 `Matches.winner_id`）：边的命中率、建树时的连接、归属追溯都要认得。→ Task 1、2 的测试（`advisor.s_id`）。
3. **复合外键**（college_2 的 takes → section）：建树能挂上父行，归属追溯能走过去。→ Task 2、4 的测试。
4. **外键值为空**（没有销售代表的客户、商品为空的订单）：不挂父行，也不报错。→ Task 4 的测试。
5. **手改档案时写错**（列名、角色冲突、漏表、JSON 类型）：校验逐条报出来；trees、generate、check 拒绝未确认的档案；`profile confirm` 拒绝有问题的档案。→ Task 1、4、5、6 的测试。

---

### Task 1: 档案格式、校验、写入范围和审阅页（`db_profile.py`）

**Files:**
- Create: `taskgen/v2/taskgen_v2/db_profile.py`
- Create: `taskgen/v2/tests/v2_fixtures.py`：测试共用的库和档案。商店库的表和锚点从 `test_taskgen_trees.py` 挪过来，避免测试模块之间循环导入。
- Modify: `taskgen/v2/tests/test_taskgen_trees.py`：开头改成从 `v2_fixtures` 导入，并转出 `SHOP2`、`FKS`、`CUSTOMER`、`STAFF`，其他测试文件照旧从这里导入。
- Test: `taskgen/v2/tests/test_taskgen_db_profile.py`
- Modify: `taskgen/v2/README.md`：加计划 2 的链接，改动记录加一行。

**Interfaces:**
- Consumes: `taskgen_v2.io.DATA`；`taskgen_common.db_select._q`；`schema.pk_info(conn)`（只在测试和审阅页里用）。
- Produces:
  - 常量和类型：`db_profile.PROFILES_JSON`、`FIELDS`、`MIN_EDGE_HIT = 0.3`、`Edge(child, cols, parent, ref_cols)`（namedtuple；cols、ref_cols 是 tuple）。
  - 边：`parse_edge(text) -> Edge`（写错时抛 ValueError）、`edge_text(edge) -> str`。
  - 读写：
    - `load(path) -> {db_key: profile}`
    - `save(profiles, path)`
    - `get(db_key, path) -> profile`：没有档案或档案未确认时抛 ValueError。
  - 根：
    - `version(profile) -> str`：10 位 hash。
    - `root_anchor(profile, table) -> {"table", "key", "names"}`：不是根时抛 ValueError。
  - 角色与范围：`parent_nodes(profile)`、`edges(profile) -> [Edge]`、`used_tables(profile) -> set`、`scope_tables(profile) -> set`。
  - 校验：`edge_hit(conn, edge) -> float | None`、`validate(profile, conn, fks=(), composite=()) -> [str]`。
  - 审阅页：`pk_classes(pk)`、`render_md(entries) -> str`。entries 形如 `[{"key", "profile", "errors", "pk"}]`。
  - 测试夹具 `v2_fixtures`：`SHOP2`、`FKS`、`CUSTOMER`、`STAFF`、`SHOP_PROFILE`、`SCHOOL`、`SCHOOL_FKS`、`SCHOOL_COMPOSITE`、`SCHOOL_PROFILE`。

- [ ] **Step 1: 写测试夹具和会失败的测试**

`taskgen/v2/tests/v2_fixtures.py`：

```python
# tests/v2_fixtures.py -- fixtures shared by the v2 tests (no tests here). The shop tables and anchors moved here from
# test_taskgen_trees.py, which re-exports them for the older test modules.
from taskgen_common.testing import SHOP, rows

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

SHOP_PROFILE = {
    "roots": [{"table": "customers", "label": "customer", "parents": []}],
    "persons": {"customers": {"key": "customer_id", "name_cols": ["first_name", "last_name"], "same_as": []},
                "staff": {"key": "staff_id", "name_cols": ["name"], "same_as": []}},
    "events": [{"table": "orders", "label": "orders", "path": ["orders.customer_id -> customers.customer_id"],
                "parents": [{"table": "products", "via": "orders.product_id -> products.product_id", "parents": []}]},
               {"table": "order_items", "label": "order items",
                "path": ["orders.customer_id -> customers.customer_id", "order_items.order_id -> orders.order_id"], "parents": []}],
    "attributes": [], "public": ["products"], "exclude": [], "no_insert": [], "quirks": [],
    "description": "A small shop.", "confirmed": True}

# a table name with a space, a composite foreign key, an edge only the profile knows (advisor.s_id is TEXT and holds
# "Student List".sid), another person under an event, a 1:1 attribute, a root parent, an excluded helper table
SCHOOL = """
CREATE TABLE dept (dept_name TEXT PRIMARY KEY, building TEXT);
CREATE TABLE "Student List" (sid INTEGER PRIMARY KEY, name TEXT, dept TEXT REFERENCES dept(dept_name));
CREATE TABLE teacher (tid INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE section (course TEXT, sec INTEGER, title TEXT, PRIMARY KEY (course, sec));
CREATE TABLE takes (sid INTEGER REFERENCES "Student List"(sid), course TEXT, sec INTEGER, grade TEXT,
                    FOREIGN KEY (course, sec) REFERENCES section(course, sec));
CREATE TABLE advisor (s_id TEXT, t_id INTEGER REFERENCES teacher(tid));
CREATE TABLE flags (sid INTEGER PRIMARY KEY REFERENCES "Student List"(sid), honors INTEGER);
CREATE TABLE calendar (day TEXT PRIMARY KEY);
INSERT INTO dept VALUES ('d0', 'B0'), ('d1', 'B1');
INSERT INTO section VALUES ('c1', 1, 'Algebra'), ('c1', 2, 'Algebra'), ('c2', 1, 'Biology');
INSERT INTO calendar VALUES ('2024-01-01'), ('2024-01-02');
""" + rows('"Student List"', 10, lambda i: f"{i},'s{i}','d{i % 2}'") + rows("teacher", 3, lambda i: f"{i},'t{i}'") \
    + rows("takes", 8, lambda i: f"{i},'c1',{1 + i % 2},'A'") + rows("takes", 8, lambda i: f"{i},'c2',1,'B'") \
    + rows("advisor", 9, lambda i: f"'{i}',{i % 3}") + rows("flags", 5, lambda i: f"{i},{i % 2}")
SCHOOL_FKS = [{"table": "Student List", "col": "dept", "ref_table": "dept", "ref_col": "dept_name", "hit": 1.0, "source": "declared"},
              {"table": "takes", "col": "sid", "ref_table": "Student List", "ref_col": "sid", "hit": 1.0, "source": "declared"},
              {"table": "advisor", "col": "t_id", "ref_table": "teacher", "ref_col": "tid", "hit": 1.0, "source": "declared"},
              {"table": "flags", "col": "sid", "ref_table": "Student List", "ref_col": "sid", "hit": 1.0, "source": "declared"}]
SCHOOL_COMPOSITE = [{"table": "takes", "cols": ["course", "sec"], "ref_table": "section", "ref_cols": ["course", "sec"], "hit": 1.0, "source": "declared"}]
SCHOOL_PROFILE = {
    "roots": [{"table": "Student List", "label": "student",
               "parents": [{"table": "dept", "via": "Student List.dept -> dept.dept_name", "parents": []}]}],
    "persons": {"Student List": {"key": "sid", "name_cols": ["name"], "same_as": []},
                "teacher": {"key": "tid", "name_cols": ["name"], "same_as": []}},
    "events": [{"table": "takes", "label": "enrolments", "path": ["takes.sid -> Student List.sid"],
                "parents": [{"table": "section", "via": "takes.(course, sec) -> section.(course, sec)", "parents": []}]},
               {"table": "advisor", "label": "advisors", "path": ["advisor.s_id -> Student List.sid"],
                "parents": [{"table": "teacher", "via": "advisor.t_id -> teacher.tid", "parents": []}]}],
    "attributes": [{"table": "flags", "of": "Student List", "via": "flags.sid -> Student List.sid"}],
    "public": ["dept", "section"], "exclude": ["calendar"], "no_insert": ["section"],
    "quirks": ["dept names are codes such as d0."], "description": "A small school.", "confirmed": True}
```

`taskgen/v2/tests/test_taskgen_trees.py` 的开头，即从第一行到 `STAFF = {...}` 结束，换成下面这些。原来的 8 个测试函数不动，Task 4 再换：

```python
# tests/test_taskgen_trees.py
import random, sqlite3
import pytest
from taskgen_common.testing import make_db
from v2_fixtures import SHOP2, FKS, CUSTOMER, STAFF   # noqa: F401 (the older test modules import them from here)
from taskgen_v2 import trees
```

`taskgen/v2/tests/test_taskgen_db_profile.py`：

```python
# tests/test_taskgen_db_profile.py
import copy, sqlite3
import pytest
from taskgen_common.testing import make_db
from v2_fixtures import SHOP2, FKS, SHOP_PROFILE, SCHOOL, SCHOOL_FKS, SCHOOL_COMPOSITE, SCHOOL_PROFILE
from taskgen_v2 import db_profile, schema

@pytest.fixture
def shop(tmp_path):
    return sqlite3.connect(make_db(tmp_path, "shop2", SHOP2))


@pytest.fixture
def school(tmp_path):
    return sqlite3.connect(make_db(tmp_path, "school", SCHOOL))


def test_edges_parse_single_composite_and_spaced_names():
    e = db_profile.parse_edge("Sales Orders._CustomerID -> Customers.CustomerID")
    assert e == db_profile.Edge("Sales Orders", ("_CustomerID",), "Customers", ("CustomerID",))
    e = db_profile.parse_edge("takes.(course, sec) -> section.(course, sec)")
    assert e.cols == ("course", "sec") and e.parent == "section"
    assert db_profile.edge_text(e) == "takes.(course, sec) -> section.(course, sec)"
    assert db_profile.parse_edge("historical-terms.bioguide -> historical.bioguide_id").child == "historical-terms"
    for bad in ["orders.customer_id", "a.b -> c.d -> e.f", "t.(a, b) -> u.x", "orders -> customers.id", None]:
        with pytest.raises(ValueError):
            db_profile.parse_edge(bad)


def test_valid_profiles_have_no_problems(shop, school):
    assert db_profile.validate(SHOP_PROFILE, shop, FKS) == []
    # the advisor edge is in no foreign key list: its values decide (TEXT '3' finds INTEGER 3)
    assert db_profile.validate(SCHOOL_PROFILE, school, SCHOOL_FKS, SCHOOL_COMPOSITE) == []


def test_validate_names_every_problem(shop):
    p = copy.deepcopy(SHOP_PROFILE)
    p["persons"]["customers"]["name_cols"] = ["first_name", "surname"]
    p["events"][0]["parents"][0]["via"] = "orders.product_id -> customers.customer_id"
    p["events"][1]["path"] = ["order_items.order_id -> orders.order_id"]
    p["public"] = ["products", "staff"]
    errs = "\n".join(db_profile.validate(p, shop, FKS))
    assert "persons.customers: no column customers.surname" in errs
    assert "events[0].parents[0].via: ends at customers, expected products" in errs
    assert "events[1].path[0]: orders is not a root" in errs
    assert "public: staff hold people" in errs
    p = copy.deepcopy(SHOP_PROFILE)
    p["public"], p["events"][0]["parents"] = [], []
    p["events"].append({"table": "order_items", "label": "x", "path": ["order_items.note -> customers.first_name"], "parents": []})
    errs = "\n".join(db_profile.validate(p, shop, FKS))
    assert "tables without a role (list them in public or exclude): products" in errs
    assert "events[2].path[0]: only 0% of order_items rows find a customers row; not a foreign key" in errs
    assert db_profile.validate({**SHOP_PROFILE, "exclude": ["orders"]}, shop, FKS) == ["exclude: orders also have a role"]
    assert db_profile.validate({**SHOP_PROFILE, "events": [{**SHOP_PROFILE["events"][0], "path": "orders.customer_id -> customers.customer_id"}]},
                               shop, FKS) == ["events[0].path: wrong JSON type (see the field list)"]
    assert db_profile.validate({"roots": []}, shop, FKS)[0].startswith("missing fields: persons")
    assert db_profile.validate({**SHOP_PROFILE, "persons": {"customers": "customer_id"}}, shop, FKS)[0].startswith("malformed profile")


def test_scope_edges_version_and_root_anchor():
    assert db_profile.scope_tables(SCHOOL_PROFILE) == {"Student List", "teacher", "takes", "advisor", "section", "dept", "flags"}
    p = {**SHOP_PROFILE, "persons": {**SHOP_PROFILE["persons"],
                                     "staff": {"key": "staff_id", "name_cols": ["name"], "same_as": ["orders.qty"]}}}
    assert db_profile.Edge("orders", ("qty",), "staff", ("staff_id",)) in db_profile.edges(p)
    v = db_profile.version(SHOP_PROFILE)
    assert v == db_profile.version({**SHOP_PROFILE, "confirmed": False, "notes": ["x"]}) != db_profile.version(p)
    assert db_profile.root_anchor(SCHOOL_PROFILE, "Student List") == {"table": "Student List", "key": "sid", "names": ["name"]}
    with pytest.raises(ValueError):
        db_profile.root_anchor(SCHOOL_PROFILE, "teacher")


def test_load_save_and_get_only_confirmed(tmp_path):
    path = str(tmp_path / "p.json")
    db_profile.save({"test:shop2": SHOP_PROFILE, "test:draft": {**SHOP_PROFILE, "confirmed": False}}, path)
    assert db_profile.load(path)["test:shop2"] == SHOP_PROFILE
    assert db_profile.get("test:shop2", path) == SHOP_PROFILE
    with pytest.raises(ValueError, match="not confirmed"):
        db_profile.get("test:draft", path)
    with pytest.raises(ValueError, match="no profile"):
        db_profile.get("test:none", path)
    assert db_profile.load(str(tmp_path / "missing.json")) == {}


def test_render_shows_roles_parents_keys_and_problems(school):
    bad = {**SCHOOL_PROFILE, "confirmed": False, "notes": ["Claude: moved dept to public"]}
    text = db_profile.render_md([{"key": "test:school", "profile": SCHOOL_PROFILE, "errors": [], "pk": schema.pk_info(school)},
                                 {"key": "test:bad", "profile": bad, "errors": ["persons.x: no table 'x'"], "pk": {}}])
    assert "## test:school　已确认　校验通过" in text and "## test:bad　未确认　1 个问题" in text
    assert "| 公共表 | dept, section |" in text and "| 排除 | calendar |" in text and "| 属性表 | flags → Student List |" in text
    assert "- takes（enrolments）\n  - section ← takes.(course, sec)" in text
    assert "- 根 Student List\n  - dept ← Student List.dept" in text
    assert "主键：可省 ID：Student List, flags, teacher；非整数或复合主键：calendar(day), dept(dept_name), section(course, sec)；无主键：advisor, takes" in text
    assert "- Claude: moved dept to public" in text and "- persons.x: no table 'x'" in text
```

- [ ] **Step 2: 跑测试，确认失败**

```bash
mkdir -p $S; cd $REPO/taskgen/v2
$P -m pytest -q tests/test_taskgen_db_profile.py 2>&1 | tail -3
$P -m pytest -q tests/test_taskgen_trees.py tests/test_taskgen_check.py tests/test_taskgen_cli.py 2>&1 | tail -1
```
Expected: 第一条在收集阶段报 `ImportError: cannot import name 'db_profile' from 'taskgen_v2'`；第二条 `45 passed`（夹具挪走后老测试照常通过）。

- [ ] **Step 3: 实现 `taskgen/v2/taskgen_v2/db_profile.py`**

```python
# taskgen/v2/taskgen_v2/db_profile.py
"""Per-database profiles (design §4.1). A profile says which tables are the roots (the people tasks are about), which
tables hold people at all, which records are a root's events and which parent rows hang under them, which tables are
1:1 attributes of a person, public reference data, excluded, or closed to INSERT. The generation model drafts a
profile and a person confirms it; trees, the generation prompt and the execution check use confirmed profiles only.
Edges are foreign keys written 'child.col -> parent.col', or 'child.(a, b) -> parent.(x, y)' when composite."""
import hashlib, json, os, re
from collections import namedtuple
from taskgen_common.db_select import _q
from taskgen_v2 import io

PROFILES_JSON = os.path.join(io.DATA, "db_profiles.json")
FIELDS = ("roots", "persons", "events", "attributes", "public", "exclude", "no_insert", "quirks", "description", "confirmed")
MIN_EDGE_HIT = 0.3   # an edge that no recorded foreign key backs must match like a validated FK (db_select.all_fks)
EDGE_SAMPLE = 2000   # child rows sampled for that match rate

Edge = namedtuple("Edge", "child cols parent ref_cols")


def _side(text):
    m = re.match(r"^\s*(.+?)\.\(([^()]*)\)\s*$", text)
    if m:
        table, cols = m.group(1).strip(), tuple(c.strip() for c in m.group(2).split(","))
    else:
        table, dot, col = text.strip().rpartition(".")
        cols = (col.strip(),) if dot else ()
    if not table or not cols or not all(cols):
        raise ValueError(f"not 'table.column' or 'table.(a, b)': {text.strip()!r}")
    return table, cols


def parse_edge(text):
    if not isinstance(text, str) or text.count("->") != 1:
        raise ValueError(f"an edge is 'child.col -> parent.col': {text!r}")
    left, right = text.split("->")
    (child, cols), (parent, ref_cols) = _side(left), _side(right)
    if len(cols) != len(ref_cols):
        raise ValueError(f"{len(cols)} column(s) point to {len(ref_cols)}: {text!r}")
    return Edge(child, cols, parent, ref_cols)


def edge_text(e):
    def side(t, cs):
        return f"{t}.{cs[0]}" if len(cs) == 1 else f"{t}.({', '.join(cs)})"
    return f"{side(e.child, e.cols)} -> {side(e.parent, e.ref_cols)}"


def load(path=PROFILES_JSON):
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save(profiles, path=PROFILES_JSON):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(dict(sorted(profiles.items())), f, ensure_ascii=False, indent=1)
        f.write("\n")


def get(db_key, path=PROFILES_JSON):
    """The confirmed profile of db_key; ValueError when there is none or it is not confirmed yet (design D1)."""
    p = load(path).get(db_key)
    if p is None:
        raise ValueError(f"no profile for {db_key} in {path}: run `taskgen.py profile draft --db {db_key}`")
    if p.get("confirmed") is not True:
        raise ValueError(f"the profile of {db_key} is not confirmed: review it, then `taskgen.py profile confirm --db {db_key}`")
    return p


def version(profile):
    """Short hash of what the profile says (the review fields left out), recorded in every tree."""
    body = {k: profile.get(k) for k in FIELDS if k != "confirmed"}
    return hashlib.sha1(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:10]


def root_anchor(profile, table):
    """A root in the anchor shape the prompt, generate and check use: {table, key, names}."""
    if table not in {r["table"] for r in profile["roots"]}:
        raise ValueError(f"{table} is not a root of this profile")
    p = profile["persons"][table]
    return {"table": table, "key": p["key"], "names": list(p["name_cols"])}


def parent_nodes(profile):
    """(table the parent hangs under, parent spec, location) for every parent: under roots, under events, nested."""
    out = []

    def walk(container, nodes, where):
        for i, p in enumerate(nodes or []):
            loc = f"{where}.parents[{i}]"
            out.append((container, p, loc))
            walk(p.get("table"), p.get("parents"), loc)
    for i, r in enumerate(profile.get("roots") or []):
        walk(r.get("table"), r.get("parents"), f"roots[{i}]")
    for i, e in enumerate(profile.get("events") or []):
        walk(e.get("table"), e.get("parents"), f"events[{i}]")
    return out


def _parsed(texts):
    for x in texts:
        try:
            yield parse_edge(x)
        except ValueError:
            continue


def edges(profile):
    """Every edge the profile states: event paths, parent links, attribute links, and same_as identity columns."""
    out = [parse_edge(x) for e in profile["events"] for x in e["path"]]
    out += [parse_edge(p["via"]) for _, p, _ in parent_nodes(profile)]
    out += [parse_edge(a["via"]) for a in profile["attributes"]]
    for t, p in profile["persons"].items():
        for s in p.get("same_as") or []:
            st, _, sc = s.rpartition(".")
            out.append(Edge(st, (sc,), t, (p["key"],)))
    return out


def used_tables(profile):
    """Every table the profile gives a role (exclude not counted)."""
    used = {r.get("table") for r in profile.get("roots") or []} | set(profile.get("persons") or {})
    used |= set(profile.get("public") or []) | {a.get("table") for a in profile.get("attributes") or []}
    for e in profile.get("events") or []:
        used.add(e.get("table"))
        for x in _parsed(e.get("path") or []):
            used |= {x.child, x.parent}
    used |= {p.get("table") for _, p, _ in parent_nodes(profile)}
    return used - {None}


def scope_tables(profile):
    """The tables a task may write (design §4.5): every table with a role, minus exclude."""
    return used_tables(profile) - set(profile["exclude"])


def _tables(conn):
    return {n: [r[1] for r in conn.execute(f"PRAGMA table_info({_q(n)})")]
            for (n,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")}


def edge_hit(conn, e):
    """Share of sampled child rows (edge columns filled) whose values exist in the parent; None when there are none."""
    cols = ", ".join(_q(c) for c in e.cols)
    filled = " AND ".join(f"{_q(c)} IS NOT NULL AND {_q(c)} != ''" for c in e.cols)
    ref = ", ".join(_q(c) for c in e.ref_cols)
    n, hit = conn.execute(f"SELECT COUNT(*), COALESCE(SUM(({cols}) IN (SELECT {ref} FROM {_q(e.parent)})), 0) "
                          f"FROM (SELECT {cols} FROM {_q(e.child)} WHERE {filled} LIMIT {EDGE_SAMPLE})").fetchone()
    return hit / n if n else None


def validate(profile, conn, fks=(), composite=()):
    """What makes a profile unusable, as readable lines; [] when it is fine. Checks names against the database, the
    shape of paths and parent links, that edges are foreign keys, and that every table has a role."""
    try:
        return _validate(profile, conn, fks, composite)
    except (AttributeError, KeyError, TypeError) as e:   # wrong JSON shapes in a draft or a hand edit
        return [f"malformed profile: {type(e).__name__}: {e}"]


def _validate(profile, conn, fks, composite):
    miss = [k for k in FIELDS if k not in profile]
    if miss:
        return [f"missing fields: {', '.join(miss)}"]
    shapes = [k for k in ("roots", "events", "attributes", "public", "exclude", "no_insert") if not isinstance(profile[k], list)]
    shapes += ["persons"] if not isinstance(profile["persons"], dict) else []
    shapes += [f"events[{i}].path" for i, e in enumerate(profile["events"] or []) if not isinstance(e.get("path"), list)]
    if shapes:
        return [f"{k}: wrong JSON type (see the field list)" for k in shapes]
    errs, tables = [], _tables(conn)
    known = {(f["table"].lower(), (f["col"].lower(),), f["ref_table"].lower(), (f["ref_col"].lower(),)) for f in fks}
    known |= {(f["table"].lower(), tuple(c.lower() for c in f["cols"]), f["ref_table"].lower(),
               tuple(c.lower() for c in f["ref_cols"])) for f in composite}

    def has(table, where, cols=()):
        if table not in tables:
            errs.append(f"{where}: no table {table!r}")
            return False
        bad = [c for c in cols if c not in tables[table]]
        if bad:
            errs.append(f"{where}: no column {', '.join(f'{table}.{c}' for c in bad)}")
            return False
        return True

    def edge(text, where, child=None, parent=None):
        try:
            e = parse_edge(text)
        except ValueError as x:
            errs.append(f"{where}: {x}")
            return None
        if child is not None and e.child != child:
            errs.append(f"{where}: starts at {e.child}, expected {child}")
        if parent is not None and e.parent != parent:
            errs.append(f"{where}: ends at {e.parent}, expected {parent}")
        if not (has(e.child, where, e.cols) and has(e.parent, where, e.ref_cols)):
            return None
        k = (e.child.lower(), tuple(c.lower() for c in e.cols), e.parent.lower(), tuple(c.lower() for c in e.ref_cols))
        if k not in known:
            h = edge_hit(conn, e)
            if h is not None and h < MIN_EDGE_HIT:
                errs.append(f"{where}: only {h:.0%} of {e.child} rows find a {e.parent} row; not a foreign key")
        return e

    persons = profile["persons"]
    for t, p in persons.items():
        if has(t, f"persons.{t}", [p.get("key")] + list(p.get("name_cols") or [])):
            n, d = conn.execute(f"SELECT COUNT(*), COUNT(DISTINCT {_q(p['key'])}) FROM {_q(t)}").fetchone()
            if n != d:
                errs.append(f"persons.{t}: key {p['key']} has empty or repeated values ({d} distinct in {n} rows)")
        if not p.get("name_cols"):
            errs.append(f"persons.{t}: name_cols is empty")
        for s in p.get("same_as") or []:
            st, dot, sc = s.rpartition(".")
            if not dot:
                errs.append(f"persons.{t}.same_as: {s!r} is not table.column")
            else:
                has(st, f"persons.{t}.same_as", [sc])
    roots = profile["roots"]
    if not roots:
        errs.append("roots: needs at least one root")
    for i, r in enumerate(roots):
        if r.get("table") not in persons:
            errs.append(f"roots[{i}]: {r.get('table')!r} must also be listed in persons")
        if not r.get("label"):
            errs.append(f"roots[{i}]: label is empty")
    root_tables = {r.get("table") for r in roots}
    event_tables = set()
    for i, ev in enumerate(profile["events"]):
        where, t = f"events[{i}]", ev.get("table")
        if not ev.get("label"):
            errs.append(f"{where}: label is empty")
        if not has(t, where):
            continue
        event_tables.add(t)
        path, prev = ev.get("path") or [], None
        if not path:
            errs.append(f"{where}: empty path")
            continue
        for j, text in enumerate(path):
            e = edge(text, f"{where}.path[{j}]", parent=prev)
            if e is None:
                break
            if j == 0 and e.parent not in root_tables:
                errs.append(f"{where}.path[0]: {e.parent} is not a root")
            prev = e.child
        else:
            if prev != t:
                errs.append(f"{where}: path ends at {prev}, not at {t}")
    public = set(profile["public"])
    for container, p, where in parent_nodes(profile):
        t = p.get("table")
        if has(t, where):
            edge(p.get("via"), f"{where}.via", child=container, parent=t)
            if t not in persons and t not in event_tables and t not in public:
                errs.append(f"{where}: {t} hangs under {container} but is not public, a person or an event table")
    for i, a in enumerate(profile["attributes"]):
        where = f"attributes[{i}]"
        if a.get("of") not in persons:
            errs.append(f"{where}: of={a.get('of')!r} is not in persons")
        if has(a.get("table"), where):
            edge(a.get("via"), f"{where}.via", child=a.get("table"), parent=a.get("of"))
    for k in ("public", "exclude", "no_insert"):
        for t in profile[k]:
            has(t, k)
    if public & set(persons):
        errs.append(f"public: {', '.join(sorted(public & set(persons)))} hold people, not public data")
    used, excl = used_tables(profile), set(profile["exclude"])
    if used & excl:
        errs.append(f"exclude: {', '.join(sorted(used & excl))} also have a role")
    loose = set(tables) - used - excl
    if loose:
        errs.append(f"tables without a role (list them in public or exclude): {', '.join(sorted(loose))}")
    if set(profile["no_insert"]) - (used - excl):
        errs.append(f"no_insert: {', '.join(sorted(set(profile['no_insert']) - (used - excl)))} are not in scope")
    if not isinstance(profile["confirmed"], bool):
        errs.append("confirmed: must be true or false")
    if not isinstance(profile["quirks"], list) or not all(isinstance(q, str) for q in profile["quirks"]):
        errs.append("quirks: must be a list of sentences")
    if not isinstance(profile["description"], str) or not profile["description"].strip():
        errs.append("description: is empty")
    return errs


def pk_classes(pk):
    """design §4.3 key classes from schema.pk_info, for the review page."""
    out = {"可省 ID": [], "ID 须用户给出": [], "非整数或复合主键": [], "无主键": []}
    for t, v in sorted(pk.items()):
        if v["omittable"]:
            out["可省 ID"].append(t)
        elif v["rowid_alias"]:
            out["ID 须用户给出"].append(t)
        elif v["cols"]:
            out["非整数或复合主键"].append(f"{t}({', '.join(v['cols'])})")
        else:
            out["无主键"].append(t)
    return out


def _parent_lines(nodes, depth):
    out = []
    for p in nodes or []:
        via = p.get("via") or ""
        out.append(f"{'  ' * depth}- {p.get('table')} ← {via.split('->')[0].strip()}")
        out += _parent_lines(p.get("parents"), depth + 1)
    return out


def render_md(entries):
    """Review page (Chinese headings, profile content as is). entries: [{key, profile, errors, pk}]."""
    lines = []
    for x in entries:
        p, errs = x["profile"], x["errors"]
        state = "已确认" if p.get("confirmed") is True else "未确认"
        lines += [f"## {x['key']}　{state}　" + ("校验通过" if not errs else f"{len(errs)} 个问题"), ""]
        if p.get("description"):
            lines += [f"> {p['description']}", ""]
        persons = p.get("persons") or {}
        rows = [("根", "；".join(f"{r.get('table')}（{r.get('label')}）" for r in p.get("roots") or [])),
                ("人物表", "；".join(f"{t}（{v.get('key')}；{', '.join(v.get('name_cols') or [])}"
                                    + (f"；same_as {', '.join(v['same_as'])}" if v.get("same_as") else "") + "）"
                                    for t, v in persons.items())),
                ("事件", "；".join(f"{e.get('table')}（{e.get('label')}）：{' / '.join(e.get('path') or [])}"
                                  for e in p.get("events") or [])),
                ("属性表", "；".join(f"{a.get('table')} → {a.get('of')}" for a in p.get("attributes") or [])),
                ("公共表", ", ".join(p.get("public") or [])), ("排除", ", ".join(p.get("exclude") or [])),
                ("不出 INSERT", ", ".join(p.get("no_insert") or [])), ("数据怪异点", "；".join(p.get("quirks") or []))]
        lines += ["| 项 | 内容 |", "|---|---|"] + [f"| {k} | {v or '—'} |" for k, v in rows] + [""]
        nested = []
        for r in p.get("roots") or []:
            if r.get("parents"):
                nested += [f"- 根 {r.get('table')}"] + _parent_lines(r["parents"], 1)
        for e in p.get("events") or []:
            if e.get("parents"):
                nested += [f"- {e.get('table')}（{e.get('label')}）"] + _parent_lines(e["parents"], 1)
        if nested:
            lines += ["挂在根和事件下面的父行（← 后面是外键列）：", ""] + nested + [""]
        if x.get("pk"):
            lines += ["主键：" + "；".join(f"{k}：{', '.join(v)}" for k, v in pk_classes(x["pk"]).items() if v), ""]
        if p.get("notes"):
            lines += ["Claude 的改动："] + [f"- {n}" for n in p["notes"]] + [""]
        d = p.get("draft") or {}
        if d:
            lines += [f"起草：{d.get('model')}，{d.get('rounds')} 轮" + (f"，没改掉的问题 {len(d['errors'])} 条" if d.get("errors") else ""), ""]
        if errs:
            lines += ["**校验问题：**"] + [f"- {e}" for e in errs] + [""]
    return "\n".join(lines)
```

- [ ] **Step 4: 跑测试，确认通过**

```bash
cd $REPO/taskgen/v2
$P -m pytest -q tests/test_taskgen_db_profile.py 2>&1 | tail -1
$P -m pytest -q 2>&1 | tail -1
```
Expected: `6 passed`；全套 `104 passed`。

- [ ] **Step 5: README，提交**

在 `taskgen/v2/README.md` 的"实施计划 1"那一行下面加一行：

```markdown
- **实施计划 2（库档案、嵌套建树、检查读档案）：** [docs/2026-10-01-taskgen-v2-plan-2.md](docs/2026-10-01-taskgen-v2-plan-2.md)
```

改动记录表末尾加一行（README 以这张表结尾，可以直接追加）：

```bash
cd $REPO
printf '%s\n' '| 库档案：`taskgen_v2/db_profile.py`（格式、校验、写入范围、审阅页）；测试夹具 `tests/v2_fixtures.py` | §4.1 |' >> taskgen/v2/README.md
git add taskgen/v2/taskgen_v2/db_profile.py taskgen/v2/tests/v2_fixtures.py taskgen/v2/tests/test_taskgen_db_profile.py \
        taskgen/v2/tests/test_taskgen_trees.py taskgen/v2/README.md
git diff --cached --name-only
git commit -m "feat(taskgen v2): database profiles: format, validation, write scope, review page

A profile names a database's roots, people, events with nested parent rows, 1:1 attributes,
public, excluded and no-insert tables. validate() checks names against the database, the shape
of paths and parent links, that edges are foreign keys (or match >= 30% of rows), and that every
table has a role. Shop and school fixtures move to tests/v2_fixtures.py.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
Expected: `git diff --cached --name-only` 列出上面 5 个文件，没有 `results/`、`output/`。

---

### Task 2: 归属追溯独立成 `owners.py`，检查改用它（行为不变）

**Files:**
- Create: `taskgen/v2/taskgen_v2/owners.py`
- Modify: `taskgen/v2/taskgen_v2/check.py`：删掉 `class Tracer`，改用 `owners.Tracer.from_rec`；`run_check` 里的局部变量 `owners` 改名为 `holders`，免得遮住模块名。
- Test: `taskgen/v2/tests/test_taskgen_owners.py`

**Interfaces:**
- Consumes: `db_profile.Edge`、`db_profile.edges(profile)`（Task 1）。
- Produces:
  - `owners.MAX_HOPS = 3`
  - 构造：`owners.Tracer(conn, edges, persons, names=None, tables=())`
    - `Tracer.from_rec(db_rec, conn)`：不带档案，和 v1 一样，人物表来自锚点，边来自已记录的单列外键。
    - `Tracer.from_profile(profile, db_rec, conn)`：档案里的人物表、边和 `same_as`，加上全部已记录的外键（含复合外键）。
  - 方法：
    - `canon(table)`
    - `trace(table, row) -> {(person_table, key_as_str)}`
    - `name(table, key) -> str`
    - `label(table, row, speaker) -> "own" | "public" | "other:<name>"`
  - 属性：`persons {table: key}`、`up {child: [(cols, parent, ref_cols)]}`。cols 是 tuple；自引用的边（如 manager_id）不进 `up`。

- [ ] **Step 1: 写会失败的测试 `taskgen/v2/tests/test_taskgen_owners.py`**

```python
# tests/test_taskgen_owners.py
import sqlite3
import pytest
from taskgen_common.testing import make_db
from v2_fixtures import SHOP2, FKS, CUSTOMER, STAFF, SHOP_PROFILE, SCHOOL, SCHOOL_FKS, SCHOOL_COMPOSITE, SCHOOL_PROFILE
from taskgen_v2 import owners

SHOP_REC = {"source": "test", "db": "shop2", "anchors": [CUSTOMER, STAFF], "fks": FKS}
SCHOOL_REC = {"source": "test", "db": "school", "anchors": [], "fks": SCHOOL_FKS, "fks_composite": SCHOOL_COMPOSITE}


@pytest.fixture
def shop(tmp_path):
    return sqlite3.connect(make_db(tmp_path, "shop2", SHOP2))


@pytest.fixture
def school(tmp_path):
    return sqlite3.connect(make_db(tmp_path, "school", SCHOOL))


def test_from_rec_traces_like_v1(shop):
    t = owners.Tracer.from_rec(SHOP_REC, shop)
    assert t.persons == {"customers": "customer_id", "staff": "staff_id"}
    item = {"item_id": 5, "order_id": 65, "note": "n5"}                     # order 65 belongs to customer 5
    assert t.trace("order_items", item) == {("customers", "5")}
    assert t.trace("products", {"product_id": 5}) == set()
    assert t.canon("ORDERS") == "orders" and t.canon("nope") == "nope"


def test_from_profile_follows_profile_edges_composite_keys_and_text_ids(school):
    t = owners.Tracer.from_profile(SCHOOL_PROFILE, SCHOOL_REC, school)
    # advisor.s_id -> "Student List".sid is only in the profile, and its TEXT '3' finds the INTEGER 3
    assert t.trace("advisor", {"s_id": "3", "t_id": 0}) == {("Student List", "3"), ("teacher", "0")}
    assert t.trace("takes", {"sid": 2, "course": "c1", "sec": 1, "grade": "A"}) == {("Student List", "2")}
    assert t.trace("section", {"course": "c1", "sec": 1, "title": "Algebra"}) == set()
    assert t.canon("student list") == "Student List"


def test_labels_name_the_other_person(school):
    t = owners.Tracer.from_profile(SCHOOL_PROFILE, SCHOOL_REC, school)
    me = {("Student List", "3")}
    assert t.label("advisor", {"s_id": "3", "t_id": 0}, me) == "own"
    assert t.label("advisor", {"s_id": "4", "t_id": 1}, me) == "other:s4"
    assert t.label("teacher", {"tid": 0, "name": "t0"}, me) == "other:t0"
    assert t.label("dept", {"dept_name": "d0", "building": "B0"}, me) == "public"


def test_self_references_say_nothing_about_ownership(tmp_path):
    c = sqlite3.connect(make_db(tmp_path, "e", "CREATE TABLE emp (id INTEGER PRIMARY KEY, name TEXT, boss INTEGER REFERENCES emp(id));"
                                               "INSERT INTO emp VALUES (1, 'a', NULL), (2, 'b', 1);"))
    rec = {"anchors": [{"table": "emp", "key": "id", "kind": "person_named", "names": ["name"]}],
           "fks": [{"table": "emp", "col": "boss", "ref_table": "emp", "ref_col": "id"}]}
    t = owners.Tracer.from_rec(rec, c)
    assert t.up == {} and t.trace("emp", {"id": 2, "name": "b", "boss": 1}) == {("emp", "2")}
```

- [ ] **Step 2: 跑测试，确认失败**

Run: `cd $REPO/taskgen/v2 && $P -m pytest -q tests/test_taskgen_owners.py 2>&1 | tail -3`
Expected: 收集阶段报 `ImportError: cannot import name 'owners' from 'taskgen_v2'`。

- [ ] **Step 3: 实现 `taskgen/v2/taskgen_v2/owners.py`**

```python
# taskgen/v2/taskgen_v2/owners.py
"""Whose data a row is: follow foreign keys from the row up to person tables (at most 3 hops) and collect the people
reached. The execution check labels every written row with it and the tree builder labels every row it shows with
it, so 'own', 'public' and 'another person's' mean the same thing in the prompt and in the check."""
import sqlite3
from taskgen_common.db_select import _q
from taskgen_v2 import db_profile

MAX_HOPS = 3


def _key(e):
    return e.child.lower(), tuple(c.lower() for c in e.cols), e.parent.lower(), tuple(c.lower() for c in e.ref_cols)


class Tracer:
    def __init__(self, conn, edges, persons, names=None, tables=()):
        """edges: db_profile.Edge list, child -> parent; persons: {table: key column}; names: {table: [name columns]};
        tables: the names write targets are canonicalized to."""
        self.conn, self.persons, self.names = conn, persons, names or {}
        self.up, seen = {}, set()
        for e in edges:
            if e.child.lower() == e.parent.lower() or _key(e) in seen:   # a manager_id says nothing about whose row it is
                continue
            seen.add(_key(e))
            self.up.setdefault(e.child, []).append((tuple(e.cols), e.parent, tuple(e.ref_cols)))
        self.tables = {t.lower(): t for t in tables}

    @classmethod
    def from_rec(cls, db_rec, conn):
        """Without a profile (DySQL gold, v1 candidates), as in v1: the anchors' person tables, the recorded
        single-column foreign keys."""
        edges = [db_profile.Edge(f["table"], (f["col"],), f["ref_table"], (f["ref_col"],)) for f in db_rec["fks"]]
        persons = {a["table"]: a["key"] for a in db_rec["anchors"] if a["kind"].startswith("person")}
        names = {a["table"]: a["names"] for a in db_rec["anchors"]}
        tables = [a["table"] for a in db_rec["anchors"]] + [f[k] for f in db_rec["fks"] for k in ("table", "ref_table")]
        return cls(conn, edges, persons, names, tables)

    @classmethod
    def from_profile(cls, profile, db_rec, conn):
        """The profile's people and edges (same_as included) plus every recorded foreign key, composite ones too."""
        edges = db_profile.edges(profile)
        edges += [db_profile.Edge(f["table"], (f["col"],), f["ref_table"], (f["ref_col"],)) for f in db_rec["fks"]]
        edges += [db_profile.Edge(f["table"], tuple(f["cols"]), f["ref_table"], tuple(f["ref_cols"]))
                  for f in db_rec.get("fks_composite", ())]
        persons = {t: p["key"] for t, p in profile["persons"].items()}
        names = {t: p["name_cols"] for t, p in profile["persons"].items()}
        tables = [n for (n,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
        return cls(conn, edges, persons, names, tables)

    def canon(self, table):
        return self.tables.get(table.lower(), table)

    def trace(self, table, row, depth=0, acc=None):
        """{(person table, key as str)} the row belongs to: itself when it is a person row, plus the people its
        parents (up to MAX_HOPS) belong to."""
        acc = set() if acc is None else acc
        if table in self.persons:
            v = row.get(self.persons[table])
            if v is not None:
                acc.add((table, str(v)))
        if depth >= MAX_HOPS:
            return acc
        for cols, parent, ref_cols in self.up.get(table, []):
            vals = [row.get(c) for c in cols]
            if any(v in (None, "") for v in vals):
                continue
            where = " AND ".join(f"{_q(r)} = ?" for r in ref_cols)
            try:
                cur = self.conn.execute(f"SELECT * FROM {_q(parent)} WHERE {where} LIMIT 3", vals)
            except sqlite3.Error:
                continue
            names = [d[0] for d in cur.description]
            for r in cur.fetchall():
                self.trace(parent, dict(zip(names, r)), depth + 1, acc)
        return acc

    def name(self, table, key):
        cols = self.names.get(table) or []
        if cols and table in self.persons:
            try:
                r = self.conn.execute(f"SELECT {', '.join(_q(c) for c in cols)} FROM {_q(table)} "
                                      f"WHERE {_q(self.persons[table])} = ?", (key,)).fetchone()
            except sqlite3.Error:
                r = None
            if r and any(v not in (None, "") for v in r):
                return " ".join(str(v) for v in r if v not in (None, ""))
        return f"{table} {key}"

    def label(self, table, row, speaker):
        """'own' when the row reaches the speaker, 'other:<name>' when it reaches only other people, else 'public'."""
        owners = self.trace(table, row)
        if owners & speaker:
            return "own"
        if owners:
            t, k = sorted(owners)[0]
            return "other:" + self.name(t, k)
        return "public"
```

- [ ] **Step 4: `check.py` 改用它（五处改动，逻辑不变）**

1. 导入：
   ```python
   from taskgen_v2 import prompt, schema, trees
   ```
   改成
   ```python
   from taskgen_v2 import owners, prompt, schema
   ```
2. 删掉整个 `class Tracer:`，从 `class Tracer:` 那一行删到 `def task_group(` 前面的空行。
3. `tracer = Tracer(db_rec, db)` 改成 `tracer = owners.Tracer.from_rec(db_rec, db)`。
4. 建触发器的那行，因为 `up` 里的列现在是 tuple：
   ```python
           need = {c for c, _, _ in tracer.up.get(t, [])} | ({tracer.persons[t]} if t in tracer.persons else set())
   ```
   改成
   ```python
           need = {c for cols, _, _ in tracer.up.get(t, []) for c in cols} | ({tracer.persons[t]} if t in tracer.persons else set())
   ```
5. 写语句循环里，局部变量 `owners` 共 6 处（`owners = set()`、两处 `owners |= ...`、`if owners & speaker_ids:`、`"other" if owners`、`"person_obj" if owners`）全部改名为 `holders`。改完 `grep -n "owners" taskgen_v2/check.py`，应该只剩 import 一处和 `owners.Tracer.from_rec` 一处。

- [ ] **Step 5: 跑测试**

```bash
cd $REPO/taskgen/v2
$P -m pytest -q tests/test_taskgen_owners.py 2>&1 | tail -1
$P -m pytest -q 2>&1 | tail -1
```
Expected: `4 passed`；全套 `108 passed`。

- [ ] **Step 6: 在真实数据上证明行为没变**

用计划 1 的校准脚本重跑 DySQL 金标准和 v1 全部 4159 条候选。生成的部分应和已提交的报告逐字相同，手写的"结论"段除外。大约 4 分钟。

```bash
cd $REPO/taskgen/v2
$P scripts/check_diff.py --out $S/recal_task2.md > /dev/null
diff <(sed -n '/^## DySQL 金标准/,$p' docs/2026-10-01-check-recalibration.md) <(sed -n '/^## DySQL 金标准/,$p' $S/recal_task2.md) && echo SAME
```
Expected: `SAME`。

- [ ] **Step 7: 提交**

```bash
cd $REPO
printf '%s\n' '| 归属追溯挪到 `taskgen_v2/owners.py`（支持复合外键和档案里的边），执行检查改用它，行为不变（校准报告逐字不变） | §4.5 |' >> taskgen/v2/README.md
git add taskgen/v2/taskgen_v2/owners.py taskgen/v2/taskgen_v2/check.py taskgen/v2/tests/test_taskgen_owners.py taskgen/v2/README.md
git diff --cached --name-only
git commit -m "refactor(taskgen v2): ownership tracing moves to owners.py

The tracer the check used becomes owners.Tracer: from_rec keeps v1's behaviour (anchors and
single-column foreign keys), from_profile adds the profile's edges, same_as columns and composite
keys, and label() names the other person. The tree builder will label rows with the same code.
check_diff reproduces the recalibration report unchanged.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: 检查读档案（范围、`no_insert`、`other_person`），顺带修计划 1 留下的三处

**Files:**
- Modify: `taskgen/v2/taskgen_v2/check.py`：`run_check` 加 `profile` 参数，加 `_keys`，`_MDY` 空白。
- Modify: `taskgen/v2/taskgen_v2/schema.py`：加 `next_rowid`。
- Modify: `taskgen/v2/scripts/check_diff.py`：加 `--profiles` 模式：同一批候选，比不带档案和带档案的检查。
- Test: `taskgen/v2/tests/test_taskgen_check.py`、`taskgen/v2/tests/test_taskgen_check_diff.py`（都是在末尾追加）。

**Interfaces:**
- Consumes: `db_profile.root_anchor`、`db_profile.scope_tables`（Task 1）；`owners.Tracer.from_profile`（Task 2）。
- Produces:
  - `check.run_check(db_rec, cand, anchor=None, cfg=prompt.CFG, profile=None)`；`run_check_safe(db_rec, cand, **kw)` 照样把 `profile` 传下去。
  - 新的拒绝原因：`no_insert: <table>`、`other_person`。
  - 说话人不是根时，`run_check` 抛 ValueError，`run_check_safe` 记成 `crash: ValueError: <table> is not a root ...`。
  - `schema.next_rowid(conn, table, col) -> int`
  - `check_diff.section(title, pairs, old="v1", new="v2")`、`check_diff.profile_pairs(results, recs, profiles) -> [(id, verdict_without, verdict_with)]`；命令行新增 `--profiles PATH`、`--anchors PATH`。

- [ ] **Step 1: 写会失败的测试**

`tests/test_taskgen_check.py` 的导入里，在 `from test_taskgen_trees import SHOP2, FKS, CUSTOMER` 下面加一行：

```python
from v2_fixtures import SHOP_PROFILE, SCHOOL, SCHOOL_FKS, SCHOOL_COMPOSITE, SCHOOL_PROFILE
```

然后在文件末尾追加：

```python
# --- plan 2: checks that read the database profile ---

@pytest.fixture
def school(tmp_path):
    return {"source": "test", "db": "school", "path": make_db(tmp_path, "school", SCHOOL), "anchors": [],
            "fks": SCHOOL_FKS, "fks_composite": SCHOOL_COMPOSITE}


def scand(instruction, sqls, task_type="1_self", key_value=3):
    return {"id": "s", "anchor_table": "Student List", "anchor_key": "sid", "key_value": key_value,
            "plan": {"task_type": task_type}, "instruction": instruction, "actions": [{"sql": s} for s in sqls]}


def test_profile_edges_decide_ownership(school):
    r = check.run_check(school, scand("I am s3. Drop my advisor t0.", ["DELETE FROM advisor WHERE s_id = '3'"]), profile=SCHOOL_PROFILE)
    assert r["ok"], r["reasons"]
    assert r["writes"] == [{"op": "DELETE", "table": "advisor", "rows": 1, "label": "own"}] and r["task_type"] == "1_self"


def test_profile_rejects_another_persons_data(school, db):
    r = check.run_check(school, scand("I am s3. Rename teacher 1 to Tao.", ["UPDATE teacher SET name = 'Tao' WHERE tid = 1"]),
                        profile=SCHOOL_PROFILE)
    assert r["reasons"] == ["other_person"] and r["task_type"] == "4_other_person"
    c = cand("I am a5 b5. Set qty of order 9 to 3.", ["UPDATE orders SET qty = 3 WHERE order_id = 9"])
    assert check.run_check(db, c)["ok"]                                       # without a profile, as in v1
    assert check.run_check(db, c, profile=SHOP_PROFILE)["reasons"] == ["other_person"]


def test_profile_scope_and_no_insert(school):
    r = check.run_check(school, scand("I am s3. Add the day 2024-01-03.", ["INSERT INTO calendar VALUES ('2024-01-03')"]),
                        profile=SCHOOL_PROFILE)
    assert r["reasons"] == ["out_of_scope: calendar"]
    r = check.run_check(school, scand("I am s3. Open section c2 2 called Biology.", ["INSERT INTO section VALUES ('c2', 2, 'Biology')"]),
                        profile=SCHOOL_PROFILE)
    assert r["reasons"] == ["no_insert: section"]


def test_profile_speaker_must_be_a_root(school):
    c = {**scand("I am t0.", ["UPDATE teacher SET name = 'Tao' WHERE tid = 0"]), "anchor_table": "teacher", "key_value": 0}
    assert check.run_check_safe(school, c, profile=SCHOOL_PROFILE)["reasons"][0].startswith("crash: ValueError: teacher is not a root")


def test_replacing_or_upserting_an_existing_person_is_not_a_new_person(db):
    r = check.run_check(db, cand("I am a5 b5. Customer 9 is now Zed Quinn.",
                                 ["INSERT OR REPLACE INTO customers (customer_id, first_name, last_name) VALUES (9, 'Zed', 'Quinn')"]))
    assert r["writes"][0]["label"] == "other" and r["task_type"] == "4_other_person"
    r = check.run_check(db, cand("I am a5 b5. Customer 9 is now Zed.",
                                 ["INSERT INTO customers (customer_id, first_name, last_name) VALUES (9, 'Zed', 'b9') "
                                  "ON CONFLICT(customer_id) DO UPDATE SET first_name = excluded.first_name"]))
    assert r["writes"][0]["label"] == "other"


def test_auto_key_is_what_sqlite_would_assign_at_that_point(db):
    # orders run 0..99 and order 99 is customer 39's: once it is deleted, SQLite gives a new order 99, not 100
    r = check.run_check(db, cand("I am a39 b39. Cancel my order 99 and place a new order of product 7, qty 2.",
                                 ["DELETE FROM orders WHERE order_id = 99",
                                  "INSERT INTO orders (order_id, customer_id, product_id, qty) VALUES (100, 39, 7, 2)"], key_value=39))
    assert r["reasons"] == ["literal_missing: '100' in INSERT orders"]


def test_auto_key_for_a_table_written_in_another_case(tmp_path):
    path = make_db(tmp_path, "shop3", SHOP2 + "CREATE TABLE Logs (log_id INTEGER PRIMARY KEY, note TEXT);" + rows("Logs", 3, lambda i: f"{i},'x'"))
    rec = {"source": "test", "db": "shop3", "path": path, "anchors": [CUSTOMER, STAFF_ANCHOR], "fks": FKS}
    r = check.run_check(rec, cand("I am a5 b5. Log the note hello.", ["INSERT INTO logs (log_id, note) VALUES (3, 'hello')"]))
    assert r["reasons"] == ["out_of_scope: logs"]                  # 3 is what SQLite would give: no literal is missing


def test_ctrl_c_in_the_rerun_pause_is_not_swallowed(rental, monkeypatch):
    def interrupted(seconds):
        raise KeyboardInterrupt
    monkeypatch.setattr(check.time, "sleep", interrupted)
    with pytest.raises(KeyboardInterrupt):
        check.run_check_safe(rental, cand("I am a5 b5. Mark my rental 5 as returned right now.",
                                          ["UPDATE rental SET return_date = CURRENT_TIMESTAMP WHERE rental_id = 5"]))
```

`tests/test_taskgen_check_diff.py` 的导入换成：

```python
# tests/test_taskgen_check_diff.py
import importlib.util, os
from taskgen_common.testing import make_db
from v2_fixtures import SHOP2, FKS, CUSTOMER, STAFF, SHOP_PROFILE
from taskgen_v2 import io
```

然后在文件末尾追加：

```python
def test_profile_pairs_compare_root_speakers_only(tmp_path):
    rec = {"source": "test", "db": "shop2", "path": make_db(tmp_path, "shop2", SHOP2), "anchors": [CUSTOMER, STAFF], "fks": FKS}
    def c(cid, table, kv, ins, sql):
        return {"id": cid, "anchor_table": table, "key_value": kv, "plan": {"task_type": "1_self"}, "instruction": ins, "actions": [{"sql": sql}]}
    io.append_jsonl(tmp_path / "res" / "shop2" / "candidates.jsonl",
                    [c("own", "customers", 5, "I am a5 b5. Set qty of my order 5 to 3.", "UPDATE orders SET qty = 3 WHERE order_id = 5"),
                     c("theirs", "customers", 5, "I am a5 b5. Set qty of order 9 to 3.", "UPDATE orders SET qty = 3 WHERE order_id = 9"),
                     c("staff", "staff", 2, "I am s2. Rename me to Zed.", "UPDATE staff SET name = 'Zed' WHERE staff_id = 2")])
    pairs = cd.profile_pairs(str(tmp_path / "res"), {"test:shop2": rec}, {"test:shop2": SHOP_PROFILE})
    assert [(cid, o["ok"], n["ok"]) for cid, o, n in pairs] == [("own", True, True), ("theirs", True, False)]
    assert pairs[1][2]["reasons"] == ["other_person"]
    assert cd.profile_pairs(str(tmp_path / "res"), {"test:shop2": rec}, {"test:shop2": {**SHOP_PROFILE, "confirmed": False}}) == []
    text = "\n".join(cd.section("demo", pairs, "不用档案", "用档案"))
    assert "| 不用档案 | 用档案 | 条数 |" in text and "- 通过 → 拒绝：other_person（1）：theirs" in text
```

- [ ] **Step 2: 跑测试，确认失败**

```bash
cd $REPO/taskgen/v2
$P -m pytest -q tests/test_taskgen_check.py 2>&1 | tail -9
$P -m pytest -q tests/test_taskgen_check_diff.py 2>&1 | tail -2
```
Expected:
- 第一条是 `7 failed, 37 passed`：
  - 4 个 profile 测试报 `TypeError: run_check() got an unexpected keyword argument 'profile'`，或断言失败；
  - REPLACE/UPSERT 测试失败，因为 label 是 `new_person`；
  - 自动主键测试失败，因为没有报出 literal_missing；
  - Ctrl-C 测试失败，因为中断被记成了 crash。
  - `test_auto_key_for_a_table_written_in_another_case` 通过：它钉住已有的大小写处理，改动前后都应通过。
- 第二条是 `1 failed, 1 passed`，失败原因是 `AttributeError: module 'check_diff' has no attribute 'profile_pairs'`。

- [ ] **Step 3: 实现**

`schema.py` 末尾追加：

```python
def next_rowid(conn, table, col):
    """The key SQLite gives the next row that leaves col (a rowid alias) out: one above the larger of MAX(col) and,
    with AUTOINCREMENT, the table's sqlite_sequence value."""
    (mx,) = conn.execute(f"SELECT MAX({_q(col)}) FROM {_q(table)}").fetchone()
    seq = None
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'sqlite_sequence'").fetchone():
        seq = conn.execute("SELECT seq FROM sqlite_sequence WHERE name = ?", (table,)).fetchone()
    return max(mx or 0, (seq or (0,))[0] or 0) + 1
```

`check.py`：
1. 导入改成 `from taskgen_v2 import db_profile, owners, prompt, schema`。
2. `_MDY =re.compile(` 改成 `_MDY = re.compile(`。
3. 在 `def _memory_copy(path):` 前面加：

```python
def _keys(db, table, col):
    return {str(k) for (k,) in db.execute(f"SELECT {_q(col)} FROM {_q(table)}")}
```

4. 整个 `run_check` 函数（从 `def run_check(` 到 `def run_check_safe(` 之前）换成：

```python
def run_check(db_rec, cand, anchor=None, cfg=prompt.CFG, profile=None):
    """With a profile (generated candidates), scope, people and ownership come from it, INSERT into no_insert tables
    and writes to another person's data are rejected; without one (DySQL gold, v1 candidates), as in v1."""
    out = {"id": cand.get("id"), "ok": False, "reasons": [], "writes": [], "task_type": None, "template": None, "difficulty": None}
    if not cand.get("instruction"):
        out["reasons"].append("no_instruction"); return out
    if not cand.get("actions"):
        out["reasons"].append("no_actions"); return out
    if profile:
        anchor = anchor or db_profile.root_anchor(profile, cand["anchor_table"])
        scope = db_profile.scope_tables(profile)
    else:
        anchor = anchor or next(a for a in db_rec["anchors"] if a["table"] == cand["anchor_table"])
        # DySQL's validated property (2432/2432 gold writes) is "in SOME anchor's scope", not the speaker's anchor:
        # customers also edit public tables only another anchor reaches (chinook playlist_track)
        scope = {t for a in db_rec["anchors"] for t in (a["table"], *a["down"], *a["up"])}
    speaker_in_db = (cand.get("plan") or {}).get("task_type", "1_self") != "5_proxy" if "plan" in cand else cand.get("speaker_in_db", True)
    db = _memory_copy(db_rec["path"])
    tracer = owners.Tracer.from_profile(profile, db_rec, db) if profile else owners.Tracer.from_rec(db_rec, db)
    auto = {t.lower(): (t, v["cols"][0]) for t, v in schema.pk_info(db).items() if v["omittable"]}   # D9 tables
    row = db.execute(f"SELECT * FROM {_q(anchor['table'])} WHERE {_q(anchor['key'])} = ?", (cand["key_value"],)).fetchone()
    # calibration candidates may name several speaker rows (DySQL's classifier matched same-name people)
    speaker_ids = {tuple(x) for x in cand.get("speaker_ids") or [(anchor["table"], str(cand["key_value"]))]}
    rows = [row] if row else []
    for t, k in speaker_ids:
        if (t, k) != (anchor["table"], str(cand["key_value"])):
            key = next((a["key"] for a in db_rec["anchors"] if a["table"] == t), None)
            if key:
                rows += db.execute(f"SELECT * FROM {_q(t)} WHERE {_q(key)} = ?", (k,)).fetchall()
    allowed = {norm_literal(v) for r in rows for v in r if v not in (None, "")}
    # capture pre-update FK/key values, like classify_dysql_tasks.py: 'move my order to product 9' is still 'own'
    db.execute("CREATE TEMP TABLE _old (tbl TEXT, j TEXT)")
    for t in scope:
        need = {c for cols, _, _ in tracer.up.get(t, []) for c in cols} | ({tracer.persons[t]} if t in tracer.persons else set())
        if need:
            obj = ", ".join(f"'{c}', OLD.{_q(c)}" for c in sorted(need))
            db.execute(f"CREATE TEMP TRIGGER {_q('_u_' + t)} BEFORE UPDATE ON main.{_q(t)} BEGIN "
                       f"INSERT INTO _old VALUES ('{t}', json_object({obj})); END")
    stmts, labels, executed = [], [], []   # executed: every statement that ran, in order (writes and DDL)
    db.execute("BEGIN")
    try:
        for a in cand["actions"]:
            for st in split_statements(a["sql"]):
                if TXN.match(st):   # would commit or end the check's own transaction
                    out["reasons"].append(f"txn_control: {st[:40]}"); continue
                wt = write_target(st)
                try:
                    if not wt:
                        db.execute(st).fetchall(); executed.append(st); continue
                    op, table = wt[0], tracer.canon(wt[1])
                    key = table.lower()
                    # what SQLite would give a row that leaves the key out, at this point of the task
                    nxt = schema.next_rowid(db, *auto[key]) if op == "INSERT" and key in auto else None
                    existing = (_keys(db, table, tracer.persons[table])
                                if op == "INSERT" and speaker_in_db and table in tracer.persons else set())
                    cur = db.execute(st + " RETURNING *")
                    rcols = [d[0] for d in cur.description]
                    rs = cur.fetchall()
                except sqlite3.Error as e:
                    out["reasons"].append(f"sql_error: {e} in {st[:80]}"); continue
                executed.append(st)
                stmts.append(st)
                if nxt is not None:
                    # keys SQLite would assign anyway: an agent may leave them out, so the user need not say them,
                    # here or in a later statement that refers to the new row
                    for r in rs:
                        v = dict(zip(rcols, r)).get(auto[key][1])
                        if v != nxt:
                            break
                        allowed.add(norm_literal(v)); nxt += 1
                if table not in scope:
                    out["reasons"].append(f"out_of_scope: {table}")
                if profile and op == "INSERT" and table in profile["no_insert"]:
                    out["reasons"].append(f"no_insert: {table}")
                for lit in literals(st):
                    if not literal_ok(lit, cand["instruction"], allowed):
                        out["reasons"].append(f"literal_missing: '{lit}' in {op} {table}"); break
                holders = set()
                for r in rs[:50]:
                    holders |= tracer.trace(table, dict(zip(rcols, r)))
                for (j,) in db.execute("SELECT j FROM _old WHERE tbl = ? LIMIT 50", (table,)).fetchall():
                    holders |= tracer.trace(table, json.loads(j))
                db.execute("DELETE FROM _old")
                if not rs:
                    lab = "noop"
                    if op != "INSERT":
                        out["reasons"].append(f"noop_write: {op} {table}")
                elif speaker_in_db:
                    if holders & speaker_ids:
                        lab = "own"
                    elif op == "INSERT" and table in tracer.persons and not any(
                            str(dict(zip(rcols, r)).get(tracer.persons[table])) in existing for r in rs):
                        lab = "new_person"   # a person row that did not exist before is nobody else's data yet
                    else:
                        lab = "other" if holders else "public"
                else:
                    lab = "person_obj" if holders else "public"
                if len(rs) > cfg["MAX_ROWS_PER_STMT"]:
                    out["reasons"].append(f"bulk: {len(rs)} rows in {op} {table}")
                labels.append(lab)
                out["writes"].append({"op": op, "table": table, "rows": len(rs), "label": lab})
        if any(NONDET.search(s) for s in executed) and not any(x.startswith("sql_error") for x in out["reasons"]):
            changed = rerun_changes(db, executed, {tracer.canon(write_target(s)[1]) for s in stmts})
            if changed:
                out["reasons"].append("nondeterministic: " + changed)
    finally:
        if db.in_transaction:   # a Ctrl-C in the rerun's pause leaves none open; ROLLBACK would hide the interrupt
            db.execute("ROLLBACK")
        db.close()
    if not out["writes"] or (all(w["rows"] == 0 for w in out["writes"])
                             and not any(r.startswith("noop_write") for r in out["reasons"])):
        out["reasons"].append("no_write")   # nothing written, or only zero-row INSERT ... SELECT
    out["task_type"] = task_group(speaker_in_db, labels) if out["writes"] else None
    if profile and out["task_type"] == "4_other_person":
        out["reasons"].append("other_person")   # design D6: the agent policy denies requests about another person
    if out["task_type"]:
        out["template"] = out["task_type"] + "|" + "+".join(sorted(f"{w['op']} {w['table']}" for w in out["writes"]))
        out["difficulty"] = difficulty(out["writes"], out["task_type"], stmts)
    out["ok"] = not out["reasons"]
    return out
```

`scripts/check_diff.py` 整个换成：

```python
#!/usr/bin/env python3
"""Run two checks on the same candidates and attribute every changed verdict. Only candidate ids and counts go into
the report, never task text.
Default: v1's frozen check vs this version's, on DySQL's 1062 gold tasks and every candidate under --results (default:
v1's full run, ../v1/results). With --profiles: this version's check without vs with the confirmed database profiles,
on the candidates under --results whose speaker table is a root of their database's profile.
Usage (from taskgen/v2/):
  ~/miniconda3/envs/dysql/bin/python scripts/check_diff.py --out docs/<date>-check-recalibration.md
  ~/miniconda3/envs/dysql/bin/python scripts/check_diff.py --profiles data/db_profiles.json --out docs/<date>-check-with-profiles.md"""
import argparse, glob, os, sys
from collections import Counter, defaultdict
V2 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TASKGEN = os.path.dirname(V2)
sys.path[:0] = [V2, os.path.join(TASKGEN, "v1"), os.path.join(TASKGEN, "common")]   # taskgen_v2, taskgen_v1, taskgen_common
from taskgen_v1 import check as old_check
from taskgen_v2 import check as new_check, db_profile, dysql, io

YES = {True: "通过", False: "拒绝"}


def kinds(result):
    return {x.split(":")[0] for x in result["reasons"]}


def section(title, pairs, old="v1", new="v2"):
    trans = Counter((o["ok"], n["ok"]) for _, o, n in pairs)
    groups, relabel = defaultdict(list), Counter()
    for cid, o, n in pairs:
        ko, kn = kinds(o), kinds(n)
        if o["ok"] and not n["ok"]:
            groups["通过 → 拒绝：" + "+".join(sorted(kn))].append(cid)
        elif n["ok"] and not o["ok"]:
            groups[f"拒绝 → 通过：{old} 的原因 " + "+".join(sorted(ko))].append(cid)
        elif not o["ok"] and ko != kn:
            groups["仍拒绝、原因变了：" + "+".join(sorted(ko)) + " → " + "+".join(sorted(kn))].append(cid)
        if o["task_type"] and n["task_type"] and o["task_type"] != n["task_type"]:
            relabel[f"{o['task_type']} → {n['task_type']}"] += 1
    lines = [f"## {title}（{len(pairs)} 条）", "", f"| {old} | {new} | 条数 |", "|---|---|---|"]
    lines += [f"| {YES[a]} | {YES[b]} | {trans[(a, b)]} |" for a in (True, False) for b in (True, False)]
    lines += ["", "### 判决变化", ""]
    lines += [f"- {k}（{len(v)}）：" + ", ".join(v[:10]) + (" …" if len(v) > 10 else "") for k, v in sorted(groups.items())] or ["- 无"]
    lines += ["", "### 类型变化（两边都算出了类型的）", ""]
    lines += [f"- {k}：{v}" for k, v in relabel.most_common()] or ["- 无"]
    return lines


def profile_pairs(results, recs, profiles):
    """(id, verdict without a profile, verdict with it) for every candidate under results whose speaker table is a root
    of its database's confirmed profile. recs: anchors JSON (key -> db record)."""
    by_db, pairs = {v["db"]: (k, v) for k, v in recs.items()}, []
    for f in sorted(glob.glob(os.path.join(results, "*", "candidates.jsonl"))):
        key, rec = by_db.get(os.path.basename(os.path.dirname(f)), (None, None))
        prof = profiles.get(key)
        if not prof or prof.get("confirmed") is not True:
            continue
        roots = {r["table"] for r in prof["roots"]}
        for c in io.read_jsonl(f):
            if c["anchor_table"] in roots:
                pairs.append((c["id"], new_check.run_check_safe(rec, c), new_check.run_check_safe(rec, c, profile=prof)))
    return pairs


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results", default=os.path.join(TASKGEN, "v1", "results"))
    ap.add_argument("--anchors", default=io.ANCHORS_JSON)
    ap.add_argument("--profiles", help="compare this version's check without and with these profiles")
    ap.add_argument("--out")
    a = ap.parse_args()
    if a.profiles:
        pairs = profile_pairs(a.results, io.load_db_recs(a.anchors), db_profile.load(a.profiles))
        lines = ["# 执行检查：不用档案 vs 用档案", "",
                 "`scripts/check_diff.py --profiles` 生成：同一批候选分别跑 v2 的 `check.run_check_safe`，不带档案和带确认过的档案，"
                 "逐条比较；只比说话人是档案根的候选。只列候选 id，不摘录题目内容。", ""]
        lines += section(f"候选：{os.path.relpath(a.results, V2)}", pairs, "不用档案", "用档案")
        return finish(lines, a.out)
    pairs = []
    for env in dysql.ENVS:
        rec = dysql.db_rec(env)
        for c in dysql.candidates(env):
            pairs.append((c["id"], old_check.run_check_safe(rec, c), new_check.run_check_safe(rec, c)))
    lines = ["# 执行检查重新校准：v1 vs v2", "",
             "`scripts/check_diff.py` 生成：同一批候选分别跑 v1（tag `taskgen-v1`，冻结）和 v2 的 `check.run_check_safe`，逐条比较。"
             "只列候选 id，不摘录题目内容。", ""] + section("DySQL 金标准", pairs)
    recs = {v["db"]: v for v in io.load_db_recs(a.anchors).values()}
    pairs = []
    for f in sorted(glob.glob(os.path.join(a.results, "*", "candidates.jsonl"))):
        rec = recs[os.path.basename(os.path.dirname(f))]
        for c in io.read_jsonl(f):
            pairs.append((c["id"], old_check.run_check_safe(rec, c), new_check.run_check_safe(rec, c)))
    lines += [""] + section(f"候选：{os.path.relpath(a.results, V2)}", pairs)
    finish(lines, a.out)


def finish(lines, out):
    text = "\n".join(lines)
    print(text)
    if out:
        with open(out, "w", encoding="utf-8") as f:
            f.write(text + "\n")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 跑测试**

```bash
cd $REPO/taskgen/v2
$P -m pytest -q tests/test_taskgen_check.py tests/test_taskgen_check_diff.py 2>&1 | tail -1
$P -m pytest -q 2>&1 | tail -1
```
Expected: `46 passed`；全套 `117 passed`。

- [ ] **Step 5: 在真实数据上证明不带档案时行为没变**

计划 1 的复核说过，这三处小修涉及的写法在 5221 条真实数据里一条都没出现，所以报告应该照样逐字相同。

```bash
cd $REPO/taskgen/v2
$P scripts/check_diff.py --out $S/recal_task3.md > /dev/null
diff <(sed -n '/^## DySQL 金标准/,$p' docs/2026-10-01-check-recalibration.md) <(sed -n '/^## DySQL 金标准/,$p' $S/recal_task3.md) && echo SAME
```
Expected: `SAME`。

- [ ] **Step 6: 提交**

```bash
cd $REPO
printf '%s\n' '| 执行检查读档案：范围按档案，往 `no_insert` 表 INSERT 拒，算出第 4 类拒（`other_person`）；REPLACE/UPSERT 覆盖已有人物行不算新人，自动主键按每条 INSERT 前现算，重跑时 Ctrl-C 不被吞；`check_diff.py --profiles` | §4.5、D6 |' >> taskgen/v2/README.md
git add taskgen/v2/taskgen_v2/check.py taskgen/v2/taskgen_v2/schema.py taskgen/v2/scripts/check_diff.py \
        taskgen/v2/tests/test_taskgen_check.py taskgen/v2/tests/test_taskgen_check_diff.py taskgen/v2/README.md
git diff --cached --name-only
git commit -m "feat(taskgen v2): the check reads the database profile

With a profile, the write scope, the people and the ownership edges come from it; INSERT into a
no_insert table and gold that computes as type 4 (another person's data, design D6) are rejected.
Without one (DySQL gold, v1 candidates) nothing changes: check_diff reproduces the recalibration
report. Also from the plan-1 review: REPLACE/UPSERT over an existing person row is not new_person,
the auto-assigned key is what SQLite would give before each INSERT, and a Ctrl-C in the rerun
pause propagates. check_diff --profiles compares the check without and with profiles.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: 按档案建嵌套事件树；`trees` 命令读档案

**Files:**
- Modify: `taskgen/v2/taskgen_v2/trees.py`：整个换掉。v1 的 `fk_edges`、`check_scope`、`anchor_key_values` 和旧的 `build_tree` 都删除，只保留 `_safe`、`_rows`、`open_ro`。
- Modify: `taskgen/v2/scripts/taskgen.py`：导入 `db_profile`、`owners`；新增 `profile_of`；重写 `cmd_trees`；`common()` 加 `--profiles`；不再写 `others.json`。
- Test: `taskgen/v2/tests/test_taskgen_trees.py`（整个换掉）、`taskgen/v2/tests/test_taskgen_cli.py`（整个换掉）。

**Interfaces:**
- Consumes: `db_profile.parse_edge`、`db_profile.version`、`db_profile.get`（Task 1）；`owners.Tracer.from_profile`（Task 2）。
- Produces:
  - 常量：`trees.MAX_EVENTS = 30`、`trees.MAX_DEPTH = 4`。
  - 抽根行：
    - `root_key_values(conn, profile, root, rng, n=None) -> [key]`：有事件的行在前。
    - `allocate(n, sizes) -> [int]`
  - `build_tree(conn, profile, root, key_value, rng, tracer, max_events=MAX_EVENTS) -> tree | None`。tree 的字段：
    - 沿用的：`anchor_table`、`anchor_key`、`key_value`、`anchor_name`、`anchor_row`、`profile_version`。
    - 新增的：
      - `parents`：节点列表。
      - `attributes`：`{table: [rows]}`。
      - `events`：`[{"table", "label", "count", "rows": [节点]}]`。
    - 节点的形状：`{"table", "row", "label", "parents": [节点]}`。
  - 出题时的视图：
    - `has_public(tree) -> bool`
    - `pick_events(tree, rng, k, need_public=False) -> [[group, row]]`
    - `shown(tree, refs) -> [group]`
    - `tables_by_label(tree, refs) -> {"own", "public", "other"}`
  - `taskgen.py trees --db X [--profiles P] [--n N] [--anchor ROOT]`：没有档案或档案未确认时，退出码 1，stderr 里有 `not confirmed`。
- **注意：** 本 Task 到 Task 5 之间，`generate` 命令还在读 `others.json`，不能用于真实运行；测试不受影响。

- [ ] **Step 1: 写会失败的测试**

`taskgen/v2/tests/test_taskgen_trees.py` 整个换成：

```python
# tests/test_taskgen_trees.py
import random, sqlite3
import pytest
from taskgen_common.testing import make_db
from v2_fixtures import SHOP2, FKS, CUSTOMER, STAFF, SHOP_PROFILE, SCHOOL, SCHOOL_FKS, SCHOOL_COMPOSITE, SCHOOL_PROFILE   # noqa: F401 (re-exported)
from taskgen_v2 import db_profile, owners, trees

SHOP_REC = {"source": "test", "db": "shop2", "anchors": [CUSTOMER, STAFF], "fks": FKS}
SCHOOL_REC = {"source": "test", "db": "school", "anchors": [], "fks": SCHOOL_FKS, "fks_composite": SCHOOL_COMPOSITE}
CUSTOMERS = SHOP_PROFILE["roots"][0]
STUDENTS = SCHOOL_PROFILE["roots"][0]


@pytest.fixture
def shop(tmp_path):
    c = sqlite3.connect(make_db(tmp_path, "shop2", SHOP2)); yield c; c.close()


@pytest.fixture
def school(tmp_path):
    c = sqlite3.connect(make_db(tmp_path, "school", SCHOOL)); yield c; c.close()


def tree(conn, profile, rec, root, key, **kw):
    return trees.build_tree(conn, profile, root, key, random.Random(0), owners.Tracer.from_profile(profile, rec, conn), **kw)


def test_root_rows_with_events_come_first(shop):
    shop.execute("DELETE FROM orders WHERE customer_id = 7"); shop.commit()
    keys = trees.root_key_values(shop, SHOP_PROFILE, CUSTOMERS, random.Random(0))
    assert len(keys) == 60 and keys[-1] == 7                        # every customer, the one without orders last
    assert trees.root_key_values(shop, SHOP_PROFILE, CUSTOMERS, random.Random(0), 5) == keys[:5]


def test_allocate_passes_unused_shares_on():
    assert trees.allocate(200, [2000, 50]) == [150, 50]
    assert trees.allocate(10, [3, 3]) == [3, 3]
    assert trees.allocate(5, [10, 10]) == [2, 3]


def test_events_follow_paths_and_parents_nest(shop):
    t = tree(shop, SHOP_PROFILE, SHOP_REC, CUSTOMERS, 5)
    assert t["anchor_name"] == "a5 b5" and t["anchor_row"]["customer_id"] == 5
    assert t["profile_version"] == db_profile.version(SHOP_PROFILE) and t["parents"] == [] and t["attributes"] == {}
    orders, items = t["events"]
    assert (orders["table"], orders["count"], [n["row"]["order_id"] for n in orders["rows"]]) == ("orders", 2, [5, 65])
    assert orders["rows"][0]["label"] == "own"
    assert orders["rows"][0]["parents"] == [{"table": "products", "row": {"product_id": 5, "name": "p5", "price": 1.0},
                                            "label": "public", "parents": []}]
    # two hops (customers -> orders -> order_items): the items of orders 5 and 65 only
    assert items["count"] == 6 and {n["row"]["order_id"] for n in items["rows"]} == {5, 65}


def test_composite_parent_attribute_root_parent_and_other_person(school):
    t = tree(school, SCHOOL_PROFILE, SCHOOL_REC, STUDENTS, 3)
    assert t["parents"] == [{"table": "dept", "row": {"dept_name": "d1", "building": "B1"}, "label": "public", "parents": []}]
    assert t["attributes"] == {"flags": [{"sid": 3, "honors": 1}]}
    takes, advisor = t["events"]
    assert [n["parents"][0]["row"]["title"] for n in takes["rows"]] == ["Algebra", "Biology"]   # (course, sec) -> section
    assert advisor["rows"][0]["label"] == "own" and advisor["rows"][0]["parents"][0]["label"] == "other:t0"


def test_events_are_capped_with_one_per_group(shop):
    t = tree(shop, SHOP_PROFILE, SHOP_REC, CUSTOMERS, 5, max_events=2)
    assert [len(g["rows"]) for g in t["events"]] == [1, 1] and [g["count"] for g in t["events"]] == [2, 6]


def test_missing_key_and_empty_foreign_keys(shop):
    assert tree(shop, SHOP_PROFILE, SHOP_REC, CUSTOMERS, 999) is None
    shop.execute("UPDATE orders SET product_id = NULL WHERE order_id = 5"); shop.commit()
    t = tree(shop, SHOP_PROFILE, SHOP_REC, CUSTOMERS, 5)
    assert t["events"][0]["rows"][0]["parents"] == []


def test_blob_values_are_json_safe(shop):
    shop.execute("UPDATE customers SET first_name = x'00ff' WHERE customer_id = 5"); shop.commit()
    assert tree(shop, SHOP_PROFILE, SHOP_REC, CUSTOMERS, 5)["anchor_row"]["first_name"] == "<blob 2 bytes>"


def test_picked_events_cover_groups_and_put_a_public_one_first(shop):
    t = tree(shop, SHOP_PROFILE, SHOP_REC, CUSTOMERS, 5)
    refs = trees.pick_events(t, random.Random(1), 3, need_public=True)
    assert len(refs) == 3 and refs[0][0] == 0                     # only orders have a public parent (products)
    assert {g for g, _ in refs[:2]} == {0, 1}                       # then a row of the group not shown yet
    shown = trees.shown(t, refs)
    assert [g["table"] for g in shown] == ["orders", "order_items"] and sum(len(g["rows"]) for g in shown) == 3
    assert trees.tables_by_label(t, refs) == {"own": ["customers", "orders", "order_items"], "public": ["products"], "other": []}
    assert trees.has_public(t)
    assert not trees.has_public({**t, "events": [t["events"][1]]})
```

`taskgen/v2/tests/test_taskgen_cli.py` 整个换成下面这样。和最终版相比，这里还没有 `check` 拒档案的检查（Task 5 加），也没有 `profile` 命令的测试（Task 6 加）：

```python
# tests/test_taskgen_cli.py
import json, os, subprocess, sys
from taskgen_common.testing import make_db
from v2_fixtures import SHOP2, FKS, CUSTOMER, STAFF, SHOP_PROFILE
from taskgen_v2 import db_profile, io

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "taskgen.py")


def run(*args, check=True):
    return subprocess.run([sys.executable, SCRIPT, *args], check=check, capture_output=True, text=True)


def setup(tmp_path, confirmed=True):
    db = make_db(tmp_path, "shop2", SHOP2)
    anchors = tmp_path / "anchors.json"
    anchors.write_text(json.dumps({"test:shop2": {"source": "test", "db": "shop2", "path": db, "anchors": [CUSTOMER, STAFF], "fks": FKS}}))
    profiles = tmp_path / "profiles.json"
    db_profile.save({"test:shop2": {**SHOP_PROFILE, "confirmed": confirmed}}, str(profiles))
    return ["--db", "test:shop2", "--anchors", str(anchors), "--profiles", str(profiles), "--out-dir", str(tmp_path / "res")]


def test_trees_check_dedup_convert_without_a_model(tmp_path):
    args = setup(tmp_path)
    out = tmp_path / "res"
    run("trees", *args, "--n", "3", "--seed", "0")
    run("trees", *args, "--n", "3", "--seed", "0")
    trees = io.read_jsonl(out / "trees.jsonl")
    assert len(trees) == 3 and all(t["anchor_table"] == "customers" and t["events"][0]["rows"] for t in trees)   # a rerun adds nothing
    assert not os.path.exists(out / "others.json")
    t = trees[0]
    oid = t["events"][0]["rows"][0]["row"]["order_id"]
    io.append_jsonl(out / "candidates.jsonl", [{"id": "test:shop2:customers:%s:0" % t["key_value"], "db": "shop2", "source": "test",
        "anchor_table": "customers", "anchor_key": "customer_id", "key_value": t["key_value"], "anchor_name": t["anchor_name"],
        "plan": {"task_type": "1_self", "difficulty": "easy"}, "instruction": f"I am {t['anchor_name']}. Set qty of my order {oid} to 3.",
        "actions": [{"sql": f"UPDATE orders SET qty = 3 WHERE order_id = {oid}"}], "outputs": [], "error": None}])
    run("check", *args)
    chk = io.read_jsonl(out / "check.jsonl")
    assert len(chk) == 1 and chk[0]["ok"] and chk[0]["template"] == "1_self|UPDATE orders"
    io.append_jsonl(out / "verify.jsonl", [{"id": chk[0]["id"], "votes": [{"verdict": "yes"}] * 3, "yes": 3, "no": 0, "pass": True, "verify_model": "fake"}])
    run("dedup", *args)
    assert len(io.read_jsonl(out / "selected.jsonl")) == 1
    manifest = tmp_path / "manifest.json"; tasks = tmp_path / "tasks.jsonl"
    run("convert", *args, "--tasks", str(tasks), "--manifest", str(manifest))
    assert io.read_jsonl(tasks)[0]["meta"]["template"] == "1_self|UPDATE orders" and json.load(open(manifest))["shop2"]["db_key"] == "test:shop2"
    assert "n_selected" in run("stats", *args).stdout


def test_trees_refuse_an_unconfirmed_profile(tmp_path):
    r = run("trees", *setup(tmp_path, confirmed=False), check=False)
    assert r.returncode == 1 and "not confirmed" in r.stderr
```

- [ ] **Step 2: 跑测试，确认失败**

```bash
cd $REPO/taskgen/v2
$P -m pytest -q tests/test_taskgen_trees.py tests/test_taskgen_cli.py 2>&1 | tail -3
```
Expected: `10 failed`。trees 测试报 `AttributeError`（没有 `root_key_values`、`allocate`）或 `TypeError`（`build_tree` 的参数不对）；CLI 测试的子进程退出码是 2，因为没有 `--profiles` 这个参数。

- [ ] **Step 3: 实现**

`taskgen/v2/taskgen_v2/trees.py` 整个换成：

```python
# taskgen/v2/taskgen_v2/trees.py
"""Event trees (design §4.2): for one root row, its event records as the profile defines them, each event row with the
parent rows it actually references nested under it (purchase -> product -> brand), and the root's own parent rows and
1:1 attributes. Every row carries its owner label (owners.Tracer), the same label the execution check computes."""
import json, sqlite3
from taskgen_common.db_select import _q
from taskgen_v2 import db_profile

MAX_EVENTS = 30   # event rows kept per tree; the prompt shows 3-12 of them
MAX_DEPTH = 4     # levels of parent rows under an event


def _safe(v):
    return f"<blob {len(v)} bytes>" if isinstance(v, (bytes, memoryview)) else v


def _rows(c, sql, params=()):
    cur = c.execute(sql, params)
    cols = [d[0] for d in cur.description]
    return [{k: _safe(v) for k, v in zip(cols, r)} for r in cur.fetchall()]


def root_key_values(conn, profile, root, rng, n=None):
    """Key values of up to n root rows in sampling order: rows with at least one event first, then the others (each
    part shuffled), so a small database still gives n trees (hr_1: 7 of 107 employees have job_history rows)."""
    t, key = root["table"], profile["persons"][root["table"]]["key"]
    with_events = set()
    for e in (db_profile.parse_edge(ev["path"][0]) for ev in profile["events"]):
        if e.parent == t:
            sub = f"SELECT {', '.join(_q(c) for c in e.cols)} FROM {_q(e.child)}"
            ref = ", ".join(_q(c) for c in e.ref_cols)
            with_events |= {r[0] for r in conn.execute(f"SELECT {_q(key)} FROM {_q(t)} WHERE ({ref}) IN ({sub})")}
    every = [r[0] for r in conn.execute(f"SELECT {_q(key)} FROM {_q(t)} WHERE {_q(key)} IS NOT NULL ORDER BY {_q(key)}")]
    first, rest = [k for k in every if k in with_events], [k for k in every if k not in with_events]
    rng.shuffle(first)
    rng.shuffle(rest)
    return (first + rest)[:n] if n is not None else first + rest


def allocate(n, sizes):
    """n trees over roots that have sizes[i] rows each: equal shares, and a root with fewer rows passes the rest on."""
    alloc, left = [0] * len(sizes), n
    order = sorted(range(len(sizes)), key=lambda i: sizes[i])
    for done, i in enumerate(order):
        alloc[i] = min(sizes[i], left // (len(order) - done))
        left -= alloc[i]
    return alloc


def _event_rows(conn, path, root_row):
    """Rows of the path's last table under root_row, joined down the path; [] when the root's value is empty."""
    vals = [root_row.get(c) for c in path[0].ref_cols]
    if any(v in (None, "") for v in vals):
        return []
    n = len(path)
    sql = f"SELECT DISTINCT t{n - 1}.* FROM {_q(path[-1].child)} t{n - 1}"
    for i in range(n - 1, 0, -1):
        on = " AND ".join(f"t{i}.{_q(c)} = t{i - 1}.{_q(r)}" for c, r in zip(path[i].cols, path[i].ref_cols))
        sql += f" JOIN {_q(path[i - 1].child)} t{i - 1} ON {on}"
    sql += " WHERE " + " AND ".join(f"t0.{_q(c)} = ?" for c in path[0].cols)
    return sorted(_rows(conn, sql, vals), key=lambda r: json.dumps(r, sort_keys=True, default=str))


def _node(conn, table, row, specs, tracer, speaker, depth=0):
    return {"table": table, "row": row, "label": tracer.label(table, row, speaker),
            "parents": _parents(conn, row, specs, tracer, speaker, depth)}


def _parents(conn, row, specs, tracer, speaker, depth=0):
    out = []
    if depth >= MAX_DEPTH:
        return out
    for p in specs or []:
        e = db_profile.parse_edge(p["via"])
        vals = [row.get(c) for c in e.cols]
        if any(v in (None, "") for v in vals):
            continue
        where = " AND ".join(f"{_q(r)} = ?" for r in e.ref_cols)
        got = _rows(conn, f"SELECT * FROM {_q(e.parent)} WHERE {where} LIMIT 1", vals)
        if got:
            out.append(_node(conn, e.parent, got[0], p.get("parents"), tracer, speaker, depth + 1))
    return out


def _cap(groups, rng, k):
    """Row indices kept per group: all of them when they fit k, else one random row per group plus random others."""
    if sum(len(g) for g in groups) <= k:
        return [list(range(len(g))) for g in groups]
    keep, pool = [[] for _ in groups], []
    for gi, g in enumerate(groups):
        idx = list(range(len(g)))
        rng.shuffle(idx)
        keep[gi] += idx[:1]
        pool += [(gi, j) for j in idx[1:]]
    rng.shuffle(pool)
    for gi, j in pool[:max(0, k - sum(map(len, keep)))]:
        keep[gi].append(j)
    return [sorted(x) for x in keep]


def build_tree(conn, profile, root, key_value, rng, tracer, max_events=MAX_EVENTS):
    """The root row with its parents and attributes, and each of the root's event groups with up to max_events rows
    in all, every event row with its parent rows nested. None when no row has this key."""
    t, person = root["table"], profile["persons"][root["table"]]
    found = _rows(conn, f"SELECT * FROM {_q(t)} WHERE {_q(person['key'])} = ?", (key_value,))
    if not found:
        return None
    row, speaker = found[0], {(t, str(key_value))}
    groups = []
    for ev in profile["events"]:
        path = [db_profile.parse_edge(x) for x in ev["path"]]
        if path[0].parent == t:
            groups.append((ev, _event_rows(conn, path, row)))
    keep = _cap([rs for _, rs in groups], rng, max_events)
    attrs = {}
    for a in profile["attributes"]:
        e = db_profile.parse_edge(a["via"])
        vals = [row.get(r) for r in e.ref_cols]
        if a["of"] == t and all(v not in (None, "") for v in vals):
            got = _rows(conn, f"SELECT * FROM {_q(a['table'])} WHERE " + " AND ".join(f"{_q(c)} = ?" for c in e.cols), vals)
            if got:
                attrs[a["table"]] = got
    return {"anchor_table": t, "anchor_key": person["key"], "key_value": key_value,
            "anchor_name": " ".join(str(row[c]) for c in person["name_cols"] if row.get(c) not in (None, "")),
            "anchor_row": row, "profile_version": db_profile.version(profile),
            "parents": _parents(conn, row, root.get("parents"), tracer, speaker),
            "attributes": attrs,
            "events": [{"table": ev["table"], "label": ev["label"], "count": len(rs),
                        "rows": [_node(conn, ev["table"], rs[j], ev.get("parents"), tracer, speaker) for j in idx]}
                       for (ev, rs), idx in zip(groups, keep)]}


def _public_in(node):
    return node["label"] == "public" or any(_public_in(p) for p in node["parents"])


def has_public(tree):
    """Whether any row of the tree is public data: types 2 and 3 need one to write."""
    return any(_public_in(p) for p in tree["parents"]) or any(_public_in(n) for g in tree["events"] for n in g["rows"])


def pick_events(tree, rng, k, need_public=False):
    """[[group, row], ...] of the k event rows the prompt shows: with need_public an event with a public row under
    it first (when there is one), then one row of each group not shown yet, then random others."""
    refs = [(gi, j) for gi, g in enumerate(tree["events"]) for j in range(len(g["rows"]))]
    rng.shuffle(refs)
    first = [r for r in refs if _public_in(tree["events"][r[0]]["rows"][r[1]])][:1] if need_public else []
    seen, spread, rest = {r[0] for r in first}, [], []
    for r in refs:
        if r in first:
            continue
        (spread if r[0] not in seen else rest).append(r)
        seen.add(r[0])
    return [list(r) for r in (first + spread + rest)[:k]]


def shown(tree, refs):
    """The event groups cut down to refs, in tree order; groups without a shown row are left out."""
    want, out = {tuple(r) for r in refs}, []
    for gi, g in enumerate(tree["events"]):
        rows = [n for j, n in enumerate(g["rows"]) if (gi, j) in want]
        if rows:
            out.append({**g, "rows": rows})
    return out


def tables_by_label(tree, refs):
    """{'own', 'public', 'other'}: the tables of the rows the prompt shows, in first-seen order. The root table and
    the attribute tables are own."""
    out = {"own": [tree["anchor_table"]] + list(tree["attributes"]), "public": [], "other": []}

    def add(node):
        kind = node["label"] if node["label"] in ("own", "public") else "other"
        if node["table"] not in out[kind]:
            out[kind].append(node["table"])
        for p in node["parents"]:
            add(p)
    for p in tree["parents"]:
        add(p)
    for g in shown(tree, refs):
        for n in g["rows"]:
            add(n)
    return out


def open_ro(path):
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)
```

`scripts/taskgen.py`：

1. 导入那行加上 `db_profile, owners`：
   ```python
   from taskgen_v2 import io, trees, schema, llm, prompt, generate, check, verify, dedup, convert, stats, db_profile, owners
   ```
2. 模块 docstring 的用法和文件说明改成：
   ```
   Usage (from taskgen/v2/), pilot on beer_factory (its profile in data/db_profiles.json must be confirmed):
     P=~/miniconda3/envs/dysql/bin/python; DB=bird:beer_factory
     $P scripts/taskgen.py profile  check --db $DB
     $P scripts/taskgen.py trees    --db $DB --n 50 --seed 0
   ```
   保留 describe 到 stats 那几行。`Files:` 那一行改成：
   ```
   Files: data/db_profiles.json; results/<db>/{trees,candidates,check,verify,selected}.jsonl; output/<db>/tasks.jsonl,
   output/manifest.json.
   ```
3. 整个 `cmd_trees` 换成下面这段（含新增的 `profile_of`）：

```python
def profile_of(a):
    try:
        return db_profile.get(a.db, a.profiles)
    except ValueError as e:
        sys.exit(str(e))


def cmd_trees(a):
    rec, out = rec_and_dir(a)
    prof = profile_of(a)
    c = trees.open_ro(io.resolve_db_path(rec["path"]))
    tracer = owners.Tracer.from_profile(prof, rec, c)
    done = {(t["anchor_table"], str(t["key_value"])) for t in io.read_jsonl(f"{out}/trees.jsonl")}
    roots = [r for r in prof["roots"] if not a.anchor or r["table"] == a.anchor]
    rngs = {r["table"]: random.Random(f"{a.seed}:{r['table']}") for r in roots}   # per root: a rerun draws the same sample
    keys = {r["table"]: trees.root_key_values(c, prof, r, rngs[r["table"]]) for r in roots}
    for r, n in zip(roots, trees.allocate(a.n, [len(keys[r["table"]]) for r in roots])):
        t, rng = r["table"], rngs[r["table"]]
        built = [tr for kv in keys[t][:n] if (t, str(kv)) not in done
                 and (tr := trees.build_tree(c, prof, r, kv, rng, tracer))]
        io.append_jsonl(f"{out}/trees.jsonl", built)
        print(f"{t}: {len(built)} trees written")
```

4. `common()` 里，在 `p.add_argument("--out-dir"); p.add_argument("--seed", type=int, default=0)` 后面加一行：
   ```python
           p.add_argument("--profiles", default=db_profile.PROFILES_JSON)
   ```
   `trees` 子命令的 `p.add_argument("--anchor")` 改成 `p.add_argument("--anchor", help="one root table only")`。

- [ ] **Step 4: 跑测试**

```bash
cd $REPO/taskgen/v2
$P -m pytest -q tests/test_taskgen_trees.py tests/test_taskgen_cli.py 2>&1 | tail -1
$P -m pytest -q 2>&1 | tail -1
grep -rn "fk_edges\|check_scope\|anchor_key_values\|others.json" --include=*.py taskgen_v2 scripts/taskgen.py
```
Expected: `10 passed`；全套 `118 passed`。grep 只输出一行，是 `cmd_generate` 里的 `others = json.load(open(f"{out}/others.json"))`，Task 5 会去掉它。

- [ ] **Step 5: 提交**

```bash
cd $REPO
printf '%s\n' '| 建树：按档案嵌套事件树（事件行挂实际引用的父行，带归属标签，≤30 条事件，先抽有事件的根行，双根按可用行数分）；`trees` 命令要已确认的档案，不再写 `others.json` | §4.2、D3 |' >> taskgen/v2/README.md
git add taskgen/v2/taskgen_v2/trees.py taskgen/v2/scripts/taskgen.py taskgen/v2/tests/test_taskgen_trees.py \
        taskgen/v2/tests/test_taskgen_cli.py taskgen/v2/README.md
git diff --cached --name-only
git commit -m "feat(taskgen v2): event trees nested from the database profile

For one root row, each event group the profile defines (joined down its path), every event row
with the parent rows it references nested under it, the root's own parents and 1:1 attributes;
rows carry owners.Tracer labels. Up to 30 events per tree, at least one per group. Root rows
with events are sampled first; two roots share --n by the rows they have. The trees command
needs a confirmed profile and no longer writes others.json (no type 4, design D6).

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: 出题读新树（展示 3–12 条事件，不出第 4 类）；`generate`、`check` 命令读档案

**Files:**
- Modify: `taskgen/v2/taskgen_v2/prompt.py`：模块 docstring、导入、`CFG`，以及从 `def feasible_types` 到文件末尾整段换掉。
- Modify: `taskgen/v2/taskgen_v2/generate.py`：`run` 去掉 `others` 参数；候选记下 `profile_version`。
- Modify: `taskgen/v2/taskgen_v2/io.py`：删掉没人用的 `person_anchors`。
- Modify: `taskgen/v2/scripts/taskgen.py`：`cmd_generate`、`cmd_check` 读档案。
- Test: `taskgen/v2/tests/test_taskgen_prompt.py`（整个换掉）、`taskgen/v2/tests/test_taskgen_generate.py`（改签名）、`taskgen/v2/tests/test_taskgen_cli.py`（拒档案的测试加上 `check`）。

**Interfaces:**
- Consumes: Task 4 的树结构和 `trees.has_public`、`pick_events`、`shown`、`tables_by_label`；`db_profile.root_anchor`；`check.run_check_safe(..., profile=)`（Task 3）。
- Produces:
  - `prompt.CFG` 新增三项：`EVENTS_SHOWN`、`DATA_CHARS = 16000`、`MAX_VALUE_CHARS = 200`。
  - 出题计划：
    - `feasible_types(tree)`
    - `sample_plan(rng, tree, anchor, cfg=CFG)`：plan 新增 `events`（展示的事件引用）和 `tables`（`{own, public, other}`），不再有 `other`。
  - 拼 prompt：
    - `data_blocks(tree, refs, who, cfg=CFG) -> str`
    - `shape_text(anchor, plan)`
    - `next_ids_block(plan, next_ids)`
    - `build_messages(db_rec, anchor, tree, plan, db_description, schema_text, cfg=CFG, next_ids=None)`（签名不变）
  - `generate.run(db_rec, anchor, trees_list, client, out_path, rng, workers=8, per_tree=1, cfg=prompt.CFG, db_description="", schema_text="", retry_errors=False, next_ids=None)`；候选多一个字段 `profile_version`。
  - `taskgen.py generate|check --db X [--profiles P]`：档案未确认时退出码 1。

- [ ] **Step 1: 写会失败的测试**

`taskgen/v2/tests/test_taskgen_prompt.py` 整个换成：

```python
# tests/test_taskgen_prompt.py
import random
from collections import Counter
from taskgen_v2 import prompt

ANCHOR = {"table": "customers", "key": "customer_id", "names": ["first_name", "last_name"]}
DB = {"source": "test", "db": "shop", "path": "x", "anchors": [], "fks": []}


def order(i, label="own"):
    return {"table": "orders", "row": {"order_id": i, "customer_id": 5, "product_id": i, "qty": 1}, "label": label,
            "parents": [{"table": "products", "row": {"product_id": i, "name": f"p{i}", "price": 1.0}, "label": "public", "parents": []}]}


TREE = {"anchor_table": "customers", "anchor_key": "customer_id", "key_value": 5, "anchor_name": "a5 b5",
        "anchor_row": {"customer_id": 5, "first_name": "a5", "last_name": "b5"}, "profile_version": "v1",
        "parents": [{"table": "staff", "row": {"staff_id": 2, "name": "s2"}, "label": "other:s2", "parents": []}],
        "attributes": {"vip": [{"customer_id": 5, "level": 3}]},
        "events": [{"table": "orders", "label": "orders", "count": 14, "rows": [order(i) for i in range(12)]},
                   {"table": "reviews", "label": "reviews", "count": 1,
                    "rows": [{"table": "reviews", "row": {"review_id": 1, "customer_id": 5, "stars": 4}, "label": "own", "parents": []}]}]}
NO_PUBLIC = {**TREE, "events": [TREE["events"][1]]}


def plan_for(task_type, difficulty="easy", tree=TREE, **shape):
    rng = random.Random(0)
    while True:
        p = prompt.sample_plan(rng, tree, ANCHOR)
        if p["task_type"] == task_type and p["difficulty"] == difficulty and all(p["shape"][k] == v for k, v in shape.items()):
            return p


def test_examples_cover_every_type_with_at_least_two():
    ex = prompt.load_examples()
    assert set(ex) == set(prompt.CFG["TYPE_MIX"]) and all(len(v) >= 2 for v in ex.values())


def test_no_type_4_and_public_types_need_a_public_row():
    assert prompt.feasible_types(TREE) == ["1_self", "2_self_and_public", "3_public_only", "5_proxy"]
    assert prompt.feasible_types(NO_PUBLIC) == ["1_self", "5_proxy"]


def test_sample_plan_follows_the_mix_and_shows_more_events_when_harder():
    rng = random.Random(0)
    plans = [prompt.sample_plan(rng, TREE, ANCHOR) for _ in range(3000)]
    types, diffs = Counter(p["task_type"] for p in plans), Counter(p["difficulty"] for p in plans)
    assert "4_other_person" not in types
    assert abs(types["1_self"] / 3000 - 0.46 / 0.92) < 0.04 and abs(types["5_proxy"] / 3000 - 0.29 / 0.92) < 0.04
    assert abs(diffs["hard"] / 3000 - 0.29) < 0.04
    for p in plans:
        lo, hi = prompt.CFG["EVENTS_SHOWN"][p["difficulty"]]
        assert lo <= len(p["events"]) <= hi
        if p["task_type"] in ("2_self_and_public", "3_public_only"):
            assert p["shape"]["public_table"] and p["tables"]["public"] == ["products"]
        if p["difficulty"] == "hard":
            assert p["shape"]["n_writes"] >= 2 and p["shape"]["n_tables"] >= 2
        assert p["example"] in prompt.load_examples()[p["task_type"]]
    assert {p["tables"]["own"][0] for p in plans} == {"customers"}


def test_long_data_loses_events_until_it_fits():
    big = {**TREE, "events": [{**TREE["events"][0], "rows": [{**order(i), "row": {**order(i)["row"], "note": "x" * 150}} for i in range(12)]}]}
    cfg = {**prompt.CFG, "DATA_CHARS": 1200}
    p = prompt.sample_plan(random.Random(3), big, ANCHOR, cfg)
    assert 1 <= len(p["events"]) < prompt.CFG["EVENTS_SHOWN"][p["difficulty"]][0]
    assert len(prompt.data_blocks(big, p["events"], "x", cfg)) <= 1200 or len(p["events"]) == 1


def test_data_blocks_nest_parents_and_say_whose_data_it_is():
    text = prompt.data_blocks(TREE, [[0, 0], [1, 0]], "the speaker's own row")
    assert text.startswith('## customers record (the speaker\'s own row)\n{"customer_id": 5, "first_name": "a5", "last_name": "b5"}')
    assert '- vip (own): {"customer_id": 5, "level": 3}' in text
    assert '- staff (another person\'s data: s2): {"staff_id": 2, "name": "s2"}' in text
    assert "## orders: orders records (1 of 14 shown)\n- orders (own): " in text
    assert '\n  - products (public, shared reference data owned by nobody): {"product_id": 0' in text
    assert "## reviews: reviews records (1 of 1 shown)" in text
    long = {**TREE, "anchor_row": {**TREE["anchor_row"], "bio": "y" * 500}}
    assert '"bio": "' + "y" * 200 + '... (500 chars)"' in prompt.data_blocks(long, [], "x")


def test_build_messages_fills_type_shape_and_scope():
    p = plan_for("2_self_and_public", "medium")
    msgs = prompt.build_messages(DB, ANCHOR, TREE, p, "A shop.", "CREATE TABLE customers (...)")
    assert msgs[0]["role"] == "system" and f"## Instruction Example\n{p['example']}" in msgs[0]["content"]
    u = msgs[1]["content"]
    assert "a5 b5 (customer_id = 5)" in u and "shared table (products)" in u and "At least one write must change a shared table: products." in u
    assert "## customers record" in u and "CREATE TABLE customers" in u and "A shop." in u
    p5 = plan_for("5_proxy")
    u = prompt.build_messages(DB, ANCHOR, TREE, p5, "A shop.", "DDL")[1]["content"]
    assert "NOT in the database" in u and "the person the request is about" in u
    assert f"The speaker is {p5['style']['name']}, {p5['style']['role']}" in u


def test_system_requires_quoted_table_names():
    s = prompt.build_messages(DB, ANCHOR, TREE, plan_for("1_self"), "A shop.", "DDL")[0]["content"]
    assert "Wrap every table name in double quotes" in s and '"transaction"' in s


def test_next_ids_only_for_tables_the_prompt_shows():
    p = plan_for("1_self")
    u = prompt.build_messages(DB, ANCHOR, TREE, p, "A shop.", "DDL",
                              next_ids={"orders": ("order_id", 101), "products": ("product_id", 61), "unrelated": ("id", 9)})[1]["content"]
    assert "## Next unused primary keys" in u and "orders.order_id = 101" in u and "unrelated" not in u
    assert "Next unused" not in prompt.build_messages(DB, ANCHOR, TREE, p, "A shop.", "DDL")[1]["content"]


def test_sample_plan_style_varies_names_roles_and_openers():
    rng = random.Random(1)
    plans = [prompt.sample_plan(rng, TREE, ANCHOR) for _ in range(400)]
    proxies = [p for p in plans if p["task_type"] == "5_proxy"]
    assert len({p["style"]["name"] for p in proxies}) > 30 and len({p["style"]["role"] for p in proxies}) >= 8
    assert all(p["style"]["name"] is None for p in plans if p["task_type"] != "5_proxy")
    assert len({p["style"]["opener"] for p in plans}) >= 6
```

`taskgen/v2/tests/test_taskgen_generate.py`：
- 导入改成 `from test_taskgen_prompt import ANCHOR, DB, TREE`。
- 所有 `generate.run(DB, ANCHOR, [...], OTHERS, client, ...)` 里的 `OTHERS, ` 删掉（共 9 处）。
- `test_run_writes_records_and_resumes` 里关于 `task_type` 的断言换成：

```python
    assert recs[0]["plan"]["task_type"] in ("1_self", "2_self_and_public", "3_public_only", "5_proxy")
    assert recs[0]["profile_version"] == "v1" and recs[0]["plan"]["events"]
```

`taskgen/v2/tests/test_taskgen_cli.py` 里的 `test_trees_refuse_an_unconfirmed_profile` 换成：

```python
def test_trees_and_check_refuse_an_unconfirmed_profile(tmp_path):
    args = setup(tmp_path, confirmed=False)
    for cmd in ("trees", "check"):
        r = run(cmd, *args, check=False)
        assert r.returncode == 1 and "not confirmed" in r.stderr
```

- [ ] **Step 2: 跑测试，确认失败**

```bash
cd $REPO/taskgen/v2
$P -m pytest -q tests/test_taskgen_prompt.py tests/test_taskgen_generate.py tests/test_taskgen_cli.py 2>&1 | tail -3
```
Expected: `15 failed, 4 passed`。失败的是：
- prompt 的 8 个用到新树或新签名的测试：`TypeError`；
- generate 里调用 `run` 的 6 个测试：`TypeError: run() missing 1 required positional argument: 'rng'`；
- CLI 拒档案的那个测试：`check` 退出码是 0。

通过的 4 个都不碰新树：`test_examples_cover_every_type_with_at_least_two`、两个 `test_parse_answer_*`、CLI 的端到端测试。

- [ ] **Step 3: 实现**

`prompt.py`：

1. 模块 docstring 和导入：
   ```python
   # taskgen/v2/taskgen_v2/prompt.py
"""Task plan sampling (type x difficulty x shape) and the generation prompt.
SYSTEM is DySQL's generation prompt (data_pipeline_shell/generate_sqlbench_multiTurn_qa.py) with one example
instruction chosen by task type; the USER message is built from the event tree (trees.py): the root row, then 3-12 of
its events with their parent rows nested, every row tagged with whose data it is."""
import json, os, random
from taskgen_v2 import trees
   ```
   原来的 `from taskgen_common.db_select import _q` 没有用处，删掉。
2. `CFG` 里 `"MAX_ROWS_PER_STMT": 50,` 后面加三行：
   ```python
       "EVENTS_SHOWN": {"easy": (3, 5), "medium": (5, 8), "hard": (8, 12)},   # design §4.2: 3-12 events, more when harder
       "DATA_CHARS": 16000,      # data blocks longer than this lose events from the end (about 4k tokens)
       "MAX_VALUE_CHARS": 200,   # longer text values are cut in the prompt
   ```
3. 从 `def feasible_types(` 到文件末尾，整段换成：

```python
def feasible_types(tree):
    """Types this tree can carry. Never 4_other_person (design D6); 2 and 3 need a public row to write."""
    return ["1_self"] + (["2_self_and_public", "3_public_only"] if trees.has_public(tree) else []) + ["5_proxy"]


def _shape(rng, difficulty, task_type, n_scope, has_events):
    s = {"n_writes": 1, "n_tables": 1, "ownership_subquery": False, "archive": False,
         "public_table": task_type in ("2_self_and_public", "3_public_only")}
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
        if rng.random() < 0.25 and has_events:
            s["archive"] = True
    if s["public_table"] and s["n_tables"] < 2 and task_type == "2_self_and_public":
        s.update(n_writes=max(s["n_writes"], 2), n_tables=2)
    return s


def _who(task_type):
    return "the speaker's own row" if task_type != "5_proxy" else "the person the request is about"


def sample_plan(rng, tree, anchor, cfg=CFG):
    task_type = _weighted(rng, {k: v for k, v in cfg["TYPE_MIX"].items() if k in feasible_types(tree)})
    difficulty = _weighted(rng, cfg["DIFFICULTY_MIX"])
    lo, hi = cfg["EVENTS_SHOWN"][difficulty]
    refs = trees.pick_events(tree, rng, rng.randint(lo, hi), need_public=task_type in ("2_self_and_public", "3_public_only"))
    while len(refs) > 1 and len(data_blocks(tree, refs, _who(task_type), cfg)) > cfg["DATA_CHARS"]:
        refs.pop()                                           # the event a public type needs is first, so it stays
    tabs = trees.tables_by_label(tree, refs)
    shape = _shape(rng, difficulty, task_type, len(tabs["own"]) + len(tabs["public"]), bool(refs))
    pool = tabs["public"] if task_type == "3_public_only" else tabs["own"]
    free = rng.random() < cfg["FREE_TABLE_SHARE"]
    write_tables = None
    if not free:
        k = min(shape["n_tables"], len(pool)) if task_type != "2_self_and_public" else min(shape["n_tables"] - 1, len(pool))
        write_tables = rng.sample(pool, max(1, k))
        if task_type == "2_self_and_public":
            write_tables.append(rng.choice(tabs["public"]))
    style = {"opener": rng.choice(OPENERS), "name": None, "role": None}
    if task_type == "5_proxy":
        style.update(name=f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}", role=rng.choice(ROLES))
    return {"task_type": task_type, "difficulty": difficulty, "shape": shape, "write_tables": write_tables,
            "events": refs, "tables": tabs, "example": rng.choice(load_examples()[task_type]),
            "scope": tabs["own"] + tabs["public"], "style": style}


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


def shape_text(anchor, plan):
    s, lines, tabs = plan["shape"], [], plan["tables"]
    lines.append(f"- Use exactly {s['n_writes']} write statement{'s' if s['n_writes'] > 1 else ''} (INSERT/UPDATE/DELETE) touching {s['n_tables']} distinct table{'s' if s['n_tables'] > 1 else ''}.")
    if s["ownership_subquery"]:
        lines.append(f"- Locate the rows to change through their owner with a subquery on {anchor['table']} (e.g. WHERE {anchor['key']} = (SELECT {anchor['key']} FROM {anchor['table']} WHERE ...)) instead of hard-coding the {anchor['key']}.")
    if s["archive"]:
        lines.append("- First copy the affected row(s) into another table in scope with INSERT ... SELECT, then change or delete the original row(s).")
    if s["public_table"]:
        lines.append(f"- At least one write must change a shared table: {', '.join(tabs['public'])}.")
    if plan["write_tables"]:
        lines.append(f"- Write to these tables: {', '.join(plan['write_tables'])}.")
    else:
        lines.append(f"- Choose freely which tables in scope to write ({', '.join(plan['scope'])}); prefer a combination that is not the obvious one.")
    lines.append(f"- Target difficulty: {plan['difficulty']}. Read-only questions (if any) go into 'outputs', not 'actions'.")
    return "\n".join(lines)


def style_text(plan):
    st = plan.get("style") or {}
    lines = [f"- Opening manner: {st.get('opener', 'natural, varied')}."]
    if st.get("name"):
        lines.append(f"- The speaker is {st['name']}, {st['role']}. Use exactly this name and role.")
    lines.append("- Vary wording; do not open with 'Hi, this is' or 'Good morning'. Do not use phrases from the example.")
    return "\n".join(lines)


def next_ids_block(plan, next_ids):
    """next_ids: schema.next_ids() output, {table: (pk_column, next value)}; only the tables the prompt shows."""
    items = [(t, *next_ids[t]) for t in plan["scope"] if t in (next_ids or {})]
    if not items:
        return ""
    return "\n## Next unused primary keys (use these for new rows)\n" + "\n".join(f"- {t}.{c} = {v}" for t, c, v in items) + "\n"


def build_messages(db_rec, anchor, tree, plan, db_description, schema_text, cfg=CFG, next_ids=None):
    tabs = plan["tables"]
    fmt = {"name": tree["anchor_name"] or f"the row with {anchor['key']} = {tree['key_value']}", "key": anchor["key"],
           "kv": tree["key_value"], "t": anchor["table"],
           "down": ", ".join(t for t in tabs["own"] if t != anchor["table"]) or "(none)",
           "up": ", ".join(tabs["public"]) or "(none)", "other_name": "", "other_kv": ""}
    user = USER.format(db_description=db_description, data_blocks=data_blocks(tree, plan["events"], _who(plan["task_type"]), cfg),
                       schema=schema_text, next_ids_block=next_ids_block(plan, next_ids),
                       type_text=TYPE_TEXT[plan["task_type"]].format(**fmt), shape_text=shape_text(anchor, plan),
                       style_text=style_text(plan),
                       id_fields=", ".join(anchor["names"] + [anchor["key"]]), max_rows=cfg["MAX_ROWS_PER_STMT"])
    system = SYSTEM.format(example_instruction=plan["example"], max_rows=cfg["MAX_ROWS_PER_STMT"])
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]
```

`generate.py`：

1. `make_candidate` 里，`"key_value": tree["key_value"], "anchor_name": tree["anchor_name"], "plan": plan,` 改成：
   ```python
               "key_value": tree["key_value"], "anchor_name": tree["anchor_name"], "profile_version": tree.get("profile_version"),
               "plan": plan,
   ```
2. `def run(db_rec, anchor, trees_list, others, client, ...` 去掉 `others, `。
3. 循环里那一行改成 `plan = prompt.sample_plan(rng, tree, anchor, cfg)`。

`io.py`：删掉 `def person_anchors(db_rec):` 和它的函数体。

`scripts/taskgen.py`：
1. `cmd_generate` 整个换成：

```python
def cmd_generate(a):
    rec, out = rec_and_dir(a)
    prof = profile_of(a)
    path = io.resolve_db_path(rec["path"])
    desc = json.load(open(DESC_PATH)).get(a.db, "") if os.path.exists(DESC_PATH) else ""
    if not desc:
        sys.exit("run `describe` first")
    client = llm.client_from_env("GEN")
    next_ids = schema.next_ids(path)
    all_trees = io.read_jsonl(f"{out}/trees.jsonl")
    if a.retry_errors:   # their check results are stale once the candidates are regenerated
        failed = {c["id"] for c in io.read_jsonl(f"{out}/candidates.jsonl")
                  if c.get("instruction") is None and (c.get("error") or "").startswith(("LLMError", "RuntimeError", "ConnectionError"))}
        chk = [r for r in io.read_jsonl(f"{out}/check.jsonl") if r["id"] not in failed]
        if os.path.exists(f"{out}/check.jsonl"):
            os.remove(f"{out}/check.jsonl")
        io.append_jsonl(f"{out}/check.jsonl", chk)
    t0, total = time.time(), {"written": 0, "errors": 0, "skipped": 0}
    for r in prof["roots"]:
        anchor = db_profile.root_anchor(prof, r["table"])
        ts = [t for t in all_trees if t["anchor_table"] == anchor["table"]]
        s = generate.run(rec, anchor, ts, client, f"{out}/candidates.jsonl",
                         random.Random(f"{a.seed}:{anchor['table']}"),   # per root: two roots must not draw the same plans
                         workers=a.workers, per_tree=a.per_tree, db_description=desc, schema_text=schema.schema_block(path),
                         retry_errors=a.retry_errors, next_ids=next_ids)
        total = {k: total[k] + s[k] for k in total}
    usage = sum((c.get("usage") or {}).get("total_tokens", 0) for c in io.read_jsonl(f"{out}/candidates.jsonl"))
    print(f"{total} in {time.time() - t0:.0f}s; total tokens so far {usage}")
```

2. `cmd_check` 里，在 `rec, out = rec_and_dir(a)` 后面加 `prof = profile_of(a)`，并把 `r = check.run_check_safe(rec, c)` 改成 `r = check.run_check_safe(rec, c, profile=prof)`。

- [ ] **Step 4: 跑测试**

```bash
cd $REPO/taskgen/v2
$P -m pytest -q tests/test_taskgen_prompt.py tests/test_taskgen_generate.py tests/test_taskgen_cli.py 2>&1 | tail -1
$P -m pytest -q 2>&1 | tail -1
grep -rn "person_anchors\|others" --include=*.py taskgen_v2 scripts | grep -v "the others\|random others"
```
Expected: `19 passed`；全套 `119 passed`。grep 没有输出：树模块 docstring 里的 "the others"、"random others" 已经排除。

- [ ] **Step 5: 提交**

```bash
cd $REPO
printf '%s\n' '| 出题读新树：按难度展示 3–5/5–8/8–12 条事件，数据块 ≤16000 字符，长文本截到 200 字符，每行注明归属；不出第 4 类；`generate`、`check` 命令读档案 | §4.2、§4.4、D6 |' >> taskgen/v2/README.md
git add taskgen/v2/taskgen_v2/prompt.py taskgen/v2/taskgen_v2/generate.py taskgen/v2/taskgen_v2/io.py taskgen/v2/scripts/taskgen.py \
        taskgen/v2/tests/test_taskgen_prompt.py taskgen/v2/tests/test_taskgen_generate.py taskgen/v2/tests/test_taskgen_cli.py taskgen/v2/README.md
git diff --cached --name-only
git commit -m "feat(taskgen v2): the prompt shows 3-12 events of the nested tree

The plan draws 3-5, 5-8 or 8-12 events by difficulty (a public-bearing one first for types 2
and 3), cuts events from the end while the data blocks exceed 16000 chars, and the blocks indent
parent rows under the row that references them, each tagged own / public / another person's.
Type 4 is no longer feasible (design D6). generate and check read the confirmed profile;
candidates record the profile version.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: GLM 起草档案；`profile` 命令（draft、check、render、confirm）

**Files:**
- Create: `taskgen/v2/taskgen_v2/profile_draft.py`
- Create: `taskgen/v2/taskgen_v2/profile_examples.json`：两份手写的 DySQL 示例，由下面 Step 3 的一次性脚本生成。
- Create: `taskgen/v2/data/profile_hints.json`：23 个库的根和已知怪异点。
- Modify: `taskgen/v2/taskgen_v2/io.py`：`json_candidates` 从 `generate.py` 挪过来，起草也要用。
- Modify: `taskgen/v2/taskgen_v2/generate.py`：改用 `io.json_candidates`，删掉用不到的 `re`。
- Modify: `taskgen/v2/scripts/taskgen.py`：新增 `draft_profiles`、`sample_trees`、`cmd_profile` 和 `profile` 子命令。
- Test: `taskgen/v2/tests/test_taskgen_profile_draft.py`、`taskgen/v2/tests/test_taskgen_cli.py`（追加一个测试）。

**Interfaces:**
- Consumes: `db_profile.validate`（Task 1）；`schema.pk_info`、`schema.column_descriptions`；`trees.root_key_values`、`trees.build_tree`（Task 4）；`prompt.data_blocks`（Task 5）；`llm.client_from_env("GEN")`。
- Produces:
  - 路径常量：`profile_draft.HINTS_JSON`、`EXAMPLES_PATH`。
  - 起草参数：`SAMPLE_ROWS = 3`、`REPAIR_ROUNDS = 2`、`DRAFT_TEMPERATURE = 0.3`。
  - 起草输入：
    - `compact_schema(conn, fks=(), composite=(), notes=None, samples=SAMPLE_ROWS) -> str`
    - `pragma_fks(conn) -> [fk]`
    - `load_examples(path)`
    - `messages(db_key, conn, rec, db_path, hints, description, examples)`
  - 起草：
    - `parse(text) -> dict`：没有档案 JSON 时抛 ValueError。
    - `draft(client, db_key, conn, rec, db_path, hints, description, examples) -> profile`：结果里 `confirmed=False`、`notes=[]`，`draft={"model", "rounds", "errors"}`。
  - `io.json_candidates(text)`
  - `taskgen.py profile draft|check|render|confirm`，参数有 `[--db K] [--profiles P] [--anchors A] [--hints H] [--redo] [--workers 5] [--out PAGE] [--trees-out FILE] [--sample-trees 1]`。
    - `check`：发现问题时退出码 1。
    - `confirm`：需要 `--db`；校验不过时退出码 1，不改动档案。

- [ ] **Step 1: 写会失败的测试**

`taskgen/v2/tests/test_taskgen_profile_draft.py`：

```python
# tests/test_taskgen_profile_draft.py
import glob, json, sqlite3
import pytest
from taskgen_common.paths import DYSQL_ENVS
from taskgen_common.testing import make_db
from v2_fixtures import SCHOOL, SCHOOL_FKS, SCHOOL_COMPOSITE, SCHOOL_PROFILE
from taskgen_v2 import db_profile, profile_draft

REC = {"source": "test", "db": "school", "anchors": [], "fks": SCHOOL_FKS, "fks_composite": SCHOOL_COMPOSITE}
HINTS = {"roots": ["Student List"], "notes": ["dept names are codes."]}


class FakeClient:
    def __init__(self, answers): self.answers, self.seen = list(answers), []
    def chat(self, messages, **kw):
        self.seen.append(messages)
        return {"content": self.answers.pop(0), "model": "fake"}


def answer(profile):
    return "<thought>t</thought><answer>" + json.dumps(profile) + "</answer>"


@pytest.fixture
def school(tmp_path):
    path = make_db(tmp_path, "school", SCHOOL)
    return sqlite3.connect(path), path


def test_compact_schema_shows_keys_references_and_rows(school):
    conn, _ = school
    text = profile_draft.compact_schema(conn, SCHOOL_FKS, SCHOOL_COMPOSITE)
    assert "TABLE Student List -- 10 rows; key sid (INTEGER; a new row may leave it out)" in text
    assert "TABLE section -- 3 rows; key (course, sec)" in text and "TABLE dept -- 2 rows; key dept_name (TEXT)" in text
    assert "  references: sid -> Student List.sid; (course, sec) -> section.(course, sec)" in text
    assert "  references: t_id -> teacher.tid" in text
    assert '  row: {"sid": 0, "name": "s0", "dept": "d0"}' in text
    assert "row:" not in profile_draft.compact_schema(conn, SCHOOL_FKS, SCHOOL_COMPOSITE, samples=0)


def test_messages_carry_examples_hints_and_schema(school):
    conn, path = school
    msgs = profile_draft.messages("test:school", conn, REC, path, HINTS, "A school.", profile_draft.load_examples())
    assert "### chinook (DySQL)" in msgs[0]["content"] and "### entertainment (DySQL)" in msgs[0]["content"]
    u = msgs[1]["content"]
    assert "# Database test:school\nA school." in u and "Roots: Student List\n- dept names are codes." in u
    assert "TABLE takes -- 16 rows; no primary key" in u


def test_examples_are_valid_profiles_of_their_dysql_databases():
    for x in profile_draft.load_examples():
        path = glob.glob(f"{DYSQL_ENVS}/{x['env']}/data/*.sqlite")[0]
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        fks = profile_draft.pragma_fks(conn)
        assert db_profile.validate(x["profile"], conn, fks) == [] and x["profile"]["confirmed"] is False
        assert x["schema"] == profile_draft.compact_schema(conn, fks, (), None, samples=0)


def test_draft_repairs_until_valid(school):
    conn, path = school
    first = {**SCHOOL_PROFILE, "public": ["section"]}                         # dept loses its role
    client = FakeClient([answer(first), answer(SCHOOL_PROFILE)])
    p = profile_draft.draft(client, "test:school", conn, REC, path, HINTS, "", profile_draft.load_examples())
    assert p["draft"] == {"model": "fake", "rounds": 2, "errors": []} and p["confirmed"] is False and p["notes"] == []
    assert {k: p[k] for k in ("roots", "events", "public")} == {k: SCHOOL_PROFILE[k] for k in ("roots", "events", "public")}
    repair = client.seen[1][-1]["content"]
    assert repair.startswith("The profile has these problems:\n- ") and "dept hangs under Student List but is not public" in repair


def test_draft_keeps_the_hinted_roots_and_gives_up_after_the_repairs(school):
    conn, path = school
    wrong = {**SCHOOL_PROFILE, "roots": SCHOOL_PROFILE["roots"] + [{"table": "teacher", "label": "teacher", "parents": []}]}
    client = FakeClient([answer(wrong), "no json here", answer(wrong)])
    p = profile_draft.draft(client, "test:school", conn, REC, path, HINTS, "", profile_draft.load_examples())
    assert p["draft"]["rounds"] == 3 and p["draft"]["errors"] == ["roots: must be exactly Student List, as the hints say"]
    assert "no profile JSON in the answer" in client.seen[2][-1]["content"]
```

`taskgen/v2/tests/test_taskgen_cli.py` 末尾追加：

```python
def test_profile_check_render_and_confirm(tmp_path):
    args = setup(tmp_path, confirmed=False)
    db, anchors, profiles = args[1], args[3], args[5]
    common = ["--anchors", anchors, "--profiles", profiles]
    r = run("profile", "check", *common)
    assert r.returncode == 0 and "test:shop2: ok, not confirmed" in r.stdout
    page, sample = tmp_path / "review.md", tmp_path / "trees.md"
    run("profile", "render", *common, "--out", str(page), "--trees-out", str(sample))
    assert "## test:shop2　未确认　校验通过" in page.read_text()
    assert sample.read_text().startswith("# test:shop2 · customers ") and "## orders: orders records" in sample.read_text()
    run("profile", "confirm", *common, "--db", db)
    assert db_profile.load(profiles)[db]["confirmed"] is True
    broken = {**SHOP_PROFILE, "public": [], "confirmed": False}                      # products hangs under orders, now without a role
    db_profile.save({db: broken}, profiles)
    r = run("profile", "check", *common, check=False)
    assert r.returncode == 1 and "products hangs under orders but is not public" in r.stdout
    r = run("profile", "confirm", *common, "--db", db, check=False)
    assert r.returncode == 1 and db_profile.load(profiles)[db]["confirmed"] is False
```

- [ ] **Step 2: 跑测试，确认失败**

```bash
cd $REPO/taskgen/v2
$P -m pytest -q tests/test_taskgen_profile_draft.py tests/test_taskgen_cli.py 2>&1 | tail -3
```
Expected: `test_taskgen_profile_draft.py` 在收集阶段报 `ImportError: cannot import name 'profile_draft'`；CLI 的新测试失败，子进程报 `invalid choice: 'profile'`。

- [ ] **Step 3: 实现**

`io.py`：
- 导入改成 `import json, os, re`。
- 把 `generate.py` 里的 `_json_candidates` 挪到 `io.py` 末尾，改名为 `json_candidates`，补一行 docstring：

```python
def json_candidates(text):
    """Strings that may hold the JSON object of a model answer, most likely first: the <answer> body, then {...} spans."""
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
```

`generate.py`：
- 删掉 `_json_candidates`。
- `parse_answer` 里改成 `for cand in io.json_candidates(text or ""):`。
- 导入改成 `import json, os`。

`taskgen/v2/taskgen_v2/profile_draft.py`：

```python
# taskgen/v2/taskgen_v2/profile_draft.py
"""The generation model drafts a database profile (design §4.1): it sees every table with its key, columns, foreign
keys, BIRD's column notes and a few rows, the reviewer's hints (the roots, known data quirks) and two hand-written
DySQL profiles. A draft that fails db_profile.validate goes back with the problems, at most REPAIR_ROUNDS times;
whatever is left is saved with the problems for the reviewer."""
import json, os
from taskgen_common.db_select import _q
from taskgen_v2 import db_profile, io, schema

HINTS_JSON = os.path.join(io.DATA, "profile_hints.json")
EXAMPLES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "profile_examples.json")
SAMPLE_ROWS, VALUE_CHARS, NOTE_CHARS = 3, 60, 150
DRAFT_TEMPERATURE, DRAFT_MAX_TOKENS, REPAIR_ROUNDS = 0.3, 16384, 2

SYSTEM = """You write the profile of a SQLite database for a task generator. The generator writes realistic requests in which one person asks a database agent to change data (their orders, bookings, records), so it needs to know who the people are, which records belong to them, and which rows those records point to.

## Fields
- roots: the people requests are about; use exactly the tables the hints name. [{{"table", "label", "parents"}}]
  label: a word or two for the person ("customer"). parents: rows the person's own row points to that help understand it (their department, their sales rep); same shape as an event's parents.
- persons: every table whose rows are people, the roots and anyone else (employees, drivers, agents): {{"<table>": {{"key", "name_cols", "same_as"}}}}.
  key: the column that identifies one person. name_cols: the columns holding the person's name. same_as: ["table.column", ...] for columns elsewhere that hold this person's key without a foreign key (usually []).
- events: the records that belong to a root person, one entry per way of reaching them: {{"table", "label", "path", "parents"}}.
  path: the foreign keys from the root table down to the event table, root side first, each written "child_table.column -> parent_table.column". The first one ends at a root table; each next one ends at the table the previous one starts from.
  A table appears twice when a person reaches it two ways (matches won, matches lost).
  parents: the rows an event row points to that a person needs to understand it (a purchase -> the product -> its brand; a shipment -> its truck, driver and city): [{{"table", "via", "parents"}}], via being the foreign key from the row above to this table. Nest one or two levels.
- attributes: one-to-one tables that only add facts about a person: [{{"table", "of", "via"}}], via going from the attribute table to the person table.
- public: reference tables that belong to nobody (products, brands, locations, categories, courses) and that a request may change. Never a table of people.
- exclude: tables requests must not touch: calendar or helper tables, tables of other people that the roots never reach, tables whose changes would make no sense.
- no_insert: tables that must not get new rows because their key has no meaningful next value (UUIDs, codes like 'rec4Xa0').
- quirks: short English sentences about data oddities the generator must respect (misspelled column names, swapped values).
- description: two or three English sentences: what the database records and who the people in it are.
- confirmed: false

## Rules
- Use table and column names exactly as the schema writes them (case, spaces, hyphens).
- Every table must appear somewhere: in roots, persons, events (as the table or on a path), parents, attributes, public or exclude.
- A composite foreign key is written "child.(a, b) -> parent.(x, y)".
- Use the foreign keys listed under "references", or columns whose values clearly hold another table's key.
- Answer with the profile as JSON inside <answer></answer>.

## Examples
{examples}"""

USER = """# Database {key}
{description}

## Hints from the person who will review the profile
Roots: {roots}
{notes}

## Schema
{schema}

Write the profile."""

REPAIR = """The profile has these problems:
{errors}
Answer with the whole corrected profile as JSON inside <answer></answer>."""


def _short(v):
    return v[:VALUE_CHARS] + "..." if isinstance(v, str) and len(v) > VALUE_CHARS else v


def compact_schema(conn, fks=(), composite=(), notes=None, samples=SAMPLE_ROWS):
    """Every table the way the drafting prompt shows it: rows, key and how new keys come about, columns with types,
    foreign keys, BIRD's column notes, a few rows."""
    pk, out = schema.pk_info(conn), []
    for t in sorted(pk, key=str.lower):
        cols = list(conn.execute(f"PRAGMA table_info({_q(t)})"))
        (n,) = conn.execute(f"SELECT COUNT(*) FROM {_q(t)}").fetchone()
        k = pk[t]
        if k["omittable"]:
            key = f"key {k['cols'][0]} (INTEGER; a new row may leave it out)"
        elif k["rowid_alias"]:
            key = f"key {k['cols'][0]} (INTEGER AUTOINCREMENT, sequence ahead of MAX; a new row needs an explicit id)"
        elif len(k["cols"]) == 1:
            key = f"key {k['cols'][0]} ({next(c[2] for c in cols if c[1] == k['cols'][0]) or 'no type'})"
        else:
            key = f"key ({', '.join(k['cols'])})" if k["cols"] else "no primary key"
        lines = [f"TABLE {t} -- {n} rows; {key}", "  columns: " + ", ".join(f"{c[1]} {c[2]}".strip() for c in cols)]
        refs = [f"{f['col']} -> {f['ref_table']}.{f['ref_col']}" + ("" if f.get("source") == "declared" else " (inferred)")
                for f in fks if f["table"] == t]
        refs += [f"({', '.join(f['cols'])}) -> {f['ref_table']}.({', '.join(f['ref_cols'])})" for f in composite if f["table"] == t]
        if refs:
            lines.append("  references: " + "; ".join(refs))
        if (notes or {}).get(t):
            lines.append("  notes: " + "; ".join(f"{c}: {d[:NOTE_CHARS]}" for c, d in notes[t].items()))
        for r in conn.execute(f"SELECT * FROM {_q(t)} LIMIT {samples}").fetchall() if samples else []:
            row = {c[1]: (f"<blob {len(v)} bytes>" if isinstance(v, (bytes, memoryview)) else _short(v)) for c, v in zip(cols, r)}
            lines.append("  row: " + json.dumps(row, ensure_ascii=False, default=str))
        out.append("\n".join(lines))
    return "\n".join(out)


def pragma_fks(conn):
    """The foreign keys a database declares, in the anchors JSON shape (single-column ones; DySQL's example databases
    have no anchors record)."""
    out = []
    for (t,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"):
        out += [{"table": t, "col": r[3], "ref_table": r[2], "ref_col": r[4], "source": "declared"}
                for r in conn.execute(f"PRAGMA foreign_key_list({_q(t)})")]
    return out


def load_examples(path=EXAMPLES_PATH):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _examples_text(examples):
    return "\n\n".join(f"### {x['db']}\nSchema:\n{x['schema']}\n\nProfile:\n{json.dumps(x['profile'], ensure_ascii=False, indent=1)}"
                       for x in examples)


def messages(db_key, conn, rec, db_path, hints, description, examples):
    notes = "\n".join(f"- {n}" for n in hints.get("notes") or []) or "(no notes)"
    user = USER.format(key=db_key, description=description or "", roots=", ".join(hints["roots"]), notes=notes,
                       schema=compact_schema(conn, rec["fks"], rec.get("fks_composite", ()), schema.column_descriptions(db_path)))
    return [{"role": "system", "content": SYSTEM.format(examples=_examples_text(examples))}, {"role": "user", "content": user}]


def parse(text):
    """The profile JSON object in a model answer; ValueError when there is none."""
    last = None
    for cand in io.json_candidates(text or ""):
        try:
            obj = json.loads(cand)
        except json.JSONDecodeError as e:
            last = e
            continue
        if isinstance(obj, dict) and "roots" in obj:
            return obj
    raise ValueError(f"no profile JSON in the answer: {last}")


def draft(client, db_key, conn, rec, db_path, hints, description, examples):
    """A profile draft with confirmed=false and a 'draft' record {model, rounds, errors}; errors is [] when it validates."""
    msgs = messages(db_key, conn, rec, db_path, hints, description, examples)
    prof, errs, rounds, model = None, [], 0, None
    for rounds in range(1, REPAIR_ROUNDS + 2):
        resp = client.chat(msgs, temperature=DRAFT_TEMPERATURE, max_tokens=DRAFT_MAX_TOKENS)
        model = resp.get("model")
        try:
            got = parse(resp["content"])
        except ValueError as e:
            errs = [str(e)]
        else:
            prof = {**got, "confirmed": False}
            errs = db_profile.validate(prof, conn, rec["fks"], rec.get("fks_composite", ()))
            roots = [r.get("table") for r in prof.get("roots") or [] if isinstance(r, dict)]
            if roots != list(hints["roots"]):
                errs.append(f"roots: must be exactly {', '.join(hints['roots'])}, as the hints say")
        if not errs:
            break
        msgs = msgs + [{"role": "assistant", "content": resp["content"]},
                       {"role": "user", "content": REPAIR.format(errors="\n".join(f"- {e}" for e in errs))}]
    return {**(prof or {}), "confirmed": False, "notes": [], "draft": {"model": model, "rounds": rounds, "errors": errs}}
```

`taskgen/v2/data/profile_hints.json`：

```json
{
 "bird:address": {
  "roots": [
   "congress"
  ],
  "notes": [
   "congress.first_name and congress.last_name are swapped in the data: first_name holds the surname ('Young', 'Don').",
   "The key column of congress is spelled cognress_rep_id.",
   "zip_congress is keyed by (zip_code, district)."
  ]
 },
 "bird:beer_factory": {
  "roots": [
   "customers"
  ],
  "notes": []
 },
 "bird:book_publishing_company": {
  "roots": [
   "authors"
  ],
  "notes": [
   "employee holds publisher staff, people who are not roots."
  ]
 },
 "bird:books": {
  "roots": [
   "customer"
  ],
  "notes": [
   "author is reference data about books for a customer, not a person who makes requests."
  ]
 },
 "bird:car_retails": {
  "roots": [
   "customers"
  ],
  "notes": [
   "customers are companies; contactFirstName and contactLastName name the person who speaks for the company.",
   "employees are the companies' sales representatives (customers.salesRepEmployeeNumber): other people."
  ]
 },
 "bird:food_inspection_2": {
  "roots": [
   "employee"
  ],
  "notes": [
   "employee are health inspectors; employee.supervisor refers to another employee."
  ]
 },
 "bird:legislator": {
  "roots": [
   "historical"
  ],
  "notes": [
   "historical-terms rows are the terms each historical legislator served (bioguide -> historical.bioguide_id): events, not separate people.",
   "current, current-terms and social-media describe current legislators, who are not rows of historical."
  ]
 },
 "bird:movie": {
  "roots": [
   "actor"
  ],
  "notes": [
   "characters links an actor to a movie: the actor's roles."
  ]
 },
 "bird:movies_4": {
  "roots": [
   "person"
  ],
  "notes": [
   "movie_cast and movie_crew are a person's credits."
  ]
 },
 "bird:olympics": {
  "roots": [
   "person"
  ],
  "notes": [
   "games_competitor is a person's entry in one Games; competitor_event hangs under it."
  ]
 },
 "bird:professional_basketball": {
  "roots": [
   "players"
  ],
  "notes": [
   "draft rows are draft picks; draft.playerID links a pick to players, so draft is an event of players, not a separate person.",
   "teams, players_teams and coaches use the composite key (tmID, year)."
  ]
 },
 "bird:regional_sales": {
  "roots": [
   "Customers"
  ],
  "notes": [
   "Table and column names contain spaces (\"Sales Orders\", \"Customer Names\")."
  ]
 },
 "bird:retail_complains": {
  "roots": [
   "client"
  ],
  "notes": []
 },
 "bird:shipping": {
  "roots": [
   "customer"
  ],
  "notes": [
   "driver holds people other than the roots; truck and city are reference data."
  ]
 },
 "bird:student_club": {
  "roots": [
   "member"
  ],
  "notes": [
   "Keys such as member_id and event_id are text codes like 'rec1x5zBFIqoOuPW8': there is no next value for new rows."
  ]
 },
 "bird:student_loan": {
  "roots": [
   "person"
  ],
  "notes": [
   "bool holds only 'neg' and 'pos': exclude it.",
   "Every table is keyed by the text name ('student123').",
   "disabled, filed_for_bankrupcy, male, unemployed, longest_absense_from_school and no_payment_due are one-to-one facts about a person."
  ]
 },
 "bird:superhero": {
  "roots": [
   "superhero"
  ],
  "notes": [
   "hero_attribute and hero_power are a hero's own rows."
  ]
 },
 "bird:synthea": {
  "roots": [
   "patients"
  ],
  "notes": [
   "patients.patient and encounters.ID are text UUIDs: there is no next value for new rows.",
   "The clinical tables reference both the patient and the encounter."
  ]
 },
 "spider1:college_2": {
  "roots": [
   "student",
   "instructor"
  ],
  "notes": [
   "Two roots: students and instructors.",
   "section, teaches and takes share the composite key (course_id, sec_id, semester, year).",
   "advisor links a student (s_ID) to an instructor (i_ID)."
  ]
 },
 "spider1:hr_1": {
  "roots": [
   "employees"
  ],
  "notes": [
   "Keys are DECIMAL, so new rows need an explicit id.",
   "employees.MANAGER_ID refers to another employee.",
   "Only 7 employees have job_history rows."
  ]
 },
 "spider2:IPL": {
  "roots": [
   "player"
  ],
  "notes": [
   "player_match is keyed by (match_id, player_id).",
   "ball_by_ball.striker, non_striker, bowler and wicket_taken.player_out hold player ids without a declared foreign key."
  ]
 },
 "spider2:WWE": {
  "roots": [
   "Wrestlers"
  ],
  "notes": [
   "Matches.winner_id and Matches.loser_id (TEXT) both hold Wrestlers.id.",
   "Wrestlers.name, Belts.name and the other name columns are UNIQUE.",
   "sqlite_sequence is ahead of MAX(id) in 8 tables, so new rows there need an explicit id."
  ]
 },
 "spider2:school_scheduling": {
  "roots": [
   "Students",
   "Staff"
  ],
  "notes": [
   "Two roots: students and staff.",
   "Faculty is the teaching profile of a Staff member (same StaffID).",
   "Student_Schedules are a student's class enrolments; Faculty_Classes, Faculty_Subjects and Faculty_Categories are a staff member's teaching records."
  ]
 }
}
```

`taskgen/v2/taskgen_v2/profile_examples.json` 用一次性脚本生成，脚本放在 `$S`，生成的 JSON 进 git。示例档案先拿 DySQL 自己的库校验，校验通过才写出：

```bash
cd $REPO/taskgen/v2 && cat > $S/make_profile_examples.py <<'EOF'
# writes taskgen_v2/profile_examples.json: two hand-written DySQL profiles and their schemas (run from taskgen/v2)
import glob, json, sqlite3, sys
sys.path[:0] = [".", "../common"]
from taskgen_common.paths import DYSQL_ENVS
from taskgen_v2 import db_profile, profile_draft

CHINOOK = {
 "roots": [
  {
   "table": "customers",
   "label": "customer",
   "parents": [
    {
     "table": "employees",
     "via": "customers.SupportRepId -> employees.EmployeeId",
     "parents": []
    }
   ]
  }
 ],
 "persons": {
  "customers": {
   "key": "CustomerId",
   "name_cols": [
    "FirstName",
    "LastName"
   ],
   "same_as": []
  },
  "employees": {
   "key": "EmployeeId",
   "name_cols": [
    "FirstName",
    "LastName"
   ],
   "same_as": []
  }
 },
 "events": [
  {
   "table": "invoices",
   "label": "invoices",
   "path": [
    "invoices.CustomerId -> customers.CustomerId"
   ],
   "parents": []
  },
  {
   "table": "invoice_items",
   "label": "invoice lines",
   "path": [
    "invoices.CustomerId -> customers.CustomerId",
    "invoice_items.InvoiceId -> invoices.InvoiceId"
   ],
   "parents": [
    {
     "table": "tracks",
     "via": "invoice_items.TrackId -> tracks.TrackId",
     "parents": [
      {
       "table": "albums",
       "via": "tracks.AlbumId -> albums.AlbumId",
       "parents": [
        {
         "table": "artists",
         "via": "albums.ArtistId -> artists.ArtistId",
         "parents": []
        }
       ]
      },
      {
       "table": "genres",
       "via": "tracks.GenreId -> genres.GenreId",
       "parents": []
      },
      {
       "table": "media_types",
       "via": "tracks.MediaTypeId -> media_types.MediaTypeId",
       "parents": []
      }
     ]
    }
   ]
  }
 ],
 "attributes": [],
 "public": [
  "tracks",
  "albums",
  "artists",
  "genres",
  "media_types",
  "playlists",
  "playlist_track"
 ],
 "exclude": [],
 "no_insert": [],
 "quirks": [],
 "description": "A digital music store: customers buy tracks, recorded on invoices with one line per track, and each customer has a support representative among the employees. Tracks belong to albums, artists, genres and playlists.",
 "confirmed": False
}
ENTERTAINMENT = {
 "roots": [
  {
   "table": "Entertainers",
   "label": "entertainer (an act)",
   "parents": []
  }
 ],
 "persons": {
  "Entertainers": {
   "key": "EntertainerID",
   "name_cols": [
    "EntStageName"
   ],
   "same_as": []
  },
  "Customers": {
   "key": "CustomerID",
   "name_cols": [
    "CustFirstName",
    "CustLastName"
   ],
   "same_as": []
  },
  "Agents": {
   "key": "AgentID",
   "name_cols": [
    "AgtFirstName",
    "AgtLastName"
   ],
   "same_as": []
  },
  "Members": {
   "key": "MemberID",
   "name_cols": [
    "MbrFirstName",
    "MbrLastName"
   ],
   "same_as": []
  }
 },
 "events": [
  {
   "table": "Engagements",
   "label": "bookings",
   "path": [
    "Engagements.EntertainerID -> Entertainers.EntertainerID"
   ],
   "parents": [
    {
     "table": "Customers",
     "via": "Engagements.CustomerID -> Customers.CustomerID",
     "parents": []
    },
    {
     "table": "Agents",
     "via": "Engagements.AgentID -> Agents.AgentID",
     "parents": []
    }
   ]
  },
  {
   "table": "Entertainer_Members",
   "label": "members",
   "path": [
    "Entertainer_Members.EntertainerID -> Entertainers.EntertainerID"
   ],
   "parents": [
    {
     "table": "Members",
     "via": "Entertainer_Members.MemberID -> Members.MemberID",
     "parents": []
    }
   ]
  },
  {
   "table": "Entertainer_Styles",
   "label": "styles",
   "path": [
    "Entertainer_Styles.EntertainerID -> Entertainers.EntertainerID"
   ],
   "parents": [
    {
     "table": "Musical_Styles",
     "via": "Entertainer_Styles.StyleID -> Musical_Styles.StyleID",
     "parents": []
    }
   ]
  }
 ],
 "attributes": [],
 "public": [
  "Musical_Styles"
 ],
 "exclude": [
  "Musical_Preferences",
  "ztblDays",
  "ztblMonths",
  "ztblSkipLabels",
  "ztblWeeks"
 ],
 "no_insert": [],
 "quirks": [
  "Entertainers are acts (bands, duos), not single people; EntStageName is the act's name."
 ],
 "description": "An entertainment agency: agents book entertainers (bands and solo acts) for customers' events. Each entertainer has members and musical styles; customers have style preferences.",
 "confirmed": False
}
out = []
for name, env, prof in [("chinook (DySQL)", "chinook", CHINOOK), ("entertainment (DySQL)", "entertainment", ENTERTAINMENT)]:
    path = glob.glob(f"{DYSQL_ENVS}/{env}/data/*.sqlite")[0]
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    fks = profile_draft.pragma_fks(conn)
    errs = db_profile.validate(prof, conn, fks)
    print(f"{name}: " + ("ok" if not errs else "; ".join(errs)))
    if errs:
        sys.exit(1)
    out.append({"db": name, "env": env, "schema": profile_draft.compact_schema(conn, fks, (), None, samples=0), "profile": prof})
with open(profile_draft.EXAMPLES_PATH, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
    f.write("\n")
EOF
$P $S/make_profile_examples.py
```
Expected: 打印 `chinook (DySQL): ok` 和 `entertainment (DySQL): ok`，写出 `taskgen_v2/profile_examples.json`。

`scripts/taskgen.py`：

1. 文件开头加 `from concurrent.futures import ThreadPoolExecutor, as_completed`；导入那行再加上 `profile_draft`。
2. 在 `def main():` 前面加：

```python
def draft_profiles(a):
    hints, recs = json.load(open(a.hints, encoding="utf-8")), io.load_db_recs(a.anchors)
    have = db_profile.load(a.profiles)
    todo = [k for k in ([a.db] if a.db else sorted(hints)) if a.redo or k not in have]
    desc = json.load(open(DESC_PATH, encoding="utf-8")) if os.path.exists(DESC_PATH) else {}
    client, examples = llm.client_from_env("GEN"), profile_draft.load_examples()

    def one(k):   # each thread opens its own connection
        rec = recs[k]
        path = io.resolve_db_path(rec["path"])
        try:
            return k, profile_draft.draft(client, k, trees.open_ro(path), rec, path, hints[k], desc.get(k, ""), examples), None
        except Exception as e:
            return k, None, f"{type(e).__name__}: {e}"
    with ThreadPoolExecutor(max_workers=max(1, a.workers)) as ex:
        for f in as_completed([ex.submit(one, k) for k in todo]):
            k, prof, err = f.result()
            if err:
                print(f"{k}: FAILED {err}")
                continue
            profiles = db_profile.load(a.profiles)   # saved after every database: an interrupted run keeps what it has
            profiles[k] = prof
            db_profile.save(profiles, a.profiles)
            print(f"{k}: {prof['draft']['rounds']} round(s), {len(prof['draft']['errors'])} problem(s) left")


def sample_trees(entries, recs, seed, n):
    """Prompt-style data blocks of n trees per root of every valid profile, for the reviewer (rows of the database,
    so the file stays out of git)."""
    parts = []
    for x in entries:
        if x["errors"]:
            continue
        rec, prof = recs[x["key"]], x["profile"]
        c = trees.open_ro(io.resolve_db_path(rec["path"]))
        tracer = owners.Tracer.from_profile(prof, rec, c)
        for r in prof["roots"]:
            rng = random.Random(f"{seed}:{r['table']}")
            for kv in trees.root_key_values(c, prof, r, rng, n):
                t = trees.build_tree(c, prof, r, kv, rng, tracer)
                refs = [[gi, j] for gi, g in enumerate(t["events"]) for j in range(len(g["rows"]))]
                parts.append(f"# {x['key']} · {r['table']} {kv}\n\n" + prompt.data_blocks(t, refs, "the speaker's own row"))
    return "\n\n".join(parts)


def cmd_profile(a):
    if a.action == "draft":
        return draft_profiles(a)
    profiles, recs = db_profile.load(a.profiles), io.load_db_recs(a.anchors)
    keys = [a.db] if a.db else sorted(profiles)
    missing = [k for k in keys if k not in profiles]
    if missing:
        sys.exit(f"no profile for {', '.join(missing)} in {a.profiles}")
    entries = []
    for k in keys:
        rec = recs[k]
        c = trees.open_ro(io.resolve_db_path(rec["path"]))
        entries.append({"key": k, "profile": profiles[k], "pk": schema.pk_info(c),
                        "errors": db_profile.validate(profiles[k], c, rec["fks"], rec.get("fks_composite", ()))})
    bad = [x["key"] for x in entries if x["errors"]]
    if a.action == "check":
        for x in entries:
            print(f"{x['key']}: " + (f"{len(x['errors'])} problems" if x["errors"] else "ok")
                  + (", confirmed" if x["profile"].get("confirmed") is True else ", not confirmed"))
            for e in x["errors"]:
                print(f"  - {e}")
        sys.exit(1 if bad else 0)
    if a.action == "render":
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(db_profile.render_md(entries) + "\n")
        print(f"wrote {a.out}: {len(entries)} profiles, {len(bad)} with problems")
        if a.trees_out:
            with open(a.trees_out, "w", encoding="utf-8") as f:
                f.write(sample_trees(entries, recs, a.seed, a.sample_trees) + "\n")
            print(f"wrote {a.trees_out}")
    if a.action == "confirm":
        if not a.db:
            sys.exit("confirm needs --db")
        if bad:
            sys.exit(f"{a.db} has problems; run `profile check --db {a.db}`")
        profiles[a.db]["confirmed"] = True
        db_profile.save(profiles, a.profiles)
        print(f"{a.db}: confirmed")
```

3. `main()` 里，在 `trees` 子命令那行前面加 `profile` 子命令：

```python
    p = sub.add_parser("profile"); p.add_argument("action", choices=["draft", "check", "render", "confirm"])
    p.add_argument("--db", help="one database (default: all in the hints for draft, all in the profiles file otherwise)")
    p.add_argument("--anchors", default=io.ANCHORS_JSON); p.add_argument("--profiles", default=db_profile.PROFILES_JSON)
    p.add_argument("--hints", default=profile_draft.HINTS_JSON); p.add_argument("--redo", action="store_true", help="draft again even if a profile exists")
    p.add_argument("--workers", type=int, default=5, help="GLM plan limit: 5 concurrent requests")
    p.add_argument("--out", help="render: the review page to write"); p.add_argument("--trees-out", help="render: sample trees for the reviewer (results/, not git)")
    p.add_argument("--sample-trees", type=int, default=1); p.add_argument("--seed", type=int, default=0); p.set_defaults(f=cmd_profile)
```

- [ ] **Step 4: 跑测试**

```bash
cd $REPO/taskgen/v2
$P -m pytest -q tests/test_taskgen_profile_draft.py tests/test_taskgen_cli.py tests/test_taskgen_generate.py 2>&1 | tail -1
$P -m pytest -q 2>&1 | tail -1
```
Expected: `16 passed`；全套 `125 passed`。

- [ ] **Step 5: 提交**

```bash
cd $REPO
printf '%s\n' '| 档案起草：`taskgen_v2/profile_draft.py`（GLM 看每表的键、列、外键、BIRD 列说明和 3 行样例，加 `data/profile_hints.json` 的根和已知怪异点、两份手写 DySQL 示例；校验不过带着问题重写，最多 2 次）；`profile draft/check/render/confirm` 命令 | §4.1、D1 |' >> taskgen/v2/README.md
git add taskgen/v2/taskgen_v2/profile_draft.py taskgen/v2/taskgen_v2/profile_examples.json taskgen/v2/data/profile_hints.json \
        taskgen/v2/taskgen_v2/io.py taskgen/v2/taskgen_v2/generate.py taskgen/v2/scripts/taskgen.py \
        taskgen/v2/tests/test_taskgen_profile_draft.py taskgen/v2/tests/test_taskgen_cli.py taskgen/v2/README.md
git diff --cached --name-only
git commit -m "feat(taskgen v2): GLM drafts database profiles; the profile command

profile_draft shows the model every table (key and how new keys come about, columns, foreign
keys, BIRD column notes, three rows), the reviewer's hints (roots from design 4.1, known data
quirks) and two hand-written DySQL profiles; a draft that fails validation or changes the roots
goes back with the problems, at most twice. profile draft|check|render|confirm drive the review;
render can also write sample trees for the reviewer to results/.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: 起草 23 份档案，Claude 预审，交你确认

**Files:**
- Create: `taskgen/v2/data/db_profiles.json`（23 份档案）
- Create: `taskgen/v2/docs/<执行当天>-db-profiles-review.md`（审阅页）
- 本地，不进 git：`taskgen/v2/results/profile_review/sample_trees.md`（每个根一棵样例树）

**Interfaces:**
- Consumes: Task 6 的 `profile` 命令；`.env` 的 `TASKGEN_GEN_*`。
- Produces: 23 份通过校验、`confirmed: true` 的档案，Task 8 和以后的计划都要用。

- [ ] **Step 1: 起草**

```bash
cd $REPO/taskgen/v2
grep -E '^TASKGEN_GEN_(BASE_URL|MODEL)=' $REPO/.env
$P scripts/taskgen.py profile draft --workers 5 2>&1 | tee $S/draft.log
```
Expected:
- 模型是 `glm-5.3`。
- 23 行 `<db>: <n> round(s), <k> problem(s) left`，没有 `FAILED`，大约 5–10 分钟（原型里每库 16–111 秒）。
- 如果有 `FAILED`（429 之类），对那个库重跑 `profile draft --db <db>`；已有档案的库会跳过。

- [ ] **Step 2: 校验**

```bash
$P scripts/taskgen.py profile check 2>&1 | tee $S/check0.log | grep -v "^  - " ; echo "exit=${PIPESTATUS[0]}"
```
Expected: 23 行。起草时没改掉的问题会列在 `  - ` 开头的行里，留到 Step 3 修。

- [ ] **Step 3: Claude 预审**

逐库对照库本身（`sqlite3` 只读打开）和提示，直接改 `data/db_profiles.json`。每处改动都在该库的 `notes` 里记一句英文，格式是 `Claude: <改了什么> -- <为什么>`。检查清单：

1. 根和提示一致；`persons` 列出了库里所有存人的表（员工、司机、代理人、在任议员……），`public` 里不能有人物表。
2. `events` 覆盖根能沿外键走到的、属于这个人的记录，包括两跳的（books 的 order_line、olympics 的 competitor_event）。同一张表有两种走法时分两条（WWE 的胜场和负场）。
3. 父行挂的是看懂一条事件需要的东西（交易 → 商品 → 品牌；运单 → 卡车、司机、城市），一般一两层，不要把整张大表挂上去。
4. `public` 是可以改的参考数据；`exclude` 是辅助表、根走不到的别人的数据、改了没有意义的表；`no_insert` 是没有"下一个"值的文本主键表（synthea、student_club、legislator 的 bioguide 这类）。审阅页里的主键分类可以帮着判断。
5. `quirks` 里的每一条事实都用 SQL 查一遍。查不实的删掉；说法不准的改准；对写 SQL 没用的删掉。
   - 例子：原型里 GLM 把 BIRD 列说明里的一句"model_year 越早的卡车越新"抄成了怪异点。它来自说明，不来自数据，对写 SQL 也没用，这种要删。
   - 提示里的怪异点，凡是影响写 SQL 的都要留下：名姓存反、列名拼错、名字列 UNIQUE。
6. `description` 和库的实际内容相符。

改完跑 `profile check`，直到 23 个都是 `ok`：

```bash
$P scripts/taskgen.py profile check | grep -c ": ok, not confirmed"
```
Expected: `23`。

- [ ] **Step 4: 生成审阅页和样例树**

```bash
D=$(date +%F); mkdir -p results/profile_review
$P scripts/taskgen.py profile render --out docs/${D}-db-profiles-review.md --trees-out results/profile_review/sample_trees.md
```
Expected: `wrote docs/<D>-db-profiles-review.md: 23 profiles, 0 with problems` 和 `wrote results/profile_review/sample_trees.md`。打开样例树翻几棵，看标签和嵌套是否合理；不合理就回到 Step 3。

在审阅页开头（第一个 `## ` 之前）加一段中文说明：
- 怎么看这张表；
- 样例树在哪（本地文件）；
- 拿不准、需要用户判断的点，每条一句，例如 books 的 author 算公共还是人、legislator 的 current 系列表算人还是排除。

- [ ] **Step 5: 提交草稿**

```bash
cd $REPO
git add taskgen/v2/data/db_profiles.json taskgen/v2/docs/${D}-db-profiles-review.md
git diff --cached --name-only
git commit -m "data(taskgen v2): profile drafts of the 23 databases and their review page

Drafted by GLM-5.3 from the hints and two DySQL examples, then reviewed by Claude against the
databases (every quirk checked with a query; changes noted in each profile's notes). Not
confirmed yet.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
Expected: 只有这两个文件。

- [ ] **Step 6: 停下来，请用户审阅**

这是本计划唯一需要停下来等用户的地方。给用户的消息要包括：
- 审阅页的链接和样例树文件的位置。
- Claude 预审改了多少处，按库各列一句。
- 需要用户判断的点：和审阅页开头那段一致，每条一句，并给出建议。
- 怎么回复：直接说要改什么，或者说"都可以"，也可以逐库确认。

收到回复前不要往下做。

- [ ] **Step 7: 按用户的意见改，逐库确认**

```bash
cd $REPO/taskgen/v2
# 按用户的意见改 data/db_profiles.json，改动记进 notes：User: <what>
$P scripts/taskgen.py profile check
for DB in <用户确认过的库>; do $P scripts/taskgen.py profile confirm --db $DB; done
$P scripts/taskgen.py profile render --out docs/${D}-db-profiles-review.md
$P scripts/taskgen.py profile check | grep -c ", confirmed"
```
Expected: 最后一条输出 `23`。用户分批确认的话，这一步可以重复多次；Task 8 要等 23 个都确认之后才开始。

```bash
cd $REPO
git add taskgen/v2/data/db_profiles.json taskgen/v2/docs/${D}-db-profiles-review.md
git diff --cached --name-only
git commit -m "data(taskgen v2): confirm the 23 database profiles

Confirmed by the user after review; their changes are noted in each profile's notes.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: 验证与收尾

**Files:**
- Create: `taskgen/v2/docs/<D>-check-with-profiles.md`：`check_diff.py --profiles` 生成的报告，末尾手写结论。
- Create: `taskgen/v2/docs/<D>-profiles-and-trees.md`：本 Task 的验证记录。
- Modify: `taskgen/v2/docs/2026-10-01-taskgen-v2-design.md`：把"本计划新定的事"写回去，并修计划 1 复核时留下的文档问题。
- Modify: `taskgen/v2/README.md`：改动记录一行。
- 本地，不进 git：`taskgen/v2/results/plan2/`（23 库的树、4 库冒烟出的题）。

**Interfaces:**
- Consumes: 23 份已确认的档案（Task 7）；Task 4–6 的命令。
- Produces: 设计 §5 阶段 B、C 的完成证据，以及给计划 3 用的树统计。

- [ ] **Step 1: 23 个库建树，统计**

```bash
cd $REPO/taskgen/v2
for DB in $($P -c "import json; print(' '.join(json.load(open('data/db_profiles.json'))))"); do
  $P scripts/taskgen.py trees --db $DB --n 200 --seed 0 --out-dir results/plan2/trees/${DB#*:} || echo "FAILED $DB"
done 2>&1 | tee $S/trees.log | grep -c FAILED
cat > $S/tree_stats.py <<'EOF'
# per database: trees, share with events / with public rows, events kept per tree, data-block chars (all events; 12 shown)
import glob, os, random, statistics as st, sys
sys.path[:0] = [".", "../common"]
from taskgen_v2 import io, prompt, trees


def q(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p * len(xs)))] if xs else 0


print("| 库 | 树 | 有事件 | 有公共行 | 每树存的事件（均值） | 全部事件的字符数 均值 / p90 | 展示 12 条的字符数 均值 / p90 |")
print("|---|---|---|---|---|---|---|")
for f in sorted(glob.glob("results/plan2/trees/*/trees.jsonl")):
    ts = io.read_jsonl(f)
    n_ev = [sum(len(g["rows"]) for g in t["events"]) for t in ts]
    full = [len(prompt.data_blocks(t, [[gi, j] for gi, g in enumerate(t["events"]) for j in range(len(g["rows"]))], "x")) for t in ts]
    twelve = [len(prompt.data_blocks(t, trees.pick_events(t, random.Random(0), 12), "x")) for t in ts]
    print(f"| {os.path.basename(os.path.dirname(f))} | {len(ts)} | {sum(x > 0 for x in n_ev) / len(ts):.0%} | "
          f"{sum(trees.has_public(t) for t in ts) / len(ts):.0%} | {st.mean(n_ev):.1f} | "
          f"{st.mean(full):.0f} / {q(full, .9)} | {st.mean(twelve):.0f} / {q(twelve, .9)} |")
EOF
$P $S/tree_stats.py | tee $S/tree_stats.md
```
Expected:
- 第一段输出 `0`，没有库失败。
- 统计表 23 行。根行有事件的库，"有事件" 一列接近 100%。
- hr_1 有 107 棵树：先 7 棵有事件的，再 100 棵没有事件的。
- 其他行数不到 200 的库：food_inspection_2 75 棵，book_publishing_company 23 棵，student_club 33 棵，school_scheduling 46 棵（Students 19 + Staff 27），regional_sales 50 棵，car_retails 122 棵，shipping 100 棵。
- 其余库都是 200 棵；college_2 是 student 150 + instructor 50。
- "展示 12 条时字符数" 一列的 p90 不超过 16000 左右。超出的库，出题时会自动少展示几条，记进报告即可。

- [ ] **Step 2: 拿 beer_factory 的一棵树和库逐行核对**

核对脚本用手写 SQL，不复用建树代码：

```bash
cat > $S/verify_beer_tree.py <<'EOF'
# the first beer_factory tree against the database, with hand-written SQL (none of the tree builder's code)
import sqlite3, sys
sys.path[:0] = [".", "../common"]
from taskgen_v2 import io

rec = io.load_db_recs()["bird:beer_factory"]
c = sqlite3.connect(f"file:{io.resolve_db_path(rec['path'])}?mode=ro", uri=True)
t = io.read_jsonl("results/plan2/trees/beer_factory/trees.jsonl")[0]
cid, problems = t["key_value"], []


def one(sql, *args):
    return c.execute(sql, args).fetchone()


if one("SELECT First, Last FROM customers WHERE CustomerID = ?", cid) != (t["anchor_row"]["First"], t["anchor_row"]["Last"]):
    problems.append("root row")
groups = {g["table"]: g for g in t["events"]}
tx = groups["transaction"]
n = one('SELECT COUNT(*) FROM "transaction" WHERE CustomerID = ?', cid)[0]
if tx["count"] != n:
    problems.append(f"transaction count {tx['count']} != {n}")
for node in tx["rows"]:
    r = node["row"]
    if r["CustomerID"] != cid or node["label"] != "own":
        problems.append(f"transaction {r['TransactionID']}: owner or label")
    par = {p["table"]: p for p in node["parents"]}
    rb = par.get("rootbeer")
    if rb:
        (brand_id,) = one("SELECT BrandID FROM rootbeer WHERE RootBeerID = ?", r["RootBeerID"])
        if rb["row"]["RootBeerID"] != r["RootBeerID"] or rb["label"] != "public":
            problems.append(f"transaction {r['TransactionID']}: rootbeer")
        br = {p["table"]: p for p in rb["parents"]}.get("rootbeerbrand")
        if br and (br["row"]["BrandID"] != brand_id or br["label"] != "public"):
            problems.append(f"transaction {r['TransactionID']}: brand")
    loc = par.get("location")
    if loc and (loc["row"]["LocationID"] != r["LocationID"] or loc["label"] != "public"):
        problems.append(f"transaction {r['TransactionID']}: location")
rv = groups.get("rootbeerreview")
if rv:
    (m,) = one("SELECT COUNT(*) FROM rootbeerreview WHERE CustomerID = ?", cid)
    if rv["count"] != m or any(x["row"]["CustomerID"] != cid or x["label"] != "own" for x in rv["rows"]):
        problems.append("reviews")
print(f"customer {cid} {t['anchor_name']}: transactions {n}, shown {len(tx['rows'])}; problems: {problems}")
EOF
$P $S/verify_beer_tree.py
```
Expected:
- 打印这棵树的客户、交易数、展示数，以及 `problems: []`。
- 如果档案里 transaction 的父行和脚本假定的（rootbeer → rootbeerbrand、location）不一样，按档案改脚本里的表名，并在 ledger 里记一条 ruling。

然后用 `prompt.data_blocks` 把这棵树渲染出来，读一遍，确认嵌套和标签读起来合理：

```bash
$P -c "
import random, sys; sys.path[:0] = ['.', '../common']
from taskgen_v2 import io, prompt, trees
t = io.read_jsonl('results/plan2/trees/beer_factory/trees.jsonl')[0]
print(prompt.data_blocks(t, trees.pick_events(t, random.Random(0), 5), \"the speaker's own row\"))" | head -40
```

- [ ] **Step 3: 4 个库各出 25 棵树的题，冒烟**

库的选法：
- college_2：双根，v1 时人物表混在 up 里。
- shipping：父行里有别的人（司机）。
- movie：v1 在这里"要求本人、算出本人+公共"最多。
- WWE：TEXT 外键，又有整页 HTML。

```bash
cd $REPO/taskgen/v2
for DB in spider1:college_2 bird:shipping bird:movie spider2:WWE; do
  OUT=results/plan2/smoke/${DB#*:}
  $P scripts/taskgen.py trees    --db $DB --n 25 --seed 1 --out-dir $OUT
  $P scripts/taskgen.py generate --db $DB --workers 5 --out-dir $OUT
  $P scripts/taskgen.py generate --db $DB --workers 5 --out-dir $OUT --retry-errors
  $P scripts/taskgen.py check    --db $DB --out-dir $OUT
done 2>&1 | tee $S/smoke.log | grep -E "trees written|checked"
cat > $S/smoke_stats.py <<'EOF'
# per smoke database: candidates, failed calls, check passes, reasons, requested != computed type, prompt tokens
import glob, os, statistics as st, sys
from collections import Counter
sys.path[:0] = [".", "../common"]
from taskgen_v2 import io


def q(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p * len(xs)))] if xs else 0


print("| 库 | 候选 | 解析/API 失败 | 过检查 | 拒绝原因 | 要求≠算出 | prompt token 均值 / p90 |")
print("|---|---|---|---|---|---|---|")
mism = []
for d in sorted(glob.glob("results/plan2/smoke/*")):
    cands = io.read_jsonl(f"{d}/candidates.jsonl")
    chk = {r["id"]: r for r in io.read_jsonl(f"{d}/check.jsonl")}
    ok = [c for c in cands if chk.get(c["id"], {}).get("ok")]
    reasons = Counter(x.split(":")[0] for r in chk.values() for x in r["reasons"])
    bad = [(c["id"], c["plan"]["task_type"], chk[c["id"]]["task_type"]) for c in ok if c["plan"]["task_type"] != chk[c["id"]]["task_type"]]
    mism += bad
    tok = [c["usage"]["prompt_tokens"] for c in cands if (c.get("usage") or {}).get("prompt_tokens")]
    print(f"| {os.path.basename(d)} | {len(cands)} | {sum(c['instruction'] is None for c in cands)} | {len(ok)} | "
          f"{', '.join(f'{k} {v}' for k, v in reasons.most_common()) or '-'} | {len(bad)} / {len(ok)} | "
          + (f"{st.mean(tok):.0f} / {q(tok, .9)} |" if tok else "- |"))
print()
for m in mism:
    print("mismatch:", *m)
EOF
$P $S/smoke_stats.py | tee $S/smoke_stats.md
```
Expected:
- 每个库约 25 条候选，总共约 100 条，GLM 大约 10–15 分钟。
- 解析失败和 API 失败合计 ≤2%。
- 过了检查的候选里没有第 4 类：被 `other_person` 拒掉的单独计数。
- 要求类型 ≠ 算出类型的比例目标是 ≤3%。每一条不一致都要归类：
  - **(a) 标签不一致：** prompt 里标 own/public 的行，写进去算出的不是 own/public。这一类必须是 0，因为两边用同一个 `owners.Tracer`。如果出现，是 bug，按 systematic-debugging 查到原因、补测试、修好。
  - **(b) 模型没按类型写：** 要求本人，却又改了公共表之类。计入比例，留给计划 3 改 prompt。
- prompt token 的均值和 p90 写进报告（原型约 5–7.5k）。

- [ ] **Step 4: 带档案和不带档案的检查，在 v1 候选上对比**

```bash
cd $REPO/taskgen/v2
$P scripts/check_diff.py --profiles data/db_profiles.json --out docs/${D}-check-with-profiles.md | head -30
```
Expected:
- 报告只比较说话人是档案根的候选：v1 的 4159 条去掉 6 个副锚点上的 669 条，大约 3490 条。
- 每一组判决变化都能归到 `other_person`、`out_of_scope`（档案排除的表，如 student_loan 的 `bool`）或 `no_insert`（synthea、student_club 等文本主键表）。归不进去的逐条查明。
- 在报告末尾手写一段"## 结论"：各原因的条数，每类举几个候选 id，不摘录题目内容；再写这些变化对产量意味着什么。

- [ ] **Step 5: 写验证记录 `docs/${D}-profiles-and-trees.md`**

中文，内容如下：
1. 档案：起草轮数分布、Claude 预审改了多少处、用户改了什么、23 份都已确认。
2. 建树：Step 1 的统计表，从 `$S/tree_stats.md` 粘过来，表里只有计数，没有数据行；再加两三句观察。
3. beer_factory 核对：哪棵树（客户 id）、核对了什么、结果。
4. 冒烟：Step 3 的表和不一致归类，只列候选 id。
5. 检查对比：引用 `docs/${D}-check-with-profiles.md` 的结论。
6. 给计划 3 的输入：(b) 类不一致的样子、prompt token 的分布、需要截断的库。

- [ ] **Step 6: 设计文档写回**

```bash
cd $REPO/taskgen/v2 && cat > $S/edit_design.py <<'EOF'
# writes plan 2's rules back into the design and fixes the stale numbers the plan-1 review found (run from taskgen/v2)
import re

PATH = "docs/2026-10-01-taskgen-v2-design.md"
EDITS = [
    ("计划 1（阶段 A、G、E）见 `2026-10-01-taskgen-v2-plan-1.md`；档案、建树、出题、校验和运行的计划在前一份完成后再写",
     "计划 1（阶段 A、G、E）见 `2026-10-01-taskgen-v2-plan-1.md`，计划 2（阶段 B、C，执行检查读档案）见 "
     "`2026-10-01-taskgen-v2-plan-2.md`；出题、校验和运行的计划在前一份完成后再写"),
    ("类型只抽 1、2、3、5。备注见 §4.8 |",
     "类型只抽 1、2、3、5；用档案检查时，算出第 4 类的候选拒掉（`other_person`）。备注见 §4.8 |"),
    ("38 条写入是新插入的人物行被算成", "8 条写入（6 题）是新插入的人物行被算成"),
    ("DySQL 70% 前 25 词内给 ID，子查询 6%；v1 28% / 45%",
     "DySQL 92.4% 前 25 词内给 ID、邮箱、SSN 或 #编号（`metrics.ID_RE`），语句含子查询 5.9%；v1 36.9% / 44.6%（§3）"),
    ("38 / 47 / 14.5 / 0 / 0，均值 1.76", "38 / 47 / 14.4 / 0 / 0，均值 1.76"),
    ("v1 是 38/47/14.5/0/0", "v1 是 38/47/14.4/0/0"),
    ("- 说话人介绍含 ID/邮箱的比例约 70%；", "- 说话人介绍含 ID/邮箱的比例按 §3 的目标（前 25 词内 ≥80%）；"),
    (re.compile(r"^roots: \[\{table, key, name_cols, label\}\].*$", re.M),
     "roots: [{table, label, parents}]                        主实体，默认一个；身份键和姓名列只写在 persons 里，\n"
     "                                                         parents 和事件的一样，挂根行引用的行（销售代表、院系）"),
    ("confirmed: false → 人工过后改 true\n```",
     "confirmed: false → 人工过后改 true\n"
     "notes, draft: 审阅用（Claude 的改动；起草模型、轮数、没改掉的问题），不计入版本号\n```\n\n"
     "边写成 `child.col -> parent.col`，复合外键写成 `child.(a, b) -> parent.(x, y)`；不在已知外键里的边，要有 ≥30% 的子行能在父表里找到。"
     "每张表都要有角色（roots、persons、events 及其路径、parents、attributes、public、exclude 之一），漏了算错。\n"),
    ("**流程：** `profile --db X` 起草 → `render_profiles_md` 生成一张表 → 人工改 JSON → `confirmed: true`。未确认的库，`trees` 拒绝运行。",
     "**流程：** `taskgen.py profile draft` 起草（GLM；输入另有 `data/profile_hints.json` 里每库的根和已知怪异点、"
     "`taskgen_v2/profile_examples.json` 里两份手写的 DySQL 示例；校验不过或根和提示不一致，就带着问题重写，最多 2 次）"
     "→ Claude 预审（怪异点逐条查库核实，改动记进 notes）→ `profile render` 生成审阅页（样例树另写到 `results/`）"
     "→ 人工改 → `profile confirm`（校验不过不让确认）。未确认的库，`trees`、`generate`、`check` 拒绝运行。"),
    ("student_loan person（exclude bool 和 flag 表）", "student_loan person（exclude bool；flag 表算属性表，计划 2 定）"),
    ("- 出题时从树里抽 3–12 条事件（与难度挂钩），控制在约 6k token。",
     "- 根行先抽有事件的，不够再抽没有事件的（hr_1 的 107 个员工里只有 7 个有 job_history）；双根库按各自可用的行数分 `--n`，"
     "一个根不够就让给另一个。\n"
     "- 出题时按难度抽 3–5 / 5–8 / 8–12 条事件，数据块超过 16000 字符就从后往前减；第 2、3 类先放一条带公共父行的事件。"
     "超过 200 字符的文本值截断（WWE 的 Cards 存整页 HTML）。\n"
     "- 标签由 `owners.Tracer` 算，执行检查用同一份代码：prompt 里标 own、public 的行，写进去算出来也是 own、public。"),
    ("往 `no_insert` 的表 INSERT 算拒绝（要档案，计划 2）。",
     "这个值在每条 INSERT 执行前按 SQLite 的规则现算（MAX 和 `sqlite_sequence` 取大者加一），前面的语句删掉最大行时也对。"
     "往 `no_insert` 的表 INSERT 拒绝（`no_insert`）。"),
    ("- 范围 = 档案里出现的表（roots、persons、events 及其 parents、attributes、public）的并集，减去 `exclude`；归属追溯用档案 `persons` 和 `same_as`。",
     "- 带档案时：范围 = 档案里有角色的表减去 `exclude`；归属追溯用档案的 `persons`、档案里的边和 `same_as`，"
     "加上已记录的外键（含复合外键），代码在 `owners.py`，建树打标签用同一份；算出第 4 类的候选拒掉（`other_person`，D6）。"
     "不带档案时（DySQL 金标准、v1 候选）照 v1。"),
    ("库外说话人（第 5 类）登记新的人，仍算 `person_obj`，不变。",
     "库外说话人（第 5 类）登记新的人，仍算 `person_obj`，不变。INSERT OR REPLACE / UPSERT 覆盖已有的人物行不算新人"
     "（看执行前这个主键是否已存在）。"),
]
text = open(PATH, encoding="utf-8").read()
for old, new in EDITS:
    hits = len(old.findall(text)) if isinstance(old, re.Pattern) else text.count(old)
    assert hits == 1, (hits, old)
    text = old.sub(new, text) if isinstance(old, re.Pattern) else text.replace(old, new)
open(PATH, "w", encoding="utf-8").write(text)
print(f"{len(EDITS)} edits applied")
EOF
$P $S/edit_design.py && git -C $REPO diff --stat -- taskgen/v2/docs/2026-10-01-taskgen-v2-design.md
```
Expected: 打印 `15 edits applied`，`diff --stat` 只显示设计文档一个文件。

- [ ] **Step 7: 测试、README、提交**

```bash
cd $REPO/taskgen/v2 && $P -m pytest -q 2>&1 | tail -1
cd $REPO
printf '%s\n' '| 验证：23 库按档案建树统计、beer_factory 一棵树逐行核对、4 库冒烟（类型一致）、带档案的检查在 v1 候选上对比（`docs/'"${D}"'-check-with-profiles.md`）；设计文档写回计划 2 的规则 | §5 B、C |' >> taskgen/v2/README.md
git add taskgen/v2/docs/${D}-check-with-profiles.md taskgen/v2/docs/${D}-profiles-and-trees.md \
        taskgen/v2/docs/2026-10-01-taskgen-v2-design.md taskgen/v2/README.md
git diff --cached --name-only
git commit -m "docs(taskgen v2): plan 2 validation and design write-back

Trees of the 23 databases from the confirmed profiles, one beer_factory tree checked row by row
against the database, a 100-candidate smoke run on four databases (requested vs computed type),
and the check with and without profiles on v1's candidates. The design takes over this plan's
rules (other_person, roots with events first, profile format, events shown) and drops the stale
numbers the plan-1 review found.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
Expected: 测试 `125 passed`；暂存区只有上面 4 个文件。

- [ ] **Step 8: memory**

- `research-plan-grpo-text2sql.md`：在计划 1 那段后面加一句：计划 2 完成，写上日期、commit 范围、冒烟的类型一致率、下一步是计划 3（出题 prompt）。
- `taskgen-v2-plan1-followups.md`：标出已在计划 2 修掉的条目（REPLACE/UPSERT、自动主键现算、Ctrl-C、文档数字、`_MDY`、大小写测试），剩下的写明归哪个计划。

