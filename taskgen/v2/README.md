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
