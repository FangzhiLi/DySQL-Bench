# taskgen：训练任务生成

这里的代码为 GRPO 训练生成 DySQL-Bench 风格的多轮写操作任务。它不属于上游的 DySQL-Bench，所以和评测代码（`DySQL-Bench/`）、官方出题脚本（`data_pipeline_shell/`）分开放。

- **v1（通用规则版）的全流程：** 见 [v1/README.md](v1/README.md)。

## 目录

```
taskgen/
  common/             第 0 步，各版本共用：选库、锚点、DySQL 任务分类
    taskgen_common/   db_select.py、db_anchor.py、paths.py（路径）、testing.py（测试用的 SQLite fixture）
    scripts/          select_dbs.py、render_candidates_md.py、fk_report.py、classify_dysql_tasks.py
    tests/  docs/
    data/             candidate_dbs.csv/.md、candidate_anchors.json、db_notes.csv、db_topics.csv、
                      fk_extra.json、dysql_task_types.csv
    results/          筛选器的完整输出（不进 git）
  v1/                 通用规则版，打 tag taskgen-v1 后冻结
    README.md         v1 全流程总览
    taskgen_v1/       trees、schema、prompt、llm、generate、check、verify、dedup、convert、stats、io
    scripts/  tests/  docs/
    data/             db_descriptions.json
    results/          每个库的中间文件（不进 git）
    output/           最终任务和 manifest（不进 git）
  v2/                 之后从 v1 复制起步
```

## 约定

- **common 只放各版本都认可的东西。** 新版本要改第 0 步的结果（比如锚点）时，在自己的目录里放覆盖配置，不改 common。这样旧版本随时能原样重跑。
- **版本冻结。** v1 打了 tag `taskgen-v1`，之后只改文档。
  - 新版本复制上一版的目录起步，包名改成 `taskgen_v2`。
  - 两版可以并排运行、直接对比。
- **生成的任务不进 git。**
  - 仓库是公开的。
  - 中间文件放 `results/`，最终任务放 `output/`，都只在本机。
- **和评测的接口只有 manifest。** `DySQL-Bench` 的 `GenEnv` 读 `TASKGEN_MANIFEST` 指向的 manifest，不 import 这里的代码。所以任何版本的输出都能用 `gen:<db>` 评测。
- **测试按目录跑：** `cd taskgen/common && pytest`，`cd taskgen/v1 && pytest`。
  - 每个目录有自己的 `conftest.py` 设好 import 路径，不用安装。
  - 不要在 `taskgen/` 下一次跑全部：v1 和 v2 的测试文件同名。
- **文档：** 用中文。设计、计划、报告放各自目录的 `docs/`，文件名带日期。

## 2026-10-01 重组前后的路径对照

重组前写的文档（设计、计划、试点报告、选库条件）里用的是旧路径。

| 旧位置 | 新位置 |
|---|---|
| `DySQL-Bench/dysql_bench/db_select.py`、`db_anchor.py` | `taskgen/common/taskgen_common/` |
| `DySQL-Bench/dysql_bench/taskgen/` | `taskgen/v1/taskgen_v1/` |
| `DySQL-Bench/scripts/` 下的 `select_dbs.py`、`render_candidates_md.py`、`fk_report.py`、`classify_dysql_tasks.py` | `taskgen/common/scripts/` |
| `DySQL-Bench/scripts/` 下的 `taskgen.py`、`taskgen_*.sh`、`calibrate_check.py`、`serve_verifier.sh` | `taskgen/v1/scripts/` |
| `DySQL-Bench/tests/` 下的 `test_db_select.py`、`test_db_anchor.py`、`test_dysql_acceptance.py`、`test_select_dbs_cli.py`、`test_render_candidates_md.py` | `taskgen/common/tests/` |
| `DySQL-Bench/tests/test_taskgen_*.py` | `taskgen/v1/tests/` |
| `DySQL-Bench/tests/_sqlite_fixtures.py` | `taskgen/common/taskgen_common/testing.py` |
| `docs/2026-09-24-data-gen-db-selection.md`，`docs/data_gen/` 下的选库文档 | `taskgen/common/docs/` |
| `docs/data_gen/` 下的候选清单、锚点 JSON、`db_notes.csv` 等数据 | `taskgen/common/data/` |
| `docs/2026-09-28-task-gen-design.md`，`docs/data_gen/` 下的 v1 计划、校准、试点、全量记录 | `taskgen/v1/docs/` |
| `docs/data_gen/db_descriptions.json` | `taskgen/v1/data/` |
| `DySQL-Bench/results/taskgen/` | `taskgen/v1/results/`（本地） |
| `DySQL-Bench/results/db_select/`、`docs/benchmark_db_catalog.xlsx` | `taskgen/common/results/`（本地） |
| `DySQL-Bench/data/taskgen/` | `taskgen/v1/output/`（本地，不进 git） |
