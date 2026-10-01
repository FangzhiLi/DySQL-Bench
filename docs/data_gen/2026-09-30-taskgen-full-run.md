# 训练任务生成：第一阶段全量运行记录

开始：2026-09-30 01:20（EDT）。分支 `isa/data-gen`，代码未 commit（用户要求先不提交）。
设计：`docs/2026-09-28-task-gen-design.md`。试点：`docs/data_gen/2026-09-28-pilot-beer-factory.md`（prompt 修改见其 §8）。

这份文档记录这一轮全量的过程、观察到的问题和待补的事。跑完后在"结果"一节填每库数字。

## 1. 这一轮跑什么

- **范围：** 23 个有 `person_named` 锚点的库，31 个锚点。
- **步骤：** `trees → describe → generate → check`。**不跑 verify / dedup / convert**，等校验模型定下来再跑。
- **参数：** `--n 200 --per-tree 1 --seed 0`；GLM-5.3，出题并发 5；`generate` 连跑两遍 `--retry-errors` 补 429。
- **预计：** 约 4.3k 条候选（beer_factory 另有 100 条旧 prompt 的候选）。
- **prompt 版本：** v2（表名一律加双引号、给出下一个可用主键、说话人姓名/职务/开场风格按 plan 抽样）。beer_factory 的旧候选没有 `plan.style` 字段，可以据此区分。
- **库描述：** 23 条已由 GLM 生成（`docs/data_gen/db_descriptions.json`），逐条对照表和列核过，没有需要改的。

## 2. 怎么跑、看哪里

| 用途 | 位置 |
|---|---|
| 全量脚本 | `DySQL-Bench/scripts/taskgen_generate_all.sh 200`（nohup 后台，pid 1376318） |
| 总日志 | `DySQL-Bench/results/taskgen/generate_all.log`，每库一行 `==` 开始、一行 `db_wall_s` 结束；出错记 `FAILED` |
| 每库日志 | `DySQL-Bench/results/taskgen/<db>/generate_all.log` |
| 每库产物 | `DySQL-Bench/results/taskgen/<db>/{trees,candidates,check}.jsonl`、`others.json` |
| 定点记录 | `DySQL-Bench/results/taskgen/checkpoints.log`，由 `checkpoint.sh` 每 2 小时追加一行（已开始库数、FAILED 数、候选数、check 通过数），结束时记 `finished` |

中断后原样重跑脚本即可，各步按 id 续跑。

## 3. 过程记录

- **01:20** 启动。01:27 第一条 checkpoint：address 进行中。
- **01:30** address 出了 39 条，API/解析失败 0。在内存里预跑 check：31/39 通过（79%，beer_factory 是 93%）。速度约 14.6 秒/条（试点 10.5 秒），address 的 prompt 平均 5.6k token。按此推算全量 13–17 小时。
  - 9 条 0 行命中：BIRD 原始数据里 `congress` 表名和姓存反了（`first_name='Eshoo', last_name='Anna'`），模型按常识写 `first_name='Anna'`，子查询匹配不到。
  - 2 条 SQL 报错：原表列名拼错（`cognress_rep_id`），模型"纠正"成 `cogngress_rep_id`。
  - 1 条 INSERT 撞复合主键 `zip_congress(zip_code, district)`。
  - 这些都被 check 正确拦掉，不进候选池；损失的只是产量。

- **10:15** 进度检查。10/23 个库完成，第 11 个 professional_basketball 进行中（152/400）。日志无 `FAILED`，没有限流迹象。已完成的 10 个库 check 通过 1933/2066（93.6%）。
  - 两遍 `--retry-errors` 之后仍有 0–3 条/库 `instruction=None`（共 13 条，约 0.6%），按设计不再重出，由 check 记为 `no_instruction`。
  - beer_factory 有 264 棵树而不是 200：试点那 100 棵是按旧版抽样代码抽的，和现在的 `--n 200` 抽样只重叠 36 个人，所以新增了 164 棵。多出来的只是候选数，没有问题。
  - 拒绝原因：books 主要是 `literal_missing`（26）；legislator 是 `sql_error` 13、`noop_write` 10、`out_of_scope` 5；olympics 是 `literal_missing` 9。
  - 实际速度约 15 秒/条（01:20–10:15 共出 2118 条）。按剩余约 2.1k 条推算，预计 19:00–20:30 完成。
  - 夜里设的两个唤醒监视进程随上一个 Claude 会话结束而停掉了。出题进程和 `checkpoint.sh` 不受影响，10:15 已重新设了完成通知。

- **11:58** 13/23 个库已开始，第 13 个 retail_complains 进行中（168/200）。无 `FAILED`。professional_basketball check 357/400（89%），主要是 `literal_missing` 37（球员统计类 INSERT 的数值没全写进 instruction）；regional_sales 47/50。当前约 11–13 秒/条，剩约 1.5k 条，预计 16:30–18:30 完成。

- **14:39** 17/23 个库完成，第 18 个 IPL 进行中（164/200）。无 `FAILED`。新完成：retail_complains 193/200、shipping 111/111、synthea 191/200、student_club 32/33、superhero 191/200。
  - **student_loan 只有 144/200（72%）**，全场最低，是这个库的结构造成的：所有表都用文本主键 `name`（'student123'），唯一的公共表 `bool` 只有 'neg'/'pos' 两行。53 条 `sql_error` 基本都是撞主键：往 `bool` 插 'neg'/'pos'，或把人改名成已存在的 'studentNNN'。文本主键不在 `next_ids` 覆盖范围内。另有 14 条 `no_write`。check 都拦掉了。
  - 跟进项：`bool` 作为"公共数据"没有意义，第 2、3 类在这个库出不出合理的题；补生成或下一轮时考虑把它从 student_loan 的 up 表里去掉。
  - 剩余约 530 条（IPL 余下、WWE、school_scheduling、college_2），预计 16:15–17:00 完成。

- **16:19** 21/23 完成，最后一个 college_2 进行中（221/250；hr_1 冒烟时已跑完）。无 `FAILED`。IPL 163/200（82%）：`sql_error` 34，主要是 `player_match` 复合主键冲突和 `player_id` 非空约束；WWE 172/200（86%）：`sql_error` 25，主要是 `Wrestlers.name`、`Belts.name` 的唯一约束（插入或改名成已存在的名字）；school_scheduling 40/42。预计 16:30 前完成。
  - 跟进项：除整数主键外，复合主键和 UNIQUE 列（`name` 之类）也会撞，`next_ids` 管不到；补生成时可在 prompt 里提示"新值不能与已有行的唯一列重复"。

（后续观察按时间追加在这里。）

## 4. 这一轮跑完后要补的事

1. **补生成（refill）。** 对 idx 0 候选没过 check 的树，用同一棵树再出一条 idx 1。需要给 `generate` 加 `--refill-failed` 选项。预计 10–20% 的树需要补，额外 2–3 小时。符合设计"不合格直接丢，产量不够再补生成"。不手工修失败候选的 SQL。
2. **prompt 加一条通用规则**（补生成那一轮开始用）："列名和值必须照抄 DDL 和数据块，即使看起来拼错或名姓颠倒"。针对上面 address 的两类失败，BIRD 里这类原始数据问题不少见。
3. **校验模型。** `.env` 目前指向 Ollama 上的 `deepseek-v4.1-flash`，没有在试点 93 条上和 27B 对比过。先校准（一致率、解析失败率、并发 3 的吞吐），再 `verify --all-dbs`，然后逐库 `dedup`、`convert`。
4. **commit。** 本轮改动（prompt v2、`schema.next_ids`、`others.json` 修复、每锚点 rng、`taskgen_generate_all.sh`、测试）等用户确认后再提交。
5. **student_loan 的 `bool` 表**不该当公共数据写，见 §3 14:39 条。
6. **第 4 类（替他人改数据）是否保留**，试点报告 §6 第 3 条，仍待决定。

## 5. 结果

（跑完后填：每库候选数、API/解析失败数、check 通过率、主要拒绝原因、要求类型与算出类型的分布、耗时。）
