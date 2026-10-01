# 外键命中率标定（2026-09-25）

命中率 = 子表外键列的非空值中，能在被引用表里找到的比例。子表没有任何非空值时记为"未验证"：外键保留，但单独列出。

## DySQL 13 库（声明的外键，共 128 条）

| 命中率 | 外键 |
|---|---|
| 未验证 | BowlingLeague `Bowler_Scores_Archive.(MatchID, GameNumber) → Match_Games_Archive`（空表） |
| 未验证 | BowlingLeague `Tourney_Matches_Archive.TourneyID → Tournaments_Archive`（空表） |
| 未验证 | Pagila `film.original_language_id → language`（全为 NULL） |
| 0.314 | complex_oracle `costs.prod_id → products` |
| 0.332 | complex_oracle `sales.prod_id → products` |
| 0.955 | law_episode `Award.person_id → Person` |
| 1.000 | 其余 122 条 |

complex_oracle 的 products 表只保留了 72 个产品中的 24 个，但 DySQL 仍在上面出了 25 个 UPDATE products 任务。数据不全的外键照样能出题：出题只会用到能连上的那部分行。

## 候选库里低于阈值的外键（2026-09-25 预跑）

| 命中率 | 外键 |
|---|---|
| 0.000 | synthea `claims.ENCOUNTER → encounters` |
| 0.081 | disney `movies_total_gross.movie_title → characters` |
| 0.091 | thrombosis_prediction `Examination.ID → Patient` |
| 0.107 | retail_complains `events."Complaint ID" → callcenterlogs` |
| 0.202 | synthea `conditions.DESCRIPTION → all_prevalences` |

## 阈值

`fk_min_hit = 0.3`：
- 取 0.3 能保住 DySQL 所有有数据的声明外键，其中最低的是 0.314。
- 同时能排除上表中命中率在 0–0.2 的外键，这类外键是错的，或者几乎连不上。

这个阈值要排除的是"错的外键"，不是"数据不全的外键"。

## 按取值推断的外键（执行时补充）

标定时发现，按取值推断会产生巧合外键：一张行数多、值很密的整数键表，会"包含"任何一小组小整数 ID。在 DySQL 的 13 个库里，旧规则推断出 9 条，其中 8 条是巧合：

| 子表不同值 / 被引用表行数 | 推断出的外键 | 判断 |
|---|---|---|
| 22 / 55,500 | complex_oracle `promotions.promo_subcategory_id → customers.cust_id` | 巧合 |
| 60 / 55,500 | complex_oracle `times.calendar_month_id → customers.cust_id`（另有同类 4 条） | 巧合 |
| 285 / 183,978 | EU_soccer `Team.team_fifa_api_id → Player_Attributes.id` | 巧合 |
| 11,060 / 183,978 | EU_soccer `Player.player_api_id / player_fifa_api_id → Player_Attributes.id` | 巧合（全表命中率只有 0.69 / 0.49） |
| 56 / 57 | BowlingLeague `Match_Games.MatchID → Tourney_Matches.MatchID` | 真外键 |

所以按取值推断额外要求：子表的不同值至少覆盖被引用表键的 10%（`min_coverage=0.1`）。真正以角色命名的外键（`winner_id → Wrestlers`）会覆盖被引用键的大部分。加上这条后，DySQL 13 个库只剩最后一条真外键，验收测试仍然 13/13 通过。

代价：如果某个真外键的子表只覆盖被引用键的不到 10%，这条规则会漏掉它；这种情况用 `taskgen/common/data/fk_extra.json` 人工补。
