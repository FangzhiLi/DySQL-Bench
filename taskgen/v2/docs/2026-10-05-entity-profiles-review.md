# 实体库 profile 审阅（关卡 1）

2026-10-05。对应实施计划 `2026-10-05-entity-tasks-plan.md` 的 Task 6。

16 份 profile 由 Claude 读 schema 和数据起草，用户 2026-10-05 确认：
- 每条数据怪异点都用 SQL 核对过；
- 都通过了 `profile check`；
- 用户的唯一改动：california_schools 的 frpm 和 satscores 从属性表改成事件表，让建树优先挑有这两张表数据的学校。

## 请你看的

逐库看下表下面每一节的这几项：
- 根：一道题围绕哪张表的一行；
- 事件：根下面哪些子表可以改；
- 公共表：只读的共享数据；
- 说话人角色：抽样用，每库 4–6 个；
- 可新建的查找行：约 10% 的题会先在公共表里新建一行，再挂到实体上；
- 数据怪异点：会写进出题和校验的 prompt。

每库一棵样例树在 `results/entity_profile_trees.md`，里面有真实数据行，不进 git。

请回复三件事：
1. 哪些库不要，哪些要改；
2. 其余是否确认；
3. 不用的 6 个库里是否要加回哪个。

## 用哪些库，配额多少

**建议用 16 个库，按 N = 16：** 每库 Q = ⌈400/16⌉ = 25 个候选，最终每库封顶 CAP = ⌈300/16⌉ = 19 题。试跑用 menu、video_games、university。

**建议不用的 6 个库：**
- citeseer、genes、toxicology：科研数据，没有自然的"来改数据的人"；
- mental_health_survey：答卷属于匿名答题人，替别人改答卷不自然，之前也没找到锚点；
- shooting：涉及真实警察和当事人的枪击事件，不适合编改数据的请求；
- wine_1：之前就没有合适的锚点，wine 表没有主键。

## 起草时看到的风险（供你决定去留）

| 库 | 风险 |
|---|---|
| bird:airline | 只有 26 个承运人有航班，每个约 1.7 万条；航班表无主键，要用日期、承运人、航班号、起飞机场四列定位（已核实这四列唯一）。题目可能偏机械 |
| spider2:Airlines | 没有声明的外键，边靠命中率；表大（ticket_flights 100 万行），检查每条要复制 110 MB 的库 |
| bird:chicago_crime | 只有 22 个警区，最多 22 棵树，题数可能不到配额 |
| spider1:csu_1 | 只有 23 个校区，同上；复合主键多，会用到"已用的键值" |
| bird:california_schools | 没有事件表，只有两张一对一的属性表；约一半学校没有属性行，题目只能改学校这一行 |
| bird:card_games | 卡名大量重名（重印），按名字的子查询基本出不来；cards 有 74 列 |
| bird:college_completion | 缺失值是文本 'NULL'；毕业队列表无主键，一行要五列定位 |

---
## bird:airline　已确认　校验通过

> US domestic flight records for August 2018. Each air carrier (Air Carriers) operates flights (Airlines, one row per flight) between airports (Airports). A task is about one carrier and its flights; airports are a shared list.

| 项 | 内容 |
|---|---|
| 根 | Air Carriers（air carrier） |
| 类型 | 实体（根是物，不是人） |
| 说话人角色 | an operations analyst at this carrier correcting its flight records；a data steward for the carrier's on-time performance reports；a dispatcher who handled these flights；an aviation statistics clerk |
| 可新建的查找行 | — |
| 人物表 | Air Carriers（Code；Description） |
| 事件 | Airlines（flights）：Airlines.OP_CARRIER_AIRLINE_ID -> Air Carriers.Code |
| 属性表 | — |
| 公共表 | Airports |
| 排除 | — |
| 不出 INSERT | — |
| 数据怪异点 | FL_DATE is written 'YYYY/M/D' without leading zeros ('2018/8/1').；Times (CRS_DEP_TIME, DEP_TIME, ARR_TIME and the like) are integers in HHMM form without a colon (1649 means 16:49).；Airlines has no key: a flight is one (FL_DATE, OP_CARRIER_AIRLINE_ID, OP_CARRIER_FL_NUM, ORIGIN).；Air Carriers.Description ends with the carrier's code after a colon ('Mackey International Inc.: MAC').；CANCELLED is 0 or 1; the delay columns are minutes and NULL when not reported. |

挂在根和事件下面的父行（← 后面是外键列）：

- Airlines（flights）
  - Airports ← Airlines.ORIGIN
  - Airports ← Airlines.DEST

主键：可省 ID：Air Carriers；非整数或复合主键：Airports(Code)；无主键：Airlines

Claude 的改动：
- Claude: drafted from the schema and data on 2026-10-05; every quirk checked with SQL

起草：claude，1 轮

## bird:california_schools　已确认　校验通过

> California public schools. Each school (schools) has its directory details, and may have one row of free and reduced-price meal figures (frpm) and one row of SAT results (satscores), each kept as an event of the school. A task is about one school.

| 项 | 内容 |
|---|---|
| 根 | schools（school） |
| 类型 | 实体（根是物，不是人） |
| 说话人角色 | the office manager at this school；a district data coordinator responsible for this school；a county office of education analyst；a state reporting specialist correcting this school's records |
| 可新建的查找行 | — |
| 人物表 | schools（CDSCode；School） |
| 事件 | frpm（free and reduced-price meal figures）：frpm.CDSCode -> schools.CDSCode；satscores（SAT results）：satscores.cds -> schools.CDSCode |
| 属性表 | — |
| 公共表 | — |
| 排除 | — |
| 不出 INSERT | — |
| 数据怪异点 | CDSCode is a 14-digit text code with leading zeros ('01100170109835'); satscores.cds holds the same code.；Many frpm column names contain spaces and punctuation ('Percent (%) Eligible Free (K-12)'); quote them in SQL.；The frpm 'Percent (%)' columns are fractions between 0 and 1, not percentages.；schools.School is NULL for 1,369 rows that are district or county offices, not schools.；satscores.rtype is 'S' for a school and 'D' for a district; AvgScrRead, AvgScrMath and AvgScrWrite are average SAT section scores. |

主键：非整数或复合主键：frpm(CDSCode), satscores(cds), schools(CDSCode)

Claude 的改动：
- Claude: drafted from the schema and data on 2026-10-05; every quirk checked with SQL
- Claude: frpm and satscores moved from attributes to events (user, 2026-10-05), so trees pick schools that have them

起草：claude，1 轮

## bird:card_games　已确认　校验通过

> Magic: The Gathering cards. Each card row is one printing of a card in a set, with its rulings, its legality in each play format and its foreign-language versions. A task is about one card printing; sets and their translations are shared lists.

| 项 | 内容 |
|---|---|
| 根 | cards（card） |
| 类型 | 实体（根是物，不是人） |
| 说话人角色 | a card database maintainer correcting this printing；a collector who catalogues this card；a tournament judge updating this card's rulings；a translator checking this card's foreign-language data |
| 可新建的查找行 | — |
| 人物表 | cards（id；name） |
| 事件 | rulings（rulings）：rulings.uuid -> cards.uuid；legalities（format legalities）：legalities.uuid -> cards.uuid；foreign_data（foreign-language printings）：foreign_data.uuid -> cards.uuid |
| 属性表 | — |
| 公共表 | sets, set_translations |
| 排除 | — |
| 不出 INSERT | — |
| 数据怪异点 | A card is one printing: the same name appears on several cards (56,822 cards have 21,738 names), so a card is named by its id.；rulings, legalities and foreign_data link to a card by uuid, not by id.；legalities.status is 'Legal', 'Banned' or 'Restricted'; format is a play format such as 'commander' or 'legacy'.；Many cards columns are 0/1 flags (isPromo, hasFoil, isReprint).；cards.setCode holds the set's short code (sets.code, such as '10E'). |

挂在根和事件下面的父行（← 后面是外键列）：

- 根 cards
  - sets ← cards.setCode

主键：可省 ID：cards, foreign_data, legalities, rulings, set_translations, sets

Claude 的改动：
- Claude: drafted from the schema and data on 2026-10-05; every quirk checked with SQL

起草：claude，1 轮

## bird:chicago_crime　已确认　校验通过

> Chicago police crime reports from 2018. Each of the 22 police districts (District) has its crime reports (Crime), each classified by an IUCR code and an FBI code and placed in a ward and a community area. A task is about one district and its reports; codes, wards, community areas and neighborhoods are shared lists.

| 项 | 内容 |
|---|---|
| 根 | District（police district） |
| 类型 | 实体（根是物，不是人） |
| 说话人角色 | a records clerk at this district's police station；a data quality analyst for this district's crime reports；this district's community policing liaison；a police department auditor reviewing this district's reports |
| 可新建的查找行 | — |
| 人物表 | District（district_no；district_name） |
| 事件 | Crime（crime reports）：Crime.district_no -> District.district_no |
| 属性表 | — |
| 公共表 | IUCR, FBI_Code, Ward, Community_Area, Neighborhood |
| 排除 | — |
| 不出 INSERT | — |
| 数据怪异点 | Crime.date is text 'M/D/YYYY H:MM' ('1/1/2018 2:46').；Crime.arrest and Crime.domestic are the strings 'TRUE' and 'FALSE'.；District.email and District.twitter begin with a non-breaking space; never copy it into a new value.；Community_Area.population is text with thousands commas ('54,991').；FBI codes mix digits and letters ('01A', '2'). |

挂在根和事件下面的父行（← 后面是外键列）：

- Crime（crime reports）
  - IUCR ← Crime.iucr_no
  - FBI_Code ← Crime.fbi_code_no
  - Ward ← Crime.ward_no
  - Community_Area ← Crime.community_area_no

主键：可省 ID：Community_Area, Crime, District, Ward；非整数或复合主键：FBI_Code(fbi_code_no), IUCR(iucr_no), Neighborhood(neighborhood_name)

Claude 的改动：
- Claude: drafted from the schema and data on 2026-10-05; every quirk checked with SQL

起草：claude，1 轮

## bird:college_completion　已确认　校验通过

> US college completion data. Each institution (institution_details) has profile figures and graduation cohorts (institution_grads, one row per year, gender, race and cohort type). A task is about one institution and its cohorts; the state and sector tables are shared summaries.

| 项 | 内容 |
|---|---|
| 根 | institution_details（institution） |
| 类型 | 实体（根是物，不是人） |
| 说话人角色 | an institutional research analyst at this college；a registrar's office data coordinator；a state higher-education reporting officer；a data steward for this institution's completion reports |
| 可新建的查找行 | — |
| 人物表 | institution_details（unitid；chronname） |
| 事件 | institution_grads（graduation cohorts）：institution_grads.unitid -> institution_details.unitid |
| 属性表 | — |
| 公共表 | state_sector_details, state_sector_grads |
| 排除 | — |
| 不出 INSERT | — |
| 数据怪异点 | Missing values are the text 'NULL', not SQL NULL, in most columns (grad_100 is 'NULL' in 69% of institution_grads rows).；institution_grads has no key: a row is one (unitid, year, gender, race, cohort); gender is 'B' (both), 'M' or 'F'; race is 'X' (all), 'W', 'B', 'H', 'Ai' or 'A'; cohort is '2y all', '4y bach' or '4y other'.；grad_100 and grad_150 count students who graduated within 100% and 150% of normal time; grad_100_rate and grad_150_rate are those counts as percentages of grad_cohort.；institution_details.state is the full state name ('Alabama'). |

主键：可省 ID：institution_details；非整数或复合主键：state_sector_details(stateid, level, control)；无主键：institution_grads, state_sector_grads

Claude 的改动：
- Claude: drafted from the schema and data on 2026-10-05; every quirk checked with SQL

起草：claude，1 轮

## bird:food_inspection　已确认　校验通过

> San Francisco restaurant health inspections. Each business (businesses) has inspections (with a score and a type) and violations (with a risk category). A task is about one business and its inspection records.

| 项 | 内容 |
|---|---|
| 根 | businesses（business） |
| 类型 | 实体（根是物，不是人） |
| 说话人角色 | the manager of this restaurant；a health inspector who visited this business；a compliance consultant hired by this business；a clerk at the city's environmental health office |
| 可新建的查找行 | — |
| 人物表 | businesses（business_id；name） |
| 事件 | inspections（inspections）：inspections.business_id -> businesses.business_id；violations（violations）：violations.business_id -> businesses.business_id |
| 属性表 | — |
| 公共表 | — |
| 排除 | — |
| 不出 INSERT | — |
| 数据怪异点 | inspections and violations have no key; dates are 'YYYY-MM-DD'.；146 inspections share business_id, date and type with another inspection, so a task naming one such inspection gives its score as well.；inspections.score is NULL for inspections that are not scored (46% of them, such as follow-ups).；violations.risk_category is 'Low Risk', 'Moderate Risk' or 'High Risk'.；owner_name is the business's legal owner, often a company ('Tiramisu LLC'), not necessarily the person speaking. |

主键：可省 ID：businesses；无主键：inspections, violations

Claude 的改动：
- Claude: drafted from the schema and data on 2026-10-05; every quirk checked with SQL

起草：claude，1 轮

## bird:menu　已确认　校验通过

> The New York Public Library's collection of historical restaurant menus. Each menu (Menu) has pages (MenuPage), and each page lists items (MenuItem) that point to a dish (Dish) with a price. A task is about one menu: its catalogue details, its pages and the items on them; dishes are shared by all menus.

| 项 | 内容 |
|---|---|
| 根 | Menu（menu） |
| 类型 | 实体（根是物，不是人） |
| 说话人角色 | a volunteer transcriber who keyed in this menu for the library's collection；a menu collection archivist cataloguing this menu；a culinary historian researching this menu；a librarian correcting this menu's catalogue record；a descendant of the restaurant's owner who donated the original menu |
| 可新建的查找行 | MenuItem.dish_id -> Dish.id（名字列 name） |
| 人物表 | Menu（id；sponsor） |
| 事件 | MenuPage（pages）：MenuPage.menu_id -> Menu.id；MenuItem（menu items）：MenuPage.menu_id -> Menu.id / MenuItem.menu_page_id -> MenuPage.id |
| 属性表 | — |
| 公共表 | Dish |
| 排除 | — |
| 不出 INSERT | — |
| 数据怪异点 | Menu.name is empty (NULL or '') for 82% of menus; the sponsor column usually names the restaurant, hotel or host, about half of the time in upper case ('HOTEL EASTMAN').；Menu.event, venue, place and occasion are transcriptions with brackets and trailing semicolons ('[DINNER]', 'EASTER;'); copy them exactly.；MenuItem.price and high_price are numbers or NULL.；Dish.menus_appeared, times_appeared, first_appeared, last_appeared, lowest_price and highest_price are statistics over all menus, not facts of one menu.；Menu.page_count and dish_count are counts kept on the menu row; adding or removing a page or an item does not change them by itself. |

挂在根和事件下面的父行（← 后面是外键列）：

- MenuItem（menu items）
  - Dish ← MenuItem.dish_id

主键：可省 ID：Dish, Menu, MenuItem, MenuPage

Claude 的改动：
- Claude: drafted from the schema and data on 2026-10-05; every quirk checked with SQL

起草：claude，1 轮

## bird:restaurant　已确认　校验通过

> A Bay Area restaurant directory. Each restaurant (generalinfo) has a food type, a city and a review score, and one address row (location). A task is about one restaurant; cities (geographic, with county and region) are a shared list.

| 项 | 内容 |
|---|---|
| 根 | generalinfo（restaurant） |
| 类型 | 实体（根是物，不是人） |
| 说话人角色 | the owner of this restaurant；a food guide editor maintaining this restaurant's listing；a local reviewer who curates the bay area listings；a data entry clerk for the restaurant directory |
| 可新建的查找行 | generalinfo.city -> geographic.city（名字列 city） |
| 人物表 | generalinfo（id_restaurant；label） |
| 事件 | — |
| 属性表 | location → generalinfo |
| 公共表 | geographic |
| 排除 | — |
| 不出 INSERT | — |
| 数据怪异点 | All text is lower case ('sparky's diner', 'san francisco', 'church st'); keep new values lower case.；review is a score between 1.3 and 4.5 with one decimal.；location.street_num is the house number and street_name the street only.；geographic.city is the key of geographic: a new city row states city, county and region. |

挂在根和事件下面的父行（← 后面是外键列）：

- 根 generalinfo
  - geographic ← generalinfo.city

主键：可省 ID：generalinfo, location；非整数或复合主键：geographic(city)

Claude 的改动：
- Claude: drafted from the schema and data on 2026-10-05; every quirk checked with SQL

起草：claude，1 轮

## bird:shakespeare　已确认　校验通过

> The works of Shakespeare. Each work (works) has scenes (chapters, by act and scene) and each scene has paragraphs of text, each spoken by a character. A task is about one work, its scenes and its paragraphs; characters are a shared list.

| 项 | 内容 |
|---|---|
| 根 | works（work） |
| 类型 | 实体（根是物，不是人） |
| 说话人角色 | an editor of this work's digital edition；a dramaturg preparing this work for a production；a literature professor correcting the text for a course reader；a volunteer proofreader for the Shakespeare corpus |
| 可新建的查找行 | paragraphs.character_id -> characters.id（名字列 CharName） |
| 人物表 | works（id；Title） |
| 事件 | chapters（scenes）：chapters.work_id -> works.id；paragraphs（paragraphs）：chapters.work_id -> works.id / paragraphs.chapter_id -> chapters.id |
| 属性表 | — |
| 公共表 | characters |
| 排除 | — |
| 不出 INSERT | — |
| 数据怪异点 | chapters are scenes: Act and Scene are numbers; 270 scene descriptions use the curly apostrophe (’), so copy them exactly.；paragraphs.PlainText often spans several lines and includes stage directions in square brackets.；characters is one list for all works; 1,266 rows hold 957 distinct names, so a character is named by its id.；works.GenreType is 'Comedy', 'Tragedy', 'History', 'Poem' or 'Sonnet'; works.Date is a year. |

挂在根和事件下面的父行（← 后面是外键列）：

- paragraphs（paragraphs）
  - characters ← paragraphs.character_id

主键：可省 ID：chapters, characters, paragraphs, works

Claude 的改动：
- Claude: drafted from the schema and data on 2026-10-05; every quirk checked with SQL

起草：claude，1 轮

## bird:university　已确认　校验通过

> World university rankings. Each university has a country, yearly figures (students, staff ratio, international and female shares) and ranking scores per year and criterion, where each criterion belongs to a ranking system. A task is about one university; countries, ranking systems and criteria are shared lists.

| 项 | 内容 |
|---|---|
| 根 | university（university） |
| 类型 | 实体（根是物，不是人） |
| 说话人角色 | a data officer in this university's planning office；an analyst at a ranking agency correcting this university's scores；this university's international office coordinator；a higher-education researcher maintaining this dataset |
| 可新建的查找行 | university_ranking_year.ranking_criteria_id -> ranking_criteria.id（名字列 criteria_name） |
| 人物表 | university（id；university_name） |
| 事件 | university_year（yearly figures）：university_year.university_id -> university.id；university_ranking_year（ranking scores）：university_ranking_year.university_id -> university.id |
| 属性表 | — |
| 公共表 | country, ranking_system, ranking_criteria |
| 排除 | — |
| 不出 INSERT | — |
| 数据怪异点 | university_year and university_ranking_year have no key: a yearly row is one (university_id, year), a score row one (university_id, ranking_criteria_id, year).；pct_international_students and pct_female_students are whole percentages; student_staff_ratio is students per staff member.；score is an integer, NULL for 130 rows.；A new ranking_criteria row states its ranking_system_id and criteria_name. |

挂在根和事件下面的父行（← 后面是外键列）：

- 根 university
  - country ← university.country_id
- university_ranking_year（ranking scores）
  - ranking_criteria ← university_ranking_year.ranking_criteria_id
    - ranking_system ← ranking_criteria.ranking_system_id

主键：可省 ID：country, ranking_criteria, ranking_system, university；无主键：university_ranking_year, university_year

Claude 的改动：
- Claude: drafted from the schema and data on 2026-10-05; every quirk checked with SQL

起草：claude，1 轮

## bird:video_games　已确认　校验通过

> A video game sales catalogue. Each game has a genre and one or more publishers (game_publisher); each publisher's release of the game on a platform is a game_platform row with a release year, and region_sales gives its sales per region. A task is about one game; genres, publishers, platforms and regions are shared lists.

| 项 | 内容 |
|---|---|
| 根 | game（game） |
| 类型 | 实体（根是物，不是人） |
| 说话人角色 | a catalog manager at the game's publisher；a video game archivist maintaining this game's entry；a sales analyst updating this game's regional figures；a community wiki editor who maintains this game's page |
| 可新建的查找行 | game.genre_id -> genre.id（名字列 genre_name）；game_publisher.publisher_id -> publisher.id（名字列 publisher_name）；game_platform.platform_id -> platform.id（名字列 platform_name） |
| 人物表 | game（id；game_name） |
| 事件 | game_publisher（publishers of the game）：game_publisher.game_id -> game.id；game_platform（platform releases）：game_publisher.game_id -> game.id / game_platform.game_publisher_id -> game_publisher.id；region_sales（regional sales）：game_publisher.game_id -> game.id / game_platform.game_publisher_id -> game_publisher.id / region_sales.game_platform_id -> game_platform.id |
| 属性表 | — |
| 公共表 | genre, publisher, platform, region |
| 排除 | — |
| 不出 INSERT | — |
| 数据怪异点 | A game reaches its platforms through game_publisher: game_platform.game_publisher_id points to a game_publisher row, not to the game.；region_sales has no key: a row is one (region_id, game_platform_id); by the database's notes, games sold = num_sales * 100000. |

挂在根和事件下面的父行（← 后面是外键列）：

- 根 game
  - genre ← game.genre_id
- game_publisher（publishers of the game）
  - publisher ← game_publisher.publisher_id
- game_platform（platform releases）
  - platform ← game_platform.platform_id
- region_sales（regional sales）
  - region ← region_sales.region_id

主键：可省 ID：game, game_platform, game_publisher, genre, platform, publisher, region；无主键：region_sales

Claude 的改动：
- Claude: drafted from the schema and data on 2026-10-05; every quirk checked with SQL

起草：claude，1 轮

## spider1:bike_1　已确认　校验通过

> A Bay Area bike-share system. Each station has minute-by-minute availability readings (status) and the trips that started there (trip). A task is about one station; daily weather is a shared table.

| 项 | 内容 |
|---|---|
| 根 | station（station） |
| 类型 | 实体（根是物，不是人） |
| 说话人角色 | an operations coordinator for this bike-share station；a rebalancing crew lead responsible for this station；a data analyst at the bike-share program；a city transportation planner who oversees this station |
| 可新建的查找行 | — |
| 人物表 | station（id；name） |
| 事件 | status（availability readings）：status.station_id -> station.id；trip（trips started here）：trip.start_station_id -> station.id |
| 属性表 | — |
| 公共表 | weather |
| 排除 | — |
| 不出 INSERT | — |
| 数据怪异点 | installation_date and trip dates are 'M/D/YYYY' ('8/21/2015 17:03' for trips); status.time is 'YYYY-MM-DD HH:MM:SS'.；status has no key: a row is one (station_id, time).；trip.start_station_name and end_station_name copy the station's name at trip time and differ from station.name for 213 trips.；trip.duration is in seconds. |

主键：可省 ID：station, trip；无主键：status, weather

Claude 的改动：
- Claude: drafted from the schema and data on 2026-10-05; every quirk checked with SQL

起草：claude，1 轮

## spider1:csu_1　已确认　校验通过

> The California State University campuses. Each campus has its yearly degrees, enrollments, enrollments by discipline, faculty counts and one fee row. A task is about one campus.

| 项 | 内容 |
|---|---|
| 根 | Campuses（campus） |
| 类型 | 实体（根是物，不是人） |
| 说话人角色 | an institutional research analyst at this campus；the campus registrar's data coordinator；a system-wide CSU reporting officer；a budget analyst who tracks this campus's fees |
| 可新建的查找行 | — |
| 人物表 | Campuses（Id；Campus） |
| 事件 | degrees（degrees awarded）：degrees.Campus -> Campuses.Id；enrollments（yearly enrollments）：enrollments.Campus -> Campuses.Id；discipline_enrollments（enrollments by discipline）：discipline_enrollments.Campus -> Campuses.Id；faculty（faculty counts）：faculty.Campus -> Campuses.Id |
| 属性表 | csu_fees → Campuses |
| 公共表 | — |
| 排除 | — |
| 不出 INSERT | — |
| 数据怪异点 | The Campus column of every other table holds Campuses.Id (a number), not the campus name.；degrees and enrollments are keyed by year and campus; discipline_enrollments by campus and Discipline, a number code.；faculty has no key: a row is one (Campus, Year); Faculty is a full-time-equivalent count with a decimal. |

主键：可省 ID：Campuses, csu_fees；非整数或复合主键：degrees(Year, Campus), discipline_enrollments(Campus, Discipline), enrollments(Campus, Year)；无主键：faculty

Claude 的改动：
- Claude: drafted from the schema and data on 2026-10-05; every quirk checked with SQL

起草：claude，1 轮

## spider1:flight_4　已确认　校验通过

> A world airline route map. Each airline operates routes from a source airport to a destination airport. A task is about one airline and its routes; airports are a shared list.

| 项 | 内容 |
|---|---|
| 根 | airlines（airline） |
| 类型 | 实体（根是物，不是人） |
| 说话人角色 | a network planner at this airline；the airline's schedules data manager；an aviation database volunteer who maintains this airline's routes；an airport slot coordinator working with this airline |
| 可新建的查找行 | routes.dst_apid -> airports.apid（名字列 name） |
| 人物表 | airlines（alid；name） |
| 事件 | routes（routes）：routes.alid -> airlines.alid |
| 属性表 | — |
| 公共表 | airports |
| 排除 | — |
| 不出 INSERT | — |
| 数据怪异点 | routes.airline, src_ap and dst_ap repeat codes as text and do not always match airlines.iata or airports.iata (airline code '2' for '2L'); routes are tied to airlines and airports by alid, src_apid and dst_apid.；airlines.active is 'Y' or 'N'; alid -1 is 'Unknown'.；routes.codeshare is 'Y' or NULL.；airports.x and airports.y are longitude and latitude. |

挂在根和事件下面的父行（← 后面是外键列）：

- routes（routes）
  - airports ← routes.src_apid
  - airports ← routes.dst_apid

主键：可省 ID：airlines, airports, routes

Claude 的改动：
- Claude: drafted from the schema and data on 2026-10-05; every quirk checked with SQL

起草：claude，1 轮

## spider2:Airlines　已确认　校验通过

> A Russian airline's bookings from 2017. Each booking has tickets, one per passenger; each ticket covers flights (ticket_flights, with fare class and amount) and may have boarding passes with seats. A task is about one booking; flights, airports, aircraft and seats are shared lists.

| 项 | 内容 |
|---|---|
| 根 | bookings（booking） |
| 类型 | 实体（根是物，不是人） |
| 说话人角色 | the customer who made this booking；a travel agent who manages this booking；a call-centre agent at the airline handling this booking；a corporate travel coordinator who booked these tickets |
| 可新建的查找行 | — |
| 人物表 | bookings（book_ref；） |
| 事件 | tickets（tickets）：tickets.book_ref -> bookings.book_ref；ticket_flights（ticket flights）：tickets.book_ref -> bookings.book_ref / ticket_flights.ticket_no -> tickets.ticket_no；boarding_passes（boarding passes）：tickets.book_ref -> bookings.book_ref / boarding_passes.ticket_no -> tickets.ticket_no |
| 属性表 | — |
| 公共表 | flights, airports_data, aircrafts_data, seats |
| 排除 | — |
| 不出 INSERT | — |
| 数据怪异点 | book_ref and ticket_no are text codes with leading zeros ('00000F', '0005435212351'); copy them exactly.；book_date and flight times carry a +03 time zone ('2017-07-05 03:12:00+03').；total_amount and amount are whole rubles.；fare_conditions is 'Economy', 'Comfort' or 'Business'.；tickets.passenger_id is a document number with a space ('8149 604011'); passengers' names are not stored.；airports_data and aircrafts_data names are JSON text with English and Russian ('{"en": "Boeing 777-300", "ru": ...}'). |

挂在根和事件下面的父行（← 后面是外键列）：

- ticket_flights（ticket flights）
  - flights ← ticket_flights.flight_id
- boarding_passes（boarding passes）
  - flights ← boarding_passes.flight_id

主键：无主键：aircrafts_data, airports_data, boarding_passes, bookings, flights, seats, ticket_flights, tickets

Claude 的改动：
- Claude: drafted from the schema and data on 2026-10-05; every quirk checked with SQL

起草：claude，1 轮

## spider2:imdb_movies　已确认　校验通过

> A movie database. Each movie has genres, a rating row, cast members (role_mapping) and directors (director_mapping), who are people in names. A task is about one movie; people are a shared list.

| 项 | 内容 |
|---|---|
| 根 | movies（movie） |
| 类型 | 实体（根是物，不是人） |
| 说话人角色 | a film database editor maintaining this movie's entry；the distributor's metadata manager for this movie；a film archivist cataloguing this title；a volunteer contributor who curates this movie's page |
| 可新建的查找行 | — |
| 人物表 | movies（id；title） |
| 事件 | genre（genres）：genre.movie_id -> movies.id；role_mapping（cast）：role_mapping.movie_id -> movies.id；director_mapping（directors）：director_mapping.movie_id -> movies.id |
| 属性表 | ratings → movies |
| 公共表 | names |
| 排除 | ERD |
| 不出 INSERT | — |
| 数据怪异点 | Ids are text: movies 'tt0012494', people 'nm0000002'.；The column worlwide_gross_income is misspelled and holds text such as '$ 12156'.；genre has one row per movie and genre ('Drama'); role_mapping.category is 'actor' or 'actress'.；date_published is 'YYYY-MM-DD 00:00:00'.；No table has a declared key; movies.id and names.id are unique. |

挂在根和事件下面的父行（← 后面是外键列）：

- role_mapping（cast）
  - names ← role_mapping.name_id
- director_mapping（directors）
  - names ← director_mapping.name_id

主键：无主键：ERD, director_mapping, genre, movies, names, ratings, role_mapping

Claude 的改动：
- Claude: drafted from the schema and data on 2026-10-05; every quirk checked with SQL

起草：claude，1 轮

