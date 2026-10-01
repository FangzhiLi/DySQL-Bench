# 训练任务生成 v2（进行中）

v2 从 v1 原样复制起步（tag `taskgen-v1`，61c8133）。复制的那个 commit 只改了包名（`taskgen_v1` → `taskgen_v2`）和路径（`taskgen/v1/` → `taskgen/v2/`），逻辑没动。之后每处改动单独提交，并在下面的改动记录里记一行。

- **设计：** [docs/2026-10-01-taskgen-v2-design.md](docs/2026-10-01-taskgen-v2-design.md)
- **实施计划 1（骨架、任务集统计、执行检查）：** [docs/2026-10-01-taskgen-v2-plan-1.md](docs/2026-10-01-taskgen-v2-plan-1.md)
- **怎么跑：** 和 v1 相同（[../v1/README.md](../v1/README.md) §3），命令在 `taskgen/v2/` 下运行。中间文件写到 `taskgen/v2/results/`，最终任务写到 `taskgen/v2/output/`，都不进 git。
- **测试：** `cd taskgen/v2 && ~/miniconda3/envs/dysql/bin/python -m pytest -q`

## 改动记录

| 改动 | 设计条目 |
|---|---|
| 从 v1 复制，只改名 | §4.0 |
| 任务集统计：`scripts/task_stats.py` 和 DySQL 并排比 §3 的指标；DySQL 金标准的读取挪到 `taskgen_v2/dysql.py` | §3、§5 G |
| 执行检查：字面量按整词匹配（`203` 不再匹配 `2030`），first…twelfth 算数字 | §4.5 |
| 执行检查：SQLite 会自动分配的新主键不必出现在 instruction 里；`schema.pk_info` 给每张表的主键分类 | D9、§4.3、§4.5 |
