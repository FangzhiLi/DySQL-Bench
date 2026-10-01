# docs：DySQL-Bench 评测

这里只放评测相关的文档。训练任务生成（选库、出题）的文档在 [taskgen/](../taskgen/README.md)。

| 文档 | 内容 |
|---|---|
| [2026-09-15-dysql-bench-eval-setup.md](2026-09-15-dysql-bench-eval-setup.md) | 评测环境搭建和 Qwen3-32B-AWQ 基线的实施计划 |
| [2026-09-17-small-agent-baselines-plan.md](2026-09-17-small-agent-baselines-plan.md) | Qwen3-1.7B / 4B 零样本基线的实施计划 |
| [dysql_db_info.md](dysql_db_info.md) | DySQL 13 个库的明细 |
| [task_counts.md](task_counts.md) | 各库的任务数 |
| [gb10_serving_notes.md](gb10_serving_notes.md) | 在 GB10 上起 vLLM 服务的经验 |
| [results/](results/) | 各次评测的报告、汇总表和失败分析 |

评测脚本在 `DySQL-Bench/scripts/`，结果目录 `DySQL-Bench/results/` 不进 git。
