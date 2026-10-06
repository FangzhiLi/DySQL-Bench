# 实体题运行记录

2026-10-05。对应 `2026-10-05-entity-tasks-plan.md` 的 Task 6–10，是设计 `2026-10-04-entity-tasks-design.md` 的完成证据。

这里只写计数和 id，不摘录题目内容。生成物都只在本地，不进 git：
- `taskgen/v2/results/<库>/`
- `taskgen/v2/output/<库>/tasks.jsonl`、`output/manifest.json`
- `DySQL-Bench/results/taskgen_v2/entity_pilot/`

## 1. 结果

- **最终 298 道 `6_entity` 题**，覆盖 16 个没有人物表的库。目标约 300 题（3,131 × 83/872），下限 270。
- 已转换进 `output/manifest.json`，和 23 个人物库的 3,131 题在同一个 manifest 里，靠 `meta.task_type`、`meta.db` 区分。
- 两个库没到每库 19 题的封顶：
  - video_games 18 题，校验模型拒了 4 条，见 §4；
  - Airlines 14 题，8 条因改动被引用的键被拒，见 §4。

| 库 | 候选 | 过检查 | 过校验 | 最终 | 检查拒绝原因 |
|---|---|---|---|---|---|
| menu | 25 | 24 | 24 | 19 | lookup_name_taken 1 |
| video_games | 25 | 22 | 18 | 18 | lookup_unreferenced 1, lookup_name_taken 1, orphans 1, literal_missing 1 |
| university | 25 | 23 | 23 | 19 | lookup_name_taken 1, net_noop 1 |
| airline | 25 | 25 | 25 | 19 | — |
| chicago_crime | 22 | 20 | 20 | 19 | noop_write 2 |
| college_completion | 25 | 24 | 24 | 19 | literal_missing 1 |
| food_inspection | 25 | 24 | 22 | 19 | literal_missing 1 |
| restaurant | 25 | 25 | 24 | 19 | — |
| shakespeare | 25 | 25 | 24 | 19 | — |
| california_schools | 25 | 25 | 25 | 19 | — |
| card_games | 25 | 25 | 23 | 19 | — |
| Airlines | 25 | 17 | 14 | 14 | orphans 8, public_write 1 |
| imdb_movies | 25 | 24 | 23 | 19 | orphans 1 |
| bike_1 | 25 | 24 | 24 | 19 | noop_write 1 |
| csu_1 | 23 | 23 | 23 | 19 | — |
| flight_4 | 25 | 25 | 22 | 19 | — |
| **合计** | **395** | **375（94.9%）** | **358** | **298** | orphans 10, lookup_name_taken 3, literal_missing 3, noop_write 3, lookup_unreferenced 1, net_noop 1, public_write 1 |

chicago_crime 和 csu_1 的根行只有 22 个和 23 个，所以候选少于 25。

## 2. 做法

- 16 个库：menu、video_games、university（试跑），airline、chicago_crime、college_completion、food_inspection、restaurant、shakespeare、california_schools、card_games、spider2 Airlines、imdb_movies、bike_1、csu_1、flight_4。
- 不用的 6 个：citeseer、genes、toxicology、mental_health_survey、shooting、wine_1。理由见 `2026-10-05-entity-profiles-review.md`。
- 每库 25 个候选，最终封顶 19 题。
- GLM-5.3 出题（并发 5）。校验用 `deepseek-v4.1-flash`，三票多数，前两票一致即停（并发 3）。思考被截断的票最多重问两次。

## 3. 四道关卡

**关卡 1：profile。** 用户确认了 16 份，共两轮。
1. 第一轮：california_schools 的两张表改成事件表。
2. 第二轮：另一次 profile 审阅之后，用户批准修改 9 份并重新确认。
   - satscores 改回属性表；
   - 改正 3 条与数据不符的说明，补 4 条说明；
   - shakespeare 的章节标签改名；
   - flight_4 加上起点机场的新查找行。

**关卡 2：试跑。** menu、video_games、university，各 25 个候选。
- **第一轮：** 过检查 71/75。读题发现 4 条坏题：
  - 3 条删除了还被平台记录引用的 `game_publisher` 行（video_games 9635、7490、7371）；
  - 1 条净效果为零（university 971）。

  因为同一毛病出现了 3 次，按规则停下报告。
- **用户批准的修法：**
  - 检查加 `orphans` 和 `net_noop` 两条规则；
  - 实体库的归档形状只复制叶子表；
  - 逐库闸门用 A（同一原因被拒 ≥3 条，或总共被拒 ≥5 条才停）。
- **第二轮：** video_games 按新 profile 重出。过检查 69/75（92%），读 69 题，坏题 0。
- plan 是否要求新查找行，和检查结果里有没有新增公共行，69/69 一致。
- 改名冒烟测试 3/3 被拒。
- `name_mismatch` 误杀 0 条。
- 抽查了 23 个没加引号的名字，都和数据一致。

**关卡 3：校验模型校准。**

| 指标 | 结果 |
|---|---|
| 负样本被拒 | 99/99 |
| DySQL car/cookbook 正样本通过 | 45/46 |
| 标为好题的试跑题通过 | 65/69（94.2%），差 95% 一条 |

被拒的 4 条（university 987，video_games 1420、9245、6378）情况相同：gold SQL 的条件比题目给的 ID 宽，但在数据上改到的行一样。用户复核判为好题，放行。

**关卡 4：Qwen3-4B。** 56 道试跑题通过 15 道，26.8%。
- 分库：menu 3/19，video_games 4/18，university 8/19。
- 分长短：短题 32.5%，长题 12.5%。
- 对照：DySQL 的 car+cookbook 是 21/78 = 26.9%，人物题试点是 25.0%，4B 在 DySQL 上总体 29.8%。
- 失败主要是 4B 的协议问题（`<action>`、`<query>` 标签不被执行）。
- 被"无法验证身份"卡住的失败只有 1 次（共 41 次失败）。

## 4. 全量

- 13 个库没有一个被闸门 A 拦下。chicago_crime 一度被拦，是跟随脚本按"原因出现次数"计数的 bug，改为按"被拒题数"后放行。
- **抽查：** 每库随机 10 题，共 140 题（含 Airlines 重抽的 10 题）。
  - Airlines 第一次抽查有 3 题坏题：改了被其他表引用着的 `ticket_no` 或 `book_ref`。这个库没有声明主键，所以 prompt 里"不改键列"那条不起作用。
  - 修法是把孤儿规则扩展到改键的 UPDATE，提交 ae45a9d。重检 16 个库后，只有 Airlines（新拒 6 条）和 imdb_movies（新拒 1 条，改了电影 id）受影响。
  - 重抽 Airlines 10 题，全部正常。其他库抽查没有坏题。
- **校验模型拒绝最多的是 video_games**（4/22），全是"gold 条件比题目给的 ID 宽"这一类。这只是产量损失，没有改 prompt（见台账里的决定）。

## 5. 和 DySQL car+cookbook 的对比

前两列来自 `task_stats.py --dysql-env car --dysql-env cookbook --set entity=results/entity_view`。entity 这一列是全部过检查的 375 条候选，不是最终的 298 题。

| 指标 | car+cookbook | 实体题 |
|---|---|---|
| 题数 | 78 | 375 |
| 写条数 1/2/3/4/≥5 | 16.7 / 59.0 / 20.5 / 2.6 / 1.3% | 38.1 / 42.9 / 12.0 / 4.8 / 2.1% |
| 写两张表以上 | 75.6% | 51.5% |
| 带子查询的语句 | 4.4% | 16.4% |
| 题目词数（均值 / 中位 / p90） | 52 / 50 / 67 | 56 / 55 / 64 |
| 难度 easy / medium / hard | 15.4 / 76.9 / 7.7% | 31.2 / 55.7 / 13.1% |
| 模板数 / 最大占比 | 40 / 14.1% | 189 / 3.7% |

最终 298 题的其他统计：
- **说话人：** 编人名 155（52%）、角色 32、用户名 22（合计 18%）、不报身份 89（30%）。目标是 55 / 17 / 28。
- **新查找行：** 12/298（4%）。只有 6 个库配了新查找行，所以达不到每题 10%。
- **难度：** easy 87、medium 172、hard 39。
- **"ID 出现在前 25 个词"：** 只有 67.7%。这是统计口径的问题：这个指标的正则认不出 "CDSCode 4569…"、"alid 3287"、"Code 20363" 这类写法。prompt 要求的"ID 或列名"在抽查里都满足。

## 6. 遗留问题

- **实体题比 car/cookbook 简单：** 单条写的题多，写两张表的题少。原因是写数量的配比按整个 DySQL 校准，而很多实体库的子表少。如果要更接近 car/cookbook，可以对实体库单独调高 `WRITES_MIX` 中多条写的比例。
- **SFT 的注意点：** 少数题的 gold SQL 条件比题目给的 ID 宽，例如 video_games 的 9245、1420、6378，后两条已被校验模型拒掉。按最终状态打分时没问题；如果直接拿 gold SQL 当 SFT 示范，会教 agent 写宽条件。
- **代码审阅暂缓的次要问题**（台账 `Final: minor (deferred)`）：
  - 写入指向不存在的行也能通过；
  - 删除根行时报的原因有误导；
  - 列名里的单引号没有转义；
  - 题目引用兄弟行的名字会被名字检查拒；
  - 几种罕见的误杀；
  - 已用键值只列当前根行下的；
  - 系统提示的措辞。
- **人物库没有 `orphans` 和 `net_noop` 规则。** 这两条只对实体库生效，人物库的 3,131 题没有按它们重检。是否对人物库也启用，要先量一下会多拒多少题。
