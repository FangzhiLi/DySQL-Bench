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
- 清单之外，再用 schema 重叠度兜底：把每个库表示成归一化的 `表.列` 集合，计算包含度 = 交集 ÷ 较小一方的大小，≥ 0.6 视为同源。用包含度而不用 Jaccard，是因为子集/超集副本（northwind ⊃ retail_world、soccer_1 ⊂ EU_soccer）的 Jaccard 只有 0.3–0.4。

另外，跨来源的重复库要去重，避免同一份数据被过度采样，例如：Spider1 `formula_1` / BIRD `formula_1` / Spider2 `f1`，Spider1 `baseball_1` / Spider2 `Baseball`，Spider1 `bike_1` / BIRD `bike_share_1`。

### B. 结构要求

- **事务/事实表：** 至少一张，有 FK 指向主实体表，行数 ≥ 50。这是写操作的落点。
- **人物实体表（软条件）：** customer / employee / member / player / user / student / patient 等，用来给任务提供 persona。DySQL 的 cars、cookbook 没有这种表，persona 是编的，所以不设为硬条件，但要优先选有的库。
- **写目标表可定位：** 有 PK，或有可用的唯一自然键；否则 gold SQL 无法确定地命中一行。可以有意保留少量无 PK 的事实表（eval 里 complex_oracle 的 sales/costs 就是这样），但要标记出来。
- **库级 FK ≥ 2：** 才能出"先插父再插子 / 先删子再删父"这类多步任务。
  - 对 Spider2-lite 要放宽：它的库大多从 Kaggle CSV 导入，基本不声明 FK。可以接受按列名推断的 join key（如两表都有 `customer_id`），但要人工抽查。

### C. 尺寸区间（为小模型和 rollout 成本，不是为像 DySQL）

- 表数 3–20，全库列数 ≤ 约 250：保证 schema 能放进 Qwen3-1.7B/4B 的 prompt。
- 总行数 ≥ 200，≤ 约 300 万；文件 ≤ 300 MB。上限取 DySQL 里最大的库：EU_soccer 只有 22 万行，但文件有 299 MB（Match 表存了大段 XML 文本），它有 215 个任务、占 eval 的 20%，训练集的上限不能比它低。文件大小主要由文本列决定，和行数关系不大。32B 基线里 EU_soccer 每个任务都复制一次 DB，没出现问题，所以 rollout 复制成本在这个量级可以接受。
- 空表可以作为 INSERT 目标（DySQL 的 BowlingLeague 就往空表 `Bowler_Scores_Archive` 写了 87 次，大多是归档用的 INSERT）；只有 UPDATE/DELETE 作用在空表或没命中行时才是 no-op。因此生成任务时要检查：每条 gold UPDATE/DELETE 实际影响的行数 > 0。选库阶段只要求至少一张 ≥ 50 行的事务表。

### D. 配额

- 每库任务上限（例如 ≤ 80），避免复制 DySQL 里两个库占 39% 的偏斜。
- 按领域分层：体育、零售/订单、内容媒体、人事/教育、医疗/科学。

## 自动筛选结果（2026-09-25 更新）

实现：`DySQL-Bench/dysql_bench/db_select.py`（测试 `tests/test_db_select.py`），运行脚本 `DySQL-Bench/scripts/select_dbs.py`。全量结果写到 `DySQL-Bench/results/db_select/db_select_all.csv`（不进 git），通过且去重后的候选写到 `docs/data_gen/candidate_dbs.csv`。

规则怎么落地的：
- **行定位键：** 单列 PK；没有 PK 时，用值唯一且非空的 id 类列（列名以 id / _key / _code 结尾），优先选列名里含表名的那一列。
- **推断 FK：** 列名等于另一张表的行定位键，或列名为 `<表名>_id`，且目标唯一时才采纳。
- **事务表：** 有出向 FK（声明或推断），且行数 ≥ 50。
- **"可定位"：** 至少一张事务表有行定位键。
- **拼凑库：** FK 图最大连通分量覆盖的表 < 60% 时判为拼凑库，排除。
- **去重：** schema 包含度 ≥ 0.6 视为同一个库，按 BIRD > Spider2 > Spider1 > SynSQL 的优先级只保留一份。计算前先去掉一个库里半数以上表共用的表名前缀（如 `olist_`），否则同一份 Olist 数据的三个副本因表名不同而认不出来。

| 来源 | 库总数 | 通过 | 重复 | 保留 | 主要淘汰原因（一个库可有多个） |
|---|---|---|---|---|---|
| BIRD（train 69 + dev 11） | 80 | 39 | 0 | 39 | 行数 17，文件 > 300 MB 15，表数 10，事务表无键 9，泄漏 9，FK 8 |
| Spider2-lite（SQLite） | 30 | 8 | 2 | 6 | 拼凑库 10，泄漏 9，事务表无键 4，表数 3，无事务表 3 |
| Spider 1.0 | 206 | 10 | 2 | 8 | 行数不足 183，无事务表 182 |
| SynSQL-2.5M | 16,583 | 0 | 0 | 0 | 全部因行数不足/无事务表淘汰（表内只有 0–2 行） |
| **合计** | | | | **53** | 其中 37 个有人物实体表；16 个没有（如 genes、toxicology、world、Airlines、flight_2） |

保留的库：
- **BIRD：** address, beer_factory, books, car_retails, chicago_crime, college_completion, computer_student, disney, food_inspection_2, genes, legislator, menu, mental_health_survey, movie, movielens, olympics, professional_basketball, public_review_platform, regional_sales, restaurant, retail_complains, shakespeare, shipping, social_media, student_loan, superstore, synthea, university, video_games, world, california_schools, card_games, debit_card_specializing, financial, formula_1, student_club, superhero, thrombosis_prediction, toxicology
- **Spider2-lite：** AdventureWorks、Airlines、Brazilian_E_Commerce（E_commerce、electronic_sales 是同一份 Olist 数据，已去重）、IPL、WWE、school_scheduling。除 school_scheduling 外，其余 5 个的 FK 全靠推断，要人工抽查
- **Spider 1.0：** aan_1, car_1, college_2, college_3, csu_1, flight_2, flight_4, hr_1。formula_1、world_1 与 BIRD 同源，已去重

待决定：
1. **`simpson_episodes` 算不算泄漏。** 它与 law_episode 是同一套 schema 模板（包含度 0.88），但数据是另一部剧。目前按泄漏排除（训练它等于提前见过 law_episode 的 schema）。
2. **超过 300 MB 的库。** 上限已从 100 MB 放宽到 300 MB（2026-09-25）。仍有 2 个库只因文件大小被淘汰：BIRD 的 codebase_community（459 MB）和 music_platform_2（1.5 GB）。要用的话需要先抽样缩小。
3. **没有人物实体表的 16 个库**（软条件）：留着的话 persona 要编，任务会更像 cars/cookbook。

## 数据来源

- 库级统计 dump、主题标签：`docs/benchmark_db_catalog.xlsx`（未进 git，由 scratchpad 脚本生成）
- 原始库文件和问题文件：`~/Documents/Isa/text2sql_bench/`（BIRD train/dev、Spider 1.0、Spider2-lite 本地 SQLite + jsonl、SynSQL；目录说明见其中的 README.md）
- DySQL 13 个库明细：`docs/dysql_db_info.md`
