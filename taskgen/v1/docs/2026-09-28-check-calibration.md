# 执行检查在 DySQL 1062 条任务上的校准

口径：去掉第 7 类（标准答案不改库）。'去掉部分 no-op' 再去掉只因 noop_write 失败的任务：它们的某条 gold 写语句命中 0 行，正是规则要拦的缺陷。

| env | 非第7类任务 | 通过 | 通过率 | 去掉部分 no-op 后通过率 | 主要失败原因 | 类型一致 | 难度 简单/中等/困难 |
|---|---|---|---|---|---|---|---|
| bowling | 108 | 104 | 96% | 100% | noop_write 5 | 100% | 12/22/74 |
| car | 27 | 26 | 96% | 96% | literal_missing 1 | 100% | 6/21/0 |
| chinook | 44 | 44 | 100% | 100% |  | 86% | 7/25/12 |
| cookbook | 49 | 40 | 82% | 91% | noop_write 9, literal_missing 9 | 100% | 6/37/6 |
| entertainment | 130 | 125 | 96% | 98% | noop_write 3, literal_missing 1, out_of_scope 1 | 100% | 27/76/27 |
| eu_soccer | 189 | 154 | 81% | 94% | noop_write 307, literal_missing 7, bulk 5 | 89% | 88/93/8 |
| human_resources | 37 | 34 | 92% | 97% | literal_missing 2, noop_write 2 | 100% | 10/19/8 |
| ice_hockey | 28 | 26 | 93% | 100% | noop_write 2 | 100% | 6/15/7 |
| law_episode | 52 | 50 | 96% | 100% | noop_write 2 | 100% | 23/27/2 |
| music | 21 | 20 | 95% | 95% | literal_missing 3 | 86% | 0/16/5 |
| pagila | 99 | 96 | 97% | 98% | literal_missing 3, noop_write 1 | 99% | 23/56/20 |
| retail | 198 | 159 | 80% | 84% | literal_missing 43, noop_write 10, bulk 6 | 49% | 36/37/125 |
| retail_world | 30 | 30 | 100% | 100% |  | 100% | 5/22/3 |
| **合计** | 1012 | 908 | **90%** | **95%** | noop_write 341, literal_missing 69, bulk 11, out_of_scope 2 | 87% | 249/466/297 |

**2026-10-01 重算：** 难度列（简单/中等/困难）用当前代码重跑。9-29 修正了'归档'标签的误报（`1e9fac2`），8 条从困难变为中等；通过率和拒绝原因不变。
**规则改动（2026-09-28，都有测试）：**
- scope 从"说话人锚点的 scope"放宽为"库内所有锚点 scope 的并集"。选库验收的原话是每条 gold 写语句落在*某个*锚点的 scope 内；chinook、music 的客户会改只有别的锚点能到的全局歌单（playlist_track）。
- 字面量检查接受 0、1、true、false（数量、标志位、默认值），strftime/LIKE 模式（含 %），把"June 19, 2024 / 19 June 2024"归一成 ISO 日期，datetime 只要日期部分出现，"one"–"twelve"对应数字。
- 校准输入支持一个任务有多个说话人行（同名客户、艺人和成员），类型一致率从 79% 升到 87%。

**结论：** 非第 7 类通过率 90%，去掉部分 no-op 后 95%，达到设计 §7 的 90%。剩下的失败主要是 retail（literal_missing 43：gold SQL 用了 instruction 没给的值，例如直接写 cust_id 或新地址的邮编）和 eu_soccer 的部分 no-op，这些是 DySQL 任务本身的缺陷，规则拦下它们是对的。retail 的类型一致率只有 49%，原因是 costs 行追不到客户、同名客户多，不影响生成任务的检查。
