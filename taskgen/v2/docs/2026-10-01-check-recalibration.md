# 执行检查重新校准：v1 vs v2

`scripts/check_diff.py` 生成：同一批候选分别跑 v1（tag `taskgen-v1`，冻结）和 v2 的 `check.run_check_safe`，逐条比较。只列候选 id，不摘录题目内容。

## 结论

- **通过数：** DySQL 金标准 908 → 895；v1 候选 3816 → 3872。
- **每组变化都归到了一处改动，没有解释不了的：**
  - DySQL 通过 → 拒绝 13 条。nondeterministic 3 条：pagila 把 `CURRENT_TIMESTAMP` 写进 return_date、payment_date（Task 5）。literal_missing 10 条，都来自整词匹配（Task 3）：1 条是真错（写 250，instruction 里是 2503）；5 条以前靠子串巧合放行（`'2'` 落在 `120` 里，`'No'` 落在 `non-optional` 里，`'F'` 落在 `office` 里）；4 条是词形误杀（复数 `cups`、`pieces`，单位紧跟数字 `20ml`，列表编号粘连 `accountant2.`）。
  - v1 候选拒绝 → 通过 61 条：原本缺失的 69 个字面量里，63 个是 SQLite 会自动分配的新主键，4 个是后面语句引用这些新行，2 个是序数词（Task 4、Task 3）。通过 → 拒绝 5 条，都是以前靠子串巧合放行的（`'2'`、`'3'` 落在说话人编号 `234` 里，`'DET'`、`'TOR'` 落在队名里）。
  - 类型变化全部来自 `new_person`（Task 6）：v1 候选 72 条（其中 48 条两边都通过），DySQL 5 条。计划里估计 DySQL 约 30 条是错的：check 规则算出的 186 条第 4 类里，180 条根本没往人物表插行。
- **跟进：** 词形误杀在 v1 的 23 个库上一条也没出现，暂不放宽规则；计划 3 的 prompt 会要求原样写出值。

## DySQL 金标准（1062 条）

| v1 | v2 | 条数 |
|---|---|---|
| 通过 | 通过 | 895 |
| 通过 | 拒绝 | 13 |
| 拒绝 | 通过 | 0 |
| 拒绝 | 拒绝 | 154 |

### 判决变化

- 仍拒绝、原因变了：noop_write → literal_missing+noop_write（1）：dysql:human_resources:39
- 通过 → 拒绝：literal_missing（10）：dysql:cookbook:14, dysql:cookbook:26, dysql:cookbook:33, dysql:cookbook:34, dysql:cookbook:38, dysql:cookbook:39, dysql:entertainment:3, dysql:entertainment:110, dysql:human_resources:27, dysql:law_episode:8
- 通过 → 拒绝：nondeterministic（3）：dysql:pagila:18, dysql:pagila:32, dysql:pagila:48

### 类型变化（两边都算出了类型的）

- 4_other_person → 2_self_and_public：5

## 候选：../v1/results（4159 条）

| v1 | v2 | 条数 |
|---|---|---|
| 通过 | 通过 | 3811 |
| 通过 | 拒绝 | 5 |
| 拒绝 | 通过 | 61 |
| 拒绝 | 拒绝 | 282 |

### 判决变化

- 仍拒绝、原因变了：literal_missing+sql_error → sql_error（1）：bird:olympics:person:103847:0
- 拒绝 → 通过：v1 的原因 literal_missing（61）：spider2:IPL:player:188:0, spider2:IPL:player:92:0, spider2:WWE:Wrestlers:25014:0, spider2:WWE:Wrestlers:117636:0, spider2:WWE:Wrestlers:21364:0, bird:beer_factory:customers:897614:0, bird:beer_factory:customers:660634:0, bird:books:customer:482:0, bird:books:customer:1897:0, bird:books:customer:1183:0 …
- 通过 → 拒绝：literal_missing（5）：bird:books:customer:1774:0, bird:professional_basketball:players:kelsegr01:0, bird:professional_basketball:players:araujra01:0, bird:superhero:superhero:234:0, bird:superhero:superhero:435:0

### 类型变化（两边都算出了类型的）

- 4_other_person → 2_self_and_public：67
- 4_other_person → 3_public_only：5
