# 23 个库的档案：审阅页

GLM-5.3 按 `data/profile_hints.json` 的提示和两份 DySQL 手写示例起草了这些档案，Claude 又对着库逐个预审过。所有档案都通过了 `profile check`。用户 2026-10-01 审阅后回复"保持现状"：下面九点都按建议，档案没有再改，23 个库全部确认。由 `taskgen.py profile render` 生成，档案原文在 `taskgen/v2/data/db_profiles.json`。

## 怎么看

- 每个库一节。表格里是各类角色：根、人物表、事件、属性表、公共表、排除、不出 INSERT、数据怪异点。表格下面是挂在根和事件下面的父行，最后是主键分类。
- **"Claude 的改动"列出了预审改过的地方和原因。** 没改的库写着"no change"。
- 预审时，每条数据怪异点都用 SQL 查过。查不实的删了，说法不准的改了，对写 SQL 没用的也删了。
- **样例树**在本地文件 `taskgen/v2/results/profile_review/sample_trees.md`（含库里的数据行，不进 git）。每个根一棵，就是出题 prompt 里数据块的样子：每行都标了是本人的（own）、公共的（public），还是别人的（another person's data）。看档案时对照着翻几棵，最直观。

## 审阅时请用户判断的点

每条附了 Claude 的建议。用户的决定：全部保持现状。

1. **books：author 算公共表。**
   - 提示里这么写，草稿把它放进了人物表，我改回了公共表。
   - 算人物表的后果：作者的行会标成"别人的数据"，顾客改作者信息就算改别人的数据。
   - 建议：公共表。
2. **legislator：只用 historical 当根。**
   - current 算人物表（在任议员，和 historical 是不同的人）；current-terms、social-media 排除。
   - 这个库没有公共表，所以只出第 1、5 类题。
   - 建议：保持。
3. **student_loan：bool 排除，六张 flag 表算属性表（本人的数据）。**
   - 设计 §4.1 有一处写"exclude bool 和 flag 表"，另一处又拿 flag 表当属性表的例子，计划里取了后者。
   - 这个库没有公共表，只出第 1、5 类题。
   - 建议：属性表。
4. **professional_basketball：coaches、awards_coaches 排除。**
   - 草稿多加了 coaches 根，我去掉了。
   - 原因：coachID 在 coaches 里一个任期一行、会重复，而且教练没有姓名列，没法当人物表。
   - 建议：排除。
5. **"不出 INSERT"的表。** 主键是没有"下一个"值的文本：
   - synthea 的 UUID；
   - student_club 的 `rec…`；
   - legislator 的 bioguide；
   - book_publishing_company 的各种代码；
   - regional_sales 的 `SO - 000101`；
   - retail_complains 的 `C00000001` / `CR0000072`。

   影响最大的是 regional_sales：它唯一的事件表 "Sales Orders" 不能新增，这个库只会出改、删和公共数据的题。car_retails 的 payments 我放开了：支票号本来就由客户提供，记一笔新付款是很自然的请求。建议：保持。
6. **synthea 的 all_prevalences 没挂到任何事件下面。**
   - conditions.DESCRIPTION 只有 20% 能对上 all_prevalences.ITEM，算不上外键。
   - 结果是这个库的样例树里没有公共行，只出第 1、5 类题。
   - 建议：保持（病人去改疾病流行率数据本来也不合理）。
7. **两条代码层面的修正（预审时发现的，已带测试单独提交）。** 它们会影响档案怎么生效：
   - **(a) 父表那一侧必须唯一。**
     - 校验现在要求每条边的父表那一侧唯一，也就是一条记录只指向一行。
     - 草稿里有 3 条边不满足：books 的书 → 作者关联（写反了方向）、college_2 的课段 → 时间段、教练奖项 → 教练。
   - **(b) 公共表的行不属于任何人。**
     - 带档案时，归属追溯到公共表就停下。
     - 起因是 school_scheduling 的 Departments.DeptChair 指向一位老师，原来的追溯会把院系、类别、科目全算成"系主任的私人数据"，学生改这些就会被当成改别人的数据。
     - 只有这个库受影响；不带档案的检查（DySQL 金标准、v1 候选）不变。
8. **父行和事件组做了精简。**
   - 目的是让每条事件只挂看懂它需要的一两层，省 prompt。
   - 改动的库：beer_factory、college_2、hr_1、IPL、WWE、school_scheduling；IPL 还去掉了"非击球端"这组。
   - 具体见各库的"Claude 的改动"。
9. **same_as 的误用都删了。**
   - 涉及 hr_1、IPL、WWE。
   - same_as 是"同一个人在别的表里的身份列"，草稿拿它表示"这一列引用了某个人"（经理、最佳球员）。照草稿那样，部门、比赛都会被算成那个人的私人数据。

---

## bird:address　已确认　校验通过

> A United States postal geography and demographics reference built around ZIP codes: zip_data records per-ZIP population, housing, income, business and benefit statistics, while alias, area_code, country and avoid map each ZIP to city names, telephone area codes and counties. The only people are the members of Congress in congress, each linked through zip_congress to the ZIP codes of the district they represent.

| 项 | 内容 |
|---|---|
| 根 | congress（member of Congress） |
| 人物表 | congress（cognress_rep_id；first_name, last_name） |
| 事件 | zip_congress（district zip codes）：zip_congress.district -> congress.cognress_rep_id |
| 属性表 | — |
| 公共表 | zip_data, CBSA, state, country, alias, area_code, avoid |
| 排除 | — |
| 不出 INSERT | congress, state |
| 数据怪异点 | congress.first_name and congress.last_name are swapped: first_name holds the surname ('Young') and last_name holds the given name ('Don').；The key column of congress is misspelled cognress_rep_id.；The House column of congress uses the misspelled value 'House of Repsentatives' for House members and 'Senate' for senators; senators have a null District and ids like 'AK-S1'.；zip_congress.district stores the representative's cognress_rep_id code (e.g. 'NY-1' or 'PR'), not a district number. |

挂在根和事件下面的父行（← 后面是外键列）：

- 根 congress
  - state ← congress.abbreviation
- zip_congress（district zip codes）
  - zip_data ← zip_congress.zip_code
    - CBSA ← zip_data.CBSA
    - state ← zip_data.state

主键：可省 ID：CBSA, alias, zip_data；非整数或复合主键：area_code(zip_code, area_code), avoid(zip_code, bad_alias), congress(cognress_rep_id), country(zip_code, county), state(abbreviation), zip_congress(zip_code, district)

Claude 的改动：
- Claude: roles, edges and every quirk checked against the data; no change

起草：glm-5.3，1 轮

## bird:beer_factory　已确认　校验通过

> A root beer retail tracker: customers buy individual root beer items (a brand in a container sold at a location) recorded as transactions with credit card type and price, and they leave star reviews and comments on brands. Brands carry brewery, ingredient, packaging, social media and pricing details, and selling locations have addresses with coordinates.

| 项 | 内容 |
|---|---|
| 根 | customers（customer） |
| 人物表 | customers（CustomerID；First, Last） |
| 事件 | transaction（transactions）：transaction.CustomerID -> customers.CustomerID；rootbeerreview（reviews）：rootbeerreview.CustomerID -> customers.CustomerID |
| 属性表 | — |
| 公共表 | rootbeerbrand, rootbeer, location, geolocation |
| 排除 | — |
| 不出 INSERT | — |
| 数据怪异点 | location and geolocation mirror each other one-to-one on LocationID; each references the other.；LocationID 0 is a placeholder: location 0 is named 'LOST' with null address fields and geolocation 0 has coordinates (0, 0).；Credit card numbers are stored as plain integers in transaction.CreditCardNumber, not text. |

挂在根和事件下面的父行（← 后面是外键列）：

- transaction（transactions）
  - rootbeer ← transaction.RootBeerID
    - rootbeerbrand ← rootbeer.BrandID
  - location ← transaction.LocationID
- rootbeerreview（reviews）
  - rootbeerbrand ← rootbeerreview.BrandID

主键：可省 ID：customers, geolocation, location, rootbeer, rootbeerbrand, transaction；非整数或复合主键：rootbeerreview(CustomerID, BrandID)

Claude 的改动：
- Claude: transaction parents trimmed to rootbeer -> rootbeerbrand and location -- the coordinates (geolocation) and the root beer's own stock location add two rows per purchase without helping read it

起草：glm-5.3，1 轮

## bird:book_publishing_company　已确认　校验通过

> A book publishing house database: authors write titles that publishers publish, with titleauthor recording each author's order and royalty share on a book and roysched defining royalty tiers per title. Publishers employ staff tracked in employee with job levels from jobs, while stores buy titles through sales orders and discounts on the store side. Requests center on the authors and the books they are credited with.

| 项 | 内容 |
|---|---|
| 根 | authors（author） |
| 人物表 | authors（au_id；au_lname, au_fname）；employee（emp_id；fname, minit, lname） |
| 事件 | titleauthor（book credits）：titleauthor.au_id -> authors.au_id |
| 属性表 | — |
| 公共表 | titles, publishers, pub_info, roysched, jobs |
| 排除 | stores, sales, discounts |
| 不出 INSERT | authors, employee, titles, publishers |
| 数据怪异点 | authors.contract is stored as text: every author has '0'; a contract flag is written as the text '1' or '0'.；employee.minit is an empty string, not NULL, when there is no middle initial.；roysched holds several tier rows per title (lorange/hirange brackets), not one row per title. |

挂在根和事件下面的父行（← 后面是外键列）：

- titleauthor（book credits）
  - titles ← titleauthor.title_id
    - publishers ← titles.pub_id

主键：可省 ID：jobs；非整数或复合主键：authors(au_id), employee(emp_id), pub_info(pub_id), publishers(pub_id), sales(stor_id, ord_num, title_id), stores(stor_id), titleauthor(au_id, title_id), titles(title_id)；无主键：discounts, roysched

Claude 的改动：
- Claude: quirks checked against the data -- contract is '0' for all 23 authors (the draft implied '1' occurs); pub_info.logo is stored as text, not a binary blob, and nobody edits it, so that quirk is dropped

起草：glm-5.3，1 轮

## bird:books　已确认　校验通过

> An online bookstore: customers place orders (cust_order) whose books are recorded one per line in order_line, whose progress is tracked in order_history, and which ship to an address by a shipping method. Customers also keep saved addresses (customer_address) marked active or inactive; books carry a language and publisher and link to authors through book_author.

| 项 | 内容 |
|---|---|
| 根 | customer（customer） |
| 人物表 | customer（customer_id；first_name, last_name） |
| 事件 | cust_order（orders）：cust_order.customer_id -> customer.customer_id；order_line（order lines）：cust_order.customer_id -> customer.customer_id / order_line.order_id -> cust_order.order_id；order_history（order status history）：cust_order.customer_id -> customer.customer_id / order_history.order_id -> cust_order.order_id；customer_address（saved addresses）：customer_address.customer_id -> customer.customer_id |
| 属性表 | — |
| 公共表 | book, book_author, book_language, publisher, address, address_status, country, shipping_method, order_status, author |
| 排除 | — |
| 不出 INSERT | — |
| 数据怪异点 | customer_address.status_id holds address_status.status_id with no declared foreign key; the schema's inferred reference from address_status.status_id to order_status.status_id is bogus — address statuses are Active (1) and Inactive (2), unrelated to order statuses.；order_line has exactly as many rows as cust_order (7550), so each order currently holds exactly one line. |

挂在根和事件下面的父行（← 后面是外键列）：

- cust_order（orders）
  - shipping_method ← cust_order.shipping_method_id
  - address ← cust_order.dest_address_id
    - country ← address.country_id
- order_line（order lines）
  - book ← order_line.book_id
    - book_language ← book.language_id
    - publisher ← book.publisher_id
- order_history（order status history）
  - order_status ← order_history.status_id
- customer_address（saved addresses）
  - address ← customer_address.address_id
    - country ← address.country_id
  - address_status ← customer_address.status_id

主键：可省 ID：address, address_status, author, book, book_language, country, cust_order, customer, order_history, order_line, order_status, publisher, shipping_method；非整数或复合主键：book_author(book_id, author_id), customer_address(customer_id, address_id)

Claude 的改动：
- Claude: author moved from persons to public -- per the hint, authors are catalogue data for a bookstore customer, not people whose rows are private
- Claude: dropped the order_line parent book -> book_author -- written backwards (a book has several authors), so the tree would show one author at random
- Claude: dropped the isbn13 quirk -- 11102 of 11127 values have 13 characters, not 10-11

起草：glm-5.3，2 轮

## bird:car_retails　已确认　校验通过

> A wholesale distributor of classic model cars. Customers are companies, each with a contact person and a sales representative among the employees, who are assigned to offices. Customers place orders whose line items list products (each belonging to a product line) and make payments by check.

| 项 | 内容 |
|---|---|
| 根 | customers（customer） |
| 人物表 | customers（customerNumber；contactFirstName, contactLastName）；employees（employeeNumber；firstName, lastName） |
| 事件 | orders（orders）：orders.customerNumber -> customers.customerNumber；orderdetails（order lines）：orders.customerNumber -> customers.customerNumber / orderdetails.orderNumber -> orders.orderNumber；payments（payments）：payments.customerNumber -> customers.customerNumber |
| 属性表 | — |
| 公共表 | offices, products, productlines |
| 排除 | — |
| 不出 INSERT | products |
| 数据怪异点 | Customers are companies: customerName is the company name, while contactFirstName and contactLastName name the person who speaks for the company.；44 of the 122 contactFirstName values end with a space ('Carine '): copy the value exactly or compare with trim().；payments are keyed by customer-supplied check numbers like 'HQ336336', which follow no sequence. |

挂在根和事件下面的父行（← 后面是外键列）：

- 根 customers
  - employees ← customers.salesRepEmployeeNumber
    - offices ← employees.officeCode
- orderdetails（order lines）
  - products ← orderdetails.productCode
    - productlines ← products.productLine

主键：可省 ID：customers, employees, orders；非整数或复合主键：offices(officeCode), orderdetails(orderNumber, productCode), payments(customerNumber, checkNumber), productlines(productLine), products(productCode)

Claude 的改动：
- Claude: payments removed from no_insert -- the check number comes from the customer, so recording a new payment is a natural request
- Claude: trailing-space quirk made exact (44 of 122 contactFirstName values; checked)

起草：glm-5.3，1 轮

## bird:food_inspection_2　已确认　校验通过

> A municipal food-safety program: health-department employees (sanitarians, supervisors and division managers, each reporting to another employee) inspect licensed establishments such as restaurants and cafeterias. Each visit is an inspection with a type and result, possibly following up an earlier inspection, and each citation is a violation tied to a standard inspection point carrying a fine and the inspector's comment.

| 项 | 内容 |
|---|---|
| 根 | employee（inspector） |
| 人物表 | employee（employee_id；first_name, last_name） |
| 事件 | inspection（inspections）：inspection.employee_id -> employee.employee_id；violation（violations）：inspection.employee_id -> employee.employee_id / violation.inspection_id -> inspection.inspection_id |
| 属性表 | — |
| 公共表 | establishment, inspection_point |
| 排除 | — |
| 不出 INSERT | — |
| 数据怪异点 | inspection.followup_to is null when the inspection is not a follow-up to an earlier one.；inspection_point.point_level is padded with spaces ('Minor   ', 'Serious ', 'Critical'): copy it exactly or compare with trim().；violation.fine is usually, not always (85%), the cited point's standard fine: Critical 500, Serious 250, Minor 100. |

挂在根和事件下面的父行（← 后面是外键列）：

- 根 employee
  - employee ← employee.supervisor
- inspection（inspections）
  - establishment ← inspection.license_no
  - inspection ← inspection.followup_to
- violation（violations）
  - inspection_point ← violation.point_id

主键：可省 ID：employee, establishment, inspection, inspection_point；非整数或复合主键：violation(inspection_id, point_id)

Claude 的改动：
- Claude: fine quirk corrected (85% of violations carry the standard fine, not all) and the space-padded point_level added (checked)

起草：glm-5.3，1 轮

## bird:legislator　已确认　校验通过

> A directory of United States members of Congress. The roots are the historical (no longer serving) legislators: each row of historical is a person, and historical-terms records that legislator's term of office with chamber type, state, district, party, and start and end dates. Currently serving legislators live in the separate current table with their terms in current-terms and their accounts in social-media, but they are different people and their records must not be touched.

| 项 | 内容 |
|---|---|
| 根 | historical（historical legislator） |
| 人物表 | historical（bioguide_id；first_name, last_name）；current（bioguide_id；first_name, last_name） |
| 事件 | historical-terms（terms of office）：historical-terms.bioguide -> historical.bioguide_id |
| 属性表 | — |
| 公共表 | — |
| 排除 | current-terms, social-media |
| 不出 INSERT | historical, current, historical-terms |
| 数据怪异点 | historical-terms has exactly one row per legislator (its key is bioguide alone), so each person has a single term on record.；chamber is null in historical-terms; type tells the chamber: 'sen' for senators, 'rep' for representatives.；class is set only for senators (1, 2 or 3) and district only for representatives.；name, relation, last, title and office in historical-terms are null in almost every row.；historical.fec_id holds a stringified list, e.g. "['S6CO00168']".；current, current-terms and social-media describe different people (sitting legislators, none of them in historical); leave them alone. |

主键：非整数或复合主键：current(bioguide_id, cspan_id), current-terms(bioguide, end), historical(bioguide_id), historical-terms(bioguide), social-media(bioguide)

Claude 的改动：
- Claude: quirks checked; dropped the two about the current table's column types (current is never written), tightened the rest

起草：glm-5.3，3 轮

## bird:movie　已确认　校验通过

> A movie database: each actor has a profile (birthplace, gender, ethnicity, net worth) and is cast in movies through the characters table, which records the character name, credit order, pay and screen time for each role. Movies carry budget, box office gross, MPAA rating, genre, runtime, rating and release date.

| 项 | 内容 |
|---|---|
| 根 | actor（actor） |
| 人物表 | actor（ActorID；Name） |
| 事件 | characters（roles）：characters.ActorID -> actor.ActorID |
| 属性表 | — |
| 公共表 | movie |
| 排除 | — |
| 不出 INSERT | — |
| 数据怪异点 | Column names with spaces or parentheses must be double-quoted: actor."Date of Birth", actor."Birth City", actor."Birth Country", actor."Height (Inches)", characters."Character Name", movie."Release Date", movie."MPAA Rating", movie."Rating Count".；actor.NetWorth and characters.pay are formatted dollar strings like '$250,000,000.00', not numbers.；characters.pay and characters.screentime are null in all but about ten rows.；movie."Release Date" is text in yyyy-mm-dd form. |

挂在根和事件下面的父行（← 后面是外键列）：

- characters（roles）
  - movie ← characters.MovieID

主键：可省 ID：actor, movie；非整数或复合主键：characters(MovieID, ActorID)

Claude 的改动：
- Claude: quirks checked; column quoting now shows double quotes (the draft used single quotes, which SQLite reads as strings); dropped the naming-style remark

起草：glm-5.3，1 轮

## bird:movies_4　已确认　校验通过

> A film catalog modeled on The Movie Database: each movie carries title, budget, revenue, release date, runtime, popularity and vote statistics, and is linked to genres, keywords, languages, production companies and countries. The people are film industry figures in person; movie_cast records the characters they played and movie_crew their departments and jobs.

| 项 | 内容 |
|---|---|
| 根 | person（person (actor or crew member)） |
| 人物表 | person（person_id；person_name） |
| 事件 | movie_cast（cast credits (acting roles)）：movie_cast.person_id -> person.person_id；movie_crew（crew credits）：movie_crew.person_id -> person.person_id |
| 属性表 | — |
| 公共表 | movie, genre, keyword, language, language_role, department, gender, production_company, country, movie_genres, movie_keywords, movie_languages, movie_company, production_country |
| 排除 | — |
| 不出 INSERT | — |
| 数据怪异点 | movie_cast.gender_id is the actor's own gender recorded on the credit; 0 means Unspecified, 1 Female, 2 Male.；movie_status is 'Released' for all but 7 movies ('Post Production', 'Rumored').；language_id values run from 24574 (English) to 24701, not from 1.；A person can have both cast and crew credits, even on the same movie (1076 such person-movie pairs). |

挂在根和事件下面的父行（← 后面是外键列）：

- movie_cast（cast credits (acting roles)）
  - movie ← movie_cast.movie_id
  - gender ← movie_cast.gender_id
- movie_crew（crew credits）
  - movie ← movie_crew.movie_id
  - department ← movie_crew.department_id

主键：可省 ID：country, department, gender, genre, keyword, language, language_role, movie, person, production_company；无主键：movie_cast, movie_company, movie_crew, movie_genres, movie_keywords, movie_languages, production_country

Claude 的改动：
- Claude: quirks checked; movie_status corrected (7 movies are not 'Released'), the others made exact

起草：glm-5.3，1 轮

## bird:olympics　已确认　校验通过

> A history of the modern Olympic Games: each athlete (person) has an entry per edition attended (games_competitor, with their age) and, under it, one row per event entered (competitor_event) recording any medal won. Athletes represent NOC regions through person_region; editions have a year, a season and host cities, and events belong to sports. Everything besides the athletes is reference data: sports, events, medals, cities and regions.

| 项 | 内容 |
|---|---|
| 根 | person（athlete） |
| 人物表 | person（id；full_name） |
| 事件 | games_competitor（games entries）：games_competitor.person_id -> person.id；competitor_event（event entries）：games_competitor.person_id -> person.id / competitor_event.competitor_id -> games_competitor.id；person_region（region links）：person_region.person_id -> person.id |
| 属性表 | — |
| 公共表 | games, sport, event, medal, noc_region, city, games_city |
| 排除 | — |
| 不出 INSERT | — |
| 数据怪异点 | In person, height 0 or weight 0 means unknown, not a real measurement.；medal has a fourth row (id 4, 'NA') meaning no medal; competitor_event.medal_id is 4 whenever the athlete did not win one.；A person can have more than one row in person_region, representing different regions over time.；games_name always equals games_year followed by season (for example '1992 Summer').；The host city of a games edition is reachable only through games_city, a link table (games_id, city_id) with no primary key; an edition may have several host-city rows. |

挂在根和事件下面的父行（← 后面是外键列）：

- games_competitor（games entries）
  - games ← games_competitor.games_id
- competitor_event（event entries）
  - event ← competitor_event.event_id
    - sport ← event.sport_id
  - medal ← competitor_event.medal_id
- person_region（region links）
  - noc_region ← person_region.region_id

主键：可省 ID：city, event, games, games_competitor, medal, noc_region, person, sport；无主键：competitor_event, games_city, person_region

Claude 的改动：
- Claude: roles, edges and every quirk checked against the data; no change

起草：glm-5.3，1 轮

## bird:professional_basketball　已确认　校验通过

> A historical professional basketball database (NBA, ABA and earlier leagues): players are drafted by teams, record season-by-season and playoff statistics with each team (players_teams), appear in all-star games (player_allstar) and win awards (awards_players). Coaches are tracked with one row per team-season stint (coaches) plus their awards (awards_coaches). Teams are tracked per season with wins, losses, scoring and playoff results (teams, series_post).

| 项 | 内容 |
|---|---|
| 根 | players（player） |
| 人物表 | players（playerID；firstName, lastName） |
| 事件 | players_teams（season statistics）：players_teams.playerID -> players.playerID；draft（draft picks）：draft.playerID -> players.playerID；player_allstar（all-star appearances）：player_allstar.playerID -> players.playerID；awards_players（awards）：awards_players.playerID -> players.playerID |
| 属性表 | — |
| 公共表 | teams, series_post |
| 排除 | coaches, awards_coaches |
| 不出 INSERT | players |
| 数据怪异点 | playerID values are text codes built from names, like 'abdulka01', not numbers.；players.firstseason and lastseason are 0 in almost every row; a player's real seasons are the years in players_teams.；players.deathDate '0000-00-00' means the player is alive.；draft.playerID is null for 4958 of 8621 picks (players who never played in the league); such rows belong to no player.；In draft, draftRound or draftSelection 0 means the number is unknown.；draft and player_allstar repeat the player's name next to playerID, and the copy often differs from players (nicknames, spellings).；Null statistics in player_allstar and players_teams mean the stat was not tracked, not zero.；In awards_players, note 'tie' means the award was shared; null means nothing special.；teams has one row per team per season, keyed by (year, tmID), and covers early leagues (ABA, NBL, ABL1, NPBL, PBLA) besides the NBA. |

挂在根和事件下面的父行（← 后面是外键列）：

- players_teams（season statistics）
  - teams ← players_teams.(tmID, year)
- draft（draft picks）
  - teams ← draft.(tmID, draftYear)

主键：可省 ID：awards_coaches, draft, players_teams, series_post；非整数或复合主键：awards_players(playerID, year, award), coaches(coachID, year, tmID, stint), player_allstar(playerID, season_id), players(playerID), teams(year, tmID)

Claude 的改动：
- Claude: removed the second root coaches and its awards_coaches event -- the hint names players only, coachID repeats across a coach's stints and coaches have no name columns, so coaches and awards_coaches are excluded
- Claude: quirks checked; dropped the coach ones, firstseason/lastseason are 0 in 5046 of 5062 rows (not all)

起草：glm-5.3，3 轮，没改掉的问题 1 条

## bird:regional_sales　已确认　校验通过

> A retail sales database: customers place sales orders for products through in-store, online, distributor or wholesale channels, each order handled by a salesperson from Sales Team and tied to a store location with regional context. The people are the customers (companies such as Avon Corp) and the sales staff listed by name in Sales Team.

| 项 | 内容 |
|---|---|
| 根 | Customers（customer） |
| 人物表 | Customers（CustomerID；Customer Names）；Sales Team（SalesTeamID；Sales Team） |
| 事件 | Sales Orders（sales orders）：Sales Orders._CustomerID -> Customers.CustomerID |
| 属性表 | — |
| 公共表 | Products, Store Locations, Regions |
| 排除 | — |
| 不出 INSERT | Sales Orders |
| 数据怪异点 | Table and column names contain spaces ("Sales Orders", "Customer Names", "Sales Team").；The foreign key columns in Sales Orders are prefixed with an underscore: _CustomerID, _ProductID, _StoreID, _SalesTeamID.；Unit Price and Unit Cost are stored as TEXT with comma thousands separators, e.g. "1,963.10".；Dates in Sales Orders are TEXT in month/day/two-digit-year form, e.g. "5/31/18"; "17" means 2017.；Each Sales Team row is a single named salesperson (e.g. "Adam Hernandez"), not a group of people.；13 of the 50 "Customer Names" values end with a space ("WakeFern "): copy the value exactly or compare with trim(). |

挂在根和事件下面的父行（← 后面是外键列）：

- Sales Orders（sales orders）
  - Products ← Sales Orders._ProductID
  - Store Locations ← Sales Orders._StoreID
    - Regions ← Store Locations.StateCode
  - Sales Team ← Sales Orders._SalesTeamID

主键：可省 ID：Customers, Products, Sales Team, Store Locations；非整数或复合主键：Regions(StateCode), Sales Orders(OrderNumber)

Claude 的改动：
- Claude: quirks checked; trailing-space quirk made exact (13 of 50)

起草：glm-5.3，1 轮

## bird:retail_complains　已确认　校验通过

> A consumer-complaint call center: clients (customers) lodge complaints by phone, each call logged in callcenterlogs with priority, type, outcome and server handling times, while events records the substance of each complaint (product, issue, narrative, channel) and the company's response. Clients live in districts grouped by state, and reviews logs daily product star ratings per district.

| 项 | 内容 |
|---|---|
| 根 | client（customer） |
| 人物表 | client（client_id；first, middle, last） |
| 事件 | callcenterlogs（complaint calls）：callcenterlogs.rand client -> client.client_id；events（complaint records）：events.Client_ID -> client.client_id |
| 属性表 | — |
| 公共表 | district, state, reviews |
| 排除 | — |
| 不出 INSERT | client, callcenterlogs, events |
| 数据怪异点 | Many column names contain spaces or special characters ('Complaint ID', 'rand client', 'vru+line', 'Date received', 'Consumer consent provided?', 'Timely response?', 'Consumer disputed?') and must be double-quoted in SQL.；'rand client' in callcenterlogs is a foreign key to client.client_id despite the space in its name.；The client table stores the birth date as three separate columns day, month, year instead of one date column.；Complaint ID appears in both callcenterlogs and events, but no foreign key links the two tables, so a call and a complaint record are only loosely associated.；callcenterlogs.priority is 0, 1, 2 or null, with higher meaning more urgent.；The server column in callcenterlogs holds call-center agents' first names (e.g. MICHAL, TOVA), not ids. |

挂在根和事件下面的父行（← 后面是外键列）：

- 根 client
  - district ← client.district_id
    - state ← district.state_abbrev

主键：可省 ID：district；非整数或复合主键：callcenterlogs(Complaint ID), client(client_id), events(Complaint ID, Client_ID), reviews(Date), state(StateCode)

Claude 的改动：
- Claude: roles, edges and every quirk checked against the data; no change

起草：glm-5.3，1 轮

## bird:shipping　已确认　校验通过

> A freight delivery operation: business customers (manufacturers, wholesalers, retailers) send shipments of goods by weight to destination cities, each shipment recording the truck and driver used. Customers are the roots of requests; drivers are the other people in the data, and trucks and cities are reference data.

| 项 | 内容 |
|---|---|
| 根 | customer（customer） |
| 人物表 | customer（cust_id；cust_name）；driver（driver_id；first_name, last_name） |
| 事件 | shipment（shipments）：shipment.cust_id -> customer.cust_id |
| 属性表 | — |
| 公共表 | truck, city |
| 排除 | — |
| 不出 INSERT | — |
| 数据怪异点 | customer.city and customer.state hold plain names, not keys into the city table.；customer.zip is stored as a number (e.g. 33415.0).；cust_type includes values like 'retailer' beyond the documented 'manufacturer' and 'wholesaler'. |

挂在根和事件下面的父行（← 后面是外键列）：

- shipment（shipments）
  - driver ← shipment.driver_id
  - truck ← shipment.truck_id
  - city ← shipment.city_id

主键：可省 ID：city, customer, driver, shipment, truck

Claude 的改动：
- Claude: dropped the model_year quirk -- it repeats a BIRD column note, not something in the data, and does not matter for writing SQL

起草：glm-5.3，1 轮

## bird:student_club　已确认　校验通过

> A student club's administrative system: members (each with a club position, academic major and hometown ZIP code) attend events, incur expenses charged against per-event per-category budgets, and pay dues that are recorded as income. Events belong to the club rather than to any member, and each budget's spent and remaining figures summarize the expenses linked to it.

| 项 | 内容 |
|---|---|
| 根 | member（club member） |
| 人物表 | member（member_id；first_name, last_name） |
| 事件 | attendance（attendance records）：attendance.link_to_member -> member.member_id；expense（expenses）：expense.link_to_member -> member.member_id；income（income records (e.g. dues paid)）：income.link_to_member -> member.member_id |
| 属性表 | — |
| 公共表 | event, budget, major, zip_code |
| 排除 | — |
| 不出 INSERT | member, event, budget, expense, income, major |
| 数据怪异点 | All id columns hold Airtable-style text codes like 'rec1x5zBFIqoOuPW8'; there is no meaningful next value for a new row.；expense.approved holds the text 'true' (one row is null); write 'true' or 'false' as text, not 1/0.；budget.remaining equals amount minus spent and may be negative or show floating-point noise such as -0.199999999999999.；budget.event_status duplicates the status of the linked event row.；Dates are stored as text: event.event_date like '2020-03-10T12:00:00', expense.expense_date and income.date_received as 'YYYY-MM-DD'. |

挂在根和事件下面的父行（← 后面是外键列）：

- 根 member
  - major ← member.link_to_major
  - zip_code ← member.zip
- attendance（attendance records）
  - event ← attendance.link_to_event
- expense（expenses）
  - budget ← expense.link_to_budget
    - event ← budget.link_to_event

主键：可省 ID：zip_code；非整数或复合主键：attendance(link_to_event, link_to_member), budget(budget_id), event(event_id), expense(expense_id), income(income_id), major(major_id), member(member_id)

Claude 的改动：
- Claude: quirks checked; approved holds only 'true' and one null (no 'false' yet)

起草：glm-5.3，1 轮

## bird:student_loan　已确认　校验通过

> A student loan database of 1000 students identified by codes like 'student123'. One-to-one tables record each student's circumstances (disabled, unemployed, male, filed for bankruptcy, longest absence, payment due), while enlist records organizations a student enlisted in and enrolled records the school and month of enrollment.

| 项 | 内容 |
|---|---|
| 根 | person（student） |
| 人物表 | person（name；name） |
| 事件 | enlist（enlistments）：enlist.name -> person.name；enrolled（enrollments）：enrolled.name -> person.name |
| 属性表 | disabled → person；filed_for_bankrupcy → person；male → person；unemployed → person；longest_absense_from_school → person；no_payment_due → person |
| 公共表 | — |
| 排除 | bool |
| 不出 INSERT | — |
| 数据怪异点 | Students are identified by codes like 'student123' stored in a name column, not by real names or numeric ids.；filed_for_bankrupcy and longest_absense_from_school are misspelled in the schema; always use those exact table names.；In longest_absense_from_school, month 0 means the student has never been absent.；Only male students appear in male; a student missing from that table is female, so 'changing gender' means adding or removing the row.；In no_payment_due, bool 'neg' means the student has no payment due and 'pos' means the student has payment due; those are the only two values.；enlist.organ and enrolled.school hold text codes like 'fire_department' and 'ucb' with no reference table. |

主键：非整数或复合主键：bool(name), disabled(name), enrolled(name, school), filed_for_bankrupcy(name), longest_absense_from_school(name), male(name), no_payment_due(name), person(name), unemployed(name)；无主键：enlist

Claude 的改动：
- Claude: roles, edges and every quirk checked against the data; no change

起草：glm-5.3，1 轮

## bird:superhero　已确认　校验通过

> A catalog of comic-book superheroes: each hero has a hero name, full name, physical traits (gender, eye/hair/skin colour, race, height, weight) plus a publisher and moral alignment, all described via small lookup tables. hero_attribute rates each hero on traits like intelligence and strength, and hero_power records which superpowers the hero has.

| 项 | 内容 |
|---|---|
| 根 | superhero（superhero） |
| 人物表 | superhero（id；superhero_name, full_name） |
| 事件 | hero_attribute（attribute ratings）：hero_attribute.hero_id -> superhero.id；hero_power（powers）：hero_power.hero_id -> superhero.id |
| 属性表 | — |
| 公共表 | alignment, attribute, colour, gender, publisher, race, superpower |
| 排除 | — |
| 不出 INSERT | — |
| 数据怪异点 | hero_attribute and hero_power have no primary key; a hero has at most one row per attribute_id and at most one row per power_id.；publisher id 1 has an empty publisher_name, race id 1 is '-' and colour id 1 is 'No Colour'; these are placeholders for an unknown value.；height_cm and weight_kg of NULL or 0 mean the hero's height or weight is unknown, not that they are actually zero. |

挂在根和事件下面的父行（← 后面是外键列）：

- 根 superhero
  - gender ← superhero.gender_id
  - colour ← superhero.eye_colour_id
  - colour ← superhero.hair_colour_id
  - colour ← superhero.skin_colour_id
  - race ← superhero.race_id
  - publisher ← superhero.publisher_id
  - alignment ← superhero.alignment_id
- hero_attribute（attribute ratings）
  - attribute ← hero_attribute.attribute_id
- hero_power（powers）
  - superpower ← hero_power.power_id

主键：可省 ID：alignment, attribute, colour, gender, publisher, race, superhero, superpower；无主键：hero_attribute, hero_power

Claude 的改动：
- Claude: roles, edges and every quirk checked against the data; no change

起草：glm-5.3，1 轮

## bird:synthea　已确认　校验通过

> A synthetic electronic health record system: each patient's identity and demographics live in patients, and their medical history is a series of encounters, each of which can carry allergies, care plans, conditions, immunizations, medications, observations, procedures and claims. Claims reference only the patient. all_prevalences is reference data on how common each disease is in the living population.

| 项 | 内容 |
|---|---|
| 根 | patients（patient） |
| 人物表 | patients（patient；first, last；same_as claims.ENCOUNTER） |
| 事件 | encounters（encounters）：encounters.PATIENT -> patients.patient；allergies（allergies）：allergies.PATIENT -> patients.patient；careplans（care plans）：careplans.PATIENT -> patients.patient；claims（claims）：claims.PATIENT -> patients.patient；conditions（conditions (diagnoses)）：conditions.PATIENT -> patients.patient；immunizations（immunizations）：immunizations.PATIENT -> patients.patient；medications（medications）：medications.PATIENT -> patients.patient；observations（observations）：observations.PATIENT -> patients.patient；procedures（procedures）：procedures.PATIENT -> patients.patient |
| 属性表 | — |
| 公共表 | all_prevalences |
| 排除 | — |
| 不出 INSERT | patients, encounters, claims, careplans |
| 数据怪异点 | In claims, the ENCOUNTER column holds the patient's id rather than an encounter id; it always matches claims.PATIENT.；allergies START and STOP are text dates in m/d/yy format (e.g. 3/11/95), unlike the yyyy-mm-dd dates used everywhere else.；patients.passport holds the string 'FALSE' (564 patients) or null (339) when a patient has no passport.；careplans.CODE is stored as a REAL number (e.g. 53950000.0) while code columns in the other clinical tables are integers. |

挂在根和事件下面的父行（← 后面是外键列）：

- allergies（allergies）
  - encounters ← allergies.ENCOUNTER
- careplans（care plans）
  - encounters ← careplans.ENCOUNTER
- conditions（conditions (diagnoses)）
  - encounters ← conditions.ENCOUNTER
- immunizations（immunizations）
  - encounters ← immunizations.ENCOUNTER
- medications（medications）
  - encounters ← medications.ENCOUNTER
- observations（observations）
  - encounters ← observations.ENCOUNTER
- procedures（procedures）
  - encounters ← procedures.ENCOUNTER

主键：非整数或复合主键：all_prevalences(ITEM), allergies(PATIENT, ENCOUNTER, CODE), claims(ID), encounters(ID), immunizations(DATE, PATIENT, ENCOUNTER, CODE), medications(START, PATIENT, ENCOUNTER, CODE), patients(patient)；无主键：careplans, conditions, observations, procedures

Claude 的改动：
- Claude: quirks checked; passport is 'FALSE' or null for patients without one

起草：glm-5.3，1 轮

## spider1:college_2　已确认　校验通过

> A university database: students and instructors each belong to a department, and advisor links every student to a supervising instructor. Courses are offered as sections in a semester, classroom and time slot; teaches records the instructor leading each section and takes records each student's enrollment and grade, with prereq holding course prerequisites.

| 项 | 内容 |
|---|---|
| 根 | student（student）；instructor（instructor） |
| 人物表 | student（ID；name）；instructor（ID；name） |
| 事件 | takes（enrollments）：takes.ID -> student.ID；advisor（advisor assignment）：advisor.s_ID -> student.ID；teaches（sections taught）：teaches.ID -> instructor.ID；advisor（advisees）：advisor.i_ID -> instructor.ID |
| 属性表 | — |
| 公共表 | course, section, prereq, department, classroom, time_slot |
| 排除 | — |
| 不出 INSERT | — |
| 数据怪异点 | section, teaches and takes all share the composite key (course_id, sec_id, semester, year); a new takes or teaches row must copy the values of an existing section row.；IDs in student, instructor and course are plain digit strings (e.g. '24746', '787'), and sec_id holds plain digits like '1'. |

挂在根和事件下面的父行（← 后面是外键列）：

- 根 student
  - department ← student.dept_name
- 根 instructor
  - department ← instructor.dept_name
- takes（enrollments）
  - section ← takes.(course_id, sec_id, semester, year)
    - course ← section.course_id
- advisor（advisor assignment）
  - instructor ← advisor.i_ID
- teaches（sections taught）
  - section ← teaches.(course_id, sec_id, semester, year)
    - course ← section.course_id
- advisor（advisees）
  - student ← advisor.s_ID

主键：非整数或复合主键：advisor(s_ID), classroom(building, room_number), course(course_id), department(dept_name), instructor(ID), prereq(course_id, prereq_id), section(course_id, sec_id, semester, year), student(ID), takes(ID, course_id, sec_id, semester, year), teaches(ID, course_id, sec_id, semester, year), time_slot(time_slot_id, day, start_hr, start_min)

Claude 的改动：
- Claude: event parents trimmed to section -> course for takes and teaches and to the other person for advisor -- a student has about 15 enrolments, and classroom, time slot and departments added four rows to each; section -> time_slot also led to several rows (one per day)

起草：glm-5.3，1 轮

## spider1:hr_1　已确认　校验通过

> A human resources database: employees hold jobs, report to managers, and belong to departments at office locations in countries grouped by region. Each employee's past assignments are logged in job_history with the job and department held over a start-to-end date range.

| 项 | 内容 |
|---|---|
| 根 | employees（employee） |
| 人物表 | employees（EMPLOYEE_ID；FIRST_NAME, LAST_NAME） |
| 事件 | job_history（job history entries）：job_history.EMPLOYEE_ID -> employees.EMPLOYEE_ID |
| 属性表 | — |
| 公共表 | jobs, departments, locations, countries, regions |
| 排除 | — |
| 不出 INSERT | jobs, countries |
| 数据怪异点 | No key is assigned automatically: every key is a DECIMAL or a varchar code, so a new row needs an explicit id.；employees.MANAGER_ID 0 (on employee 100, the president) means 'no manager' and matches no employee row.；regions.REGION_NAME values end with the two characters \r (a backslash and r), e.g. 'Europe\r'.；Only 7 of the 107 employees have job_history rows. |

挂在根和事件下面的父行（← 后面是外键列）：

- 根 employees
  - employees ← employees.MANAGER_ID
  - jobs ← employees.JOB_ID
  - departments ← employees.DEPARTMENT_ID
    - locations ← departments.LOCATION_ID
- job_history（job history entries）
  - jobs ← job_history.JOB_ID
  - departments ← job_history.DEPARTMENT_ID

主键：非整数或复合主键：countries(COUNTRY_ID), departments(DEPARTMENT_ID), employees(EMPLOYEE_ID), job_history(EMPLOYEE_ID, START_DATE), jobs(JOB_ID), locations(LOCATION_ID), regions(REGION_ID)

Claude 的改动：
- Claude: removed same_as employees.MANAGER_ID and departments.MANAGER_ID -- same_as is for the same person's id in another table; these columns name a manager, and as ownership edges they would make every department the manager's private data
- Claude: root parents end at departments -> locations and job_history parents at jobs and departments -- countries and regions add rows without helping
- Claude: quirks checked: REGION_NAME ends with a literal backslash and r, not a carriage return; dropped the unverifiable claim that job_history rows predate the current job

起草：glm-5.3，1 轮

## spider2:IPL　已确认　校验通过

> An Indian Premier League (Twenty20 cricket) results database over many seasons: each match between two teams records venue, toss and result, every delivery sits in ball_by_ball, and the runs, extras and wickets off each ball live in separate tables sharing the ball's key. The people are the cricketers in player, linked to the matches they played with a role and team in player_match, and appearing throughout the ball data as striker, non-striker, bowler, dismissed player and man of the match.

| 项 | 内容 |
|---|---|
| 根 | player（cricketer） |
| 人物表 | player（player_id；player_name） |
| 事件 | player_match（match appearances）：player_match.player_id -> player.player_id；ball_by_ball（balls faced (striker)）：ball_by_ball.striker -> player.player_id；ball_by_ball（balls bowled）：ball_by_ball.bowler -> player.player_id；batsman_scored（runs scored off the bat）：ball_by_ball.striker -> player.player_id / batsman_scored.(match_id, over_id, ball_id, innings_no) -> ball_by_ball.(match_id, over_id, ball_id, innings_no)；extra_runs（extras on balls they bowled）：ball_by_ball.bowler -> player.player_id / extra_runs.(match_id, over_id, ball_id, innings_no) -> ball_by_ball.(match_id, over_id, ball_id, innings_no)；wicket_taken（dismissals (the player out)）：wicket_taken.player_out -> player.player_id |
| 属性表 | — |
| 公共表 | team, match |
| 排除 | — |
| 不出 INSERT | — |
| 数据怪异点 | batsman_scored, extra_runs and wicket_taken have no declared foreign key to ball_by_ball; they join on the shared columns (match_id, over_id, ball_id, innings_no).；ball_by_ball.striker, ball_by_ball.non_striker, ball_by_ball.bowler, wicket_taken.player_out and match.man_of_the_match hold player_id values without declared foreign keys.；match.team_1, match.team_2, match.toss_winner, match.match_winner, ball_by_ball.team_batting and ball_by_ball.team_bowling hold team_id values without declared foreign keys.；There is no season table; match.season_id is just a season number. |

挂在根和事件下面的父行（← 后面是外键列）：

- player_match（match appearances）
  - match ← player_match.match_id
  - team ← player_match.team_id
- ball_by_ball（balls faced (striker)）
  - match ← ball_by_ball.match_id
- ball_by_ball（balls bowled）
  - match ← ball_by_ball.match_id
- batsman_scored（runs scored off the bat）
  - match ← batsman_scored.match_id
- extra_runs（extras on balls they bowled）
  - match ← extra_runs.match_id
- wicket_taken（dismissals (the player out)）
  - match ← wicket_taken.match_id
  - ball_by_ball ← wicket_taken.(match_id, over_id, ball_id, innings_no)

主键：可省 ID：match, player, team；非整数或复合主键：ball_by_ball(match_id, over_id, ball_id, innings_no), batsman_scored(match_id, over_id, ball_id, innings_no), extra_runs(match_id, over_id, ball_id, innings_no), player_match(match_id, player_id), wicket_taken(match_id, over_id, ball_id, innings_no)

Claude 的改动：
- Claude: removed same_as -- striker, non_striker, bowler and player_out are references already in the recorded foreign keys, and match.man_of_the_match as an identity column would make every match the man of the match's private data
- Claude: dropped the non-striker event group and trimmed parents to the match (plus the player's team and the dismissal ball) -- a player has hundreds of ball rows per role and team rows under each added little

起草：glm-5.3，1 轮

## spider2:WWE　已确认　校验通过

> A professional-wrestling results database assembled by scraping profightdb.com. Cards record each event card (date, promotion, location and event name), and Matches record each individual bout with its winner, loser, win type, match type, duration and the championship belt at stake. The only people are the wrestlers, who appear in Matches as the winner and the loser.

| 项 | 内容 |
|---|---|
| 根 | Wrestlers（wrestler） |
| 人物表 | Wrestlers（id；name） |
| 事件 | Matches（matches won）：Matches.winner_id -> Wrestlers.id；Matches（matches lost）：Matches.loser_id -> Wrestlers.id |
| 属性表 | — |
| 公共表 | Cards, Events, Locations, Promotions, Match_Types, Belts |
| 排除 | Tables |
| 不出 INSERT | — |
| 数据怪异点 | Matches.winner_id, loser_id, match_type_id and title_id are TEXT columns holding integer ids as strings; compare them as text.；Wrestlers.name, Belts.name, Events.name, Locations.name, Promotions.name and Match_Types.name are UNIQUE.；sqlite_sequence is ahead of MAX(id) in Belts, Cards, Events, Locations, Match_Types, Promotions, Tables and Wrestlers, so a new row in any of those tables needs an explicit id.；Belts id 1 and Match_Types id 1 have empty names and act as 'no title' / 'no special type' placeholders referenced by most Matches.；Cards.url, Cards.info_html, Cards.match_html and Tables.html are scraped web artifacts, not data a request should rewrite. |

挂在根和事件下面的父行（← 后面是外键列）：

- Matches（matches won）
  - Wrestlers ← Matches.loser_id
  - Cards ← Matches.card_id
    - Events ← Cards.event_id
  - Match_Types ← Matches.match_type_id
  - Belts ← Matches.title_id
- Matches（matches lost）
  - Wrestlers ← Matches.winner_id
  - Cards ← Matches.card_id
    - Events ← Cards.event_id
  - Match_Types ← Matches.match_type_id
  - Belts ← Matches.title_id

主键：可省 ID：Matches；ID 须用户给出：Belts, Cards, Events, Locations, Match_Types, Promotions, Tables, Wrestlers

Claude 的改动：
- Claude: removed same_as Matches.winner_id -- it repeats the 'matches won' path, and same_as is for identity columns, not references
- Claude: Cards parents trimmed to Events -- each card row already carries cut-down HTML, Locations and Promotions added two more rows per match

起草：glm-5.3，1 轮

## spider2:school_scheduling　已确认　校验通过

> A university course scheduling and academic records database: students, each with a major, enroll in class sections (Classes) through Student_Schedules records carrying an enrollment status and grade, while staff members teach those sections via Faculty_Classes and hold subject proficiencies and teaching categories. Classes meet in classrooms grouped by building and teach subjects grouped into categories and departments; some staff carry a Faculty profile (title, status, tenure) sharing the same StaffID, and one staff member chairs each department.

| 项 | 内容 |
|---|---|
| 根 | Students（student）；Staff（staff member） |
| 人物表 | Students（StudentID；StudFirstName, StudLastName）；Staff（StaffID；StfFirstName, StfLastname） |
| 事件 | Student_Schedules（class enrollments）：Student_Schedules.StudentID -> Students.StudentID；Faculty_Classes（classes taught）：Faculty_Classes.StaffID -> Staff.StaffID；Faculty_Subjects（subject proficiencies）：Faculty.StaffID -> Staff.StaffID / Faculty_Subjects.StaffID -> Faculty.StaffID；Faculty_Categories（teaching categories）：Faculty.StaffID -> Staff.StaffID / Faculty_Categories.StaffID -> Faculty.StaffID |
| 属性表 | Faculty → Staff |
| 公共表 | Classes, Subjects, Categories, Departments, Class_Rooms, Buildings, Majors, Student_Class_Status |
| 排除 | — |
| 不出 INSERT | — |
| 数据怪异点 | Staff's last-name column is StfLastname (lowercase n), while Students uses StudLastName.；Subjects.SubjectPreReq stores another subject's SubjectCode (e.g. 'ACC 210'), not a SubjectID; it is null when there is no prerequisite.；Faculty is the teaching profile of a Staff member and reuses Staff.StaffID; only 24 of the 27 staff members are faculty.；Departments.DeptChair holds the StaffID of the staff member who chairs the department.；Grades in Student_Schedules and StudGPA in Students are on a 0-100 scale, not 0-4. |

挂在根和事件下面的父行（← 后面是外键列）：

- 根 Students
  - Majors ← Students.StudMajor
- Student_Schedules（class enrollments）
  - Classes ← Student_Schedules.ClassID
    - Subjects ← Classes.SubjectID
  - Student_Class_Status ← Student_Schedules.ClassStatus
- Faculty_Classes（classes taught）
  - Classes ← Faculty_Classes.ClassID
    - Subjects ← Classes.SubjectID
- Faculty_Subjects（subject proficiencies）
  - Subjects ← Faculty_Subjects.SubjectID
- Faculty_Categories（teaching categories）
  - Categories ← Faculty_Categories.CategoryID

主键：可省 ID：Class_Rooms, Classes, Departments, Faculty, Majors, Staff, Student_Class_Status, Students, Subjects；非整数或复合主键：Buildings(BuildingCode), Categories(CategoryID), Faculty_Categories(StaffID, CategoryID), Faculty_Classes(ClassID, StaffID), Faculty_Subjects(StaffID, SubjectID), Student_Schedules(StudentID, ClassID)

Claude 的改动：
- Claude: event parents trimmed to class -> subject (plus the enrolment status) -- category, classroom, building and department added up to four rows per record
- Claude: quirks checked against the data; no change

起草：glm-5.3，1 轮

