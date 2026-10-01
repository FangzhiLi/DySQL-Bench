# 训练任务生成 v2：设计

**日期：** 2026-10-01　**状态：** 已确认（2026-10-01）。实施计划分几份写：计划 1（阶段 A、G、E）见 `2026-10-01-taskgen-v2-plan-1.md`，计划 2（阶段 B、C，执行检查读档案）见 `2026-10-01-taskgen-v2-plan-2.md`；出题、校验和运行的计划在前一份完成后再写
**起点：** v1（tag `taskgen-v1`，61c8133），复制到 `taskgen/v2/`，包名 `taskgen_v2`。
**依据：** 论文（ACL Findings 2026）§3 和附录 J、官方 `data_pipeline_shell/`、v1 全量结果（3816 条）与 DySQL 1062 条的逐项对比。

## 1. 目标

用论文的做法（逐库档案、嵌套事件树）加 v1 的通用流水线（计划抽样、执行检查、封顶、`GenEnv`），生成 DySQL 风格的多轮写操作任务作为 GRPO 训练数据。要求任务的统计特征落在 DySQL 的范围内，gold 的可靠性不低于 v1 并有校准证据。

## 2. 已定的决定

| # | 决定 | 来源 |
|---|---|---|
| D1 | 每库一份**人工确认过的档案**（主实体、人物表和姓名列、身份键、事件表及其父表、属性表、公共表、排除表、数据怪异点、库描述）；LLM 起草，人工过，建树拒绝未确认的档案 | 论文 Fig. 14 前两步；v1 的 draft/historical-terms 误判、4 个库姓名列拼错、154 条归属标错 |
| D2 | 根默认一个，college_2 和 school_scheduling 双根；hr_1、address 保留；23 个库的根见 §4.1 | 论文每库一个主实体；DySQL 两群人都会来的库有例外 |
| D3 | 树以事件记录为单位嵌套，父行取被抽中事件实际引用的；出题时再抽事件 | 论文 Fig. 14 的 `build_info_tree`；v1 兄弟表对不上、两跳公共表看不到 |
| D4 | 校验先用**一个模型**：`deepseek-v4.1-flash`，走 ollama.com 的 OpenAI 兼容接口（`.env` 已配好）；代码按"模型列表 + 每模型票数"设计；要不要加第二个由校准决定 | 官方实际是两模型串跑各过多数；我们有执行检查在前、GRPO 奖励统计在后兜底 |
| D5 | 校验模型先做**校准**，三组样本：①正样本 = 过了 v2 执行检查的 DySQL gold（原样 gold 的通过率单独报告，不设门槛）；②负样本 = 程序化改坏的 gold，只算改坏后库哈希确实变了、且仍过执行检查的；③人工标注的真实候选 100–150 条（v1 试点的 93 条起步），覆盖 instruction 一侧的错误。漏的类别补进执行检查，而不是加模型 | 单模型的风险是系统性盲点。DySQL gold 本身有坏题（47 条全 0 行、42 条缺字面量、约 3 条把当前时间写进评测会比较的列、retail 按不唯一邮箱定位），而且被 DeepSeek-R1 筛过，用同系模型校准会偏高 |
| D6 | **这一轮不出第 4 类**（库内的人改别人的数据），也不为此加 staff 根；类型只抽 1、2、3、5；用档案检查时，算出第 4 类的候选拒掉（`other_person`）。备注见 §4.8 | agent policy 写明 "must deny any requests for tasks related to any other user"（v1 试点 4B 在第 4 类 0/6）。DySQL 按 check 规则的 17.6% 是假象：186 条里 retail 占 100（不唯一邮箱把同邮箱的别人算进来）、eu_soccer 35（分析员被当成库内人）、8 条写入（6 题）是新插入的人物行被算成"别人"；真实的约 5% |
| D7 | gold 里不放 SELECT；prompt 去掉 `outputs` 和只读提问 | 奖励只看库哈希；v1 73% 的题带只读提问，DySQL 4% |
| D8 | 说话人"名字 + ID/邮箱"一起给，被改的记录直接给 ID；按归属子查询的形状降到 10% 左右 | DySQL 92.4% 前 25 词内给 ID、邮箱、SSN 或 #编号（`metrics.ID_RE`），语句含子查询 5.9%；v1 36.9% / 44.6%（§3） |
| D9 | 新行 ID 算隐含字面量、prompt 允许不写 ID，**只限"可省 ID"的表**：主键是 rowid 别名（`INTEGER PRIMARY KEY`），且没有 AUTOINCREMENT 或 `sqlite_sequence.seq = MAX`。其余表的新 ID 必须出现在 instruction 里（v1 的规则），或档案标成不出 INSERT | v1 70 条 literal_missing 是 next id。23 个库 205 张表里可省 ID 的只有 86 张：WWE 8 张表 seq ≠ MAX（不写 ID 分到的不是 MAX+1），52 张主键是 TEXT/VARCHAR/DECIMAL（不写 ID 会插进 NULL 或报 NOT NULL），41 张复合键，19 张无主键 |
| D10 | 第一阶段仍用 v1 的 23 个库；实体库放第二阶段 | 和 v1 可比 |
| D11 | 不做全量人工审核；每库抽 30 条人工看，训练时全程 0 分的题事后剔 | 训练数据，不是评测集 |
| D12 | 生成物不进 git；`taskgen/v2/results/`、`output/` 已被 ignore | 公开 fork |

## 3. 验收指标

v2 试点和全量都用 `task_stats.py`（§5 G）和 DySQL 比，目标区间取自 DySQL 的实测值：

| 指标 | DySQL | v1 | v2 目标 |
|---|---|---|---|
| 每题写语句数分布 1/2/3/4/≥5 | 33 / 47 / 12 / 5 / 3（%）；中位 2；均值 2.29 被 27 条 ≥6 条的长尾拉高（eu_soccer 16、bowling 8，最多 68 条），截到 5 后均值 1.97 | 38 / 47 / 14.4 / 0 / 0，均值 1.76 | 33 / 45 / 13 / 6 / 3，均值 1.9–2.1 |
| ≥3 条写语句的题 | 20.0%（212/1062；论文的 Long 47% 是连 SELECT 一起数的） | 14.4% | 18–24% |
| instruction 含只读提问 | 4.2% | 73.4% | <5% |
| instruction 词数均值 / p90 | 57 / 80 | 102 / 146 | 50–80 / <110 |
| 前 25 词内出现 ID、邮箱、SSN 或 #编号（`metrics.ID_RE`） | 92.4% | 36.9% | ≥80% |
| 语句含子查询 | 5.9% | 44.6% | <15% |
| 每题写入表 ≥2 | 56.8% | 46.2% | ≥50% |
| 每题改动 >10 行 | 6.2% | 0.7% | 3–8% |
| 类型 1/2/3/5 | 分类脚本：本人 40、本人+公共 15、只改公共 5、库外代办 23（另有改别人 5、改实体 8、无改动 5） | 46/9/3/30（另有第 4 类 12） | 50 / 13 / 6 / 31 左右；不抽第 4 类 |
| 难度 easy/medium/hard | 26/45/28 | 21/43/36 | 25–30 / 40–50 / 25–30，且"难"主要来自多语句多表 |
| 执行检查通过率 | 85.5%（gold，908/1062，分母含 47 条无改动题） | 91.8% | ≥92%；在 DySQL gold 上，新增的拒绝只来自列出的原因（时间函数约 3 条等），逐条看过；实测 DySQL 908 → 895，v1 候选 3816 → 3872，见 `docs/2026-10-01-check-recalibration.md` |
| 校验：正样本通过率 | — | 未校准 | 过了 v2 执行检查的 DySQL gold ≥95% |
| 校验：负样本被拒率 | — | — | 按改坏类别报告，整体 ≥80%；人工标注集上报告精度和召回 |
| 要求类型 = 算出类型 | — | 92% | ≥97% |

## 4. 各环节设计

### 4.0 目录与起点
- `taskgen/v2/` = v1 的纯复制（包、scripts、tests、data/db_descriptions.json、conftest、pytest.ini），不复制 docs/results/output。第一个 commit 只改名，`diff -r` 只剩改名行，71 个测试照过，同 seed 下 trees 和 prompt 的输出与 v1 相同。
- 之后每处改动单独 commit，`git diff <复制commit> -- taskgen/v2` 就是 v2 相对 v1 的全部逻辑改动。

### 4.1 库档案（新模块 `db_profile.py`，新子命令 `taskgen.py profile`）
**输入：** DDL、每表 3 行样例、`candidate_anchors.json` 里的锚点候选和外键、BIRD 列说明；2–3 个 DySQL 库的手写档案作示例。
**输出：** `data/db_profiles.json`，每库一条：

```
roots: [{table, label, parents}]                        主实体，默认一个；身份键和姓名列只写在 persons 里，
                                                         parents 和事件的一样，挂根行引用的行（销售代表、院系）
persons: {table: {key, name_cols, same_as: [table.col]}} 哪些表是人；same_as 是身份键：同一个人在另一张表的行
                                                         （historical ↔ historical-terms.bioguide，players ↔ draft.playerID）
events: [{table, path: [fk...], parents: [{table, via, parents: [...]}], label}]
                                                         path 是从根到事件的外键路径（customers → orders → orderdetails）；
                                                         parents 是一棵树，不是一条链（shipment 同时引用 driver、truck、city）
attributes: [{table, of, via}]                           1:1 的属性表（social-media、student_loan 的 flag 表），随所属行一起展示
public: [table...]  exclude: [table...]  no_insert: [table...]
quirks: ["address: first_name/last_name 存反", "congress.cognress_rep_id 拼写如此"]
description: 2–3 句
confirmed: false → 人工过后改 true
notes, draft: 审阅用（Claude 的改动；起草模型、轮数、没改掉的问题），不计入版本号
```

边写成 `child.col -> parent.col`，复合外键写成 `child.(a, b) -> parent.(x, y)`；不在已知外键里的边，要有 ≥30% 的子行能在父表里找到。父表那一侧的列必须唯一，一条边只通向一行父行（计划 2 预审时加的：起草里有写反方向的边）。每张表都要有角色（roots、persons、events 及其路径、parents、attributes、public、exclude 之一），漏了算错。

**流程：** `taskgen.py profile draft` 起草（GLM；输入另有 `data/profile_hints.json` 里每库的根和已知怪异点、`taskgen_v2/profile_examples.json` 里两份手写的 DySQL 示例；校验不过或根和提示不一致，就带着问题重写，最多 2 次）→ Claude 预审（怪异点逐条查库核实，改动记进 notes）→ `profile render` 生成审阅页（样例树另写到 `results/`）→ 人工改 → `profile confirm`（校验不过不让确认）。未确认的库，`trees`、`generate`、`check` 拒绝运行。
**23 个库的根（草案）：** beer_factory customers；books customer；book_publishing_company authors；car_retails customers；regional_sales Customers；retail_complains client；shipping customer；legislator historical（historical-terms 为事件）；professional_basketball players（draft 为事件）；IPL player；WWE Wrestlers；olympics person；movie actor；movies_4 person；superhero superhero；synthea patients；student_club member；student_loan person（exclude bool；flag 表算属性表，计划 2 定）；food_inspection_2 employee；college_2 student + instructor；school_scheduling Students + Staff；hr_1 employees；address congress。
**可选检验：** 对 DySQL 13 个库也起草一遍，看根是否和论文一致（Bowlers、customer、Entertainers…）。

### 4.2 建树（改 `trees.py`）
- 读档案。根行 → 沿各事件的 `path` 取出属于根的事件记录 → 沿 `parents` 树逐级嵌套父行（交易 → 商品 → 品牌；shipment 同时挂 driver、truck、city）；兄弟事件表各自成列表；`attributes` 随所属行展示。
- 存全树或 ≤30 条事件；不再生成 `others.json`。
- 每块数据带归属标签：`own` / `other:<name>` / `public`，来自档案的 `persons`；`same_as` 连到的行标 `own`。
- 根行先抽有事件的，不够再抽没有事件的（hr_1 的 107 个员工里只有 7 个有 job_history）；双根库按各自可用的行数分 `--n`，一个根不够就让给另一个。
- 出题时按难度抽 3–5 / 5–8 / 8–12 条事件，数据块超过 16000 字符就从后往前减；第 2、3 类先放一条带公共父行的事件。超过 200 字符的文本值截断（WWE 的 Cards 存整页 HTML）。
- 标签由 `owners.Tracer` 算，执行检查用同一份代码：prompt 里标 own、public 的行，写进去算出来也是 own、public。

### 4.3 schema 与素材（改 `schema.py`）
- DDL + BIRD 列说明 + 档案 `description`（取代 `describe`）。
- 每表给出 UNIQUE 列、复合键，并把主键分成三类写进 prompt：
  - **可省 ID**（rowid 别名且 seq = MAX）：给 next id，新行可以不写 ID，写了也不必让用户说出来。
  - **ID 必须由用户给出**（WWE 那 8 张 seq ≠ MAX 的表；hr_1 的 DECIMAL 主键；college_2 这类数字样式的 VARCHAR 主键）：给 MAX+1 作建议值，instruction 里必须出现。
  - **不出 INSERT**（student_club 的 `rec…`、synthea 的 UUID、legislator 的 bioguide 这类没有"下一个"的文本主键）：档案里标 `no_insert`，只出 UPDATE/DELETE。
- 规则："不要 UPDATE 键列；INSERT 前对照给出的已有值"。
- 不改库文件（不重置 `sqlite_sequence`），保持和来源库逐字节一致。
- `quirks` 原样列出，加规则"列名和值原样照抄，即使看起来是错的"。

### 4.4 出题计划与 prompt（改 `prompt.py`、`examples.json`）
- 写语句数按 DySQL 分布抽：1/2/3/4/5 条 = 33/45/13/6/3（%）。v1 是 38/47/14.4/0/0，差距其实不大，主要是补上 4–5 条。
- 删 `outputs` 字段和只读提问；长度目标 40–80 词、3–4 句；风格段精简。
- 说话人介绍含 ID/邮箱的比例按 §3 的目标（前 25 词内 ≥80%）；`ownership_subquery` 形状 ~10%。
- 新增批量形状 ~6%（按条件改删 2–50 行）；新增"改什么"：从事件行抽目标列。
- 类型只抽 1、2、3、5 四类。
- few-shot：手写示例改成 DySQL 式（名字 + ID 开头、40–80 词、没有只读提问、可省 ID 的新行不念 ID）。**不用 v1 的产出当示例**：它们带着 v1 的毛病（73% 有只读提问、平均 102 词），会把这些毛病传下去。试点之后可以把 v2 校验通过的任务加进示例池（自举，像官方），运行时从本地 `output/` 读，不写进 `examples.json`，因为生成物不进 git。
- 比例从档案或 `CFG` 读，每库可覆盖写语句数倾向（可选）。

### 4.5 执行检查（改 `check.py`）
- 字面量按词边界匹配，序数词 first…twelfth → 数字。
- **SQLite 会自动分配的新主键算隐含字面量：** 表是"可省 ID"的（`schema.pk_info`，§4.3），INSERT 写的主键正好是 SQLite 会分配的下一个值（多行时依次加一）。这个值在这条 INSERT 和之后引用新行的语句里都不必出现在 instruction 里。其余表的新 ID 仍必须在 instruction 里。这个值在每条 INSERT 执行前按 SQLite 的规则现算（MAX 和 `sqlite_sequence` 取大者加一），前面的语句删掉最大行时也对。往 `no_insert` 的表 INSERT 拒绝（`no_insert`）。
- **非确定性：** gold 里有读时钟或随机数的函数（`CURRENT_TIMESTAMP`、`'now'`、`random()` 等）时，间隔 1.1 秒执行两遍，比较评测哈希会比较的列（去掉 `last_update` 这类 volatile 列，正则和评测一致）；不一致就拒（`nondeterministic`）。只精确到日的值（`CURRENT_DATE`、`date('now')`）同一天内一致，放行；写进 volatile 列的时间也放行（pagila 的 `last_update = CURRENT_TIMESTAMP`）。不含这些函数的 gold 不重跑：同一个库上执行同样的语句，SQLite 的结果是确定的。
- 带档案时：范围 = 档案里有角色的表减去 `exclude`；归属追溯用档案的 `persons`、档案里的边和 `same_as`，加上已记录的外键（含复合外键），追溯到 `public` 表就停，公共行不属于任何人（计划 2 预审时加的：school_scheduling 的院系表引用系主任）；代码在 `owners.py`，建树打标签用同一份；算出第 4 类的候选拒掉（`other_person`，D6）。不带档案时（DySQL 金标准、v1 候选）照 v1。
- **新插入的人物行**不再算"别人"：说话人在库里时，INSERT 进人物表、又追不到说话人的行标 `new_person`，算类型时按公共数据处理（v1 里造成 54 条类型不一致，也是 DySQL 被算出 17.6% 第 4 类的来源之一）。库外说话人（第 5 类）登记新的人，仍算 `person_obj`，不变。INSERT OR REPLACE / UPSERT 覆盖已有的人物行不算新人（看执行前这个主键是否已存在）。
- 其余规则不变（noop、bulk 50、txn、out_of_scope）。在 DySQL gold 上重新校准：相对 v1 新增的拒绝只应来自上面列出的原因（时间函数里会被拒的约 3 条：pagila 把 `CURRENT_TIMESTAMP` 写进 return_date、payment_date；其余写的是 last_update，或只精确到日），逐条看过。

### 4.6 校验（改 `verify.py`、`llm.py` 配置）
- 配置：`TASKGEN_VERIFY_MODELS="deepseek-v4.1-flash:2"`（模型:票数，逗号分隔多个；端点和 key 沿用 `TASKGEN_VERIFY_BASE_URL`、`TASKGEN_VERIFY_API_KEY`）；每个模型 Yes 严格多于 No 才过（2 票即两票都要 Yes），全部模型通过才通过。
- prompt 沿用 v1 重写的五问版。
- 校准脚本 `scripts/verify_calibrate.py`，三组样本（D5）：
  - 正样本：过了 v2 执行检查的 DySQL gold。
  - 负样本：五种改坏（改一个字面量、删一个 WHERE 条件、换一个 SET 列、删最后一条语句、对调两个值）；只保留改坏后库哈希变了、且仍过执行检查的，按类别报告拒绝率。
  - 人工标注集：v1 试点的 93 条起步，不够再从全量里补到 100–150 条。每条标"好 / 坏"（标准：只看得到 instruction、能查库的 agent 能否得到和 gold 一样的库）；坏的再选原因：SQL 没做 instruction 说的事 / SQL 多做了 / instruction 缺信息或有歧义 / 改错了行 / 其它。
    流程：先由 Claude 全部标一遍；用户只复核"Claude 与校验模型结论不一致"和"Claude 拿不准"的条目（估计 20–30 条）。标注文件放 `results/`，不进 git。
  - 同系偏差：DySQL gold 被 DeepSeek-R1 筛过，正样本通过率只作下限参考，判断以负样本和人工标注集为主。
- 顺序改为 check → 预封顶（每模板 ≤25、每库 ≤900）→ verify → 终封顶（v1 的 2/15/600）。

### 4.7 封顶与转换（改 `dedup.py`，`convert.py` 不变）
- 加 instruction 近重复过滤（同库 3-gram Jaccard ≥0.6 只留一条）。
- `meta` 多记档案版本、每模型每票结论。

### 4.8 不做的
- 全量人工审核；refine（窄版留作 v2.1，只改 instruction、SQL 冻结）；实体库；换出题模型。
- **第 4 类（库内的人改别人的数据）这一轮不出。** 留给以后的备注：
  - DySQL 里真实的这类约 5%（HR 经理改员工、经纪人改客户的预约），不是 check 规则算出的 17.6%。
  - 和 agent policy 的 "must deny any requests for tasks related to any other user" 冲突；要出就得按库加授权条款，或者让 staff 当根、只改 staff 自己直接挂着的事件。
  - 第二阶段的实体库（没有人物表的库）里可能自然有这种题型：说话人是库外的管理者，改的是某个实体名下的记录。做实体库时一起评估。

## 5. 实施阶段

每个阶段单独 commit，有测试，完成标准写在括号里。A、E、G 不依赖档案，可先做；B 需要你参与确认。

| 阶段 | 内容 | 完成标准 |
|---|---|---|
| A 骨架 | 纯复制 v1 → v2，改名，`taskgen/v2/README.md` 起点说明 | grep 无 `taskgen_v1`；四套测试全过；同 seed 的 trees/prompt 输出与 v1 相同；结果只写到 `taskgen/v2/` |
| G 统计工具 | `taskgen/v2/scripts/task_stats.py` + `taskgen_v2/metrics.py`：任意任务集 vs DySQL 的指标表（§3 的指标）。放在 v2 而不是 common：DySQL 一列要用本版本的执行检查打标签，common 不能 import 版本包 | DySQL 和 v1 两列都复算出 §3 的数字 |
| E 执行检查 | §4.5 的改动（范围和归属先用锚点，档案出来后切换） | DySQL gold 和 v1 全部 4159 条各重跑一遍，和 v1 的结果逐条 diff：每条由通过变拒绝、由拒绝变通过的，都能归到一条列出的改动 |
| B 库档案 | `db_profile.py`、起草 prompt、渲染脚本；23 个库起草 → 人工确认 | 23 份 `confirmed: true`；DySQL 13 库的根与论文一致（可选） |
| C 建树 | §4.2 | beer_factory 一棵树人工核对；归属标签测试；类型不一致 ≤3% |
| D 出题 | §4.3、§4.4、few-shot | beer_factory 100 条生成 + 执行检查，§3 指标进入目标区间 |
| F 校验 | §4.6 配置化 + 三组样本校准 + 顺序调整；标注集的分歧条目要你复核 | 正样本 ≥95%；负样本和人工标注集的报告；漏的类别补进 E |
| H 试点 | beer_factory 100 条走完全部步骤；与 v1 试点（82 条）和 DySQL 对比；Qwen3-4B 跑一遍 | 指标达标；4B 通过率与 DySQL 同量级 |
| I 全量 | 23 个库，每库 200 棵树（双根库分摊）；check → 预封顶 → verify → 终封顶 → convert | `output/manifest.json` 可被 `gen:<db>` 加载；每库抽 30 条人工看 |
| J 对照 | v1 的 3816 条跑 v2 的 check + verify，得到 v1 对照集 | 两份任务集的 `task_stats` 并排表 |
| K 收尾 | `taskgen/v2/README.md` 全流程、运行记录、memory | — |

## 6. 待查
- `deepseek-v4.1-flash` 在 ollama.com 上的速度、并发上限和限流，阶段 F 实测。
- 实体库的 `entity_anchors_ok` 确认，留到第二阶段。
