# 候选库清单（55 个）

由 `DySQL-Bench/scripts/render_candidates_md.py` 从 `docs/data_gen/candidate_dbs.csv`（筛选器输出）和 `docs/data_gen/db_notes.csv`（人工主题与备注）生成，不要手改。规则见 `docs/2026-09-24-data-gen-db-selection.md`。

锚点写作 `表[姓名或名称列]`。人物锚点里有姓名列的是带名字的人，方括号为空的是只有 ID 的人；实体锚点按 有名称列 > 下游表多 > 行数多 排序，只列前 3 个。

| 来源 | 候选数 | 有带名字的人物锚点 | 只有 ID 的人物锚点 | 只有实体锚点 |
|---|---|---|---|---|
| BIRD | 41 | 18 | 7 | 16 |
| Spider2-lite（SQLite） | 8 | 3 | 3 | 2 |
| Spider 1.0 | 6 | 2 | 0 | 4 |
| **合计** | **55** | **23** | **10** | **22** |

## BIRD（41 个）

| 数据库 | 划分 | 主题 | 表 | 列 | 总行数 | MB | FK 有效/声明/推断 | 人物锚点（姓名列） | 实体锚点（名称列） | 无效外键 | 长文本列 | 备注 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| address | train | 美国邮编、州、国会选区与区号 | 9 | 81 | 258,473 | 25.3 | 11/10/1 | congress[first_name,last_name] | state[name], CBSA[CBSA_name], alias[] 等 4 个 |  |  |  |
| airline | train | 美国航班准点与航空公司 | 3 | 32 | 709,518 | 117.0 | 3/3/0 |  | Airports[], Air Carriers[] |  |  | 实体锚点为执行者建议，待用户确认；确认锚点：Air Carriers |
| beer_factory | train | 根啤品牌、销售交易与评价 | 7 | 61 | 14,039 | 0.9 | 10/10/0 | customers[First,Last] | rootbeerbrand[BrandName,BreweryName], rootbeer[] |  | rootbeerbrand.Description |  |
| book_publishing_company | train | 图书出版公司（作者、出版社、门店、销售） | 11 | 64 | 254 | 0.2 | 10/10/0 | employee[fname,lname], authors[au_lname,au_fname] | publishers[pub_name], titles[title], stores[stor_name] 等 4 个 |  | pub_info.logo, pub_info.pr_info |  |
| books | train | 网上书店订单（图书、客户、配送） | 15 | 50 | 84,337 | 4.1 | 15/14/1 | author[author_name], customer[first_name,last_name] | address[street_name], publisher[publisher_name], country[country_name] 等 7 个 |  |  |  |
| car_retails | train | 模型车零售（办公室、员工、订单、付款） | 8 | 59 | 3,864 | 0.5 | 8/8/0 | customers[customerName,contactLastName,contactFirstName], employees[lastName,firstName] | products[productName], offices[], productlines[] 等 4 个 |  | productlines.textDescription | customers 是公司（带联系人姓名）；44/122 个联系人姓名与 Northwind/retail_world 相同 |
| chicago_crime | train | 芝加哥犯罪记录 | 7 | 52 | 268,824 | 63.6 | 6/6/0 |  | Community_Area[community_area_name], Ward[alderman_first_name,alderman_last_name], FBI_Code[title] 等 5 个 |  |  | FBI_Code、IUCR 是代码字典；实体锚点为执行者建议，待用户确认；确认锚点：District; Ward |
| citeseer | train | CiteSeer 论文引用网络 | 3 | 6 | 113,209 | 7.1 | 3/1/2 |  | paper[class_label] |  |  | 实体锚点为执行者建议，待用户确认；确认锚点：paper |
| college_completion | train | 美国大学毕业率 | 4 | 102 | 1,391,154 | 67.9 | 4/4/0 |  | institution_details[chronname] |  |  | 实体锚点为执行者建议，待用户确认；确认锚点：institution_details |
| computer_student | train | 计算机系课程、教师与学生 | 4 | 12 | 712 | 0.0 | 2/3/0 | person[] | course[] | advisedBy.p_id,p_id_dummy->person 0.0 |  |  |
| disney | train | 迪士尼电影、角色、票房 | 5 | 23 | 1,639 | 0.2 | 3/4/0 | voice-actors[] | characters[movie_title] | movies_total_gross.movie_title->characters 0.081 |  |  |
| food_inspection | train | 旧金山餐厅卫生检查 | 3 | 25 | 66,172 | 4.8 | 2/2/0 |  | businesses[name,owner_name] |  |  | 有 owner_name，可当作店主；实体锚点为执行者建议，待用户确认；确认锚点：businesses |
| food_inspection_2 | train | 芝加哥食品安全检查 | 5 | 40 | 701,342 | 206.9 | 6/6/0 | employee[first_name,last_name] | establishment[dba_name,aka_name], inspection[], inspection_point[] |  |  |  |
| genes | train | 基因分类与相互作用 | 3 | 15 | 6,118 | 1.5 | 3/3/0 |  | Classification[] |  |  | 每行代表一个基因（GeneID），锚点偏弱；实体锚点为执行者建议，待用户确认；确认锚点：Classification |
| legislator | train | 美国国会议员 | 5 | 107 | 27,826 | 3.3 | 3/3/0 | historical[first_name,last_name,middle_name,nickname_name,official_full_name,suffix_name], historical-terms[last,name] |  |  |  |  |
| mental_health_survey | train | 科技行业心理健康调查 | 3 | 8 | 234,750 | 17.4 | 2/2/0 |  | Question[], Survey[] |  |  | 无合适实体锚点：答卷人只有 UserID，没有对应的表；实体锚点为执行者建议，待用户确认 |
| menu | train | 纽约公共图书馆历史菜单 | 4 | 45 | 1,845,587 | 259.8 | 3/3/0 |  | Menu[name], Dish[name], MenuPage[] |  |  | 实体锚点为执行者建议，待用户确认；确认锚点：Menu; Dish |
| movie | train | 电影与演员角色 | 3 | 27 | 7,659 | 1.5 | 2/2/0 | actor[Name] | movie[Title] |  | actor.Biography |  |
| movielens | train | MovieLens 电影评分 | 7 | 24 | 1,249,411 | 81.8 | 6/6/0 | actors[], users[] | movies[], directors[] |  |  |  |
| movies_4 | train | TMDB 电影（演职员、公司、类型） | 17 | 53 | 393,358 | 12.5 | 17/17/0 | person[person_name] | movie[title], keyword[keyword_name], production_company[company_name] 等 7 个 |  | movie.overview |  |
| olympics | train | 奥运会运动员与奖牌 | 11 | 32 | 701,801 | 17.3 | 10/10/0 | person[full_name] | games[games_name], sport[sport_name], event[event_name] 等 6 个 |  |  |  |
| professional_basketball | train | NBA 球员、球队、奖项、选秀 | 9 | 157 | 44,822 | 6.4 | 10/9/1 | draft[firstName,lastName,suffixName], players[firstName,middleName,lastName,fullGivenName] |  |  |  |  |
| public_review_platform | train | Yelp 商户点评 | 15 | 75 | 990,846 | 62.3 | 16/16/0 | Users[] | Categories[category_name], Attributes[attribute_name], Business[] 等 6 个 |  |  |  |
| regional_sales | train | 区域销售订单 | 6 | 41 | 8,531 | 2.2 | 5/5/0 | Customers[Customer Names] | Store Locations[City Name], Products[Product Name], Regions[] 等 4 个 |  |  | Customers 是 50 家公司；人名在 Sales Team 表 |
| restaurant | train | 湾区餐厅信息 | 3 | 12 | 19,297 | 0.8 | 3/3/0 |  | generalinfo[label], geographic[] |  |  | geographic 是城市字典；实体锚点为执行者建议，待用户确认；确认锚点：generalinfo |
| retail_complains | train | 银行客户投诉与呼叫中心 | 6 | 58 | 33,289 | 24.0 | 5/6/0 | client[first,last] | district[], state[] | events.Complaint ID->callcenterlogs 0.107 | events.Consumer complaint narrative, reviews.Reviews |  |
| shakespeare | train | 莎士比亚作品、角色与段落 | 4 | 19 | 37,380 | 11.5 | 3/3/0 |  | works[Title,LongTitle], characters[CharName], chapters[] |  |  | 实体锚点为执行者建议，待用户确认；确认锚点：works; characters |
| shipping | train | 货运物流（卡车、司机、运单） | 5 | 32 | 1,684 | 0.1 | 4/4/0 | customer[cust_name], driver[first_name,last_name] | city[city_name], truck[] |  |  | 规模小：driver 11 人、customer 100 |
| shooting | train | 达拉斯警察枪击事件 | 3 | 20 | 812 | 0.2 | 2/2/0 |  | incidents[] |  |  | 实体锚点为执行者建议，待用户确认；确认锚点：incidents |
| social_media | train | 推特推文与用户 | 3 | 21 | 205,372 | 65.9 | 2/2/0 | user[] | location[] |  |  |  |
| student_loan | train | 学生贷款与个人状况 | 10 | 15 | 5,288 | 0.3 | 9/9/0 | person[name] |  |  |  | 名字是 student1…student1000（编号） |
| synthea | train | Synthea 合成病人医疗记录 | 11 | 85 | 170,810 | 36.8 | 16/18/0 | patients[first,last] | encounters[] | conditions.DESCRIPTION->all_prevalences 0.202, claims.ENCOUNTER->encounters 0.0 |  |  |
| university | train | 世界大学排名 | 6 | 20 | 32,042 | 0.6 | 5/5/0 |  | country[country_name], university[university_name], ranking_criteria[criteria_name] |  |  | country、ranking_criteria 是字典；实体锚点为执行者建议，待用户确认；确认锚点：university |
| video_games | train | 电子游戏、平台、发行商与区域销量 | 8 | 21 | 105,319 | 2.4 | 7/7/0 |  | game[game_name], publisher[publisher_name], platform[platform_name] 等 6 个 |  |  | platform、genre 是字典；实体锚点为执行者建议，待用户确认；确认锚点：game; publisher |
| california_schools | dev | 加州学校、SAT 成绩与免费餐 | 3 | 89 | 29,941 | 10.6 | 2/2/0 |  | schools[EdOpsName,EILName] |  |  | 实体锚点为执行者建议，待用户确认；确认锚点：schools |
| card_games | dev | 万智牌卡牌与规则 | 6 | 115 | 803,445 | 249.7 | 5/4/1 |  | cards[asciiName,faceName,flavorName,name], sets[mcmName,name], legalities[] |  | sets.booster | 实体锚点为执行者建议，待用户确认；确认锚点：cards; sets |
| debit_card_specializing | dev | 捷克加油站借记卡交易 | 5 | 21 | 423,050 | 33.0 | 5/2/3 | customers[] | gasstations[], products[] |  |  |  |
| financial | dev | 捷克银行账户、贷款与交易 | 8 | 55 | 1,079,680 | 68.0 | 8/8/0 | client[] | district[], account[], disp[] |  |  |  |
| student_club | dev | 学生社团活动、预算与支出 | 8 | 48 | 42,511 | 2.5 | 8/8/0 | member[first_name,last_name] | major[major_name], event[event_name], zip_code[] 等 4 个 |  |  | 规模小：member 33 人 |
| superhero | dev | 超级英雄属性与超能力 | 10 | 31 | 10,614 | 0.2 | 11/11/0 | superhero[superhero_name,full_name] | publisher[publisher_name], superpower[power_name], attribute[attribute_name] 等 5 个 |  |  | 虚构角色；full_name 有 247/750 为空或 '-' |
| toxicology | dev | 分子毒理（原子、化学键、分子） | 4 | 11 | 49,813 | 2.6 | 5/5/0 |  | molecule[label], bond[], atom[] |  |  | 实体锚点为执行者建议，待用户确认；确认锚点：molecule |

## Spider2-lite（SQLite）（8 个）

| 数据库 | 划分 | 主题 | 表 | 列 | 总行数 | MB | FK 有效/声明/推断 | 人物锚点（姓名列） | 实体锚点（名称列） | 无效外键 | 长文本列 | 备注 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| AdventureWorks | test | AdventureWorks 自行车制造企业销售 | 13 | 120 | 168,686 | 19.3 | 14/0/14 | salesperson[] | salesterritory[name], product[NAME], productsubcategory[name] 等 6 个 |  | productreview.comments | NULL 存成空串；只有 salesperson 一张无名字的人物表 |
| Airlines | test | 俄罗斯航空订票（航班、座位、机票、登机牌） | 8 | 35 | 2,289,506 | 104.5 | 4/0/4 |  | aircrafts_data[], flights[] |  |  | tickets 有 passenger_name，但 ticket_no 不像 ID 列，没连上；实体锚点为执行者建议，待用户确认；确认锚点：flights |
| Brazilian_E_Commerce | test | 巴西 Olist 电商订单 | 10 | 62 | 1,583,873 | 109.3 | 5/0/5 | olist_customers[], olist_sellers[] | olist_orders[] |  |  | customer_id 每单一个，真正的人是 customer_unique_id（32 位哈希） |
| IPL | test | IPL 板球（比赛、逐球数据、得分、出局） | 8 | 52 | 293,471 | 12.1 | 11/0/11 | player[player_name,country_name] | team[name], match[] |  |  |  |
| WWE | test | WWE 摔跤赛事、选手与冠军腰带 | 9 | 33 | 578,890 | 167.9 | 8/0/8 | Wrestlers[name] | Events[name], Locations[name], Promotions[name] 等 7 个 |  | Tables.html, Cards.info_html, Cards.match_html |  |
| delivery_center | test | 巴西外卖配送中心（订单、骑手、门店） | 7 | 59 | 1,154,523 | 122.5 | 6/0/6 | drivers[] | stores[store_name], channels[channel_name], hubs[hub_name] 等 4 个 |  |  |  |
| imdb_movies | test | IMDB 电影评分与导演、演员 | 7 | 38 | 75,898 | 3.0 | 5/0/5 |  | names[name], ratings[] |  |  | names 实际是人物表（演员、导演）；ratings 每行代表一部电影；实体锚点为执行者建议，待用户确认；确认锚点：names; ratings |
| school_scheduling | test | 学校排课（教师、课程、教室、学生） | 15 | 75 | 811 | 0.2 | 18/17/1 | Staff[StfFirstName,StfLastname], Students[StudFirstName,StudLastName], Faculty[] | Subjects[SubjectName], Departments[DeptName], Buildings[BuildingName] 等 7 个 |  |  | 规模小：全库 811 行 |

## Spider 1.0（6 个）

| 数据库 | 划分 | 主题 | 表 | 列 | 总行数 | MB | FK 有效/声明/推断 | 人物锚点（姓名列） | 实体锚点（名称列） | 无效外键 | 长文本列 | 备注 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| bike_1 | train | 旧金山共享单车（站点、骑行、天气） | 4 | 46 | 22,181 | 1.7 | 3/1/2 |  | station[name] |  |  | 实体锚点为执行者建议，待用户确认；确认锚点：station |
| college_2 | train | 大学教务（院系、课程、教师、选课、先修课） | 11 | 46 | 34,620 | 2.0 | 13/13/0 | student[name,dept_name], instructor[name,dept_name] | department[dept_name], course[title,dept_name] |  |  | 学生名是单个姓氏，有重名 |
| csu_1 | train | 加州州立大学（校区、学费、学位、招生） | 6 | 23 | 1,943 | 0.1 | 5/5/0 |  | Campuses[] |  |  | 实体锚点为执行者建议，待用户确认；确认锚点：Campuses |
| flight_4 | train | 航线、机场与航空公司 | 3 | 24 | 80,586 | 3.0 | 3/3/0 |  | airports[name], airlines[name] |  |  | 实体锚点为执行者建议，待用户确认；确认锚点：airlines; airports |
| hr_1 | train | 人力资源（员工、部门、职位、地区） | 7 | 35 | 216 | 0.1 | 8/7/1 | employees[FIRST_NAME,LAST_NAME] | departments[DEPARTMENT_NAME], countries[COUNTRY_NAME], jobs[JOB_TITLE] 等 4 个 |  |  |  |
| wine_1 | train | 葡萄酒、葡萄与产区 | 3 | 20 | 577 | 0.1 | 2/2/0 |  | appellations[], grapes[] |  |  | 无合适实体锚点：只有产区、葡萄品种这类字典表；实体锚点为执行者建议，待用户确认 |
