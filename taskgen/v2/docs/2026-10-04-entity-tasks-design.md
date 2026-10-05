# 实体题设计：用无人物表的库出 `6_entity` 题

2026-10-04。接在 v2 全量（计划 5，23 个人物库）之后。本文是设计，实施计划另写。

## 1. 目标

DySQL 的 1062 题里有 83 题（7.8%）是"库外的人改实体数据"（`6_entity`），其中 76 题在 car 和 cookbook 这两个没有人物表的库。v2 的 23 个库都以人物为根，只出 1/2/3/5 型，这一类没有覆盖。

本设计用候选库里 22 个没有人物表的库出这类题，供 SFT/RL 训练用。

**成功标准：**

- 最终约 **300 题**（用户 2026-10-05 定）。依据：v2 人物题最终 3,131 题；DySQL 的 `6_entity` 在 v2 会出的几类题（1/2/3/5/6 型）中占 83/955 = 8.7%，3,131 × 83/872 ≈ 298。
- 题目形状接近 car/cookbook（§2），但不带它们的毛病（§2 末）。
- 现有 23 个库的行为不变：全部现有测试通过，对现有候选重跑检查，结果逐条相同。

训练时按类型和库抽样来定实际比例，所以每道题要带类型和库的标签（`meta.task_type`、`meta.db`，转换已有）。

## 2. 参照：car 和 cookbook 的 78 题

2026-10-02 全部读过，并拿题里的 ID 对过库。

- **形状：** 说话人自称某个实体的主人或编辑（"我的车""我的菜谱"），改这一行实体的属性，再改一两张通过外键挂在它下面的子表。库里没有表示归属的列，所以没有身份验证。
- **说话人：** 编的人名 43 题（55%），用户名或角色 13 题（17%），不报身份 22 题（28%）。
- **ID：** 几乎每题直接给实体 ID；car 有 2 题按名字查。
- **难题：** cookbook 的 6 道 hard 都是"新建一条配料，再用子查询挂到菜谱上"。
- **毛病，不照搬：**
  - cookbook 16/51 题里配料名和 ID 对不上，或 ID 不存在；gold 按 ID 写。
  - car 6/27 题往整数外键里插文本，或年份超出数据范围。
  - cookbook 12 题落在库里原有的空壳菜谱上。我们的库不一定有空壳，不模仿。

## 3. 做法：实体当根，复用 v2

v2 的"自己的行 / 公共行 / 别人的行"是沿外键往上追到根算出来的（`owners.Tracer`）。根是人还是菜谱，算法相同。所以不另起流水线，只让 profile 的根可以是实体。

### 3.1 profile

- 新字段 `kind`，取 `"person"`（缺省，现有 23 个库）或 `"entity"`。
- 实体类 profile 的根表（如 `Menu`）照旧填在 `roots` 和 `persons` 里：`key` 是主键，`name_cols` 是实体的名字列。字段名 `persons` 不改，含义放宽为"行的归属方"。
- 子表填 `events`，查找表填 `public`，其余字段含义不变。
- 实体类 profile 加字段 `speaker_roles`：本库 4–6 个说话人角色，每个写明此人和实体的关系，如 menu 的"a menu collection archivist cataloguing this menu"、video_games 的"a catalog manager at the game's publisher"。角色要贴合本库领域，不用 v2 那 16 个通用的公司角色。
- 校验（`db_profile.validate`）对实体类：`name_cols` 可以为空（有的实体没有名字列，题目里只用 ID 指它）；`speaker_roles` 必须有 4–6 条。人物类 profile 不允许出现 `speaker_roles`。
- 22 个库的 profile 由 Claude 读 schema 和数据起草，过 `validate`，出中文审阅表，用户逐个确认。找不到合适根的库（子表没有可用的键、数据不像有人会来改）不用，并在审阅表里写明原因。预计留下 16 个左右；citeseer、genes、toxicology、shooting、mental_health_survey、wine_1 预计不用。

### 3.2 建树

不改。选中的实体及其子表行标为 own，别的实体的行标为 other，查找表行标为 public。

### 3.3 出题（prompt）

- 实体类 profile 只出一种类型 `6_entity`。
- **说话人**不在库里。人设只活在 instruction 里：评测时用户模拟器只看到 instruction，并被要求 "stick to the personalities in the instruction"（`DySQL-Bench/dysql_bench/envs/user.py`）。所以人设由代码抽样后交给 GLM 写进题目，不让 GLM 自由编（v2 试跑时 GLM 自编的名字"Priya Raghavan"出现 6 次）。三种说话人按 car/cookbook 的 55/17/28 抽：

  | 说话人 | 占比 | 生成 | 第一句 |
  |---|---|---|---|
  | 编的人名 | 55% | 复用 v2 的名字池（48 名 × 48 姓）；其中一半再从本库 `speaker_roles` 抽一个角色，另一半只用"我的 X"口吻 | 名字（和角色），实体的名字和 ID |
  | 角色或用户名 | 17% | 各半：角色从本库 `speaker_roles` 抽；用户名由代码从名字池拼（如 `elena.f`、`rossi_88`、`user_4821`） | 角色或用户名，实体的名字和 ID |
  | 不报身份 | 28% | 无 | 实体的名字和 ID |

- **语气**沿用 v2 的 9 种（`prompt.TONES`），每题抽一种。
- 实体没有名字列时只给 ID。"ID 出现在前 25 个词"的规则不变。
- **写的范围：** 每条写都落在 own 行上。例外是"新查找行"形状（约 10% 的题）：先在一张 public 表里 INSERT 一行，再让一条 own 行引用它。这是 cookbook 难题的形状，也补一点 INSERT 偏低的缺口。`no_insert` 的表不参与。
- 写数量、两表、子查询、批量、归档沿用现有配置。子查询按实体名字查，条件是名字在表里唯一（`trees.lookup` 已有此判断）。
- `examples.json` 加 3–4 条手写的 `6_entity` 示例，三种说话人各至少一条，不用 car/cookbook 的数据。
- agent 策略文本（"先定位用户做身份验证"）原样保留：DySQL 的 car/cookbook 也用同一份策略，训练和评测保持一致。

### 3.4 检查（check）

- 实体类 profile 下算出的类型：写的标签都是 own，或 own 加"新查找行"形状允许的那条 public INSERT，记为 `6_entity`。
- 拒绝：
  - 写到别的实体的行（沿用 `other_person`）。
  - 没有任何一条写落在 own 行上。
  - 改或删已有的 public 行；public INSERT 的新行没有被 own 行引用。
  - 往根表 INSERT（那是新实体，不是改"我的"实体）。
  - 说话人的编造人名与库里某个文本列存的人名相同（大小写不敏感的整名匹配，如 food_inspection 的 `businesses.owner_name`）：agent 会误以为说话人在库里。
- 其余规则（`no_insert`、字面值必须出现在题目里、不改键、时钟、归档等）不变，不为产量放松。

### 3.5 校验（verify）

- 提示词里"说话人自己的行"在实体类 profile 下换成"题目所指的实体"。
- 校准，规模小：
  - 正样本：DySQL 的 car/cookbook 里名字和 ID 对得上、执行不出错的题。
  - 负样本：现有 5 种破坏法作用在新出的实体题上，加一种新的——把题目里的实体名或子项名换成库里另一行的名字，ID 不动。要求全部被拒。
  - 新题：约 60 条，Claude 标注，用户只看有分歧的。
- 票数沿用全量的做法（三票多数，前两票一致即停）。

### 3.6 统计和转换

- `metrics.TYPES` 加 `6_entity`。
- `task_stats.py` 增加一组对比：新题对 DySQL 的 car+cookbook 78 题，比写数量、操作类型、两表比例、说话人三种的比例、题目词数。
- 转换和 manifest 不改；实体库和人物库的题进同一个 manifest，靠类型和库区分。

## 4. 规模、时间、关卡

- 产出率按 v2 全量实测：过检查 98.1%，过校验 94.5%，候选到最终题 88%。实体题是新类型，留两成余量：共约 **400 个候选**，每库 ⌈400 / 用上的库数⌉ 个（16 个库时每库 25 个）。
- 每库最终封顶 ⌈300 / 用上的库数⌉ 题；某库不足时不由别的库补。合计不足 270 题时，在有余量的库补出候选。
- GLM：约 400 次调用，并发 5，约 40 分钟。校验约 850 票，ollama 并发 3，约 1 小时。

**关卡，按顺序，任一不过就停下报告：**

1. **profile：** 用户确认每一份。
2. **试跑：** menu 和 video_games 各出本库配额的候选（计入最终题）。过检查 ≥90%；要求类型和算出类型不一致 ≤3%；Claude 人工读 40 题，记录每一条有问题的题。
3. **校准：** 负样本全部被拒；Claude 标为好的新题通过 ≥95%。
4. **agent：** Qwen3-4B 随机跑 60 题。通过率与 DySQL 上的 car（44%）、cookbook（18%）和 v2 人物题的试点值对照，明显偏离（低于 10% 或高于 70%）就先查原因。
5. **全量：** 其余库出题、检查、校验、转换。沿用计划 5 的逐库闸门（过检查低于 92% 且被拒至少 3 条，或单一拒绝原因超过 3% 且至少 3 条，就先不校验、报告用户）。

## 5. 改动范围

| 文件 | 改动 |
|---|---|
| `taskgen_v2/db_profile.py` | `kind`、`speaker_roles` 字段及其校验；审阅表显示两者 |
| `data/db_profiles.json` | 加实体库的 profile |
| `taskgen_v2/prompt.py`、`examples.json` | `6_entity` 的类型文本、说话人三种的抽样（含用户名拼法）、新查找行形状、示例 |
| `taskgen_v2/check.py` | 实体类的类型判定和 §3.4 的拒绝（含编造人名撞库） |
| `taskgen_v2/verify.py`、`corrupt.py`、`calibrate.py` | 措辞、名字错配的破坏法、校准集 |
| `taskgen_v2/metrics.py`、`scripts/task_stats.py` | 类型和对比 |

`owners.py`、`trees.py`、`generate.py`、`convert.py`、`dedup.py` 预计不改。

## 6. 约定

- 在 `isa/data-gen` 上做。全量已跑完，不需要另开 worktree。
- 生成物（`results/`、`output/`）只在本地，不进 git。
- 已知问题一并处理一项：INSERT 撞唯一键（计划 6 待办）。实体题的子表多是连接表，更容易撞；键说明里要写明新行不能重复已有的组合。只对实体库生效，不重出人物库的题。
