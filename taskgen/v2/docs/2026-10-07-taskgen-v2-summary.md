# 训练任务生成 v2：总结

2026-10-07。网页版：<https://claude.ai/artifact/7zEVFyUw5eVsqVqmXX8vBC>（默认私有，要从页面的 Share 菜单共享后别人才能打开）。

这一份把 v2 从设计到最终题集的全过程收在一处：流程、数字、质量结论、已知局限，以及下一步（SFT、GRPO）怎么用。细节见文末索引里的各份文档。

这里只写计数和 id，不摘录题目内容。生成的题和中间文件都只在本地（`taskgen/v2/results/`、`taskgen/v2/output/`），不进 git，因为 origin 是公开的 fork。

## 1. 结论

- **最终 3,425 道训练题**，覆盖 39 个库：
  - 23 个有人物表的库，人物题 3,122 道；
  - 16 个没有人物表的库，实体题（`6_entity`）303 道。
- **每道题都过了三道关：**
  - 执行检查：在库的内存副本上执行，过全部规则；
  - 三票校验：deepseek-v4.1-flash 投票，多数通过；
  - Opus 人读：每道题至少一个 Opus 读者读过，先盲写预期终态，再对照 gold。
- **质量：**
  - **影响判分或会让 agent 学偏的题（A 类）：0 道。** 读出的都已修好或删掉。
  - **照题目做就和 gold 一致、只是写完后数据前后矛盾的题（B 类）：609 道（17.8%），保留。** DySQL 自己的题里这类约占两成（§5.3）。
- **形状和 DySQL 接近：** 写语句条数、题型比例、难度、题目长度、写几张表都在同一水平（§4.2）。
- **难度和 DySQL 同量级：** 试点时 Qwen3-4B 的通过率，人物题 25.0%，实体题 26.8%；它在 DySQL 上是 29.8%，在 DySQL 的 car+cookbook 上是 26.9%。

## 2. 目标

为在 DySQL-Bench 上评测的 text-to-SQL agent 生成训练任务，用于 SFT 和 GRPO（研究计划第 4 步）。

任务的格式和 DySQL 一样：
- 一段用户的话（instruction）；
- 一串 gold SQL。

评测时由模拟用户扮演题里的人，agent 在库上执行 SQL。结束后比较全库状态和 gold 执行后的状态，一致才算通过（volatile 时间列除外）。

agent 遵守 DySQL 的 policy：
- 先定位用户、做身份验证；
- 只帮这一个人；
- 写库前列出要做的改动，等用户确认；
- 不编造信息。

设计上的取舍：
- 题目风格和难度贴近 DySQL；
- 宁可错杀，不放过肯定错的题（precision over recall）；
- 训练库不和 DySQL 的 13 个评测库重合；
- 不用 DySQL 的 gold 当示例。

## 3. 流程

v1（2026-09-30，冻结在 `taskgen/v1`，tag `taskgen-v1`）跑出 4,159 个候选，过检查 3,816 个，但没有做校验。v2 从 v1 复制起步，按设计文档的阶段 A–K 逐步改。

| 步骤 | 做什么 | 用什么 |
|---|---|---|
| 选库 | 39 个库，来自 BIRD train、Spider 1、Spider 2-lite（SQLite），和 DySQL 的 13 个库没有同一个文件 | `data/db_profiles.json` |
| 库档案 | 每个库一份档案：谁是"人"（根表）、哪些表归个人、哪些是公共表、哪些不能插入、数据怪异点。GLM 起草，Claude 预审，用户逐库确认 | `taskgen_v2/db_profile.py`、`profile_draft.py` |
| 建树 | 每个根行连同它名下的事件行建一棵树，每行标归属（自己的 / 公共 / 别人的）。人物库每库约 200 棵，实体库每库 25 棵 | `taskgen_v2/trees.py` |
| 出题计划 | 按 DySQL 的分布抽题型（1 自己的 / 2 自己 + 公共 / 3 只改公共 / 5 代办 / 6 实体）、写语句条数、形状（两张表、子查询、批量、复制归档），难度由形状推出 | `taskgen_v2/prompt.py` |
| 出题 | GLM-5.3 看档案描述、范围内表的 DDL、键说明、树里的行和一个手写 DySQL 式示例，写出 instruction 和 SQL | `taskgen_v2/generate.py` |
| 执行检查 | 在库的内存副本上执行，下表"执行检查规则"一节逐条列出 | `taskgen_v2/check.py`、`audit.py`、`owners.py` |
| 预封顶 | 每模板 ≤25、每库 ≤900，再花校验的票 | `taskgen_v2/dedup.py` |
| 校验 | deepseek-v4.1-flash（ollama.com）判断 SQL 是否正好做了题目要的事；3 票多数，前两票一致就不投第三票；附档案的数据怪异点 | `taskgen_v2/verify.py` |
| 去重和封顶 | 同库 instruction 3-gram Jaccard ≥0.6 只留一条；每人 ≤2、每模板 ≤15；实体库每库 19 题；跳过 `excluded.jsonl` 里的 id | `taskgen_v2/dedup.py` |
| 转换 | 写成 DySQL 的 Task 格式，加 `meta`；`output/manifest.json` 给 GenEnv 读 | `taskgen_v2/convert.py` |
| 修补和修复 | 被检查拒掉、或审查判坏的题：能改 SQL 或文字的就改，GLM 按说明改写题目，改不了就同一棵树重出；新题照常走检查和校验，原题排除 | `taskgen_v2/repair.py`、`fixes.py`、`scripts/fix_audit_tasks.py` |
| 审查 | 规则扫全量，加上 Opus 盲读：先只看题目写下预期终态，再看 gold 和它改动的行 | `scripts/audit_tasks.py`、`audit_read.py` |

**执行检查规则：**
- 每条写语句都要改到行，不是净无改动；
- gold 里的值都要在题目或说话人的记录里出现过；
- 只写说话人自己的数据或公共表，不往 `no_insert` 表插入；
- 不留悬空引用，不产生孤儿行；
- 读时钟的 gold 结果要确定；
- 复制归档的副本不能被后面的写改到；
- 四条来自审查的规则（`check.GATE`）：
  - 复制多行时，题里列出的顺序和表里的顺序一致；
  - 写入的键和已有行不冲突，也包括原表里全表唯一、以 `_id` 结尾的标识列；
  - 新插入或在查找表里改名的名称，和已有的名称不重复（大小写、空格、标点都不算区别）；
  - 写入的外键指向存在的行。

**时间线：**
- 10-01：设计和计划 1–4（骨架、统计、检查、档案、建树、出题、校验校准）。
- 10-01 至 10-02：试点和人物库全量（计划 5）。
- 10-04 至 10-05：实体库。
- 10-06 至 10-07：审查和修复。

## 4. 数字

### 4.1 漏斗

最终 39 个库合计：

| 步骤 | 数量 |
|---|---|
| 树 | 3,951 |
| 候选，含修复和重出 | 4,308 |
| 过执行检查 | 3,977 |
| 过校验 | 3,858 |
| 排除，审查判坏或修复失败 | 264 |
| 最终 | **3,425** |

"过校验"之后还经过去重、封顶和排除，所以最终数少于过校验数。

**最终题里修过的：**
- 审查修复 219 道：改值 20，按表的顺序重列复制的行 31，改写 22，重出 146。
- 修补 73 道：检查加上孤儿行（`orphans`）和净无改动（`net_noop`）两条规则后，所有库里被它们拒掉的题，级联补写 54，重出 19（`docs/2026-10-05-entity-run.md` §7）。

### 4.2 和 DySQL 对照

最终题集，DySQL 一列是它的 1,062 道 gold（`scripts/task_stats.py` 的指标）。

| 指标 | DySQL | v2 全部 | v2 人物 | v2 实体 |
|---|---|---|---|---|
| 题数 | 1,062 | 3,425 | 3,122 | 303 |
| 写语句 0/1/2/3/4/≥5 条 | 0.3 / 33.1 / 46.6 / 12.1 / 4.8 / 3.1 % | 0 / 34.2 / 44.5 / 12.3 / 5.9 / 3.1 % | 0 / 34.0 / 44.7 / 12.3 / 5.9 / 3.1 % | 0 / 36.6 / 42.9 / 12.5 / 5.6 / 2.3 % |
| 写语句均值 / 中位 | 2.29 / 2 | 2.00 / 2 | 2.01 / 2 | 1.94 / 2 |
| ≥3 条写语句 | 20.0% | 21.3% | 21.3% | 20.5% |
| 含子查询的语句 | 5.9% | 12.8% | 12.5% | 16.3% |
| 题目词数 均值 / 中位 / p90 | 57 / 54 / 80 | 55 / 55 / 65 | 55 / 55 / 65 | 56 / 55 / 65 |
| 只读提问 | 4.2% | 0.9% | 0.8% | 2.3% |
| 前 25 词给出 ID 或邮箱 | 92.4% | 88.0% | 89.8% | 68.6% |
| 题型 1/2/3/4/5/6/其他 | 40.4 / 14.5 / 4.7 / 5.4 / 22.7 / 7.8 / 4.4 % | 43.8 / 13.9 / 5.1 / 0 / 28.4 / 8.8 / 0 % | 48.0 / 15.2 / 5.6 / 0 / 31.1 / 0 / 0 % | 实体 100% |
| 难度 易/中/难 | 26.3 / 45.3 / 28.4 % | 29.6 / 46.9 / 23.5 % | 29.7 / 45.7 / 24.6 % | 28.4 / 59.4 / 12.2 % |
| 写两张及以上的表 | 56.8% | 57.4% | 58.0% | 51.2% |
| 改动超过 10 行 | 6.2% | 3.2% | 3.3% | 2.3% |
| 模板数 / 最大占比 | 421 / 6.6% | 1,402 / 0.9% | 1,231 / 1.0% | 171 / 3.0% |

**语句构成：**
- UPDATE / INSERT / DELETE 为 75 / 9 / 16（%），DySQL 约 70 / 15 / 15。
- 每道题 1 / 2 / 3 / 4 / ≥5 条语句：1,173 / 1,524 / 422 / 201 / 105。

**来源：** BIRD 2,698 道，Spider 2-lite 419 道，Spider 1 308 道。

### 4.3 每个库

| 库 | 来源 | 类型 | 题数 | 其中 B 类 |
|---|---|---|---|---|
| superhero | BIRD | 人物 | 196 | 1 |
| professional_basketball | BIRD | 人物 | 192 | 95 |
| college_2 | Spider 1 | 人物 | 192 | 0 |
| student_loan | BIRD | 人物 | 189 | 1 |
| books | BIRD | 人物 | 187 | 40 |
| beer_factory | BIRD | 人物 | 186 | 31 |
| IPL | Spider 2 | 人物 | 186 | 112 |
| movies_4 | BIRD | 人物 | 183 | 6 |
| olympics | BIRD | 人物 | 183 | 25 |
| synthea | BIRD | 人物 | 182 | 35 |
| retail_complains | BIRD | 人物 | 173 | 34 |
| movie | BIRD | 人物 | 171 | 45 |
| address | BIRD | 人物 | 162 | 19 |
| WWE | Spider 2 | 人物 | 154 | 25 |
| legislator | BIRD | 人物 | 119 | 19 |
| car_retails | BIRD | 人物 | 114 | 12 |
| shipping | BIRD | 人物 | 99 | 3 |
| hr_1 | Spider 1 | 人物 | 59 | 2 |
| food_inspection_2 | BIRD | 人物 | 50 | 12 |
| regional_sales | BIRD | 人物 | 50 | 0 |
| school_scheduling | Spider 2 | 人物 | 42 | 1 |
| student_club | BIRD | 人物 | 32 | 5 |
| book_publishing_company | BIRD | 人物 | 21 | 11 |
| 16 个实体库 | BIRD 11、Spider 1 3、Spider 2 2 | 实体 | 各 18–19，共 303 | 共 75 |

实体库是：menu、video_games、university、airline、college_completion、chicago_crime、food_inspection、restaurant、shakespeare、california_schools、card_games、imdb_movies、bike_1、csu_1、flight_4、Airlines。

## 5. 质量

### 5.1 审查做了什么

| 轮次 | 读了多少 | 读者 | 结果 |
|---|---|---|---|
| 规则扫全量 | 全部 | 脚本，13 条规则 | 其中 4 条后来加进检查 |
| 第一轮抽读 | 462 道 | Sonnet，盲读 | 坏题率约 1.7%，后来证明偏乐观 |
| 高风险子集 | 316 道（插入公共表、复制归档） | Opus | 坏题 7.3% |
| 随机抽读 | 300 道 | Opus | 坏题 7.0% |
| 全量精读 | 剩下的 2,740 道 | Opus | 分出 A、B 两类 |
| 修复后新进来的题 | 每次修复后都读 | Opus | 直到 A 类为 0 |

判坏的题都按"能修就修，修不了就删"处理。检查规则也跟着补了四条：
- 复制顺序；
- 键冲突，包括原表里全表唯一的标识列；
- 改名撞上已有名称，比较时忽略标点；
- 悬空外键。

这样以后再生成，同类问题会直接被拦下。

### 5.2 A 类和 B 类

- **A 类：影响判分，或会让 agent 学偏。**
  - 典型情况：
    - 题里说的现值不对；
    - 值的写法两读，比如没加引号又和列的写法不同；
    - gold 改的行比题里点名的多；
    - 改了很多人共用的查找行；
    - 复制时带不带子表的行，题意两读。
  - **最终为 0。**
- **B 类：照题目做就和 gold 一致，判分不受影响，只是写完后数据前后矛盾。**
  - 典型情况：
    - 改了分项没改总数；
    - 和同一行的其他列对不上，比如卡号前缀和卡类型、城市和邮编；
    - 同一组只能有一个却出现两个，比如一场两个队长；
    - 体育规则上不可能，比如接杀的球得分、季后赛 0 出场却有数据。
  - **共 609 道，保留。** 集中在体育和统计类的库：IPL 112/186，professional_basketball 95/192，airline 和 college_completion 各 14/19。
  - 609 道的 id 在本地 `results/audit/labels_B_final.json`。

### 5.3 和 DySQL 官方题对照

用同一套标准读了 DySQL 的 121 道写操作题（按库分层抽样）：

| | DySQL 抽样 | v2 最终 |
|---|---|---|
| 好题 | 51% | 82% |
| A 类 | 17% | 0% |
| B 类 | 22% | 18% |
| 只因"代别人改记录"判坏 | 10% | 我们的标准里判为好 |

- DySQL 的校验模型只看题目和 SQL，看不到数据库，原理上查不出 B 类；它的判分也只比终态。
- 所以 B 类是评测集本身就有的特征，我们和它同一水平。
- A 类我们低得多，因为多了执行检查、三票校验和几轮人读。

## 6. 已知局限

- **INSERT 比例偏低：** 我们 9%，DySQL 约 15%。实体题也一样。原因没细查，可能是：第 1、5 类不新建人物行；有些表不能插入；键说明让模型倾向于改已有的行。
- **gold 里没有 SELECT：** 设计上故意的，DySQL 有 49.7% 的题带 SELECT。agent 查库的行为要靠 rollout 学，不在 gold 里。
- **没有第 4 类：** 库内的人改别人的数据。和 policy 的"只帮这一个人"冲突，这一轮不出。
- **子查询偏多：** 我们 12.8%，DySQL 5.9%。
- **语气上的口癖：** 截止时间、道歉、"其他保持不变"之类，DySQL 没有。不影响对错，风格分布和评测集不同。
- **实体题比 DySQL 的 car、cookbook 简单：** 写条数少；但 4B 的通过率一样，所以不改。
- **B 类数据矛盾：** 保留。按库差别大，如果以后要清理，应该按库写规则统一判，不能直接用读者的结论。读者之间对 B 类的尺度不完全一致。
- **代码里遗留的小问题：** 计划 3、4 的复核记录里有一串边角情况（时钟函数的几种写法、批量条件数为 2 时的措辞等），不影响已生成的题，再改代码时顺手处理。
- **阶段 J 没做：** 用 v2 的检查和校验重跑 v1 的 3,816 条，得到一份对照集。SFT 用不到，先不做。

## 7. 产出和怎么用

**文件（本地）：**
- `taskgen/v2/output/manifest.json`：每个库一项 `{db_key, sqlite, tasks}`。`sqlite` 是相对 `TEXT2SQL_BENCH`（默认 `~/Documents/Isa/text2sql_bench`）的库文件路径，`tasks` 是相对 manifest 的 `<库>/tasks.jsonl`。
- `tasks.jsonl` 每行一道题：
  - `user_id`、`instruction`；
  - `actions`：`[{"name": "sql", "kwargs": {"sql": ...}}]`；
  - `meta`：`id`、`db`、`source`、`task_type`、`difficulty`、`template`、`plan`（形状和树的事件）、`gen_model`、`verify_model`、`verify_votes`、`profile_version`、`repair`、`fix`。
- 中间文件在 `taskgen/v2/results/<库>/`：`trees`、`candidates`、`check`、`verify`、`selected`、`excluded`、`fixes`、`repairs`。审查记录在 `taskgen/v2/results/audit/`。

**跑 agent：**
- DySQL-Bench 的 `gen:<db>` 环境（`DySQL-Bench/dysql_bench/envs/gen/`）读这个 manifest。
- 设 `TASKGEN_MANIFEST=taskgen/v2/output/manifest.json`。
- agent 的 policy 是 DySQL 13 个库共用的那段开头，加上这个库的 DDL。实体库也一样：DySQL 自己的 car、cookbook 用的就是这段开头。
- 每个线程用库文件的副本，和其他 env 相同。

**给 SFT 和 GRPO 的说明：**
- 这些是任务，不是对话。SFT 需要先在这些任务上用强模型（加模拟用户）跑出轨迹，再按全库状态比较的结果筛。
- 判分只比终态，B 类题不影响判分。
- 想按题型、难度、库切分时，用 `meta.task_type`、`meta.difficulty.level`、`meta.db`。
- 题目和库都不和 DySQL 的评测集重合：库没有同一个文件，题目与 DySQL 的最大 3-gram Jaccard 是 0.053。

**重跑或续跑**（在 `taskgen/v2/` 下，`P=~/miniconda3/envs/dysql/bin/python`）：
- 命令都在 `scripts/taskgen.py`：`trees`、`generate`、`check`、`verify`、`dedup`、`convert`。用法见 README 和 v1 README §3。
- 出题和校验的模型通过环境变量配置：出题用 `TASKGEN_GEN_BASE_URL`、`TASKGEN_GEN_API_KEY`、`TASKGEN_GEN_MODEL`（GLM-5.3），校验用 `TASKGEN_VERIFY_*`。
- 并发：GLM 不超过 5，ollama 校验不超过 3。
- 检查和校验都会跳过已经处理过的 id，可以断点续跑。
- 测试：`$P -m pytest -q`。

## 8. 代码和文档

**代码：**
- `taskgen_v2/`：
  - `db_profile`、`profile_draft`：库档案；
  - `trees`：建树；
  - `prompt`、`generate`：出题；
  - `check`、`owners`、`schema`、`audit`：执行检查和审查规则；
  - `verify`、`llm`：校验和模型调用；
  - `dedup`、`convert`：去重和转换；
  - `repair`、`fixes`：修补和修复；
  - `metrics`、`stats`：统计；
  - `dysql`：读 DySQL 的 gold；
  - `calibrate`、`corrupt`：校验校准。
- `scripts/`：
  - `taskgen.py`：主命令；
  - `task_stats.py`：和 DySQL 的对照表；
  - `audit_tasks.py`、`audit_read.py`、`audit_read_dysql.py`：审查；
  - `fix_audit_tasks.py`、`repair_tasks.py`：修复和修补；
  - `verify_calibrate.py`、`calibrate_check.py`、`check_diff.py`：校准；
  - 几个批处理 sh。
- `tests/`：262 个测试。

**文档（`docs/`）：**

| 文档 | 内容 |
|---|---|
| `2026-10-01-taskgen-v2-design.md` | 设计：目标指标、阶段 A–K |
| `2026-10-01-taskgen-v2-plan-1.md` … `plan-5.md` | 实施计划 1–5 |
| `2026-10-01-check-recalibration.md`、`check-with-profiles.md` | 执行检查的校准 |
| `2026-10-01-db-profiles-review.md`、`profiles-and-trees.md` | 库档案和建树 |
| `2026-10-01-prompt-and-materials.md` | 出题素材和 prompt |
| `2026-10-01-verify-calibration.md` | 校验校准 |
| `2026-10-02-pilot.md` | 试点和人物库全量 |
| `2026-10-04-entity-tasks-design.md`、`2026-10-05-entity-tasks-plan.md`、`2026-10-05-entity-profiles-review.md`、`2026-10-05-entity-run.md` | 实体题 |
| `2026-10-06-task-audit.md` | 审查和修复（§1–§13） |
| 本文 | 总结 |
