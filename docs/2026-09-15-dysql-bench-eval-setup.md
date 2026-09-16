# DySQL-Bench 评测环境搭建与 Qwen3-32B-AWQ 基线 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 GB10 上跑通 DySQL-Bench，以 Qwen3-32B-AWQ 为 agent、Qwen2.5-72B-Instruct-AWQ 为 user sim，先小子集后全量，产出带完整分析字段的日志和一份基线报告。本轮（第一轮）目标缩为：pagila 5 个任务、thinking 开、并发 5，验证能跑、测吞吐、补日志、预估全量耗时；pass rate 不在本轮结论范围内。

**Architecture:** 两个 vLLM docker 容器分别服务 agent 和 user sim（端口 8000 / 8001，共享 GB10 统一内存）。DySQL-Bench 的 fork 上打一层"分析日志"补丁（每轮 token/耗时/finish_reason、终止原因、伪造 `<result>` 检测、按表 hash diff、任务元信息、断点续跑），不改评测语义。先跑 pagila 5 个任务（3 short + 2 long）的 pilot 校准耗时和日志格式，再放全量。3 库 × 8 任务、thinking on/off 对比留作第二轮可选项。

**Tech Stack:** docker + `vllm/vllm-openai:cu130-nightly`（GB10 上已验证可用）、conda python 3.11、DySQL-Bench（pydantic / sqlparse / requests）、pytest、huggingface_hub CLI。

**Spec:** 本次没有独立 spec 文档。需求来自本对话的三条结论：先小子集再全量；按真实负载测吞吐；日志字段清单（每轮完整消息含 thinking、SQL 执行结果与伪造检测、终止原因、按表 hash diff、每轮 token 与耗时、任务元信息）。

## Global Constraints

- 硬件：单卡 NVIDIA GB10，128GB 统一内存，driver 580 / CUDA 13.0。两个模型服务的 `--gpu-memory-utilization` 之和不超过 0.72。
- 推理镜像固定用 `vllm/vllm-openai:cu130-nightly`（本机已有，image id ffa30d66ff5c）。不要 `docker pull` 更新它，避免 sm_121 兼容性回退。
- 采样参数与论文对齐：temperature 0.6、top_p 0.95、top_k 20、min_p 0、max_tokens 8192、max turns 30。
- **thinking 一律开启**（用户已决定，与论文 Qwen3-32B 对齐）。agent 服务 `--max-model-len 40960`（Qwen3-32B 原生上限；系统提示 pagila 约 11KB、eu_soccer 约 14KB，30 轮 + 8192 max_tokens 下 32768 会撞 400）。
- 任务总数按代码实际为 **1062**（13 个库 tasks_test 之和），论文写 1072，估时与 summarize 一律用 1062。
- 本轮不加 1.7B / 4B 的 agent 服务脚本，内存分配只按两个服务切；三服务方案放到 pilot 之后。
- 评测语义（状态 hash 判定、`###STOP###` 终止、user sim 系统提示词）一律不改。只允许**增加**日志字段。
- 所有新增代码放在 fork 的 `isa/eval-harness` 分支。每个 Task 结束时 commit。
- 模型：agent = `Qwen/Qwen3-32B-AWQ`，user sim = `Qwen/Qwen2.5-72B-Instruct-AWQ`。served-model-name 分别固定为 `qwen3-32b-awq` 和 `qwen2.5-72b-awq`。
- 目录：fork **已经**克隆在 `~/Documents/Isa/DySQL-Bench`（origin 为 https 的 `FangzhiLi/DySQL-Bench`，当前只有 main 分支）；conda 环境名 `dysql`；结果写到 `~/Documents/Isa/DySQL-Bench/DySQL-Bench/results/`。
- `.gitignore` 里现有的 `docs/` 一行要**去掉**（用户已决定），否则本计划所有 docs 产出都不入库。
- 当前机器状态（2026-09-15）：conda 环境未建、13 个 sqlite 未下载、两个模型未下载；docker 镜像 `vllm/vllm-openai:cu130-nightly` 已在；磁盘剩 2.7T。模型下载是本轮最先启动的耗时项。

---

## 文件结构

fork 内（相对 `~/Documents/Isa/DySQL-Bench/DySQL-Bench/`）：

| 路径 | 职责 |
|---|---|
| `scripts/serve_user_sim.sh` | 起 72B-AWQ user sim 容器（端口 8001） |
| `scripts/serve_agent.sh` | 起 Qwen3-32B-AWQ agent 容器（端口 8000），`THINKING=on/off` 环境变量控制，默认 on |
| `scripts/wait_ready.sh` | 轮询 `/v1/models` 直到两个服务就绪 |
| `scripts/bench_throughput.py` | （本轮跳过，可选）按合成负载测并发吞吐 |
| `dysql_bench/analysis.py` | 纯函数：任务元信息分类、伪造 `<result>` 检测、按表 hash diff 比较、SQL 报错计数、写前确认判定 |
| `dysql_bench/agents/sql_calling_agent.py` | 修改：请求带 `model`、剥离历史消息里的 `reasoning_content`、记录每轮 usage/finish_reason/耗时、记录终止原因 |
| `dysql_bench/envs/user.py` | 修改：user sim 请求同样记录 usage 与耗时 |
| `dysql_bench/envs/base.py` | 修改：`get_data_hash` 同时返回按表 hash；reward info 增加 `mismatched_tables` |
| `dysql_bench/types.py` | 修改：`RewardActionInfo` 增加 `mismatched_tables`；`EnvRunResult` 增加 `meta` |
| `dysql_bench/run.py` | 修改：写入任务元信息与终止原因；`--resume` 跳过已完成 (task_id, trial) |
| `run.py` | 修改：新增 `--resume` 参数 |
| `scripts/pick_pilot_tasks.py` | 用 `classify_task` 从 pagila 挑 3 short + 2 long 任务 id |
| `scripts/run_pilot.sh` | pagila 5 任务、并发 5、thinking on 的 pilot |
| `scripts/estimate_full.py` | 从 pilot 结果按墙钟和 token 两种口径估全量耗时 |
| `scripts/run_full.sh` | 13 个库全量，nohup + resume |
| `scripts/summarize.py` | 从 results JSON 汇总 pass^k、耗时、token、幻觉率、终止原因、按表失配、SQL 报错率、写前确认率、末轮 prompt 长度，输出 markdown |
| `tests/test_analysis.py` | analysis.py 纯函数测试 |
| `tests/test_agent_logging.py` | monkeypatch `requests.post`，验证 agent 每轮日志字段 |
| `tests/test_env_hash.py` | 内存 sqlite 上验证按表 hash diff |
| `tests/test_resume.py` | 验证 resume 跳过逻辑 |

---

### Task 1: 配置 fork 远端与分支、建环境、拉数据库

**Files:**
- Modify: `~/Documents/Isa/DySQL-Bench/`（已 clone，加 upstream、建分支）
- Modify: `.gitignore` 去掉 `docs/` 一行；`results/`、`logs/`、`*.sqlite` 已在上游 ignore 则跳过

**Interfaces:**
- Produces: conda 环境 `dysql`；13 个库的 sqlite 在 `dysql_bench/envs/<env>/data/`；分支 `isa/eval-harness`

- [ ] **Step 1: 确认 fork 已在本地且工作区干净**

Run: `cd ~/Documents/Isa/DySQL-Bench && git remote -v && git status --short`
Expected: origin 指向 `https://github.com/FangzhiLi/DySQL-Bench.git`；status 只有 ` M .gitignore`（另一会话加的 `docs/`）。

- [ ] **Step 2: 加 upstream、建分支、修 .gitignore**

```bash
cd ~/Documents/Isa/DySQL-Bench
git remote add upstream https://github.com/Aurora-slz/DySQL-Bench.git
git checkout -b isa/eval-harness
sed -i '/^docs\/$/d' .gitignore
```

Run: `grep -c '^docs/$' .gitignore; git branch --show-current`
Expected: `0` 和 `isa/eval-harness`。注意 docs 目录在仓库根，不在 `DySQL-Bench/DySQL-Bench/` 下。

- [ ] **Step 3: 建 conda 环境并安装**

```bash
conda create -n dysql python=3.11 -y
conda run -n dysql pip install -e ~/Documents/Isa/DySQL-Bench/DySQL-Bench
conda run -n dysql pip install requests tqdm pydantic sqlparse "huggingface_hub[cli]" pytest
```

Run: `conda run -n dysql python -c "import dysql_bench, sqlparse, pydantic; print('ok')"`
Expected: `ok`

- [ ] **Step 4: 拉 13 个数据库**

```bash
cd ~/Documents/Isa/DySQL-Bench/DySQL-Bench
conda run -n dysql python ./scripts/fetch_dbs.py --all
```

Run: `find dysql_bench/envs -name '*.sqlite' | wc -l`
Expected: `13`

- [ ] **Step 5: 校验任务总数**

```bash
conda run -n dysql python - <<'EOF'
import importlib
envs = ["pagila","retail","bowling","chinook","entertainment","eu_soccer","music","car","cookbook","human_resources","ice_hockey","law_episode","retail_world"]
total = 0
for e in envs:
    m = importlib.import_module(f"dysql_bench.envs.{e}.tasks_test")
    n = len(m.TASKS_TEST); total += n
    print(f"{e:16s} {n}")
print("TOTAL", total)
EOF
```

Expected: TOTAL 为 1062（pagila 105、retail 205、eu_soccer 215、entertainment 131、bowling 111、law_episode 53、cookbook 52、chinook 44、human_resources 40、retail_world 31、ice_hockey 28、car 27、music 21）。把每个库的数字记入 `docs/task_counts.md`（新建文件，一行一库）。这个数字后面估时和 summarize 要用。注意不要在 `dysql_bench/` 目录内直接跑 python，该目录下的 `types.py` 会遮蔽标准库。

- [ ] **Step 6: Commit**

```bash
git add .gitignore docs/task_counts.md
git commit -m "chore: record task counts, stop ignoring docs/"
```

---

### Task 2: 下载两个模型

**Files:**
- 无代码。模型进 `~/.cache/huggingface/hub/`

**Interfaces:**
- Produces: `models--Qwen--Qwen3-32B-AWQ`、`models--Qwen--Qwen2.5-72B-Instruct-AWQ`

- [ ] **Step 1: 后台下载（约 60GB，磁盘剩 2.7T）**

```bash
conda run -n dysql hf download Qwen/Qwen3-32B-AWQ > /tmp/dl_agent.log 2>&1 &
conda run -n dysql hf download Qwen/Qwen2.5-72B-Instruct-AWQ > /tmp/dl_user.log 2>&1 &
```

- [ ] **Step 2: 校验完整性**

Run:
```bash
ls ~/.cache/huggingface/hub/models--Qwen--Qwen3-32B-AWQ/snapshots/*/ | grep -c safetensors
ls ~/.cache/huggingface/hub/models--Qwen--Qwen2.5-72B-Instruct-AWQ/snapshots/*/ | grep -c safetensors
```
Expected: 两个数字都大于 0，且 `model.safetensors.index.json` 存在。下载期间可并行做 Task 3 的脚本编写和 Task 5 的补丁。

---

### Task 3: 服务脚本与就绪检查

**Files:**
- Create: `scripts/serve_user_sim.sh`
- Create: `scripts/serve_agent.sh`
- Create: `scripts/wait_ready.sh`

**Interfaces:**
- Produces: `http://127.0.0.1:8000`（agent，served name `qwen3-32b-awq`）、`http://127.0.0.1:8001`（user sim，served name `qwen2.5-72b-awq`）

- [ ] **Step 1: 写 user sim 启动脚本**

```bash
#!/usr/bin/env bash
# scripts/serve_user_sim.sh  -- Qwen2.5-72B-Instruct-AWQ on :8001
set -euo pipefail
docker rm -f dysql-user 2>/dev/null || true
docker run -d --name dysql-user --restart unless-stopped \
  --gpus all --ipc host --shm-size 64gb \
  -p 8001:8001 \
  -v ~/.cache/huggingface:/root/.cache/huggingface \
  vllm/vllm-openai:cu130-nightly \
  Qwen/Qwen2.5-72B-Instruct-AWQ \
  --served-model-name qwen2.5-72b-awq \
  --host 0.0.0.0 --port 8001 \
  --quantization awq_marlin \
  --max-model-len 16384 \
  --max-num-seqs 8 \
  --gpu-memory-utilization 0.42 \
  --enable-prefix-caching
echo "user sim starting; logs: docker logs -f dysql-user"
```

- [ ] **Step 2: 写 agent 启动脚本（thinking 可切换）**

```bash
#!/usr/bin/env bash
# scripts/serve_agent.sh -- Qwen3-32B-AWQ on :8000. THINKING=on|off (default on)
set -euo pipefail
THINKING="${THINKING:-on}"
if [ "$THINKING" = "on" ]; then KW='{"enable_thinking": true}'; else KW='{"enable_thinking": false}'; fi
docker rm -f dysql-agent 2>/dev/null || true
docker run -d --name dysql-agent --restart unless-stopped \
  --gpus all --ipc host --shm-size 64gb \
  -p 8000:8000 \
  -v ~/.cache/huggingface:/root/.cache/huggingface \
  vllm/vllm-openai:cu130-nightly \
  Qwen/Qwen3-32B-AWQ \
  --served-model-name qwen3-32b-awq \
  --host 0.0.0.0 --port 8000 \
  --quantization awq_marlin \
  --max-model-len 40960 \
  --max-num-seqs 8 \
  --gpu-memory-utilization 0.28 \
  --enable-prefix-caching \
  --reasoning-parser qwen3 \
  --default-chat-template-kwargs "$KW"
echo "agent starting with thinking=$THINKING; logs: docker logs -f dysql-agent"
```

说明：`--reasoning-parser qwen3` 让思考内容进入 API 的 `reasoning_content` 字段而不是混在 content 里，这样截断时不会把思考里的 SQL 误当动作。Task 5 会把该字段记进日志。

- [ ] **Step 3: 写就绪检查脚本**

```bash
#!/usr/bin/env bash
# scripts/wait_ready.sh -- block until both servers answer /v1/models (timeout 30 min)
set -u
for i in $(seq 1 180); do
  a=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/v1/models || true)
  u=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8001/v1/models || true)
  if [ "$a" = "200" ] && [ "$u" = "200" ]; then echo "both ready"; exit 0; fi
  sleep 10
done
echo "timeout"; exit 1
```

- [ ] **Step 4: 启动并做冒烟请求**

```bash
chmod +x scripts/*.sh
bash scripts/serve_user_sim.sh
bash scripts/serve_agent.sh
bash scripts/wait_ready.sh
curl -s http://127.0.0.1:8000/v1/chat/completions -H 'Content-Type: application/json' \
  -d '{"model":"qwen3-32b-awq","messages":[{"role":"user","content":"Write one SQL that counts rows in table t."}],"max_tokens":64}'
curl -s http://127.0.0.1:8001/v1/chat/completions -H 'Content-Type: application/json' \
  -d '{"model":"qwen2.5-72b-awq","messages":[{"role":"user","content":"Say hi in one line."}],"max_tokens":16}'
```

Expected: 两个都返回 JSON 且 `choices[0].message.content` 非空。agent 在 thinking=on 时 `reasoning_content` 非空且 content 里不含 `<think>`。

**如果 AWQ 在 sm_121 上加载失败**（日志出现 `awq_marlin` / `Marlin` 不支持或 CUDA kernel 报错）：先试去掉 `--quantization awq_marlin` 让 vLLM 自选；仍失败则切换备选模型 `Qwen/Qwen3-32B-FP8` 和 `Qwen/Qwen2.5-72B-Instruct-GPTQ-Int4`，并把改动同步到 served-model-name 以外的参数。把结论记入 `docs/gb10_serving_notes.md`。

- [ ] **Step 5: 记录显存占用并 commit**

Run: `nvidia-smi --query-gpu=memory.used --format=csv` 与 `free -g`，把数字写进 `docs/gb10_serving_notes.md`。

```bash
git add scripts/serve_user_sim.sh scripts/serve_agent.sh scripts/wait_ready.sh docs/gb10_serving_notes.md
git commit -m "feat: vLLM serving scripts for agent and user sim on GB10"
```

---

### Task 4: （本轮跳过）按合成负载测吞吐

> **本轮不做。** 5 个真实任务并发跑本身就是负载测试，且带每轮 usage / latency 日志，比合成 prompt 更准。下面的脚本和阈值保留为第二轮可选项；其中 40 / 60 tok/s 的判定阈值是拍的，无依据，用时需重新定。

**Files:**
- Create: `scripts/bench_throughput.py`
- Create: `results/throughput/`（运行产物，不入库）

**Interfaces:**
- Produces: `results/throughput/<name>_c<N>.json`，字段 `concurrency, n_requests, prompt_tokens_avg, completion_tokens_avg, wall_s, gen_tok_per_s, p50_latency_s, p95_latency_s`

- [ ] **Step 1: 写测试脚本**

```python
#!/usr/bin/env python3
"""Measure chat-completions throughput with DySQL-shaped prompts.
Usage: python scripts/bench_throughput.py --api http://127.0.0.1:8000 --model qwen3-32b-awq \
         --concurrency 1 4 8 --max-tokens 1024 --n 16 --out results/throughput/agent
"""
import argparse, json, os, statistics, time
from concurrent.futures import ThreadPoolExecutor
import requests
from dysql_bench.envs.pagila.wiki import WIKI
from dysql_bench.envs.pagila.tasks_test import TASKS_TEST

def one(api, model, max_tokens, task):
    msgs = [{"role": "system", "content": WIKI},
            {"role": "user", "content": task.instruction},
            {"role": "assistant", "content": "I will first look up your record."},
            {"role": "user", "content": "Okay, please proceed and explain each SQL you run."}]
    t0 = time.time()
    r = requests.post(f"{api}/v1/chat/completions", json={
        "model": model, "messages": msgs, "max_tokens": max_tokens,
        "temperature": 0.6, "top_p": 0.95, "top_k": 20}).json()
    dt = time.time() - t0
    u = r["usage"]
    return dt, u["prompt_tokens"], u["completion_tokens"]

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--api", required=True); p.add_argument("--model", required=True)
    p.add_argument("--concurrency", type=int, nargs="+", default=[1, 4, 8])
    p.add_argument("--max-tokens", type=int, default=1024)
    p.add_argument("--n", type=int, default=16)
    p.add_argument("--out", required=True)
    a = p.parse_args()
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    tasks = (TASKS_TEST * 10)[: a.n]
    for c in a.concurrency:
        t0 = time.time()
        with ThreadPoolExecutor(c) as ex:
            rows = list(ex.map(lambda t: one(a.api, a.model, a.max_tokens, t), tasks))
        wall = time.time() - t0
        lat = [r[0] for r in rows]; pt = [r[1] for r in rows]; ct = [r[2] for r in rows]
        res = {"concurrency": c, "n_requests": len(rows),
               "prompt_tokens_avg": statistics.mean(pt), "completion_tokens_avg": statistics.mean(ct),
               "wall_s": wall, "gen_tok_per_s": sum(ct) / wall,
               "p50_latency_s": statistics.median(lat),
               "p95_latency_s": sorted(lat)[int(0.95 * (len(lat) - 1))]}
        print(json.dumps(res))
        with open(f"{a.out}_c{c}.json", "w") as f: json.dump(res, f, indent=2)

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 分别测 agent 和 user sim，再同时测**

```bash
cd ~/Documents/Isa/DySQL-Bench/DySQL-Bench
conda run -n dysql python scripts/bench_throughput.py --api http://127.0.0.1:8000 --model qwen3-32b-awq --max-tokens 1024 --out results/throughput/agent
conda run -n dysql python scripts/bench_throughput.py --api http://127.0.0.1:8001 --model qwen2.5-72b-awq --max-tokens 200 --out results/throughput/user
# 同时压两边，模拟真实评测
conda run -n dysql python scripts/bench_throughput.py --api http://127.0.0.1:8000 --model qwen3-32b-awq --max-tokens 1024 --concurrency 4 --out results/throughput/agent_concurrent &
conda run -n dysql python scripts/bench_throughput.py --api http://127.0.0.1:8001 --model qwen2.5-72b-awq --max-tokens 200 --concurrency 4 --out results/throughput/user_concurrent
wait
```

Expected: 每个命令输出 3 行（或 1 行）JSON。

- [ ] **Step 3: 判定与记录**

把所有 JSON 汇成一张表写进 `docs/gb10_serving_notes.md`。判定规则：
- 并发 4 下两边同时压，user sim `gen_tok_per_s` ≥ 40 且 agent ≥ 60 → 72B 方案可用，进入 Task 5。
- 不满足 → 记录数字，停下来向用户汇报，由用户决定是换 Qwen3-32B-AWQ 做 user sim 还是接受更长的全量时间。

```bash
git add scripts/bench_throughput.py docs/gb10_serving_notes.md
git commit -m "feat: throughput benchmark with DySQL-shaped prompts"
```

---

### Task 5: 分析日志补丁（纯函数部分）

**Files:**
- Create: `dysql_bench/analysis.py`
- Test: `tests/test_analysis.py`

**Interfaces:**
- Produces:
  - `classify_task(task: Task) -> dict` 返回 `{"n_gold_actions": int, "length": "short"|"long", "crud_types": list[str]}`
  - `count_fabricated_results(traj: list[dict]) -> int` 统计 assistant 消息 content 里出现 `<result>` 的条数
  - `diff_table_hashes(a: dict[str,str], b: dict[str,str]) -> list[str]` 返回两边 hash 不同的表名（排序）
  - `count_sql_errors(traj: list[dict]) -> int` 统计 `name == "sql"` 的 user 消息里 `<result>Error:` 开头的条数
  - `confirmed_before_write(traj: list[dict]) -> Optional[bool]` 第一条非 SELECT 的 agent SQL 之前，是否有 user 消息含 yes / confirm / proceed（大小写不敏感）；trajectory 里没有写操作返回 None

- [ ] **Step 1: 写失败测试**

```python
# tests/test_analysis.py
from dysql_bench.types import Task, Action
from dysql_bench.analysis import (classify_task, count_fabricated_results, diff_table_hashes,
                                  count_sql_errors, confirmed_before_write)

def _task(sqls):
    return Task(user_id="1", instruction="x",
                actions=[Action(name="sql", kwargs={"sql": s}) for s in sqls])

def test_classify_short_long_and_crud():
    t = _task(["DELETE FROM payment WHERE id=1", "UPDATE rental SET x=1"])
    assert classify_task(t) == {"n_gold_actions": 2, "length": "short", "crud_types": ["DELETE", "UPDATE"]}
    t3 = _task(["INSERT INTO a VALUES (1)", "SELECT 1", "UPDATE a SET b=2"])
    assert classify_task(t3)["length"] == "long"
    assert classify_task(t3)["crud_types"] == ["INSERT", "SELECT", "UPDATE"]

def test_count_fabricated_results():
    traj = [{"role": "system", "content": "<result> in system is fine"},
            {"role": "assistant", "content": "```sql\nSELECT 1\n```\n<result>[(1,)]</result>"},
            {"role": "user", "name": "sql", "content": "<result>[(1,)]</result>"},
            {"role": "assistant", "content": "Done."}]
    assert count_fabricated_results(traj) == 1

def test_diff_table_hashes():
    a = {"t1": "h1", "t2": "h2", "t3": "h3"}
    b = {"t1": "h1", "t2": "zz", "t3": "yy"}
    assert diff_table_hashes(a, b) == ["t2", "t3"]

def test_count_sql_errors():
    traj = [{"role": "user", "name": "sql", "content": "<result>Error: no such table: x\n</result>"},
            {"role": "user", "name": "sql", "content": "<result>[(1,)]</result>"},
            {"role": "user", "content": "<result>Error: not from sql</result>"}]
    assert count_sql_errors(traj) == 1

def test_confirmed_before_write():
    sel = {"role": "assistant", "content": "```sql\nSELECT 1\n```"}
    upd = {"role": "assistant", "content": "```sql\nUPDATE a SET b=1\n```"}
    assert confirmed_before_write([sel, {"role": "user", "content": "Yes, go ahead"}, upd]) is True
    assert confirmed_before_write([sel, {"role": "user", "content": "what next?"}, upd]) is False
    assert confirmed_before_write([sel]) is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `conda run -n dysql pytest tests/test_analysis.py -v`
Expected: FAIL，`ModuleNotFoundError: dysql_bench.analysis`

- [ ] **Step 3: 实现**

```python
# dysql_bench/analysis.py
"""Pure helpers used for logging / post-hoc analysis. No evaluation semantics live here."""
import re
from typing import Dict, List, Optional
import sqlparse
from dysql_bench.types import Task, SQL_ACTION_NAME

SHORT_MAX_ACTIONS = 2  # paper: fewer than three actions = Short

def classify_task(task: Task) -> dict:
    sqls = [a.kwargs["sql"] for a in task.actions if a.name == SQL_ACTION_NAME]
    types = set()
    for s in sqls:
        for stmt in sqlparse.split(s):
            stmt = stmt.strip()
            if stmt:
                types.add(sqlparse.parse(stmt)[0].get_type().upper())
    return {"n_gold_actions": len(sqls),
            "length": "short" if len(sqls) <= SHORT_MAX_ACTIONS else "long",
            "crud_types": sorted(types)}

def count_fabricated_results(traj: List[dict]) -> int:
    return sum(1 for m in traj if m.get("role") == "assistant" and "<result>" in (m.get("content") or ""))

def diff_table_hashes(a: Dict[str, str], b: Dict[str, str]) -> List[str]:
    return sorted(t for t in set(a) | set(b) if a.get(t) != b.get(t))

def count_sql_errors(traj: List[dict]) -> int:
    return sum(1 for m in traj
               if m.get("role") == "user" and m.get("name") == "sql"
               and (m.get("content") or "").lstrip().startswith("<result>Error:"))

_SQL_BLOCK = re.compile(r"```sql(.*?)```|<sql>(.*?)</sql>", re.DOTALL)
_CONFIRM = re.compile(r"\b(yes|confirm|confirmed|proceed|go ahead)\b", re.IGNORECASE)

def _first_sql(content: str) -> Optional[str]:
    m = _SQL_BLOCK.search(content or "")
    return (m.group(1) or m.group(2)).strip() if m else None

def confirmed_before_write(traj: List[dict]) -> Optional[bool]:
    seen_confirm = False
    for m in traj:
        if m.get("role") == "user" and m.get("name") != "sql":
            if _CONFIRM.search(m.get("content") or ""):
                seen_confirm = True
        elif m.get("role") == "assistant":
            sql = _first_sql(m.get("content"))
            if sql and sqlparse.parse(sql) and sqlparse.parse(sql)[0].get_type().upper() not in ("SELECT", "UNKNOWN"):
                return seen_confirm
    return None
```

文件顶部 import 改为 `import re` 加 `from typing import Dict, List, Optional`。`confirmed_before_write` 是规则粗判，只用于分析和后续 reward shaping 的候选，不进评测。

- [ ] **Step 4: 跑测试确认通过**

Run: `conda run -n dysql pytest tests/test_analysis.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add dysql_bench/analysis.py tests/test_analysis.py
git commit -m "feat: analysis helpers (task classification, fabricated result count, table diff)"
```

---

### Task 6: 按表 hash diff 进 reward info

**Files:**
- Modify: `dysql_bench/types.py`（`RewardActionInfo`）
- Modify: `dysql_bench/envs/base.py`（`get_data_hash`、`calculate_reward`）
- Test: `tests/test_env_hash.py`

**Interfaces:**
- Consumes: `diff_table_hashes` from Task 5
- Produces: `Env.get_table_hashes() -> dict[str,str]`；`get_data_hash()` 行为不变；`RewardActionInfo.mismatched_tables: list[str]`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_env_hash.py
import sqlite3, os, tempfile
from dysql_bench.envs.base import Env
from dysql_bench.types import Task, Action

def _make_db(dirpath):
    p = os.path.join(dirpath, "t.sqlite")
    c = sqlite3.connect(p); cur = c.cursor()
    cur.execute("CREATE TABLE a(id INTEGER, v TEXT)"); cur.execute("CREATE TABLE b(id INTEGER)")
    cur.execute("INSERT INTO a VALUES (1,'x')"); cur.execute("INSERT INTO b VALUES (1)"); c.commit()
    return c, cur, dirpath

def _env(tmp):
    task = Task(user_id="1", instruction="i",
                actions=[Action(name="sql", kwargs={"sql": "UPDATE a SET v='y' WHERE id=1"})])
    return Env(data_load_func=lambda tid: _make_db(tmp), table_names=["a", "b"], tasks=[task],
               wiki="w", user_strategy="human", user_model="", user_model_api="", task_index=0)

def test_table_hashes_and_mismatch(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        env = _env(tmp)
        h = env.get_table_hashes()
        assert set(h) == {"a", "b"}
        env.cursor.execute("UPDATE a SET v='wrong' WHERE id=1"); env.conn.commit()
        monkeypatch.setattr(env, "delete_db", lambda: None)
        res = env.calculate_reward()
        assert res.reward == 0.0
        assert res.info.mismatched_tables == ["a"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `conda run -n dysql pytest tests/test_env_hash.py -v`
Expected: FAIL，`AttributeError: 'Env' object has no attribute 'get_table_hashes'`

- [ ] **Step 3: 改 types.py**

在 `RewardActionInfo` 加一个字段：

```python
class RewardActionInfo(BaseModel):
    r_actions: float
    gt_data_hash: str
    mismatched_tables: List[str] = []
```

- [ ] **Step 4: 改 base.py**

把现有 `get_data_hash` 的循环体抽成 `get_table_hashes`，`get_data_hash` 基于它计算总 hash（保持原语义：总 hash 仍是对全部表数据的一次 hash，不是对表 hash 列表的 hash，以免改变判定）：

```python
    def _collect_table_data(self) -> list:
        all_data = []
        self.cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        all_tables = {row[0] for row in self.cursor.fetchall()} - IGNORE_TABLES
        for table in self.table_names:
            if table not in all_tables:
                continue
            self.cursor.execute(f'PRAGMA table_info("{table}")')
            cols = [c[1] for c in self.cursor.fetchall()]
            if not cols:
                all_data.append((table, ())); continue
            stable_cols = [c for c in cols if not VOLATILE_COL_RE.match(c)]
            if stable_cols:
                sel = ", ".join(f'"{c}"' for c in stable_cols)
                self.cursor.execute(f'SELECT {sel} FROM "{table}" ORDER BY {sel}, rowid')
                all_data.append((table, tuple(self.cursor.fetchall())))
            else:
                self.cursor.execute(f'SELECT COUNT(*) FROM "{table}"')
                all_data.append((table, ("__ONLY_ROWCOUNT__", self.cursor.fetchone()[0])))
        return all_data

    def get_table_hashes(self) -> Dict[str, str]:
        return {t: consistent_hash(to_hashable(rows)) for t, rows in self._collect_table_data()}

    def get_data_hash(self) -> str:
        return consistent_hash(to_hashable(self._collect_table_data()))
```

`calculate_reward` 里在计算 agent 侧 `data_hash` 的同时取 `agent_tables = self.get_table_hashes()`，在 gold 侧取 `gt_tables = self.get_table_hashes()`，然后：

```python
        from dysql_bench.analysis import diff_table_hashes
        info = RewardActionInfo(
            r_actions=data_hash == gt_data_hash,
            gt_data_hash=gt_data_hash,
            mismatched_tables=diff_table_hashes(agent_tables, gt_tables),
        )
```

注意原代码里 `ob` 变量和 `sel` 相同，合并成一个即可，SQL 不变。`IGNORE_TABLES` 在 base.py 第 30 行已定义，直接用。

- [ ] **Step 5: 跑测试确认通过**

Run: `conda run -n dysql pytest tests/test_env_hash.py tests/test_analysis.py -v`
Expected: 6 passed

- [ ] **Step 6: Commit**

```bash
git add dysql_bench/types.py dysql_bench/envs/base.py tests/test_env_hash.py
git commit -m "feat: per-table hash diff in reward info (evaluation semantics unchanged)"
```

---

### Task 7: agent 与 user sim 每轮日志

**Files:**
- Modify: `dysql_bench/agents/sql_calling_agent.py`
- Modify: `dysql_bench/envs/user.py`
- Test: `tests/test_agent_logging.py`

**Interfaces:**
- Produces: traj 里每条 assistant 消息带 `reasoning_content`、`finish_reason`、`usage`（`{"prompt_tokens","completion_tokens"}`）、`latency_s`；`SolveResult.info["termination"]` ∈ `{"user_stop","max_steps","error"}`；`SolveResult.info["n_steps"]`；user sim 消息带 `usage` 与 `latency_s` 存到 `env.user.messages`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_agent_logging.py
import types
from dysql_bench.agents import sql_calling_agent as sca
from dysql_bench.types import EnvResetResponse, EnvResponse, EnvInfo, Task

class FakeEnv:
    def __init__(self):
        self.task = Task(user_id="1", instruction="i", actions=[])
        self.calls = 0
    def reset(self, task_index=None):
        return EnvResetResponse(observation="hi", info=EnvInfo(task=self.task, source="user"))
    def step(self, action):
        self.calls += 1
        return EnvResponse(observation="###STOP###", reward=1.0, done=True, info=EnvInfo(task=self.task))

def _fake_post(url, headers=None, json=None):
    assert json["model"] == "m"
    for m in json["messages"]:
        assert "reasoning_content" not in m
    body = {"choices": [{"message": {"content": "Sure.", "reasoning_content": "thinking..."},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 3}}
    return types.SimpleNamespace(json=lambda: body)

def test_agent_logs_turn_fields(monkeypatch):
    monkeypatch.setattr(sca.requests, "post", _fake_post)
    agent = sca.SQLCallingAgent(api="http://x", wiki="w", model="m")
    res = agent.solve(FakeEnv(), task_index=0, max_num_steps=5)
    a = [m for m in res.messages if m["role"] == "assistant"][0]
    assert a["reasoning_content"] == "thinking..."
    assert a["finish_reason"] == "stop"
    assert a["usage"] == {"prompt_tokens": 10, "completion_tokens": 3}
    assert a["latency_s"] >= 0
    assert res.info["termination"] == "user_stop"
    assert res.info["n_steps"] == 1

def test_agent_max_steps(monkeypatch):
    monkeypatch.setattr(sca.requests, "post", _fake_post)
    class NeverDone(FakeEnv):
        def step(self, action):
            return EnvResponse(observation="more?", reward=0.0, done=False, info=EnvInfo(task=self.task))
    res = sca.SQLCallingAgent(api="http://x", wiki="w", model="m").solve(NeverDone(), 0, max_num_steps=2)
    assert res.info["termination"] == "max_steps"
    assert res.info["n_steps"] == 2
```

- [ ] **Step 2: 跑测试确认失败**

Run: `conda run -n dysql pytest tests/test_agent_logging.py -v`
Expected: FAIL（`KeyError: 'finish_reason'` 或 model 断言失败）

- [ ] **Step 3: 改 sql_calling_agent.py 的 solve**

```python
    def _api_messages(self, messages):
        keep = ("role", "content", "name")
        return [{k: m[k] for k in keep if k in m} for m in messages]

    def solve(self, env, task_index=None, max_num_steps=30):
        env_reset_res = env.reset(task_index=task_index)
        obs = env_reset_res.observation
        info = env_reset_res.info.model_dump()
        reward = 0.0
        messages = [{"role": "system", "content": self.wiki}, {"role": "user", "content": obs}]
        termination, n_steps = "max_steps", 0
        for _ in range(max_num_steps):
            t0 = time.time()
            response = requests.post(
                self.api + "/v1/chat/completions",
                headers={"Content-Type": "application/json"},
                json={"model": self.model, "messages": self._api_messages(messages),
                      "max_tokens": self.max_tokens, "temperature": self.temperature,
                      "top_p": self.top_p, "top_k": self.top_k, "min_p": self.min_p},
            ).json()
            latency = time.time() - t0
            choice = response["choices"][0]
            next_message = self.parse_response(choice["message"]["content"])
            if choice["message"].get("reasoning_content") and not next_message["reasoning_content"]:
                next_message["reasoning_content"] = choice["message"]["reasoning_content"]
            next_message["finish_reason"] = choice.get("finish_reason")
            u = response.get("usage") or {}
            next_message["usage"] = {"prompt_tokens": u.get("prompt_tokens"),
                                     "completion_tokens": u.get("completion_tokens")}
            next_message["latency_s"] = round(latency, 3)
            n_steps += 1

            action = message_to_action(next_message)
            env_response = env.step(action)
            reward = env_response.reward
            info = {**info, **env_response.info.model_dump()}
            if action.name != RESPOND_ACTION_NAME:
                messages.extend([next_message, {"role": "user", "name": "sql", "content": env_response.observation}])
            else:
                messages.extend([next_message, {"role": "user", "content": env_response.observation}])
            if env_response.done:
                termination = "user_stop"
                break
        info["termination"] = termination
        info["n_steps"] = n_steps
        return SolveResult(reward=reward, info=info, messages=messages)
```

文件顶部加 `import time`。`parse_response` 保持不变（thinking 内联在 content 里的情况仍然处理）。

- [ ] **Step 4: 改 user.py 的 generate_next_message**

```python
    def generate_next_message(self, messages):
        t0 = time.time()
        response = requests.post(
            f"{self.api}/v1/chat/completions",
            headers={"Content-Type": "application/json"},
            json={"model": self.model,
                  "messages": [{k: m[k] for k in ("role", "content") if k in m} for m in messages],
                  "max_tokens": 8192, "temperature": 0.6, "top_p": 0.95, "top_k": 20, "min_p": 0.0},
        ).json()
        message = parse_response(response["choices"][0]["message"]["content"])
        u = response.get("usage") or {}
        message["usage"] = {"prompt_tokens": u.get("prompt_tokens"), "completion_tokens": u.get("completion_tokens")}
        message["latency_s"] = round(time.time() - t0, 3)
        self.messages.append({"role": "assistant", **message})
        return message["content"]
```

文件顶部加 `import time`。

- [ ] **Step 5: 跑全部测试**

Run: `conda run -n dysql pytest tests -v`
Expected: 8 passed

- [ ] **Step 6: Commit**

```bash
git add dysql_bench/agents/sql_calling_agent.py dysql_bench/envs/user.py tests/test_agent_logging.py
git commit -m "feat: per-turn logging (reasoning, finish_reason, usage, latency, termination)"
```

---

### Task 8: run.py 写入元信息、user sim 轨迹与断点续跑

**Files:**
- Modify: `dysql_bench/types.py`（`EnvRunResult`）
- Modify: `dysql_bench/run.py`
- Modify: `run.py`（CLI）
- Test: `tests/test_resume.py`

**Interfaces:**
- Consumes: `classify_task`、`count_fabricated_results`（Task 5）；`info["termination"]`（Task 7）
- Produces: `EnvRunResult.meta: dict` 含 `env, n_gold_actions, length, crud_types, termination, n_steps, n_fabricated_results, n_sql_errors, confirmed_before_write, mismatched_tables, wall_s, agent_completion_tokens, user_completion_tokens, last_prompt_tokens`；`EnvRunResult.user_traj: list`；`RunConfig.resume: Optional[str]`；`load_done(path) -> set[tuple[int,int]]`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_resume.py
import json, tempfile, os
from dysql_bench.run import load_done, build_meta
from dysql_bench.types import Task, Action

def test_load_done_reads_task_trial_pairs():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "ckpt.json")
        json.dump([{"task_id": 3, "trial": 0, "reward": 1, "info": {}, "traj": []},
                   {"task_id": 5, "trial": 1, "reward": 0, "info": {}, "traj": []}], open(p, "w"))
        assert load_done(p) == {(3, 0), (5, 1)}
    assert load_done("/nonexistent.json") == set()

def test_build_meta():
    task = Task(user_id="1", instruction="i", actions=[Action(name="sql", kwargs={"sql": "UPDATE a SET b=1"})])
    info = {"termination": "user_stop", "n_steps": 4,
            "reward_info": {"info": {"mismatched_tables": ["a"]}}}
    traj = [{"role": "assistant", "content": "<result>fake</result>",
             "usage": {"prompt_tokens": 4000, "completion_tokens": 5}},
            {"role": "user", "name": "sql", "content": "<result>Error: boom</result>"},
            {"role": "assistant", "content": "```sql\nUPDATE a SET b=1\n```",
             "usage": {"prompt_tokens": 4100, "completion_tokens": 3}}]
    user_traj = [{"role": "assistant", "content": "hi", "usage": {"completion_tokens": 7}}]
    m = build_meta("pagila", task, info, traj, user_traj, wall_s=12.5)
    assert m["length"] == "short" and m["crud_types"] == ["UPDATE"]
    assert m["termination"] == "user_stop" and m["n_steps"] == 4
    assert m["n_fabricated_results"] == 1 and m["mismatched_tables"] == ["a"]
    assert m["n_sql_errors"] == 1 and m["confirmed_before_write"] is False
    assert m["agent_completion_tokens"] == 8 and m["user_completion_tokens"] == 7
    assert m["last_prompt_tokens"] == 4100
    assert m["wall_s"] == 12.5
```

- [ ] **Step 2: 跑测试确认失败**

Run: `conda run -n dysql pytest tests/test_resume.py -v`
Expected: FAIL，`ImportError: cannot import name 'load_done'`

- [ ] **Step 3: 改 types.py**

```python
class EnvRunResult(BaseModel):
    task_id: int
    reward: float
    info: Dict[str, Any]
    traj: List[Dict[str, Any]]
    trial: int
    meta: Dict[str, Any] = {}
    user_traj: List[Dict[str, Any]] = []
```

`RunConfig` 末尾加 `resume: Optional[str] = None`。

- [ ] **Step 4: 改 dysql_bench/run.py**

顶部加：

```python
from dysql_bench.analysis import (classify_task, count_fabricated_results,
                                  count_sql_errors, confirmed_before_write)

def load_done(path):
    if not path or not os.path.exists(path):
        return set()
    with open(path) as f:
        return {(r["task_id"], r["trial"]) for r in json.load(f)}

def _sum_completion(traj):
    return sum((m.get("usage") or {}).get("completion_tokens") or 0
               for m in traj if m.get("role") == "assistant")

def _last_prompt(traj):
    pts = [(m.get("usage") or {}).get("prompt_tokens") for m in traj if m.get("role") == "assistant"]
    pts = [p for p in pts if p is not None]
    return pts[-1] if pts else None

def build_meta(env_name, task, info, traj, user_traj, wall_s):
    ri = (info.get("reward_info") or {}).get("info") or {}
    return {"env": env_name, **classify_task(task),
            "termination": info.get("termination"), "n_steps": info.get("n_steps"),
            "n_fabricated_results": count_fabricated_results(traj),
            "n_sql_errors": count_sql_errors(traj),
            "confirmed_before_write": confirmed_before_write(traj),
            "mismatched_tables": ri.get("mismatched_tables", []),
            "wall_s": round(wall_s, 2),
            "agent_completion_tokens": _sum_completion(traj),
            "user_completion_tokens": _sum_completion(user_traj),
            "last_prompt_tokens": _last_prompt(traj)}
```

`run()` 里：
- 若 `config.resume`，则 `ckpt_path = config.resume`，`done = load_done(ckpt_path)`；否则 `done = set()`。
- 每个 trial 的 `idxs` 过滤掉 `(idx, i) in done`。
- `_run` 里 `try` 成功分支改为：

```python
                result = EnvRunResult(
                    task_id=idx, reward=res.reward, info=res.info, traj=res.messages, trial=i,
                    user_traj=isolated_env.user.messages,
                    meta=build_meta(config.env, isolated_env.task, res.info, res.messages,
                                    isolated_env.user.messages, time.time() - run_start_time))
```

异常分支加 `meta={"env": config.env, "termination": "error", "wall_s": round(time.time() - run_start_time, 2)}`。
- 最后 `display_metrics` 和整体写盘时，若 resume，先把 ckpt 里旧结果读回并入 `results`，再计算 pass^k（否则 resume 后指标只算新跑的）。

- [ ] **Step 5: 改 run.py CLI**

加 `parser.add_argument("--resume", type=str, default=None, help="existing results json to continue")`，并在 `RunConfig(...)` 传 `resume=args.resume`。

- [ ] **Step 6: 跑全部测试**

Run: `conda run -n dysql pytest tests -v`
Expected: 10 passed

- [ ] **Step 7: 端到端冒烟：单任务真跑**

```bash
cd ~/Documents/Isa/DySQL-Bench/DySQL-Bench
conda run -n dysql python run.py --env pagila --task-ids 0 --num-trials 1 \
  --model qwen3-32b-awq --model-api http://127.0.0.1:8000 \
  --user-model qwen2.5-72b-awq --user-model-api http://127.0.0.1:8001 \
  --user-strategy llm --log-dir results/smoke
python3 -c "import json,glob; r=json.load(open(glob.glob('results/smoke/*.json')[0]))[0]; print(r['meta']); print(len(r['traj']), len(r['user_traj']))"
```

Expected: 打印 meta 字典，`termination` 为 `user_stop` 或 `max_steps`，traj 每条 assistant 消息含 `usage`。若 vLLM 对请求返回 400，把错误贴进 `docs/gb10_serving_notes.md` 并修请求体后重跑。

- [ ] **Step 8: Commit**

```bash
git add dysql_bench/types.py dysql_bench/run.py run.py tests/test_resume.py
git commit -m "feat: task meta, user trajectory, and --resume in results"
```

---

### Task 9: 汇总脚本

**Files:**
- Create: `scripts/summarize.py`
- Test: `tests/test_summarize.py`

**Interfaces:**
- Consumes: `EnvRunResult` JSON（Task 8 格式）
- Produces: `summarize(results: list[dict]) -> dict`，键 `overall, by_env, by_length`，每项含 `n_tasks, n_runs, pass_hat_k (dict k->float), avg_steps, avg_wall_s, avg_agent_tokens, avg_user_tokens, fabricated_rate, sql_error_rate, confirm_rate, last_prompt_p50, last_prompt_max, termination_counts, top_mismatched_tables`；CLI 输出 markdown 到 stdout

- [ ] **Step 1: 写失败测试**

```python
# tests/test_summarize.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from summarize import summarize

def _r(task, trial, reward, env="pagila", length="short", term="user_stop", fab=0, tables=()):
    return {"task_id": task, "trial": trial, "reward": reward, "info": {}, "traj": [],
            "meta": {"env": env, "length": length, "termination": term, "n_steps": 3,
                     "wall_s": 10.0, "agent_completion_tokens": 100, "user_completion_tokens": 20,
                     "n_fabricated_results": fab, "mismatched_tables": list(tables),
                     "n_sql_errors": 1 if fab else 0, "confirmed_before_write": True if task == 1 else None,
                     "last_prompt_tokens": 5000 + 1000 * task}}

def test_summarize_pass_hat_k_and_counts():
    rs = [_r(0, 0, 1), _r(0, 1, 0), _r(1, 0, 1), _r(1, 1, 1, length="long", fab=1, tables=("a",))]
    s = summarize(rs)
    assert s["overall"]["n_tasks"] == 2 and s["overall"]["n_runs"] == 4
    assert abs(s["overall"]["pass_hat_k"][1] - 0.75) < 1e-9
    assert abs(s["overall"]["pass_hat_k"][2] - 0.5) < 1e-9
    assert s["overall"]["fabricated_rate"] == 0.25
    assert s["overall"]["termination_counts"] == {"user_stop": 4}
    assert s["overall"]["top_mismatched_tables"][0] == ("a", 1)
    assert s["overall"]["sql_error_rate"] == 0.25
    assert s["overall"]["confirm_rate"] == 1.0   # only runs with a write are counted
    assert s["overall"]["last_prompt_p50"] == 5500 and s["overall"]["last_prompt_max"] == 6000
    assert set(s["by_env"]) == {"pagila"}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `conda run -n dysql pytest tests/test_summarize.py -v`
Expected: FAIL，`ModuleNotFoundError: summarize`

- [ ] **Step 3: 实现**

```python
#!/usr/bin/env python3
"""Summarize DySQL-Bench result JSONs into pass^k and analysis stats.
Usage: python scripts/summarize.py results/full/*.json > docs/results/<date>.md
"""
import argparse, glob, json, statistics
from collections import Counter, defaultdict
from math import comb

def _group_stats(rs):
    by_task = defaultdict(list)
    for r in rs: by_task[r["task_id"]].append(1 if abs(r["reward"] - 1) < 1e-6 else 0)
    n_trials = max(len(v) for v in by_task.values())
    pk = {}
    for k in range(1, n_trials + 1):
        vals = [comb(sum(v), k) / comb(len(v), k) for v in by_task.values() if len(v) >= k]
        pk[k] = sum(vals) / len(vals) if vals else 0.0
    metas = [r.get("meta", {}) for r in rs]
    tables = Counter(t for m in metas for t in m.get("mismatched_tables", []))
    return {"n_tasks": len(by_task), "n_runs": len(rs), "pass_hat_k": pk,
            "avg_steps": statistics.mean(m.get("n_steps") or 0 for m in metas),
            "avg_wall_s": statistics.mean(m.get("wall_s") or 0 for m in metas),
            "avg_agent_tokens": statistics.mean(m.get("agent_completion_tokens") or 0 for m in metas),
            "avg_user_tokens": statistics.mean(m.get("user_completion_tokens") or 0 for m in metas),
            "fabricated_rate": sum(1 for m in metas if m.get("n_fabricated_results", 0) > 0) / len(rs),
            "sql_error_rate": sum(1 for m in metas if (m.get("n_sql_errors") or 0) > 0) / len(rs),
            "confirm_rate": (lambda w: sum(1 for c in w if c) / len(w) if w else None)(
                [m.get("confirmed_before_write") for m in metas if m.get("confirmed_before_write") is not None]),
            "last_prompt_p50": statistics.median(lp) if (lp := [m["last_prompt_tokens"] for m in metas if m.get("last_prompt_tokens")]) else None,
            "last_prompt_max": max(lp) if lp else None,
            "termination_counts": dict(Counter(m.get("termination") for m in metas)),
            "top_mismatched_tables": tables.most_common(5)}

def summarize(results):
    out = {"overall": _group_stats(results), "by_env": {}, "by_length": {}}
    for key, field in (("by_env", "env"), ("by_length", "length")):
        groups = defaultdict(list)
        for r in results: groups[r.get("meta", {}).get(field, "?")].append(r)
        out[key] = {g: _group_stats(v) for g, v in sorted(groups.items())}
    return out

def to_markdown(s):
    lines = ["| group | tasks | runs | pass^1 | pass^3 | pass^5 | steps | wall s | agent tok | user tok | fab rate | sql err | confirm | last prompt p50/max | terminations |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    def row(name, g):
        pk = g["pass_hat_k"]
        f = lambda k: f"{100*pk[k]:.2f}" if k in pk else "-"
        conf = "-" if g["confirm_rate"] is None else f"{100*g['confirm_rate']:.0f}%"
        return (f"| {name} | {g['n_tasks']} | {g['n_runs']} | {f(1)} | {f(3)} | {f(5)} | {g['avg_steps']:.1f} | "
                f"{g['avg_wall_s']:.0f} | {g['avg_agent_tokens']:.0f} | {g['avg_user_tokens']:.0f} | "
                f"{100*g['fabricated_rate']:.1f}% | {100*g['sql_error_rate']:.1f}% | "
                f"{conf} | "
                f"{g['last_prompt_p50']}/{g['last_prompt_max']} | {g['termination_counts']} |")
    lines.append(row("overall", s["overall"]))
    for k, g in s["by_length"].items(): lines.append(row(k, g))
    for k, g in s["by_env"].items(): lines.append(row(k, g))
    lines.append(""); lines.append(f"Top mismatched tables: {s['overall']['top_mismatched_tables']}")
    return "\n".join(lines)

if __name__ == "__main__":
    p = argparse.ArgumentParser(); p.add_argument("paths", nargs="+"); a = p.parse_args()
    results = [r for path in a.paths for f in glob.glob(path) for r in json.load(open(f))]
    print(to_markdown(summarize(results)))
```

- [ ] **Step 4: 跑测试确认通过**

Run: `conda run -n dysql pytest tests -v`
Expected: 11 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/summarize.py tests/test_summarize.py
git commit -m "feat: summarize results into pass^k and analysis table"
```

---

### Task 10: Pilot（pagila 5 任务，thinking on，并发 5）

**目标**：验证能跑、测真实吞吐、检查日志字段、预估全量耗时。**不下 pass rate 结论**，5 个任务没有统计意义。

**Files:**
- Create: `scripts/pick_pilot_tasks.py`
- Create: `scripts/run_pilot.sh`
- Create: `scripts/estimate_full.py`
- Create: `docs/results/2026-09-XX-pilot.md`（运行后写）

**Interfaces:**
- Consumes: Task 3 服务脚本、Task 5 `classify_task`、Task 8 的 run.py、Task 9 的 summarize、`docs/task_counts.md`
- Produces: `results/pilot_think_on/*.json`；全量耗时估算（两种口径）

- [ ] **Step 1: 挑任务**

```python
#!/usr/bin/env python3
"""Pick 3 short + 2 long pagila tasks for the pilot. Prints space-separated task ids."""
import argparse, importlib
from dysql_bench.analysis import classify_task

p = argparse.ArgumentParser(); p.add_argument("--env", default="pagila")
p.add_argument("--short", type=int, default=3); p.add_argument("--long", type=int, default=2)
a = p.parse_args()
tasks = importlib.import_module(f"dysql_bench.envs.{a.env}.tasks_test").TASKS_TEST
short = [i for i, t in enumerate(tasks) if classify_task(t)["length"] == "short"]
long_ = [i for i, t in enumerate(tasks) if classify_task(t)["length"] == "long"]
print(" ".join(map(str, short[: a.short] + long_[: a.long])))
```

Run: `conda run -n dysql python scripts/pick_pilot_tasks.py`
Expected: 5 个整数。把这行记进 pilot 报告。

- [ ] **Step 2: 写 pilot 脚本**

```bash
#!/usr/bin/env bash
# scripts/run_pilot.sh <tag>  -- pagila, 3 short + 2 long tasks, 1 trial, concurrency 5
set -euo pipefail
TAG="${1:?usage: run_pilot.sh <tag>}"
cd "$(dirname "$0")/.."
OUT="results/pilot_${TAG}"; mkdir -p "$OUT"
IDS=$(conda run -n dysql python scripts/pick_pilot_tasks.py --env pagila)
echo "pilot task ids: $IDS" | tee "$OUT/task_ids.txt"
START=$(date +%s)
conda run -n dysql python run.py --env pagila --task-ids $IDS --num-trials 1 \
  --model qwen3-32b-awq --model-api http://127.0.0.1:8000 \
  --user-model qwen2.5-72b-awq --user-model-api http://127.0.0.1:8001 \
  --user-strategy llm --max-concurrency 5 --log-dir "$OUT" 2>&1 | tee "$OUT/pagila.log"
echo "pilot_wall_s $(( $(date +%s) - START ))" | tee "$OUT/wall.txt"
conda run -n dysql python scripts/summarize.py "$OUT/*.json" | tee "$OUT/summary.md"
conda run -n dysql python scripts/estimate_full.py "$OUT" | tee "$OUT/estimate.md"
```

- [ ] **Step 3: 写估时脚本（两种口径）**

```python
#!/usr/bin/env python3
"""Estimate full-run wall time from a pilot directory.
口径 A（墙钟）: pilot_wall_s / n_pilot_tasks * N_TOTAL           -- 已含并发排队，直接外推
口径 B（token）: 每任务 agent/user 生成 token 之和 / 各自实测 tok/s -- 交叉验证
两者都乘 1.3~1.5 作为上限（pagila 提示词偏短，eu_soccer/retail 更长、任务更多）。
"""
import glob, json, sys, statistics
d = sys.argv[1]; N_TOTAL = 1062
rs = [r for f in glob.glob(f"{d}/*.json") for r in json.load(open(f))]
wall = int(open(f"{d}/wall.txt").read().split()[1])
n = len(rs)
per_task = wall / n
est_a = per_task * N_TOTAL
def toks(traj): return sum((m.get("usage") or {}).get("completion_tokens") or 0 for m in traj if m.get("role") == "assistant")
def secs(traj): return sum(m.get("latency_s") or 0 for m in traj if m.get("role") == "assistant")
a_tok = sum(toks(r["traj"]) for r in rs); a_sec = sum(secs(r["traj"]) for r in rs)
u_tok = sum(toks(r.get("user_traj", [])) for r in rs); u_sec = sum(secs(r.get("user_traj", [])) for r in rs)
a_tps = a_tok / a_sec if a_sec else float("nan"); u_tps = u_tok / u_sec if u_sec else float("nan")
# 口径 B: 每任务生成时长按并发 5 折算
est_b = (a_tok / a_tps + u_tok / u_tps) / n * N_TOTAL / 5 if a_sec and u_sec else float("nan")
steps = [r["meta"].get("n_steps") or 0 for r in rs]
lp = [r["meta"].get("last_prompt_tokens") or 0 for r in rs]
print(f"pilot tasks: {n}, wall: {wall}s, per task (concurrent): {per_task:.0f}s")
print(f"agent: {a_tok} gen tok, per-request tok/s ≈ {a_tps:.1f}; user: {u_tok} gen tok, tok/s ≈ {u_tps:.1f}")
print(f"steps avg {statistics.mean(steps):.1f} max {max(steps)}; last prompt tokens avg {statistics.mean(lp):.0f} max {max(lp)}")
print(f"length_hits: {sum(1 for r in rs for m in r['traj'] if m.get('finish_reason') == 'length')}")
print(f"估时 A（墙钟外推）: {est_a/3600:.1f} h   上限 ×1.5: {est_a*1.5/3600:.1f} h")
print(f"估时 B（token 口径）: {est_b/3600:.1f} h   上限 ×1.5: {est_b*1.5/3600:.1f} h")
```

- [ ] **Step 4: 跑 pilot**

```bash
THINKING=on bash scripts/serve_agent.sh && bash scripts/wait_ready.sh
bash scripts/run_pilot.sh think_on
```

Expected: `results/pilot_think_on/summary.md` 有 overall 行；5 个任务全部有 `termination` 且非 `error`；`estimate.md` 两个估时数量级一致（差 2 倍以内）。

- [ ] **Step 5: 写 pilot 报告**

`docs/results/<date>-pilot.md` 包含：
- 任务 id 与 short/long 标注；summary 表；`estimate.md` 全文。
- 日志字段抽查：贴一条完整 traj 片段，确认 `reasoning_content`、`usage`、`latency_s`、`finish_reason`、`mismatched_tables`、`n_sql_errors`、`confirmed_before_write`、`last_prompt_tokens` 都在。
- `finish_reason == "length"` 的次数；`last_prompt_tokens` 最大值与 40960 的余量。
- 运行中 `nvidia-smi` / `free -g` 峰值，两个容器有无 OOM 或 400。
- 明确写一句：pass rate 不作为本轮结论。

**在这里停下来向用户汇报**。用户决定：是否直接进全量；是否先补第二轮 pilot（3 库 × 8 任务，或 thinking off 对比）；user sim 是否换更小模型换吞吐。

- [ ] **Step 6: Commit**

```bash
git add scripts/pick_pilot_tasks.py scripts/run_pilot.sh scripts/estimate_full.py docs/results/
git commit -m "feat: pilot runner (pagila 5 tasks), task picker, full-run estimator"
```

---

### Task 11: 全量运行与基线报告（pass@1）

**Files:**
- Create: `scripts/run_full.sh`
- Create: `docs/results/<date>-qwen3-32b-awq-full.md`

**Interfaces:**
- Consumes: 用户在 Task 10 后的决定；THINKING=on；NUM_TRIALS 默认 1（用户已定先做 pass@1）
- Produces: `results/full_<tag>/<env>-*.json` 13 个文件；报告

- [ ] **Step 1: 写全量脚本（nohup、逐库、可 resume）**

```bash
#!/usr/bin/env bash
# scripts/run_full.sh <tag> [num_trials] [concurrency]  -- all 13 envs, resumable; run under nohup
set -uo pipefail
TAG="${1:?usage: run_full.sh <tag> [num_trials] [concurrency]}"; TRIALS="${2:-1}"; CONC="${3:-5}"
cd "$(dirname "$0")/.."
OUT="results/full_${TAG}"; mkdir -p "$OUT"
ENVS="pagila retail bowling chinook entertainment eu_soccer music car cookbook human_resources ice_hockey law_episode retail_world"
for ENV in $ENVS; do
  EXISTING=$(ls "$OUT"/${ENV}-*.json 2>/dev/null | head -1 || true)
  RESUME=""; [ -n "$EXISTING" ] && RESUME="--resume $EXISTING"
  echo "[$(date)] start $ENV $RESUME"
  conda run -n dysql python run.py --env "$ENV" --num-trials "$TRIALS" \
    --model qwen3-32b-awq --model-api http://127.0.0.1:8000 \
    --user-model qwen2.5-72b-awq --user-model-api http://127.0.0.1:8001 \
    --user-strategy llm --max-concurrency "$CONC" --log-dir "$OUT" $RESUME >> "$OUT/${ENV}.log" 2>&1
  echo "[$(date)] done $ENV rc=$?"
done
conda run -n dysql python scripts/summarize.py "$OUT/*.json" > "$OUT/summary.md"
echo "[$(date)] ALL DONE"
```

并发数按 pilot 实测定：若 pilot 中 user sim 的 p95 延迟没有随并发明显恶化，可试 8（等于 `--max-num-seqs`）。

- [ ] **Step 2: 启动**

```bash
THINKING=on bash scripts/serve_agent.sh && bash scripts/wait_ready.sh
nohup bash scripts/run_full.sh qwen3_32b_think_on 1 5 > results/full_run.log 2>&1 &
```

进度检查：`grep -c '"task_id"' results/full_*/*.json`；服务健康：`docker logs --tail 20 dysql-agent`。中断后重新执行同一条 nohup 命令即可续跑。

- [ ] **Step 3: 写基线报告**

`docs/results/<date>-qwen3-32b-awq-full.md` 包含：summarize 输出的完整表；与论文 Table 3 的 Qwen3-32B 行按库对比（论文 Pass^1 overall 行：ES 55.81, IH 46.43, BO 30.63, EN 51.15, MU 76.19, LE 26.42, CK 27.45, CH 54.55, PA 51.43, CA 55.56, HR 50.00, RE 49.27, RW 41.94）；差异超过 10 个点的库列出来并抽 2 条轨迹看原因；终止原因分布；伪造 `<result>` 率与论文图 7 对比；SQL 报错率与写前确认率；top mismatched tables；`last_prompt_tokens` 分布（决定后续 RL 的 context 长度）；总耗时与 token 用量，与 pilot 估时对比。小库（music 21、car 27、ice_hockey 28）的单库数字标注为低置信。

- [ ] **Step 4: Commit 并推送分支**

```bash
git add scripts/run_full.sh docs/results/
git commit -m "feat: full-run script and Qwen3-32B-AWQ baseline report"
git push -u origin isa/eval-harness
```

---

## Addendum (2026-09-16, after pilot): extra log fields

Added after reviewing the five pilot trajectories. Selection rule: only fields that directly separate failure classes or flag bad data; nothing else.

| where | field | why |
|---|---|---|
| `info.reward_info.info.row_diff` | per mismatched table: `only_agent` / `only_gold` rows (≤20 each) + counts; `rowcount_only` when the table has no stable columns | tells *how* a table differs (UPDATE vs DELETE, `'N'` vs `'0'`) instead of just its name |
| `sql_log` (top-level on each result) | every executed statement: `phase` (agent/gold), `step`, `sql`, `type`, `rowcount`, `error`, `duration_s` | `rowcount == 0` on a write is invisible in the observation string; gold-phase entries with `rowcount == 0` flag a broken gold task |
| `meta.n_extra_sql_blocks` | SQL blocks beyond the first per assistant turn | the env runs only the first block; this counts SQL the agent believed it ran. Complements `n_fabricated_results` |
| `meta.n_zero_row_writes`, `meta.gold_zero_row_writes` | derived from `sql_log` | one number per run for the two signals above |
| `<ckpt>.config.json` sidecar | `run_config`, `max_num_steps`, `git_commit`, vLLM version + served models for both servers, `started_at` | every results file carries how it was produced; needed once 1.7B / 4B / trained checkpoints are compared |
| `summarize.py` | columns `multi-sql`, `0-row write` | |

Also: `calculate_reward` now reads each side of the DB once instead of twice (hash and per-table hashes come from the same read). Observation strings, commit/rollback and the judgement are unchanged. Not added on purpose: an "authenticated before write" rule (the user table differs per env; a keyword rule would be noise). Tests: 22.

## Self-Review

**需求覆盖**：fork 远端与分支（Task 1）；起服务、thinking on、40960 上下文（Task 3）；小子集先行、两种口径估时（Task 10）；全量与详细日志（Task 7、8、11）。日志字段清单逐项对应：每轮完整消息含 thinking（Task 7 `reasoning_content`）、SQL 结果与伪造检测（原 traj 已含 `<result>` 观测，Task 5 `count_fabricated_results`）、SQL 报错计数与写前确认（Task 5）、终止原因（Task 7）、按表 hash diff（Task 6）、每轮 token 与耗时、末轮 prompt 长度（Task 7、8）、任务元信息（Task 5 + Task 8）。

**本轮范围**：Task 1、2、3、5、6、7、8、9、10。Task 4 跳过；Task 11 待 pilot 汇报后由用户放行。

**类型一致性**：`classify_task / count_fabricated_results / diff_table_hashes / count_sql_errors / confirmed_before_write` 在 Task 5 定义，Task 6、8、10 按同名使用；`RewardActionInfo.mismatched_tables` 在 Task 6 定义，Task 8 的 `build_meta` 从 `info["reward_info"]["info"]["mismatched_tables"]` 读，与 `EnvInfo.reward_info -> RewardResult.info` 的 `model_dump` 结构一致；`EnvRunResult.meta / user_traj` 在 Task 8 定义，Task 9 的 summarize 与 Task 10 的 estimate_full 按 `meta` 键和 `latency_s / usage` 读取。测试数累计：Task 5 五个、Task 6 一个、Task 7 两个、Task 8 两个、Task 9 一个，共 11。

**已知取舍**：user sim 的每轮日志存在 `user_traj`，与 agent 的 `traj` 分开，因为 agent 看到的 user 消息只有 content；分析时按顺序对齐即可。`--resume` 合并旧结果后再算 pass^k，避免只统计新跑的部分。`confirmed_before_write` 是关键词规则，会有误判，只用于分析不进评测。5 任务 pilot 的估时置信度中等，报告里要带 1.5 倍上限。
