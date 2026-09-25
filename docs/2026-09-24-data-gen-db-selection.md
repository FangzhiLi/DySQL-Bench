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
- 这份清单是人工识别的。还要用表名集合 Jaccard 相似度（阈值约 0.5）对全部候选跑一遍兜底。

另外，跨来源的重复库要去重，避免同一份数据被过度采样，例如：Spider1 `formula_1` / BIRD `formula_1` / Spider2 `f1`，Spider1 `baseball_1` / Spider2 `Baseball`，Spider1 `bike_1` / BIRD `bike_share_1`。

### B. 结构要求

- **事务/事实表：** 至少一张，有 FK 指向主实体表，行数 ≥ 50。这是写操作的落点。
- **人物实体表（软条件）：** customer / employee / member / player / user / student / patient 等，用来给任务提供 persona。DySQL 的 cars、cookbook 没有这种表，persona 是编的，所以不设为硬条件，但要优先选有的库。
- **写目标表可定位：** 有 PK，或有可用的唯一自然键；否则 gold SQL 无法确定地命中一行。可以有意保留少量无 PK 的事实表（eval 里 complex_oracle 的 sales/costs 就是这样），但要标记出来。
- **库级 FK ≥ 2：** 才能出"先插父再插子 / 先删子再删父"这类多步任务。
  - 对 Spider2-lite 要放宽：它的库大多从 Kaggle CSV 导入，基本不声明 FK。可以接受按列名推断的 join key（如两表都有 `customer_id`），但要人工抽查。

### C. 尺寸区间（为小模型和 rollout 成本，不是为像 DySQL）

- 表数 3–20，全库列数 ≤ 约 250：保证 schema 能放进 Qwen3-1.7B/4B 的 prompt。
- 总行数 ≥ 200，≤ 约 300 万；文件 ≤ 约 100 MB：GRPO 每个 rollout 都要复制/重置 DB，complex_oracle 这种百万行规模已经偏慢。
- 写目标表不能为空，避免 no-op gold（每条 gold 写操作都要检查实际影响行数 > 0）。

### D. 配额

- 每库任务上限（例如 ≤ 80），避免复制 DySQL 里两个库占 39% 的偏斜。
- 按领域分层：体育、零售/订单、内容媒体、人事/教育、医疗/科学。

## 各来源的初步通过情况

用 A（只用清单，未跑 Jaccard）加 C 的表数/列数/行数，再加"声明 FK ≥ 2"跑了一遍（2026-09-24，基于 PRAGMA 统计）：

| 来源 | 库总数 | 排除泄漏后 | 通过尺寸 + FK≥2 | 备注 |
|---|---|---|---|---|
| BIRD（train 69 + dev 11） | 80 | 72 | 58 | 主要来源。超出尺寸：hockey、mondial_geo、soccer_2016、works_cycles |
| Spider 1.0 | 206 | 202 | 16 | 大多数库数据太少（中位 11 行/表）。通过的：aan_1, activity_1, bakery_1, car_1, college_2, college_3, cre_Drama_Workshop_Groups, csu_1, flight_2, flight_4, formula_1, hr_1, voter_1, wine_1, world_1, wta_1 |
| Spider2-lite（SQLite） | 30 | 21 | 1（school_scheduling） | 被"声明 FK"卡掉的居多，按上面 B 的放宽规则重算。`city_legislation`、`modern_data`、`education_business`、`oracle_sql` 是多个无关数据集拼在一起的库，领域不连贯，建议排除或按子数据集拆开 |
| SynSQL-2.5M | 16,583 | 16,583 | — | 不能直接用：75% 的表只有 2 行，20% 是空表，写任务要么 no-op 要么平凡。价值在于 schema（PK/FK 齐全、无泄漏风险），要用必须先填充数据，作为单独的工作项 |

B 的其余条件（事务表、人物表、写目标可定位）还没自动化，是下一步。

## 数据来源

- 库级统计 dump、主题标签：`docs/benchmark_db_catalog.xlsx`（未进 git，由 scratchpad 脚本生成）
- DySQL 13 个库明细：`docs/dysql_db_info.md`
