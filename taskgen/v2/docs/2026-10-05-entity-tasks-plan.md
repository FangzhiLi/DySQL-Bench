# 实体题实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用没有人物表的候选库出约 300 道 `6_entity` 训练题，题型接近 DySQL 的 car/cookbook，并且不带它们的毛病。

**Architecture:** 实体当根，复用 v2 流水线。profile 加 `kind: "entity"`，根表填在原来放人物的位置（`roots` 和 `persons`），所以建树、归属标签、检查的追溯算法都不变。新增的部分有：
- prompt 的 `6_entity` 类型，以及三种说话人的抽样；
- "新查找行"形状；
- 检查里实体类的拒绝规则，包括名字和 ID 对不上；
- 校验模型的实体说明；
- 树里"已用的键值"，这一项对所有库生效。

**Tech Stack:** Python 3（`~/miniconda3/envs/dysql/bin/python`）、SQLite、pytest；GLM-5.3 出题（并发 ≤5），ollama `deepseek-v4.1-flash` 校验（并发 ≤3），GB10 上的 Qwen3-4B 和 Qwen2.5-72B 跑 agent 关卡。

**Spec:** `taskgen/v2/docs/2026-10-04-entity-tasks-design.md`（用户 2026-10-05 通过）。执行者两份都要读。

## Global Constraints

- 分支 `isa/data-gen`，在主工作区做，不开 worktree。
- 命令都在 `taskgen/v2/` 下跑：`P=~/miniconda3/envs/dysql/bin/python`，`REPO=/home/wmd3i/Documents/Isa/DySQL-Bench`，`S=` 本会话的 scratchpad。测试用 `cd $REPO/taskgen/v2 && $P -m pytest -q`，开工前是 194 passed。
- 不提交 `results/`、`output/`，也不把任何题目文本写进 git；记录文档只写计数和 id。
- 每次提交，信息末尾加上会话 system reminder 给出的 Co-Authored-By 行。
- 23 个人物库：已确认 profile 的 `version` 不能变，现有候选重跑检查的结果必须逐条相同（Task 4 Step 7 验证）。
- 题量和配比：
  - 目标约 **300** 题。
  - 候选共约 400 个，每库 ⌈400/N⌉ 个，最终每库封顶 ⌈300/N⌉ 题（N 是用户确认留下的库数；16 个库时是 25 和 19）。合计不足 270 题时，按 Task 10 Step 6 补出。
  - 说话人：`SPEAKER_MIX` 是 name 0.55 / role_or_username 0.17 / none 0.28；`NAME_WITH_ROLE` 0.5；`USERNAME` 0.5。
  - `NEW_LOOKUP` 0.10。
- GLM `--workers 5`，ollama `--workers 3`。校验沿用全量的做法：三票多数，前两票一致即停（`verify.DEFAULT_VOTES = 3`）。
- agent 策略文本（DySQL `sql_wiki.md`）原样保留，不改。

## Review Focus

下面五种输入或情形，spec 隐含但各任务的主测试碰不到，最容易出问题。每条的测试都已经加进负责它的任务。

1. **实体根没有名字列**（spider2 Airlines 的 `bookings`）。prompt 只要求给 ID，没有子查询，检查不崩。测试：Task 3 `test_entity_text_without_a_name_and_with_a_new_lookup_row`、Task 1 `name_cols` 为空的校验。
2. **新查找行由根表自己引用**（`game.genre_id -> genre.id`、`generalinfo.city -> geographic.city`）。根行本身就是 own，所以新行算被用上。测试：Task 4 `test_a_new_lookup_row_may_hang_under_the_root_itself`。
3. **题目里有撇号**（I'm、it's、3's），不能被当成引号，造成名字错配的误杀。测试：Task 4 `test_a_quoted_name_of_another_row_is_a_mismatch` 的最后一段。
4. **人物库的旧 profile、旧树、旧候选**。版本号不变（Task 1），没有 `kind`、`taken` 的旧树照常渲染（Task 2 原有测试），3,556 条候选重跑检查结果不变（Task 4 Step 7）。
5. **超宽表**（card_games 的 `cards` 有 74 列）。实体模式下 UPDATE 触发器要记下整行，而 SQLite 一个函数最多 127 个参数。测试：Task 4 `test_a_row_wider_than_sqlite_function_arguments_is_still_recorded`。

## 与设计文档的两处偏差（Task 5 Step 6 写回设计）

1. **名字和 ID 对不上，由检查拦，不靠校验模型。** 校验模型只看 DDL 和数据说明，看不到行数据，判断不了"菜谱 935 叫不叫 Grape Nuts"。所以 §3.5 里"改名字的负样本"改成检查规则 `name_mismatch`（§3.4）：题目引号里的名字如果是库里某个名字列的值，就必须出现在任务碰到的行或其父行里。校准集的负样本只用原有 5 种 SQL 破坏。
2. **"已用的键值"放在树和数据块里，不放在键说明里。** 键说明按库生成，而已用的组合是按根行而不同的。所以 `trees.py` 和 `schema.py` 也要改（§5 原写"预计不改"）。

---

### Task 1: profile 的 `kind`、`speaker_roles`、`new_lookup`

**Files:**
- Modify: `taskgen/v2/taskgen_v2/db_profile.py`
- Modify: `taskgen/v2/tests/v2_fixtures.py`（加 MENUS 夹具）
- Modify: `taskgen/v2/scripts/taskgen.py`（`profile --kind`；`sample_trees` 的措辞）
- Test: `taskgen/v2/tests/test_taskgen_db_profile.py`、`taskgen/v2/tests/test_taskgen_cli.py`

**Interfaces:**
- Produces:
  - `db_profile.kind(profile) -> "person" | "entity"`；
  - 常量 `db_profile.OPTIONAL`、`KINDS`、`N_ROLES`；
  - 夹具 `MENUS`、`MENUS_FKS`、`MENUS_PROFILE`（v2_fixtures），后面每个任务的测试都用；
  - CLI `profile {check,render} --kind entity`。
- profile 的新字段：`kind`（缺省 person）；`speaker_roles`（list[str]，4–6 条）；`new_lookup`（list of `{"via": "child.col -> parent.col", "name_cols": [...]}`）。

- [ ] **Step 1: 加夹具**

在 `tests/v2_fixtures.py` 末尾加：

```python
# an entity-rooted database (design 2026-10-04): menus with pages and items, dishes shared by every menu (public) and
# pointed at by a menu's house dish, yearly view counts under a composite key, and owner names a sampled speaker name
# could hit (menu 3 is owned by 'Grace Kim')
MENUS = """
CREATE TABLE dish (dish_id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE menu (menu_id INTEGER PRIMARY KEY, name TEXT, owner_name TEXT, house_dish INTEGER REFERENCES dish(dish_id));
CREATE TABLE page (page_id INTEGER PRIMARY KEY, menu_id INTEGER REFERENCES menu(menu_id), page_number INTEGER);
CREATE TABLE item (item_id INTEGER PRIMARY KEY, page_id INTEGER REFERENCES page(page_id),
                   dish_id INTEGER REFERENCES dish(dish_id), price REAL);
CREATE TABLE menu_stats (menu_id INTEGER REFERENCES menu(menu_id), year INTEGER, views INTEGER, PRIMARY KEY (menu_id, year));
""" + rows("dish", 30, lambda i: f"{i},'dish {i}'") \
    + rows("menu", 10, lambda i: f"{i},'Menu {i}','{'Grace Kim' if i == 3 else f'Owner {i}'}',{i}") \
    + rows("page", 20, lambda i: f"{i},{i % 10},{1 + i // 10}") \
    + rows("item", 60, lambda i: f"{i},{i % 20},{i % 30},{1.5 + i}") \
    + rows("menu_stats", 30, lambda i: f"{i % 10},{2000 + i // 10},{i}")
MENUS_FKS = [{"table": "menu", "col": "house_dish", "ref_table": "dish", "ref_col": "dish_id", "hit": 1.0, "source": "declared"},
             {"table": "page", "col": "menu_id", "ref_table": "menu", "ref_col": "menu_id", "hit": 1.0, "source": "declared"},
             {"table": "item", "col": "page_id", "ref_table": "page", "ref_col": "page_id", "hit": 1.0, "source": "declared"},
             {"table": "item", "col": "dish_id", "ref_table": "dish", "ref_col": "dish_id", "hit": 1.0, "source": "declared"},
             {"table": "menu_stats", "col": "menu_id", "ref_table": "menu", "ref_col": "menu_id", "hit": 1.0, "source": "declared"}]
MENUS_PROFILE = {
    "kind": "entity",
    "roots": [{"table": "menu", "label": "menu",
               "parents": [{"table": "dish", "via": "menu.house_dish -> dish.dish_id", "parents": []}]}],
    "persons": {"menu": {"key": "menu_id", "name_cols": ["name"], "same_as": []}},
    "events": [{"table": "page", "label": "pages", "path": ["page.menu_id -> menu.menu_id"], "parents": []},
               {"table": "item", "label": "menu items", "path": ["page.menu_id -> menu.menu_id", "item.page_id -> page.page_id"],
                "parents": [{"table": "dish", "via": "item.dish_id -> dish.dish_id", "parents": []}]},
               {"table": "menu_stats", "label": "yearly views", "path": ["menu_stats.menu_id -> menu.menu_id"], "parents": []}],
    "attributes": [], "public": ["dish"], "exclude": [], "no_insert": [], "quirks": [],
    "speaker_roles": ["a menu collection archivist cataloguing this menu", "a volunteer transcriber who keyed in this menu",
                      "a restaurant historian researching this menu", "a librarian correcting the catalogue"],
    "new_lookup": [{"via": "item.dish_id -> dish.dish_id", "name_cols": ["name"]},
                   {"via": "menu.house_dish -> dish.dish_id", "name_cols": ["name"]}],
    "description": "Historical restaurant menus with their pages and items; dishes are shared by all menus.", "confirmed": True}
MENUS_PROFILE["confirmed_version"] = version(MENUS_PROFILE)
```

Menu 3 的数据（后面的测试都依赖这些）：

| 内容 | 值 |
|---|---|
| 页 | 3、13 |
| 菜品条目 | 3、13、23、33、43、53 |
| 条目对应的菜 | 3、13、23、3、13、23 |
| 已有年份 | 2000、2001、2002 |
| house_dish | 3 |
| owner_name | 'Grace Kim' |

- [ ] **Step 2: 写失败的测试**

在 `tests/test_taskgen_db_profile.py` 里：import 行加 `import hashlib, json`，fixtures 的 import 加上 `MENUS, MENUS_FKS, MENUS_PROFILE`；文件末尾加：

```python
@pytest.fixture
def menus(tmp_path):
    return sqlite3.connect(make_db(tmp_path, "menus", MENUS))


def test_an_entity_profile_is_valid_and_person_versions_stay(menus):
    assert db_profile.validate(MENUS_PROFILE, menus, MENUS_FKS) == []
    assert db_profile.kind(MENUS_PROFILE) == "entity" and db_profile.kind(SHOP_PROFILE) == "person"
    # the 23 confirmed person profiles have no kind, speaker_roles or new_lookup: their versions must not move
    body = {k: SHOP_PROFILE.get(k) for k in db_profile.FIELDS if k != "confirmed"}
    old = hashlib.sha1(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:10]
    assert db_profile.version(SHOP_PROFILE) == old and db_profile.status(SHOP_PROFILE) == "confirmed"
    fewer = {**MENUS_PROFILE, "speaker_roles": MENUS_PROFILE["speaker_roles"][:3] + ["a chef"]}
    assert db_profile.version(fewer) != db_profile.version(MENUS_PROFILE)       # the new fields are part of what is confirmed


def test_entity_profile_rules(menus, shop):
    def errs(**kw):
        return db_profile.validate({**copy.deepcopy(MENUS_PROFILE), **kw}, menus, MENUS_FKS)
    assert errs(kind="thing") == ["kind: 'thing' is not one of person, entity",
                                  "speaker_roles and new_lookup are for entity profiles only"]
    assert errs(speaker_roles=["a librarian"]) == ["speaker_roles: an entity profile needs 4-6 roles, each a phrase"]
    assert errs(new_lookup=[{"via": "item.page_id -> page.page_id", "name_cols": ["page_number"]}]) == ["new_lookup[0]: page is not public"]
    assert errs(new_lookup=[{"via": "item.dish_id -> dish.dish_id", "name_cols": ["title"]}]) == ["new_lookup[0].name_cols: no column dish.title"]
    assert errs(new_lookup=[{"via": "item.dish_id -> dish.dish_id", "name_cols": []}]) == ["new_lookup[0].name_cols: is empty"]
    assert errs(no_insert=["dish"]) == ["new_lookup[0]: dish is closed to INSERT (no_insert)",
                                        "new_lookup[1]: dish is closed to INSERT (no_insert)"]
    assert errs(persons={"menu": {"key": "menu_id", "name_cols": [], "same_as": []}}) == []   # spider2 Airlines bookings: no name
    extra = errs(persons={**MENUS_PROFILE["persons"], "dish": {"key": "dish_id", "name_cols": ["name"], "same_as": []}})
    assert "persons: an entity profile lists its roots only, not dish" in extra
    assert db_profile.validate({**SHOP_PROFILE, "speaker_roles": ["a", "b", "c", "d"]}, shop, FKS) == \
        ["speaker_roles and new_lookup are for entity profiles only"]


def test_render_shows_the_kind_roles_and_new_lookup_rows():
    text = db_profile.render_md([{"key": "test:menus", "profile": MENUS_PROFILE, "errors": [], "pk": {}}])
    assert "| 类型 | 实体（根是物，不是人） |" in text
    assert "| 说话人角色 | a menu collection archivist cataloguing this menu；a volunteer transcriber" in text
    assert "| 可新建的查找行 | item.dish_id -> dish.dish_id（名字列 name）；menu.house_dish -> dish.dish_id（名字列 name） |" in text
    assert "| 类型 |" not in db_profile.render_md([{"key": "x", "profile": SHOP_PROFILE, "errors": [], "pk": {}}])
```

在 `tests/test_taskgen_cli.py` 末尾加：

```python
def test_profile_render_keeps_one_kind(tmp_path):
    args = setup(tmp_path)
    common = ["--anchors", args[3], "--profiles", args[5]]
    page = tmp_path / "p.md"
    assert "0 profiles" in run("profile", "render", *common, "--kind", "entity", "--out", str(page)).stdout
    assert "1 profiles" in run("profile", "render", *common, "--kind", "person", "--out", str(page)).stdout
```

- [ ] **Step 3: 跑测试，确认失败**

Run: `cd $REPO/taskgen/v2 && $P -m pytest -q tests/test_taskgen_db_profile.py tests/test_taskgen_cli.py`
Expected: FAIL，报 `ImportError: cannot import name 'MENUS'`（Step 1 还没保存时），或 `AttributeError: module 'taskgen_v2.db_profile' has no attribute 'kind'`，或 `--kind` 是未知参数。

- [ ] **Step 4: 实现 `db_profile.py`**

在 `MAX_PATH = 3 ...` 一行后加：

```python
OPTIONAL = ("kind", "speaker_roles", "new_lookup")   # entity profiles only (design 2026-10-04 §3.1)
KINDS = ("person", "entity")
N_ROLES = (4, 6)     # speaker roles an entity profile lists
```

在 `def load(` 之前加：

```python
def kind(profile):
    """'person' (the 23 databases of plans 1-5: the roots are people) or 'entity' (the root is a thing, such as a menu)."""
    return profile.get("kind") or "person"
```

`version()` 改成：

```python
def version(profile):
    """Short hash of what the profile says (the review fields left out), recorded in every tree."""
    body = {k: profile.get(k) for k in FIELDS if k != "confirmed"}
    body.update({k: profile[k] for k in OPTIONAL if k in profile})   # absent from person profiles, so their versions stay
    return hashlib.sha1(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:10]
```

`_validate()` 里：

- `shapes += [f"events[{i}].path" ...]` 一行之后加：

```python
    shapes += ["new_lookup"] if not isinstance(profile.get("new_lookup", []), list) else []
```

- `persons = profile["persons"]` 一行改成：

```python
    persons, entity = profile["persons"], profile.get("kind") == "entity"
    if kind(profile) not in KINDS:
        errs.append(f"kind: {profile.get('kind')!r} is not one of {', '.join(KINDS)}")
```

- `if not p.get("name_cols"):` 改成 `if not p.get("name_cols") and not entity:   # an entity may have no name (Airlines bookings)`。

- `root_tables = {r.get("table") for r in roots}` 一行之后加：

```python
    if entity and set(persons) - root_tables:
        errs.append(f"persons: an entity profile lists its roots only, not {', '.join(sorted(set(persons) - root_tables))}")
```

- `if not isinstance(profile["confirmed"], bool):` 之前加：

```python
    roles = profile.get("speaker_roles")
    if entity:
        if not (isinstance(roles, list) and N_ROLES[0] <= len(roles) <= N_ROLES[1]
                and all(isinstance(r, str) and r.strip() for r in roles)):
            errs.append(f"speaker_roles: an entity profile needs {N_ROLES[0]}-{N_ROLES[1]} roles, each a phrase")
    elif roles is not None or profile.get("new_lookup") is not None:
        errs.append("speaker_roles and new_lookup are for entity profiles only")
    for i, x in enumerate(profile.get("new_lookup") or []):
        where = f"new_lookup[{i}]"
        e = edge(x.get("via"), f"{where}.via")
        if e is None:
            continue
        if e.parent not in public:
            errs.append(f"{where}: {e.parent} is not public")
        if e.parent in profile["no_insert"]:
            errs.append(f"{where}: {e.parent} is closed to INSERT (no_insert)")
        if e.child not in owned | root_tables:
            errs.append(f"{where}: {e.child} is neither a root nor one of its event, path or attribute tables")
        if not x.get("name_cols"):
            errs.append(f"{where}.name_cols: is empty")
        else:
            has(e.parent, f"{where}.name_cols", x["name_cols"])
```

`render_md()` 里，在 `lines += ["| 项 | 内容 |", ...]` 之前加：

```python
        if kind(p) == "entity":
            rows[1:1] = [("类型", "实体（根是物，不是人）"), ("说话人角色", "；".join(p.get("speaker_roles") or [])),
                         ("可新建的查找行", "；".join(f"{x.get('via')}（名字列 {', '.join(x.get('name_cols') or [])}）"
                                                for x in p.get("new_lookup") or []))]
```

- [ ] **Step 5: CLI 的 `--kind`**

在 `scripts/taskgen.py` 里改三处：

1. `cmd_profile()` 里，`keys = [a.db] if a.db else sorted(profiles)` 改成：

```python
    keys = [a.db] if a.db else sorted(k for k, p in profiles.items() if not a.kind or db_profile.kind(p) == a.kind)
```

2. `main()` 里，profile 子命令那段加一行：

```python
    p.add_argument("--kind", choices=db_profile.KINDS, help="check/render: only profiles of this kind")
```

3. `sample_trees()` 里，`prompt.data_blocks(t, refs, "the speaker's own row")` 改成：

```python
prompt.data_blocks(t, refs, "the record the request is about" if db_profile.kind(prof) == "entity" else "the speaker's own row")
```

- [ ] **Step 6: 跑测试，确认通过**

Run: `cd $REPO/taskgen/v2 && $P -m pytest -q`
Expected: 全部通过，为 194 + 4 = 198 passed。再确认真实的 23 份 profile 都还是 confirmed：

```bash
$P scripts/taskgen.py profile check | grep -c "ok, confirmed"
```
Expected：`23`。

- [ ] **Step 7: 提交**

```bash
cd $REPO && git add taskgen/v2/taskgen_v2/db_profile.py taskgen/v2/scripts/taskgen.py taskgen/v2/tests/v2_fixtures.py \
  taskgen/v2/tests/test_taskgen_db_profile.py taskgen/v2/tests/test_taskgen_cli.py
git commit -m "feat(taskgen v2): entity profiles: kind, speaker roles and new lookup rows"
```

---

### Task 2: 树记下 kind、根的 label 和已用的键值；数据块的实体措辞

**Files:**
- Modify: `taskgen/v2/taskgen_v2/schema.py`（`key_groups`）
- Modify: `taskgen/v2/taskgen_v2/trees.py`（`kind`、`root_label`、`taken`）
- Modify: `taskgen/v2/taskgen_v2/prompt.py`（`data_blocks`、`_label_text`、`_who`）
- Test: `taskgen/v2/tests/test_taskgen_schema.py`、`tests/test_taskgen_trees.py`、`tests/test_taskgen_prompt.py`

**Interfaces:**
- Consumes：Task 1 的 `db_profile.kind`、MENUS 夹具。
- Produces：
  - `schema.key_groups(conn, table) -> [tuple[str, ...]]`；
  - 树新增字段 `tree["kind"]`、`tree["root_label"]`，每个事件组新增 `group["taken"]: {"a, b": [[v1, v2], ...]}`；
  - `prompt.ENTITY = "6_entity"`；
  - `prompt._who("6_entity") == "the record the request is about"`；
  - 实体树里别的实体的行，标成 "another {root_label}'s data"。

- [ ] **Step 1: 写失败的测试**

`tests/test_taskgen_schema.py` 末尾加：

```python
def test_key_groups_are_the_keys_a_new_row_must_not_repeat(tmp_path):
    conn = sqlite3.connect(make_db(tmp_path, "kg", """
CREATE TABLE auto (id INTEGER PRIMARY KEY, v TEXT);
CREATE TABLE pair (a INTEGER, b INTEGER, v TEXT, PRIMARY KEY (a, b));
CREATE TABLE coded (code TEXT PRIMARY KEY, name TEXT UNIQUE);
CREATE TABLE nokey (v TEXT);"""))
    assert schema.key_groups(conn, "auto") == [] and schema.key_groups(conn, "nokey") == []
    assert schema.key_groups(conn, "pair") == [("a", "b")] and schema.key_groups(conn, "coded") == [("code",), ("name",)]
```

`tests/test_taskgen_trees.py`：fixtures 的 import 加上 `MENUS, MENUS_FKS, MENUS_PROFILE`，文件末尾加：

```python
MENUS_REC = {"source": "test", "db": "menus", "anchors": [], "fks": MENUS_FKS}


@pytest.fixture
def menus(tmp_path):
    c = sqlite3.connect(make_db(tmp_path, "menus", MENUS)); yield c; c.close()


def test_an_entity_tree_says_its_kind_and_lists_used_keys(menus, monkeypatch):
    t = tree(menus, MENUS_PROFILE, MENUS_REC, MENUS_PROFILE["roots"][0], 3)
    assert (t["kind"], t["root_label"], t["anchor_name"]) == ("entity", "menu", "Menu 3")
    assert t["parents"][0]["table"] == "dish" and t["parents"][0]["label"] == "public"
    pages, items, stats = t["events"]
    assert {n["label"] for n in pages["rows"] + items["rows"]} == {"own"} and items["rows"][0]["parents"][0]["label"] == "public"
    assert stats["taken"] == {"menu_id, year": [[3, 2000], [3, 2001], [3, 2002]]} and pages["taken"] == {} and items["taken"] == {}
    monkeypatch.setattr(trees, "TAKEN_MAX", 2)
    assert tree(menus, MENUS_PROFILE, MENUS_REC, MENUS_PROFILE["roots"][0], 3)["events"][2]["taken"] == \
        {"menu_id, year": [[3, 2000], [3, 2001]]}


def test_person_trees_say_person(shop):
    t = tree(shop, SHOP_PROFILE, SHOP_REC, CUSTOMERS, 5)
    assert t["kind"] == "person" and t["root_label"] == "customer" and all(g["taken"] == {} for g in t["events"])
```

`tests/test_taskgen_prompt.py` 在 `NO_EVENTS = ...` 之后加 `ENTITY_TREE`；文件末尾加测试：

```python
def item(i, label="own"):
    return {"table": "item", "row": {"item_id": i, "page_id": 3, "dish_id": i, "price": 2.5}, "label": label,
            "parents": [{"table": "dish", "row": {"dish_id": i, "name": f"dish {i}"}, "label": "public", "parents": []}]}


ENTITY_TREE = {"kind": "entity", "root_label": "menu", "anchor_table": "menu", "anchor_key": "menu_id", "key_value": 3,
               "anchor_name": "Menu 3", "anchor_row": {"menu_id": 3, "name": "Menu 3", "owner_name": "Grace Kim", "house_dish": 3},
               "lookup": {"name": "Menu 3"}, "profile_version": "v1", "attributes": {},
               "parents": [{"table": "dish", "row": {"dish_id": 3, "name": "dish 3"}, "label": "public", "parents": []}],
               "events": [{"table": "item", "label": "menu items", "count": 6, "taken": {}, "rows": [item(i) for i in (3, 13, 23)]},
                          {"table": "menu_stats", "label": "yearly views", "count": 3, "taken": {"menu_id, year": [[3, 2000], [3, 2001], [3, 2002]]},
                           "rows": [{"table": "menu_stats", "row": {"menu_id": 3, "year": 2000 + k, "views": k}, "label": "own", "parents": []}
                                    for k in range(3)]},
                          {"table": "page", "label": "pages", "count": 1, "taken": {},
                           "rows": [{"table": "page", "row": {"page_id": 4, "menu_id": 4, "page_number": 1}, "label": "other:Menu 4", "parents": []}]}]}
```

```python
def test_entity_data_blocks_name_the_record_and_the_used_keys():
    text = prompt.data_blocks(ENTITY_TREE, [[0, 0], [1, 0], [2, 0]], prompt._who(prompt.ENTITY))
    assert text.startswith("## menu record (the record the request is about)\n")
    assert "- page (another menu's data: Menu 4): " in text
    assert ("A new menu_stats row must not repeat these (menu_id, year) values, already used: (3, 2000), (3, 2001), (3, 2002)."
            in text)
    few = {**ENTITY_TREE, "events": [{**ENTITY_TREE["events"][1], "count": 9}]}
    assert "already used: (3, 2000), (3, 2001), (3, 2002) and others." in prompt.data_blocks(few, [[0, 0]], "x")
    assert "already used" not in prompt.data_blocks(TREE, [[0, 0], [1, 0]], "x")       # person trees from before Task 2
```

- [ ] **Step 2: 跑测试，确认失败**

Run: `$P -m pytest -q tests/test_taskgen_schema.py tests/test_taskgen_trees.py tests/test_taskgen_prompt.py`
Expected: FAIL，报 `AttributeError: module 'taskgen_v2.schema' has no attribute 'key_groups'`、`KeyError: 'kind'`，以及 `module 'taskgen_v2.prompt' has no attribute 'ENTITY'`。

- [ ] **Step 3: 实现 `schema.key_groups`**

在 `schema.py` 的 `unique_columns` 之后加：

```python
def key_groups(conn, table):
    """Column groups no two rows may share that a new row has to state (design 2026-10-04 §6): a primary key SQLite
    does not fill in (anything but a rowid alias) and every UNIQUE group. Trees list the values a root's rows already
    use, since the prompt shows only some rows (plan 5 lost address, IPL, WWE and school_scheduling candidates to them)."""
    pk = sorted((r for r in conn.execute(f"PRAGMA table_info({_q(table)})") if r[5]), key=lambda r: r[5])
    sql = (conn.execute("SELECT sql FROM sqlite_master WHERE name = ?", (table,)).fetchone() or ("",))[0] or ""
    rowid = len(pk) == 1 and (pk[0][2] or "").upper() == "INTEGER" and not re.search(r"(?i)\bwithout\s+rowid\b", sql)
    out = [tuple(r[1] for r in pk)] if pk and not rowid else []
    return out + [u for u in unique_columns(conn, table) if u not in out]
```

- [ ] **Step 4: 实现 `trees.py`**

- import 行改成 `from taskgen_v2 import db_profile, schema`。
- 在 `MAX_DEPTH = 4 ...` 之后加 `TAKEN_MAX = 60    # used key values listed per event group; a group with more lists the first 60`。
- 在 `lookup()` 之前加：

```python
def taken(conn, table, rows):
    """{'a, b': [[1, 2], ...]}: the values of each key group (schema.key_groups) that the group's rows already use."""
    out = {}
    for g in schema.key_groups(conn, table):
        vals = sorted({tuple(r.get(c) for c in g) for r in rows if all(r.get(c) is not None for c in g)}, key=str)
        if vals:
            out[", ".join(g)] = [list(v) for v in vals[:TAKEN_MAX]]
    return out
```

- `build_tree()` 的 return：
  - 字典开头加 `"kind": db_profile.kind(profile), "root_label": root["label"],`；
  - 事件组字典改成 `{"table": ev["table"], "label": ev["label"], "count": len(rs), "taken": taken(conn, ev["table"], rs), "rows": [...]}`（rows 部分不变）。

- [ ] **Step 5: 实现 prompt 的数据块**

在 `prompt.py` 的 `PUBLIC_TYPES = ...` 之后加 `ENTITY = "6_entity"   # an entity profile's only type (design 2026-10-04)`。

`_who` 改成：

```python
def _who(task_type):
    if task_type == ENTITY:
        return "the record the request is about"
    return "the speaker's own row" if task_type != "5_proxy" else "the person the request is about"
```

`_label_text` 改成：

```python
def _label_text(label, other="another person's data"):
    if label.startswith("other:"):
        return f"{other}: {label[6:]}"
    return {"own": "own", "public": "public, shared reference data owned by nobody"}.get(label, label)


def _taken_lines(g):
    """What a new row of the group must not repeat (trees.taken), so the model does not pick a used pair."""
    out = []
    for cols, vals in (g.get("taken") or {}).items():
        shown = ", ".join("(" + ", ".join(sql_value(v) for v in t) + ")" if len(t) > 1 else sql_value(t[0]) for t in vals)
        more = " and others" if g["count"] > len(vals) else ""
        out.append(f"A new {g['table']} row must not repeat these ({cols}) values, already used: {shown}{more}.")
    return out
```

`data_blocks` 里：
- `def js(row)` 之前加 `other = f"another {tree['root_label']}'s data" if tree.get("kind") == "entity" else "another person's data"`；
- `lines()` 里的 `_label_text(node['label'])` 改成 `_label_text(node['label'], other)`；
- 事件组那段改成：

```python
    for g in trees.shown(tree, refs):
        blocks.append(f"## {g['label']}: {g['table']} records ({len(g['rows'])} of {g['count']} shown)\n"
                      + "\n".join([x for n in g["rows"] for x in lines(n, 0)] + _taken_lines(g)))
```

- [ ] **Step 6: 跑测试，确认通过**

Run: `$P -m pytest -q`
Expected: 全部通过，为 198 + 4 = 202 passed。

- [ ] **Step 7: 提交**

```bash
cd $REPO && git add taskgen/v2/taskgen_v2/{schema,trees,prompt}.py taskgen/v2/tests/test_taskgen_{schema,trees,prompt}.py
git commit -m "feat(taskgen v2): trees know their kind and list the key values a root's rows already use"
```

---

### Task 3: `6_entity` 的出题：说话人、新查找行形状、类型文本、示例

**Files:**
- Modify: `taskgen/v2/taskgen_v2/prompt.py`
- Modify: `taskgen/v2/taskgen_v2/examples.json`
- Modify: `taskgen/v2/taskgen_v2/generate.py`（`context` 加两个键）
- Test: `taskgen/v2/tests/test_taskgen_prompt.py`、`tests/test_taskgen_generate.py`

**Interfaces:**
- Consumes：Task 2 的 `ENTITY`、`tree["kind"]`、`tree["root_label"]`；Task 1 的 `MENUS_PROFILE` 和 `db_profile.parse_edge`。
- Produces：
  - `prompt.SPEAKERS = ("name", "role", "username", "none")`；
  - `prompt.entity_speaker(rng, roles, cfg) -> {"speaker", "name", "role", "username"}`；
  - `prompt.entity_fmt(tree, plan) -> dict`；
  - 实体 plan 的 `plan["style"]` 带 `speaker`、`name`、`role`、`username`、`tone`；
  - `plan["shape"]["new_lookup"]`：`None`，或 `{"table", "child", "via", "name_cols"}`，人物 plan 也有这个键，值为 None；
  - `generate.context()` 多出 `"speaker_roles"`、`"new_lookup"`；
  - `examples.json` 多出 `"6_entity/name"`、`"6_entity/role"`、`"6_entity/username"`、`"6_entity/none"` 四个键。
- Task 4 读 `cand["plan"]["style"]["name"]`。

- [ ] **Step 1: 写失败的测试**

`tests/test_taskgen_prompt.py`：

`test_examples_are_dysql_style_for_the_four_types` 整个换成：

```python
def test_examples_are_dysql_style_for_every_type():
    ex = prompt.load_examples()
    assert set(ex) == set(prompt.CFG["TYPE_MIX"]) | {f"6_entity/{s}" for s in prompt.SPEAKERS}
    for t, xs in ex.items():
        assert len(xs) >= (2 if t.startswith("6_entity/") else 3), t
        for x in xs:
            assert 40 <= len(x.split()) <= 80 and metrics.ID_RE.search(" ".join(x.split()[:25])) and not metrics.ASK.search(x), x
```

文件末尾加：

```python
ENTITY_ANCHOR = {"table": "menu", "key": "menu_id", "names": ["name"]}
ENTITY_CTX = {"fixed": {"item": {"item_id", "page_id", "dish_id"}, "dish": {"dish_id"}, "menu_stats": {"menu_id", "year"},
                        "menu": {"menu_id", "house_dish"}},
              "copyable": {"item"}, "pk": {"item": ["item_id"]},
              "speaker_roles": ["a menu collection archivist", "a volunteer transcriber", "a restaurant historian", "a librarian"],
              "new_lookup": [{"via": "item.dish_id -> dish.dish_id", "name_cols": ["name"]}]}
ENTITY_MATERIALS = {**ENTITY_CTX, "description": "Historical menus.", "quirks": [], "schema": "CREATE TABLE menu (...)",
                    "keys": {"dish": "- dish: a new row may leave dish_id out (SQLite assigns 30)"}}


def entity_plans(n=3000, seed=0, tree=ENTITY_TREE, ctx=ENTITY_CTX):
    rng = random.Random(seed)
    return [prompt.sample_plan(rng, tree, ENTITY_ANCHOR, prompt.CFG, ctx) for _ in range(n)]


def test_entity_trees_get_only_entity_tasks_with_the_speaker_mix():
    assert prompt.feasible_types(ENTITY_TREE) == ["6_entity"]
    ps = entity_plans()
    assert {p["task_type"] for p in ps} == {"6_entity"}
    sp = Counter(p["style"]["speaker"] for p in ps)
    assert abs(sp["name"] / 3000 - 0.55) < 0.04 and abs(sp["none"] / 3000 - 0.28) < 0.04
    assert abs((sp["role"] + sp["username"]) / 3000 - 0.17) < 0.03 and sp["role"] > 100 and sp["username"] > 100
    named = [p["style"] for p in ps if p["style"]["speaker"] == "name"]
    assert 0.4 < sum(s["role"] is not None for s in named) / len(named) < 0.6
    assert all(p["style"]["role"] in ENTITY_CTX["speaker_roles"] for p in ps if p["style"]["role"])
    assert len({p["style"]["username"] for p in ps if p["style"]["username"]}) > 100
    assert all(p["style"]["name"] is None for p in ps if p["style"]["speaker"] != "name")
    assert all(p["example"] in prompt.load_examples()[f"6_entity/{p['style']['speaker']}"] for p in ps[:300])


def test_entity_tasks_write_only_own_tables_except_a_new_lookup_row():
    ps = entity_plans()
    look = [p for p in ps if p["shape"]["new_lookup"]]
    assert 0.06 < len(look) / 3000 < 0.13      # 10% of the plans whose shown tables include item
    for p in look:
        s = p["shape"]
        assert s["new_lookup"] == {"table": "dish", "child": "item", "via": "item.dish_id -> dish.dish_id", "name_cols": ["name"]}
        assert s["n_writes"] >= 2 and s["n_tables"] == 2 and p["write_tables"] == ["dish", "item"]
        assert not s["batch"] and not s["archive"] and "dish" in p["scope"]
        assert not any(t.startswith("dish.") for t in p["targets"])
    for p in ps:
        if not p["shape"]["new_lookup"]:
            assert "dish" not in p["scope"] and set(p["write_tables"] or []) <= set(p["tables"]["own"])
    assert not any(p["shape"]["new_lookup"] for p in entity_plans(300, ctx={**ENTITY_CTX, "new_lookup": []}))
    assert all(p["shape"]["new_lookup"] is None for p in plans(300))     # person plans never get one


def test_entity_messages_say_who_speaks_and_what_the_request_is_about():
    rng, by = random.Random(0), {}
    while len(by) < 4:
        p = prompt.sample_plan(rng, ENTITY_TREE, ENTITY_ANCHOR, prompt.CFG, ENTITY_CTX)
        by.setdefault(p["style"]["speaker"], p)
    users = {k: prompt.build_messages(DB, ENTITY_ANCHOR, ENTITY_TREE, p, ENTITY_MATERIALS)[1]["content"] for k, p in by.items()}
    for k, u in users.items():
        assert "The speaker is not in the database, and nothing in it records who they are: " in u
        assert "The request is about the menu in menu with menu_id = 3 (Menu 3)." in u
        assert "the menu's name and its ID, written with the word ID or the column name (menu_id 3 or ID 3)" in u
        assert "no new row is added to menu (that would be another menu)" in u
        assert "## menu record (the record the request is about)" in u
        assert by[k]["shape"]["ownership_subquery"] or "identify the menu by menu_id = 3; names can repeat" in u
    st = by["name"]["style"]
    assert f"The speaker is not in the database, and nothing in it records who they are: {st['name']}, " in users["name"]
    assert f"a user with the username {by['username']['style']['username']}, who gives no other name" in users["username"]
    assert f"{by['role']['style']['role']}, who gives no name" in users["role"] and "Their first sentence gives their role, then" in users["role"]
    assert "someone who gives no name, role or username" in users["none"]
    assert "Their first sentence says nothing about who they are and gives the menu's name and its ID" in users["none"]


def test_entity_text_without_a_name_and_with_a_new_lookup_row():
    nameless = {**ENTITY_TREE, "anchor_name": "", "lookup": {}}
    rng = random.Random(1)
    while not (p := prompt.sample_plan(rng, nameless, ENTITY_ANCHOR, prompt.CFG, ENTITY_CTX))["shape"]["new_lookup"]:
        pass
    assert not p["shape"]["ownership_subquery"]
    u = prompt.build_messages(DB, ENTITY_ANCHOR, nameless, p, ENTITY_MATERIALS)[1]["content"]
    assert "The request is about the menu in menu with menu_id = 3." in u and "the menu's name" not in u
    assert "except the one new dish row the task shape asks for" in u
    assert ("- First add one new row to dish whose name no dish row has yet (say it in the instruction), then make one "
            "item row of this menu refer to it through item.dish_id: change an existing row or add a new one. "
            "No other dish row changes.") in u
```

`tests/test_taskgen_generate.py`：fixtures 的 import 加上 `MENUS, MENUS_FKS, MENUS_PROFILE`，文件末尾加：

```python
def test_context_carries_the_entity_fields(tmp_path):
    rec = {"source": "test", "db": "menus", "path": make_db(tmp_path, "menus", MENUS), "anchors": [], "fks": MENUS_FKS}
    m = generate.context(rec, MENUS_PROFILE)
    assert m["speaker_roles"] == MENUS_PROFILE["speaker_roles"] and m["new_lookup"] == MENUS_PROFILE["new_lookup"]
    assert m["keys"]["menu_stats"] == "- menu_stats: key (menu_id, year); a new row states every key column, in a combination not used yet"
    shop = {"source": "test", "db": "shop2", "path": make_db(tmp_path, "shop2", SHOP2), "anchors": [], "fks": FKS}
    assert generate.context(shop, SHOP_PROFILE)["speaker_roles"] == [] and generate.context(shop, SHOP_PROFILE)["new_lookup"] == []
```

- [ ] **Step 2: 跑测试，确认失败**

Run: `$P -m pytest -q tests/test_taskgen_prompt.py tests/test_taskgen_generate.py`
Expected: FAIL，报 `AttributeError: ... 'SPEAKERS'` 和 `KeyError: 'speaker_roles'`。

- [ ] **Step 3: 实现 prompt.py**

- import 行改成 `from taskgen_v2 import db_profile, trees`。

- `CFG` 里，`"MAX_VALUE_CHARS"` 一行之后加：

```python
    # 6_entity (design 2026-10-04 §3.3): who speaks, as hand-counted on DySQL's car and cookbook (43/13/22 of 78)
    "SPEAKER_MIX": {"name": 0.55, "role_or_username": 0.17, "none": 0.28},
    "NAME_WITH_ROLE": 0.5,   # named speakers who also give a role from the profile ("Markus Klein, an auto dealer")
    "USERNAME": 0.5,         # role_or_username speakers who give a username ("dana_chef2001") instead of a role
    "NEW_LOOKUP": 0.10,      # entity tasks that add a public lookup row and point an own row at it (cookbook's hard tasks)
```

- `ENTITY = ...` 之后加 `SPEAKERS = ("name", "role", "username", "none")`。

- `TYPE_TEXT` 里加一项：

```python
    ENTITY: "The speaker is not in the database, and nothing in it records who they are: {speaker}. The request is about the {label} in {t} with {key} = {kv}{named}. {first}, written with the word ID or the column name ({key} {kv} or ID {kv}). Every write changes only rows marked own (this {label}'s rows){lookup}; rows marked public stay unchanged, rows of another {label} stay untouched, and no new row is added to {t} (that would be another {label}).",
```

- `feasible_types` 改成：

```python
def feasible_types(tree):
    """Types this tree can carry. An entity tree carries 6_entity only; never 4_other_person (design D6); 2 and 3 need
    a public row to write."""
    if tree.get("kind") == "entity":
        return [ENTITY]
    return ["1_self"] + (list(PUBLIC_TYPES) if trees.has_public(tree) else []) + ["5_proxy"]
```

- `_who` 之后加：

```python
def _username(rng):
    f, l = rng.choice(FIRST_NAMES).lower(), rng.choice(LAST_NAMES).lower()
    return rng.choice([f"{f}.{l[0]}", f"{l}_{rng.randint(10, 99)}", f"user_{rng.randint(1000, 9999)}", f"{f}{rng.randint(1970, 2005)}"])


def entity_speaker(rng, roles, cfg=CFG):
    """Who asks for an entity task (design 2026-10-04 §3.3): a sampled name (half of them with a role from the
    profile), a role or a username, or nobody in particular. The model never invents the name: the plan-3 pilot
    repeated 'Priya Raghavan' six times."""
    kind = _weighted(rng, cfg["SPEAKER_MIX"])
    out = {"speaker": kind, "name": None, "role": None, "username": None}
    if kind == "name":
        out["name"] = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"
        out["role"] = rng.choice(roles) if roles and rng.random() < cfg["NAME_WITH_ROLE"] else None
    elif kind == "role_or_username":
        if roles and rng.random() >= cfg["USERNAME"]:
            out.update(speaker="role", role=rng.choice(roles))
        else:
            out.update(speaker="username", username=_username(rng))
    return out


def entity_fmt(tree, plan):
    """The 6_entity placeholders of TYPE_TEXT: who speaks, which record, what their first sentence gives."""
    st, label, name = plan["style"], tree["root_label"], tree["anchor_name"]
    speaker = {"name": f"{st['name']}, " + (st["role"] or f"who looks after this {label} and calls it 'my {label}'"),
               "role": f"{st['role']}, who gives no name",
               "username": f"a user with the username {st['username']}, who gives no other name",
               "none": "someone who gives no name, role or username"}[st["speaker"]]
    own = {"name": "their name" + (" and role" if st["role"] else ""), "role": "their role",
           "username": "their username", "none": None}[st["speaker"]]
    record = f"the {label}'s name and its ID" if name else f"the {label}'s ID"
    first = (f"Their first sentence gives {own}, then {record}" if own
             else f"Their first sentence says nothing about who they are and gives {record}")
    look = plan["shape"].get("new_lookup")
    return {"speaker": speaker, "label": label, "named": f" ({name})" if name else "", "first": first,
            "lookup": f", except the one new {look['table']} row the task shape asks for" if look else ""}
```

- `sample_plan` 的改动按出现顺序如下。人物 plan 不能多调用 rng，这样已出的题仍可复现。
  1. docstring 末句加 ", and for an entity profile \"speaker_roles\" and \"new_lookup\" (design 2026-10-04 §3.3)"。
  2. `task_type = _weighted(...)` 一行改成：

```python
    entity = tree.get("kind") == "entity"
    task_type = ENTITY if entity else _weighted(rng, {k: v for k, v in cfg["TYPE_MIX"].items() if k in feasible_types(tree)})
```

  3. `pool = {...}.get(task_type, tabs["own"])` 之后、`if not refs:` 之前插入：

```python
    lookup = None   # an entity task may add one public lookup row and point a row of its own at it (cookbook's hard tasks)
    options = [x for x in ctx.get("new_lookup") or [] if db_profile.parse_edge(x["via"]).child in tabs["own"]] if entity else []
    if options and rng.random() < cfg["NEW_LOOKUP"]:
        x = rng.choice(options)
        e = db_profile.parse_edge(x["via"])
        lookup = {"table": e.parent, "child": e.child, "via": x["via"], "name_cols": list(x["name_cols"])}
        n_writes, pool = max(n_writes, 2), pool + [e.parent]
```

  4. batch 的条件改成 `if task_type != "3_public_only" and not lookup and groups and rng.random() < cfg["BATCH"]:`。
  5. n_tables：`if task_type == "2_self_and_public":` 改成 `if task_type == "2_self_and_public" or lookup:`。
  6. archive 的条件改成 `if not batch and not lookup and n_writes >= n_tables + 1 and sources and rng.random() < cfg["ARCHIVE"]:`。
  7. `write_tables = None` 之后的 `if rng.random() >= cfg["FREE_TABLE_SHARE"]:` 改成：

```python
    if lookup:
        write_tables = [lookup["table"], lookup["child"]]
    elif rng.random() >= cfg["FREE_TABLE_SHARE"]:
```

  8. `shape = {...}` 里加 `"new_lookup": lookup`。
  9. style 和 return 改成：

```python
    style = {"tone": rng.choice(TONES), "name": None, "role": None}
    if task_type == "5_proxy":
        style.update(name=f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}", role=rng.choice(ROLES))
    elif entity:
        style.update(entity_speaker(rng, ctx.get("speaker_roles") or [], cfg))
    return {"task_type": task_type, "difficulty": difficulty, "shape": shape, "write_tables": write_tables,
            "events": refs, "tables": tabs, "scope": pool,
            "targets": _targets(rng, rows_by_table(tree, refs),
                                [t for t in (write_tables or pool) if not lookup or t != lookup["table"]], fixed),
            "example": rng.choice(load_examples()[f"{ENTITY}/{style['speaker']}" if entity else task_type]), "style": style}
```

- `shape_text`：
  - 开头加 `noun = tree["root_label"] if tree.get("kind") == "entity" else "person"`。
  - 下面几处字面量里的 `person` 都换成 `{noun}`：
    - 两条 batch 文本里的 `the person's {b['label']} rows`；
    - `Find the person's rows`；
    - `identify the person by`。
  - 人物树的 noun 是 "person"，所以文本不变。
  - `if plan["targets"]:` 之前加：

```python
    if s.get("new_lookup"):
        x = s["new_lookup"]
        lines.append(f"- First add one new row to {x['table']} whose {' and '.join(x['name_cols'])} no {x['table']} row has yet "
                     f"(say it in the instruction), then make one {x['child']} row of this {noun} refer to it through "
                     f"{x['via'].split('->')[0].strip()}: change an existing row or add a new one. No other {x['table']} row changes.")
```

- `build_messages`：在 `quirks = ...` 之前加：

```python
    if plan["task_type"] == ENTITY:
        fmt.update(entity_fmt(tree, plan))
```

- [ ] **Step 4: 加示例**

```bash
cd $REPO/taskgen/v2 && $P - <<'EOF'
import json
p = "taskgen_v2/examples.json"
ex = json.load(open(p, encoding="utf-8"))
ex.update({
 "6_entity/name": [
  "I'm Lena Hartmann, and album ID 4471, 'Harbour Lights 1962', in the photo archive is mine. The scan of print 88213 is filed under the wrong year, so please set its year to 1963. Also give print 88214 the caption 'Fishing boats at dawn', which the album has been missing since it was first catalogued.",
  "Tobias Reyes here, a curator for the coastal collection, about artefact ID 3092, the brass ship's bell. Its display case changed last week, so please move it to case 'C-14'. The condition report from 2019-04-02 was entered twice: delete report 5531 and keep report 5530 exactly as it is."],
 "6_entity/role": [
  "As the volunteer who catalogues the trail network, I'm updating trail ID 218, Ridge Loop. It was measured again this spring at 7.4 km, so please change its length from 6.9 to 7.4. The signpost at waypoint 1904 was replaced, and its marker text should now read 'Ridge Loop North'.",
  "I'm the librarian in charge of the board game shelf, writing about game ID 615, 'Harbor Masters'. We started a new genre this month: please create the genre 'Cooperative Logistics' and make it the genre of this game. We also bought a second copy, so its copy count goes from 1 to 2."],
 "6_entity/username": [
  "Username vinyl_otto, editing record ID 9021, 'Blue Hours' by the Larsen Trio. Track 4 is listed at 192 seconds, but on the pressing it actually runs 221 seconds, so please set its length to 221. The pressing year printed on the sleeve is 1974, not 1975, so change that as well.",
  "This is gardener.k about plot ID 57 in the community garden. I've stopped growing beans there this season, so please remove planting 7713 from the plot. Change the plot's watering day to 'Thursday' too, since the old Monday slot clashes with the farmers' market that moved next door."],
 "6_entity/none": [
  "Podcast episode ID 1208, 'Night Shift Stories', needs two fixes before the weekly newsletter goes out. Its release date should be 2023-11-14 rather than 2023-11-07. The guest entry 3317 for that episode also has the guest's name misspelled; please change it to 'Amara Okonkwo', which is how she spells it.",
  "Please update ship ID 7340, the 'Northern Tern', in the harbour registry. Its home port moved to 'Bergen' this spring after the old berth was sold. Inspection 2291 from 2021 was a duplicate of inspection 2290, so delete 2291 and leave inspection 2290 exactly as it is now."]})
with open(p, "w", encoding="utf-8") as f:
    json.dump(ex, f, ensure_ascii=False, indent=2); f.write("\n")
EOF
git diff --stat taskgen_v2/examples.json
```
Expected：只多了 4 个键；原有四类的示例不变（diff 里只有新增行）。这 8 条在写计划时已经验证过：48–55 词，前 25 词里有 ID，不触发 ASK。

- [ ] **Step 5: `generate.context` 加两个键**

`generate.py` 的 `context()` 在 return 字典末尾加：

```python
            "speaker_roles": profile.get("speaker_roles") or [], "new_lookup": profile.get("new_lookup") or []}
```

（把原来的 `"pk": {...}}` 结尾改成 `"pk": {...},`，再接上这一行。）

- [ ] **Step 6: 跑测试，确认通过**

Run: `$P -m pytest -q`
Expected: 全部通过，为 202 + 5 = 207 passed（示例测试是改名替换，不算新增）。

- [ ] **Step 7: 提交**

```bash
cd $REPO && git add taskgen/v2/taskgen_v2/{prompt,generate}.py taskgen/v2/taskgen_v2/examples.json taskgen/v2/tests/test_taskgen_{prompt,generate}.py
git commit -m "feat(taskgen v2): entity tasks: sampled speakers, a new lookup row shape and their own examples"
```

---

### Task 4: 检查的实体规则

**Files:**
- Modify: `taskgen/v2/taskgen_v2/check.py`
- Test: `taskgen/v2/tests/test_taskgen_check.py`

**Interfaces:**
- Consumes：
  - `db_profile.kind`、`db_profile.parse_edge`、`db_profile.scope_tables`；
  - 候选的 `plan.task_type == "6_entity"`、`plan.style.name`；
  - profile 的 `new_lookup`。
- Produces：
  - 实体 profile 下 `run_check` 的 `task_type == "6_entity"`；
  - 新的拒绝原因：`other_person`、`root_insert: T`、`public_write: OP T`、`no_own_write`、`lookup_unreferenced: T`、`lookup_name_taken: T`、`speaker_name_taken`、`name_mismatch: T.C`；
  - 辅助函数 `check.quoted(text)`、`check.name_columns(db, tables)`、`check.person_name_stored(db, name)`。
- 人物 profile 和不带 profile 的检查，行为不变。

- [ ] **Step 1: 记下改动前的检查结果（后台跑，Step 7 比对）**

先写一个脚本 `$S/recheck.py`，用当前代码重跑全部人物库候选的检查：

```python
# $S/recheck.py OUT -- re-run the check on every person database's candidates; one JSON line per candidate
import json, sys
sys.path[:0] = [".", "../common"]
from taskgen_v2 import check, db_profile, io
recs, profiles = io.load_db_recs(), db_profile.load()
with open(sys.argv[1], "w", encoding="utf-8") as f:
    for key, prof in sorted(profiles.items()):
        if db_profile.kind(prof) != "person":
            continue
        for c in io.read_jsonl(f"results/{recs[key]['db']}/candidates.jsonl"):
            r = check.run_check_safe(recs[key], c, profile=prof)
            f.write(json.dumps({k: r[k] for k in ("id", "ok", "reasons", "task_type", "template", "difficulty", "writes")},
                               ensure_ascii=False, default=str) + "\n")
```

Run（后台，约 20–40 分钟）：`cd $REPO/taskgen/v2 && $P $S/recheck.py $S/recheck_before.jsonl`
Expected：跑完后 `wc -l $S/recheck_before.jsonl` 是 3556。

- [ ] **Step 2: 写失败的测试**

`tests/test_taskgen_check.py`：fixtures 的 import 加上 `MENUS, MENUS_FKS, MENUS_PROFILE`，文件末尾加：

```python
@pytest.fixture
def menus(tmp_path):
    return {"source": "test", "db": "menus", "path": make_db(tmp_path, "menus", MENUS), "anchors": [], "fks": MENUS_FKS}


def mcand(instruction, sqls, speaker=None, key_value=3):
    style = {"tone": "x", "speaker": "name" if speaker else "none", "name": speaker, "role": None, "username": None}
    return {"id": "m", "anchor_table": "menu", "anchor_key": "menu_id", "key_value": key_value,
            "plan": {"task_type": "6_entity", "style": style}, "instruction": instruction, "actions": [{"sql": s} for s in sqls]}


def mreasons(menus, ins, sqls, profile=MENUS_PROFILE, **kw):
    return check.run_check(menus, mcand(ins, sqls, **kw), profile=profile)["reasons"]


def test_an_entity_task_on_its_own_rows_is_type_6(menus):
    r = check.run_check(menus, mcand("Menu ID 3: set the price of item 13 to 4.5 and add the year 2003 with 7 views.",
                                     ["UPDATE item SET price = 4.5 WHERE item_id = 13",
                                      "INSERT INTO menu_stats VALUES (3, 2003, 7)"]), profile=MENUS_PROFILE)
    assert r["ok"], r["reasons"]
    assert [w["label"] for w in r["writes"]] == ["own", "own"] and r["task_type"] == "6_entity"
    assert r["template"] == "6_entity|INSERT menu_stats+UPDATE item"


def test_an_entity_task_may_not_touch_another_entity_or_public_rows(menus):
    assert mreasons(menus, "Menu ID 3: set item 14 to 4.5.", ["UPDATE item SET price = 4.5 WHERE item_id = 14"]) == \
        ["other_person", "no_own_write"]                                               # item 14 is on menu 4's page
    assert mreasons(menus, "Menu ID 3: rename dish 3 to 'Tea' and set item 3 to 4.5.",
                    ["UPDATE dish SET name = 'Tea' WHERE dish_id = 3", "UPDATE item SET price = 4.5 WHERE item_id = 3"]) == \
        ["public_write: UPDATE dish"]
    assert mreasons(menus, "Menu ID 3: add menu 10 called 'New'.", ["INSERT INTO menu (menu_id, name) VALUES (10, 'New')"]) == \
        ["root_insert: menu", "no_own_write"]


def test_a_new_lookup_row_must_be_new_and_used_by_the_entity(menus):
    ok = check.run_check(menus, mcand("Menu ID 3: add the dish 'Smoked Trout' and put it on item 13.",
                                      ["INSERT INTO dish (name) VALUES ('Smoked Trout')",
                                       "UPDATE item SET dish_id = (SELECT dish_id FROM dish WHERE name = 'Smoked Trout') WHERE item_id = 13"]),
                         profile=MENUS_PROFILE)
    assert ok["ok"], ok["reasons"]
    assert [w["label"] for w in ok["writes"]] == ["public", "own"] and ok["task_type"] == "6_entity"
    assert mreasons(menus, "Menu ID 3: add the dish 'Smoked Trout' and set item 13 to 4.5.",
                    ["INSERT INTO dish (name) VALUES ('Smoked Trout')", "UPDATE item SET price = 4.5 WHERE item_id = 13"]) == \
        ["lookup_unreferenced: dish"]
    assert mreasons(menus, "Menu ID 3: add the dish 'Dish 5' and put it on item 13.",      # 'dish 5' exists
                    ["INSERT INTO dish (name) VALUES ('Dish 5')", "UPDATE item SET dish_id = 30 WHERE item_id = 13"]) == \
        ["lookup_name_taken: dish"]
    assert mreasons(menus, "Menu ID 3: add the dish 'Smoked Trout' and put it on item 13.",
                    ["INSERT INTO dish (name) VALUES ('Smoked Trout')", "UPDATE item SET dish_id = 30 WHERE item_id = 13"],
                    profile={**MENUS_PROFILE, "new_lookup": []}) == ["public_write: INSERT dish"]


def test_a_new_lookup_row_may_hang_under_the_root_itself(menus):
    # video_games game.genre_id -> genre.id: the root row is the entity's own, so it uses the new row
    r = check.run_check(menus, mcand("Menu ID 3: add the dish 'Smoked Trout' and make it the house dish.",
                                     ["INSERT INTO dish (name) VALUES ('Smoked Trout')",
                                      "UPDATE menu SET house_dish = 30 WHERE menu_id = 3"]), profile=MENUS_PROFILE)
    assert r["ok"], r["reasons"]


def test_a_sampled_speaker_name_stored_in_the_database_is_rejected(menus):
    ins, sql = "I'm {} and menu ID 3 is mine: set the price of item 13 to 4.5.", ["UPDATE item SET price = 4.5 WHERE item_id = 13"]
    assert mreasons(menus, ins.format("Grace Kim"), sql, speaker="Grace Kim") == ["speaker_name_taken"]
    assert mreasons(menus, ins.format("Grace Kimura"), sql, speaker="Grace Kimura") == []


def test_a_quoted_name_of_another_row_is_a_mismatch(menus):
    sql = ["UPDATE item SET price = 4.5 WHERE item_id = 13"]
    assert mreasons(menus, "Menu ID 3, 'Menu 3': on item 13 ('dish 13') set the price to 4.5.", sql) == []
    assert mreasons(menus, "Menu ID 3, 'Menu 3': on item 13 ('dish 14') set the price to 4.5.", sql) == ["name_mismatch: dish.name"]
    assert mreasons(menus, "Menu ID 3, 'Menu 4': set the price of item 13 to 4.5.", sql) == ["name_mismatch: menu.name"]
    # the old dish is the item's parent before the change; a new name the SQL writes is no claim about a row
    assert mreasons(menus, "Menu ID 3: on item 13, replace 'dish 13' with dish 5.", ["UPDATE item SET dish_id = 5 WHERE item_id = 13"]) == []
    assert mreasons(menus, "Menu ID 3: rename it to 'Menu 4'.", ["UPDATE menu SET name = 'Menu 4' WHERE menu_id = 3"]) == []
    assert mreasons(menus, "I'm Ann and it's menu ID 3's item 13: set its price to 4.5.", sql) == []   # apostrophes
    assert check.quoted("I'm Ann, it's 'Menu 3' and “dish 2”") == {"menu 3", "dish 2"}


def test_a_row_wider_than_sqlite_function_arguments_is_still_recorded(tmp_path):
    cols = ", ".join(f"c{i} TEXT" for i in range(70))         # card_games.cards has 74 columns; a function takes 127 arguments
    path = make_db(tmp_path, "wide", f"CREATE TABLE card (id INTEGER PRIMARY KEY, name TEXT, {cols});"
                   "INSERT INTO card (id, name) VALUES (1, 'Lotus'), (2, 'Bolt');")
    prof = {"kind": "entity", "roots": [{"table": "card", "label": "card", "parents": []}],
            "persons": {"card": {"key": "id", "name_cols": ["name"], "same_as": []}}, "events": [], "attributes": [],
            "public": [], "exclude": [], "no_insert": [], "quirks": [], "description": "Cards.", "confirmed": True,
            "speaker_roles": ["a", "b", "c", "d"]}
    c = {"id": "w", "anchor_table": "card", "anchor_key": "id", "key_value": 1, "plan": {"task_type": "6_entity", "style": {}},
         "instruction": "Card ID 1, 'Lotus': set c69 to 'x1'.", "actions": [{"sql": "UPDATE card SET c69 = 'x1' WHERE id = 1"}]}
    r = check.run_check({"source": "test", "db": "wide", "path": path, "anchors": [], "fks": []}, c, profile=prof)
    assert r["ok"], r["reasons"]
```

- [ ] **Step 3: 跑测试，确认失败**

Run: `$P -m pytest -q tests/test_taskgen_check.py`
Expected: FAIL。实体任务被算成 `1_self` 或 `3_public_only`，没有新原因；`check.quoted` 不存在；宽表在实体模式下没有被处理。

- [ ] **Step 4: 实现 check.py：常量和辅助函数**

在 `INSTANTS = (...)` 之后加：

```python
ENTITY = "6_entity"
NAME_COL = re.compile(r"(?i)name$|^name|title$|owner|author|artist|director|commander|alderman")   # where names are kept
# a quote opened by an apostrophe (I'm, it's) is not a quote: it needs a non-letter before ' and after the closing '
QUOTED = re.compile(r"(?<![A-Za-z])'([^'\n]{2,80})'(?![A-Za-z])|\"([^\"\n]{2,80})\"|“([^”\n]{2,80})”|‘([^’\n]{2,80})’")
JSON_ARGS = 60   # columns per json_object(): SQLite lets a function take 127 arguments (card_games.cards has 74 columns)


def quoted(text):
    """The normalized strings an instruction puts in quotes ('Smoked Trout', "Menu 3")."""
    return {norm_literal(next(g for g in m.groups() if g is not None)) for m in QUOTED.finditer(text or "")}


def name_columns(db, tables):
    """[(table, column)] of the text columns that hold names or titles (NAME_COL) in the given tables."""
    out = []
    for t in sorted(tables):
        for r in db.execute(f"PRAGMA table_info({_q(t)})"):
            if NAME_COL.search(r[1]) and not re.search(r"(?i)int|real|num|float|double", r[2] or ""):
                out.append((t, r[1]))
    return out


def stored(db, cols, value):
    """The first (table, column) of cols where some row holds value (trimmed, case-insensitive), else None."""
    for t, c in cols:
        if db.execute(f"SELECT 1 FROM {_q(t)} WHERE lower(trim({_q(c)})) = ? LIMIT 1", (value,)).fetchone():
            return t, c
    return None


def person_name_stored(db, name):
    """Whether a sampled speaker name is stored in the database: as a whole value of a name column, or split over a
    first-name and a last-name column of one row (chicago_crime's alderman_first_name, alderman_last_name)."""
    n = norm_literal(name)
    tables = [t for (t,) in db.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")]
    if stored(db, name_columns(db, tables), n):
        return True
    first, _, last = n.partition(" ")
    for t in tables:
        cols = [r[1] for r in db.execute(f"PRAGMA table_info({_q(t)})")]
        f = next((c for c in cols if re.search(r"(?i)first.?name", c)), None)
        l = next((c for c in cols if re.search(r"(?i)last.?name|surname", c)), None)
        if f and l and db.execute(f"SELECT 1 FROM {_q(t)} WHERE lower(trim({_q(f)})) = ? AND lower(trim({_q(l)})) = ? LIMIT 1",
                                  (first, last)).fetchone():
            return True
    return False


def _json_row(cols, ref="OLD"):
    """json_object(...) of the columns, in chunks of JSON_ARGS merged with json_patch."""
    parts = [", ".join(f"'{c}', {ref}.{_q(c)}" for c in cols[i:i + JSON_ARGS]) for i in range(0, len(cols), JSON_ARGS)]
    expr = f"json_object({parts[0]})"
    for p in parts[1:]:
        expr = f"json_patch({expr}, json_object({p}))"
    return expr
```

在 `def run_check(` 之前加：

```python
def name_mismatches(db, profile, tracer, cand, stmts, seen):
    """A quoted name the database stores, but in no row the task touches (before or after it) and in none of their
    parent rows (design 2026-10-04 §3.4): DySQL's cookbook named one ingredient and wrote another's ID in 16 of 51
    tasks, and the verifier sees no rows. Values the SQL itself writes or matches are new names, not claims."""
    key = profile["persons"][cand["anchor_table"]]["key"]
    cur = db.execute(f"SELECT * FROM {_q(cand['anchor_table'])} WHERE {_q(key)} = ?", (cand["key_value"],))
    rows = [(cand["anchor_table"], dict(zip([d[0] for d in cur.description], r))) for r in cur.fetchall()] + list(seen)
    for t, r in list(rows):
        for cols, parent, ref_cols in tracer.up.get(t, []):
            vals = [r.get(c) for c in cols]
            if any(v in (None, "") for v in vals):
                continue
            try:
                cur = db.execute(f"SELECT * FROM {_q(parent)} WHERE " + " AND ".join(f"{_q(c)} = ?" for c in ref_cols) + " LIMIT 3", vals)
            except sqlite3.Error:
                continue
            rows += [(parent, dict(zip([d[0] for d in cur.description], x))) for x in cur.fetchall()]
    near = {norm_literal(v) for _, r in rows for v in r.values() if isinstance(v, str)}
    written = {norm_literal(x) for s in stmts for x in literals(s)}
    cols = name_columns(db, db_profile.scope_tables(profile))
    return [f"name_mismatch: {hit[0]}.{hit[1]}" for s in sorted(quoted(cand["instruction"]) - near - written)
            if (hit := stored(db, cols, s))]


def entity_reasons(db, profile, tracer, speaker_ids, cand, stmts, labels, writes, seen, new_public):
    """What an entity task may not do (design 2026-10-04 §3.4), checked on the database after its statements ran."""
    out = ["other_person"] if "other" in labels else []
    out += [f"root_insert: {w['table']}" for w in writes if w["label"] == "new_person"]
    lookups = {}
    for x in profile.get("new_lookup") or []:
        e = db_profile.parse_edge(x["via"])
        lookups.setdefault(e.parent, []).append((e, x["name_cols"]))
    out += [f"public_write: {w['op']} {w['table']}" for w in writes
            if w["label"] == "public" and (w["op"] != "INSERT" or w["table"] not in lookups)]
    if "own" not in labels and any(x != "noop" for x in labels):
        out.append("no_own_write")
    for table, new in new_public:
        used = False
        for e, names in lookups.get(table, []):
            cur = db.execute(f"SELECT * FROM {_q(e.child)} WHERE " + " AND ".join(f"{_q(c)} = ?" for c in e.cols) + " LIMIT 50",
                             [new.get(c) for c in e.ref_cols])
            cols = [d[0] for d in cur.description]
            used = used or any(tracer.trace(e.child, dict(zip(cols, r))) & speaker_ids for r in cur.fetchall())
            same = " AND ".join(f"lower(trim({_q(c)})) = lower(trim(?))" for c in names)
            if db.execute(f"SELECT COUNT(*) FROM {_q(table)} WHERE {same}", [new.get(c) for c in names]).fetchone()[0] > 1:
                out.append(f"lookup_name_taken: {table}")
        if table in lookups and not used:
            out.append(f"lookup_unreferenced: {table}")
    name = ((cand.get("plan") or {}).get("style") or {}).get("name")
    if name and person_name_stored(db, name):
        out.append("speaker_name_taken")
    out += name_mismatches(db, profile, tracer, cand, stmts, seen)
    return list(dict.fromkeys(out))   # one reason per kind and table
```

- [ ] **Step 5: 实现 check.py：接进 `run_check`**

1. `scope = db_profile.scope_tables(profile)` 那个 if/else 之后加：

```python
    entity = bool(profile) and db_profile.kind(profile) == "entity"
```

2. `speaker_in_db = ...` 一行上方加注释 `# 6_entity is not 5_proxy, so speaker_in_db holds: the entity's rows are "own" the way a speaker's are`。

3. 触发器那段改成：

```python
    for t in scope:
        need = {c for cols, _, _ in tracer.up.get(t, []) for c in cols} | ({tracer.persons[t]} if t in tracer.persons else set())
        if entity:   # the whole row before the change: the names it held belong to the task (name_mismatches)
            need = {r[1] for r in db.execute(f"PRAGMA table_info({_q(t)})")}
        if need:
            db.execute(f"CREATE TEMP TRIGGER {_q('_u_' + t)} BEFORE UPDATE ON main.{_q(t)} BEGIN "
                       f"INSERT INTO _old VALUES ('{t}', {_json_row(sorted(need))}); END")
```

4. `stmts, labels, executed = [], [], []` 那一行之后加 `seen, new_public = [], []   # rows the task touched (before and after); new public rows`。

5. `_old` 那段循环改成：

```python
                for (j,) in db.execute("SELECT j FROM _old WHERE tbl = ? LIMIT 50", (table,)).fetchall():
                    old = json.loads(j)
                    holders |= tracer.trace(table, old)
                    seen.append((table, old))
                seen += [(table, dict(zip(rcols, r))) for r in rs[:50]]
```

6. `labels.append(lab)` 之后加：

```python
                if entity and lab == "public" and op == "INSERT":
                    new_public += [(table, dict(zip(rcols, r))) for r in rs]
```

7. `if any(NONDET.search(s) ...` 之前，与它同一层，加：

```python
        if entity:
            out["reasons"] += entity_reasons(db, profile, tracer, speaker_ids, cand, stmts, labels, out["writes"], seen, new_public)
```

8. `out["task_type"] = task_group(...)` 之后加：

```python
    if entity and out["task_type"] not in (None, "7_no_change"):
        out["task_type"] = ENTITY
```

- [ ] **Step 6: 跑测试，确认通过**

Run: `$P -m pytest -q`
Expected: 全部通过，为 207 + 7 = 214 passed。

- [ ] **Step 7: 确认人物库候选的检查结果不变**

Step 1 的后台任务跑完以后：

```bash
cd $REPO/taskgen/v2 && $P $S/recheck.py $S/recheck_after.jsonl && cmp $S/recheck_before.jsonl $S/recheck_after.jsonl && echo SAME
```
Expected: `SAME`。不一样就用 `diff <(...) <(...) | head` 找出不同的 id，修到一样为止。改动只能影响实体 profile。

- [ ] **Step 8: 提交**

```bash
cd $REPO && git add taskgen/v2/taskgen_v2/check.py taskgen/v2/tests/test_taskgen_check.py
git commit -m "feat(taskgen v2): the check's entity rules: own rows only, new lookup rows, speaker names, quoted names"
```

---

### Task 5: 校验的实体说明、校准的输入、统计；设计文档写回

**Files:**
- Modify: `taskgen/v2/taskgen_v2/verify.py`、`taskgen/v2/taskgen_v2/calibrate.py`、`taskgen/v2/taskgen_v2/metrics.py`
- Modify: `taskgen/v2/scripts/taskgen.py`（`cmd_verify` 的说明）、`scripts/verify_calibrate.py`（`--env`、`--skip`）、`scripts/task_stats.py`（`--dysql-env`）
- Create: `taskgen/v2/data/dysql_entity_defects.json`
- Modify: `taskgen/v2/docs/2026-10-04-entity-tasks-design.md`
- Test: `tests/test_taskgen_verify.py`、`tests/test_taskgen_calibrate.py`、`tests/test_taskgen_metrics.py`

**Interfaces:**
- Produces：
  - `verify.ENTITY_NOTE`（带 `{label}` 的格式串）；
  - `verify.notes_for(profile) -> [str]`；
  - `calibrate.DYSQL_ENTITY = {"car": "car", "cookbook": "recipe"}`；
  - `calibrate.v2_items(roots)`：root 可以是单个库的目录；
  - `verify_calibrate.py build --env car --env cookbook --skip data/dysql_entity_defects.json`；
  - `task_stats.py --dysql-env car --dysql-env cookbook`；
  - metrics 的类型行改成 `"type 1/2/3/4/5/6/other"`。

- [ ] **Step 1: 写失败的测试**

`tests/test_taskgen_verify.py` 末尾加：

```python
def test_entity_profiles_tell_the_verifier_that_nobody_can_be_looked_up():
    from v2_fixtures import MENUS_PROFILE, SHOP_PROFILE
    assert verify.notes_for(SHOP_PROFILE) == []
    notes = verify.notes_for({**MENUS_PROFILE, "quirks": ["prices are in dollars."]})
    assert notes[0] == "prices are in dollars." and notes[1] == verify.ENTITY_NOTE.format(label="menu")
    assert notes[1].startswith("This database has no table of people") and "one menu record" in notes[1]
```

`tests/test_taskgen_calibrate.py` 末尾加：

```python
def test_v2_items_reads_database_folders_or_their_parent(tmp_path):
    d = tmp_path / "menu"
    d.mkdir()
    io.append_jsonl(str(d / "candidates.jsonl"), [{"id": "bird:menu:Menu:5:0", "instruction": "x", "actions": []},
                                                  {"id": "bird:menu:Menu:6:0"}])
    io.append_jsonl(str(d / "check.jsonl"), [{"id": "bird:menu:Menu:5:0", "ok": True}, {"id": "bird:menu:Menu:6:0", "ok": False}])
    for root in (str(tmp_path), str(d)):
        assert [(i["id"], i["db"]) for i in calibrate.v2_items([root])] == [("bird:menu:Menu:5:0", "bird:menu")]


def test_dysql_entity_databases_get_the_entity_note():
    from taskgen_v2 import verify
    dbs = calibrate.Databases()
    assert dbs.get("dysql:car")["notes"] == [verify.ENTITY_NOTE.format(label="car")]
    assert dbs.get("dysql:chinook")["notes"] == []
```

`tests/test_taskgen_metrics.py`：
- 第 48 行的断言改成 `m["type 1/2/3/4/5/6/other"] == "33.3% / 33.3% / 0.0% / 0.0% / 33.3% / 0.0% / 0.0%"`；
- 第 57 行改成 `m["type 1/2/3/4/5/6/other"] == "- / - / - / - / - / - / -"`。

- [ ] **Step 2: 跑测试，确认失败**

Run: `$P -m pytest -q tests/test_taskgen_verify.py tests/test_taskgen_calibrate.py tests/test_taskgen_metrics.py`
Expected: FAIL，报 `AttributeError: ... 'notes_for'`、v2_items 返回空、`KeyError: 'type 1/2/3/4/5/6/other'`。

- [ ] **Step 3: 实现**

`verify.py`，`NOTES = ...` 之后加：

```python
ENTITY_NOTE = ("This database has no table of people: the requester is not stored in it and cannot be looked up or "
               "authenticated. The request is about one {label} record, named by its ID; the requester's name, role or "
               "username is not used by the SQL.")


def notes_for(profile):
    """The data notes the verifier reads for a database: the profile's quirks, plus ENTITY_NOTE for an entity profile
    (design 2026-10-04 §3.5)."""
    notes = list(profile["quirks"])
    if profile.get("kind") == "entity":
        notes.append(ENTITY_NOTE.format(label=" or ".join(r["label"] for r in profile["roots"])))
    return notes
```

`calibrate.py`：
- import 加上 `verify`；
- `REASONS = ...` 之后加 `DYSQL_ENTITY = {"car": "car", "cookbook": "recipe"}   # DySQL's databases without people`；
- `Databases.get` 改成：

```python
    def get(self, key):
        if key not in self.cache:
            if key.startswith("dysql:"):
                env = key.split(":", 1)[1]
                rec = dysql.db_rec(env)
                path, prof = rec["path"], None
                notes = [verify.ENTITY_NOTE.format(label=DYSQL_ENTITY[env])] if env in DYSQL_ENTITY else []
            else:
                self.recs = self.recs or io.load_db_recs()
                self.profiles = self.profiles or db_profile.load()
                rec, prof = self.recs[key], self.profiles[key]
                path = io.resolve_db_path(rec["path"])
                notes = verify.notes_for(prof)
            self.cache[key] = {"rec": rec, "path": path, "profile": prof, "ddl": schema.ddl(path), "notes": notes}
        return self.cache[key]
```

- `v2_items` 第一行（`for d in sorted(...)`）改成：

```python
    dirs = [p for root in roots for p in ([root] if os.path.exists(os.path.join(root, "check.jsonl"))
                                           else glob.glob(os.path.join(root, "*")))]
    for d in sorted(p for p in dirs if os.path.isdir(p)):
```

  docstring 改成 "The v2 candidates under roots (database folders, or folders of them) that passed the check, ..."。

`metrics.py`：
- `TYPES` 末尾加 `"6_entity"`；
- `m["type 1/2/3/4/5/other"]` 的键改成 `"type 1/2/3/4/5/6/other"`。

`scripts/taskgen.py`：`cmd_verify` 里 `ddl, quirks = schema.ddl(...), prof["quirks"]` 改成 `ddl, quirks = schema.ddl(io.resolve_db_path(rec["path"])), verify.notes_for(prof)`。

`scripts/verify_calibrate.py`：
- `cmd_build` 里 `gold = calibrate.positives()` 改成：

```python
    gold = calibrate.positives(a.env)
    if a.skip:   # DySQL gold whose instruction and SQL disagree (data/dysql_entity_defects.json)
        with open(a.skip, encoding="utf-8") as f:
            skip = set(json.load(f)["ids"])
        gold = [g for g in gold if g["id"] not in skip]
```

- build 子命令加两个参数：

```python
    p.add_argument("--env", action="append", help="only these DySQL databases as positives (default: all 13)")
    p.add_argument("--skip", help="JSON file whose 'ids' are DySQL gold to leave out")
```

`scripts/task_stats.py`：
- 加参数 `ap.add_argument("--dysql-env", action="append", help="only these DySQL databases in the DySQL column (car, cookbook)")`；
- DySQL 那段改成：

```python
        recs = metrics.from_dysql(cache)
        if a.dysql_env:
            recs = [r for r in recs if r["db"] in a.dysql_env]
        cols["DySQL" + (" " + "+".join(a.dysql_env) if a.dysql_env else "")] = metrics.compute(recs)
```

`data/dysql_entity_defects.json`（只有 DySQL 公开题的 id，可以进 git）：

```json
{
 "note": "DySQL car/cookbook gold whose instruction names another row than its SQL writes (cookbook: ingredient name against its ID, or an ID that does not exist) or whose SQL writes a value outside the data (car: the country as text, a model_year outside 1970-1982). Read on 2026-10-02; left out of the verifier's positives.",
 "ids": ["dysql:car:3", "dysql:car:4", "dysql:car:9", "dysql:car:13", "dysql:car:21", "dysql:car:22",
         "dysql:cookbook:6", "dysql:cookbook:8", "dysql:cookbook:12", "dysql:cookbook:13", "dysql:cookbook:18",
         "dysql:cookbook:23", "dysql:cookbook:25", "dysql:cookbook:33", "dysql:cookbook:34", "dysql:cookbook:37",
         "dysql:cookbook:38", "dysql:cookbook:39", "dysql:cookbook:42", "dysql:cookbook:43", "dysql:cookbook:47",
         "dysql:cookbook:49"]
}
```

- [ ] **Step 4: 跑测试，确认通过**

Run: `$P -m pytest -q`
Expected: 全部通过，为 214 + 3 = 217 passed。再看一下 DySQL 的正样本数：

```bash
$P -c "
import sys, json; sys.path[:0] = ['.', '../common']
from taskgen_v2 import calibrate
g = calibrate.positives(['car', 'cookbook']); skip = set(json.load(open('data/dysql_entity_defects.json'))['ids'])
print(len(g), len([x for x in g if x['id'] not in skip]))"
```
Expected: `60 46`。写计划时实测：car 26 条过检查，其中 6 条有毛病；cookbook 34 条过检查，其中 8 条有毛病。

- [ ] **Step 5: 统计脚本冒烟**

```bash
$P scripts/task_stats.py --dysql-env car --dysql-env cookbook | head -4
```
Expected: 表头一列叫 `DySQL car+cookbook`，`tasks` 是 78。

- [ ] **Step 6: 设计文档写回**

在 `docs/2026-10-04-entity-tasks-design.md` 里：
- §3.4 的拒绝列表加一条：题目引号里的名字如果是库里某个名字列的值，却不在任务碰到的行（改前改后）或它们的父行里，就拒（`name_mismatch`）。理由：cookbook 16/51 的毛病，而且校验模型看不到行数据。
- §3.5 的"负样本"一段改成：只用原有 5 种 SQL 破坏；名字和 ID 对不上由 §3.4 的检查拦，理由同上。正样本是 car/cookbook 过检查的题，去掉 `data/dysql_entity_defects.json` 里的 22 条，剩 46 条。
- §5 的表：`trees.py`、`schema.py` 也改（kind、root_label、已用的键值），`verify.py` 加 `notes_for`。
- §6 末条：已用的组合列在树的数据块里（`trees.taken`），不在键说明里，因为键说明按库生成，而已用组合按根行而不同。

- [ ] **Step 7: 提交**

```bash
cd $REPO && git add taskgen/v2/taskgen_v2/{verify,calibrate,metrics}.py taskgen/v2/scripts/{taskgen,verify_calibrate,task_stats}.py \
  taskgen/v2/data/dysql_entity_defects.json taskgen/v2/docs/2026-10-04-entity-tasks-design.md \
  taskgen/v2/tests/test_taskgen_{verify,calibrate,metrics}.py
git commit -m "feat(taskgen v2): the verifier knows entity databases have no people; calibration and stats inputs for them"
```

---

### Task 6: 起草实体 profile（关卡 1：用户确认）

**Files:**
- Modify: `taskgen/v2/data/db_profiles.json`（加实体 profile）
- Create: `taskgen/v2/docs/2026-10-0X-entity-profiles-review.md`（审阅页；X 是当天日期）
- 只放在 scratchpad：`$S/entity_dbs.md`（库的结构和样例行）、`$S/entity_profiles.json`（起草稿）

**Interfaces:**
- Consumes：Task 1 的字段和校验；`profile render --kind entity`。
- Produces：用户确认过的实体 profile；N（留下的库数）、Q = ⌈400/N⌉、CAP = ⌈300/N⌉，写进审阅页开头，Task 7–10 都用。

起草时的建议（写计划时只读过结构，具体以数据为准；`validate` 不过就照它说的改）：

| 库 | 根（label） | 事件（路径） | 公共 | new_lookup | 要注意 |
|---|---|---|---|---|---|
| bird:menu | `Menu`（menu） | `MenuPage`；`MenuItem`（经 MenuPage，2 跳，父 Dish） | Dish | `MenuItem.dish_id -> Dish.id`（name） | 272 MB；MenuItem 的 created_at、updated_at 不进比对 |
| bird:video_games | `game`（game），父 genre | `game_publisher`（父 publisher）；`game_platform`（2 跳，父 platform）；`region_sales`（3 跳，父 region） | genre, publisher, platform, region | `game.genre_id -> genre.id`（genre_name）；`game_publisher.publisher_id -> publisher.id`（publisher_name）；`game_platform.platform_id -> platform.id`（platform_name） | 根自己引用新行（Review Focus 2） |
| bird:airline | `Air Carriers`（carrier） | `Airlines`（父 Airports，ORIGIN/DEST） | Airports | — | Airlines 无主键，航班要靠日期加航班号定位；先数有航班的承运人有几个 |
| bird:chicago_crime | `District`（police district） | `Crime`（父 IUCR、FBI_Code、Ward、Community_Area） | IUCR, FBI_Code, Ward, Community_Area, Neighborhood | — | 只有 22 个分局，树最多 22 棵；Ward 存市议员姓名（说话人名字规则会用到） |
| bird:college_completion | `institution_details`（institution） | `institution_grads` | — | — | state_sector_* 和学校之间没有可用的边，放 exclude 或 public；62 列 |
| bird:food_inspection | `businesses`（business） | `inspections`；`violations` | — | — | owner_name 存的是真人名 |
| bird:restaurant | `generalinfo`（restaurant），父 geographic | —；属性 `location` | geographic | `generalinfo.city -> geographic.city`（city） | 表少，多是 1–2 条写 |
| bird:shakespeare | `works`（work） | `chapters`；`paragraphs`（2 跳，父 characters） | characters | `paragraphs.character_id -> characters.id`（CharName） | 段落文本长（MAX_VALUE_CHARS 会截断） |
| bird:university | `university`（university），父 country | `university_year`；`university_ranking_year`（父 ranking_criteria → ranking_system） | country, ranking_system, ranking_criteria | `university.country_id -> country.id`（country_name） | |
| bird:california_schools | `schools`（school） | —；属性 `frpm`、`satscores` | — | — | CDSCode 是文本键；49 列 |
| bird:card_games | `cards`（card），父 sets | `foreign_data`、`legalities`、`rulings`（经 uuid） | sets, set_translations | — | 262 MB；74 列（Review Focus 5） |
| spider2:Airlines | `bookings`（booking） | `tickets`；`ticket_flights`（2 跳，父 flights）；`boarding_passes`（2 跳） | flights, airports_data, aircrafts_data, seats | — | 没有声明的外键，边靠命中率；bookings 没有名字列（Review Focus 1）；表大，建树慢 |
| spider2:imdb_movies | `movies`（movie） | `genre`、`role_mapping`、`director_mapping`（父 names）；属性 `ratings` | names | — | ERD 放 exclude；names 是真人，说话人名字规则会查到 |
| spider1:bike_1 | `station`（station） | `status`；`trip`（经 start_station_id） | weather | — | 70 个站 |
| spider1:csu_1 | `Campuses`（campus） | `degrees`、`discipline_enrollments`、`enrollments`、`faculty`；属性 `csu_fees` | — | — | 23 个校区；复合主键（会用到已用的键值） |
| spider1:flight_4 | `airlines`（airline） | `routes`（父 airports，src/dst） | airports | `routes.dst_apid -> airports.apid`（name） | |

**建议不用的 6 个库**（审阅页里写明理由，用户可以要回来）：
- citeseer、genes、toxicology：科研数据，没有自然的"来改数据的人"；
- mental_health_survey：答卷属于匿名的答题人，替别人改答卷不自然，之前也没找到锚点；
- shooting：涉及真实警察和当事人的枪击事件，不适合编改数据的请求；
- wine_1：之前就没有合适的锚点，wine 表没有主键。

- [ ] **Step 1: 导出每个库的结构和样例**

```bash
cd $REPO/taskgen/v2 && $P - <<'EOF' > $S/entity_dbs.md
import sys, json; sys.path[:0] = [".", "../common"]
from taskgen_v2 import io, schema, trees
from taskgen_common.db_select import _q
DBS = ["bird:menu", "bird:video_games", "bird:airline", "bird:chicago_crime", "bird:college_completion", "bird:food_inspection",
       "bird:restaurant", "bird:shakespeare", "bird:university", "bird:california_schools", "bird:card_games", "spider2:Airlines",
       "spider2:imdb_movies", "spider1:bike_1", "spider1:csu_1", "spider1:flight_4"]
recs = io.load_db_recs()
for k in DBS:
    rec = recs[k]; c = trees.open_ro(io.resolve_db_path(rec["path"]))
    print(f"\n# {k}\nFKs: " + "; ".join(f"{f['table']}.{f['col']} -> {f['ref_table']}.{f['ref_col']} ({f['source']}, hit {f['hit']})" for f in rec["fks"]))
    for t, v in schema.pk_info(c).items():
        n = c.execute(f"SELECT COUNT(*) FROM {_q(t)}").fetchone()[0]
        print(f"\n## {t}: {n} rows, pk {v['cols']}, unique {schema.unique_columns(c, t)}")
        cur = c.execute(f"SELECT * FROM {_q(t)} LIMIT 3")
        for r in cur.fetchall():
            print("- " + json.dumps({d[0]: (str(x)[:80] if x is not None else None) for d, x in zip(cur.description, r)}, ensure_ascii=False))
EOF
wc -l $S/entity_dbs.md
```

- [ ] **Step 2: 起草 profile**

逐库读 `$S/entity_dbs.md`，必要时再用 SQL 查数据，把起草稿写进 `$S/entity_profiles.json`，格式是 `{db_key: profile}`。每份 profile：
- 必须有全部 `FIELDS`，加上 `kind: "entity"`、`speaker_roles`（4–6 条，贴合领域，写清此人和实体的关系）、`new_lookup`（可以是空列表）；
- 另外写 `"notes": ["Claude: drafted from the schema and data on <date>"]`、`"draft": {"model": "claude", "rounds": 1, "errors": []}`、`"confirmed": false`；
- `description` 写 1–3 句，说清库里有什么、根是什么、事件是什么；
- `quirks` 只写对过数据的事实（拼错的列名、奇怪的编码、空值多的列）。人物库那次的教训：padded 值不能把尾部空格抄进 SET（见 memory `taskgen-v2-profile-factcheck`）。

- [ ] **Step 3: 合并并校验**

```bash
cd $REPO/taskgen/v2 && $P - <<EOF
import json, sys; sys.path[:0] = [".", "../common"]
from taskgen_v2 import db_profile
ps = db_profile.load(); new = json.load(open("$S/entity_profiles.json", encoding="utf-8"))
assert not set(new) & set(ps), set(new) & set(ps)
ps.update(new); db_profile.save(ps); print(len(new), "added")
EOF
$P scripts/taskgen.py profile check --kind entity
```
Expected: 每个库都是 `ok, not confirmed`。有问题就改 `$S/entity_profiles.json`，重新合并（先删掉 `data/db_profiles.json` 里这几个键），直到全部 ok。

- [ ] **Step 4: 出审阅页和样例树**

```bash
$P scripts/taskgen.py profile render --kind entity --out docs/<当天日期>-entity-profiles-review.md \
  --trees-out results/entity_profile_trees.md --sample-trees 1
```

在审阅页开头手写一段中文说明：
- 用了哪些库，不用的 6 个各自的理由；
- 每库的 Q 和 CAP（16 个库时是 25 和 19）；
- 请用户逐库看根、事件、公共表、`speaker_roles`、`new_lookup` 和数据怪异点；
- 样例树在 `results/entity_profile_trees.md`（含数据行，不进 git）。

自己先读一遍样例树，确认每棵树都有 own 行，没有误标的 other。

- [ ] **Step 5: 提交草稿（未确认）**

```bash
cd $REPO && git add taskgen/v2/data/db_profiles.json taskgen/v2/docs/*-entity-profiles-review.md
git commit -m "data(taskgen v2): entity profile drafts for review"
```

- [ ] **Step 6: 关卡 1 —— 停下，请用户审**

把审阅页路径发给用户。问三件事：哪些库要改、要加回或去掉；每份 profile 是否确认；N 是否就此定下。等用户回复，按回复修改，然后逐库确认：

```bash
$P scripts/taskgen.py profile confirm --db <db_key>     # each kept database
$P scripts/taskgen.py profile check --kind entity        # every kept one: ok, confirmed
```

用户不要的库，从 `data/db_profiles.json` 删掉。算出 N、Q、CAP，写进审阅页开头。

```bash
cd $REPO && git add taskgen/v2/data/db_profiles.json taskgen/v2/docs/*-entity-profiles-review.md
git commit -m "data(taskgen v2): entity profiles confirmed by the user"
```

---

### Task 7: 试跑 menu 和 video_games（关卡 2）

**Files:** 只写 `results/menu/`、`results/video_games/`（不进 git）和 `$S/`。

**Interfaces:**
- Consumes：Task 6 确认的 profile 和 Q。
- Produces：两个库的候选和检查结果；`$S/pilot_read.md`，里面是 Claude 对每条过检查的题的判断（good，或 bad 加原因）。Task 8 把它转成 labels。

- [ ] **Step 1: 出题和检查**

```bash
cd $REPO/taskgen/v2
for DB in bird:menu bird:video_games; do
  $P scripts/taskgen.py trees --db $DB --n $Q --seed 0 && \
  $P scripts/taskgen.py generate --db $DB --workers 5 && \
  $P scripts/taskgen.py generate --db $DB --workers 5 --retry-errors && \
  $P scripts/taskgen.py check --db $DB
done
```
Expected：每库写出 Q 棵树和 Q 个候选，`checked Q, passed …`。GLM 合计约 5 分钟。

- [ ] **Step 2: 统计**

```bash
$P - <<'EOF'
import sys; sys.path[:0] = [".", "../common"]
from collections import Counter
from taskgen_v2 import io
for db in ("menu", "video_games"):
    cands = {c["id"]: c for c in io.read_jsonl(f"results/{db}/candidates.jsonl")}
    chk = io.read_jsonl(f"results/{db}/check.jsonl"); ok = [r for r in chk if r["ok"]]
    print(db, "candidates", len(cands), "pass", len(ok), f"{len(ok) / len(chk):.0%}")
    print("  reasons", Counter(x.split(":")[0] for r in chk for x in r["reasons"]).most_common())
    print("  computed types", Counter(r["task_type"] for r in ok))
    print("  speakers", Counter(c["plan"]["style"]["speaker"] for c in cands.values()))
    print("  new_lookup", sum(bool(c["plan"]["shape"].get("new_lookup")) for c in cands.values()),
          "words", sorted(len(c["instruction"].split()) for c in cands.values() if c.get("instruction"))[len(cands) // 2])
EOF
```

- [ ] **Step 3: 改名探针（名字和 ID 对不上，检查必须拦住）**

```bash
$P - <<'EOF'
import random, re, sys; sys.path[:0] = [".", "../common"]
from taskgen_v2 import check, db_profile, io
recs, n, caught = io.load_db_recs(), 0, 0
for key in ("bird:menu", "bird:video_games"):
    rec, prof = recs[key], db_profile.get(key)
    db = check._memory_copy(io.resolve_db_path(rec["path"]))
    cols = check.name_columns(db, db_profile.scope_tables(prof))
    ok = {r["id"] for r in io.read_jsonl(f"results/{rec['db']}/check.jsonl") if r["ok"]}
    for c in io.read_jsonl(f"results/{rec['db']}/candidates.jsonl"):
        if c["id"] not in ok:
            continue
        for s in sorted(check.quoted(c["instruction"])):
            hit = check.stored(db, cols, s)
            if not hit:
                continue
            t, col = hit
            other = db.execute(f'SELECT "{col}" FROM "{t}" WHERE lower(trim("{col}")) != ? AND "{col}" IS NOT NULL LIMIT 1 OFFSET ?',
                               (s, random.Random(c["id"]).randint(0, 50))).fetchone()
            if not other:
                continue
            bad = {**c, "instruction": re.sub(re.escape(s), other[0], c["instruction"], flags=re.I)}
            r = check.run_check(rec, bad, profile=prof)
            n += 1; caught += any(x.startswith(("name_mismatch", "literal_missing")) for x in r["reasons"])
            break
print(f"renamed {n}, rejected {caught}")
EOF
```
Expected: `rejected == renamed`。漏掉的逐条看：如果名字没加引号，检查本来就管不到，记进试跑记录；其他原因要修检查。

- [ ] **Step 4: Claude 逐条读过检查的题**

把每条过检查的候选的 instruction、SQL 和执行效果都读一遍。可以用 `scripts/verify_calibrate.py` 的 `block()` 格式，或者自己写个片段打出来。读完写进 `$S/pilot_read.md`，每条一行：`id | good/bad | 原因（calibrate.REASONS 之一）| 备注`。重点看这几项：
- 说话人和抽到的类型是否一致；
- 实体名和 ID 是否对得上；
- 新查找行的名字是否真是新的；
- 有没有改到别的实体；
- 题目给的信息是否足够 agent 走到同一个终态。

- [ ] **Step 5: 关卡 2 —— 判断能不能继续**

通过条件，三条都满足：
- 两库合计过检查 ≥ 90%；
- 过检查的题里算出的类型都是 `6_entity`（不一致 ≤ 3%）；
- Step 4 读出的坏题 ≤ 10%，而且没有系统性的问题（同一个毛病出现 3 次以上算系统性）。

不满足就停下：把数字和典型问题（只给 id 和问题描述）报告给用户，提出要改 prompt 还是改 profile。改完对这两个库删掉 `results/<db>/` 重跑。

---

### Task 8: 校验模型校准（关卡 3）

**Files:** `results/entity_calib/`（不进 git）。

**Interfaces:**
- Consumes：Task 5 的 `--env`、`--skip`、`v2_items`；Task 7 的 `$S/pilot_read.md`。
- Produces：`results/entity_calib/report.md` 和是否通过的结论。

- [ ] **Step 1: 建校准集**

```bash
cd $REPO/taskgen/v2 && D=results/entity_calib
$P scripts/verify_calibrate.py build --dir $D --env car --env cookbook --skip data/dysql_entity_defects.json \
  --labeled results/menu --labeled results/video_games --per-kind-dysql 10 --per-kind-v2 10
```
Expected：打出的计数里，positives 约 46，labeled 约等于两库过检查的条数，negatives 中 dysql 和 v2 每种最多 10 条。

- [ ] **Step 2: 写 labels**

把 `$S/pilot_read.md` 转成 `$D/labels.jsonl`，每行 `{"id", "label", "reason", "unsure", "note", "by": "claude"}`；拿不准的标 `"unsure": true`。

- [ ] **Step 3: 投票**

```bash
$P scripts/verify_calibrate.py vote --dir $D --models deepseek-v4.1-flash:2 --workers 3
$P scripts/verify_calibrate.py vote --dir $D --models deepseek-v4.1-flash:3 --undecided --workers 3
$P scripts/verify_calibrate.py report --dir $D
```
Expected：约 400 票，约 25 分钟；`report.md` 有三种规则的各项比例。

- [ ] **Step 4: 分歧给用户复核**

```bash
$P scripts/verify_calibrate.py review --dir $D --votes 3
```
`review.md` 里的条数大于 0 时，停下请用户逐条回复 good 或 bad。把回复追加到 labels（`"by": "user"`），再跑一次 `report`。

- [ ] **Step 5: 关卡 3**

用"3 votes, 2 Yes"这条规则看，通过条件：
- 负样本全部被拒；
- 标注为好的题通过 ≥ 95%；
- 正样本（DySQL car/cookbook 的干净题）通过 ≥ 90%（写进记录，低了要分析原因）。

不通过就停下，报告用户。可能的处理有：改 `ENTITY_NOTE`、加数据说明、换票数规则。

---

### Task 9: 试跑库的校验、去重、转换，以及 4B 关卡（关卡 4）

**Files:** `results/<db>/`、`output/<db>/`、`output/manifest.json`、`DySQL-Bench/results/taskgen_v2/entity_pilot/`（都不进 git）。

**Interfaces:**
- Consumes：Task 7 的候选，Task 6 的 CAP。
- Produces：两库的 `output/<db>/tasks.jsonl`，manifest 里多两个库；4B 的通过率。

- [ ] **Step 1: 校验、去重、转换**

```bash
cd $REPO/taskgen/v2
for DB in bird:menu bird:video_games; do
  $P scripts/taskgen.py verify --db $DB --workers 3 && \
  $P scripts/taskgen.py dedup --db $DB --per-db $CAP && \
  $P scripts/taskgen.py convert --db $DB && \
  $P scripts/taskgen.py stats --db $DB
done
```
Expected：`n_verify_unvoted` 是 0；每库 selected ≤ CAP。

- [ ] **Step 2: 4B 跑全部试跑题**

先确认 GB10 上两个服务都在（起服务的方法见 memory `gb10-serving-facts`）：

```bash
for p in 8001 8002; do curl -s -m 5 http://127.0.0.1:$p/v1/models; echo; done
cd $REPO/DySQL-Bench
for DB in menu video_games; do
  OUT=results/taskgen_v2/entity_pilot/$DB && mkdir -p $OUT
  TASKGEN_MANIFEST=$REPO/taskgen/v2/output/manifest.json $P run.py --env gen:$DB --task-split train --num-trials 1 \
    --model qwen3-4b --model-api http://127.0.0.1:8002 \
    --user-model qwen2.5-72b-awq --user-model-api http://127.0.0.1:8001 \
    --user-strategy llm --max-concurrency 8 --log-dir $OUT 2>&1 | tee $OUT/run.log | tail -n 3
done
$P scripts/summarize.py "results/taskgen_v2/entity_pilot/*/*.json" | tee results/taskgen_v2/entity_pilot/summary.md
```
Expected：约 2 × CAP 题全部跑完，`summary.md` 有 overall。

- [ ] **Step 3: 关卡 4**

拿通过率和这几个数对照：DySQL 上的 car 44.4%、cookbook 17.6%，4B 在 DySQL 上总体 29.8%，以及 v2 人物题试点的值（`docs/2026-10-02-pilot.md`）。约 40 题的误差约 ±15 个百分点。
- 低于 10% 或高于 70%：停下。抽 10 条轨迹看是题的问题还是 agent 的问题，然后报告用户。
- 特别看一项：agent 因为"无法验证身份"而拒绝或转人工的题有几条（在轨迹里搜 authenticat、identity），记进记录。这是设计里保留策略文本的那个取舍。

---

### Task 10: 全量、统计和记录

**Files:**
- `results/<db>/`、`output/`（不进 git）
- Create: `taskgen/v2/docs/<日期>-entity-run.md`（只写计数和 id）
- 记忆：`taskgen-v2-entity-design.md` 更新

**Interfaces:**
- Consumes：前面所有任务；Q、CAP、逐库闸门。
- Produces：约 300 道实体题进 `output/` 和 manifest；运行记录。

- [ ] **Step 1: 其余库出题和检查（后台）**

```bash
cd $REPO/taskgen/v2 && cat > $S/entity_generate.sh <<EOF
P=$P; cd $REPO/taskgen/v2
for DB in <除 menu、video_games 外确认留下的库，空格分隔>; do
  \$P scripts/taskgen.py trees --db \$DB --n $Q --seed 0 && \
  \$P scripts/taskgen.py generate --db \$DB --workers 5 && \
  \$P scripts/taskgen.py generate --db \$DB --workers 5 --retry-errors && \
  \$P scripts/taskgen.py check --db \$DB
done > $S/entity_generate.log 2>&1
echo "DONE \$(date)" >> $S/entity_generate.log
EOF
bash $S/entity_generate.sh    # run_in_background; ~14 × Q GLM calls, about 30–40 minutes
```

- [ ] **Step 2: 逐库闸门**

每个库检查完，套用计划 5 的规则：过检查低于 92% 且被拒至少 3 条，或某一种拒绝原因超过候选的 3% 且至少 3 条，就先不校验，把原因计数报告给用户。没被拦下的库进 Step 3。

- [ ] **Step 3: 校验、去重、转换（逐库）**

```bash
for DB in <过了闸门的库>; do
  $P scripts/taskgen.py verify --db $DB --workers 3 && \
  $P scripts/taskgen.py dedup --db $DB --per-db $CAP && \
  $P scripts/taskgen.py convert --db $DB
done
```

- [ ] **Step 4: 抽查**

每库随机读 10 条最终题（`random.Random(0)`），看 Task 7 Step 4 列的那几项。坏题的 id 写进 `results/<db>/excluded.jsonl`（`{"id", "reason", "by": "claude"}`），然后对这个库重跑 dedup 和 convert。坏题超过 2/10 的库停下报告用户。

- [ ] **Step 5: 合计和对比**

```bash
cd $REPO/taskgen/v2 && mkdir -p results/entity_view
for d in <所有实体库目录名>; do ln -sfn ../$d results/entity_view/$d; done
$P scripts/task_stats.py --dysql-env car --dysql-env cookbook --set entity=results/entity_view --out $S/entity_stats.md
$P - <<'EOF'
import json, sys; sys.path[:0] = [".", "../common"]
from collections import Counter
from taskgen_v2 import io
m = json.load(open("output/manifest.json"))
rows = [r for k, v in m.items() for r in io.read_jsonl("output/" + v["tasks"]) if r["meta"].get("task_type") == "6_entity"]
print("entity tasks", len(rows), Counter(r["meta"]["db"] for r in rows))
print("speakers", Counter(r["meta"]["plan"]["style"]["speaker"] for r in rows))
print("new_lookup", sum(bool(r["meta"]["plan"]["shape"].get("new_lookup")) for r in rows))
EOF
```
Expected：合计 270–330 题。说话人比例接近 55/17/28（name / role+username / none）。

- [ ] **Step 6: 不足 270 题时补出**

挑候选都用上了、但还没到 CAP 的库，而且根行数要比 Q 多（csu_1、chicago_crime 的根行太少，不能补）。补的做法：
1. `trees --n <Q + 10>`，会追加新树；
2. `generate`，只出新树的题；
3. `check`，套用逐库闸门；
4. `verify`；
5. `dedup --per-db <新的 CAP>`，让合计约等于 300；
6. `convert`。

只补到够数为止。

- [ ] **Step 7: 记录**

写 `docs/<日期>-entity-run.md`，中文，只写计数和 id，不摘题目内容。内容：
1. 做法和库；
2. 每库的候选、过检查、过校验、最终题数，以及拒绝原因计数；
3. 关卡 1–4 的结果，含 4B 通过率和"无法验证身份"的条数；
4. `$S/entity_stats.md` 的对比表（对 DySQL car+cookbook）；
5. 说话人比例、新查找行的条数；
6. 遗留问题。

```bash
cd $REPO && git add taskgen/v2/docs/*-entity-run.md && git commit -m "docs(taskgen v2): the entity task run"
```

- [ ] **Step 8: 更新记忆**

在 memory 的 `taskgen-v2-entity-design.md` 里补上：
- 实施完成的日期和提交范围；
- 最终题数；
- 4B 通过率；
- 遗留问题。

`MEMORY.md` 那一行的 hook 也同步改掉。
