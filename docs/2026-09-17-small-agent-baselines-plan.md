# Qwen3-1.7B / Qwen3-4B 零样本 agent 基线（全量 1062 任务）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在同一台 GB10 上并行跑两条全量 DySQL-Bench（1062 任务，pass@1）：agent 分别为 Qwen3-1.7B 和 Qwen3-4B，user sim 共用 Qwen2.5-72B-Instruct-AWQ，产出与 2026-09-17 Qwen3-32B-AWQ 基线可直接对比的结果和报告。

**Architecture:** 三个 vLLM 容器共享 121 GB 统一内存：user sim 在 :8001（不变），1.7B 在 :8000，4B 在 :8002。两条 `run_full.sh` 进程各自连自己的 agent 端口、共用 user sim，写到各自的 `results/full_<tag>/` 目录。harness 只改一处（13 个 env 的 sqlite 临时目录名加进程号，Task 1b），其余只把 5 个脚本里写死的模型名、端口、容器名参数化，默认值保持 32B 行为。

**Tech Stack:** vLLM `vllm/vllm-openai:cu130-nightly`（0.19.2rc1）、docker、bash、conda env `dysql`、现有 `scripts/*.py` 分析脚本。

**Spec:** 本文档第 1 部分“分析与决策”即为 spec（用户在 2026-09-17 对话中提出的问题及本文的回答）。相关背景：`docs/results/2026-09-17-qwen3-32b-awq-full.md`、`docs/gb10_serving_notes.md`。

## Global Constraints

- 采样参数与 32B 基线完全一致：temp 0.6、top_p 0.95、top_k 20、min_p 0、max_tokens 8192、max 30 steps。不改 wiki/system prompt，不截断 SELECT 结果（那是后续单独的对照实验）。
- thinking 模式默认 **on**（与 32B 基线一致）；只有 pilot 触发 Task 8 的门槛才考虑 off，且必须在报告里写明。
- vLLM 容器 **一次只起一个**，等 `/v1/models` 返回 200 再起下一个（`docs/gb10_serving_notes.md`：并发起会让先起的那个 KV 为负失败）。
- 两条 run 活跃期间 **不得** 重启 `dysql-user`，也不得使用 `scripts/handover_restart.sh`（它会 `docker rm -f dysql-user` 并按 32B 配置重启 agent）。
- 所有脚本改动向后兼容：不带环境变量运行时行为与现在完全相同。
- 提交信息末尾加 `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`。

---

## 第 1 部分：分析与决策

### 1.1 Setup 拓扑与内存预算

| 服务 | 模型 | 端口 | 容器名 | 权重 | GPU_UTIL | 折合内存 |
|---|---|---|---|---|---|---|
| user sim | Qwen/Qwen2.5-72B-Instruct-AWQ | 8001 | dysql-user | ~40 GB | 0.38（不变） | 46 GB |
| agent A | Qwen/Qwen3-1.7B（bf16） | 8000 | dysql-agent-1.7b | 3.4 GB | 0.10 | 12 GB |
| agent B | Qwen/Qwen3-4B（bf16） | 8002 | dysql-agent-4b | 8 GB | 0.15 | 18 GB |
| 合计 | | | | | 0.63 | 76 GB，剩 45 GB 给 host、reward 计算加载 sqlite |

KV 依据：32B 那轮 agent KV 峰值 42%（约 7 GB，≈27k token 并发在飞）。1.7B 每 token KV 是 32B-AWQ 的 0.44 倍（28 层 vs 64 层），4B 是 0.56 倍，所以 3 GB / 4 GB 就够，上表留了一倍余量。现在 32B agent 占 0.36（44 GB），停掉后腾出的空间比两个小模型合计还多 14 GB。

**user sim 是瓶颈。** 32B 那轮它的日志 `Running: 16 reqs` 已经顶到 `--max-num-seqs 16`，KV 只用 20%。两条 run 各 16 并发 = 32 个 user 请求，必须把 user sim 的 `MAX_SEQS` 提到 32 再起（启动参数，只能重启）。72B 解码是带宽瓶颈，批次翻倍时延几乎不变（2026-09-16 pilot 结论）。

**时间预估**：32B 全量 28.3 h，agent 是瓶颈。换成小模型后 agent 时间大幅缩短，两条 run 总墙钟 ≈ user sim 处理 2 倍请求 + reward 计算，粗估 1 到 1.5 倍单条 run 时间；串行是 2 倍。精确数字以 pilot 的 `estimate_full.py` 为准。

### 1.2 与 32B 全量相比，环境配置要改什么

| 项 | 32B 基线 | 1.7B / 4B | 原因 |
|---|---|---|---|
| `--quantization awq_marlin` | 有 | **去掉** | bf16 权重，带此参数 vLLM 启动直接报错 |
| `--max-model-len 40960` | 40960 | **保持 40960** | 两个模型 config.json 的 max_position_embeddings 都是 40960（已核对 HF） |
| `--gpu-memory-utilization` | 0.36 | 0.10 / 0.15 | 见 1.1 |
| `--served-model-name` | qwen3-32b-awq | qwen3-1.7b / qwen3-4b | 会进入结果文件名，见 1.4 |
| 容器名 / 端口 | dysql-agent / 8000 | dysql-agent-1.7b:8000、dysql-agent-4b:8002 | 两个 agent 共存 |
| user sim `--max-num-seqs` | 16 | **32** | 两条 run 共用 |
| `--reasoning-parser qwen3`、`enable_thinking` | 有 / on | 不变 | thinking 输出走 `message.reasoning`，harness 已兼容 |
| 采样、max_tokens、max steps | 见 Global Constraints | 不变 | 可比性 |
| HF 缓存 | 已有 32B | **需下载** Qwen/Qwen3-1.7B、Qwen/Qwen3-4B | 缓存里目前没有，磁盘剩 2.7 TB，huggingface.co 可达 |

harness 代码（`dysql_bench/`）除 Task 1b 的目录名外无需改动：`--model`、`--model-api`、`--user-model-api` 都已是 CLI 参数，`.config.json` sidecar 会探测各自的 agent 端口记录 served model 和 vLLM 版本。

### 1.3 要不要开新 branch

**不用，留在 `isa/eval-harness`。** 理由：

- 本次不改 harness 逻辑，只参数化 5 个脚本且默认值不变，属于 eval-harness 这条线的自然延续。
- `DySQL-Bench/results/` 在 .gitignore 里，结果不进 git；进 git 的只有 `docs/results/*.md` 报告，和 32B 报告放同一目录即可。
- sidecar 会记录 `git_commit`。**开跑前先把脚本改动和现在两个未跟踪文件（`scripts/classify_failures.py`、失败分析 md）提交掉**，这样 1062 个结果指向一个干净、可复现的 commit，而不是 dirty tree。

如果以后要把 eval-harness 合回 main，这些脚本改动一起走，不需要单独分支。

### 1.4 result 和 log 的命名与路径

| 产物 | 32B 基线 | 本次 | 说明 |
|---|---|---|---|
| 结果目录 | `results/full_qwen3_32b_think_on_c12/` | `results/full_qwen3_1.7b_think_on_c16/`、`results/full_qwen3_4b_think_on_c16/` | tag 编码 模型_思考模式_并发；由 `run_full.sh <tag>` 决定 |
| 每 env 结果文件 | `<env>-sql-agent-qwen3-32b-awq-0.6_range_0--1_user-qwen2.5-72b-awq-llm_<ts>.json` | 同格式，中间变成 `qwen3-1.7b` / `qwen3-4b` | run.py 自动用 `--model` 值生成，不用改 |
| sidecar | `<同名>.config.json` | 同 | 自动 |
| 每 env python 日志 | `results/full_<tag>/<env>.log` | 同 | 自动 |
| **脚本级日志** | `results/full_run.log`（nohup 重定向，**所有 run 共用**） | **`results/full_<tag>/run.log`**（脚本内 `exec` 重定向） | 必须改：两条并行 run 写同一个文件会串行；`progress.sh` 也改成读这个 |
| 汇总 | `results/full_<tag>/summary.md` | 同 | run_full.sh 结束时自动生成 |
| 报告 | `docs/results/2026-09-17-qwen3-32b-awq-full.md` | `docs/results/<完成日期>-qwen3-1.7b-full.md`、`-qwen3-4b-full.md`，外加一份三模型对比 | 手写，Task 10 |

### 1.5 需要注意的地方（运行期）

1. **起容器顺序**：先 `docker rm -f dysql-agent`（32B）；再重启 user sim（MAX_SEQS=32）并等 :8001 就绪；再起 1.7B 等 :8000；再起 4B 等 :8002。大模型先起，因为它的内存 profiling 最脆弱。
2. **eu_soccer 不要两条 run 同时跑**：reward 计算每线程整份加载 299 MB 的库。4B 那条 run 用 `ENV_ORDER=reverse`，让 eu_soccer 一头一尾错开；eu_soccer 的并发 8 覆盖保留。
3. **续跑**：任何一条 run 中断，原样重跑同一条 nohup 命令即可，`--resume` 会跳过已完成、重跑 `error` 的。单个 agent 容器挂了由 `--restart unless-stopped` 拉回；不行就单独重跑它的 serve 命令，**不要碰 dysql-user**。
4. **预期会多出来、但不需要修的失败**（都已是带标签的失败类别，计入 pass^1 分母）：
   - `length_no_content`：小模型 thinking 把 8192 耗尽。32B 出现 5 次；pilot 门槛见 Task 8。
   - `context_overflow`：32B 有 8 次；小模型长度上限相同，次数应接近。
   - 协议违规（多 SQL block、假 `<result>`、没写入就宣称完成）：32B 已占失败的 39%+13.5%，小模型会更高，正是 GRPO 前要测的零样本基线。
5. **报告时 no-op gold 任务的通过率要报两版**（含 / 不含 99 个 gold 写入 0 行的任务），与 32B 报告一致。
6. **两条 run 的唯一文件级冲突**：每个任务的 sqlite 副本目录只用线程 id 命名（见 Task 1b），并行前必须加进程号。其余维度互不冲突：容器/端口/结果目录/日志各自独立，HF 缓存只读，user sim 按请求排队。
7. **不要顺手做的事**：改 wiki、截断 SELECT 结果、调 max_tokens。这些各自是对照实验，混进基线就没法和 32B 比了。

---

## 第 2 部分：任务

### Task 1: 提交现有未跟踪文件，确保开跑前工作树干净

**Files:**
- Commit: `DySQL-Bench/scripts/classify_failures.py`、`docs/results/2026-09-17-qwen3-32b-awq-full-failure-analysis.md`

- [ ] **Step 1: 确认当前状态**

Run: `cd /home/wmd3i/Documents/Isa/DySQL-Bench && git status --short`
Expected: 只有上述两个 `??` 文件，branch 为 `isa/eval-harness`。

- [ ] **Step 2: 提交**

```bash
cd /home/wmd3i/Documents/Isa/DySQL-Bench
git add DySQL-Bench/scripts/classify_failures.py docs/results/2026-09-17-qwen3-32b-awq-full-failure-analysis.md
git commit -m "docs: Qwen3-32B-AWQ full-run failure attribution + classify_failures.py

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

- [ ] **Step 3: 验证**

Run: `git status --short | wc -l`
Expected: `0`

### Task 1b: 每个 env 的 sqlite 工作目录加上进程号（并行两条 run 的唯一真实冲突点）

**背景：** 13 个 `dysql_bench/envs/<env>/data/__init__.py` 里的 `load_sql_data(thread_id)` 都把该任务的数据库副本放在 `data/tmp/thread_<threading.get_ident()>/`。`get_ident()` 只在一个进程内唯一；两条 run 是两个 python 进程，同一时刻处理同一个 env 时目录名可能相同（ASLR 使概率很低但不为零），一方的 `shutil.copy` 会覆盖另一方正在写的库，`delete_db` 的 `rmtree` 会删掉对方的目录，结果静默变成错的。另外 `thread_None` 目录（run.py:175 用 `thread_id=None` 建 env 枚举任务）是两条 run 必然共用的路径。加上 `os.getpid()` 后两个进程永不同名。

**Files:**
- Modify: 13 个 `DySQL-Bench/dysql_bench/envs/*/data/__init__.py`（同一行）
- Test: `DySQL-Bench/tests/test_tmp_dir_per_process.py`

**Interfaces:**
- Produces: 目录名格式 `thread_<pid>_<thread_id>`。`base.py:233` 的断言比较的是同一进程内两次调用的返回值，不受影响。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_tmp_dir_per_process.py
import os, glob, importlib, re

ENVS = sorted(os.path.basename(os.path.dirname(os.path.dirname(p)))
              for p in glob.glob(os.path.join(os.path.dirname(__file__), "..", "dysql_bench", "envs", "*", "data", "__init__.py")))

def test_all_13_envs_have_loader():
    assert len(ENVS) == 13

def test_tmp_folder_includes_pid():
    for env in ENVS:
        mod = importlib.import_module(f"dysql_bench.envs.{env}.data")
        conn, cur, folder = mod.load_sql_data(4242)
        try:
            assert os.path.basename(folder) == f"thread_{os.getpid()}_4242", (env, folder)
        finally:
            conn.close()
            import shutil; shutil.rmtree(folder)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /home/wmd3i/Documents/Isa/DySQL-Bench/DySQL-Bench && conda run -n dysql python -m pytest tests/test_tmp_dir_per_process.py -q`
Expected: `test_tmp_folder_includes_pid` FAIL，断言信息里目录名是 `thread_4242`。

- [ ] **Step 3: 一次改 13 个文件**

```bash
cd /home/wmd3i/Documents/Isa/DySQL-Bench/DySQL-Bench
sed -i 's|f"thread_{thread_id}"|f"thread_{os.getpid()}_{thread_id}"|' dysql_bench/envs/*/data/__init__.py
grep -c 'thread_{os.getpid()}_{thread_id}' dysql_bench/envs/*/data/__init__.py | grep -vc ':1$'
```
Expected: 最后一行输出 `0`（13 个文件每个恰好一处）。所有 13 个文件已 `import os`，无需再加。

- [ ] **Step 4: 跑测试确认通过**

Run: `conda run -n dysql python -m pytest tests/ -q`
Expected: 全部 PASS（包括原有的 test_env_hash、test_resume 等）。

- [ ] **Step 5: 清理历史残留的 tmp 目录并提交**

```bash
rm -rf dysql_bench/envs/*/data/tmp/thread_*
cd /home/wmd3i/Documents/Isa/DySQL-Bench
git add DySQL-Bench/dysql_bench/envs/*/data/__init__.py DySQL-Bench/tests/test_tmp_dir_per_process.py
git commit -m "fix(envs): per-task sqlite tmp dir keyed by (pid, thread id) so two run.py processes never collide

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task 2: 参数化 `serve_agent.sh`

**Files:**
- Modify: `DySQL-Bench/scripts/serve_agent.sh`（整文件替换）

**Interfaces:**
- Produces: 环境变量 `MODEL SERVED_NAME PORT CONTAINER QUANT MAX_LEN MAX_SEQS GPU_UTIL THINKING DRY_RUN`。`QUANT=none` 表示不传 `--quantization`。`DRY_RUN=1` 只打印 docker 命令。默认值 = 现在的 32B 行为。

- [ ] **Step 1: 写入新脚本**

```bash
#!/usr/bin/env bash
# scripts/serve_agent.sh -- start a vLLM agent server. All knobs are env vars; defaults reproduce the Qwen3-32B-AWQ setup.
#   MODEL        HF id                      default Qwen/Qwen3-32B-AWQ
#   SERVED_NAME  --served-model-name        default qwen3-32b-awq   (this string ends up in result file names via run.py --model)
#   PORT         host and container port    default 8000
#   CONTAINER    docker container name      default dysql-agent
#   QUANT        --quantization value       default awq_marlin; QUANT=none for bf16 checkpoints (Qwen3-1.7B / 4B)
#   MAX_LEN      --max-model-len            default 40960
#   MAX_SEQS     --max-num-seqs             default 32
#   GPU_UTIL     --gpu-memory-utilization   default 0.36
#   THINKING     on|off                     default on
#   DRY_RUN=1    print the docker command and exit without touching containers
set -euo pipefail
MODEL="${MODEL:-Qwen/Qwen3-32B-AWQ}"
SERVED_NAME="${SERVED_NAME:-qwen3-32b-awq}"
PORT="${PORT:-8000}"
CONTAINER="${CONTAINER:-dysql-agent}"
QUANT="${QUANT:-awq_marlin}"
MAX_LEN="${MAX_LEN:-40960}"
MAX_SEQS="${MAX_SEQS:-32}"
GPU_UTIL="${GPU_UTIL:-0.36}"
THINKING="${THINKING:-on}"
if [ "$THINKING" = "on" ]; then KW='{"enable_thinking": true}'; else KW='{"enable_thinking": false}'; fi
QARGS=()
if [ "$QUANT" != "none" ]; then QARGS=(--quantization "$QUANT"); fi
CMD=(docker run -d --name "$CONTAINER" --restart unless-stopped
  --gpus all --ipc host --shm-size 64gb
  -p "$PORT:$PORT"
  -v "$HOME/.cache/huggingface:/root/.cache/huggingface"
  vllm/vllm-openai:cu130-nightly
  "$MODEL"
  --served-model-name "$SERVED_NAME"
  --host 0.0.0.0 --port "$PORT"
  "${QARGS[@]}"
  --max-model-len "$MAX_LEN"
  --max-num-seqs "$MAX_SEQS"
  --gpu-memory-utilization "$GPU_UTIL"
  --enable-prefix-caching
  --reasoning-parser qwen3
  --default-chat-template-kwargs "$KW")
if [ "${DRY_RUN:-0}" = "1" ]; then printf '%q ' "${CMD[@]}"; echo; exit 0; fi
docker rm -f "$CONTAINER" 2>/dev/null || true
"${CMD[@]}"
echo "$CONTAINER ($SERVED_NAME) starting on :$PORT thinking=$THINKING max-num-seqs=$MAX_SEQS gpu-util=$GPU_UTIL; logs: docker logs -f $CONTAINER"
```

- [ ] **Step 2: 验证默认行为不变（32B）**

Run:
```bash
cd /home/wmd3i/Documents/Isa/DySQL-Bench/DySQL-Bench
DRY_RUN=1 bash scripts/serve_agent.sh | tr ' ' '\n' | grep -cE '^(Qwen/Qwen3-32B-AWQ|qwen3-32b-awq|awq_marlin|40960|dysql-agent|0.36)$'
```
Expected: `6`

- [ ] **Step 3: 验证 1.7B 配置去掉了 quantization**

Run:
```bash
DRY_RUN=1 MODEL=Qwen/Qwen3-1.7B SERVED_NAME=qwen3-1.7b PORT=8000 CONTAINER=dysql-agent-1.7b QUANT=none GPU_UTIL=0.10 \
  bash scripts/serve_agent.sh | tee /dev/stderr | grep -c quantization
```
Expected: `0`，且 stderr 打印的命令里含 `-p 8000:8000`、`--name dysql-agent-1.7b`、`--gpu-memory-utilization 0.10`。

- [ ] **Step 4: 提交**

```bash
cd /home/wmd3i/Documents/Isa/DySQL-Bench
git add DySQL-Bench/scripts/serve_agent.sh
git commit -m "feat(scripts): serve_agent.sh takes MODEL/SERVED_NAME/PORT/CONTAINER/QUANT/MAX_LEN env knobs; defaults unchanged

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task 3: 参数化 `wait_ready.sh`

**Files:**
- Modify: `DySQL-Bench/scripts/wait_ready.sh`（整文件替换）

**Interfaces:**
- Produces: `wait_ready.sh [port ...]`，默认 `8000 8001`。全部 200 才退出 0。

- [ ] **Step 1: 写入新脚本**

```bash
#!/usr/bin/env bash
# scripts/wait_ready.sh [port ...] -- block until every listed vLLM server answers /v1/models with 200 (default: 8000 8001). 30 min timeout.
set -u
PORTS=("$@"); [ ${#PORTS[@]} -eq 0 ] && PORTS=(8000 8001)
for i in $(seq 1 180); do
  ok=1
  for p in "${PORTS[@]}"; do
    code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$p/v1/models" || true)
    [ "$code" = "200" ] || ok=0
  done
  if [ "$ok" = "1" ]; then echo "ready: ${PORTS[*]}"; exit 0; fi
  sleep 10
done
echo "timeout waiting for ${PORTS[*]}"; exit 1
```

- [ ] **Step 2: 验证（当前 8000/8001 都在跑）**

Run: `bash scripts/wait_ready.sh 8001 && echo OK`
Expected: 立即打印 `ready: 8001` 和 `OK`。

Run: `timeout 12 bash scripts/wait_ready.sh 8999; echo rc=$?`
Expected: 无 `ready`，`rc=124`（被 timeout 杀掉，说明它在等）。

- [ ] **Step 3: 提交**

```bash
git add DySQL-Bench/scripts/wait_ready.sh
git commit -m "feat(scripts): wait_ready.sh accepts a port list

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task 4: 参数化 `run_full.sh`（模型、端口、env 顺序、独立 run.log）

**Files:**
- Modify: `DySQL-Bench/scripts/run_full.sh`（整文件替换）

**Interfaces:**
- Produces: 环境变量 `MODEL`（served name，默认 qwen3-32b-awq）、`AGENT_PORT`（默认 8000）、`ENV_ORDER=forward|reverse`（默认 forward）。脚本级日志写到 `results/full_<tag>/run.log`。

- [ ] **Step 1: 写入新脚本**

```bash
#!/usr/bin/env bash
# scripts/run_full.sh <tag> [num_trials] [concurrency]  -- all 13 envs, resumable; run under nohup
# Env knobs: MODEL (served model name, default qwen3-32b-awq), AGENT_PORT (default 8000),
#            ENV_ORDER=forward|reverse (default forward; use reverse for a second concurrent run so eu_soccer is not shared)
# Script-level log: results/full_<tag>/run.log (so two concurrent runs never share a log file).
# Re-running the same command resumes: each env's existing results json is passed via --resume.
set -uo pipefail
TAG="${1:?usage: run_full.sh <tag> [num_trials] [concurrency]}"; TRIALS="${2:-1}"; CONC="${3:-16}"
MODEL="${MODEL:-qwen3-32b-awq}"; AGENT_PORT="${AGENT_PORT:-8000}"; ENV_ORDER="${ENV_ORDER:-forward}"
cd "$(dirname "$0")/.."
OUT="results/full_${TAG}"; mkdir -p "$OUT"
exec >> "$OUT/run.log" 2>&1
# largest DBs first so the long tail lands on small envs; eu_soccer (299 MB) gets lower concurrency
# because reward calculation loads the whole DB into memory per thread
ENVS="eu_soccer retail entertainment bowling pagila law_episode cookbook chinook human_resources retail_world ice_hockey car music"
if [ "$ENV_ORDER" = "reverse" ]; then ENVS=$(echo "$ENVS" | tr ' ' '\n' | tac | tr '\n' ' '); fi
declare -A CONC_OVERRIDE=( [eu_soccer]=8 )
echo "[$(date)] full run tag=$TAG model=$MODEL agent_port=$AGENT_PORT trials=$TRIALS conc=$CONC order=$ENV_ORDER"
for ENV in $ENVS; do
  C="${CONC_OVERRIDE[$ENV]:-$CONC}"
  EXISTING=$(ls "$OUT"/${ENV}-*[0-9].json 2>/dev/null | grep -v '\.config\.json$' | head -1 || true)
  RESUME=""; [ -n "$EXISTING" ] && RESUME="--resume $EXISTING"
  echo "[$(date)] start $ENV conc=$C $RESUME"
  conda run -n dysql --no-capture-output python run.py --env "$ENV" --num-trials "$TRIALS" \
    --model "$MODEL" --model-api "http://127.0.0.1:$AGENT_PORT" \
    --user-model qwen2.5-72b-awq --user-model-api http://127.0.0.1:8001 \
    --user-strategy llm --max-concurrency "$C" --log-dir "$OUT" $RESUME >> "$OUT/${ENV}.log" 2>&1
  echo "[$(date)] done $ENV rc=$?"
done
conda run -n dysql python scripts/summarize.py "$OUT/*.json" > "$OUT/summary.md" 2>/dev/null
echo "[$(date)] ALL DONE"
```

- [ ] **Step 2: 语法与 env 顺序验证（不真正跑）**

Run:
```bash
bash -n scripts/run_full.sh && echo syntax-ok
ENVS="eu_soccer retail entertainment bowling pagila law_episode cookbook chinook human_resources retail_world ice_hockey car music"
echo "$ENVS" | tr ' ' '\n' | tac | tr '\n' ' '; echo
```
Expected: `syntax-ok`；第二行以 `music car ice_hockey` 开头、`retail eu_soccer` 结尾。

- [ ] **Step 3: 提交**

```bash
git add DySQL-Bench/scripts/run_full.sh
git commit -m "feat(scripts): run_full.sh takes MODEL/AGENT_PORT/ENV_ORDER; per-tag run.log instead of shared full_run.log

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task 5: 参数化 `run_pilot.sh` 和 `progress.sh`

**Files:**
- Modify: `DySQL-Bench/scripts/run_pilot.sh`（第 12–15 行的 run.py 调用）
- Modify: `DySQL-Bench/scripts/progress.sh`（整文件替换）

**Interfaces:**
- `run_pilot.sh <tag> [conc] [nshort] [nlong]`，新增环境变量 `MODEL`、`AGENT_PORT`，语义同 Task 4。
- `progress.sh <tag> [conc] [agent_port] [agent_container]`，读 `results/full_<tag>/run.log`，找不到时回退到旧的 `results/full_run.log`。

- [ ] **Step 1: 改 run_pilot.sh**

在 `CONC="${2:-5}"` 那一行后面加：
```bash
MODEL="${MODEL:-qwen3-32b-awq}"; AGENT_PORT="${AGENT_PORT:-8000}"
```
把 run.py 调用里的
```bash
  --model qwen3-32b-awq --model-api http://127.0.0.1:8000 \
```
改成
```bash
  --model "$MODEL" --model-api "http://127.0.0.1:$AGENT_PORT" \
```

- [ ] **Step 2: 写入新 progress.sh**

```bash
#!/usr/bin/env bash
# scripts/progress.sh <tag> [conc] [agent_port] [agent_container] -- one-screen status of a full run
TAG="${1:?usage: progress.sh <tag> [conc] [agent_port] [agent_container]}"
CONC="${2:-16}"; APORT="${3:-8000}"; ACONT="${4:-dysql-agent}"
cd "$(dirname "$0")/.."
OUT="results/full_${TAG}"
LOG="$OUT/run.log"; [ -f "$LOG" ] || LOG="$OUT/../full_run.log"
echo "== $(date '+%F %T')  tag=$TAG"
grep -E "^\[" "$LOG" 2>/dev/null | tail -3
python3 - "$OUT" "$CONC" <<'PY'
import glob, json, sys, statistics
out, conc = sys.argv[1], int(sys.argv[2])
counts = {"eu_soccer":215,"retail":205,"entertainment":131,"bowling":111,"pagila":105,"law_episode":53,"cookbook":51,
          "chinook":44,"human_resources":40,"retail_world":31,"ice_hockey":28,"car":27,"music":21}
tot_done = tot_pass = 0; walls = []
print(f"{'env':16s} {'done':>9s} {'pass':>6s} {'avg wall':>9s}")
for env, n in counts.items():
    fs = [f for f in glob.glob(f"{out}/{env}-*.json") if not f.endswith(".config.json")]
    if not fs: continue
    rs = json.load(open(fs[0]))
    d = len(rs); p = sum(1 for r in rs if r["reward"] == 1)
    w = [r["meta"].get("wall_s") or 0 for r in rs]
    walls += w; tot_done += d; tot_pass += p
    err = sum(1 for r in rs if r["meta"].get("termination") == "error")
    print(f"{env:16s} {d:4d}/{n:<4d} {100*p/max(d,1):5.1f}% {statistics.mean(w) if w else 0:8.0f}s" + (f"  errors={err}" if err else ""))
print(f"{'TOTAL':16s} {tot_done:4d}/1062 {100*tot_pass/max(tot_done,1):5.1f}%")
if walls:
    rem = 1062 - tot_done
    print(f"ETA ≈ {rem*statistics.mean(walls)/conc/3600:.1f} h remaining (avg wall {statistics.mean(walls):.0f}s, c≈{conc})")
PY
echo "-- servers: agent:$APORT $(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:$APORT/v1/models) user:8001 $(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8001/v1/models) | preempt agent=$(docker logs --since 1h $ACONT 2>&1 | grep -ci preempt) user=$(docker logs --since 1h dysql-user 2>&1 | grep -ci preempt) | $(docker logs --since 30s $ACONT 2>&1 | grep -oE 'Running: [0-9]+ reqs, Waiting: [0-9]+' | tail -1)"
free -g | sed -n 2p
```

- [ ] **Step 3: 验证 progress.sh 对旧 run 仍能工作（回退到 full_run.log）**

Run: `bash scripts/progress.sh qwen3_32b_think_on_c12 16 8000 dysql-agent | head -20`
Expected: 前 3 行来自 `results/full_run.log`（含 `ALL DONE`），表格 TOTAL 行为 `1062/1062  46.1%`。

- [ ] **Step 4: 验证 run_pilot.sh 语法**

Run: `bash -n scripts/run_pilot.sh && grep -c '"\$MODEL"' scripts/run_pilot.sh`
Expected: `1`

- [ ] **Step 5: 提交**

```bash
git add DySQL-Bench/scripts/run_pilot.sh DySQL-Bench/scripts/progress.sh
git commit -m "feat(scripts): run_pilot.sh/progress.sh take model, port, container; progress reads per-tag run.log

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task 6: 下载 Qwen3-1.7B 和 Qwen3-4B 权重

**Files:** 无代码改动；写入 `~/.cache/huggingface/hub/`。

- [ ] **Step 1: 用 vLLM 镜像里的 `hf` 下载（镜像已带 `/usr/local/bin/hf`，避免在 host 装依赖）**

```bash
docker run --rm -v "$HOME/.cache/huggingface:/root/.cache/huggingface" --entrypoint hf \
  vllm/vllm-openai:cu130-nightly download Qwen/Qwen3-1.7B
docker run --rm -v "$HOME/.cache/huggingface:/root/.cache/huggingface" --entrypoint hf \
  vllm/vllm-openai:cu130-nightly download Qwen/Qwen3-4B
```
两个模型合计约 11.5 GB，可以顺序执行；如果 `hf` 报 command not found，把 `--entrypoint hf` 换成 `--entrypoint huggingface-cli`。

- [ ] **Step 2: 验证**

Run:
```bash
for m in Qwen3-1.7B Qwen3-4B; do
  python3 -c "import json,glob;d=json.load(open(glob.glob('$HOME/.cache/huggingface/hub/models--Qwen--$m/snapshots/*/config.json')[0]));print('$m',d['max_position_embeddings'],d['torch_dtype'])"
  ls "$HOME"/.cache/huggingface/hub/models--Qwen--$m/snapshots/*/*.safetensors | wc -l
done
```
Expected: `Qwen3-1.7B 40960 bfloat16` 后跟 `2`；`Qwen3-4B 40960 bfloat16` 后跟 `3`（safetensors 分片数以实际为准，只要 ≥1 且无报错）。

### Task 7: 停 32B、按顺序起三个服务、冒烟测试

**Files:** 无代码改动。

- [ ] **Step 1: 确认没有 run 在跑，停掉 32B agent**

Run:
```bash
pgrep -fa "python run.py --env" || echo "no run active"
docker rm -f dysql-agent
free -g | sed -n 2p
```
Expected: `no run active`；`free` 的 available 比之前（约 22 GB）多出约 40 GB。

- [ ] **Step 2: 重启 user sim，MAX_SEQS=32**

```bash
cd /home/wmd3i/Documents/Isa/DySQL-Bench/DySQL-Bench
MAX_SEQS=32 bash scripts/serve_user_sim.sh
bash scripts/wait_ready.sh 8001
docker logs dysql-user 2>&1 | grep -oE 'GPU KV cache size: [0-9,]+ tokens' | tail -1
```
Expected: `ready: 8001`；KV 行存在且 token 数 ≥ 32B 那轮的水平（起来后 `docker logs dysql-user | grep -i "negative\|No available memory"` 无输出）。

- [ ] **Step 3: 起 1.7B**

```bash
MODEL=Qwen/Qwen3-1.7B SERVED_NAME=qwen3-1.7b PORT=8000 CONTAINER=dysql-agent-1.7b QUANT=none GPU_UTIL=0.10 \
  bash scripts/serve_agent.sh
bash scripts/wait_ready.sh 8000
docker logs dysql-agent-1.7b 2>&1 | grep -oE 'GPU KV cache size: [0-9,]+ tokens' | tail -1
```
Expected: `ready: 8000`；KV ≥ 50,000 tokens。

- [ ] **Step 4: 起 4B**

```bash
MODEL=Qwen/Qwen3-4B SERVED_NAME=qwen3-4b PORT=8002 CONTAINER=dysql-agent-4b QUANT=none GPU_UTIL=0.15 \
  bash scripts/serve_agent.sh
bash scripts/wait_ready.sh 8002
docker logs dysql-agent-4b 2>&1 | grep -oE 'GPU KV cache size: [0-9,]+ tokens' | tail -1
free -g | sed -n 2p
```
Expected: `ready: 8002`；KV ≥ 50,000 tokens；`free` available ≥ 35 GB。

- [ ] **Step 5: 冒烟测试两个 agent 的 thinking 输出走 `reasoning` 字段**

```bash
for p in 8000 8002; do
  curl -s http://127.0.0.1:$p/v1/chat/completions -H 'Content-Type: application/json' -d '{
    "model": "'$( [ $p = 8000 ] && echo qwen3-1.7b || echo qwen3-4b )'",
    "messages": [{"role":"user","content":"Write one SQL statement that counts rows in table t."}],
    "max_tokens": 512, "temperature": 0.6}' \
  | python3 -c "import json,sys;m=json.load(sys.stdin)['choices'][0]['message'];print($p,'reasoning' if (m.get('reasoning') or m.get('reasoning_content')) else 'NO-REASONING','|',(m.get('content') or '')[:80].replace(chr(10),' '))"
done
```
Expected: 两行，各含 `reasoning` 和一段 `SELECT COUNT(*)` 之类的内容。若出现 `NO-REASONING`，检查容器日志里 `--reasoning-parser qwen3` 是否生效。

### Task 8: 双 pilot（各 10 个 pagila 任务）与 thinking 门槛判定

**Files:** 产出 `results/pilot_qwen3_1.7b_think_on/`、`results/pilot_qwen3_4b_think_on/`。

- [ ] **Step 1: 并行起两个 pilot（6 短 + 4 长，并发 8）**

```bash
cd /home/wmd3i/Documents/Isa/DySQL-Bench/DySQL-Bench
MODEL=qwen3-1.7b AGENT_PORT=8000 nohup bash scripts/run_pilot.sh qwen3_1.7b_think_on 8 6 4 > /dev/null 2>&1 &
MODEL=qwen3-4b   AGENT_PORT=8002 nohup bash scripts/run_pilot.sh qwen3_4b_think_on 8 6 4 > /dev/null 2>&1 &
```
（run_pilot.sh 自己 `tee` 到 `$OUT/pagila.log`、`summary.md`、`estimate.md`。）

- [ ] **Step 2: 等结束，看汇总**

Run:
```bash
while pgrep -f "run_pilot.sh" >/dev/null; do sleep 60; done
for t in qwen3_1.7b_think_on qwen3_4b_think_on; do echo "== $t"; cat results/pilot_$t/wall.txt; sed -n 1,3p results/pilot_$t/summary.md; cat results/pilot_$t/estimate.md; done
docker logs --since 30m dysql-user 2>&1 | grep -oE 'Running: [0-9]+ reqs, Waiting: [0-9]+' | sort -t: -k2 -n | tail -1
```
Expected: 两个 summary 的 overall 行存在，`terminations` 字典可读；user sim 的 `Running` 峰值 ≤ 32 且 `Waiting` 为 0（说明 MAX_SEQS=32 够用）。

- [ ] **Step 3: 门槛判定（写进 Task 10 的报告）**

对每个模型，从 `summary.md` overall 行的 `terminations` 取 `length_no_content` 计数：
- `< 2`（10 个 run 里少于 20%）：thinking **on** 进全量。
- `≥ 2`：对该模型单独用 `THINKING=off` 重起它自己的容器（同 Task 7 Step 3/4 的命令加 `THINKING=off`，只动这一个容器），再跑一次 pilot（tag 加 `_think_off`），选 `length_no_content + max_steps` 更少的模式进全量；全量 tag 相应改为 `think_off`。

同时记录：pass 数、`estimate.md` 给出的全量预估小时数。10 个任务通过 0 个**不是**停下的理由（零样本基线本来就可能很低），只有 termination 全是 `error` 之类的基础设施问题才停下排查。

### Task 9: 启动两条全量 run 并监控

**Files:** 产出 `results/full_qwen3_1.7b_think_on_c16/`、`results/full_qwen3_4b_think_on_c16/`（若 Task 8 改了模式，tag 中 `think_on` 换成 `think_off`）。

- [ ] **Step 1: 启动**

```bash
cd /home/wmd3i/Documents/Isa/DySQL-Bench/DySQL-Bench
MODEL=qwen3-1.7b AGENT_PORT=8000 nohup bash scripts/run_full.sh qwen3_1.7b_think_on_c16 1 16 > /dev/null 2>&1 &
MODEL=qwen3-4b   AGENT_PORT=8002 ENV_ORDER=reverse nohup bash scripts/run_full.sh qwen3_4b_think_on_c16 1 16 > /dev/null 2>&1 &
sleep 30
tail -2 results/full_qwen3_1.7b_think_on_c16/run.log results/full_qwen3_4b_think_on_c16/run.log
```
Expected: 1.7B 的 run.log 首行 `start eu_soccer conc=8`；4B 的首行 `start music conc=16`。

- [ ] **Step 2: 监控命令（每隔几小时看一次）**

```bash
bash scripts/progress.sh qwen3_1.7b_think_on_c16 16 8000 dysql-agent-1.7b
bash scripts/progress.sh qwen3_4b_think_on_c16   16 8002 dysql-agent-4b
docker ps --format '{{.Names}} {{.Status}}' | grep dysql
```
注意点：`errors=` 非零且持续增长说明某个服务不健康；`preempt` 计数持续增长说明 KV 不够，可等这条 run 完成后再调，不要中途重启。

- [ ] **Step 3: 中断后续跑**

原样重跑 Step 1 中对应的那条命令；`--resume` 跳过已完成、重跑 `error`。若某个 agent 容器 `docker ps` 里消失且 restart 策略没拉回，只重跑 Task 7 Step 3 或 Step 4 对应的 serve 命令。**不要重启 dysql-user，不要使用 handover_restart.sh。**

- [ ] **Step 4: 完成判定**

Run: `grep -c "ALL DONE" results/full_qwen3_1.7b_think_on_c16/run.log results/full_qwen3_4b_think_on_c16/run.log; grep -c '"task_id"' results/full_qwen3_*_c16/*[0-9].json | awk -F: '{s[$1 ~ /1.7b/ ? "1.7b":"4b"]+=$2} END{for(k in s) print k, s[k]}'`
Expected: 两个 `1`；两个模型各 `1062`。

### Task 10: 汇总、失败归因、报告、提交

**Files:**
- Create: `docs/results/<YYYY-MM-DD>-qwen3-1.7b-full.md`
- Create: `docs/results/<YYYY-MM-DD>-qwen3-4b-full.md`
- Create: `docs/results/<YYYY-MM-DD>-agent-size-comparison.md`
- Copy: 两个 `summary.md` 到 `docs/results/<YYYY-MM-DD>-qwen3-{1.7b,4b}-full-summary.md`

- [ ] **Step 1: 跑失败归因**

```bash
cd /home/wmd3i/Documents/Isa/DySQL-Bench/DySQL-Bench
mkdir -p /tmp/claude-1000/-home-wmd3i-Documents-Isa-DySQL-Bench/cls
conda run -n dysql python scripts/classify_failures.py results/full_qwen3_1.7b_think_on_c16 /tmp/claude-1000/-home-wmd3i-Documents-Isa-DySQL-Bench/cls/1.7b/
conda run -n dysql python scripts/classify_failures.py results/full_qwen3_4b_think_on_c16   /tmp/claude-1000/-home-wmd3i-Documents-Isa-DySQL-Bench/cls/4b/
```

- [ ] **Step 2: 写两份单模型报告**

结构照抄 `docs/results/2026-09-17-qwen3-32b-awq-full.md`：开头 run 时间/墙钟/分支/结果目录；配置表（agent 行写 `Qwen/Qwen3-1.7B`，bf16，无 quantization，GPU_UTIL 0.10，thinking 模式按 Task 8 决定；user sim 行加 `max-num-seqs 32`，并注明与 4B run 并行共用）；Headline：overall pass^1、short/long、**含与不含 no-op gold 两版**；per-env 表 加一列 32B 数值做对照；失败归因表用 Step 1 输出，类别与 32B 报告一致（多 block 丢写入 / 错值 / 没写 / 部分写 / 多写表 / gold no-op / 异常终止），并单列 `length_no_content`、`context_overflow`、`max_steps` 计数；Ops 段记录三容器内存分配、user sim 峰值 Running、两条 run 的起止时间和是否发生续跑。

- [ ] **Step 3: 写三模型对比**

`docs/results/<YYYY-MM-DD>-agent-size-comparison.md`：一张表，行 = 1.7B / 4B / 32B-AWQ，列 = overall pass^1、short、long、excl. no-op、平均步数、agent tok/run、fab rate、multi-sql 率、unexecuted-write 率、length_no_content、context_overflow、max_steps、墙钟。下面用 3 到 5 句写结论：哪些失败类别随模型变小增长最快（这直接决定 GRPO 的第一批 reward 项），以及 1.7B 零样本是否低到需要 SFT/RFT 热启动（对应研究计划 step 4）。

- [ ] **Step 4: 提交**

```bash
cd /home/wmd3i/Documents/Isa/DySQL-Bench
cp DySQL-Bench/results/full_qwen3_1.7b_think_on_c16/summary.md docs/results/$(date +%F)-qwen3-1.7b-full-summary.md
cp DySQL-Bench/results/full_qwen3_4b_think_on_c16/summary.md   docs/results/$(date +%F)-qwen3-4b-full-summary.md
git add docs/results/
git commit -m "docs: Qwen3-1.7B and Qwen3-4B zero-shot agent baselines (full 1062) + size comparison vs 32B-AWQ

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## 自查

- **覆盖**：1.1 setup → Task 6/7；1.2 配置差异 → Task 2/7；1.3 分支 → Task 1（提交后再跑）；1.4 命名 → Task 4/5/9/10；1.5 注意点 → Global Constraints、Task 7 顺序、Task 9 Step 3；thinking 门槛 → Task 8。
- **接口一致性**：`SERVED_NAME=qwen3-1.7b/qwen3-4b`（Task 7）= `MODEL=qwen3-1.7b/qwen3-4b`（Task 8/9 传给 run.py 的 `--model`）；端口 8000/8002 与容器名 `dysql-agent-1.7b/-4b` 在 Task 7、8、9、progress.sh 参数中一致；`ENV_ORDER=reverse` 只在 4B run 使用。
- **不做的事**：不改 harness Python（Task 1b 的目录名除外）、不改 wiki、不截断 SELECT、不调 max_tokens、不重启 user sim、不用 handover_restart.sh。
