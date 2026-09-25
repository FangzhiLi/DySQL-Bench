# 训练数据生成：候选库筛选条件

目标：从 BIRD 1.0、Spider2.0-lite（仅 SQLite 任务用到的 30 个库）、Spider 1.0、SynSQL-2.5M 中选库，生成 DySQL-Bench 风格（多轮、以写操作为主）的训练任务，用于 GRPO。DySQL 的 13 个库的统计见 `docs/dysql_db_info.md`。

## 原则：对齐结构特征，而不是尺寸统计

不按 DySQL 13 个库的均值（8.3 表/库、8.2 列/表、中位 110 行/表）去卡尺寸，原因：

1. 这 13 个库不是按设计选出来的分布。论文没有给选择标准；其中 music 和 chinook 是同一份数据，human_resources 全库只有 37 行。
2. 训练集要覆盖 eval，而不是复制 eval 的均值。EU_soccer（199 列）和 complex_oracle（140 列，106 万行）两个库占了 39% 的任务；只落在中位数附近的训练集，模型见不到这种规模的 schema。所以尺寸按小/中/大分层覆盖，上界到约 200 列。
3. 决定能否生成 DySQL 风格任务的是结构。1,059/1,062 个 DySQL 任务含写操作，写操作集中在"有外键指向人物/主实体的事务表"（Match、sales、payment、Bowler_Scores、invoice_items 等）。

## 筛选条件

### A. 硬排除（防泄漏）

- DySQL 的 13 个库本身，以及其他 benchmark 里的同源副本：
  - Spider 1.0：`chinook_1`、`store_1`（Chinook）、`sakila_1`（Sakila/Pagila）、`soccer_1`（EU_soccer 去掉 Match）
  - BIRD：6 个原库，加 `movie_3`（Sakila）、`european_football_2`（EU_soccer）
  - Spider2-lite：7 个原库，加 `sqlite-sakila`、`northwind`（retail_world 是 Northwind 子集）
- 其他可能要报告的评测集用到的库（2026-09-25 决定）：
  - **Spider 1.0 的 dev（20 个）和 test（40 个）库。** CoSQL、SParC 与 Spider 用完全相同的库划分（train/dev/test = 140/20/40，两篇论文原文如此），评测就在这 60 个库上。研究计划第 2 步要和 MTSQL-R1 对比，它报告的就是 CoSQL/SParC。Spider 的 train 库本来就是 CoSQL/SParC 的训练库，可以用。
  - **Ergast F1 数据**：BIRD `formula_1`、Spider1 `formula_1`、Spider2 `f1`。BIRD-Interact full 版的 `sports_events` 是同一份数据，只是列被改名并打包成 JSON（样例行里车手 id、赛道 id 与 BIRD formula_1 一一对应），schema 比对查不出来，所以按名字排除。BIRD-Interact 其余 39 个库，与候选库的样例值比对没有发现同源（只比对了每张表公开的 3 行样例）。
  - **Spider 1.0 train 的 activity_1、college_3（2026-09-25 决定）：** 它们的 Student 表与 CoSQL/SParC 评测库 pets_1 同模板，包含度 0.57，略低于 0.6 的阈值，按名字排除。两个都要排除：college_3 原本是作为 activity_1 的重复库被去掉的。
  - **保留：** BIRD dev 和 Spider2-lite。BIRD 没有多轮版本，Spider2 我们不打算报告；DySQL 本身也用了 Spider2-lite 的库。
- 清单之外，再用 schema 重叠度兜底：把每个库表示成归一化的 `表.列` 集合，计算包含度 = 交集 ÷ 较小一方的大小，与任何一个被排除的库（DySQL、上面的清单、Spider dev/test）≥ 0.6 即视为同源并排除。例如 BIRD `world` 与 Spider dev 的 `world_1` 是同一份数据（包含度 1.0），因此被排除。用包含度而不用 Jaccard，是因为子集/超集副本（northwind ⊃ retail_world、soccer_1 ⊂ EU_soccer）的 Jaccard 只有 0.3–0.4。

另外，跨来源的重复库要去重，避免同一份数据被过度采样，例如：Spider1 `formula_1` / BIRD `formula_1` / Spider2 `f1`，Spider1 `baseball_1` / Spider2 `Baseball`，Spider1 `bike_1` / BIRD `bike_share_1`。

### B. 结构要求（2026-09-26 起：锚点 + 更新目标）

DySQL 的任务都是"围绕某个锚点行，修改它范围内的数据"。锚点多数是人，也可以是车、菜谱这类实体。依据是 `docs/data_gen/dysql_task_types.md` 对 1062 个任务的实测：
- 说话人是库里真人的占 67%，而且几乎都报名字。
- 22.6% 是库外的人代办、改库里人物的数据。
- 7.8% 是库外的人改实体数据（car/cookbook，库里没有人物表）。
- 19% 的任务会同时改不属于任何人的公共数据（产品、成本、歌单）。

打分只比较 DB 状态，人名和身份核对都不参与。所以硬条件是结构：

- **外键先验证再使用。**
  - 声明的、按名字推断的、按取值推断的（`winner_id`/`loser_id` 这类角色命名列）、人工补充的（`docs/data_gen/fk_extra.json`）外键，都要用数据算命中率。
  - 按取值推断还要求子表的不同值覆盖被引用键的 10% 以上，否则一张大而密的整数键表会"包含"任何一小组小整数 ID（DySQL 自己的库里就有 8 条这样的巧合，见 `docs/data_gen/fk_calibration.md`）。
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

### C. 尺寸区间（为小模型和 rollout 成本，不是为像 DySQL）

- 表数 3–20，全库列数 ≤ 约 250：保证 schema 能放进 Qwen3-1.7B/4B 的 prompt。
- 总行数 ≥ 200，≤ 约 300 万；文件 ≤ 300 MB。上限取 DySQL 里最大的库：EU_soccer 只有 22 万行，但文件有 299 MB（Match 表存了大段 XML 文本），它有 215 个任务、占 eval 的 20%，训练集的上限不能比它低。文件大小主要由文本列决定，和行数关系不大。32B 基线里 EU_soccer 每个任务都复制一次 DB，没出现问题，所以 rollout 复制成本在这个量级可以接受。
- 空表可以作为 INSERT 目标（DySQL 的 BowlingLeague 就往空表 `Bowler_Scores_Archive` 写了 87 次，大多是归档用的 INSERT）；只有 UPDATE/DELETE 作用在空表或没命中行时才是 no-op。因此生成任务时要检查：每条 gold UPDATE/DELETE 实际影响的行数 > 0。选库阶段不设行数下限，只要求锚点范围内有更新目标（见 B）。

### D. 配额

- 每库任务上限（例如 ≤ 80），避免复制 DySQL 里两个库占 39% 的偏斜。
- 按领域分层：体育、零售/订单、内容媒体、人事/教育、医疗/科学。

## 自动筛选结果（2026-09-26 更新：锚点规则）

实现：
- `DySQL-Bench/dysql_bench/db_select.py`：剖析、外键推断与验证、评估、去重。
- `DySQL-Bench/dysql_bench/db_anchor.py`：更新目标、锚点。
- 测试：`tests/test_db_select.py`、`tests/test_db_anchor.py`、`tests/test_dysql_acceptance.py`（DySQL 13 库验收）、`tests/test_select_dbs_cli.py`。
- 运行脚本：`DySQL-Bench/scripts/select_dbs.py`，用法见脚本开头，全量重跑约 4 分钟。

输出：
- 全量结果：`DySQL-Bench/results/db_select/db_select_all.csv`（不进 git）。
- 通过且去重后的候选：`docs/data_gen/candidate_dbs.csv`。
- 每个候选的完整锚点记录：`docs/data_gen/candidate_anchors.json`。
- 可读版：`docs/data_gen/candidate_dbs.md`，由 `scripts/render_candidates_md.py` 从 CSV 和 `docs/data_gen/db_notes.csv` 生成。
- 与旧的 34 个候选的对比：`docs/data_gen/2026-09-26-candidate-diff.md`。

规则怎么落地的：
- **行定位键：**
  - 单列 PK。
  - 没有 PK 时，用值唯一且非空的 id 类列（列名以 id / _key / _code 结尾），优先选列名里含表名的那一列。
  - 都没有时，找两列组成的复合键。复合键只记录，不作锚点。
- **推断 FK：**
  - **按名字：** 列名等于另一张表的行定位键，或列名为 `<表名>_id`，且目标唯一。
    - 跳过 guid 列，以及 `id`/`rowid`/`pk`/`key`/`code` 这类通用列名。
    - 本表自己的行键只能引用行数更多的表（1:1 扩展表）。
    - 复合主键的成员列照常推断。
  - **按取值：** 名字规则没覆盖的 id 类列，要同时满足：抽样的非空值 99% 以上落在唯一一张表的键里；不同值 ≥ 20 个；并覆盖被引用键的 10% 以上。
  - **人工补充：** `docs/data_gen/fk_extra.json`。
- **外键验证、更新目标、锚点：** 见 B。
- **拼凑库：** 只用有效和未验证的外键建图，最大连通分量覆盖的表 < 60% 时判为拼凑库，排除。
- **评测集排除：** `select_dbs.py --holdout spider1=<dev.json/test.json>` 读取评测问题文件里的全部 `db_id`；F1 系列和 activity_1、college_3 写在脚本的 `LEAK` 清单里。被排除的库的 schema 也加入比对参照。
- **去重：** schema 包含度 ≥ 0.6 视为同一个库，按 BIRD > Spider2 > Spider1 > SynSQL 的优先级只保留一份。计算前先去掉一个库里半数以上表共用的表名前缀（如 `olist_`），否则同一份 Olist 数据的三个副本因表名不同而认不出来。

| 来源 | 库总数 | 通过 | 重复 | 保留 | 主要淘汰原因（一个库可有多个） |
|---|---|---|---|---|---|
| BIRD（train 69 + dev 11） | 80 | 41 | 0 | 41 | 行数 17，文件 > 300 MB 15，泄漏/评测集 11，表数 10，可用外键 < 2 共 7，无锚点 3 |
| Spider2-lite（SQLite） | 30 | 10 | 2 | 8 | 泄漏/评测集 10，拼凑库 10，表数 3，可用外键 < 2 共 3，无锚点 3 |
| Spider 1.0 | 206 | 6 | 0 | 6 | 行数不足 183，泄漏/评测集 72（含 dev/test 60 个），表数 32，可用外键 < 2 共 31，无锚点 14 |
| SynSQL-2.5M | 16,583 | 0 | 0 | 0 | 全部行数不足（表内只有 0–2 行） |
| **合计** | | | | **55** | |

按锚点类型（`docs/data_gen/candidate_dbs.md` 的汇总表）：

| 来源 | 候选数 | 有带名字的人物锚点 | 只有 ID 的人物锚点 | 只有实体锚点 |
|---|---|---|---|---|
| BIRD | 41 | 18 | 7 | 16 |
| Spider2-lite（SQLite） | 8 | 3 | 3 | 2 |
| Spider 1.0 | 6 | 2 | 0 | 4 |
| **合计** | **55** | **23** | **10** | **22** |

逐库清单见 `docs/data_gen/candidate_dbs.md`。与旧 34 个相比：
- **退出 3 个：** superstore、thrombosis_prediction、college_3。
- **进入 24 个：** 其中 14 个是旧规则下"没有人物表"的库。

## 已决定事项与备注（2026-09-25，2026-09-26 更新）

1. **`simpson_episodes`（BIRD train）排除。** 它与 law_episode 是同一套 schema 模板（包含度 0.88），数据是另一部剧；训练它等于提前见过 DySQL 里 law_episode 的 schema。
2. **备注：超过 300 MB、暂不使用的库。** 只因文件大小被淘汰，数据本身合格，以后需要时可抽样缩小再用：
   - BIRD train：codebase_community（459 MB）、music_platform_2（1.5 GB）
3. **旧规则下"没有人物实体表"的 14 个库，在锚点规则下重新参与了筛选，14 个全部以实体锚点进入候选。** 它们是：
   - BIRD train：chicago_crime、college_completion、genes、mental_health_survey、menu、restaurant、shakespeare、university、video_games
   - BIRD dev：california_schools、card_games、toxicology
   - Spider2-lite：Airlines；Spider 1.0 train：flight_4

   明细见 `docs/data_gen/2026-09-26-candidate-diff.md`。不再有"第二阶段"：DySQL 自己的 car/cookbook 就是库外说话人改实体数据的任务，生成阶段按比例出这一类（见注 4）。

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

5. **给建树脚本的接口。**
   - `docs/data_gen/candidate_anchors.json` 里每个锚点有这些字段：
     - `table`：根。
     - `key`：用户报的 ID。
     - `kind`：锚点类型。
     - `names`：姓名或名称列。
     - `down`：子表，写入目标。
     - `up`：父表，背景信息和公共数据，对应 DySQL 数据池里的产品详情、负责员工。
     - `update_targets`：范围内能 UPDATE 的表。
   - 建树脚本另开计划。

6. **待用户确认：只有实体锚点的 22 个库的锚点选择。**
   - `docs/data_gen/db_notes.csv` 的 `entity_anchors_ok` 目前是执行者给的建议，每行备注都标了"待用户确认"。
   - mental_health_survey 和 wine_1 没有合适的实体锚点，去留待定：
     - mental_health_survey：答卷人只有 UserID，没有对应的表。
     - wine_1：只有产区、葡萄品种这类字典表。

## 数据来源

- 库级统计 dump、主题标签：`docs/benchmark_db_catalog.xlsx`（未进 git，由 scratchpad 脚本生成）
- 原始库文件和问题文件：`~/Documents/Isa/text2sql_bench/`（BIRD train/dev、Spider 1.0、Spider2-lite 本地 SQLite + jsonl、SynSQL；目录说明见其中的 README.md）
- DySQL 13 个库明细：`docs/dysql_db_info.md`
