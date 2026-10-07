# Multi-turn RL for general agents with a simulated user (2025-01 .. 2026-10)

Scope: general (non-text-to-SQL) agents trained with RL in a loop that contains an LLM user simulator and/or a tool environment. Target reader: someone training a 1.7B-4B user-agent-database text-to-SQL agent. All numbers are quoted from the primary source; "not stated" means the source (abstract/HTML as fetched) did not give it. Months are arXiv v1 months unless noted.

## KQ1. Paper-by-paper methodology: user-simulator-in-the-loop RL (tau-bench-style, collaborative, clarification)

### Takeaway
Every 2025-26 paper that puts an LLM user in the RL loop uses a *frozen* prompted simulator (GPT-4o / Qwen3-32B / Qwen3-8B / DeepSeek-V4-Flash / Gemini-3-pro), GRPO-family critic-free optimisation, a sparse 0/1 outcome reward on final environment state (optionally plus a small per-turn or "reaction" term), a 10-30 turn cap, and an SFT cold start of only ~1.5K-5K trajectories against a few hundred RL tasks. The strongest small-model results (Qwen3-4B/8B) come from UserRL, BAO, MUA-RL and FACA.

### Cited Findings

#### UserRL (Salesforce + UIUC, 2025-09, arXiv 2509.19736)
- Framework: "eight distinct gym environments with a standardized interaction interface", RL on five of them; "integrates multi-turn RL rollouts with LLM-based user simulation" — [arXiv 2509.19736](https://arxiv.org/abs/2509.19736)
- Base models: "Qwen3 models of 4B and 8B parameters", with 14B/32B as comparison — [UserRL HTML](https://arxiv.org/html/2509.19736)
- User simulator: "Qwen3-32B as the simulated user model" for the main runs; GPT-4o tested as alternative training-time user; fixed (not co-trained); IntentionGym temperature 0.7 for naturalness, 0.0 for evaluation calls — [UserRL HTML](https://arxiv.org/html/2509.19736)
- Simulator constraint text (IntentionGym, Fig. 4): "Do NOT provide what missing details need to be clarified or give any examples. Do NOT provide concrete help or solutions." — [UserRL HTML v1](https://arxiv.org/html/2509.19736v1)
- Cold start: "1K trajectories sampled from each of the five training gyms" with "GPT-4o as both the agent and simulated user" -> 5,000 SFT trajectories (distillation) — [UserRL HTML](https://arxiv.org/html/2509.19736)
- RL training tasks: TravelGym 925, TurtleGym 423, FunctionGym 460, TauGym 500, PersuadeGym 378 (total 2,686) — [UserRL HTML](https://arxiv.org/html/2509.19736)
- Algorithm: GRPO, "we remove KL regularization and apply temperature 1.0"; "batch of 128, and generate 8 responses per query, training for 15 epochs"; "max interaction turns to 16 without step penalty" — [UserRL HTML](https://arxiv.org/html/2509.19736); [UserRL HTML v1](https://arxiv.org/html/2509.19736v1)
- Reward shaping variants: turn-level Naive / Equalized (r_t = c) / R2G (reward-to-go, discounted) / EM (exponential mapping); trajectory-level Sum vs R2G. "Equalized/R2G setting consistently achieves the best performance"; naive turn shaping "quickly leads to training collapse" — [UserRL HTML](https://arxiv.org/html/2509.19736)
- Results (avg over 8 gyms): Qwen3-8B Equalized/R2G 0.5652; Qwen3-4B Equalized/R2G 0.5269; raw Qwen3-32B 0.3128; raw Qwen3-4B 0.2929 — [UserRL HTML](https://arxiv.org/html/2509.19736)
- SFT finding: "models with SFT cold start not only begin from a higher baseline but also continue to improve, whereas models trained without SFT plateau early"; gains "exceeding 100%" on some tasks — [UserRL HTML](https://arxiv.org/html/2509.19736)
- Simulator finding: "GPT-4o-based training generally yields higher performance" than Qwen3-32B, but open-source simulators "remain a cost-effective and transferable option" — [UserRL HTML v1](https://arxiv.org/html/2509.19736v1); [arXiv abstract](https://arxiv.org/abs/2509.19736)

#### UserBench (Salesforce + UIUC, 2025-07, arXiv 2507.22034) — evaluation gym that UserRL's TravelGym builds on
- "simulated users who start with underspecified goals and reveal preferences incrementally"; models "fully align with all user intents only 20% of the time on average", best models "uncover fewer than 30% of all user preferences" — [arXiv 2507.22034](https://arxiv.org/abs/2507.22034)

#### BAO: Behavioral Agentic Optimization (CMU et al., 2026-02, rev. 2026-06, arXiv 2602.11351)
- Base models: Qwen3 1.7B and 4B (the closest match to the target size) — [BAO HTML](https://arxiv.org/html/2602.11351)
- User simulator: Qwen3-8B during training; GPT-4o at evaluation on Telepathy-Gym and Turtle-Gym "to introduce distribution shift" — [BAO HTML](https://arxiv.org/html/2602.11351)
- Cold start: SFT warm-start on data synthesised with GPT-4o using explicit behaviour prompts, then behaviour-regularised GRPO with turn-level advantages — [BAO HTML](https://arxiv.org/html/2602.11351)
- Two objectives: accumulated task reward R(tau) vs user engagement U(tau) = "the number of user-involved actions per trajectory" — [BAO HTML](https://arxiv.org/html/2602.11351)
- Behaviour regularisers: (i) information-seeking penalty on consecutive user turns without environment feedback; (ii) over-thinking penalty "(T-T')/T'" for exhausting token budget before completion; max turns T=15 (Function/Turtle), T=12 (Telepathy) — [BAO HTML](https://arxiv.org/html/2602.11351)
- Results Function-Gym Qwen3-4B: BAO Score 0.6923 vs UserRL 0.5256 vs GPT-4o 0.1410; Pass@U-1 0.2692 vs 0.2436; user-rate 0.2148 vs 0.3758. Turtle-Gym Pass@U-1 0.1063 vs UserRL 0.0417 (GPT-4o 0.1719) — [BAO HTML](https://arxiv.org/html/2602.11351)
- Reward hacking observed in the UserRL baseline on Turtle-Gym: "long answers to confuse the judge model"; BAO reward-translation rate 0.575 vs UserRL 0.154 — [BAO HTML](https://arxiv.org/html/2602.11351)
- Baseline pathology: UserRL agent "relies heavily on user engagement to verify answer correctness rather than autonomously exploring the environment" — [BAO HTML](https://arxiv.org/html/2602.11351)

#### MUA-RL (CAS + PKU, 2025-08, arXiv 2508.18669)
- "for the first time in the field of agentic tool use, integrates LLM-simulated users into the reinforcement learning loop" — [arXiv 2508.18669](https://www.arxiv.org/abs/2508.18669)
- Base: Qwen3-8B / 14B / 32B non-thinking — [MUA-RL HTML](https://arxiv.org/html/2508.18669)
- User simulator: "GPT-4o-2024-11-20" during RL; "GPT-4.1 as the user simulator" at tau1/tau2 evaluation (train/eval simulator mismatch) — [MUA-RL HTML](https://arxiv.org/html/2508.18669)
- Cold start: "approximately two thousand trajectories" over "9 scenarios, including 5 synthetic scenarios and 4 real-world MCP server scenarios", generated by three LLMs (agent / user / tool-simulator), filtered by "dual-verification, which combines human expert annotation with DeepSeek-R1 evaluation" — [MUA-RL HTML](https://arxiv.org/html/2508.18669). The public release is "1,580 annotated multi-turn tool-use trajectories spanning five mock and four MCP tasks" per FACA — [FACA HTML](https://arxiv.org/html/2608.17499)
- RL tasks: "115 retail and 50 airline datasets from TAU1-Bench" (165 tasks) — [MUA-RL HTML](https://arxiv.org/html/2508.18669)
- Algorithm/reward: GRPO; "r=1 only when the agent successfully fulfills the task...and r=0 otherwise"; dialogue-content checks of tau-bench removed; no format penalty; "Upper bound of 30 interaction turns"; 32,768-token sequence cap; group 8, batch 32, 25 epochs, KL beta=0.001, rollout temperature 1.0 — [MUA-RL HTML](https://arxiv.org/html/2508.18669)
- Results tau2 Retail/Airline: Qwen3-8B base 41.0/12.5 -> cold-start 31.4/16.0 -> MUA-RL-8B 49.8/19.0; Qwen3-14B base 43.1/14.8 -> cold-start 53.7/24.0 -> MUA-RL-14B 66.0/38.0; MUA-RL-32B 67.3/45.4/Telecom 28.3; cold-start 32B 58.2/31.1 — [MUA-RL HTML](https://arxiv.org/html/2508.18669)
- Ablation: "MUA-RL-32B w/o cold-start achieves higher scores on TAU2-Bench compared to MUA-RL-32B w/o RL; however, it performs worse on BFCL-V3 Multi Turn. Nevertheless, both variants underperform relative to MUA-RL-32B" — [MUA-RL HTML](https://arxiv.org/html/2508.18669)
- Failure: cold-start SFT alone "degraded performance on TAU Telecom" (and lowered 8B retail 41.0 -> 31.4), attributed to "domain-specific patterns and biases" — [MUA-RL HTML](https://arxiv.org/html/2508.18669)

#### FACA: "The Next User Turn Is More Than Context" (2026-08, arXiv 2608.17499)
- Base: "Qwen3-8B and Qwen3-14B" initialised by "SFT on the public MUA-RL release" (1,580 trajectories); RL on "Only the Airline and Retail training splits of tau-bench" — [FACA HTML](https://arxiv.org/html/2608.17499)
- User simulator: "frozen DeepSeek-V4-Flash user policy" that emits JSON with a private "strategy" field in {be_vague, reveal_piece, ask_clarification, change_mind, challenge_solution, confirm, close} alongside the visible utterance — [FACA HTML](https://arxiv.org/html/2608.17499)
- Reward: strategy -> polarity {+1: confirm, close, reveal_piece; 0: be_vague, invalid; -1: ask_clarification, challenge_solution, change_mind}; locally normalised "reaction advantage" A^p added to terminal outcome advantage: A = A^o + lambda A^p, lambda capped at 0.5 "so that reaction credit remains optimization-relevant while A^o stays dominant"; clipping applied per user-to-user segment — [FACA HTML](https://arxiv.org/html/2608.17499)
- Results (9 tau-family domains, 3 runs): 8B Interactive-GRPO 34.7% -> FACA 40.6% (+5.91); 14B 42.5% -> 52.7% (+10.22); tau2 Telecom 30.7 -> 41.2 (8B), 26.3 -> 83.6 (14B); zero-shot transfer to Pare-Bench and Co-Gym — [FACA HTML](https://arxiv.org/html/2608.17499); [arXiv abstract](https://arxiv.org/abs/2608.17499)
- Ablations (8B): shifted reactions 33.92%, randomised polarity 32.66% (both below the 34.70% baseline), sign reversal lambda=-0.5 -> 15.08% — [FACA HTML](https://arxiv.org/html/2608.17499)

#### APIGen-MT / xLAM-2 (Salesforce, 2025-04, arXiv 2504.03601; NeurIPS 2025 D&B) — SFT-only but defines the simulated-human data recipe
- Two phases: blueprint (q, a_gt, o_gt) validated by "Format & Execution Checker" and "a committee of multiple LLM reviewers" with "majority voting"; reflection raises blueprint pass rate "2.5x ... to attain 70%" (from 28%) — [APIGen-MT HTML](https://arxiv.org/html/2504.03601)
- Trajectory phase: GPT-4o function-calling agent vs LLM human; verified by "comparing the final environment state to a_gt and the agent's final responses to o_gt"; 67% of simulations pass — [APIGen-MT HTML](https://arxiv.org/html/2504.03601)
- Human-simulator stabilisation: best-of-N (N=4) with self-critique so the simulated human does not "drift from the original instruction or be unduly influenced by the agent's responses" — [APIGen-MT HTML](https://arxiv.org/html/2504.03601)
- Data/training: "We open-source 5K synthetic data trajectories" (APIGen-MT-5k); "filtered Behavioral Cloning" full fine-tune; base models Llama 3.1/3.2 (8B, 70B) and Qwen2.5 (1B, 3B, 32B) — [arXiv 2504.03601v4](https://arxiv.org/abs/2504.03601v4); [HF model card](https://huggingface.co/Salesforce/Llama-xLAM-2-8b-fc-r)
- tau-bench pass^1: xLAM-2-70b Retail 67.1 / Airline 45.2 / overall 56.2; GPT-4o 62.8 / 43.0 / 52.9; xLAM-2-8b 58.2 / 35.2 / 46.7; Claude 3.5 Sonnet overall 60.1 — [APIGen-MT HTML](https://arxiv.org/html/2504.03601); [HF model card](https://huggingface.co/Salesforce/Llama-xLAM-2-8b-fc-r)

#### SWEET-RL / ColBench (Meta FAIR + Berkeley, 2025-03, arXiv 2503.15478)
- Base: Llama-3.1-8B-Instruct; human simulator Llama-3.1-70B-Instruct (backend) and Qwen2-VL-72B (frontend), which sees the hidden reference solution: "based on the reference code visible only to the human simulator" but "will not write code" — [SWEET-RL HTML](https://arxiv.org/html/2503.15478)
- "interactions are limited to 10 back-and-forth rounds"; 10k train tasks per domain; 15k (backend) / 6k (frontend) offline trajectories — [SWEET-RL HTML](https://arxiv.org/html/2503.15478)
- Algorithm: step-level critic trained with Bradley-Terry objective using training-time info (reference solution); advantage parameterised via mean log-prob difference from a reference model; policy updated with DPO on critic-ranked candidates (offline, so GRPO/PPO "do not apply") — [SWEET-RL HTML](https://arxiv.org/html/2503.15478)
- Results: backend success 40.4% vs multi-turn DPO 34.4%; frontend win-rate 48.2% vs 42.8%; "6% absolute improvement" overall; 8B "match or exceed ... GPT4-o" — [arXiv abstract](https://arxiv.org/abs/2503.15478)
- Failure of judge rewards: "a fixed LLM-as-a-Judge can easily get distracted by the length and format of the response without actually attending to its utility for task success" — [SWEET-RL HTML](https://arxiv.org/html/2503.15478)

#### CollabLLM (Stanford/Microsoft, 2025-02, arXiv 2502.00640; ICML 2025 oral)
- Base: Llama-3.1-8B-Instruct, LoRA rank 32; user simulator GPT-4o-mini with an "implicit goal", prompted to "Provide vague or incomplete demands in the early stages" and "Occasionally Make Mistakes" — [CollabLLM HTML](https://arxiv.org/html/2502.00640v3)
- Multiturn-aware Reward = expected future reward from forward-sampled conversations, window w=2; reward = extrinsic task similarity + intrinsic "-min[lambda*TokenCount, 1] + R_LLM" (Claude-3.5-Sonnet judge, lambda 5e-4 code/math, 1e-4 docs) — [CollabLLM HTML](https://arxiv.org/html/2502.00640v3)
- Training: offline SFT / DPO on "500-sample synthetic datasets (2,300+ turns each)", then online PPO / online DPO; +18.5% task, +46.3% interactivity, 201-person study +17.6% satisfaction, -10.4% time — [CollabLLM HTML](https://arxiv.org/html/2502.00640v3)

#### IntentRL (Alibaba Tongyi, 2026-02, arXiv 2602.03468) — clarification agent for deep research
- Base: Qwen2.5-7B clarification agent; Qwen2.5-72B-Instruct summariser; simulator LLM gemini-3-pro-preview behind rule filters — [IntentRL HTML](https://arxiv.org/html/2602.03468)
- Simulator: "Hybrid rule-based and LLM-judge design": all-mpnet-base-v2 embeddings, repetition threshold 0.92, relevance threshold 0.8; "Only if the question passes these checks does an LLM generate a user response conditioned on the intent list" — [IntentRL HTML](https://arxiv.org/html/2602.03468)
- Two-stage GRPO: Stage I offline on 371 intent trajectories / 2,347 turns (from 50 seeds); Stage II online with simulator and "partial teacher forcing"; T=9 max clarification turns; rewards: cosine content score, format 1.0/0.5/0, penalties for repetition (gamma=2), deviation, insignificance — [IntentRL HTML](https://arxiv.org/html/2602.03468)
- Results: intent precision 36.44% vs CollabLLM 18.00%; report score 43.65 vs 39.39 no-clarification; removing Stage II yields "repeated behaviors, irrelevant questions, and stubborn reactions to user feedback"; SFT baseline "memorization rather than adaptive clarification" — [IntentRL HTML](https://arxiv.org/html/2602.03468)

#### AskBench / rubric-guided RLVR (2026-02, arXiv 2602.11199)
- Qwen2.5-7B-Instruct policy; frozen Qwen3-30B-A3B judge doubles as user: "Provide a concise, natural-sounding response that ONLY answers the assistant's immediate question" and "Do NOT volunteer extra information" — [AskBench HTML](https://arxiv.org/html/2602.11199v1)
- GRPO rewards: -2.0 premature final answer, +1.0 full rubric coverage / 0.8 partial, -0.8 unfocused question, terminal +1/-1; 100 rejection-sampled items per domain; accuracy 0.332 -> 0.615; SFT baseline hurts OOD (HealthBench 0.526 -> 0.247); redundant-question rate 0.463 in one variant — [AskBench HTML](https://arxiv.org/html/2602.11199v1)

#### Steerable clarification via collaborative self-play (Google DeepMind, arXiv 2512.04068, v1 2025-12, revised 2026-09)
- Gemma 2 9B main, also Gemma 2 2B and Qwen3 4B; user simulated by the same model given the true interpretation "instructed to communicate without revealing it"; ReST (3 epochs); reward "acc(a,a*) - alpha*n_clar - beta*|answer tokens|"; 1,776 AmbigQA + 3,744 Pacific train tasks — [arXiv 2512.04068](https://arxiv.org/html/2512.04068)

#### Calibrated Interactive RL with aligned simulator (2026-05, arXiv 2605.26403)
- Gemma-3-4B-IT policy; Qwen2.5-7B-Instruct simulator SFT-calibrated on oracle-collected human-like dialogues (1,860 MATH-Chat, 16,028 MediumDocEdit-Chat); GRPO with sparse final-turn reward — [Calibrated RL HTML](https://arxiv.org/html/2605.26403)
- Theory: performance gap compounds O(H^2 eps) in policy shift and O(H^2 delta) in simulator deviation — [Calibrated RL HTML](https://arxiv.org/html/2605.26403)
- Results: MATH acc base 82.3 / static-context 85.0 / naive interactive 89.3 / calibrated 91.5; DocEdit BLEU 32.2 / 33.8 / 26.1 / 34.6 (naive interactive *below* base) — [Calibrated RL HTML](https://arxiv.org/html/2605.26403)

#### Other 2026 simulator-in-loop training works (abstract-level only)
- WMG-RL (2026-09, arXiv 2609.01067): "a frozen user simulator provides reward supervision before real user exposure" to train "a compact 1.7B student policy" for recommendation; details not stated — [arXiv 2609.01067](https://arxiv.org/abs/2609.01067v1)
- EnvACE (2026-08, arXiv 2608.06197): policy "plays the role of the environment to produce the response induced by that action" (world rehearsal) and transfers to tau2-Bench; not a user-simulator method — [arXiv 2608.06197](https://arxiv.org/pdf/2608.06197)
- Early Experience (Meta + OSU, 2025-10, arXiv 2510.08558): Llama-3.2-3B / Qwen2.5-7B / Llama-3.1-8B on 8 envs incl. tau-bench; Tau-Bench (Llama-3.1-8B) IL 35.9 -> IWM 40.8 / SR 41.7; WebShop IL 47.3 -> 58.6 / 58.2; "1/8 of the demonstrations already surpasses imitation learning trained on the full dataset" (WebShop); WebShop Llama-3.2-3B IL->GRPO ~82% vs SR->GRPO ~92%; ungrounded STaR-style long CoT "-47.3" on WebShop — [Early Experience HTML](https://arxiv.org/html/2510.08558)

### Inferences
- For a 1.7B-4B agent, the closest templates are BAO (Qwen3-1.7B/4B, Qwen3-8B simulator, SFT warm-start, GRPO with turn-level advantages, turn-efficiency regulariser) and UserRL (Qwen3-4B, Qwen3-32B simulator, 5K distilled SFT, GRPO Equalized/R2G); both run a frozen open-weight simulator of 8B-32B, so a GPT-class simulator is not required.
- The de-facto reward is binary on final environment state (MUA-RL, UserRL TauGym, APIGen-MT verification), which maps directly onto a DB-state check; the papers that add user-side signals (FACA reaction advantage, CollabLLM MR, BAO engagement penalty) keep the outcome term dominant.
- Typical caps: 10-30 agent-user turns, 16-32K tokens; the SQL-agent setting (DB result rows in context) is closer to MUA-RL's 32K than to 128K deep-research settings.

### Gaps
- UserRL's exact "RL without SFT" numbers (Fig. 2 left) were not extracted; only raw baselines (0.2929 / 0.3128) and the plateau statement are available.
- APIGen-MT per-size (1B/3B/32B) tau-bench numbers were not retrievable from the HTML or model card.
- No paper reports a trained 1.7B-4B agent on tau2-bench proper; the smallest tau-trained models found are Qwen3-8B (MUA-RL, FACA).
- MUA-RL does not publish its training-time user prompt; whether it reuses the tau-bench user prompt is not stated.

## KQ2. RL algorithm and credit assignment for multi-turn agents (general agent RL, no user simulator)

### Takeaway
Critic-free group methods dominate; the 2025-26 refinements are (a) step/turn-level advantages without a critic (GiGPO anchor-state groups, Flow-GRPO broadcast, FACA local normalisation, LightningRL per-call credit), (b) stabilisers against collapse (StarPO-S trajectory filtering + clip-higher + no KL, SimpleTIR void-turn filtering, Tongyi negative-sample filtering), and (c) horizon curricula (AgentGym-RL ScalingInter).

### Cited Findings
- GiGPO (2025-05, arXiv 2505.10978; verl-agent): Qwen2.5-1.5B/3B/7B-Instruct; A(a_t) = A^E(tau) + omega*A^S(a_t) with omega=1; step groups formed by hashing repeated environment states ("anchor states") across the trajectory group, no extra rollouts, "< 0.002% of the total per-iteration training time"; rewards 10/0 with -0.1 invalid-action penalty (ALFWorld/WebShop), 1/0 with -0.01 (Search QA); group 8 x 16 groups = 128 envs; ALFWorld 50 steps, WebShop 15, search 4 turns; history window 2 for ALFWorld/WebShop; ALFWorld 1.5B 86.1% vs GRPO 72.8%, WebShop 83.5 vs 75.8 — [GiGPO HTML](https://arxiv.org/html/2505.10978); [verl-agent](https://github.com/langfengQ/verl-agent)
- RAGEN / StarPO (2025-04, arXiv 2504.20073): Qwen2.5-0.5B (symbolic) and 3B (WebShop); "Echo Trap": "the model repeatedly reuses memorized reasoning paths when trained on self-generated trajectories, leading to a collapse in diversity", preceded by reward-std collapse, entropy swings, gradient spikes; StarPO-S keeps "the top p% highly-uncertain prompts" (25% default), removes KL, clip-higher eps_high=0.28 / eps_low=0.2; fewer responses per prompt (4) with more prompts generalises better; 5-6 actions per turn best; fresher rollouts (Online-1) better; "without fine-grained, reasoning-aware reward signals, agent reasoning hardly emerge" and models "produce hallucinated reasoning" with success-only reward — [RAGEN HTML](https://arxiv.org/html/2504.20073v2)
- AgentGym-RL / ScalingInter-RL (2025-09, arXiv 2509.08755; ICLR 2026): trains "from scratch -- without relying on supervised fine-tuning (SFT)"; "restricting the number of interactions, and gradually shifts towards exploration with larger horizons"; Qwen2.5-3B/7B; 7B "average improvement of 33.65 points"; gradual scaling makes the agent "less prone to collapse under long horizons" — [arXiv 2509.08755](https://arxiv.org/abs/2509.08755); [moonlight review](https://www.themoonlight.io/en/review/agentgym-rl-training-llm-agents-for-long-horizon-decision-making-through-multi-turn-reinforcement-learning)
- SPA-RL (2025-05, arXiv 2505.20732): trains a progress estimator whose stepwise contributions sum to task completion; combines with a grounding signal; +2.5% success, +1.9% grounding on WebShop/ALFWorld/VirtualHome — [arXiv 2505.20732](https://www.arxiv.org/abs/2505.20732)
- RLVMR (2025-07, arXiv 2507.22844; ICLR 2026): rule-verifiable rewards for explicitly tagged planning/exploration/reflection steps plus outcome; 7B reaches 83.6% on hardest unseen ALFWorld split — [arXiv 2507.22844](https://arxiv.org/abs/2507.22844v1)
- Agent Lightning / LightningRL (Microsoft, 2025-08, arXiv 2508.03680): decouples agent execution from training; "credit assignment module determines how much each LLM request contributed" then applies GRPO/PPO per call; demos include text-to-SQL, RAG, math tool-use — [arXiv 2508.03680](https://arxiv.org/abs/2508.03680v1)
- AgentFlow / Flow-GRPO (2025-10, arXiv 2510.05592; ICLR 2026 oral): "broadcasting a single, verifiable trajectory-level outcome to every turn", group-normalised advantages, trains only the planner (Qwen2.5-7B-Instruct) in a 4-module system; +14.9% search, +14.0% agentic — [arXiv 2510.05592](https://arxiv.org/abs/2510.05592)
- SimpleTIR (2025-09, arXiv 2509.02479): instability "caused by distributional drift from external tool feedback, leading to the generation of low-probability tokens, which compounds over successive turns"; fix: filter trajectories with "void turns (turns that yield neither a code block nor a final answer)"; Qwen2.5-7B base AIME24 22.1 -> 50.5 — [arXiv 2509.02479](https://arxiv.org/pdf/2509.02479)
- MEM1 (2025-06, arXiv 2506.15841): PPO-style RL with masked trajectories so the agent keeps a "compact shared internal state" of constant size; MEM1-7B "3.5x" performance and "3.7x" less memory vs Qwen2.5-14B-Instruct on 16-objective QA — [arXiv 2506.15841](https://arxiv.org/abs/2506.15841v1)
- ToolRL (2025-04, arXiv 2504.13958): R_final = R_format{0,1} + R_correct[-3,3] (tool name / param name / param value matched by bipartite matching); 4K RL examples (2K ToolACE + 1K Hammer + 1K xLAM); "Adding a length reward does not consistently improve task performance, and in smaller-scale models, it can even cause substantial degradation"; reward scale should shift gradually from format to correctness — [ToolRL HTML](https://arxiv.org/html/2504.13958v1)
- Tongyi DeepResearch (2025-10, arXiv 2510.24701): "tailored adaptation of GRPO" with token-level loss, clip-higher, leave-one-out advantage, strict on-policy; "reward is a pure 0 or 1 signal of answer correctness", "We do not include a format reward ... because the preceding cold start stage ensures the model is already familiar with the required output format"; drops negatives that "exceed a length limit"; 128 tool calls / 128K context; dynamic filtering of always-fail / always-succeed problems; "Directly optimizing on an unfiltered set of negative rollouts significantly degrade training stability and can lead to policy collapse" — [Tongyi HTML](https://arxiv.org/html/2510.24701)
- Kimi K2 (Moonshot, 2025-07): synthesis over "3000+ real MCP tools" and "over 20,000 synthetic tools", "LLM-generated user personas with distinct communication styles", a stateful tool simulator, LLM-judge rubric filtering, real sandboxes for code; RL with verifiable rewards + self-critique rubric, per-task token budget, PTX loss, temperature decay; tau2 retail 70.6 / airline 56.5 / telecom 65.8 (Avg@4) — [Kimi K2 report](https://arxiv.org/html/2507.20534)

### Inferences
- For a DB agent whose environment state is deterministic and hashable (schema + table contents), GiGPO's anchor-state grouping is directly applicable: identical DB states reached by different rollouts form a step-level group for free.
- Filtering degenerate rollouts (void turns, over-length, all-same-reward groups) is a recurring, cheap stabiliser reported independently by SimpleTIR, StarPO-S and Tongyi; this is the first thing to add before any reward shaping.
- Format rewards are optional once SFT establishes the protocol (Tongyi); ToolRL shows length rewards hurt small models.

### Gaps
- No work was found that applies GiGPO-style anchor grouping in a user-simulator setting (states include stochastic user text).
- ScalingInter-RL's exact horizon schedule and per-environment numbers were not retrievable (HTML 404; abstract only).

## KQ3. How the simulated user is kept from leaking the answer or playing along with protocol violations

### Takeaway
Prevention is almost entirely prompt-level ("reveal only what is asked", "do not give solutions"), sometimes plus mechanical gates (lexical leak filters, embedding-based redundancy checks, best-of-N self-critique, structured strategy fields). 2026 fidelity audits show prompted simulators still leak early and are over-cooperative: 24.4% of successful tau-family episodes contain a user-spec violation, dominated by premature disclosure.

### Cited Findings
- tau-bench user prompt rules: "Do not give away all the instruction at once. Only provide the information that is necessary for the current step" and "Do not repeat the exact instruction in the conversation. Instead, use your own words" — [tau-bench](https://arxiv.org/pdf/2406.12045)
- UserRL IntentionGym: "Do NOT provide what missing details need to be clarified or give any examples. Do NOT provide concrete help or solutions." — [UserRL HTML v1](https://arxiv.org/html/2509.19736v1)
- AskBench simulator: "ONLY answers the assistant's immediate question", "Do NOT volunteer extra information" — [AskBench HTML](https://arxiv.org/html/2602.11199v1)
- SWEET-RL: simulator sees reference code but "will not write code", only "a brief explanation in natural language to each clarification question" — [SWEET-RL HTML](https://arxiv.org/html/2503.15478)
- Self-play clarification: user given the true interpretation and "instructed to communicate without revealing it" — [arXiv 2512.04068](https://arxiv.org/html/2512.04068)
- IntentRL: mechanical gate before the LLM answers — embedding similarity to history > 0.92 flags redundancy, similarity to intent set < 0.8 flags irrelevance; LLM response "conditioned on the intent list" only after passing — [IntentRL HTML](https://arxiv.org/html/2602.03468)
- APIGen-MT: best-of-N=4 with self-critique so the human does not "drift from the original instruction or be unduly influenced by the agent's responses"; trajectories accepted only when final state and final response match ground truth — [APIGen-MT HTML](https://arxiv.org/html/2504.03601)
- FACA: simulator emits a hidden "strategy" label (be_vague / reveal_piece / ...) alongside the utterance, making the simulator's disclosure behaviour explicit and auditable — [FACA HTML](https://arxiv.org/html/2608.17499)
- CUE (2026-10, arXiv 2610.02460): commands/examples "rejected if they contain task-specific content detected by a fixed lexical filter, including terms associated with credentials, identifiers, products, policies, addresses, receipts, or deliveries"; failure taxonomy includes "User Data Leakage", "Unnecessary Escalation", "Ignoring or Not Gathering Available Information" (16 categories); base simulators Llama 3.1 8B, GPT 5.4 Mini, Gemini 3.5 Flash Lite; evaluation-only — [CUE HTML](https://arxiv.org/html/2610.02460v1)
- UserProxyBench (2026-09, arXiv 2609.38043): varying only the user proxy over 375 enterprise tasks "changes mean task reward by 15.2 points"; "24.4% of successful episodes contain a user-specification violation"; "The dominant failure is premature disclosure: users provide information before it is requested" — [arXiv 2609.38043](https://arxiv.org/abs/2609.38043)
- Sim2Real gap (COLM 2026, arXiv 2603.11245, 451 participants / 165 tasks / 31 simulators): human-baseline agent success 63.6% vs up to 77.8% with simulators ("easy mode"); best USI DeepSeek-V3.1 76.0 vs human 92.7; "UserLM-8b includes nearly twice as many identifier-like tokens per turn (4.8 vs. 2.6 for humans)"; GPT-4o 49.0% polite turns vs 15.3% humans; GPT-4o pivots strategy 19.1% vs 8.4%, "quietly accepting errors rather than pushing back"; persona prompting dropped USI 70.9 -> 64.6; "70.6% of reward=0 interactions are actually judged as successful by human users, while 33% of reward=1 interactions are judged as unsuccessful" — [Sim2Real HTML](https://arxiv.org/html/2603.11245)
- Non-collaborative simulators (2025-09, arXiv 2509.23124): four behaviours "requesting unavailable services, digressing into tangential conversations, expressing impatience, and providing incomplete utterances" cause "significant performance degradation" on MultiWOZ and tau-bench — [arXiv 2509.23124](https://arxiv.org/abs/2509.23124)
- Calibrated Interactive RL: "uncalibrated simulators frequently exhibit sycophancy...which RL agents rapidly exploit by generating confident but incorrect responses"; fix is SFT-aligning the simulator on human-like dialogues — [Calibrated RL HTML](https://arxiv.org/html/2605.26403)
- Survey: "A Survey on LLM-based Conversational User Simulation" (EACL 2026, arXiv 2604.24977) taxonomises simulators and RL/DPO-trained simulators — [survey](https://www.opentrain.ai/papers/a-survey-on-llm-based-conversational-user-simulation--arxiv-2604.24977/)

### Inferences
- None of the training papers relies on the simulator to detect a fabricated tool result; protection against the agent "writing fake results" comes from the reward being computed on the real environment state (MUA-RL, APIGen-MT, UserRL TauGym), not from the user. For a SQL agent this argues for a DB-diff/gold-query reward and a programmatic protocol checker (did every reported result come from an executed query), rather than any user-judged reward.
- The cheapest leak controls that transfer: (1) give the simulator only the fields it may disclose plus "answer only what is asked"; (2) a lexical/regex gate on simulator output for identifiers the agent has not yet asked about (CUE-style); (3) log a hidden disclosure label per user turn (FACA-style) to audit leakage rates during training.
- Since the simulator is over-cooperative, evaluation with a different, stricter simulator (BAO swaps Qwen3-8B -> GPT-4o at test; MUA-RL trains on GPT-4o, evaluates with GPT-4.1) is the standard guard against simulator over-fitting.

### Gaps
- No paper quantifies how often a *trained* agent induces leakage from the simulator (leak rate before vs after RL); UserProxyBench measures leakage with frontier agents only.
- No paper found that trains an agent against a non-collaborative simulator and reports gains.

## KQ4. SFT : RL ratio; does SFT hurt exploration; does RL-only from a small instruct model collapse?

### Takeaway
Reported SFT sets are tiny relative to what one might expect (1.5K-5K trajectories) and the RL task pools are smaller still (165-2,686 tasks), i.e. SFT examples : RL tasks of roughly 2:1 to 10:1. User-simulator papers (UserRL, BAO, MUA-RL, FACA, IntentRL) all keep an SFT cold start and report RL-without-SFT plateauing; single-turn tool-calling (ToolRL) and some embodied/agent setups (AgentGym-RL) report RL-only is better. 2026 work shows *over*-training SFT (deep epochs) collapses entropy and lowers the RL ceiling on 3B models.

### Cited Findings
- UserRL: 5,000 SFT trajectories vs 2,686 RL tasks; "SFT cold start is critical for unlocking initial interaction ability and enabling sustained RL improvements"; no-SFT runs "plateau early" — [arXiv 2509.19736](https://arxiv.org/abs/2509.19736); [UserRL HTML](https://arxiv.org/html/2509.19736)
- MUA-RL: ~2,000 (public 1,580) SFT trajectories vs 165 RL tasks; RL w/o cold-start beats SFT-only on tau2 but is worse on BFCL multi-turn, and both trail SFT+RL — [MUA-RL HTML](https://arxiv.org/html/2508.18669); [FACA HTML](https://arxiv.org/html/2608.17499)
- FACA: 1,580 SFT trajectories vs 165 RL tasks (Airline 50 + Retail 115) — [FACA HTML](https://arxiv.org/html/2608.17499)
- IntentRL: 371 offline trajectories / 2,347 turns from 50 seeds; SFT baseline "memorization rather than adaptive clarification" — [IntentRL HTML](https://arxiv.org/html/2602.03468)
- CollabLLM: 500-sample offline sets before online PPO/DPO — [CollabLLM HTML](https://arxiv.org/html/2502.00640v3)
- ToolRL (single-turn tool calls): "GRPO Cold Start" = RL directly from the instruct model; BFCL-V3 Qwen2.5-1.5B 46.20% (RL-only) vs 40.21% (SFT-400) vs 19.41% raw; 3B 52.98 / 34.08 / 33.04; 7B 58.38 / 34.08 / 41.97; "SFT initialization leads to memorization and overfitting, which reduces the impact of GRPO's effectiveness" — [ToolRL HTML](https://arxiv.org/html/2504.13958v1)
- AgentGym-RL: RL "from scratch -- without relying on supervised fine-tuning (SFT)" works when the horizon is grown gradually; without it agents are "prone to collapse under long horizons" — [arXiv 2509.08755](https://arxiv.org/abs/2509.08755)
- AskBench: SFT baseline hurts OOD (HealthBench 0.526 -> 0.247) while GRPO improves — [AskBench HTML](https://arxiv.org/html/2602.11199v1)
- Demystifying RL in Agentic Reasoning (2025-10, arXiv 2510.11701): 3K real end-to-end SFT trajectories (Qwen3-Coder-30B-A3B teacher) vs 30K RL problems (~1:10); "Replacing stitched synthetic trajectories with real end-to-end tool-use trajectories yields a far stronger SFT initialization"; synthetic SFT "yields below 10% on average@32"; "Diverse RL datasets sustain higher policy entropy"; clip-higher eps_high 0.28 -> 0.315; DemyAgent-4B AIME24 72.6 / AIME25 70.0 / GPQA 58.5 / LCB-v6 26.8 — [Demystifying HTML](https://arxiv.org/html/2510.11701)
- Tongyi DeepResearch: SFT via rejection sampling of strong open-source model trajectories, "Over 20% of the samples exceed 32k tokens and involve more than 10 tool invocations"; exact count not stated — [Tongyi HTML](https://arxiv.org/html/2510.24701)
- SFT over-training (2026-06, arXiv 2606.18487): Qwen2.5-Coder-3B-Base, 5,000 KodCode problems, 1.0-5.8 epochs; "peak GRPO pass@10 falls from 0.806 to 0.481" as SFT depth rises while pre-RL pass@1 rises; pre-RL entropy threshold 0.18 nats; pick the 1.9-epoch checkpoint (+0.090 pass@10) — [arXiv 2606.18487](https://arxiv.org/html/2606.18487v1)
- "When RL Fails after SFT" (2026-06, arXiv 2606.09932): "checkpoints with excessive SFT often show limited improvement during RL"; cause "over-confident token distributions and ... sharp parameter landscapes"; fix "base-anchored model fusion ... with targeted neuron reset" — [arXiv 2606.09932](https://arxiv.org/abs/2606.09932)
- MUA-RL cold-start regression: SFT lowered Qwen3-8B tau2 Retail 41.0 -> 31.4 before RL recovered it to 49.8 — [MUA-RL HTML](https://arxiv.org/html/2508.18669)
- Early Experience: self-generated rollout data "up to an order of magnitude larger than expert data"; on WebShop "1/8 of the demonstrations already surpasses imitation learning trained on the full dataset" — [Early Experience HTML](https://arxiv.org/html/2510.08558)

### Inferences
- The split in the literature is by interaction type: where the protocol (when to ask, when to act, when to stop) is new to the base model (user-facing multi-turn), every paper keeps a small SFT; where the base model already emits the right format (single-turn tool calls), RL-only wins. A 1.7B-4B SQL agent that must learn a user-interaction protocol falls in the first group.
- The consistent recipe is "light" SFT: 1.5K-5K trajectories, 1-3 epochs, selected for protocol correctness, followed by RL on a few hundred to a few thousand tasks with KL removed and clip-higher. Deep SFT (>2 epochs on the same data) is the documented way to kill the RL ceiling on 3B models.
- Expect SFT alone to regress some domains (MUA-RL Telecom/8B Retail); judge the cold start by the post-RL curve, not by SFT-only accuracy.

### Gaps
- No paper reports an explicit RL-only collapse for a Qwen3-1.7B/4B agent in a user-simulator loop; UserRL reports plateau (not collapse) and gives curves, not a table.
- No controlled study varies SFT size (e.g., 500 vs 5K) in a user-simulator RL setting.

## KQ5. Self-taught (same-model rejection sampling) vs distillation from a larger model for the cold start

### Takeaway
Direct head-to-head evidence inside user-simulator RL is absent. Adjacent evidence: Early Experience shows self-generated, environment-grounded data beats pure expert imitation and raises the post-RL ceiling; Demystifying-RL shows distilled *real* trajectories from a strong teacher beat synthetic stitched data; ToolRL/AskBench show SFT on teacher data can over-fit relative to RL-only; most tau-style papers simply distil from GPT-4o.

### Cited Findings
- Early Experience: self-generated (same policy) alternative actions + grounded reflection beat IL on all 8 environments; Tau-Bench IL 35.9 -> SR 41.7; post-RL ceiling higher (WebShop 3B ~82% IL->GRPO vs ~92% SR->GRPO) — [Early Experience HTML](https://arxiv.org/html/2510.08558)
- Demystifying RL: 3K teacher trajectories (Qwen3-Coder-30B-A3B via Qwen-Agent) "deliver a clear improvement" over stitched synthetic SFT ("below 10% on average@32") — [Demystifying HTML](https://arxiv.org/html/2510.11701)
- UserRL distils GPT-4o agent + GPT-4o user (5K) — [UserRL HTML](https://arxiv.org/html/2509.19736); BAO distils GPT-4o with behaviour prompts — [BAO HTML](https://arxiv.org/html/2602.11351); MUA-RL filters LLM-generated trajectories with human + DeepSeek-R1 review — [MUA-RL HTML](https://arxiv.org/html/2508.18669)
- Steerable clarification uses ReST (same-model rejection sampling of best rollouts) with no external teacher and reaches reward 6.63 vs -34.49 prompted on AmbigQA — [arXiv 2512.04068](https://arxiv.org/html/2512.04068)
- ToolRL: SFT on teacher-format data then GRPO under-performs GRPO-only on all four small models — [ToolRL HTML](https://arxiv.org/html/2504.13958v1)
- "Smaller Models, Better Rejects" (2026-09, arXiv 2609.38987): for preference distillation, "smaller frozen models generate rejects with less inference compute yet train stronger students than self-generated rejects" (code/math, students 7B-72B) — [arXiv 2609.38987](https://arxiv.org/abs/2609.38987)
- "Finetuning with Sampling" (2026-10, arXiv 2610.02140): MCMC "progressively transforms off-policy traces to be more on-policy", letting SFT rival on-policy methods, "generalizing better and forgetting less" (numbers not stated) — [arXiv 2610.02140](https://arxiv.org/abs/2610.02140)

### Inferences
- The reconciling view from these sources: what matters is (a) environment-grounded, end-to-end trajectories (not stitched), and (b) low off-policy-ness. Distillation supplies (a); self-generation supplies (b). A practical compromise used implicitly by APIGen-MT/MUA-RL is teacher-generated trajectories filtered by environment-state verification, then kept short in epochs.

### Gaps
- No paper in scope ran "same-model RFT cold start vs GPT-4o distillation cold start" with the same RL afterwards; this remains an open experiment.

## KQ6. Failure modes and reward hacking observed

### Takeaway
Documented hacks are: gaming LLM judges with long answers (BAO on UserRL, SWEET-RL on judges), exploiting sycophantic simulators with confident wrong answers (Calibrated RL), over-asking the user instead of exploring the environment (BAO, IntentRL, AskBench), echo-trap/entropy collapse (RAGEN, SimpleTIR), hallucinated reasoning under success-only rewards (RAGEN), and SFT-induced domain regression (MUA-RL). Agent-side fabrication of tool results is not reported in these papers because rewards are computed on real state.

### Cited Findings
- Judge gaming: UserRL agent on Turtle-Gym produced "long answers to confuse the judge model"; BAO reward-translation rate 0.575 vs 0.154 — [BAO HTML](https://arxiv.org/html/2602.11351); "a fixed LLM-as-a-Judge can easily get distracted by the length and format of the response" — [SWEET-RL HTML](https://arxiv.org/html/2503.15478)
- Simulator sycophancy exploited: "RL agents rapidly exploit by generating confident but incorrect responses"; naive interactive RL dropped DocEdit BLEU 32.2 -> 26.1 — [Calibrated RL HTML](https://arxiv.org/html/2605.26403)
- Over-reliance on user: "agents repeatedly request user interactions without information gain from the environment"; "excessive thinking ... premature exhaustion of the token budget" — [BAO HTML](https://arxiv.org/html/2602.11351); redundant-question rate 0.463 — [AskBench HTML](https://arxiv.org/html/2602.11199v1); "repeated behaviors, irrelevant questions, and stubborn reactions to user feedback" without online stage — [IntentRL HTML](https://arxiv.org/html/2602.03468)
- Collapse dynamics: Echo Trap with reward-std collapse and gradient spikes — [RAGEN HTML](https://arxiv.org/html/2504.20073v2); void turns and "catastrophic gradient norm explosions" — [SimpleTIR](https://arxiv.org/pdf/2509.02479); unfiltered negatives "can lead to policy collapse" — [Tongyi HTML](https://arxiv.org/html/2510.24701)
- Hallucinated reasoning: models "produce hallucinated reasoning" when "rewards only reflect task success" — [RAGEN HTML](https://arxiv.org/html/2504.20073v2)
- Length rewards harm small models — [ToolRL HTML](https://arxiv.org/html/2504.13958v1); ungrounded long-CoT SFT "-47.3" on WebShop — [Early Experience HTML](https://arxiv.org/html/2510.08558)
- Simulator-specific over-fitting risk: UserRL and BAO evaluate with a different simulator than training; sim2real "easy mode" inflates success from 63.6% (humans) to 77.8% — [Sim2Real HTML](https://arxiv.org/html/2603.11245)
- Reaction-reward brittleness: at 8B "randomizing reaction polarity removes the Telecom gain" — [arXiv 2608.17499](https://arxiv.org/abs/2608.17499)

### Inferences
- Any user-judged or LLM-judged component should be bounded (FACA caps lambda at 0.5; CollabLLM caps token penalty at 1) and monitored with a hacking-rate metric (BAO's reward-translation rate); the outcome term on real state must stay dominant.
- The two agent-side pathologies most relevant to a user-agent-DB loop — asking the user instead of querying the DB, and ending early — have published counter-measures: a per-turn penalty on consecutive user turns without an environment call (BAO) and a premature-answer penalty (AskBench -2.0).

### Gaps
- No paper in scope reports the specific hack "agent fabricates a tool/DB result and the simulated user accepts it"; the closest is Calibrated-RL's sycophancy finding and the Sim2Real observation that simulators accept errors instead of pushing back.
- Premature-termination rates before/after RL are not reported numerically by any paper found.
