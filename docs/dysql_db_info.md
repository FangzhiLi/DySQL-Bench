# DySQL-Bench 数据库明细

13 个 SQLite 库，文件与原版 Spider2-lite / BIRD train 逐字节一致。统计方式：PRAGMA + COUNT(*)（不含 view）；任务 SQL 构成来自各 env 的 tasks_test.py 中 gold action 的 SQL 语句。

## 总览

| 数据库 | env | 来源 | 主题 | 任务数（含写操作） | gold SQL 构成 | 主要写入表 | 表 | 列 | 总行数 | 有 PK 的表 | FK |
|---|---|---|---|---|---|---|---|---|---|---|---|
| EU_soccer | eu_soccer | Spider2-lite | 欧洲足球比赛、球员、球队属性 | 215（213） | U642 / I16 / D11 / S139 (+其他 4) | Match(449), Player(166), Player_Attributes(51) | 7 | 199 | 222,796 | 7/7 | 31 |
| complex_oracle | retail | Spider2-lite | Oracle SH 销售数仓（销售、促销、成本、渠道） | 205（204） | U288 / I48 / D87 / S98 (+其他 1) | sales(167), costs(156), customers(53) | 10 | 140 | 1,064,608 | 7/10 | 10 |
| EntertainmentAgency | entertainment | Spider2-lite | 演艺经纪（艺人、演出预约、客户、经纪人） | 131（131） | U206 / I52 / D24 / S95 (+其他 1) | Entertainer_Styles(78), Engagements(77), Entertainer_Members(58) | 13 | 76 | 1,654 | 13/13 | 9 |
| BowlingLeague | bowling | Spider2-lite | 保龄球联赛（队伍、比赛、成绩） | 111（111） | U70 / I125 / D86 / S81 | Bowler_Scores(116), Bowler_Scores_Archive(87), Bowlers(19) | 11 | 54 | 2,156 | 11/11 | 8 |
| Pagila | pagila | Spider2-lite | Pagila DVD 租赁（Sakila 的 Postgres 版） | 105（105） | U122 / I5 / D77 / S69 (+其他 1) | payment(99), rental(68), customer(15) | 16 | 89 | 46,273 | 16/16 | 22 |
| law_episode | law_episode | BIRD train | 《法律与秩序》剧集、演职员、奖项 | 53（53） | U61 / I15 / D5 / S23 | Credit(56), Person(15), Award(10) | 6 | 41 | 3,350 | 5/6 | 6 |
| cookbook | cookbook | BIRD train | 菜谱、食材与营养 | 51（51） | U69 / I29 / D19 / S10 | Quantity(64), Nutrition(31), Recipe(13) | 4 | 39 | 10,371 | 4/4 | 4 |
| chinook | chinook | Spider2-lite | Chinook 数字音乐商店 | 44（44） | U41 / I11 / D29 / S46 | invoice_items(37), invoices(22), customers(14) | 11 | 64 | 15,607 | 11/11 | 11 |
| human_resources | human_resources | BIRD train | 员工、职位与办公地点 | 40（40） | U48 / I12 / D4 / S30 | employee(46), location(16), position(2) | 3 | 20 | 37 | 3/3 | 2 |
| retail_world | retail_world | BIRD train | Northwind 式贸易公司（订单、供应商、运输） | 31（31） | U56 / I8 / D2 / S19 | Orders(37), OrderDetails(29) | 8 | 42 | 932 | 8/8 | 7 |
| ice_hockey_draft | ice_hockey | BIRD train | 冰球选秀球员与赛季数据 | 28（28） | U44 / I18 / S15 | PlayerInfo(28), SeasonStatus(15), weight_info(13) | 4 | 37 | 7,718 | 3/4 | 3 |
| cars | car | BIRD train | 汽车油耗、价格与产地（Auto MPG） | 27（27） | U37 / I9 / D4 / S6 | price(25), production(19), data(6) | 4 | 16 | 1,491 | 4/4 | 4 |
| music | music | Spider2-lite | Chinook 数字音乐商店（驼峰命名版） | 21（21） | U16 / I16 / D22 / S15 | InvoiceLine(32), Invoice(12), PlaylistTrack(7) | 11 | 64 | 15,607 | 11/11 | 11 |
| **合计** | | | | **1062（1059）** | U1700 / I364 / D370 / S646 | | **108** | **881** | **1,392,600** | 103/108 | 128 |

gold SQL 构成：U=UPDATE，I=INSERT，D=DELETE，S=SELECT（语句条数）；FK 数按外键约束计，复合外键算 1 条。

## 各库表结构

### EU_soccer — 欧洲足球比赛、球员、球队属性

| 表 | 行数 | 列数 | 列名 | PK | FK（本列 → 引用表.列） |
|---|---|---|---|---|---|
| Player_Attributes | 183,978 | 42 | id, player_fifa_api_id, player_api_id, date, overall_rating, potential, preferred_foot, attacking_work_rate, defensive_work_rate, crossing, finishing, heading_accuracy, short_passing, volleys, dribbling, curve, free_kick_accuracy, long_passing, ball_control, acceleration, sprint_speed, agility, reactions, balance, shot_power, jumping, stamina, strength, long_shots, aggression, interceptions, positioning, vision, penalties, marking, standing_tackle, sliding_tackle, gk_diving, gk_handling, gk_kicking, gk_positioning, gk_reflexes | id | player_api_id → Player.player_api_id; player_fifa_api_id → Player.player_fifa_api_id |
| Player | 11,060 | 7 | id, player_api_id, player_name, player_fifa_api_id, birthday, height, weight | id | — |
| Match | 25,979 | 115 | id, country_id, league_id, season, stage, date, match_api_id, home_team_api_id, away_team_api_id, home_team_goal, away_team_goal, home_player_X1, home_player_X2, home_player_X3, home_player_X4, home_player_X5, home_player_X6, home_player_X7, home_player_X8, home_player_X9, home_player_X10, home_player_X11, away_player_X1, away_player_X2, away_player_X3, away_player_X4, away_player_X5, away_player_X6, away_player_X7, away_player_X8, away_player_X9, away_player_X10, away_player_X11, home_player_Y1, home_player_Y2, home_player_Y3, home_player_Y4, home_player_Y5, home_player_Y6, home_player_Y7, home_player_Y8, home_player_Y9, home_player_Y10, home_player_Y11, away_player_Y1, away_player_Y2, away_player_Y3, away_player_Y4, away_player_Y5, away_player_Y6, away_player_Y7, away_player_Y8, away_player_Y9, away_player_Y10, away_player_Y11, home_player_1, home_player_2, home_player_3, home_player_4, home_player_5, home_player_6, home_player_7, home_player_8, home_player_9, home_player_10, home_player_11, away_player_1, away_player_2, away_player_3, away_player_4, away_player_5, away_player_6, away_player_7, away_player_8, away_player_9, away_player_10, away_player_11, goal, shoton, shotoff, foulcommit, card, cross, corner, possession, B365H, B365D, B365A, BWH, BWD, BWA, IWH, IWD, IWA, LBH, LBD, LBA, PSH, PSD, PSA, WHH, WHD, WHA, SJH, SJD, SJA, VCH, VCD, VCA, GBH, GBD, GBA, BSH, BSD, BSA | id | away_player_1..11, home_player_1..11 → Player.player_api_id; away_team_api_id, home_team_api_id → Team.team_api_id; league_id → League.id; country_id → country.id |
| League | 11 | 3 | id, country_id, name | id | country_id → country.id |
| Country | 11 | 2 | id, name | id | — |
| Team | 299 | 5 | id, team_api_id, team_fifa_api_id, team_long_name, team_short_name | id | — |
| Team_Attributes | 1,458 | 25 | id, team_fifa_api_id, team_api_id, date, buildUpPlaySpeed, buildUpPlaySpeedClass, buildUpPlayDribbling, buildUpPlayDribblingClass, buildUpPlayPassing, buildUpPlayPassingClass, buildUpPlayPositioningClass, chanceCreationPassing, chanceCreationPassingClass, chanceCreationCrossing, chanceCreationCrossingClass, chanceCreationShooting, chanceCreationShootingClass, chanceCreationPositioningClass, defencePressure, defencePressureClass, defenceAggression, defenceAggressionClass, defenceTeamWidth, defenceTeamWidthClass, defenceDefenderLineClass | id | team_api_id → Team.team_api_id; team_fifa_api_id → Team.team_fifa_api_id |

### complex_oracle — Oracle SH 销售数仓（销售、促销、成本、渠道）

| 表 | 行数 | 列数 | 列名 | PK | FK（本列 → 引用表.列） |
|---|---|---|---|---|---|
| countries | 35 | 9 | country_id, country_iso_code, country_name, country_subregion, country_subregion_id, country_region, country_region_id, country_total, country_total_id | country_id | — |
| customers | 55,500 | 23 | cust_id, cust_first_name, cust_last_name, cust_gender, cust_year_of_birth, cust_marital_status, cust_street_address, cust_postal_code, cust_city, cust_city_id, cust_state_province, cust_state_province_id, country_id, cust_main_phone_number, cust_income_level, cust_credit_limit, cust_email, cust_total, cust_total_id, cust_src_id, cust_eff_from, cust_eff_to, cust_valid | cust_id | country_id → countries.country_id |
| promotions | 503 | 11 | promo_id, promo_name, promo_subcategory, promo_subcategory_id, promo_category, promo_category_id, promo_cost, promo_begin_date, promo_end_date, promo_total, promo_total_id | promo_id | — |
| products | 24 | 22 | prod_id, prod_name, prod_desc, prod_subcategory, prod_subcategory_id, prod_subcategory_desc, prod_category, prod_category_id, prod_category_desc, prod_weight_class, prod_unit_of_measure, prod_pack_size, supplier_id, prod_status, prod_list_price, prod_min_price, prod_total, prod_total_id, prod_src_id, prod_eff_from, prod_eff_to, prod_valid | prod_id | — |
| times | 1,826 | 38 | time_id, day_name, day_number_in_week, day_number_in_month, calendar_week_number, fiscal_week_number, week_ending_day, week_ending_day_id, calendar_month_number, fiscal_month_number, calendar_month_desc, calendar_month_id, fiscal_month_desc, fiscal_month_id, days_in_cal_month, days_in_fis_month, end_of_cal_month, end_of_fis_month, calendar_month_name, fiscal_month_name, calendar_quarter_desc, calendar_quarter_id, fiscal_quarter_desc, fiscal_quarter_id, days_in_cal_quarter, days_in_fis_quarter, end_of_cal_quarter, end_of_fis_quarter, calendar_quarter_number, fiscal_quarter_number, calendar_year, calendar_year_id, fiscal_year, fiscal_year_id, days_in_cal_year, days_in_fis_year, end_of_cal_year, end_of_fis_year | time_id | — |
| channels | 5 | 6 | channel_id, channel_desc, channel_class, channel_class_id, channel_total, channel_total_id | channel_id | — |
| sales | 918,843 | 7 | prod_id, cust_id, time_id, channel_id, promo_id, quantity_sold, amount_sold | — | time_id → times.time_id; channel_id → channels.channel_id; prod_id → products.prod_id; cust_id → customers.cust_id; promo_id → promotions.promo_id |
| costs | 82,112 | 6 | prod_id, time_id, promo_id, channel_id, unit_cost, unit_price | — | channel_id → channels.channel_id; time_id → times.time_id; prod_id → products.prod_id; promo_id → promotions.promo_id |
| supplementary_demographics | 4,500 | 14 | cust_id, education, occupation, household_size, yrs_residence, affinity_card, cricket, baseball, tennis, soccer, golf, unknown, misc, comments | cust_id | — |
| currency | 1,260 | 4 | country, year, month, to_us | — | — |

### EntertainmentAgency — 演艺经纪（艺人、演出预约、客户、经纪人）

| 表 | 行数 | 列数 | 列名 | PK | FK（本列 → 引用表.列） |
|---|---|---|---|---|---|
| Agents | 9 | 11 | AgentID, AgtFirstName, AgtLastName, AgtStreetAddress, AgtCity, AgtState, AgtZipCode, AgtPhoneNumber, DateHired, Salary, CommissionRate | AgentID | — |
| Customers | 15 | 8 | CustomerID, CustFirstName, CustLastName, CustStreetAddress, CustCity, CustState, CustZipCode, CustPhoneNumber | CustomerID | — |
| Engagements | 111 | 9 | EngagementNumber, StartDate, EndDate, StartTime, StopTime, ContractPrice, CustomerID, AgentID, EntertainerID | EngagementNumber | EntertainerID → Entertainers.EntertainerID; CustomerID → Customers.CustomerID; AgentID → Agents.AgentID |
| Entertainer_Members | 40 | 3 | EntertainerID, MemberID, Status | EntertainerID, MemberID | MemberID → Members.MemberID; EntertainerID → Entertainers.EntertainerID |
| Entertainer_Styles | 32 | 3 | EntertainerID, StyleID, StyleStrength | EntertainerID, StyleID | StyleID → Musical_Styles.StyleID; EntertainerID → Entertainers.EntertainerID |
| Entertainers | 13 | 11 | EntertainerID, EntStageName, EntSSN, EntStreetAddress, EntCity, EntState, EntZipCode, EntPhoneNumber, EntWebPage, EntEMailAddress, DateEntered | EntertainerID | — |
| Members | 25 | 5 | MemberID, MbrFirstName, MbrLastName, MbrPhoneNumber, Gender | MemberID | — |
| Musical_Preferences | 36 | 3 | CustomerID, StyleID, PreferenceSeq | CustomerID, StyleID | StyleID → Musical_Styles.StyleID; CustomerID → Customers.CustomerID |
| Musical_Styles | 25 | 2 | StyleID, StyleName | StyleID | — |
| ztblDays | 1,096 | 1 | DateField | DateField | — |
| ztblMonths | 36 | 17 | MonthYear, YearNumber, MonthNumber, MonthStart, MonthEnd, January, February, March, April, May, June, July, August, September, October, November, December | YearNumber, MonthNumber | — |
| ztblSkipLabels | 60 | 1 | LabelCount | LabelCount | — |
| ztblWeeks | 156 | 2 | WeekStart, WeekEnd | WeekStart | — |

### BowlingLeague — 保龄球联赛（队伍、比赛、成绩）

| 表 | 行数 | 列数 | 列名 | PK | FK（本列 → 引用表.列） |
|---|---|---|---|---|---|
| Bowler_Scores | 1,344 | 6 | MatchID, GameNumber, BowlerID, RawScore, HandiCapScore, WonGame | MatchID, GameNumber, BowlerID | MatchID,GameNumber → Match_Games.MatchID,GameNumber; BowlerID → Bowlers.BowlerID |
| Bowler_Scores_Archive | 0 | 6 | MatchID, GameNumber, BowlerID, RawScore, HandiCapScore, WonGame | MatchID, GameNumber, BowlerID | MatchID,GameNumber → Match_Games_Archive.MatchID,GameNumber |
| Bowlers | 34 | 14 | BowlerID, BowlerLastName, BowlerFirstName, BowlerMiddleInit, BowlerAddress, BowlerCity, BowlerState, BowlerZip, BowlerPhoneNumber, TeamID, BowlerTotalPins, BowlerGamesBowled, BowlerCurrentAverage, BowlerCurrentHcp | BowlerID | TeamID → Teams.TeamID |
| Match_Games | 168 | 3 | MatchID, GameNumber, WinningTeamID | MatchID, GameNumber | — |
| Match_Games_Archive | 0 | 3 | MatchID, GameNumber, WinningTeamID | MatchID, GameNumber | — |
| Teams | 10 | 3 | TeamID, TeamName, CaptainID | TeamID | — |
| Tournaments | 20 | 3 | TourneyID, TourneyDate, TourneyLocation | TourneyID | — |
| Tournaments_Archive | 0 | 3 | TourneyID, TourneyDate, TourneyLocation | TourneyID | — |
| Tourney_Matches | 57 | 5 | MatchID, TourneyID, Lanes, OddLaneTeamID, EvenLaneTeamID | MatchID | TourneyID → Tournaments.TourneyID; OddLaneTeamID, EvenLaneTeamID → Teams.TeamID |
| Tourney_Matches_Archive | 0 | 5 | MatchID, TourneyID, Lanes, OddLaneTeamID, EvenLaneTeamID | MatchID | TourneyID → Tournaments_Archive.TourneyID |
| WAZips | 523 | 3 | ZIP, City, State | ZIP | — |

### Pagila — Pagila DVD 租赁（Sakila 的 Postgres 版）

| 表 | 行数 | 列数 | 列名 | PK | FK（本列 → 引用表.列） |
|---|---|---|---|---|---|
| actor | 200 | 4 | actor_id, first_name, last_name, last_update | actor_id | — |
| country | 109 | 3 | country_id, country, last_update | country_id | — |
| city | 600 | 4 | city_id, city, country_id, last_update | city_id | country_id → country.country_id |
| address | 603 | 8 | address_id, address, address2, district, city_id, postal_code, phone, last_update | address_id | city_id → city.city_id |
| language | 6 | 3 | language_id, name, last_update | language_id | — |
| category | 16 | 3 | category_id, name, last_update | category_id | — |
| customer | 599 | 9 | customer_id, store_id, first_name, last_name, email, address_id, active, create_date, last_update | customer_id | address_id → address.address_id; store_id → store.store_id |
| film | 1,000 | 13 | film_id, title, description, release_year, language_id, original_language_id, rental_duration, rental_rate, length, replacement_cost, rating, special_features, last_update | film_id | original_language_id, language_id → language.language_id |
| film_actor | 5,462 | 3 | actor_id, film_id, last_update | actor_id, film_id | film_id → film.film_id; actor_id → actor.actor_id |
| film_category | 1,000 | 3 | film_id, category_id, last_update | film_id, category_id | category_id → category.category_id; film_id → film.film_id |
| film_text | 0 | 3 | film_id, title, description | film_id | — |
| inventory | 4,581 | 4 | inventory_id, film_id, store_id, last_update | inventory_id | film_id → film.film_id; store_id → store.store_id |
| staff | 2 | 11 | staff_id, first_name, last_name, address_id, picture, email, store_id, active, username, password, last_update | staff_id | address_id → address.address_id; store_id → store.store_id |
| store | 2 | 4 | store_id, manager_staff_id, address_id, last_update | store_id | address_id → address.address_id; manager_staff_id → staff.staff_id |
| payment | 16,049 | 7 | payment_id, customer_id, staff_id, rental_id, amount, payment_date, last_update | payment_id | staff_id → staff.staff_id; customer_id → customer.customer_id; rental_id → rental.rental_id |
| rental | 16,044 | 7 | rental_id, rental_date, inventory_id, customer_id, return_date, staff_id, last_update | rental_id | customer_id → customer.customer_id; inventory_id → inventory.inventory_id; staff_id → staff.staff_id |

### law_episode — 《法律与秩序》剧集、演职员、奖项

| 表 | 行数 | 列数 | 列名 | PK | FK（本列 → 引用表.列） |
|---|---|---|---|---|---|
| Episode | 24 | 11 | episode_id, series, season, episode, number_in_series, title, summary, air_date, episode_image, rating, votes | episode_id | — |
| Keyword | 33 | 2 | episode_id, keyword | episode_id, keyword | episode_id → Episode.episode_id |
| Person | 800 | 9 | person_id, name, birthdate, birth_name, birth_place, birth_region, birth_country, height_meters, nickname | person_id | — |
| Award | 22 | 10 | award_id, organization, year, award_category, award, series, episode_id, person_id, role, result | award_id | person_id → Person.person_id; episode_id → Episode.episode_id |
| Credit | 2,231 | 5 | episode_id, person_id, category, role, credited | episode_id, person_id | person_id → Person.person_id; episode_id → Episode.episode_id |
| Vote | 240 | 4 | episode_id, stars, votes, percent | — | episode_id → Episode.episode_id |

### cookbook — 菜谱、食材与营养

| 表 | 行数 | 列数 | 列名 | PK | FK（本列 → 引用表.列） |
|---|---|---|---|---|---|
| Ingredient | 3,346 | 4 | ingredient_id, category, name, plural | ingredient_id | — |
| Recipe | 1,031 | 11 | recipe_id, title, subtitle, servings, yield_unit, prep_min, cook_min, stnd_min, source, intro, directions | recipe_id | — |
| Nutrition | 878 | 16 | recipe_id, protein, carbo, alcohol, total_fat, sat_fat, cholestrl, sodium, iron, vitamin_c, vitamin_a, fiber, pcnt_cal_carb, pcnt_cal_fat, pcnt_cal_prot, calories | recipe_id | recipe_id → Recipe.recipe_id |
| Quantity | 5,116 | 8 | quantity_id, recipe_id, ingredient_id, max_qty, min_qty, unit, preparation, optional | quantity_id | recipe_id → Nutrition.recipe_id; ingredient_id → Ingredient.ingredient_id; recipe_id → Recipe.recipe_id |

### chinook — Chinook 数字音乐商店

| 表 | 行数 | 列数 | 列名 | PK | FK（本列 → 引用表.列） |
|---|---|---|---|---|---|
| albums | 347 | 3 | AlbumId, Title, ArtistId | AlbumId | ArtistId → artists.ArtistId |
| artists | 275 | 2 | ArtistId, Name | ArtistId | — |
| customers | 59 | 13 | CustomerId, FirstName, LastName, Company, Address, City, State, Country, PostalCode, Phone, Fax, Email, SupportRepId | CustomerId | SupportRepId → employees.EmployeeId |
| employees | 8 | 15 | EmployeeId, LastName, FirstName, Title, ReportsTo, BirthDate, HireDate, Address, City, State, Country, PostalCode, Phone, Fax, Email | EmployeeId | ReportsTo → employees.EmployeeId |
| genres | 25 | 2 | GenreId, Name | GenreId | — |
| invoices | 412 | 9 | InvoiceId, CustomerId, InvoiceDate, BillingAddress, BillingCity, BillingState, BillingCountry, BillingPostalCode, Total | InvoiceId | CustomerId → customers.CustomerId |
| invoice_items | 2,240 | 5 | InvoiceLineId, InvoiceId, TrackId, UnitPrice, Quantity | InvoiceLineId | TrackId → tracks.TrackId; InvoiceId → invoices.InvoiceId |
| media_types | 5 | 2 | MediaTypeId, Name | MediaTypeId | — |
| playlists | 18 | 2 | PlaylistId, Name | PlaylistId | — |
| playlist_track | 8,715 | 2 | PlaylistId, TrackId | PlaylistId, TrackId | TrackId → tracks.TrackId; PlaylistId → playlists.PlaylistId |
| tracks | 3,503 | 9 | TrackId, Name, AlbumId, MediaTypeId, GenreId, Composer, Milliseconds, Bytes, UnitPrice | TrackId | MediaTypeId → media_types.MediaTypeId; GenreId → genres.GenreId; AlbumId → albums.AlbumId |

### human_resources — 员工、职位与办公地点

| 表 | 行数 | 列数 | 列名 | PK | FK（本列 → 引用表.列） |
|---|---|---|---|---|---|
| location | 8 | 6 | locationID, locationcity, address, state, zipcode, officephone | locationID | — |
| position | 4 | 5 | positionID, positiontitle, educationrequired, minsalary, maxsalary | positionID | — |
| employee | 25 | 9 | ssn, lastname, firstname, hiredate, salary, gender, performance, positionID, locationID | ssn | positionID → position.positionID; locationID → location.locationID |

### retail_world — Northwind 式贸易公司（订单、供应商、运输）

| 表 | 行数 | 列数 | 列名 | PK | FK（本列 → 引用表.列） |
|---|---|---|---|---|---|
| Categories | 8 | 3 | CategoryID, CategoryName, Description | CategoryID | — |
| Customers | 91 | 7 | CustomerID, CustomerName, ContactName, Address, City, PostalCode, Country | CustomerID | — |
| Employees | 10 | 6 | EmployeeID, LastName, FirstName, BirthDate, Photo, Notes | EmployeeID | — |
| Shippers | 3 | 3 | ShipperID, ShipperName, Phone | ShipperID | — |
| Suppliers | 29 | 8 | SupplierID, SupplierName, ContactName, Address, City, PostalCode, Country, Phone | SupplierID | — |
| Products | 77 | 6 | ProductID, ProductName, SupplierID, CategoryID, Unit, Price | ProductID | SupplierID → Suppliers.SupplierID; CategoryID → Categories.CategoryID |
| Orders | 196 | 5 | OrderID, CustomerID, EmployeeID, OrderDate, ShipperID | OrderID | ShipperID → Shippers.ShipperID; CustomerID → Customers.CustomerID; EmployeeID → Employees.EmployeeID |
| OrderDetails | 518 | 4 | OrderDetailID, OrderID, ProductID, Quantity | OrderDetailID | ProductID → Products.ProductID; OrderID → Orders.OrderID |

### ice_hockey_draft — 冰球选秀球员与赛季数据

| 表 | 行数 | 列数 | 列名 | PK | FK（本列 → 引用表.列） |
|---|---|---|---|---|---|
| height_info | 16 | 3 | height_id, height_in_cm, height_in_inch | height_id | — |
| weight_info | 46 | 3 | weight_id, weight_in_kg, weight_in_lbs | weight_id | — |
| PlayerInfo | 2,171 | 20 | ELITEID, PlayerName, birthdate, birthyear, birthmonth, birthday, birthplace, nation, height, weight, position_info, shoots, draftyear, draftround, overall, overallby, CSS_rank, sum_7yr_GP, sum_7yr_TOI, GP_greater_than_0 | ELITEID | weight → weight_info.weight_id; height → height_info.height_id |
| SeasonStatus | 5,485 | 11 | ELITEID, SEASON, TEAM, LEAGUE, GAMETYPE, GP, G, A, P, PIM, PLUSMINUS | — | ELITEID → PlayerInfo.ELITEID |

### cars — 汽车油耗、价格与产地（Auto MPG）

| 表 | 行数 | 列数 | 列名 | PK | FK（本列 → 引用表.列） |
|---|---|---|---|---|---|
| country | 3 | 2 | origin, country | origin | — |
| price | 398 | 2 | ID, price | ID | — |
| data | 398 | 9 | ID, mpg, cylinders, displacement, horsepower, weight, acceleration, model, car_name | ID | ID → price.ID |
| production | 692 | 3 | ID, model_year, country | ID, model_year | ID → price.ID; ID → data.ID; country → country.origin |

### music — Chinook 数字音乐商店（驼峰命名版）

| 表 | 行数 | 列数 | 列名 | PK | FK（本列 → 引用表.列） |
|---|---|---|---|---|---|
| Album | 347 | 3 | AlbumId, Title, ArtistId | AlbumId | ArtistId → Artist.ArtistId |
| Artist | 275 | 2 | ArtistId, Name | ArtistId | — |
| Customer | 59 | 13 | CustomerId, FirstName, LastName, Company, Address, City, State, Country, PostalCode, Phone, Fax, Email, SupportRepId | CustomerId | SupportRepId → Employee.EmployeeId |
| Employee | 8 | 15 | EmployeeId, LastName, FirstName, Title, ReportsTo, BirthDate, HireDate, Address, City, State, Country, PostalCode, Phone, Fax, Email | EmployeeId | ReportsTo → Employee.EmployeeId |
| Genre | 25 | 2 | GenreId, Name | GenreId | — |
| Invoice | 412 | 9 | InvoiceId, CustomerId, InvoiceDate, BillingAddress, BillingCity, BillingState, BillingCountry, BillingPostalCode, Total | InvoiceId | CustomerId → Customer.CustomerId |
| InvoiceLine | 2,240 | 5 | InvoiceLineId, InvoiceId, TrackId, UnitPrice, Quantity | InvoiceLineId | TrackId → Track.TrackId; InvoiceId → Invoice.InvoiceId |
| MediaType | 5 | 2 | MediaTypeId, Name | MediaTypeId | — |
| Playlist | 18 | 2 | PlaylistId, Name | PlaylistId | — |
| PlaylistTrack | 8,715 | 2 | PlaylistId, TrackId | PlaylistId, TrackId | TrackId → Track.TrackId; PlaylistId → Playlist.PlaylistId |
| Track | 3,503 | 9 | TrackId, Name, AlbumId, MediaTypeId, GenreId, Composer, Milliseconds, Bytes, UnitPrice | TrackId | MediaTypeId → MediaType.MediaTypeId; GenreId → Genre.GenreId; AlbumId → Album.AlbumId |
