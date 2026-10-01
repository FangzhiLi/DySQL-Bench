# 训练任务生成：第一阶段全量运行记录

开始：2026-09-30 01:20（EDT），结束 16:22，共 15.0 小时。分支 `isa/data-gen`。本轮代码 2026-10-01 提交，随后整理进 `taskgen/v1/`（目录说明见 [taskgen/README.md](../../README.md)，v1 全流程见 [v1 总览](../README.md)）。
设计：[2026-09-28-task-gen-design.md](2026-09-28-task-gen-design.md)。试点：[2026-09-28-pilot-beer-factory.md](2026-09-28-pilot-beer-factory.md)（prompt 修改见其 §8）。

这份文档记录这一轮全量的过程、观察到的问题、待补的事和结果。路径都是整理后的新位置。

## 1. 这一轮跑什么

- **范围：** 23 个有 `person_named` 锚点的库，31 个锚点。
- **步骤：** `trees → describe → generate → check`。**不跑 verify / dedup / convert**，等校验模型定下来再跑。
- **参数：** `--n 200 --per-tree 1 --seed 0`；GLM-5.3，出题并发 5；`generate` 连跑两遍 `--retry-errors` 补 429。
- **预计：** 约 4.3k 条候选（beer_factory 另有 100 条旧 prompt 的候选）。
- **prompt 版本：** v2（表名一律加双引号、给出下一个可用主键、说话人姓名/职务/开场风格按 plan 抽样）。beer_factory 的旧候选没有 `plan.style` 字段，可以据此区分。
- **库描述：** 23 条已由 GLM 生成（`taskgen/v1/data/db_descriptions.json`），逐条对照表和列核过，没有需要改的。

## 2. 怎么跑、看哪里

| 用途 | 位置 |
|---|---|
| 全量脚本 | `taskgen/v1/scripts/taskgen_generate_all.sh 200`（nohup 后台，pid 1376318） |
| 总日志 | `taskgen/v1/results/generate_all.log`，每库一行 `==` 开始、一行 `db_wall_s` 结束；出错记 `FAILED` |
| 每库日志 | `taskgen/v1/results/<db>/generate_all.log` |
| 每库产物 | `taskgen/v1/results/<db>/{trees,candidates,check}.jsonl`、`others.json` |
| 定点记录 | `taskgen/v1/results/checkpoints.log`，由 `taskgen/v1/scripts/taskgen_checkpoint.sh` 每 2 小时追加一行（已开始库数、FAILED 数、候选数、check 通过数），结束时记 `finished` |

中断后原样重跑脚本即可，各步按 id 续跑。`taskgen/v1/results/` 不进 git，只在本机（GB10）上。

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
4. **commit：已完成（2026-10-01）。** 本轮改动拆成 4 个 commit 提交，随后出题代码整体搬到 `taskgen/v1/`。
5. **student_loan 的 `bool` 表**不该当公共数据写，见 §3 14:39 条。
6. **第 4 类（替他人改数据）是否保留**，试点报告 §6 第 3 条，仍待决定。
7. **要求类型与算出类型不一致**（8%，见 §5），根因在锚点和建树，留给 v2。

## 5. 结果

**总数：** 23 个库、31 个锚点。候选 4159 条，其中 beer_factory 有 100 条是试点时旧 prompt 出的。API 或解析失败 21 条，执行检查通过 3816 条（91.8%）。用时 15.0 小时（54115 秒）。GLM 共 3457 万 token，平均每条 8.3k。verify、dedup、convert 没跑。

**每库：**

| 库 | 锚点（树数） | 候选 | API/解析失败 | 过执行检查 | 模板数 | 最大模板占比 | 主要拒绝原因 | 用时（分） |
|---|---|---|---|---|---|---|---|---|
| address | congress 200 | 200 | 2 | 166 (83%) | 39 | 14% | noop_write 26, sql_error 15 | 50 |
| beer_factory | customers 264 | 264 | 2 | 249 (94%) | 97 | 8% | sql_error 11, literal_missing 4 | 39 |
| book_publishing_company | authors 19 + employee 43 | 62 | 0 | 61 (98%) | 29 | 18% | literal_missing 2 | 20 |
| books | author 200 + customer 200 | 400 | 2 | 374 (94%) | 141 | 6% | literal_missing 26, no_instruction 2 | 101 |
| car_retails | employees 15 + customers 98 | 113 | 1 | 111 (98%) | 64 | 5% | noop_write 1, sql_error 1 | 23 |
| college_2 | instructor 50 + student 200 | 250 | 1 | 235 (94%) | 77 | 6% | sql_error 10, no_write 6 | 37 |
| food_inspection_2 | employee 27 | 27 | 0 | 25 (93%) | 19 | 12% | bulk 3 | 10 |
| hr_1 | employees 7 | 7 | 0 | 7 (100%) | 6 | 29% | — | 冒烟时跑完 |
| IPL | player 200 | 200 | 2 | 163 (82%) | 87 | 7% | sql_error 34, no_write 6 | 41 |
| legislator | historical 200 + historical-terms 200 | 400 | 3 | 374 (94%) | 34 | 14% | sql_error 13, noop_write 10 | 104 |
| movie | actor 200 | 200 | 1 | 192 (96%) | 47 | 10% | literal_missing 8, sql_error 2 | 39 |
| movies_4 | person 200 | 200 | 1 | 192 (96%) | 80 | 8% | noop_write 7, literal_missing 2 | 45 |
| olympics | person 200 | 200 | 1 | 189 (94%) | 96 | 7% | literal_missing 9, noop_write 4 | 60 |
| professional_basketball | draft 200 + players 200 | 400 | 1 | 357 (89%) | 79 | 15% | literal_missing 37, noop_write 8 | 106 |
| regional_sales | Customers 50 | 50 | 0 | 47 (94%) | 24 | 15% | sql_error 3 | 8 |
| retail_complains | client 200 | 200 | 0 | 193 (96%) | 56 | 15% | literal_missing 6, noop_write 3 | 37 |
| school_scheduling | Staff 24 + Students 18 | 42 | 1 | 40 (95%) | 35 | 8% | sql_error 1, no_instruction 1 | 9 |
| shipping | customer 100 + driver 11 | 111 | 0 | 111 (100%) | 45 | 13% | — | 15 |
| student_club | member 33 | 33 | 0 | 32 (97%) | 20 | 9% | noop_write 1 | 7 |
| student_loan | person 200 | 200 | 1 | 144 (72%) | 81 | 10% | sql_error 53, no_write 14 | 32 |
| superhero | superhero 200 | 200 | 0 | 191 (96%) | 86 | 10% | literal_missing 7, noop_write 6 | 30 |
| synthea | patients 200 | 200 | 1 | 191 (96%) | 120 | 7% | literal_missing 6, noop_write 4 | 37 |
| WWE | Wrestlers 200 | 200 | 1 | 172 (86%) | 59 | 12% | sql_error 25, literal_missing 6 | 51 |

锚点行数不到 200 的库，树数就是能抽到的全部行。beer_factory 的用时只算这一轮新出的 164 条。

**类型和难度**（3816 条过执行检查的候选，标签按 gold SQL 算出）：

| | 第 1 类 本人 | 第 2 类 本人+公共 | 第 3 类 只改公共 | 第 4 类 替他人 | 第 5 类 代办 | 第 6 类 实体 |
|---|---|---|---|---|---|---|
| 实际 | 46% | 9% | 3% | 12% | 29% | 0.2%（8 条） |
| 目标 | 46% | 12% | 5% | 8% | 29% | — |

- 难度：简单 21%、中等 43%、困难 36%（目标 26 / 45 / 29）。
- 难题型占比：多条写语句 62%、写多张表 46%、按归属用子查询 44%、归档 5%、改公共或他人数据 22%。

**要求的类型和算出的类型不一致：305 条（8%）。** 试点里是 0 条。

| 要求 \ 算出 | 1 | 2 | 3 | 4 | 5 | 6 | 一致率 |
|---|---|---|---|---|---|---|---|
| 1 本人 | 1732 | 59 | 7 | 117 | 0 | 0 | 90% |
| 2 本人+公共 | 0 | 291 | 0 | 64 | 0 | 0 | 82% |
| 3 只改公共 | 0 | 9 | 110 | 31 | 0 | 0 | 73% |
| 4 替他人 | 7 | 1 | 2 | 254 | 0 | 0 | 96% |
| 5 代办 | 0 | 0 | 0 | 0 | 1124 | 8 | 99% |

| 原因 | 条数 | 主要库 |
|---|---|---|
| 父表本身是人物表，数据块却标成"不属于任何人的公共数据"；模型去改，执行检查记为"别人的数据"。legislator 和 professional_basketball 的这类父表其实是说话人自己的另一张表（historical-terms 与 historical、draft 与 players），标签是错的；college_2、car_retails 改的是导师、销售代表，确实是另一个人 | 154 | legislator 80、college_2 28、professional_basketball 26、car_retails 11 |
| 要求只改自己的数据，模型顺手改了公共表 | 66 | books 22、book_publishing_company 10、beer_factory 7 |
| 插入新的人物行（新球员、新演员），记为"别人的数据" | 54 | professional_basketball 18、movie 9、books 7 |
| 其他 | 31 | books、WWE、movie |

这些候选都过了执行检查。配比按算出的标签统计即可，第一类的根因（锚点和建树）留给 v2。
