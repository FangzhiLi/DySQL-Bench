# 训练任务生成：设计（2026-09-28）

目标：用筛选出来的候选库（`docs/data_gen/candidate_dbs.md`，55 个）生成 DySQL-Bench 风格的多轮写操作任务，作为 GRPO 的训练数据。选库规则见 `docs/2026-09-24-data-gen-db-selection.md`，DySQL 任务的实测分类见 `docs/data_gen/dysql_task_types.md`。本文记录 2026-09-28 讨论定下的设计，实现计划另见 `docs/data_gen/2026-09-28-task-gen-plan.md`。

## 1. 范围

- **第一阶段：** 23 个有带名字人物锚点的库（`candidate_dbs.csv` 里 `has_person_named=True`）。
- **第二阶段：** 22 个只有实体锚点的库，等 `docs/data_gen/db_notes.csv` 的 `entity_anchors_ok` 确认后跑。复用第一阶段的角色生成机制，不另起框架。mental_health_survey、wine_1 没有合适锚点，放弃。
- **不做：** 10 个只有 ID 的人物库（第一阶段不用）；SynSQL-2.5M（表里几乎没数据，以后需要扩量时再给它填数据）；DySQL 的 refine 步骤（不合格直接丢，产量不够再补生成）。
- **数量：** 不定总数。按多样性封顶（见 §5），每库产出多少报实测数。第一阶段预计 2.5k–4k 条。最终训练需要 5k–10k，靠第二阶段和后续扩量补。

## 2. DySQL 的 pipeline 里我们缺什么

DySQL 放出的代码（`data_pipeline_shell/`）只有出题 prompt、LLM 投票校验、refine 三段，而且每个库一份脚本、路径写死。缺的两头和我们要加的：

| 环节 | DySQL | 我们 |
|---|---|---|
| 建树 | 未放出（`lean_tree_v2.jsonl` 等是现成输入） | 由 `candidate_anchors.json` 驱动的通用建树 |
| 库描述、数据块标题 | 每库手改 prompt | 从 schema 和 BIRD 的 `database_description/*.csv` 自动生成 |
| few-shot | `r1_tau_r1_5w.json`，未放出，只用其中一条 instruction 示范语气 | 手写 15 条，按任务类型选 |
| 任务类型、难度控制 | 无，靠随机 | 出题时指定类型和形状，出完按 gold SQL 算标签 |
| 执行检查 | 无，全靠 LLM | 在 DB 副本上跑 gold SQL，见 §7 |
| 校验 | r1 投票 5 次，写死第三方 API | 本地 Qwen 投票 3 次，通用 OpenAI 兼容接口 |
| 去重 | 无 | 按人物行和模板封顶 |
| 输出 | 到校验结果为止，没有到 `Task` 的转换 | 转成 `Task` 格式加 meta，通用 env 类接入 |

## 3. 模型与接口

- **出题：** GLM-5.3，Z.ai Coding Plan 的 OpenAI 兼容 endpoint（`https://api.z.ai/api/coding/paas/v4`，2026-09-28 测通）。默认开 thinking，答案在 `content`，推理在 `reasoning_content`，客户端只解析 `content`。订阅制不按 token 计费，但有速率限制：并发保守，429 退避重试，并发数试点时探。
- **校验：** 本地 vLLM，候选两个：Qwen3.8-27B 和 Qwen3.6-35B-A3B（MoE，激活 3B，快 5–10 倍）。27B 是官方 Qwen 里 GB10 能装下的最强模型（Qwen3.5-122B-A10B Int4 能装下但早两代、分数更低；Flash-Next 和更大的装不下）。27B 优先用 NVIDIA 官方的 NVFP4 量化版 `nvidia/Qwen3.8-27B-NVFP4`（约 15 GB，GB10 原生格式，比 FP8 快 1.7–2 倍，还能和用户模拟器并存），加载不了再退回官方 FP8（31 GB）。都开 thinking，多数决通过。和出题模型不同家族，本地不花钱。DeepSeek-R1 671B 在 GB10 上部署不了；Qwen3-32B-AWQ 这类旧稠密模型投 5 票的用时和 27B 投 3 票差不多，质量更低，不考虑。
  - **试点对照：** 100 条候选两个模型各投 5 票，都和人工核对的 20 条比，同时算 3 票与 5 票的结论差异率和单票一致率。三种结果：一致率差不多就全量用 35B-A3B；35B-A3B 明显差就两层（35B-A3B 初筛，27B 复核 2:1 分歧样本和 10% 随机审计）；都不够好切 DeepSeek 官方 API。
  - 全量票数按试点定：3 票和 5 票结论差异 < 5% 就用 3 票。票数是配置项 `TASKGEN_VERIFY_VOTES`。若单票噪声大，多出的票改用第二个 prompt（只问参数是否给全、不看库能不能做），不同角度的票比同一 prompt 重复投更有用。
- **接口：** 沿用 repo 里的做法，用 `requests` 直接调 `/chat/completions`，带重试和线程池并发，记录 token 用量。出题和校验各一组环境变量：`TASKGEN_GEN_BASE_URL / API_KEY / MODEL`、`TASKGEN_VERIFY_BASE_URL / API_KEY / MODEL`，放在仓库根目录 `.env`（已在 `.gitignore`）。
- **注意：** 校验模型是 Qwen 家族、策略模型也是 Qwen，不是问题。校验判断的是题目本身，不给策略模型的输出打分。

## 4. 任务类型与角色

第一阶段只出第 1–5 类。按 DySQL 的比例去掉第 6、7 类后归一，第 2 类调低，因为 DySQL 的 14.5% 大半来自 retail 的 sales 加 costs 数据池构造：

| 类 | 目标比例 | 可行条件 |
|---|---|---|
| 1 本人改自己的数据 | 46% | 总能出 |
| 2 本人改自己的 + 公共数据 | 12% | 树里有 up 表可改 |
| 3 本人只改公共数据 | 5% | 同上 |
| 4 本人改别人的数据 | 8% | 库里有第二个人物锚点，或同表其他行 |
| 5 库外角色代办 | 29% | 总能出 |

- 比例写在配置里。一个锚点树不可行的类型跳过，从可行类型里重新归一。
- **第 5 类的角色：** prompt 要求编一个名字加一个和锚点表相关的职业身份（数据分析师、客户经理、协调员），说话人自报姓名和职务，然后针对锚点行（报姓名和键）提出修改。第二阶段实体库的第 6 类用同一个机制。
- **说话人身份：** 第 1–4 类用锚点行的姓名列，再报键值或邮箱之类可核对的字段，和 DySQL 一致（DySQL 里 67% 是库里真人，几乎都报名字）。

## 5. 多样性与难度

### 模板与封顶

**模板** = 任务类型 + 写语句的 (表, 操作) 集合。同一模板的任务只是换人换值。DySQL 实测：1062 条任务 351 个模板，每库最大的模板占 12%–55%，63% 的模板只出现一次；说话人几乎不重复，每人 1.0–1.3 条。

封顶规则（也是去重规则）：
- 每个人物行最多 2 条。
- 每个模板最多 15 条。DySQL 头部模板到 20–79 条，我们比它平一些。
- 每库最多 600 条。
- 约三成样本不指定写入表，让模型在 scope 内自由组合多表，用来产生长尾模板。

### 难度

模板集中不会让通过率变高，只会让库的通过率等于大模板的通过率。真正决定难度的是结构。DySQL 基线实测（32B / 4B）：

| 特征 | 通过率变化 |
|---|---|
| 写语句 1 / 2 / 3 / 4+ 条 | 61 / 42 / 40 / 17%（32B） |
| 写入 1 / 2 / 3 张表 | 59 / 38 / 28% |
| 写语句里有子查询定位行 | 48% → 31% |
| INSERT … SELECT 归档 | 48% → 29% |
| 改公共表或别人的数据 | 49% → 25%（第 2 类） |

**难度分** = 以下五项各 1 分：写语句 ≥ 2；写入表 ≥ 2；有子查询；有归档；第 2 或 4 类。DySQL 的分布和通过率：

| 分 | 档 | DySQL 占比 | 32B | 4B |
|---|---|---|---|---|
| 0 | 简单 | 26% | 66% | 47% |
| 1–2 | 中等 | 45% | 49–44% | 29–24% |
| 3+ | 困难 | 29% | 29% | 20% |

做法：
- 出题时在 prompt 里指定"形状"：写语句条数、表数、是否按归属用子查询定位、是否归档、是否改公共表。按 26 / 45 / 29 抽。
- 标签以生成后从 gold SQL 算出的为准，配比按算出的标签调。
- 每个库都要出到三档；小库困难题出不满是正常的，按库报实测比例。
- 四种难题型是每个库的必出项，单独统计占比：多条写语句、按归属子查询定位、归档（INSERT … SELECT 再 DELETE/UPDATE 原行）、改公共表。

## 6. 模块

新包 `DySQL-Bench/dysql_bench/taskgen/`，CLI `DySQL-Bench/scripts/taskgen.py`，子命令对应步骤。中间产物写 `DySQL-Bench/results/taskgen/<db>/`（不进 git），可断点续跑；最终产物进 git。

| 模块 | 输入 | 输出 | 要点 |
|---|---|---|---|
| `trees` | sqlite + 锚点记录 + 外键边 | 每个锚点行一棵树 JSONL | 锚点行；down 各表 ≤ 15 行（不足全取），2 跳的表经中间表 join；up 取被引用的父行加少量随机行。只保留 down 有数据的锚点行；person_named 没子表时以自己为写入目标。读入后沿外键边重算 down / up，与 JSON 记录不一致就报错 |
| `schema` | sqlite + BIRD 列说明 | DDL 文本、列说明、库的一句话英文描述 | 库描述用 LLM 生成一次，存 `docs/data_gen/db_descriptions.json`，人工过一遍。Spider 的库没有列说明，只给 DDL |
| `prompt` | 树 + 类型 + 形状 + few-shot | SYSTEM / USER 消息 | SYSTEM 移植 DySQL 的，加任务类型段、形状段、第 5 类角色说明；USER 的数据块按锚点 / down / up 自动命名；few-shot 按类型选 |
| `llm` | 消息 | 文本 + 用量 | requests，重试，线程池 |
| `generate` | 树 × 类型 × 形状 | 候选任务 JSONL | 记 db、锚点表、键值、要求的类型和形状、模型、原文 |
| `check` | 候选任务 | 通过 / 失败原因 + 算出的类型、难度、模板 | 见 §7 |
| `verify` | 通过 check 的任务 | 每票原文 + 结论 | 见 §8 |
| `dedup` | 通过校验的任务 | 去重后的任务 | §5 的封顶规则 |
| `convert` | 去重后的任务 | `DySQL-Bench/data/taskgen/<db>/tasks.jsonl` + `manifest.json` | `Task` 字段加 meta |
| `envs/gen` | manifest | `GenEnv` | `get_env("gen:<db>")`；DDL 从 sqlite 现生成；agent_policy 用 13 个 env 共用的那段模板加 DDL；DB 副本机制和现有 env 相同 |

`tasks.jsonl` 每行：`user_id`、`instruction`、`actions`（和 `Task` 一致），加 `meta`：`db`、`source`、`anchor_table`、`anchor_key`、`task_type`（算出的）、`difficulty`（分和档）、`template`、`shape_requested`、`gen_model`、`verify_votes`（每票结论）。

### 锚点文件要补外键边

`candidate_anchors.json` 是树的骨架（根表、键、姓名列、down / up 表、可更新表），不是逐行的数据树，而且没有外键的列对。建树要按列 join，`down` 里 2 跳的表（books 的 customer → cust_order → order_line）要经中间表连。所以 `select_dbs.py` 给每个库加 `fks` 字段：有效外键的 (子表, 子列, 父表, 父列, 命中率)，来源就是 `db_select.all_fks`。JSON 自包含，建树只读 JSON 和 sqlite。

### 运行方式

每个步骤是独立子命令，读上一步的 JSONL、写自己的 JSONL，按 id 断点续跑。试点严格串行，校验结果回流到 prompt 后再进下一轮。全量按库分批、两个阶段流水：进程 A 出题加执行检查（网络 IO，几十路并发），进程 B 循环校验所有已通过检查但未投票的记录（GPU）。库按与试点库的相似度排序，前几个库校验通过率明显下跌就停下改 prompt。dedup 和 convert 要看一个库的全部候选，等该库校验完整再跑。

## 7. 执行检查

DySQL 没有这一步，是主要质量闸门，不花钱，放在 LLM 校验前面。

- 在 DB 副本上按顺序执行全部 actions，任何一条报错就丢。
- 每条 UPDATE / DELETE 命中行数必须 > 0；INSERT 到空表允许。总体至少改一行。
- 单条语句改超过 50 行的丢（阈值可配；DySQL 有 37 条超过 10 行）。
- 写入的表必须在该锚点的 scope 内（DySQL 的 2432 条写语句全部满足）。
- 字面量检查：写语句里每个字符串和数字字面量，必须出现在 instruction 里，或等于锚点行的某个值（用户报了名字，agent 能查到 ID）。
- 顺便算出类型、难度分、模板，写进记录。
- **校准：** 这套规则跑在 DySQL 的 1062 条任务上，除已知的 47 条 no-op 外通过率 ≥ 90%；不到就调规则，不调任务。

## 8. LLM 校验

- prompt 移植 DySQL 的 `verify_qa_voting_request.py`，保留"Verification: Is the answer correct (Yes/No)?"的结尾格式。
- 加两问：instruction 是否给了执行所需的全部参数；一个看不到数据库内容的人读了 instruction 能不能做到。
- 3 票，temperature 沿用 DySQL 的 1.2，Yes ≥ 2 通过。每票原文都保留。
- 试点时人工核对 20 条，和校验结论比，作为校验模型是否可信的依据。

## 9. few-shot

- 手写 15 条 instruction，每类 2–3 条，存 `dysql_bench/taskgen/examples.json`。出题时按目标类型选一条放进 SYSTEM 的 `## Instruction Example`，和 DySQL 的用法一致。
- 不用 DySQL 的 1062 条任务当例子，那是评测集。
- 可参考 τ-bench 公开的 retail / airline 任务的语气，但不照搬场景。

## 10. 试点与验收

1. beer_factory 出 100 条候选。选它的理由：customers 有名字，down 有 transaction 和 rootbeerreview，up 有 rootbeerbrand 和 location，是 DySQL 里 retail、chinook 那种"客户、交易、商品"三层结构；7 张表 14k 行，跑得快；声明的 FK 全部有效。car_retails 和 retail_world 共享 44 个联系人姓名，不做试点。
2. 验收：
   - 经 check 和 verify 后剩 ≥ 50 条。
   - 类型分布与目标比例误差 ≤ 10 个百分点；第 7 类为 0。
   - 三个多样性数落在 DySQL 区间：模板数、最大模板占比、每人任务数。
   - 三档难度都有，四种难题型都出现。
   - 校验模型吞吐：按 100 × 3 票的用时推全量，决定要不要两层校验。
   - 校验结论与人工核对 20 条的一致率。
   - `run.py --env gen:beer_factory` 跑 Qwen3-4B，通过率在 20%–50% 之间。
3. 手读 20 条，记录问题，改 prompt 后再来一轮。
4. 通过后跑 books（15 张表，订单加明细）验证大 schema，再跑剩余 21 个库。

## 11. 成本

每条候选出题约 5k token，校验 3 票约 9k。校验在本地不花钱。出题走 Coding Plan 订阅，不按 token 计费，瓶颈是速率限制而不是钱。

## 12. 已定事项清单

- 出题 GLM-5.3（Z.ai Coding Plan endpoint），校验本地 Qwen3.8-27B（NVFP4 优先）或 Qwen3.6-35B-A3B，试点对照后定；接口都是 OpenAI 兼容，配置在 `.env`。
- `candidate_anchors.json` 加外键边；建树重算 scope 并与之核对。
- 出题和校验按库流水，试点串行。
- 通用 `GenEnv`，`get_env("gen:<db>")`，不给每个库建目录。
- 第一阶段 23 个有名字的人物库；只有 ID 的 10 个库和实体库不在第一阶段。
- 不定总数，按多样性封顶：每人 ≤ 2、每模板 ≤ 15、每库 ≤ 600。
- 难度按 gold SQL 算分，三档 26 / 45 / 29，标签进 meta。
- 不做 refine；3 票校验；执行检查放在校验前并在 DySQL 上校准。
- 文档沿用现有惯例：设计放 `docs/`，计划放 `docs/data_gen/`，中文。
