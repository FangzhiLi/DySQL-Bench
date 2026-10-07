# Multi-turn / agentic text-to-SQL with RL (2025-01 to 2026-10): recipes, SFT cold start, rewards

Scope note: only systems where the policy interacts with a database over several turns (execute, observe, retry) and/or with a (simulated) user. Single-turn reasoning-RL (SQL-R1, Reasoning-SQL, Graph-Reward-SQL, CogniSQL-R1-Zero, RLVR-on-verified-data) is left to the other researcher and is only mentioned where a multi-turn paper uses it as a baseline. Months are arXiv first-submission months inferred from the arXiv ID (YYMM) unless a page stated a date.

Correction recorded during research: a first PDF-summary pass reported MTSQL-R1 Qwen3-1.7B scores of "20.2 -> 26.8 EX". A `pdftotext` dump of the same PDF (arXiv 2510.12831v3, Table 2) shows the 1.7B rows are 73.0 -> 77.3 EX on CoSQL; the verified table values are used below.

## Key question 1: MTSQL-R1 (multi-turn text-to-SQL, CoSQL/SParC, 1.7B and 4B checkpoints) — exact recipe

### Takeaway
MTSQL-R1 (Amazon / ACL 2026, arXiv Oct 2025) trains Qwen3-1.7B and Qwen3-4B as a propose -> execute -> verify -> refine agent over a SQLite DB plus a "dialogue memory" tool, with a max of 4 tool interactions per question. It is strictly SFT-then-RL: a 3-round self-taught rejection-sampling SFT (19,416 CoSQL / 29,710 SParC trajectories, from the model's own correct rollouts, no external teacher) followed by GRPO with outcome (EX+EM) plus per-action process rewards. Without the SFT warm start, the untrained 1.7B agent scores only 22.6% EX on CoSQL in the long-horizon format; after SFT+RL it reaches 77.3% EX (4B: 79.9%). No long-horizon RL-only (no SFT) ablation is reported.

### Cited Findings
- Paper: "MTSQL-R1: Towards Long-Horizon Multi-Turn Text-to-SQL via Agentic Training", arXiv 2510.12831 (Oct 2025; v3 dated April 2026), ACL 2026 long paper; Amazon Science publication page exists — [arXiv HTML](https://arxiv.org/html/2510.12831); [ACL Anthology](https://aclanthology.org/2026.acl-long.1563/); [Amazon Science](https://www.amazon.science/publications/mtsql-r1-towards-long-horizon-multi-turn-text-to-sql-via-agentic-training)
- Base models: Qwen3-1.7B and Qwen3-4B as backbones; generalization check on LLaMA3.2-3B-Instruct; trained on a single node of 8 NVIDIA A100 GPUs — [arXiv HTML](https://arxiv.org/html/2510.12831)
- Environment / MDP: state = dialogue history, schema, current question, dialogue memory, intermediate SQL, accumulated execution observations; discrete actions PROPOSE, EXECUTE (run SQL on DB, returns rows/errors), E-VERIFY (judge execution result), M-VERIFY (check coherence against memory of prior questions/SQL/constraints), SELF-CORRECT, FINALIZE. Two tools exposed via verl multi-turn: `exec_sql` and `memory_retrieve` ("retrieving the historical questions and ground-truth SQL in this dialogue"). verl config `multi_turn.max_turns: 4  # Important Max-turns`; paper text: "maximum interaction between agent and tools is set to 4" — [arXiv HTML](https://arxiv.org/html/2510.12831); [arXiv PDF v3, Appendix C](https://arxiv.org/pdf/2510.12831v3)
- No simulated user: the "user" turns are the fixed CoSQL/SParC dialogue questions; the memory tool supplies gold SQL of prior turns in the standard setting. A robustness variant uses the model's own predicted SQL as prior-turn history: Direct RL 75.2 (gold prior) -> 71.2 (predicted prior) vs MTSQL-R1 79.9 -> 76.5 EX on CoSQL (Table 6) — [arXiv PDF v3](https://arxiv.org/pdf/2510.12831v3)
- SFT stage ("Self-Taught Warm-Start SFT"): prompt the base model on all training questions in the long-horizon format, 20 rollouts per question at temperature 0.7, keep only trajectories whose final SQL is correct; difficulty-aware rejection sampling keeps up to 2 short trajectories (<=2 interactions) for easy items and 3 clustered representatives of longer trajectories (>=2 interactions) for hard items; repeated for 3 rounds, each round re-sampling with the newly fine-tuned model. Coverage (Table 9): CoSQL 9,337 training examples -> 6,311 / 7,409 / 7,555 covered after rounds 1/2/3, final 19,416 trajectories; SParC 11,905 -> 9,132 / 10,103 / 10,285, final 29,710 trajectories. No external teacher model is used — [arXiv PDF v3, Table 9](https://arxiv.org/pdf/2510.12831v3); [arXiv HTML](https://arxiv.org/html/2510.12831)
- SFT hyperparameters: LlamaFactory + DeepSpeed ZeRO-3 offload, full-parameter, lr 5e-6 cosine, per-device batch 2; loss masking supervises only action/SQL tokens and masks instructions and tool outputs — [arXiv HTML](https://arxiv.org/html/2510.12831)
- RL stage: GRPO via verl 0.4.1 with SGLang rollouts; train batch 256; `rollout.n=5`; lr 1e-6; max prompt 4,000 tokens, max response 8,000 tokens; `use_kl_in_reward=False`; curriculum partitioning easy -> hard and dropping examples the SFT model already solves 20/20; config lists `trainer.total_epochs=60` — [arXiv PDF v3, Appendix C.2](https://arxiv.org/pdf/2510.12831v3); [GitHub taichengguo/MTSQL-R1](https://github.com/taichengguo/MTSQL-R1)
- Reward: R_all = w1 * (R_EX + R_EM) + w2 * (R_Propose/Self-Correct + R_E-Verify + R_M-Verify). Outcome: R_EX = 1 if execution result matches gold, R_EM = 1 if exact SQL match. Process: PROPOSE/SELF-CORRECT = average clause-level F1 between predicted and gold SQL over SELECT/WHERE/JOIN/GROUP/ORDER; E-VERIFY = lookup table over (execution ok/null/error) x (verdict pass/fail) with values {0, 0.1, 1}; M-VERIFY = avg clause F1 if verdict pass else 1 - avg F1. "weights are selected via grid search on a small validation set" — exact w1, w2 not stated — [arXiv HTML](https://arxiv.org/html/2510.12831); [arXiv PDF v3](https://arxiv.org/pdf/2510.12831v3)
- Training task source: CoSQL (3,007 dialogues / 15,598 questions) and SParC (4,298 / 12,726) training splits, ~200 databases — [arXiv HTML](https://arxiv.org/html/2510.12831)
- Main results, Table 2, in-domain question-level EX / EM (CoSQL dev, SParC dev), Qwen3-1.7B: prompting-only Qwen3-1.7B 59.9/49.3, 61.5/46.5; Short-horizon SFT 68.1/59.3, 74.3/69.2; Short-horizon Direct RL 72.8/59.0, 72.1/65.5; Long-horizon base agent without training 22.6/16.3, 23.9/17.8; Warm-start SFT only round 1 69.9/57.6, 70.6/62.0; round 2 72.2/60.5, 72.3/63.0; round 3 73.0/62.1, 72.8/65.7; SFT + RL (outcome only) 76.6/62.7, 76.2/66.1; SFT + RL (outcome + process) 77.3/63.5, 76.2/66.1 — [arXiv PDF v3, Table 2](https://arxiv.org/pdf/2510.12831v3)
- Table 2, Qwen3-4B: prompting-only 64.0/50.7, 62.9/49.8; Short-horizon SFT 73.1/64.8, 78.3/71.5; Short-horizon Direct RL 75.2/64.8, 75.8/66.5; Long-horizon base agent without training 60.3/45.6, 57.6/44.1; Warm-start SFT round 3 75.2/63.0, 75.1/65.6; SFT + RL (outcome only) 79.1/64.5, 78.1/67.8; SFT + RL (outcome + process) 79.9/65.2, 79.0/68.7 — [arXiv PDF v3, Table 2](https://arxiv.org/pdf/2510.12831v3)
- Frontier prompting baselines in the same table: GPT-4.1 60.9/32.1 (CoSQL), 61.8/33.3 (SParC); OpenAI-o3 59.8/29.1, 57.0/30.3; DeepSeek-R1 58.5/36.0, 57.6/37.2; Qwen3-32B 66.8/54.4, 74.0/53.4; LangGraph SQL agent 69.9/32.5, 69.6/34.6 — [arXiv PDF v3, Table 2](https://arxiv.org/pdf/2510.12831v3)
- LLaMA3.2-3B-Instruct (Table 11, CoSQL / SParC EX): base 22.9 / 24.4; short-horizon RL 70.4 / 70.9; MTSQL-R1 long-horizon 74.8 / 75.2 — [arXiv PDF v3, Table 11](https://arxiv.org/pdf/2510.12831v3)
- Tool ablation (Table 3, Qwen3-4B SFT+RL on CoSQL): full 79.9 EX; w/o Execute tool 74.6; w/o Memory-Verify tool 77.8 — [arXiv PDF v3, Table 3](https://arxiv.org/pdf/2510.12831v3)
- Reward ablation (Table 10, Qwen3-4B CoSQL, mean +- std): outcome only 79.1 +- 0.15 EX; + verify reward 79.7; + propose/correction reward 79.4; all 79.9 +- 0.11 — [arXiv PDF v3, Table 10](https://arxiv.org/pdf/2510.12831v3)
- Small-model observation: "Result 5: Small LLMs struggle to follow long-horizon function-calling instructions (Table 2)"; "(iii) The 1.7B base model is much weaker than the 4B model primarily..." in the long-horizon-abilities analysis — [arXiv PDF v3](https://arxiv.org/pdf/2510.12831v3)
- Length limits: with a 2,000-token output cap "performance drops drastically ... the agent often cannot complete its full reasoning process, so we must extract intermediate SQL"; the 8,000-token cap is cited as the cause of 6 residual failures; max latency ~28 s per query — [arXiv PDF v3, Appendix D](https://arxiv.org/pdf/2510.12831v3); [arXiv HTML](https://arxiv.org/html/2510.12831)
- On pipelines: "A frequent industry pipeline is to RL-post-train a very large model and then use it to generate SFT/distillation data ... We have not explored such pipelines due to computational constraints ... our self-taught SFT-then-RL pipeline trains stably even when the initial model lacks frontier-level reasoning" — [arXiv PDF v3, Appendix C.3](https://arxiv.org/pdf/2510.12831v3)
- Code/checkpoints: GitHub repo provides CoSQL-1.7B, SParC-1.7B, CoSQL-4B, SParC-4B checkpoints on Hugging Face; SFT via LLaMA-Factory 0.9.3, RL via verl 0.4.1 with reward file `text2sql_process.py`; databases under `database/cosql/` and `database/sparc/` — [GitHub](https://github.com/taichengguo/MTSQL-R1)

### Inferences
- The SFT cold start in MTSQL-R1 is pure self-distillation (rejection-sampled from the policy itself), so its 1.7B recipe does not depend on a stronger teacher; the price is that round 1 covers only ~68% (CoSQL) / ~77% (SParC) of training questions, growing to ~81% / ~86% after three rounds.
- The 22.6% EX of the untrained 1.7B long-horizon agent versus 59.9% for the same model in plain prompting shows the format/tool protocol, not SQL skill, is the bottleneck before SFT; this is the strongest evidence in the paper that a 1.7B model needs a warm start before multi-turn RL.
- Process rewards add only +0.7 EX over outcome-only at 4B (79.1 -> 79.9) and +0.7 at 1.7B (76.6 -> 77.3); most of the gain comes from the long-horizon formulation plus outcome GRPO.

### Gaps
- Exact w1/w2 reward weights, number of RL steps actually run, and the number of RL training prompts after curriculum filtering are not stated.
- No RL-only (no warm-start) run in the long-horizon format is reported; "Direct RL" rows are short-horizon single-turn RL.
- Interaction-level (IM) metrics for the 1.7B/4B models were not found in the extracted text.

## Key question 2: SkyRL-SQL (NovaSky) — ~650 examples, no SFT

### Takeaway
SkyRL-SQL (blog May 20, 2025) RL-trains Qwen2.5-Coder-7B-Instruct directly (no SFT stage is described) with GRPO-style multi-turn RL on 653 prompts drawn from SynSQL-2.5M/Spider databases, 5 turns max, 14 epochs, a terminal-only reward (+1 result-set match, 0 wrong, -1 malformed solution). NovaSky claims the 7B model beats GPT-4o, o4-mini and OmniSQL-7B (SFT on 2.5M samples) on several Spider/BIRD splits, with "up to 8.7%" gain over the base; the per-benchmark numbers live on a Notion page that could not be fetched.

### Cited Findings
- Blog post "SkyRL-SQL: Simple and Data Efficient Multi-Turn RL for Text2SQL", published 2025-05-20 (page updated 2026-03-14); the full write-up is a Notion page linked from the SkyRL README — [NovaSky blog index](https://novasky-ai.github.io/posts/skyrl-sql/); [SkyRL GitHub README](https://github.com/NovaSky-AI/SkyRL)
- NovaSky announcement: "a simple, data-efficient RL pipeline for Text-to-SQL that trains LLMs to interactively probe, refine, and verify SQL queries with a real database ... trained on just ~600 samples, SkyRL-SQL-7B outperforms GPT-4o, o4-mini, and SFT model trained with 2.5M samples" — [NovaSky on X](https://x.com/NovaSkyAI/status/1925592895010246863)
- Recipe summary (SkyRL docs recipe page, as indexed): "SkyRL-SQL-7B was trained on top of Qwen2.5-Coder-7B-Instruct with 653 samples, using simple rewards (format + execution), for 5 turns and 14 epochs"; "Using just 653 training samples, SkyRL-SQL-7B can improve accuracy by up to 8.7% compared to the base model, outperforming GPT-4o, o4-mini, and open-source SFT model trained on 2.5 million samples" — [SkyRL docs (old readthedocs URL, now redirects)](https://skyrl.readthedocs.io/en/latest/recipes/skyrl-sql.html); [SkyRL docs recipe](https://docs.skyrl.ai/docs/recipes/skyrl-sql)
- Data: dataset `NovaSky-AI/SkyRL-SQL-653-data` has 654 rows (653 train + 1 validation) with fields data_source, prompt, db_id, reward_model, extra_info, synsql; databases are "from SynSQL-2.5M and Spider, sourced from OmniSQL dataset collections"; training script path `examples/train/text_to_sql/run_skyrl_sql.sh` — [HF dataset](https://huggingface.co/datasets/NovaSky-AI/SkyRL-SQL-653-data); [SkyRL docs recipe](https://docs.skyrl.ai/docs/recipes/skyrl-sql)
- Environment (skyrl-gym `envs/sql/env.py`): model emits `<think>`, `<sql>...</sql>` (executed on SQLite via `SQLCodeExecutorToolGroup`) and `<solution>...</solution>` to finish; execution results or the error string are appended as a `user` message; `max_turns` default 5; "No reward for intermediate steps for SQL tasks" — [env.py](https://raw.githubusercontent.com/NovaSky-AI/SkyRL/main/skyrl-gym/skyrl_gym/envs/sql/env.py)
- Reward (`envs/sql/utils.py`, `compute_score_single`): format check requires exactly one `<solution>` pair with a preceding `<think>` and no nested tags, otherwise `reward = -1.0`; predicted and gold SQL are executed with a 30 s timeout and compared as `frozenset(cur.fetchall())` (order-insensitive); `reward = 1.0` on match, `0.0` on mismatch, execution error or timeout; no separate positive format reward, no per-turn penalty — [utils.py](https://raw.githubusercontent.com/NovaSky-AI/SkyRL/main/skyrl-gym/skyrl_gym/envs/sql/utils.py)
- Model card `NovaSky-AI/SkyRL-SQL-7B`: "No model card", safetensors BF16, listed as 8B params (Qwen2 arch) — [HF model](https://huggingface.co/NovaSky-AI/SkyRL-SQL-7B)
- Independent use as a baseline: SQL-Trail cites SkyRL-style multi-turn RL and reports its own Qwen2.5-Coder-7B multi-turn results (see KQ4) — [SQL-Trail ACL PDF](https://aclanthology.org/2026.acl-long.1677.pdf)

### Inferences
- The absence of any SFT step in the docs/X post and the comparison against an "SFT model trained on 2.5M samples" (OmniSQL) indicate RL-from-instruct with no cold start; the Qwen2.5-Coder-7B-Instruct base already follows the tag format well enough for a -1 format penalty to suffice.
- The reward is purely terminal and sparse; "format + execution" in the docs maps to the -1 / 0 / +1 scheme in code rather than a separate shaped format bonus.

### Gaps
- Per-benchmark numbers (Spider-dev/test/DK/Realistic/Syn, BIRD-dev) and the 653-sample selection criteria are on the Notion page (https://novasky-ai.notion.site/skyrl-sql), which rendered empty to the fetcher; the X thread and docs only give "up to 8.7%" and the qualitative claims.
- RL algorithm name, learning rate, batch size and GPU count were not retrievable (training script README returned 404 at the guessed paths).

## Key question 3: DySQL-Bench — does it train anything?

### Takeaway
No. DySQL-Bench (arXiv Oct 2025, ACL Findings 2026) is evaluation-only: 1,072 auto-synthesized tasks over 13 BIRD/Spider 2 databases, judged by a three-role loop (Qwen2.5-72B-Instruct simulated user, model under test, SQLite) with up to 30 dialogue turns and Pass^k metrics; it evaluates off-the-shelf models and contains no SFT or RL.

### Cited Findings
- Paper: "Rethinking Text-to-SQL: Dynamic Multi-turn SQL Interaction for Real-world Database Exploration", arXiv 2510.26495 (Oct 2025; v2 Nov 13, 2025), ACL 2026 Findings; code at github.com/Aurora-slz/DySQL-Bench — [arXiv](https://arxiv.org/abs/2510.26495); [ACL Anthology](https://aclanthology.org/2026.findings-acl.1654/); [GitHub](https://github.com/Aurora-slz/DySQL-Bench)
- "The paper does not train or fine-tune any models" (no sentences about training, fine-tuning or RL applied to new models were found in the HTML) — [arXiv HTML](https://arxiv.org/html/2510.26495)
- Evaluation framework: simulated user = Qwen2.5-72B-Instruct with task-specific instructions; model under evaluation receives DDL schema; executable SQLite database; max dialogue turns eta = 30; sampling temperature 0.6, top_p 0.95, top_k 20 — [arXiv HTML](https://arxiv.org/html/2510.26495)
- Scale and construction: 13 domains, 1,072 tasks; two-stage pipeline (databases -> hierarchical tree structures; LLM task generation + verification filtering); human validation by 10 domain experts, >99.5% inter-annotator agreement — [arXiv HTML](https://arxiv.org/html/2510.26495)
- Metrics / results: Pass^k for k = 1, 3, 5; GPT-4o "58.34% overall accuracy and 23.81% on the Pass^5 metric"; models evaluated: Qwen2.5-Max, Qwen2.5-72B-Instruct, Llama-3.1-70B-Instruct, OmniSQL-32B, Qwen3-32B, DeepSeek-V3, GPT-4o, Gemini-2.5-Flash — [arXiv HTML](https://arxiv.org/html/2510.26495); [arXiv abstract](https://arxiv.org/abs/2510.26495)
- Tasks require state manipulation: "not just information retrieval (SELECT) but continuous state manipulation (INSERT, UPDATE, DELETE)" — [arXiv abstract](https://arxiv.org/abs/2510.26495)
- A search for follow-up work that RL-trains on DySQL-Bench returned nothing relevant (only generic SWE-agent RL and ReToolSQL results) — [search context: ReToolSQL](https://arxiv.org/pdf/2608.27796)

### Inferences
- DySQL-Bench's three-role loop (LLM user + policy + DB with writes) is the same shape as a tau-bench-style RL environment, but as of Oct 2026 no published work uses it as a training environment; its 30-turn budget and Qwen2.5-72B user are the only concrete environment parameters available to copy.

### Gaps
- Per-model Pass^1/3/5 for the open models (e.g., Qwen3-32B, OmniSQL-32B) were not extracted; the paper's error taxonomy was not captured.
- Nothing on how the authors propose to use the benchmark for training.

## Key question 4: BIRD-Interact and agents trained on it; Spider 2.0 agents; other interactive/conversational systems (Interactive-T2S, T2S-Agent, TIDE-Bench, Agentar)

### Takeaway
BIRD-Interact (Oct 2025) trains nothing; the only trained system found that targets it is "Learning to Retrieve" (June 2026), which keeps GPT-5 as the policy and uses PPO only to train Qwen3-4B memory-retrieval selectors (episode reward = task success; turn reward = a 7B PRM). Spider 2.0 numbers from RL-trained open agents are sparse: SQL-ASTRA (OmniSQL-7B, 17.7% Spider 2.0) and SERL-SQL (32B, 26.78% Spider 2.0-SQLite). No 2025-26 paper other than MTSQL-R1 RL-trains on CoSQL/SParC; TIDE-Bench and Interactive-T2S are evaluation/prompting only; no system was found that RL-trains an agent to ask clarifying questions of a simulated user in text-to-SQL.

### Cited Findings
- BIRD-Interact (arXiv 2510.05318, Oct 2025; v3 Mar 24, 2026): 600-task Full (11,796 interactions) and 300-task Lite; function-driven user simulator (GPT-4o and Gemini-2.0-Flash tested) routes requests to AMB (annotated ambiguities) / LOC (localizable detail from gold SQL AST) / UNA (refuse); c-Interact = conversational with one debug chance per sub-task; a-Interact = ReAct with 9 actions and budget B = 6 + 2*m_amb + 2*lambda_pat (patience default 3); score = Success Rate online, normalized reward 70% primary / 30% follow-up offline — [arXiv HTML](https://arxiv.org/html/2510.05318); [arXiv abstract](https://arxiv.org/abs/2510.05318)
- BIRD-Interact-Full results (c-Interact SR / a-Interact SR / normalized reward): GPT-5 14.50 / 29.17 / 25.52; Gemini-2.5-Pro 25.00 / 20.33 / 20.92; Claude-Sonnet-4 22.33 / 27.83 / 23.28; o3-mini 24.00 / 19.83 / 16.43; Qwen3-Coder-480B 22.00 / 13.33 / 10.58; DeepSeek-V3.1 18.50 / 17.17 / 13.47. Abstract/Lite numbers: "GPT-5 completes only 8.67% of tasks in c-Interact and 17.00% in a-Interact" — [arXiv HTML](https://arxiv.org/html/2510.05318); [arXiv abstract](https://arxiv.org/abs/2510.05318)
- BIRD-Interact training status: "No models were trained/fine-tuned in this paper"; future work mentions a "post-trained, human-aligned local user simulator". Simulator leakage: function-driven design cuts baseline failure on unanswerable queries from 54-67.4% to 2.7%; 0.84 Pearson with humans vs 0.61 for a naive simulator — [arXiv HTML](https://arxiv.org/html/2510.05318)
- Learning to Retrieve: Dual-Level Long-Term Memory for Text-to-SQL Agents (arXiv 2606.00547, June 2026 by ID): policy = GPT-5 (low reasoning); user simulator = GPT-4o; PRM = DeepSeek-R1-Distill-Qwen-7B SFT'd on 5,346 teacher-annotated state-memory pairs; episode- and turn-level retrieval selectors = LoRA Qwen3-4B-Instruct-2507 trained with PPO, 4 epochs, batch 128, lr 1e-7; rewards: terminal task success (episode) and dense PRM utility (turn). BIRD-Interact phase-1 success 33.01% vs 23.33% no-memory; phase-2 22.17% vs 13.17%; avg turns 7.84 vs 8.93; Spider2-Snow transfer 69.29% — [arXiv HTML](https://arxiv.org/html/2606.00547)
- Spider 2.0 with RL-trained open models: SQL-ASTRA OmniSQL-7B 17.7% on Spider 2.0 vs ~15% binary-reward GRPO — [arXiv HTML](https://arxiv.org/html/2603.16161v1); SERL-SQL-32B 26.78% on Spider 2.0-SQLite — [arXiv HTML](https://arxiv.org/html/2608.00485v3)
- FlexSQL (arXiv 2605.02815, May 2026 by ID): prompting-only agent on gpt-oss-120b/20b with six tools (GetSchema, GetTableCol, GetColValues, FindRows, SQLExecutor, PythonExecutor); no SFT or RL; Spider2-Snow 55.15% Pass@1 (120b), 59.74% Maj@8, 65.44% Maj@16; Spider2-SQLite 57.78% Pass@1 — [arXiv HTML](https://arxiv.org/html/2605.02815)
- Spider 2.0 search for RL-trained agents surfaced only single-turn RL work (RingSQL synthetic data; "Human-Level Text-to-SQL via RL on Verified Data", Mar 2026, Qwen3-235B/Kimi-K2.6, single-turn, 2.5k verified BIRD-Platinum instances, Spider2 gains "0.6-16%") — [arXiv 2603.20004](https://arxiv.org/abs/2603.20004); [search](https://arxiv.org/pdf/2601.05451)
- Interactive-T2S (arXiv 2408.11062, Aug 2024, outside the window): prompting framework with four generic tools; "state-of-the-art results with only two exemplars" on BIRD-dev; no training — [arXiv PDF](https://arxiv.org/pdf/2408.11062)
- TIDE-Bench, "Evaluating LLMs on Conversational Text-to-SQL under Chain Ambiguity and Intent Drift" (arXiv 2608.29543, Aug 2026): 1,542 samples from 514 BIRD anchor SQLs; evaluates 12 LLMs; no training reported in the abstract — [arXiv](https://arxiv.org/abs/2608.29543)
- T2S-Agent, "Text-to-SQL Agent: An Iterative Question Rewriting Framework Based on Reinforcement Learning" (ACM DL): RL applied to the question-rewriting phase, agent "progressively approximating the user's true intent through dynamic interaction" (search snippet); the ACM page returned HTTP 403 — [ACM DL](https://dl.acm.org/doi/10.1145/3811238.3811548)
- Agentar-Scale-SQL (arXiv 2509.24403, Sep 2025): test-time-scaling framework whose "Intrinsic Reasoning SQL Generator" is RL-enhanced with GRPO, plus iterative refinement and tournament selection; BIRD dev 74.90% EX, test 81.67%; the RL component is single-turn — [arXiv PDF](https://arxiv.org/pdf/2509.24403)
- Searches for "SQL-Agent RL", "DB-Agent" RL and tau-bench-style DB-write agents trained with RL returned only general tool-use agent RL (MUA-RL, 2508.18669) which is outside this scope — [MUA-RL](https://arxiv.org/pdf/2508.18669)

### Inferences
- As of Oct 2026, no paper RL-trains a policy inside BIRD-Interact's or DySQL-Bench's user-in-the-loop environment; the closest is training auxiliary components (memory selectors) around a frozen frontier policy.
- Conversational text-to-SQL RL in the CoSQL/SParC sense is essentially a one-paper field (MTSQL-R1); the newer "conversational" benchmarks (TIDE-Bench, BIRD-Interact c-mode) have no trained baselines yet.

### Gaps
- T2S-Agent details (venue date, model, rewards, simulated user) could not be read (403).
- No evidence found for any "Interactive-T2S"-style RL extension, nor for a "DB-Agent" or "SQL-Agent RL" paper by those names.
- Spider-Agent / ReFoRCE RL variants: none found; the Spider 2.0 numbers above come from models trained on BIRD/Spider-1 and evaluated zero-shot.

## Key question 5: Other 2025-26 multi-turn/agentic text-to-SQL RL systems — recipes and SFT handling (SQL-Trail, TRUST-SQL, MTIR-SQL, MARS-SQL, SQL-ASTRA, SERL-SQL, ReToolSQL, DualSQL, AGRO-SQL, ReEx-SQL)

### Takeaway
Ten additional multi-turn RL systems were found, all GRPO-family, all rewarding final execution match, most capping episodes at 5-10 tool turns. They split cleanly on cold start: distilled-SFT-then-RL (SQL-Trail: 1,000 Claude-Sonnet-3.7 trajectories; TRUST-SQL: 70,970 trajectories from GPT-4.1-mini/GPT-4o-mini/DeepSeek-R1 on 9,217 SynSQL questions; AGRO-SQL: DeepSeek-V3.2; ReToolSQL: privileged self-traces; DualSQL: 3,755 BIRD examples), versus RL directly from an instruct model (SkyRL-SQL, MTIR-SQL, MARS-SQL, SQL-ASTRA, SERL-SQL, ReEx-SQL). The three papers that ablate it (SQL-Trail, TRUST-SQL, ReToolSQL) all find SFT->RL > RL-only > SFT-only, with the gap shrinking at 14B and reversing at 3B.

### Cited Findings

SQL-Trail (Amazon, arXiv 2601.17699, Jan 2026; ACL 2026 long)
- Base: Qwen2.5-Coder-Instruct 3B/7B/14B; two-stage SFT -> RL; 10-turn trajectory cap; G = 6 rollouts, temperature 1.0; observation returned in `<observation>` tags with column headers — [ACL PDF](https://aclanthology.org/2026.acl-long.1677.pdf); [arXiv HTML](https://arxiv.org/html/2601.17699)
- SFT data: "sample 3,000 Spider-train questions, generate multi-turn trajectories with Claude-Sonnet-3.7 using our agent template, and retain 1,000 trajectories with correct final SQL, prioritized toward medium/hard difficulty"; SFT batch 128, 2 epochs, lr 1e-5 — [ACL PDF, Sec. 4.2, App. A.5](https://aclanthology.org/2026.acl-long.1677.pdf)
- RL data: 1,027 prompts = 700 "hard-but-solvable" (non-degenerate pass@6) + 327 exploration set (127 post-SFT failures, 100 SynSQL pass@6 = 0, 100 extra-hard Spider pass@6 = 0); total training set 1,873 examples; RL batch 128, lr 1e-6, top-p 0.99, evaluated at step 108; GRPO with "clip-higher" — [ACL PDF](https://aclanthology.org/2026.acl-long.1677.pdf); [arXiv HTML](https://arxiv.org/html/2601.17699)
- Reward: R = 5*r_exec + 2*r_turns + r_schema + r_bigram + r_syntax + r_format; r_turns = 1 if (simple and t <= 2) or (medium and t <= 3) or (hard/extra and r_exec = 1 and t < T), else 0; r_schema = Jaccard over table/column names; r_bigram = Jaccard of SQL 2-grams; r_syntax = executable; r_format = tag compliance — [ACL PDF, Eq. 4 and 7](https://aclanthology.org/2026.acl-long.1677.pdf)
- Main results (Table 1, EX greedy/majority; Spider-dev, Spider-test, BIRD-dev): SQL-Trail-3B 76.3/83.1, 77.7/84.3, 50.1/55.1; SQL-Trail-7B 85.2/86.8, 86.0/87.6, 60.1/64.2; SQL-Trail-14B 85.1/87.1, 86.8/88.5, 63.6/66.7; baselines: Sonnet-3.7 single-pass 78.3/78.9, 82.0/83.2, 58.5/60.1; Sonnet-3.7 as untuned multi-turn agent 77.2/77.9, 81.9/82.0, 60.0/60.8; Qwen2.5-Coder-7B-Instruct single-pass 73.4/77.1, 82.2/85.6, 50.9/61.3; SQL-R1-7B 81.9/84.5, 83.5/86.1, 58.9/63.1; OmniSQL-7B 81.2/81.6, 87.9/88.9, 63.9/66.1 — [ACL PDF, Table 1](https://aclanthology.org/2026.acl-long.1677.pdf)
- Cold-start ablation (Table 7, EX Spider-dev / Spider-test / BIRD-dev): 3B SFT-only 83.1/82.9/55.7, RL-only 84.6/83.1/55.2, SFT+RL 84.6/84.3/55.2; 7B SFT-only 83.6/83.5/58.7, RL-only 85.8/86.8/61.7, SFT+RL 86.5/87.0/64.2; 14B SFT-only 83.3/86.1/64.8, RL-only 86.9/87.2/65.4, SFT+RL 87.1/88.5/66.7; "RL with SFT cold-start yields the highest performance, surpassing both the RL model trained without cold-start and the SFT-only baseline" — [ACL PDF, Table 7](https://aclanthology.org/2026.acl-long.1677.pdf)
- Single-pass vs multi-turn RL, identical data/hyperparameters (Table 2, majority EX): single-pass 82.8 / 85.1 / 56.3; multi-turn 84.5 / 86.1 / 59.3 — [ACL PDF, Table 2](https://aclanthology.org/2026.acl-long.1677.pdf)
- Reward ablation (Table 6, 7B, BIRD-dev greedy/majority, avg turns): all rewards 60.1/64.2 (2.26 turns); w/o turns 59.3/63.2 (3.19 turns, std 2.12); w/o n-gram 57.2/61.6; w/o schema 58.5/62.6; w/o syntax 59.1/63.8; w/o format 59.8/62.9; w/o execution 57.9/62.8; post-SFT-only 57.8/58.7 (2.53 turns); untuned Qwen2.5-Coder-7B agent 49.1/51.2 with 6.44 turns; untuned Sonnet agent 60.0/60.8 with 4.24 turns — [ACL PDF, Table 6](https://aclanthology.org/2026.acl-long.1677.pdf)
- Degenerate behaviour: "both Sonnet and base Qwen generate overly long trajectories ... Sonnet wastes turns probing the schema, while base Qwen repeatedly revises flawed SQL due to weaker syntax"; "SFT improves syntax accuracy and shortens trajectories, but schema linking remains difficult; RL further improves schema identification" — [ACL PDF, Sec. 5.2](https://aclanthology.org/2026.acl-long.1677.pdf)
- Data-efficiency metric: EX gain (pp) per 1,000 training examples; SQL-Trail-7B 1.90 (Spider-test) / 4.60 (BIRD-dev) vs SQL-R1-7B 0.26 / 1.6 and OmniSQL-7B 0.002 / 0.005; "7-18x higher efficiency" — [ACL PDF, Table 1](https://aclanthology.org/2026.acl-long.1677.pdf)

TRUST-SQL (arXiv 2603.16448, Mar 2026; claims EMNLP main)
- Base: Qwen3-4B and Qwen3-8B; unknown-schema POMDP: Explore (metadata queries) -> Propose (commit to verified schema K) -> Generate -> Confirm; tool `execute_sql_query` on SQLite; training budget 10 turns ("further increasing to 12 turns causes severe training instability"); inference 15 turns for majority voting — [arXiv HTML v1](https://arxiv.org/html/2603.16448v1)
- SFT data: 9,217 SynSQL-2.5M questions (moderate/complex/highly-complex) annotated by GPT-4.1-mini, GPT-4o-mini and DeepSeek-R1, kept if execution-correct and format-compliant: 70,970 trajectories, 61.7% (43,803) from GPT-4.1-mini — [arXiv HTML v1](https://arxiv.org/html/2603.16448v1)
- RL data: 18,078 BIRD+Spider train questions -> 11,642 retained (pass rate < 6/8 filter), 8 rollouts each — [arXiv HTML v1](https://arxiv.org/html/2603.16448v1)
- Dual-Track GRPO: schema track (trajectory up to Propose) with R_schema, full track with R_exec + R_fmt; token-level masked advantages (tokens after Propose get zero schema advantage); loss = L_full + lambda * L_schema, lambda = 0.25 — [arXiv HTML v1](https://arxiv.org/html/2603.16448v1)
- Rewards: R_exec 1.0 correct / 0.2 executable-but-wrong / 0.0 non-executable; R_fmt 0.1; R_schema binary schema match, paid only when R_exec = 1.0 — [arXiv HTML v1](https://arxiv.org/html/2603.16448v1)
- Results (greedy / majority): TRUST-SQL-4B BIRD-dev 64.9/67.2, Spider-test 82.8/85.0, Spider-DK 71.6/73.8, Spider-Syn 74.7/77.3, Spider-Realistic 79.9/82.5; TRUST-SQL-8B BIRD-dev 65.8/67.7, Spider-test 83.9/86.5, Spider-DK 72.1/75.7, Spider-Syn 75.4/77.4, Spider-Realistic 82.1/84.1; base Qwen3-4B without schema prefill 29.3% BIRD-dev; abstract: average absolute gains 30.6 (4B) and 16.6 (8B) over base across five benchmarks — [arXiv HTML v1](https://arxiv.org/html/2603.16448v1); [arXiv abstract](https://arxiv.org/abs/2603.16448)
- SFT/RL ablation (4B, BIRD-dev): SFT-only 46.2; RL-only 59.9; SFT+RL 64.9. RL-only "hacks" by "exhaustively querying all tables in turn one", degenerating the unknown-schema task into full-schema prefill (4.23 tool calls vs 3.66 with SFT). Over-weighted schema reward (lambda = 0.375) collapses accuracy to 54.2% with 7.66 avg turns vs 5.64; naive schema-reward mixing 58.7; pure execution (lambda = 0) 60.9; dual-track 64.5 — [arXiv HTML v1](https://arxiv.org/html/2603.16448v1)

MTIR-SQL (arXiv 2510.25510, Oct 2025; ICLR 2026)
- Base: Qwen3-4B; RL-only from the base model, no SFT described; SQLite execution returns column headers and up to 10 rows; N = 6 tool calls max; temperature 0.6; 5 rollouts per prompt — [arXiv HTML](https://arxiv.org/html/2510.25510); [ICLR page](https://iclr.cc/virtual/2026/10017469)
- Algorithm: "GRPO-Filter" = GRPO without KL term plus trajectory filtering (keep only trajectories meeting predefined criteria) to counter instability and distribution drift — [arXiv HTML](https://arxiv.org/html/2510.25510)
- Rewards: format +0.1 / -0.1; executable +0.1 / -0.1; result correct +1 / -1 — [arXiv HTML](https://arxiv.org/html/2510.25510)
- Data: BIRD and Spider train, filtered for executability and low redundancy, empty-result references dropped (counts not stated) — [arXiv HTML](https://arxiv.org/html/2510.25510)
- Results: BIRD-dev 64.4% (vs SQL-R1-7B 63.1%, Qwen2.5-Coder-3B 48.1%); Spider dev 84.6% per abstract (HTML extraction also lists 82.4 dev / 83.4 test, so the dev figure is inconsistent between the two extractions); removing execution reward -3.9 pts — [arXiv abstract](https://arxiv.org/abs/2510.25510); [arXiv HTML](https://arxiv.org/html/2510.25510)

MARS-SQL (arXiv 2511.01008, Nov 2025; v2 May 2026)
- Base: Qwen2.5-Coder-7B-Instruct for three agents (grounding, generation, validation); generation agent = ReAct loop with live execution, T = 10 turns; GRPO without SFT cold start; sparse reward 1.0 correct / 0.0 valid-but-wrong / -1.0 invalid; validation agent SFT'd on ~16k self-generated trajectory preference triples (16 candidates per question), selects by "Yes"-token probability over 8 rounds — [arXiv HTML](https://arxiv.org/html/2511.01008)
- Data: BIRD train filtered 9,428 -> 8,036; ~35k examples total across agents; ~13 h on 4x H800 — [arXiv HTML](https://arxiv.org/html/2511.01008)
- Results: BIRD-dev 77.84%, Spider-test 89.75%, Spider-DK 78.13%; generator-only 66.37%; w/o validation 68.71%; w/o grounding 69.75%; self-consistency instead of validator 72.93% — [arXiv HTML](https://arxiv.org/html/2511.01008)

SQL-ASTRA (arXiv 2603.16161, Mar 2026; ACL Findings 2026)
- Base: Qwen2.5-7B-Instruct (no cold start) and OmniSQL-7B (needed a "Format-6k" SFT to learn the tool-call format); Qwen2.5-Coder rejected for "insufficient exploratory capabilities"; max 3 tool calls — [arXiv HTML](https://arxiv.org/html/2603.16161v1)
- Rewards: Column-Set Matching Reward per step (dense [0,1] from column value-set overlap, capped at alpha ~0.8 so only exact match gets 1.0) + Aggregated Trajectory Reward via an asymmetric transition matrix (|R_high->low| > |R_low->high|) to kill oscillation loops; GRPO with tool-output masking — [arXiv HTML](https://arxiv.org/html/2603.16161v1)
- Data: BIRD train 8,958 after filtering; results: BIRD 64.2% vs binary GRPO 58.5% (Qwen 7B); Spider-dev 82.9 vs 79.2; OmniSQL-7B BIRD 69.1 vs 67.4, Spider 2.0 17.7 vs ~15; symmetric matrix 60.1; step-wise update 61.3; agentic rollout ~2x the wall time of single-turn — [arXiv HTML](https://arxiv.org/html/2603.16161v1)

SERL-SQL (arXiv 2608.00485, Aug 2026; v3)
- Base: Qwen2.5-Coder-Instruct 7B/14B/32B; 5-turn default; no SFT cold start; GRPO with +1 / 0 / -1 trajectory reward; "selective hindsight distillation": a teacher re-scores the student's on-policy SQL/tool tokens given execution feedback, and the log-prob gap becomes bounded advantage weights on SQL and tool-action tokens only; training on BIRD only — [arXiv HTML](https://arxiv.org/html/2608.00485v3)
- Results: BIRD-dev 75.55 (7B), 74.95 (14B), 76.56 (32B); Spider-test 89.24 (7B), 89.92 (14B), 89.78 (32B); Spider 2.0-SQLite 26.78 (32B); ablations: schema grounding -9.5, execution hindsight -3.0, weight clipping -1.8, selective masking -1.5 — [arXiv HTML](https://arxiv.org/html/2608.00485v3)

ReToolSQL (arXiv 2608.27796, Aug 2026)
- Base: Gemma 4 31B Instruct, ablation on Gemma 4 E4B; three read-only tools (`sqlite_query` SELECT/WITH only, 5 s timeout; `sqlite_peek` column profiler; `bm25_search_sqlite` value search); 8 turns max — [arXiv HTML](https://arxiv.org/html/2608.27796)
- SFT: pass@16 identifies an "all-wrong band" of hard examples; teacher traces generated with privileged access to gold SQL for those, self-traces for easy/medium, all verified by execution match — [arXiv HTML](https://arxiv.org/html/2608.27796)
- RL: GRPO with DAPO-style asymmetric clipping (0.20 / 0.28), dynamic sampling K = 12, tool-observation loss masking, decaying KL 0.005 -> 0.001 -> 0; reward = execution match 2.0 + format 0.2 + syntax 0.5 + table coverage 0.5 + column coverage 0.5 (Jaccard) + non-empty result 0.1 - length penalty 0.1; data = BIRD train 6,601 questions, 1 epoch — [arXiv HTML](https://arxiv.org/html/2608.27796)
- BIRD-dev EX: base 71.19; SFT-only 72.69; RFT from base 73.66 (74.12 SC@16); SFT->RFT 74.32 (74.77 SC@16); SFT raises pass@16 on hard questions to 81.29, RFT keeps 81.94; E4B 68.45% with a larger RL gain (+3.33 vs +1.95 for 31B); tool access alone +2.02, RL alone +0.45, both +3.97 — [arXiv HTML](https://arxiv.org/html/2608.27796)

DualSQL (arXiv 2609.18135, Sep 2026)
- Base: Qwen3-4B and Qwen3-8B, one backbone playing schema-linker (5 turns) and SQL-generator (10 turns) with SQL executor, full-text search and DB profiler tools; SFT cold start on 3,755 BIRD examples (2,715 trivial removed, 384 annotation errors corrected); GRPO with token-mean loss, clip-higher, sequence-level masked importance sampling; rewards: schema-linking F1, execution match with tool-use bonus, "robust execution match" (REX), length penalties; 32K-token limit with 4K overlong buffer; "strict format checking with rollout cutoff and error-focused loss masking" against malformed trajectories — [arXiv HTML](https://arxiv.org/html/2609.18135)
- Results: DualSQL-4B 68.0% BIRD-dev EX (64.0 REX); DualSQL-8B 71.1% BIRD-dev, 83.1% Spider; multi-agent RL +1.5 EX over single-agent — [arXiv HTML](https://arxiv.org/html/2609.18135)

AGRO-SQL (arXiv 2512.23366, Dec 2025)
- Base: Qwen3-8B-Base; multi-turn action-feedback loop (max turns not stated); "Diversity-Aware Cold Start" SFT from DeepSeek-V3.2 trajectories selected by hybrid embeddings of SQL actions and reasoning (count not stated); synthetic data kept only when execution matches gold ("Generation-as-Verification"); GRPO, reward 1.0 correct / -1.0 invalid format, batch 256 x 10 rollouts, lr 5e-6, temperature 0.7; BIRD train 9,428 — [arXiv HTML](https://arxiv.org/html/2512.23366)
- Results: BIRD-dev 72.10%, Spider-dev 89.13%; no cold-start ablation — [arXiv HTML](https://arxiv.org/html/2512.23366)

ReEx-SQL (arXiv 2505.12768, May 2025)
- Base: Qwen2.5-Coder-7B-Instruct; execution interleaved mid-generation via `<intermediate_sql>` / `<result>` tags, N = 10 interactions; GRPO without SFT; composite reward weights: format 2.0, execution 3.0, exact match 1.0, entity match 1.0, exploration 2.0; BIRD-dev 64.9%, Spider-test 86.6% (abstract says 88.8%), Spider-Realistic 85.2%; dropping execution reward -6.5 on BIRD; tree-based decoding cuts inference time 51.9% — [arXiv HTML](https://arxiv.org/html/2505.12768); [arXiv abstract](https://arxiv.org/abs/2505.12768)

### Inferences
- The field has converged on a 5-10 turn cap during training; papers that pushed higher (TRUST-SQL 12) report instability, and MTSQL-R1 found 2,000-token caps break long-horizon agents while 8,000 is mostly sufficient.
- Where distilled SFT is used, the teacher is a frontier closed model (Claude-Sonnet-3.7, GPT-4.1-mini, DeepSeek-V3.2) or the model itself with privileged gold SQL (ReToolSQL) or self-rejection sampling (MTSQL-R1); trajectory counts range from 1,000 (SQL-Trail) to 70,970 (TRUST-SQL), and all are filtered by execution correctness of the final SQL.
- Shaped auxiliary rewards (schema Jaccard, n-gram, clause F1, column-set match) are consistently reported to help by 1-6 EX points over binary execution reward, but every paper keeps execution match as the dominant term (weights 2-5x the shaping terms).

### Gaps
- MTIR-SQL and SQL-ASTRA do not state training set sizes precisely; AGRO-SQL omits its SFT trajectory count and max turns.
- MTIR-SQL Spider-dev figure appears as 84.6 (abstract) and 82.4 (HTML extraction) — unresolved.
- None of these papers uses a simulated user; "multi-turn" means policy-DB turns.

## Key question 6: Reward designs used for multi-turn SQL

### Takeaway
Every system found rewards the final SQL by executing it and comparing result sets (order-insensitive set/frozenset equality in SkyRL-SQL; "execution match" elsewhere); none rewards final database state, because all training tasks are SELECT-only. Shaping is added via (a) per-turn/intermediate signals (MTSQL-R1 clause-F1 process rewards, SQL-ASTRA per-step column-set match, TRUST-SQL schema track), (b) efficiency penalties (SQL-Trail difficulty-aware turn reward, ReToolSQL length penalty, DualSQL length penalty), and (c) format penalties (-1 in SkyRL-SQL/MARS-SQL/SERL-SQL/AGRO-SQL, +-0.1 in MTIR-SQL).

### Cited Findings
- Result-set match, terminal only: SkyRL-SQL `frozenset(cur.fetchall())` equality, +1 / 0 / -1 format, "No reward for intermediate steps" — [utils.py](https://raw.githubusercontent.com/NovaSky-AI/SkyRL/main/skyrl-gym/skyrl_gym/envs/sql/utils.py); [env.py](https://raw.githubusercontent.com/NovaSky-AI/SkyRL/main/skyrl-gym/skyrl_gym/envs/sql/env.py); MARS-SQL 1.0 / 0.0 / -1.0 — [arXiv](https://arxiv.org/html/2511.01008); SERL-SQL +1 / 0 / -1 — [arXiv](https://arxiv.org/html/2608.00485v3); AGRO-SQL 1.0 / -1.0 — [arXiv](https://arxiv.org/html/2512.23366)
- Graded execution: TRUST-SQL 1.0 correct / 0.2 executable-but-wrong / 0.0 non-executable, plus 0.1 format and a schema reward gated on R_exec = 1 — [arXiv](https://arxiv.org/html/2603.16448v1); MTIR-SQL +-0.1 format, +-0.1 executable, +-1 result — [arXiv](https://arxiv.org/html/2510.25510)
- Per-action process rewards: MTSQL-R1 clause-level F1 for PROPOSE/SELF-CORRECT, {0, 0.1, 1} lookup for E-VERIFY, F1 or 1-F1 for M-VERIFY, combined as w1*(EX+EM) + w2*(process); ablation shows +0.8 EX at 4B — [arXiv](https://arxiv.org/html/2510.12831); [PDF Table 10](https://arxiv.org/pdf/2510.12831v3)
- Per-step dense reward with anti-oscillation aggregation: SQL-ASTRA CSMR in [0, alpha=0.8] per turn and asymmetric transition matrix so that dropping quality is penalized more than recovering it; +5.7 BIRD over binary GRPO — [arXiv](https://arxiv.org/html/2603.16161v1)
- Turn-count shaping: SQL-Trail r_turns (weight 2 of 11) pays 1 only if the agent finishes within 2 turns (simple), 3 (medium) or before the cap with a correct answer (hard); removing it raises mean turns from 2.26 to 3.19 and std from 0.65 to 2.12 while BIRD-dev greedy drops 60.1 -> 59.3 — [ACL PDF, Eq. 7 and Table 6](https://aclanthology.org/2026.acl-long.1677.pdf)
- Composite shaping with coverage terms: ReToolSQL execution 2.0, format 0.2, syntax 0.5, table/column coverage Jaccard 0.5 each, non-empty 0.1, length penalty -0.1 — [arXiv](https://arxiv.org/html/2608.27796); ReEx-SQL format 2.0, execution 3.0, EM 1.0, entity 1.0, exploration 2.0 — [arXiv](https://arxiv.org/html/2505.12768); SQL-Trail 5 exec + 2 turns + schema + bigram + syntax + format — [ACL PDF](https://aclanthology.org/2026.acl-long.1677.pdf)
- Multi-agent / multi-track credit assignment: TRUST-SQL token-masked dual-track advantages (lambda = 0.25; lambda = 0.375 collapses to 54.2% with 7.66 turns) — [arXiv](https://arxiv.org/html/2603.16448v1); DualSQL schema-linking F1 + execution + tool-use bonus + REX + length penalty — [arXiv](https://arxiv.org/html/2609.18135)
- Reward-hacking reports: TRUST-SQL RL-only policy dumps all tables in turn 1 to convert unknown-schema into full-schema (59.9 vs 64.9 with SFT) — [arXiv](https://arxiv.org/html/2603.16448v1); SQL-Trail untuned agents spam turns (Qwen 6.44 avg turns, Sonnet 4.24) — [ACL PDF Table 6](https://aclanthology.org/2026.acl-long.1677.pdf); SQL-ASTRA documents "repetitive generation" and "numerous unnecessary loops" with symmetric step rewards (60.1 vs 64.2) — [arXiv](https://arxiv.org/html/2603.16161v1); DualSQL uses rollout cutoff on format violation to stop malformed trajectories — [arXiv](https://arxiv.org/html/2609.18135); MARS-SQL reports no reward hacking with sparse rewards — [arXiv](https://arxiv.org/html/2511.01008)
- Evaluation-side rewards that could be reused for write tasks: BIRD-Interact normalized reward = 0.7 primary + 0.3 follow-up with debugging penalties, success judged by test cases on the PostgreSQL state; DySQL-Bench judges final DB state after INSERT/UPDATE/DELETE with Pass^k — [BIRD-Interact](https://arxiv.org/html/2510.05318); [DySQL-Bench](https://arxiv.org/html/2510.26495)

### Inferences
- A final-DB-state reward for write tasks has no published RL precedent in text-to-SQL; the closest analogues are the result-set rewards above plus the state-checking evaluators of BIRD-Interact and DySQL-Bench.
- The two reproducible fixes for turn-spamming are an explicit per-difficulty turn reward (SQL-Trail) or a hard cap plus asymmetric step rewards (SQL-ASTRA); both are cheap to add to a GRPO loop.

### Gaps
- No paper reports a reward for asking the user a clarifying question or a penalty for an unexecuted final SQL beyond the generic "non-executable = 0" term.

## Key question 7: Can a 1.7B / 4B policy learn multi-turn SQL from RL alone?

### Takeaway
At 4B, yes for read-only tool loops when the base already follows the tag protocol: MTIR-SQL takes Qwen3-4B from base to 64.4% BIRD-dev with RL only; but TRUST-SQL shows RL-only Qwen3-4B plateaus at 59.9% vs 64.9% with SFT and learns a degenerate dump-all-tables strategy. At 3B, SQL-Trail finds RL-only equals SFT+RL on BIRD (55.2 vs 55.2) and SFT alone is slightly better (55.7). At 1.7B, the only evidence (MTSQL-R1) shows the untrained long-horizon agent at 22.6% EX (vs 59.9% for single-shot prompting), and the authors rely on three rounds of self-taught SFT before GRPO; no 1.7B RL-only multi-turn result exists in the literature found.

### Cited Findings
- MTSQL-R1 Qwen3-1.7B: long-horizon base agent without training 22.6 EX (CoSQL) / 23.9 (SParC); warm-start SFT round 1 69.9 / 70.6; SFT+RL 77.3 / 76.2; "Small LLMs struggle to follow long-horizon function-calling instructions"; no long-horizon RL-only row — [arXiv PDF v3, Table 2](https://arxiv.org/pdf/2510.12831v3)
- MTSQL-R1 Qwen3-4B long-horizon base agent without training 60.3 / 57.6 EX (vs 22.6 / 23.9 for 1.7B), i.e., the 4B model already follows the tool protocol far better — [arXiv PDF v3, Table 2](https://arxiv.org/pdf/2510.12831v3)
- MTSQL-R1 LLaMA3.2-3B-Instruct base 22.9 / 24.4 -> SFT+RL 74.8 / 75.2 — [arXiv PDF v3, Table 11](https://arxiv.org/pdf/2510.12831v3)
- TRUST-SQL Qwen3-4B: SFT-only 46.2, RL-only 59.9, SFT+RL 64.9 BIRD-dev; RL-only reward hack (query all tables turn 1); base without schema prefill 29.3 — [arXiv](https://arxiv.org/html/2603.16448v1)
- MTIR-SQL Qwen3-4B RL-only (GRPO-Filter, no KL, 5 rollouts, 6 tool calls): BIRD-dev 64.4, Spider-dev 84.6 (abstract) — [arXiv abstract](https://arxiv.org/abs/2510.25510); [arXiv HTML](https://arxiv.org/html/2510.25510)
- SQL-Trail Qwen2.5-Coder-3B (Table 7, Spider-dev / Spider-test / BIRD-dev): SFT-only 83.1/82.9/55.7; RL-only 84.6/83.1/55.2; SFT+RL 84.6/84.3/55.2; 3B main result 76.3/83.1 Spider-dev, 50.1/55.1 BIRD (greedy/majority) vs single-pass base 72.8/77.0, 45.2/50.5 — [ACL PDF, Tables 1 and 7](https://aclanthology.org/2026.acl-long.1677.pdf)
- DualSQL-4B (Qwen3-4B, SFT on 3,755 + GRPO): 68.0% BIRD-dev — [arXiv](https://arxiv.org/html/2609.18135)
- ReToolSQL Gemma 4 E4B: RFT from base 68.45% BIRD-dev; "smaller model shows larger RL gains (+3.33% vs +1.95%)" — [arXiv](https://arxiv.org/html/2608.27796)
- SQL-ASTRA: Qwen2.5-Coder-7B-Instruct was unusable for agentic RL due to "insufficient exploratory capabilities" and OmniSQL-7B needed a 6k-example format SFT before RL — [arXiv](https://arxiv.org/html/2603.16161v1)
- SkyRL-SQL: 7B instruct with no SFT and a -1 format penalty learned the 5-turn protocol from 653 prompts in 14 epochs — [SkyRL docs](https://skyrl.readthedocs.io/en/latest/recipes/skyrl-sql.html); [utils.py](https://raw.githubusercontent.com/NovaSky-AI/SkyRL/main/skyrl-gym/skyrl_gym/envs/sql/utils.py)

### Inferences
- The deciding variable is whether the base model can already emit the tool protocol at a non-trivial success rate: Qwen3-4B (60% untrained in MTSQL-R1's format) and Qwen2.5-Coder-7B-Instruct learn from RL alone, while Qwen3-1.7B (22.6%) and LLaMA3.2-3B (22.9%) in the richer 6-action MTSQL-R1 protocol do not produce enough successful rollouts for GRPO without a warm start; a smaller-vocabulary protocol (SkyRL's three tags) lowers that bar.
- Where the task has a hidden structure that can be bypassed (unknown schema in TRUST-SQL), RL-only policies find the bypass; SFT fixes the behaviour prior, not just the format.
- At 3B, SQL-Trail's flat SFT-vs-RL numbers on BIRD suggest the ceiling is model capacity rather than training recipe for cross-domain transfer.

### Gaps
- No paper trains a 1.7B (or smaller) model with multi-turn RL and no SFT; the 1.7B evidence is a single paper (MTSQL-R1) on CoSQL/SParC with gold-history memory.
- No study of how many SFT trajectories are "enough" at 1.7B-4B; counts range from 1,000 (SQL-Trail 7B) to 70,970 (TRUST-SQL 4B/8B) without a controlled sweep.
- No small-model result exists with a simulated user in the loop.

## Key question 8: OmniSQL / SynSQL-2.5M as SFT or trajectory source; converting single-turn data to multi-turn agent trajectories

### Takeaway
SynSQL-2.5M is the dominant seed for agentic RL prompts and for distilled trajectories: SkyRL-SQL's 653 prompts and SQL-Trail's 800 RL prompts come from its databases/questions, and TRUST-SQL converts 9,217 SynSQL questions into 70,970 multi-turn tool trajectories with three teacher LLMs. OmniSQL-7B itself is used as an RL starting point (SQL-ASTRA) but needs a 6k-example format SFT first. The standard conversion recipe is: take a single-turn (question, gold SQL, DB) triple, run a teacher or the policy itself in the agent template with a SQL executor, keep trajectories whose final SQL execution matches the gold result, and optionally filter by difficulty or pass@k.

### Cited Findings
- SynSQL-2.5M: 2,544,390 synthetic samples; OmniSQL 7B/14B/32B trained on it (VLDB 2025) — [OmniSQL arXiv](https://arxiv.org/pdf/2503.02240); [VLDB](https://www.vldb.org/pvldb/vol18/p4695-li.pdf)
- TRUST-SQL: 9,217 SynSQL-2.5M questions of moderate/complex/highly-complex difficulty -> trajectories by GPT-4.1-mini, GPT-4o-mini, DeepSeek-R1 -> 70,970 kept by execution correctness + format compliance (61.7% from GPT-4.1-mini) — [arXiv](https://arxiv.org/html/2603.16448v1)
- SQL-Trail: SFT = 1,000 of 3,000 Claude-Sonnet-3.7 trajectories on Spider-train (correct final SQL, medium/hard prioritized); RL = SynSQL(0.8k) + Spider(1k), total 1,873 examples, selected by pass@6 bands — [ACL PDF](https://aclanthology.org/2026.acl-long.1677.pdf)
- SkyRL-SQL: 653 prompts; DBs "from SynSQL-2.5M and Spider, sourced from OmniSQL dataset collections"; dataset rows carry a `synsql` field — [SkyRL docs](https://docs.skyrl.ai/docs/recipes/skyrl-sql); [HF dataset](https://huggingface.co/datasets/NovaSky-AI/SkyRL-SQL-653-data)
- SQL-ASTRA: OmniSQL-7B as RL base required "Format-6k fine-tuning step to acquire the tool-calling format"; after RL BIRD 69.1, Spider 2.0 17.7 — [arXiv](https://arxiv.org/html/2603.16161v1)
- MTSQL-R1: self-taught conversion of CoSQL/SParC single-turn-per-question data into 4-interaction tool trajectories by rejection sampling the policy's own rollouts (20 per question, 3 rounds) — [arXiv HTML](https://arxiv.org/html/2510.12831)
- ReToolSQL: converts BIRD single-turn pairs into tool trajectories with "privileged access to the gold reference SQL as contextual guidance" for examples the model fails at pass@16, self-traces otherwise, all execution-verified — [arXiv](https://arxiv.org/html/2608.27796)
- AGRO-SQL: DeepSeek-V3.2 trajectories with diversity-aware selection on hybrid embeddings of SQL actions and reasoning; synthetic examples kept only on exact execution match — [arXiv](https://arxiv.org/html/2512.23366)
- OmniSQL as a baseline for data efficiency: OmniSQL-7B trained on SynSQL(2.5M)+BIRD(9.4k)+Spider(8.7k) scores 0.002 pp per 1k examples on Spider-test vs SQL-Trail-7B 1.90 — [ACL PDF Table 1](https://aclanthology.org/2026.acl-long.1677.pdf)

### Inferences
- No paper converts SynSQL single-turn data into user-in-the-loop (clarification / follow-up) dialogues; all conversions are policy-DB tool trajectories.
- Difficulty filtering (TRUST-SQL moderate+; SQL-Trail medium/hard, pass@6 in (0,1)) is universal; trivial SynSQL items are dropped before trajectory generation.

### Gaps
- SkyRL-SQL's exact 653-sample selection rule (difficulty / pass-rate filter) is not documented in the pages reachable here.
- No published yield numbers for teacher trajectory generation on SynSQL other than TRUST-SQL's 9,217 -> 70,970 (multiple trajectories per question; per-question acceptance rate not stated).
