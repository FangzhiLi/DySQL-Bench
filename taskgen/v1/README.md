# 训练任务生成 v1（通用规则版）：全流程总览

v1 用一套通用规则，从公开的 text-to-SQL 库自动生成 DySQL-Bench 风格的多轮写操作任务，作为 GRPO 的训练数据。整个流程不需要逐库写代码，但有几处语义判断（哪张表是人、哪一列是名字、父表属于谁）也是交给规则做的。这是 v1 的主要短板，见 §6。

**状态（2026-10-01，tag `taskgen-v1`）：** 代码冻结，之后只改文档。v2 会结合论文的做法重做锚点和建树，并复制 v1 目录作为起点（目录约定见 [../README.md](../README.md)）。

**产出：**
- **试点 beer_factory：** 100 条候选走完全部步骤（含 LLM 校验），留下 82 条任务。Qwen3-4B 在这 82 条上的通过率是 23.2%。
- **全量 23 个库：** 4159 条候选，3816 条过了执行检查，**还没做 LLM 校验**。
- **存放位置：** 生成物都只在本机（GB10），不进 git。中间文件在 `results/`，最终任务在 `output/`。

## 1. 流程一览

```
第 0 步   选库和锚点   taskgen/common（各版本共用）→ candidate_anchors.json：55 个库的锚点、可写表、外键
第 1–2 步 建树         trees     每个锚点抽 N 行，每行一棵数据树
第 3 步   库描述       describe  LLM 写 2–3 句库描述，每库一次，缓存
第 4–5 步 出题         generate  抽出题计划 → 拼 prompt → GLM 写 instruction 和 gold SQL
第 6 步   执行检查     check     在库副本上执行 gold SQL，按规则拒绝；算出类型、难度、模板
第 7 步   LLM 校验     verify    本地 Qwen 投 3 票，多数通过
第 8 步   去重封顶     dedup     每人、每模板、每库封顶
第 9 步   转换和评测   convert   转成 Task 格式并写 manifest；DySQL-Bench 用 gen:<db> 评测
```

| 步骤 | 输入 → 输出 | 命令 | 代码 |
|---|---|---|---|
| 0 选库、锚点 | 四个来源的 SQLite → `../common/data/candidate_dbs.csv`、`candidate_anchors.json` | 在 `taskgen/common/` 下跑 `scripts/select_dbs.py` | `../common/taskgen_common/db_select.py`、`db_anchor.py` |
| 1–2 建树 | 锚点记录 + SQLite → `results/<db>/trees.jsonl`、`others.json` | `scripts/taskgen.py trees --db <key> --n 200` | `taskgen_v1/trees.py` |
| 3 库描述 | DDL + BIRD 列说明 → `data/db_descriptions.json` | `taskgen.py describe` | `schema.py` |
| 4–5 出题 | 树 → `results/<db>/candidates.jsonl` | `taskgen.py generate` | `prompt.py`、`examples.json`、`generate.py`、`llm.py` |
| 6 执行检查 | 候选 → `check.jsonl` | `taskgen.py check` | `check.py` |
| 7 LLM 校验 | 过了检查的候选 → `verify.jsonl` | `taskgen.py verify` | `verify.py` |
| 8 去重封顶 | 过了校验的候选 → `selected.jsonl` | `taskgen.py dedup` | `dedup.py` |
| 9 转换 | → `output/<db>/tasks.jsonl`、`output/manifest.json` | `taskgen.py convert` | `convert.py`；评测侧 `DySQL-Bench/dysql_bench/envs/gen/` |
| 统计 | 各步文件 → 指标表 | `taskgen.py stats` | `stats.py` |

表中命令都在 `taskgen/v1/` 下运行（第 0 步除外）。每一步只读上一步的 JSONL、写自己的 JSONL，按候选 id 断点续跑。id 的格式是 `<source>:<db>:<锚点表>:<键值>:<序号>`。

## 2. 各步要点

### 第 0 步：选库（`taskgen/common`）

- **来源：** BIRD train/dev、Spider2-lite 的 SQLite 库、Spider 1.0、SynSQL-2.5M。
- **硬排除：**
  - DySQL 的 13 个库及其同源副本；
  - 打算报告的评测集：Spider dev/test（也就是 CoSQL、SParC 的评测库），以及 Ergast F1；
  - 与上面任一库的 schema 包含度 ≥ 0.6 的库。
- **结构要求：**
  - 外键先用数据验证，命中率 ≥ 0.3 才用；
  - 要有锚点，并且有可写的表；
  - 尺寸：3–20 张表，不超过 300 MB。
- **结果：** 55 个库。v1 只用其中有"带名字人物锚点"的 23 个。SynSQL 的库表里几乎没有数据，全部落选。
- 详见 [选库条件](../common/docs/2026-09-24-data-gen-db-selection.md) 和 [候选清单](../common/data/candidate_dbs.md)。

### 第 1 步：锚点（主表）

- **锚点的条件**（`db_anchor.anchors`），四条都满足的表才算：
  - 有单列键；
  - 至少 5 行；
  - 沿外键向下 2 跳以内有子表（有名字的人物表可以没有子表）；
  - 范围（自己 + 子表 + 这些表引用的父表）里至少有一张可写的表。
- **分类：** 按表名和列名分三类。像人且有姓名列的是 `person_named`，像人但没有姓名列的是 `person_id_only`，其余是 `entity`。
- **v1 用了哪些：** 每个库的**所有** `person_named` 锚点都当根，23 个库共 31 个。
- **验收：** DySQL 自己 13 个库的 2432 条 gold 写语句，全部落在某个锚点的范围内（[test_dysql_acceptance.py](../common/tests/test_dysql_acceptance.py)）。
- **和论文的差别：** 论文是人工分析后每个库选一张主表。

### 第 2 步：建树（`trees.py`）

- **抽样：** 每个锚点抽 `--n` 行，只抽有子表行的行（没有子表的锚点抽任意行）。每行建一棵树：
  - **根：** 锚点行。
  - **子表（down）：** 沿外键向下最多 2 跳，每张表最多随机取 15 行。第 2 跳的表通过中间表连接，只取和已抽中的行相连的行。
  - **父表（up）：** 根和子表直接引用的父表，每张表最多 3 行。
- **建树前的检查：** 用外键重算一遍范围，和锚点记录不一致就报错。
- **`others.json`：** 每个锚点另取 20 个"另一个人"，给第 4 类任务用。
- **和论文的差别：** 论文以事件记录为单位嵌套，每条记录带着往上多跳的关联信息；v1 按表平铺，父表只挂一跳。

### 第 3 步：库描述和 schema（`schema.py`）

- **schema：** prompt 里给 DDL，加上 BIRD 自带的列说明（Spider 的库没有列说明）。
- **库描述：** 每个库让 GLM 写 2–3 句，说明库是关于什么的、谁是人、主要的事务表记录什么。结果缓存在 `data/db_descriptions.json`，每条都对照表和列人工核过。
- **下一个可用主键：** 对单列整数主键的表计算 `MAX + 1` 写进 prompt，避免新插入的行撞主键。

### 第 4 步：出题计划和 prompt（`prompt.py`）

每条候选先抽一份出题计划，再拼 prompt：

| 计划项 | 取值 |
|---|---|
| 任务类型 | 第 1 类本人改自己的 46%，第 2 类本人改自己的和公共的 12%，第 3 类本人只改公共的 5%，第 4 类本人改别人的 8%，第 5 类库外的人代办 29%。树里不具备条件的类型跳过 |
| 难度 | 简单 26%，中等 45%，困难 29% |
| 形状 | 写几条语句、写几张表、是否按归属用子查询定位行、是否先归档（INSERT … SELECT）再修改 |
| 写入哪些表 | 70% 由计划指定；30% 让模型在范围内自选，用来产生长尾模板 |
| 风格 | 10 种开场方式抽 1 种；第 5 类另外抽姓名（48 个名 × 48 个姓）和职务（16 种） |
| few-shot | 手写 15 条，每类 3 条，按类型抽 1 条，只示范语气 |

- **SYSTEM 消息：** 移植官方的出题 prompt，另加了几条规则：
  - 每个 action 只放一条语句；
  - UPDATE、DELETE 必须命中给出的行，单条最多改 50 行；
  - 表名一律加双引号；
  - 新插入的行使用给出的下一个可用主键。
- **USER 消息依次包含：**
  - 库描述；
  - 数据块，标明哪块是说话人自己的、哪块是"不属于任何人的公共数据"；
  - 下一个可用主键；
  - DDL；
  - 类型段、形状段、风格段；
  - 最后一条要求：SQL 里的每个字面量都必须出现在 instruction 里，说话人自己行的标识除外。
- **比例的来源：** 类型和难度的比例来自对 DySQL 1062 条任务的实测分类（[dysql_task_types.md](../common/docs/dysql_task_types.md)）。第 2 类的比例调低了，因为 DySQL 里这一类大多来自 retail 一个库的特殊结构。

### 第 5 步：出题（`generate.py`、`llm.py`）

- **模型和参数：** GLM-5.3，走 Z.ai Coding Plan 的 OpenAI 兼容接口。temperature 1.0，top_p 0.95，max_tokens 16384，并发 5（订阅上限）。
- **解析和容错：**
  - 从回答里解析 `<answer>` 中的 JSON；
  - 每条一返回就写盘；
  - 遇到 429 和 5xx 退避重试；
  - `--retry-errors` 重新生成 API 调用失败的候选。
- **用量：** 每条候选约 8.3k token（输入加输出）。

### 第 6 步：执行检查（`check.py`）

在库的内存副本上按顺序执行 gold SQL，触犯任何一条规则就丢弃：

| 规则 | 拒绝原因 |
|---|---|
| SQL 报错，或包含 BEGIN、COMMIT 之类的事务语句 | `sql_error`、`txn_control` |
| UPDATE 或 DELETE 命中 0 行（INSERT 到空表允许） | `noop_write` |
| 一行都没改 | `no_write` |
| 单条语句改了超过 50 行 | `bulk` |
| 写入的表不在任何锚点的范围内 | `out_of_scope` |
| 字面量既不在 instruction 里，也不是说话人自己那一行的值 | `literal_missing` |

字面量检查对以下几种情况放行：0、1、true、false；含 `%` 的模式；各种写法的日期；"one" 到 "twelve" 这样的数字单词。

**同时按 gold SQL 算出三个标签：**
- **类型：** 每条写入沿外键追到人，看改的是本人的、别人的还是公共的数据。
- **难度：** 五项各 1 分：多条写语句、写多张表、子查询、归档、第 2 或第 4 类。0 分是简单，1–2 分是中等，3 分及以上是困难。
- **模板：** 类型 + 写入的（表，操作）集合。

**校准：** 在 DySQL 的 1062 条 gold 任务上，除第 7 类外通过 90%；再去掉部分 no-op 任务后通过 95%（[校准记录](docs/2026-09-28-check-calibration.md)）。

### 第 7 步：LLM 校验（`verify.py`）

- **模型和投票：**
  - 用本地 vLLM 0.30 跑 `nvidia/Qwen3.8-27B-NVFP4`，开 thinking（服务脚本 `scripts/serve_verifier.sh`，端口 8003）；
  - temperature 1.2，投 3 票，Yes 比 No 多才通过；
  - 解析不出结论的票算 No；API 失败的不算一票，续跑时重投。
- **prompt 是重写的：** 官方的校验 prompt 把 gold SQL 当成 agent 的对话记录来审，试点第一轮 93 条全被拒。现在只审五件事：
  1. SQL 是否正确、完整地实现了请求；
  2. 有没有多改；
  3. 参数是否都在请求里；
  4. 看不到 SQL 的 agent 能否得到同样的结果；
  5. SQL 是否合法。
- **为什么全量还没校验：** 3 票平均约 125 秒一条（并发 32），这一轮 3816 条要 5.5 天左右，校验模型还没定下来。`.env` 现在指向 Ollama 上的 `deepseek-v4.1-flash`，它没有校准过，不要直接用。

### 第 8 步：去重封顶（`dedup.py`）

- 每个人物行最多 2 条，每个模板最多 15 条，每个库最多 600 条。
- 稀有模板优先入选，这样长尾不会被每库上限挤掉。

### 第 9 步：转换和评测（`convert.py`、`DySQL-Bench/dysql_bench/envs/gen/`）

- **任务文件：** `output/<db>/tasks.jsonl` 每行是 DySQL 的 Task 格式（`user_id`、`instruction`、`actions`），另加 `meta`：库、锚点、算出的类型、难度、模板、出题计划、出题模型、每票的结论。
- **manifest：** `output/manifest.json` 记录每个库的 SQLite 路径和任务文件路径。任务路径相对于 manifest 所在目录。
- **评测侧：** `GenEnv` 只读 manifest，不 import 出题代码。评测时在 `DySQL-Bench/` 下运行，其余参数和评测 DySQL 的 13 个库一样：

```
TASKGEN_MANIFEST=../taskgen/v1/output/manifest.json python run.py --env gen:beer_factory --task-split train ...
```

## 3. 怎么跑

**准备：**
- conda 环境 `dysql`，里面装了 `dysql_bench`。
- 仓库根目录的 `.env`（不进 git）里配好两组变量：出题用 `TASKGEN_GEN_BASE_URL`、`TASKGEN_GEN_API_KEY`、`TASKGEN_GEN_MODEL`，校验用 `TASKGEN_VERIFY_BASE_URL`、`TASKGEN_VERIFY_API_KEY`、`TASKGEN_VERIFY_MODEL`。
- 原始库放在 `TEXT2SQL_BENCH` 指向的目录（默认 `~/Documents/Isa/text2sql_bench`）。

**一个库走完全部步骤**（要先把校验模型起来）：

```
cd taskgen/v1
bash scripts/serve_verifier.sh && bash ../../DySQL-Bench/scripts/wait_ready.sh 8003
bash scripts/taskgen_pilot.sh bird:beer_factory 100 3      # <库> [树数] [票数]
```

**全量出题**（不含校验），覆盖所有有 `person_named` 锚点的库：

```
cd taskgen/v1
nohup bash scripts/taskgen_generate_all.sh 200 > results/generate_all.log 2>&1 &
nohup bash scripts/taskgen_checkpoint.sh $! > /dev/null 2>&1 &     # 每 2 小时往 results/checkpoints.log 记一行进度
```

**之后校验和收尾：**
- 运行 `scripts/taskgen.py verify --all-dbs --db <任意库>`。`--db` 在加了 `--all-dbs` 时仍然必填，但值不起作用。
- 然后对每个库运行 `dedup`、`convert`、`stats`。库的列表和 `taskgen_generate_all.sh` 用的相同。

**补充：**
- **断点续跑：** 任何一步中断后原样重跑即可。
- **换输出位置：** 中间文件用 `--out-dir`，最终任务用 `--tasks` 和 `--manifest`。
- **测试：**

| 目录 | 命令 | 测试数 |
|---|---|---|
| v1 | `cd taskgen/v1 && pytest` | 71 |
| 选库 | `cd taskgen/common && pytest` | 65 |
| 评测侧 | `cd DySQL-Bench && pytest` | 33 |

## 4. v1 的结果

**试点（beer_factory，2026-09-29）：**
- 100 条候选，过执行检查 93 条，过校验 82 条，去重后仍是 82 条。
- 类型和难度的分布接近目标。模板 45 个，最大的模板占 11%，每人 1.0 条，都在 DySQL 的区间里。
- Qwen3-4B 在这 82 条上通过率 23.2%，它在 DySQL 上是 29.8%。
- 详见 [试点报告](docs/2026-09-28-pilot-beer-factory.md)。

**全量（23 个库，2026-09-30）：**
- **数量：** 4159 条候选，其中 100 条是试点时用旧 prompt 出的。API 或解析失败 21 条，过执行检查 3816 条（91.8%），用时 15 小时。
- **拒绝原因**（一条候选可能有多个）：sql_error 176，literal_missing 116，noop_write 81，no_write 38，no_instruction 21，out_of_scope 5，bulk 4。
- **分布：**

| | 第 1 类 | 第 2 类 | 第 3 类 | 第 4 类 | 第 5 类 | 简单 | 中等 | 困难 |
|---|---|---|---|---|---|---|---|---|
| 算出的 | 46% | 9% | 3% | 12% | 29% | 21% | 43% | 36% |
| 目标 | 46% | 12% | 5% | 8% | 29% | 26% | 45% | 29% |

- **类型不一致：** 要求的类型和算出的类型不一致的有 8%，试点里是 0。原因分析见运行记录。
- **还没跑：** LLM 校验、去重、转换。
- 每库数字和过程记录见 [全量运行记录](docs/2026-09-30-taskgen-full-run.md)。

## 5. 和论文、官方代码的对照

| 环节 | 论文 / 官方代码 | v1 |
|---|---|---|
| 选主表 | 人工分析，每库一张；代码没放出 | 规则选锚点，每库所有带名字的人物锚点都当根 |
| 建树 | 作者用 LLM 辅助逐库设计（模型未说明），以事件为单位嵌套，往上多跳；代码没放出 | 通用代码，按表平铺，往下 2 跳、往上 1 跳 |
| few-shot | 每次从 `r1_tau_r1_5w.json` 抽 1 条（文件没放出） | 手写 15 条，按类型抽 1 条 |
| 出题 | GPT-4.1（ACL 版写的是 GPT-4），temperature 1.2 | GLM-5.3，temperature 1.0；加了类型、难度、形状、风格控制 |
| 校验 | DeepSeek-R1 和 Qwen3-235B 两个模型各查 n 次；refine 前后各审一轮 | 一个模型（Qwen3.8-27B）投 3 票，多数通过；只审一轮；prompt 重写 |
| Refine | 把缺的参数回填进 instruction 后再审 | 不做，不合格的直接丢 |
| 可执行性 | 在 mock 环境执行，报错就丢；代码没放出 | 执行检查规则更多，放在校验之前，并在 DySQL 上校准过 |
| 人工审核 | 10 位专家审完全部 1072 条 | 没有 |
| 去重封顶 | 没有 | 每人、每模板、每库封顶 |
| 转成任务 | 只保留 `outputs` 为空的任务；没有转成 env 格式的代码 | `convert` 加通用的 `GenEnv` |

## 6. 已知问题（v2 的输入）

**锚点（第 1 步）**
- **多根：** 每个库所有符合条件的人物表都当根，而 DySQL 自己大多一库一个根（chinook、music、pagila 都只用了客户表）。8 个库有 2 个锚点，题量因此翻倍，其中一些根的场景很弱，比如 books 的 author、shipping 的 driver。
- **把非人物表当成人：** professional_basketball 的 `draft`（选秀记录）；legislator 的 `historical-terms`（任期记录，抽到的根行姓名为空）。
- **姓名列识别错误**（规则是"以 name 结尾的列都算"）：
  - IPL 的球员名拼上了国家名，变成 "S Vidyut India"；
  - college_2 的姓名拼上了系名；
  - car_retails 把公司名和联系人拼在了一起；
  - superhero 的全名是 `-`。

**建树（第 2 步）**
- **按表平铺，父表只挂一跳、每表 3 行：**
  - 试点里一棵树有 15 条交易，只有 3 条能看到对应的商品；
  - 两跳以上的公共表（品牌、专辑、歌单）完全看不到，相关的题出不来。
- **每张表独立抽样：** 兄弟表（比如交易和评价）之间对不上。
- **人物父表被标错：** 父表本身是人物表时，数据块仍标成"不属于任何人"。这是全量里类型不一致的最大来源（154 条）。其中 legislator、professional_basketball 的"父表人物"其实就是说话人自己在另一张表里的行。

**出题（第 4–5 步）**
- **撞唯一约束：** 复合主键（如 `player_match`）、UNIQUE 列（如 `Wrestlers.name`），以及 student_loan 的文本主键，都不在"下一个可用主键"的覆盖范围内。
- **BIRD 原始数据的错误：** 比如 address 的名和姓存反了、列名拼错了。模型会自作主张"纠正"，结果执行失败。
- **无意义的公共表：** student_loan 的 `bool` 表只有 neg、pos 两行，不该当公共数据去写。
- **"改什么"没有控制：** 简单题偏向改电话、改地址。
- **few-shot 的副作用：** 15 条示例都把 ID 写全了，等于示范了"不用查库"的请求。
- **措辞趋同：** v2 prompt 已经加了风格抽样，但全量的效果还没量化。

**检查和校验（第 6–7 步）**
- **校验偏松：** 校验模型还没定。一个模型投多数票，比论文的两个模型各查 n 次松；没有 refine，也没有人工审核。
- **执行检查的漏洞：** 字面量检查是子串匹配，`203` 能匹配上 `2030`；gold 里的 `CURRENT_TIMESTAMP` 能过检查，但评测时永远对不上。
- **第 4 类和 agent policy 冲突：** 第 4 类（替别人改数据）违反 agent policy 的"只能帮一个用户"。4B 在试点里这一类是 0/6，去留还没定。

## 7. 文档

| 文档 | 内容 |
|---|---|
| [docs/2026-09-28-task-gen-design.md](docs/2026-09-28-task-gen-design.md) | 设计和当时定下的决定 |
| [docs/2026-09-28-task-gen-plan.md](docs/2026-09-28-task-gen-plan.md) | 实现计划（15 个任务） |
| [docs/2026-09-28-check-calibration.md](docs/2026-09-28-check-calibration.md) | 执行检查在 DySQL 上的校准 |
| [docs/2026-09-28-pilot-beer-factory.md](docs/2026-09-28-pilot-beer-factory.md) | 试点报告、校验 prompt 的重写、prompt v2 |
| [docs/2026-09-30-taskgen-full-run.md](docs/2026-09-30-taskgen-full-run.md) | 全量运行记录和结果 |
| [../common/docs/](../common/docs/) | 选库条件、筛选器修正计划、外键校准、DySQL 任务分类 |

设计、计划和试点报告写于 2026-10-01 目录重组之前，文中是旧路径，新旧对照见 [../README.md](../README.md)。
