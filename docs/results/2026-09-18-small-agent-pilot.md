# Pilot: Qwen3-1.7B and Qwen3-4B as agent, run in parallel (10 pagila tasks each)

Run 2026-09-17 22:58 → 23:22 EDT (1405 s wall, both pilots concurrently). Branch `isa/eval-harness` @ `cea8147`.
Results: `DySQL-Bench/results/pilot_qwen3_1.7b_think_on/`, `DySQL-Bench/results/pilot_qwen3_4b_think_on/`.
Plan this executes: `docs/2026-09-17-small-agent-baselines-plan.md` (Tasks 1–8 done; Task 9 full run pending decision).

## Setup (as it actually ran)

| service | model | port | quant | gpu-util | max-num-seqs | KV cache |
|---|---|---|---|---|---|---|
| user sim `dysql-user` | Qwen/Qwen2.5-72B-Instruct-AWQ | 8001 | awq_marlin | **0.50** (plan said 0.38; see Ops) | 32 | 53,584 tok |
| agent `dysql-agent-1.7b` | Qwen/Qwen3-1.7B bf16 | 8000 | none | 0.10 | 32 | 57,680 tok |
| agent `dysql-agent-4b` | Qwen/Qwen3-4B bf16 | 8002 | none | 0.15 | 32 | 69,264 tok |

Sampling identical to the 32B baseline: temp 0.6, top_p 0.95, top_k 20, max_tokens 8192, max 30 steps, thinking **on**.
Pilot tasks: pagila ids `0 4 11 12 14 17 1 2 3 5` (6 short + 4 long), concurrency 8 per run. Same ids for both models,
and the 32B full run covers them, so all three are compared on identical tasks.

## Infrastructure smoke: all green

- Both runs: 10/10 tasks completed, terminations `user_stop` ×10 (1.7B) and `user_stop` ×9 + `length_no_content` ×1 (4B). Zero `error`.
- Two `run.py` processes ran the same env concurrently with **no sqlite collision** (per-process tmp dirs from commit `2a551ff`).
- user sim: peak `Running: 14` with two c=8 runs, `Waiting: 0`, 0 preemptions, KV peak 3.4 %. Headroom for 2 × c=16 is fine (MAX_SEQS 32).
- agents: 0 preemptions; KV peak 19.4 % (1.7B) / 23.8 % (4B) at c=8 → ~40–50 % expected at c=16, still fine.
- Thinking arrives in `message.reasoning` for both models; every assistant turn had reasoning (86/86, 66/66).
- Result file names embed the served model (`pagila-sql-agent-qwen3-1.7b-…`, `…-qwen3-4b-…`); sidecars record the right port.
- Idle memory after all three servers up: `free -g` used 95 / available 26 GB. During the pilots available stayed ≥ 25 GB.

## Results on the 10 shared tasks

| task | 32B-AWQ | 1.7B | 4B | steps 32B/1.7B/4B | agent completion tok 32B/1.7B/4B |
|---|---|---|---|---|---|
| 0 | 0 | 0 | 0 | 9/12/5 | 4172/8161/3597 |
| 4 | **1** | 0 | 0 | 5/5/4 | 2343/3250/2277 |
| 11 | 0 | 0 | 0 | 8/5/3 | 4926/4366/3813 |
| 12 | 0 | 0 | 0 | 6/5/6 | 2685/2163/4653 |
| 14 | **1** | **1** | 0 (length_no_content) | 7/6/2 | 3846/4910/8646 |
| 17 | **1** | 0 | 0 | 12/23/12 | 8627/16578/8610 |
| 1 | **1** | 0 | 0 | 8/6/5 | 3225/1818/2435 |
| 2 | 0 | 0 | 0 | 13/7/15 | 6745/4537/7786 |
| 3 | 0 | 0 | 0 | 16/12/7 | 7772/5818/3991 |
| 5 | 0 | 0 | 0 | 13/5/7 | 8569/2796/3969 |
| **pass** | **4/10** | **1/10** | **0/10** | | |

The one 1.7B pass (task 14) is a **gold no-op task** (gold write touches 0 rows), so it passes by doing nothing. Excluding it: 0/9.

## Why they fail: the SQL never reaches the database

The harness executes SQL only from a ` ```sql ` fence or `<sql>…</sql>`. Anything else is treated as a message to the user.
The system prompt says only "write the SQL in a code block" and mentions that results come back in `<result>`.

| | 32B-AWQ | 1.7B | 4B |
|---|---|---|---|
| assistant turns | 97 | 86 | 66 |
| turns whose SQL was executed | 61 | 32 | 14 |
| turns with SQL in a **non-executable wrapper** | 0 | 30 | 35 |
| of which contained a write (UPDATE/INSERT/DELETE) | 0 | 13 | 17 |
| failed tasks where a write was never executed for this reason | 0/10 | 5/10 | 7/10 |
| wrappers used | ` ```sql ` only | ` ```sql ` 25, `<result>` 32, `<sql>` 7 | `<action>` 46, `<result>` 21, `<sql>` 15, ` ```sql ` **0** |

- **1.7B** alternates between the correct fence and wrapping its SQL in `<result>`, the tag the prompt uses for *execution output*.
- **4B** never uses a code fence at all. It invents an `<action>…</action>` protocol (plus `<confirmation>`, `<response>`), which reads well but executes nothing.
- The models then continue as if the SQL had run, often fabricating a `<result>` (fab rate 80 % / 60 %; 32B on the full run: 66 %).

Failure classifier (`scripts/classify_failures.py`, primary cause):

| primary cause | 1.7B (9 fails) | 4B (10 fails) |
|---|---|---|
| C. no_write: phantom_sql_outside_block | 6 | 7 |
| B. write_dropped_in_extra_sql_block | 1 | 1 |
| D. partial: sql_error_unrecovered | 1 | 1 |
| F. no_write: escalated_to_human | 1 | 0 |
| A. abnormal: length_no_content | 0 | 1 |

Other pilot stats: 1.7B steps avg 8.6 (max 23), last-prompt tokens avg 4.1k (max 8.9k); 4B steps avg 6.6 (max 15), avg 3.4k (max 4.0k).
No `context_overflow`. The single `length_no_content` (4B, task 14) is 8192 tokens of pure thinking (39k chars) with no answer.

## Thinking gate (plan Task 8 step 3)

`length_no_content`: 1.7B 0/10, 4B 1/10 (10 %). Both below the 20 % threshold → **thinking on for the full run**, unchanged from 32B.

## Time estimate for the full 1062 (per run, from `estimate_full.py`)

| | 1.7B | 4B |
|---|---|---|
| token-based estimate (B) | 20.5 h | 29.4 h |
| wall-clock extrapolation (A) | 41.4 h | 41.5 h |
| agent per-request decode | 13.9 tok/s | 7.5 tok/s |

Estimate A is pessimistic: 10 tasks at c=8 is two rounds with the second round only 2 tasks wide, so utilisation was poor.
With c=16 in the full run expect closer to B. Note the low per-request decode speed: three vLLM engines share one memory bus,
and each 72B decode step reads 39 GiB of weights, so the agents slow down whenever the user sim is generating. The 32B run
had the same coupling with one agent. Expect roughly **25–35 h with both runs in parallel**, versus ~2× that serially.

## Ops notes

- **user sim needs GPU_UTIL ≥ 0.46, not 0.38.** Budget is util × 113.3 GiB; weights are 38.8 GiB. At 0.38 the KV cache came out at
  1.87 GiB and 4.91 GiB on two attempts (< 5.0 GiB needed for one 16k request → EngineCore failed twice, docker restart policy retried)
  and 5.24 GiB = 17k tokens on the third. Restarted at 0.50 → 16.35 GiB = 53,584 tokens. Recorded in `docs/gb10_serving_notes.md`.
- Leftover sqlite scratch dirs: after the pilots, `pagila/data/tmp/` still had `thread_<pid>_None` ×2 (the task-enumeration env
  built with `thread_id=None` at startup, never deleted; pre-existing behaviour) and one `thread_<pid>_<tid>` (a run whose env never
  reached `done`, i.e. the `length_no_content` case, so `delete_db` was never called). Same leak existed in the 32B run. Harmless on
  disk (≤ 300 MB per leaked eu_soccer copy) but worth an `rm -rf dysql_bench/envs/*/data/tmp/thread_*` between runs.
- `classify_failures.py` crashed on a run with 0 passes (ZeroDivision); fixed in `2dd6e09`.

## What this means for the decision on the full run

1. The harness is ready; nothing infrastructural blocks Task 9.
2. Zero-shot pass^1 on the full set will be very low: extrapolating, **1.7B ≈ 5–10 % (mostly gold no-op tasks), 4B ≈ 0–5 %**.
   The number will measure *protocol compliance* (does the model use the one fence the parser accepts), not SQL skill.
3. That is still the honest zero-shot baseline under the benchmark's protocol and the natural "before GRPO" row. But it also says
   the first reward term / SFT target has to be output format, and that a **format-tolerant parser variant** (accept `<action>`,
   `<result>`-wrapped SQL, bare ` ``` ` fences) is a cheap, separate ablation that would show how much SQL ability hides behind the
   format failure. That variant must be a separate tag, not mixed into the baseline.
