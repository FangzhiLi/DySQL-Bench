# Qwen3-32B-AWQ (thinking on) 全量跑 —— 572 个失败任务的归因分析

数据：`DySQL-Bench/results/full_qwen3_32b_think_on_c12`，13 个库，1062 个任务，pass^1 = 46.1%（490 过 / 572 败）。
工具：`DySQL-Bench/scripts/classify_failures.py`（对每个失败样本，用 gold SQL、agent 实际执行的 sql_log、reward 的 row_diff 和对话轨迹自动归因；再人工抽样 40+ 条核对）。

判分方式回顾：跑完后对整库所有表做 hash，和 gold SQL 跑出来的库做 hash 对比，任何一张表有任何一行不同即 0 分。所以"多改一张表"和"少改一张表"同样致命。

## 1. 主因分布（每个失败任务只归一个主因）

| 主因 | 数量 | 占失败 | 说明 |
|---|---|---|---|
| **B. 一条消息里写了多个 SQL 块，第 2 个起的写操作被丢弃** | **223** | **39.0%** | 环境只执行每轮第一个 ```sql 块。模型把 SELECT+UPDATE 或 UPDATE+DELETE 塞进同一条消息，并自己编造 `<result>1 row affected</result>`，然后向用户宣布完成。 |
| F. 表对了、内容错 | 136 | 23.8% | 见 §3 |
| C. 一次写操作都没执行 | 77 | 13.5% | 见 §4 |
| D. 只完成了一部分写操作（漏表） | 64 | 11.2% | 见 §5 |
| A. 异常终止 | 26 | 4.5% | max_steps 12，context_overflow 8，length_no_content 5，malformed_sql_block 1 |
| E. 多改了 gold 没碰的表 | 24 | 4.2% | "好心"更新派生表（Bowlers 总分、rental 归还时间、Ingredient 新增行、Player_Attributes 置空等） |
| G. gold 本身是 no-op（gold 写操作影响 0 行） | 22 | 3.8% | 任务生成缺陷，见 [[dysql-noop-gold-tasks]] |

按长度：long 任务里 B 占 47%（150/319），short 里 F 占 34%（87/253）。多步任务主要死于"多块 SQL 被丢"，单步任务主要死于值/条件写错。

按库（fail/total，后面是 A~G 数量）：

| env | fail/total | A | B | C | D | E | F | G |
|---|---|---|---|---|---|---|---|---|
| retail | 138/205 | 6 | 63 | 18 | 16 | 2 | 31 | 2 |
| eu_soccer | 87/215 | 14 | 13 | 18 | 3 | 2 | 23 | 14 |
| bowling | 66/111 | 0 | 31 | 3 | 19 | 4 | 9 | 0 |
| pagila | 64/105 | 2 | 28 | 11 | 9 | 1 | 10 | 3 |
| entertainment | 58/131 | 1 | 35 | 3 | 6 | 1 | 11 | 1 |
| cookbook | 37/51 | 1 | 8 | 7 | 1 | 7 | 13 | 0 |
| chinook | 27/44 | 0 | 17 | 1 | 2 | 0 | 7 | 0 |
| human_resources | 23/40 | 0 | 9 | 4 | 2 | 1 | 7 | 0 |
| law_episode | 22/53 | 1 | 1 | 7 | 2 | 3 | 8 | 0 |
| ice_hockey | 17/28 | 0 | 5 | 1 | 4 | 3 | 2 | 2 |
| music | 14/21 | 0 | 7 | 0 | 0 | 0 | 7 | 0 |
| car | 12/27 | 1 | 3 | 4 | 0 | 0 | 4 | 0 |
| retail_world | 7/31 | 0 | 3 | 0 | 0 | 0 | 4 | 0 |

eu_soccer 特殊：Match 表 22 列 home/away_player_N 的置空任务，gold 逐列写 22 条 UPDATE，模型用一条 CASE WHEN 合并。合并本身没错，但 gold 常常影响 0 行（G 类 14 个）加上 context_overflow（A 类 14 个）让它成为异常终止最多的库。

## 2. 关键相关指标（失败 vs 通过）

| 标志 | 失败组 | 通过组 |
|---|---|---|
| 消息里含伪造 `<result>` | 78.3% | 52.7% |
| 有写操作被扔进第 2+ 个 SQL 块 | 42.0% | 5.5% |
| 写操作里出现对话中从未出现过的数字字面量（幻觉 ID） | 19.1% | 5.5% |
| 转人工 | 14.9% | 7.8% |
| 多改了表 | 10.1% | 0.2% |
| 写操作 SQL 报错 | 6.6% | 1.6% |

- 有多 SQL 块的 361 个 run，通过率 20.2%；没有的 701 个 run，通过率 59.5%。
- 有伪造 `<result>` 的 706 个 run（66.5%），通过率 36.5%；没有的通过率 65.2%。
- 排除 99 个 gold no-op 任务后 pass^1 = 45.6%，和整体差别不大。

## 3. F 类（136）：表对了、内容错

| 子类 | 数量 | 典型例子 |
|---|---|---|
| 值/条件用了幻觉 ID（wrong_values / wrong_where） | 47 | 模型先在脑内编造了一次 SELECT 结果（`prod_id=7890`、`ssn='123-45-6789'`、`promo_id=105`），然后拿编造的 ID 去 UPDATE，真实执行后 0 行或改错行。 |
| 数值不同 | 33 | 漏列（INSERT Bowler_Scores 没写 HandiCapScore → 0）、看错行（AgentID 9 vs 3）、算错。 |
| 字符串不同 | 23 | 用户说改 A 字段，模型改了 B 字段或写了不同文本（chinook 地址/邮箱）。 |
| WHERE 写错影响 0 行（非幻觉） | 13 | `WHERE id = 41318` 应为 `player_api_id`；`UPDATE Bowler_Scores_Archive` 应改 `Bowler_Scores`；用了 Match_Games_Archive 而不是 Tourney_Matches。 |
| 日期格式 | 7 | `'1990-12-10'` vs gold `'1990-12-10 00:00:00'`（eu_soccer Player.birthday，text 列，hash 不同）。 |
| 值规范化 | 5 | `'cups'` vs `'cup'`、`'No'/'N'` vs `'no'`（cookbook Quantity）。 |
| NULL vs 值、日期不同、多列不同、多/少行 | 其余 | |

日期格式和值规范化这 12 个属于 benchmark 过严（语义正确但 hash 不同），其余是模型真错。

## 4. C 类（77）：一次写操作都没执行

| 子类 | 数量 | 说明 |
|---|---|---|
| 转人工 | 37 | 身份/记录查询没命中（地址写法差异、找不到"重复付款"），或模型对退款/删除过度谨慎，直接转人工；用户模拟器随即 STOP。 |
| 口头宣布完成、从未出 SQL | 26 | 模型直接输出 `<result>{"rows_affected": 2}</result>` 之类的假结果并总结完成；有几例把 SQL 写在 `<result>` 标签里面。 |
| SQL 写在了非法容器里 | 12 | 用了 `<code>…</code>`、`<action>…</action>` 或纯文本，环境不识别，模型再伪造 `<result>`。 |
| 用户在确认环节就 STOP | 2 | |

## 5. D 类（64）：只完成了部分写操作

| 子类 | 数量 | 说明 |
|---|---|---|
| 漏掉子请求或改错表 | 48 | 典型：说"已归档"但根本没 INSERT 进 Archive 表；用户说改 invoices 的账单地址，模型改了 customers；说"discontinue 商品"模型去 supplementary_demographics 加了条备注。 |
| 幻觉 ID 导致某张表没改到 | 10 | |
| 某条写操作报错后没重试 | 6 | 例如 INSERT 里写 `[prod_id]` 占位符报错，后续用编造的值重试。 |

## 6. 结论

1. **单一最大杀手是"一条消息多个 SQL 块 + 自己伪造 `<result>`"**，独占 39% 的失败，long 任务中占 47%。这是模型不遵守系统提示"一次只能一个 SQL 调用"的格式问题，不是 SQL 能力问题。如果这类全部修好，pass^1 上限可到 67%。这也是 GRPO 最容易拿到的奖励：对"消息里出现第 2 个 SQL 块或出现伪造 `<result>`"直接给负奖励/截断，或者在环境里改为执行所有块。
2. **第二大问题是幻觉**：66.5% 的 run 出现伪造 `<result>`。伪造不仅让写操作被跳过（B、C 类），还污染后续推理（F/D 类的 57 个"幻觉 ID"）。模型思维链先"想象"查询结果，然后把想象当事实。
3. **真正的 SQL/语义错误**（改错表、漏列、WHERE 列名错、多改派生表）合计约 130 个，占失败 23%，是模型能力层面需要提升的部分。
4. **benchmark 侧噪声**约 34 个（gold no-op 22 个 + 日期格式/值规范化 12 个），占失败 6%，对整体 pass^1 影响约 3 个百分点。
5. **过度谨慎转人工** 37 个，多发生在 retail（地址匹配失败）和 pagila（退款）。

## 7. 对下一步的建议

- 训练前先做一个廉价实验：把 `message_to_action` 改成执行消息里所有 SQL 块（或提示词里强调只写一个块并给格式样例），重跑 retail + bowling + entertainment，看 B 类是否消失。这能把"格式问题"和"能力问题"分开。
- GRPO reward shaping：伪造 `<result>`、多 SQL 块、非法容器（`<code>`/`<action>`）三项作为可直接检测的负信号。
- 任务生成侧：过滤 gold no-op；eu_soccer 的日期比较用 `date()` 规范化或把 birthday 存为统一格式。
