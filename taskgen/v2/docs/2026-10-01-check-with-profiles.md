# 执行检查：不用档案 vs 用档案

`scripts/check_diff.py --profiles` 生成：同一批候选分别跑 v2 的 `check.run_check_safe`，不带档案和带确认过的档案，逐条比较；只比说话人是档案根的候选。只列候选 id，不摘录题目内容。

## 候选：../v1/results（3490 条）

| 不用档案 | 用档案 | 条数 |
|---|---|---|
| 通过 | 通过 | 2902 |
| 通过 | 拒绝 | 321 |
| 拒绝 | 通过 | 0 |
| 拒绝 | 拒绝 | 267 |

### 判决变化

- 仍拒绝、原因变了：literal_missing → literal_missing+no_insert+other_person（1）：bird:synthea:patients:459b6c2c-16ca-44e9-a232-6369b4a3daa7:0
- 仍拒绝、原因变了：literal_missing → literal_missing+other_person（2）：spider2:WWE:Wrestlers:29826:0, bird:professional_basketball:players:leonaka01:0
- 仍拒绝、原因变了：noop_write → no_insert+noop_write（2）：bird:address:congress:CA-16:0, bird:legislator:historical:F000310:0
- 仍拒绝、原因变了：noop_write → no_insert+noop_write+other_person（1）：bird:synthea:patients:ae669b65-6f20-4731-a77f-c871b36f2ce4:0
- 仍拒绝、原因变了：noop_write → noop_write+other_person（3）：bird:beer_factory:customers:719921:0, bird:professional_basketball:players:jordoph01:0, bird:superhero:superhero:53:0
- 仍拒绝、原因变了：out_of_scope → no_insert+out_of_scope（1）：bird:legislator:historical:F000403:0
- 仍拒绝、原因变了：sql_error → no_insert+sql_error（1）：bird:address:congress:GA-10:0
- 仍拒绝、原因变了：sql_error → other_person+sql_error（19）：spider2:IPL:player:230:0, spider2:IPL:player:295:0, bird:address:congress:AZ-5:0, bird:beer_factory:customers:238347:0, bird:beer_factory:customers:205190:0, spider1:college_2:student:56232:0, spider1:college_2:student:30164:0, spider1:college_2:student:99660:0, spider1:college_2:student:22086:0, bird:legislator:historical:C000094:0 …
- 仍拒绝、原因变了：sql_error → out_of_scope+sql_error（4）：bird:student_loan:person:student921:0, bird:student_loan:person:student894:0, bird:student_loan:person:student642:0, bird:student_loan:person:student778:0
- 通过 → 拒绝：no_insert（65）：bird:book_publishing_company:authors:672-71-3249:0, bird:legislator:historical:S000764:0, bird:legislator:historical:S000038:0, bird:legislator:historical:S000330:0, bird:legislator:historical:M000104:0, bird:legislator:historical:S000663:0, bird:legislator:historical:D000016:0, bird:legislator:historical:V000126:0, bird:legislator:historical:B000323:0, bird:legislator:historical:S000147:0 …
- 通过 → 拒绝：no_insert+other_person（17）：bird:regional_sales:Customers:30:0, bird:retail_complains:client:C00003924:0, bird:retail_complains:client:C00001472:0, bird:retail_complains:client:C00003306:0, bird:retail_complains:client:C00004794:0, bird:retail_complains:client:C00001970:0, bird:retail_complains:client:C00009997:0, bird:retail_complains:client:C00004483:0, bird:retail_complains:client:C00002540:0, bird:retail_complains:client:C00003161:0 …
- 通过 → 拒绝：other_person（239）：spider2:IPL:player:224:0, spider2:IPL:player:452:0, spider2:IPL:player:253:0, spider2:IPL:player:302:0, spider2:IPL:player:98:0, spider2:IPL:player:2:0, spider2:IPL:player:26:0, spider2:IPL:player:373:0, spider2:IPL:player:86:0, spider2:IPL:player:459:0 …

### 类型变化（两边都算出了类型的）

- 4_other_person → 1_self：2
- 3_public_only → 4_other_person：2
- 3_public_only → 1_self：1
- 2_self_and_public → 1_self：1
- 4_other_person → 2_self_and_public：1
- 2_self_and_public → 4_other_person：1
- 1_self → 3_public_only：1
- 1_self → 2_self_and_public：1

## 结论

Claude 手写。数字来自对同一批结果的拆分：按库、按原因统计，并把两边算出的类型不同的候选逐条追溯过。只列计数和候选 id。

**比较范围。** v1 的 4159 条候选里，说话人是档案根的有 3490 条；另外 669 条的说话人在 6 个副锚点上，不比。不用档案时通过 3223 条，用档案时通过 2902 条。没有一条是"原来拒绝、现在通过"。

**通过 → 拒绝的 321 条，全部归到两条新规则：**
- **`other_person`：239 条。**
  - 其中 236 条不用档案时就算出第 4 类（改别人的数据）。v1 允许第 4 类；按 D6，带档案的检查把它拒掉。
  - 这一类分布很散。最多的是 college_2（37 条），其次是 movies_4（17 条），address、car_retails、olympics 各 16 条。例：`spider2:IPL:player:224:0`。
  - 另外 3 条是档案改了人物表：
    - regional_sales 的 Sales Team 在档案里算人物表（销售代表），改它就是改别人的数据：`bird:regional_sales:Customers:19:0`、`bird:regional_sales:Customers:20:0`。
    - professional_basketball 的 draft 在档案里不再算人物表，往里插别的球员的选秀记录，就算别人的数据：`bird:professional_basketball:players:snydeki01:0`。
- **`no_insert`：65 条；和 `other_person` 同时出现的另有 17 条。**
  - 这些候选往文本主键表里 INSERT。按库分：legislator 25 条，retail_complains 23 条，synthea 21 条，regional_sales 7 条，student_club 5 条，book_publishing_company 1 条。
  - 涉及的表（一条候选可能涉及两张）：
    - legislator：historical-terms 22 条，historical 3 条；
    - retail_complains：events 14 条，callcenterlogs 11 条；
    - synthea：careplans、encounters 各 8 条，claims 6 条；
    - regional_sales：Sales Orders 7 条；
    - student_club：income 3 条，member、expense 各 1 条；
    - book_publishing_company：authors 1 条。
  - 例：`bird:legislator:historical:S000764:0`、`bird:retail_complains:client:C00003924:0`。

**仍然拒绝、但多了原因的 34 条。** 多出来的原因同样只有三种，其中 2 条同时多了两种：
- `other_person`：26 条；
- `no_insert`：6 条；
- `out_of_scope`：4 条，都是 student_loan 写了档案排除的 `bool` 表，例 `bird:student_loan:person:student921:0`。

**两边都算出类型、但类型不同的 10 条。** 都是档案改变了追溯的结果，逐条查过：
- **档案补上了 v1 推断外键漏掉的边（5 条）。**
  - WWE：v1 只推断出 `Matches.loser_id → Wrestlers`，漏了 `winner_id`。所以说话人赢的比赛只追溯到败者，被算成别人的；档案里两条路径都有，现在算本人的。候选：`spider2:WWE:Wrestlers:2383:0`、`spider2:WWE:Wrestlers:8902:0`、`spider2:WWE:Wrestlers:106382:0`。
  - IPL：插入的 wicket_taken 经档案的复合边通到那一球的 ball_by_ball 行，再追溯到说话人。这两条 INSERT 的 `player_out` 子查询用了库里没有的名字，取出来是 NULL。候选：`spider2:IPL:player:87:0`、`spider2:IPL:player:165:0`。
- **档案的人物表不同（3 条）。** 就是上面 `other_person` 里的 regional_sales 2 条和 professional_basketball 1 条。
- **公共行不属于任何人（2 条）。** school_scheduling 的 Departments、Categories 原来经系主任追溯成本人的数据，现在算公共的：`spider2:school_scheduling:Staff:98010:0`、`spider2:school_scheduling:Staff:98005:0`。

**对产量意味着什么。**
- 在 v1 的这批候选上，带档案的检查让通过率从 92.3% 降到 83.2%，少了 9.2 个百分点：
  - 牵涉 `other_person` 的 256 条，占 7.3%；
  - 牵涉 `no_insert` 的 82 条，占 2.3%。
- v2 出题不再要第 4 类，prompt 里也把别人的数据标了出来，所以 `other_person` 在 v2 候选里应当少见。冒烟结果见 `2026-10-01-profiles-and-trees.md`。
- `no_insert` 不一样：prompt 还没告诉模型哪些表不能新增。设计 §4.1 说这些表只出 UPDATE/DELETE，但计划 2 只做了检查这一侧。
  - 在 v1 里，这一类集中在 legislator（25/200）、retail_complains（23/200）、synthea（21/200）。
  - 这留给计划 3：在 prompt 里列出不出 INSERT 的表，或者抽题时避开。
