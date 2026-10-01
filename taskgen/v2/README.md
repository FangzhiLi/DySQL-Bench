# 训练任务生成 v2（进行中）

v2 从 v1 原样复制起步（tag `taskgen-v1`，61c8133）。复制的那个 commit 只改了包名（`taskgen_v1` → `taskgen_v2`）和路径（`taskgen/v1/` → `taskgen/v2/`），逻辑没动。之后每处改动单独提交，并在下面的改动记录里记一行。

- **设计：** [docs/2026-10-01-taskgen-v2-design.md](docs/2026-10-01-taskgen-v2-design.md)
- **实施计划 1（骨架、任务集统计、执行检查）：** [docs/2026-10-01-taskgen-v2-plan-1.md](docs/2026-10-01-taskgen-v2-plan-1.md)
- **实施计划 2（库档案、嵌套建树、检查读档案）：** [docs/2026-10-01-taskgen-v2-plan-2.md](docs/2026-10-01-taskgen-v2-plan-2.md)
- **怎么跑：** 和 v1 相同（[../v1/README.md](../v1/README.md) §3），命令在 `taskgen/v2/` 下运行。中间文件写到 `taskgen/v2/results/`，最终任务写到 `taskgen/v2/output/`，都不进 git。
- **测试：** `cd taskgen/v2 && ~/miniconda3/envs/dysql/bin/python -m pytest -q`

## 改动记录

| 改动 | 设计条目 |
|---|---|
| 从 v1 复制，只改名 | §4.0 |
| 任务集统计：`scripts/task_stats.py` 和 DySQL 并排比 §3 的指标；DySQL 金标准的读取挪到 `taskgen_v2/dysql.py` | §3、§5 G |
| 执行检查：字面量按整词匹配（`203` 不再匹配 `2030`），first…twelfth 算数字 | §4.5 |
| 执行检查：SQLite 会自动分配的新主键不必出现在 instruction 里；`schema.pk_info` 给每张表的主键分类 | D9、§4.3、§4.5 |
| 执行检查：读时钟或随机数的 gold 间隔 1.1 秒执行两遍，评测会比较的列不一致就拒 | §4.5 |
| 执行检查：说话人登记的新人物行标 `new_person`，算类型时按公共数据 | §4.5 |
| 执行检查重新校准：v1 和 v2 的检查在 DySQL 金标准和 v1 全部候选上逐条对比（`scripts/check_diff.py`），报告 `docs/2026-10-01-check-recalibration.md` | §5 E |
| 库档案：`taskgen_v2/db_profile.py`（格式、校验、写入范围、审阅页）；测试夹具 `tests/v2_fixtures.py` | §4.1 |
| 归属追溯挪到 `taskgen_v2/owners.py`（支持复合外键和档案里的边），执行检查改用它，行为不变（校准报告逐字不变） | §4.5 |
| 执行检查读档案：范围按档案，往 `no_insert` 表 INSERT 拒，算出第 4 类拒（`other_person`）；REPLACE/UPSERT 覆盖已有人物行不算新人，自动主键按每条 INSERT 前现算，重跑时 Ctrl-C 不被吞；`check_diff.py --profiles` | §4.5、D6 |
| 建树：按档案嵌套事件树（事件行挂实际引用的父行，带归属标签，≤30 条事件，先抽有事件的根行，双根按可用行数分）；`trees` 命令要已确认的档案，不再写 `others.json` | §4.2、D3 |
| 出题读新树：按难度展示 3–5/5–8/8–12 条事件，数据块 ≤16000 字符，长文本截到 200 字符，每行注明归属；不出第 4 类；`generate`、`check` 命令读档案 | §4.2、§4.4、D6 |
| 档案起草：`taskgen_v2/profile_draft.py`（GLM 看每表的键、列、外键、BIRD 列说明和 3 行样例，加 `data/profile_hints.json` 的根和已知怪异点、两份手写 DySQL 示例；校验不过带着问题重写，最多 2 次）；`profile draft/check/render/confirm` 命令 | §4.1、D1 |
| 23 个库的档案：GLM 起草，Claude 逐库预审，用户确认（`data/db_profiles.json`，审阅页 `docs/2026-10-01-db-profiles-review.md`）；预审时加了两条规则：档案里一条边的父表一侧必须唯一，带档案时公共行不属于任何人 | §4.1、§4.5 |
| 验证：23 库按档案建树统计、beer_factory 一棵树逐行核对、4 库冒烟（要求和算出的类型不一致 4/95，标签不一致 0）、带档案的检查在 v1 候选上对比（`docs/2026-10-01-check-with-profiles.md`），记录在 `docs/2026-10-01-profiles-and-trees.md`；设计文档写回计划 2 的规则 | §5 B、C |
| 最终复核后的修正：档案校验加三条（事件表、路径上的表、属性表不能是公共表；事件路径最多 3 条边；same_as 的列要能对上主键）；确认绑定内容的版本号（`confirmed_version`），确认后改过内容要重新确认；`trees`、`generate`、`check` 遇到别的档案版本留下的树或候选就停 | §4.1 |
| 执行检查：读时钟的 gold 在同一天的两个固定时刻各跑一遍（不再隔 1.1 秒）；不带时间参数的日期函数也算读时钟；字面量认复数词尾和紧跟数字的单位，不认左边粘着字母的数字 | §4.5 |
| 出题素材：档案的描述和数据怪异点、范围内表的 DDL 和列说明、每表一行键说明（`schema.key_notes`）；树记下能单独认出说话人的列（`lookup`） | §4.3 |
| 出题计划与 prompt：写语句数和形状（两张表、子查询、批量、archive）按 DySQL 校准，难度由形状推出；不要 `outputs` 和只读提问；40–80 词、名字加 ID 开头；手写 DySQL 式示例；删掉 `describe` 和 `data/db_descriptions.json` | §4.4 |
| 验证：beer_factory 100 条、其余 22 个库各 10 条，§3 指标对照 DySQL（`docs/2026-10-01-prompt-and-materials.md`）；设计写回计划 3 的规则 | §5 D |
