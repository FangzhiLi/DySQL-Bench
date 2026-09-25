# 候选库变化（旧 34 → 新 55）

旧清单：commit 4bdf1cd 生成的 34 个候选（规则：必须有人物表）。新清单：`docs/data_gen/candidate_dbs.csv`（2026-09-25 重跑，用时 3 分 37 秒），逐库锚点记录见 `docs/data_gen/candidate_anchors.json`。

新清单按来源：BIRD 41、Spider2-lite 8、Spider 1.0 6、SynSQL 0。按锚点类型：有带名字的人物锚点 23 个，只有 ID 的人物锚点 10 个，只有实体锚点 22 个。

规则变化：
- 人物表硬条件改为"锚点 + 范围内有更新目标"。
- 外键按命中率验证，阈值 0.3；没有值可查的外键记为未验证并保留。
- 推断修正：guid 列、通用 id、复合主键成员、1:1 扩展表、按取值推断。按取值推断额外要求子表的不同值覆盖被引用键的 10% 以上（执行时补充，依据见 `docs/data_gen/fk_calibration.md`）。
- 新增复合键识别。
- activity_1 和 college_3 按名字排除（用户 2026-09-25 决定）：它们的 Student 表和 CoSQL/SParC 评测库 pets_1 同模板，包含度 0.57。

## 退出（3 个）

| 来源 | 库 | 原因 |
|---|---|---|
| BIRD | superstore | no_anchor：people 表按地区重复（主键是 Customer ID + Region），没有单列键，当不了锚点 |
| BIRD | thrombosis_prediction | fks：Examination.ID → Patient 命中率 0.091，低于 0.3，只剩 1 条可用外键 |
| Spider 1.0 | college_3 | leak：按用户决定排除（见上） |

## 进入（24 个）

| 来源 | 库 | 锚点类型 | 人物锚点 | 实体锚点（前 3） |
|---|---|---|---|---|
| BIRD | airline | 只有实体 | — | Airports[], Air Carriers[] |
| BIRD | book_publishing_company | 有名字的人物 | employee[fname,lname], authors[au_lname,au_fname] | publishers[pub_name], titles[title], stores[stor_name] 等 4 个 |
| BIRD | california_schools | 只有实体 | — | schools[EdOpsName,EILName] |
| BIRD | card_games | 只有实体 | — | cards[asciiName,faceName,flavorName,name], sets[mcmName,name], legalities[] |
| BIRD | chicago_crime | 只有实体 | — | Community_Area[community_area_name], Ward[alderman_first_name,alderman_last_name], FBI_Code[title] 等 5 个 |
| BIRD | citeseer | 只有实体 | — | paper[class_label] |
| BIRD | college_completion | 只有实体 | — | institution_details[chronname] |
| BIRD | food_inspection | 只有实体 | — | businesses[name,owner_name] |
| BIRD | genes | 只有实体 | — | Classification[] |
| BIRD | mental_health_survey | 只有实体 | — | Question[], Survey[] |
| BIRD | menu | 只有实体 | — | Menu[name], Dish[name], MenuPage[] |
| BIRD | movies_4 | 有名字的人物 | person[person_name] | movie[title], keyword[keyword_name], production_company[company_name] 等 7 个 |
| BIRD | restaurant | 只有实体 | — | generalinfo[label], geographic[] |
| BIRD | shakespeare | 只有实体 | — | works[Title,LongTitle], characters[CharName], chapters[] |
| BIRD | shooting | 只有实体 | — | incidents[] |
| BIRD | toxicology | 只有实体 | — | molecule[label], bond[], atom[] |
| BIRD | university | 只有实体 | — | country[country_name], university[university_name], ranking_criteria[criteria_name] |
| BIRD | video_games | 只有实体 | — | game[game_name], publisher[publisher_name], platform[platform_name] 等 6 个 |
| Spider2-lite | Airlines | 只有实体 | — | aircrafts_data[], flights[] |
| Spider2-lite | delivery_center | 只有 ID 的人物 | drivers[] | stores[store_name], channels[channel_name], hubs[hub_name] 等 4 个 |
| Spider2-lite | imdb_movies | 只有实体 | — | names[name], ratings[] |
| Spider 1.0 | bike_1 | 只有实体 | — | station[name] |
| Spider 1.0 | flight_4 | 只有实体 | — | airports[name], airlines[name] |
| Spider 1.0 | wine_1 | 只有实体 | — | appellations[], grapes[] |

## 预期核对

- **退出项与预跑一致：** superstore、thrombosis_prediction、college_3。college_3 这次是按名字排除的，预跑时它是作为 activity_1 的重复库被去掉的。
- **新增项：** 与计划列出的预期一致，另外多一个 **book_publishing_company**（BIRD，有带名字的人物锚点 employee、authors）。预跑结果里本来就有它，是计划漏列了，不是规则问题。
- **仍然退出：** Db-IMDB（fragmented）。M_Cast.PID 带前导空格，连不上 Person 表，是数据本身的问题。
- **总数与预期一致：** 55 个；按锚点类型 named 23、id_only 10、entity 22。按取值推断加上覆盖率条件后，候选清单没有变化。
- **接下来要做的：** 只有实体锚点的 22 个库，要人工确认哪些实体锚点有意义（Task 11 的 `entity_anchors_ok`）。
