# 带模拟用户的通用 agent 多轮 RL（2025-01 .. 2026-10）

范围：在包含 LLM 用户模拟器和/或工具环境的循环中用 RL 训练的通用（非 text-to-SQL）agent。目标读者：正在训练 1.7B-4B 用户-agent-数据库 text-to-SQL agent 的人。所有数字均引自一手来源；"not stated"（未说明）表示来源（所抓取的摘要/HTML）没有给出。除非另有说明，月份均为 arXiv v1 的月份。

## 关键问题 1. 逐篇方法论：用户模拟器在环的 RL（tau-bench 式、协作式、澄清式）

### 要点
2025-26 年所有把 LLM 用户放进 RL 循环的论文都使用*冻结的*、基于 prompt 的模拟器（GPT-4o / Qwen3-32B / Qwen3-8B / DeepSeek-V4-Flash / Gemini-3-pro），GRPO 系的无 critic 优化，基于最终环境状态的稀疏 0/1 outcome reward（可选再加一个小的逐轮或 "reaction" 项），10-30 轮上限，以及仅约 1.5K-5K 条 trajectory 的 SFT cold start，配合几百个 RL 任务。最强的小模型结果（Qwen3-4B/8B）来自 UserRL、BAO、MUA-RL 和 FACA。

### 引用的发现

#### UserRL（Salesforce + UIUC，2025-09，arXiv 2509.19736）
- 框架："eight distinct gym environments with a standardized interaction interface"（八个具有标准化交互接口的不同 gym 环境），在其中五个上做 RL；"integrates multi-turn RL rollouts with LLM-based user simulation"（将多轮 RL rollout 与基于 LLM 的用户模拟相结合）— [arXiv 2509.19736](https://arxiv.org/abs/2509.19736)
- 基座模型："Qwen3 models of 4B and 8B parameters"（4B 和 8B 参数的 Qwen3 模型），14B/32B 作为对比 — [UserRL HTML](https://arxiv.org/html/2509.19736)
- 用户模拟器：主实验中 "Qwen3-32B as the simulated user model"（Qwen3-32B 作为模拟用户模型）；GPT-4o 作为训练时的替代用户进行了测试；固定（不共同训练）；IntentionGym 为了自然度使用 temperature 0.7，评估调用用 0.0 — [UserRL HTML](https://arxiv.org/html/2509.19736)
- 模拟器约束文本（IntentionGym，图 4）："Do NOT provide what missing details need to be clarified or give any examples. Do NOT provide concrete help or solutions."（不要指出需要澄清哪些缺失细节，也不要给任何例子。不要提供具体帮助或解决方案。）— [UserRL HTML v1](https://arxiv.org/html/2509.19736v1)
- Cold start："1K trajectories sampled from each of the five training gyms"（从五个训练 gym 各采样 1K 条 trajectory），"GPT-4o as both the agent and simulated user"（GPT-4o 同时充当 agent 和模拟用户）-> 5,000 条 SFT trajectory（蒸馏）— [UserRL HTML](https://arxiv.org/html/2509.19736)
- RL 训练任务：TravelGym 925、TurtleGym 423、FunctionGym 460、TauGym 500、PersuadeGym 378（共 2,686）— [UserRL HTML](https://arxiv.org/html/2509.19736)
- 算法：GRPO，"we remove KL regularization and apply temperature 1.0"（我们去掉 KL 正则并使用 temperature 1.0）；"batch of 128, and generate 8 responses per query, training for 15 epochs"（batch 为 128，每个 query 生成 8 个回复，训练 15 个 epoch）；"max interaction turns to 16 without step penalty"（最大交互轮数 16，无步数惩罚）— [UserRL HTML](https://arxiv.org/html/2509.19736)；[UserRL HTML v1](https://arxiv.org/html/2509.19736v1)
- Reward shaping 变体：turn 级的 Naive / Equalized (r_t = c) / R2G（reward-to-go，带折扣）/ EM（指数映射）；trajectory 级的 Sum vs R2G。"Equalized/R2G setting consistently achieves the best performance"（Equalized/R2G 设置始终取得最佳表现）；naive 的 turn shaping "quickly leads to training collapse"（很快导致训练崩溃）— [UserRL HTML](https://arxiv.org/html/2509.19736)
- 结果（8 个 gym 平均）：Qwen3-8B Equalized/R2G 0.5652；Qwen3-4B Equalized/R2G 0.5269；原始 Qwen3-32B 0.3128；原始 Qwen3-4B 0.2929 — [UserRL HTML](https://arxiv.org/html/2509.19736)
- SFT 发现："models with SFT cold start not only begin from a higher baseline but also continue to improve, whereas models trained without SFT plateau early"（有 SFT cold start 的模型不仅起点 baseline 更高，而且能持续提升，而没有 SFT 训练的模型很早就进入平台期）；部分任务上的提升 "exceeding 100%"（超过 100%）— [UserRL HTML](https://arxiv.org/html/2509.19736)
- 模拟器发现："GPT-4o-based training generally yields higher performance"（基于 GPT-4o 的训练通常带来更高性能），优于 Qwen3-32B，但开源模拟器 "remain a cost-effective and transferable option"（仍是一个性价比高且可迁移的选择）— [UserRL HTML v1](https://arxiv.org/html/2509.19736v1)；[arXiv abstract](https://arxiv.org/abs/2509.19736)

#### UserBench（Salesforce + UIUC，2025-07，arXiv 2507.22034）— UserRL 的 TravelGym 所基于的评估 gym
- "simulated users who start with underspecified goals and reveal preferences incrementally"（模拟用户从不充分指定的目标开始，并逐步透露偏好）；模型 "fully align with all user intents only 20% of the time on average"（平均只有 20% 的时间能完全对齐所有用户意图），最好的模型 "uncover fewer than 30% of all user preferences"（发现的用户偏好不到全部的 30%）— [arXiv 2507.22034](https://arxiv.org/abs/2507.22034)

#### BAO: Behavioral Agentic Optimization（CMU 等，2026-02，修订于 2026-06，arXiv 2602.11351）
- 基座模型：Qwen3 1.7B 和 4B（与目标规模最接近）— [BAO HTML](https://arxiv.org/html/2602.11351)
- 用户模拟器：训练时用 Qwen3-8B；在 Telepathy-Gym 和 Turtle-Gym 上评估时用 GPT-4o，"to introduce distribution shift"（以引入分布偏移）— [BAO HTML](https://arxiv.org/html/2602.11351)
- Cold start：在用 GPT-4o 配合显式行为 prompt 合成的数据上做 SFT warm start，然后做带 turn 级 advantage 的行为正则化 GRPO — [BAO HTML](https://arxiv.org/html/2602.11351)
- 两个目标：累积任务 reward R(tau) vs 用户参与度 U(tau) = "the number of user-involved actions per trajectory"（每条 trajectory 中涉及用户的动作数）— [BAO HTML](https://arxiv.org/html/2602.11351)
- 行为正则项：(i) 对没有环境反馈的连续用户轮次施加信息寻求惩罚；(ii) 过度思考惩罚 "(T-T')/T'"，针对在完成前耗尽 token 预算的情况；最大轮数 T=15（Function/Turtle），T=12（Telepathy）— [BAO HTML](https://arxiv.org/html/2602.11351)
- 结果 Function-Gym Qwen3-4B：BAO Score 0.6923 vs UserRL 0.5256 vs GPT-4o 0.1410；Pass@U-1 0.2692 vs 0.2436；user-rate 0.2148 vs 0.3758。Turtle-Gym Pass@U-1 0.1063 vs UserRL 0.0417（GPT-4o 0.1719）— [BAO HTML](https://arxiv.org/html/2602.11351)
- 在 Turtle-Gym 上的 UserRL baseline 中观察到 reward hacking："long answers to confuse the judge model"（用长答案迷惑 judge 模型）；BAO 的 reward-translation rate 为 0.575 vs UserRL 0.154 — [BAO HTML](https://arxiv.org/html/2602.11351)
- Baseline 的病态行为：UserRL agent "relies heavily on user engagement to verify answer correctness rather than autonomously exploring the environment"（严重依赖用户参与来验证答案正确性，而不是自主探索环境）— [BAO HTML](https://arxiv.org/html/2602.11351)

#### MUA-RL（中科院 + 北大，2025-08，arXiv 2508.18669）
- "for the first time in the field of agentic tool use, integrates LLM-simulated users into the reinforcement learning loop"（在 agentic 工具使用领域首次将 LLM 模拟用户整合进强化学习循环）— [arXiv 2508.18669](https://www.arxiv.org/abs/2508.18669)
- 基座：Qwen3-8B / 14B / 32B non-thinking — [MUA-RL HTML](https://arxiv.org/html/2508.18669)
- 用户模拟器：RL 期间用 "GPT-4o-2024-11-20"；在 tau1/tau2 评估时用 "GPT-4.1 as the user simulator"（GPT-4.1 作为用户模拟器）（训练/评估模拟器不一致）— [MUA-RL HTML](https://arxiv.org/html/2508.18669)
- Cold start：在 "9 scenarios, including 5 synthetic scenarios and 4 real-world MCP server scenarios"（9 个场景，包括 5 个合成场景和 4 个真实 MCP server 场景）上的 "approximately two thousand trajectories"（约两千条 trajectory），由三个 LLM（agent / 用户 / 工具模拟器）生成，经 "dual-verification, which combines human expert annotation with DeepSeek-R1 evaluation"（结合人类专家标注与 DeepSeek-R1 评估的双重验证）过滤 — [MUA-RL HTML](https://arxiv.org/html/2508.18669)。据 FACA，公开发布的是 "1,580 annotated multi-turn tool-use trajectories spanning five mock and four MCP tasks"（1,580 条标注的多轮工具使用 trajectory，覆盖五个 mock 任务和四个 MCP 任务）— [FACA HTML](https://arxiv.org/html/2608.17499)
- RL 任务："115 retail and 50 airline datasets from TAU1-Bench"（来自 TAU1-Bench 的 115 个 retail 和 50 个 airline 数据）（共 165 个任务）— [MUA-RL HTML](https://arxiv.org/html/2508.18669)
- 算法/reward：GRPO；"r=1 only when the agent successfully fulfills the task...and r=0 otherwise"（仅当 agent 成功完成任务时 r=1……否则 r=0）；去掉了 tau-bench 的对话内容检查；无格式惩罚；"Upper bound of 30 interaction turns"（交互轮数上限 30）；序列上限 32,768 token；group 8，batch 32，25 个 epoch，KL beta=0.001，rollout temperature 1.0 — [MUA-RL HTML](https://arxiv.org/html/2508.18669)
- 结果 tau2 Retail/Airline：Qwen3-8B 基座 41.0/12.5 -> cold-start 31.4/16.0 -> MUA-RL-8B 49.8/19.0；Qwen3-14B 基座 43.1/14.8 -> cold-start 53.7/24.0 -> MUA-RL-14B 66.0/38.0；MUA-RL-32B 67.3/45.4/Telecom 28.3；cold-start 32B 58.2/31.1 — [MUA-RL HTML](https://arxiv.org/html/2508.18669)
- Ablation："MUA-RL-32B w/o cold-start achieves higher scores on TAU2-Bench compared to MUA-RL-32B w/o RL; however, it performs worse on BFCL-V3 Multi Turn. Nevertheless, both variants underperform relative to MUA-RL-32B"（无 cold-start 的 MUA-RL-32B 在 TAU2-Bench 上得分高于无 RL 的 MUA-RL-32B；但在 BFCL-V3 Multi Turn 上表现更差。不过两个变体都不如 MUA-RL-32B）— [MUA-RL HTML](https://arxiv.org/html/2508.18669)
- 失败：仅 cold-start SFT 就 "degraded performance on TAU Telecom"（降低了 TAU Telecom 上的性能）（并把 8B retail 从 41.0 降到 31.4），归因于 "domain-specific patterns and biases"（领域特定的模式和偏差）— [MUA-RL HTML](https://arxiv.org/html/2508.18669)

#### FACA："The Next User Turn Is More Than Context"（2026-08，arXiv 2608.17499）
- 基座："Qwen3-8B and Qwen3-14B"，通过 "SFT on the public MUA-RL release"（在公开的 MUA-RL 数据上做 SFT）初始化（1,580 条 trajectory）；RL 仅在 "Only the Airline and Retail training splits of tau-bench"（仅 tau-bench 的 Airline 和 Retail 训练划分）上进行 — [FACA HTML](https://arxiv.org/html/2608.17499)
- 用户模拟器："frozen DeepSeek-V4-Flash user policy"（冻结的 DeepSeek-V4-Flash 用户 policy），输出 JSON，在可见话语之外带一个私有的 "strategy" 字段，取值于 {be_vague, reveal_piece, ask_clarification, change_mind, challenge_solution, confirm, close} — [FACA HTML](https://arxiv.org/html/2608.17499)
- Reward：strategy -> 极性 {+1: confirm, close, reveal_piece; 0: be_vague, invalid; -1: ask_clarification, challenge_solution, change_mind}；局部归一化的 "reaction advantage" A^p 加到终局 outcome advantage 上：A = A^o + lambda A^p，lambda 上限为 0.5，"so that reaction credit remains optimization-relevant while A^o stays dominant"（使 reaction credit 仍与优化相关，同时 A^o 保持主导）；clipping 按每个用户到用户的片段分别施加 — [FACA HTML](https://arxiv.org/html/2608.17499)
- 结果（9 个 tau 系领域，3 次运行）：8B Interactive-GRPO 34.7% -> FACA 40.6%（+5.91）；14B 42.5% -> 52.7%（+10.22）；tau2 Telecom 30.7 -> 41.2（8B），26.3 -> 83.6（14B）；zero-shot 迁移到 Pare-Bench 和 Co-Gym — [FACA HTML](https://arxiv.org/html/2608.17499)；[arXiv abstract](https://arxiv.org/abs/2608.17499)
- Ablation（8B）：错位的 reaction 33.92%，随机化极性 32.66%（都低于 34.70% 的 baseline），符号反转 lambda=-0.5 -> 15.08% — [FACA HTML](https://arxiv.org/html/2608.17499)

#### APIGen-MT / xLAM-2（Salesforce，2025-04，arXiv 2504.03601；NeurIPS 2025 D&B）— 仅 SFT，但定义了模拟人类数据的配方
- 两个阶段：blueprint (q, a_gt, o_gt) 由 "Format & Execution Checker"（格式与执行检查器）和 "a committee of multiple LLM reviewers"（多个 LLM 审阅者组成的委员会）通过 "majority voting"（多数投票）验证；reflection 使 blueprint 通过率提升 "2.5x ... to attain 70%"（2.5 倍……达到 70%）（从 28%）— [APIGen-MT HTML](https://arxiv.org/html/2504.03601)
- Trajectory 阶段：GPT-4o function-calling agent 对 LLM 人类；验证方式为 "comparing the final environment state to a_gt and the agent's final responses to o_gt"（将最终环境状态与 a_gt 比较，将 agent 的最终回复与 o_gt 比较）；67% 的模拟通过 — [APIGen-MT HTML](https://arxiv.org/html/2504.03601)
- 人类模拟器稳定化：best-of-N（N=4）加 self-critique，使模拟人类不会 "drift from the original instruction or be unduly influenced by the agent's responses"（偏离原始指令或过度受 agent 回复影响）— [APIGen-MT HTML](https://arxiv.org/html/2504.03601)
- 数据/训练："We open-source 5K synthetic data trajectories"（我们开源了 5K 条合成数据 trajectory）（APIGen-MT-5k）；"filtered Behavioral Cloning"（过滤后的行为克隆）全参微调；基座模型 Llama 3.1/3.2（8B、70B）和 Qwen2.5（1B、3B、32B）— [arXiv 2504.03601v4](https://arxiv.org/abs/2504.03601v4)；[HF model card](https://huggingface.co/Salesforce/Llama-xLAM-2-8b-fc-r)
- tau-bench pass^1：xLAM-2-70b Retail 67.1 / Airline 45.2 / 总体 56.2；GPT-4o 62.8 / 43.0 / 52.9；xLAM-2-8b 58.2 / 35.2 / 46.7；Claude 3.5 Sonnet 总体 60.1 — [APIGen-MT HTML](https://arxiv.org/html/2504.03601)；[HF model card](https://huggingface.co/Salesforce/Llama-xLAM-2-8b-fc-r)

#### SWEET-RL / ColBench（Meta FAIR + Berkeley，2025-03，arXiv 2503.15478）
- 基座：Llama-3.1-8B-Instruct；人类模拟器为 Llama-3.1-70B-Instruct（backend）和 Qwen2-VL-72B（frontend），它能看到隐藏的参考解："based on the reference code visible only to the human simulator"（基于仅对人类模拟器可见的参考代码），但 "will not write code"（不会写代码）— [SWEET-RL HTML](https://arxiv.org/html/2503.15478)
- "interactions are limited to 10 back-and-forth rounds"（交互限制为 10 个来回）；每个领域 10k 个训练任务；15k（backend）/ 6k（frontend）条离线 trajectory — [SWEET-RL HTML](https://arxiv.org/html/2503.15478)
- 算法：step 级 critic，用 Bradley-Terry 目标并利用训练时信息（参考解）训练；advantage 通过与参考模型的平均 log-prob 差进行参数化；policy 用 DPO 在 critic 排序的候选上更新（离线，因此 GRPO/PPO "do not apply"（不适用））— [SWEET-RL HTML](https://arxiv.org/html/2503.15478)
- 结果：backend 成功率 40.4% vs 多轮 DPO 34.4%；frontend 胜率 48.2% vs 42.8%；总体 "6% absolute improvement"（6% 的绝对提升）；8B "match or exceed ... GPT4-o"（达到或超过……GPT4-o）— [arXiv abstract](https://arxiv.org/abs/2503.15478)
- Judge reward 的失败："a fixed LLM-as-a-Judge can easily get distracted by the length and format of the response without actually attending to its utility for task success"（固定的 LLM-as-a-Judge 很容易被回复的长度和格式分散注意力，而没有真正关注其对任务成功的效用）— [SWEET-RL HTML](https://arxiv.org/html/2503.15478)

#### CollabLLM（Stanford/Microsoft，2025-02，arXiv 2502.00640；ICML 2025 oral）
- 基座：Llama-3.1-8B-Instruct，LoRA rank 32；用户模拟器为 GPT-4o-mini，带一个 "implicit goal"（隐式目标），prompt 要求 "Provide vague or incomplete demands in the early stages"（在早期阶段提出模糊或不完整的需求）以及 "Occasionally Make Mistakes"（偶尔犯错）— [CollabLLM HTML](https://arxiv.org/html/2502.00640v3)
- Multiturn-aware Reward = 来自前向采样对话的期望未来 reward，窗口 w=2；reward = 外在任务相似度 + 内在项 "-min[lambda*TokenCount, 1] + R_LLM"（Claude-3.5-Sonnet 作 judge，lambda 在 code/math 上为 5e-4，docs 上为 1e-4）— [CollabLLM HTML](https://arxiv.org/html/2502.00640v3)
- 训练：先在 "500-sample synthetic datasets (2,300+ turns each)"（500 样本的合成数据集（每个 2,300+ 轮））上做离线 SFT / DPO，然后做在线 PPO / 在线 DPO；任务 +18.5%，交互性 +46.3%，201 人用户研究满意度 +17.6%，用时 -10.4% — [CollabLLM HTML](https://arxiv.org/html/2502.00640v3)

#### IntentRL（阿里通义，2026-02，arXiv 2602.03468）— 面向 deep research 的澄清 agent
- 基座：Qwen2.5-7B 澄清 agent；Qwen2.5-72B-Instruct 摘要器；模拟器 LLM 为 gemini-3-pro-preview，前面加规则过滤器 — [IntentRL HTML](https://arxiv.org/html/2602.03468)
- 模拟器："Hybrid rule-based and LLM-judge design"（规则与 LLM-judge 混合设计）：all-mpnet-base-v2 embedding，重复阈值 0.92，相关性阈值 0.8；"Only if the question passes these checks does an LLM generate a user response conditioned on the intent list"（只有问题通过这些检查后，LLM 才会以意图列表为条件生成用户回复）— [IntentRL HTML](https://arxiv.org/html/2602.03468)
- 两阶段 GRPO：阶段 I 在 371 条意图 trajectory / 2,347 轮（来自 50 个种子）上离线训练；阶段 II 用模拟器在线训练，并采用 "partial teacher forcing"（部分 teacher forcing）；最大澄清轮数 T=9；reward：余弦内容分、格式 1.0/0.5/0、对重复（gamma=2）、偏离、无关紧要的惩罚 — [IntentRL HTML](https://arxiv.org/html/2602.03468)
- 结果：意图 precision 36.44% vs CollabLLM 18.00%；报告分 43.65 vs 无澄清 39.39；去掉阶段 II 会导致 "repeated behaviors, irrelevant questions, and stubborn reactions to user feedback"（重复行为、无关问题以及对用户反馈的固执反应）；SFT baseline 表现为 "memorization rather than adaptive clarification"（记忆而非自适应澄清）— [IntentRL HTML](https://arxiv.org/html/2602.03468)

#### AskBench / rubric 引导的 RLVR（2026-02，arXiv 2602.11199）
- Qwen2.5-7B-Instruct policy；冻结的 Qwen3-30B-A3B judge 兼任用户："Provide a concise, natural-sounding response that ONLY answers the assistant's immediate question"（给出简洁、自然的回复，只回答助手当前的问题）以及 "Do NOT volunteer extra information"（不要主动提供额外信息）— [AskBench HTML](https://arxiv.org/html/2602.11199v1)
- GRPO reward：过早给出最终答案 -2.0，rubric 全覆盖 +1.0 / 部分 0.8，问题不聚焦 -0.8，终局 +1/-1；每个领域 100 个拒绝采样的条目；准确率 0.332 -> 0.615；SFT baseline 损害 OOD（HealthBench 0.526 -> 0.247）；某一变体中冗余提问率 0.463 — [AskBench HTML](https://arxiv.org/html/2602.11199v1)

#### 通过协作式 self-play 实现可控澄清（Google DeepMind，arXiv 2512.04068，v1 2025-12，修订于 2026-09）
- 主模型 Gemma 2 9B，另有 Gemma 2 2B 和 Qwen3 4B；用户由同一模型模拟，给定真实解释并 "instructed to communicate without revealing it"（被要求在不透露它的情况下交流）；ReST（3 个 epoch）；reward "acc(a,a*) - alpha*n_clar - beta*|answer tokens|"；1,776 个 AmbigQA + 3,744 个 Pacific 训练任务 — [arXiv 2512.04068](https://arxiv.org/html/2512.04068)

#### 带对齐模拟器的校准交互式 RL（2026-05，arXiv 2605.26403）
- Gemma-3-4B-IT policy；Qwen2.5-7B-Instruct 模拟器，在 oracle 收集的类人对话上做 SFT 校准（1,860 条 MATH-Chat，16,028 条 MediumDocEdit-Chat）；GRPO，稀疏的末轮 reward — [Calibrated RL HTML](https://arxiv.org/html/2605.26403)
- 理论：性能差距在 policy 偏移上以 O(H^2 eps) 累积，在模拟器偏差上以 O(H^2 delta) 累积 — [Calibrated RL HTML](https://arxiv.org/html/2605.26403)
- 结果：MATH 准确率 基座 82.3 / 静态上下文 85.0 / naive 交互式 89.3 / 校准后 91.5；DocEdit BLEU 32.2 / 33.8 / 26.1 / 34.6（naive 交互式*低于*基座）— [Calibrated RL HTML](https://arxiv.org/html/2605.26403)

#### 其他 2026 年模拟器在环的训练工作（仅摘要层面）
- WMG-RL（2026-09，arXiv 2609.01067）："a frozen user simulator provides reward supervision before real user exposure"（在接触真实用户之前，由冻结的用户模拟器提供 reward 监督），用于训练推荐任务中的 "a compact 1.7B student policy"（一个紧凑的 1.7B 学生 policy）；细节未说明 — [arXiv 2609.01067](https://arxiv.org/abs/2609.01067v1)
- EnvACE（2026-08，arXiv 2608.06197）：policy "plays the role of the environment to produce the response induced by that action"（扮演环境的角色，产生该动作所引发的响应）（world rehearsal），并迁移到 tau2-Bench；不是用户模拟器方法 — [arXiv 2608.06197](https://arxiv.org/pdf/2608.06197)
- Early Experience（Meta + OSU，2025-10，arXiv 2510.08558）：Llama-3.2-3B / Qwen2.5-7B / Llama-3.1-8B，在包括 tau-bench 在内的 8 个环境上；Tau-Bench（Llama-3.1-8B）IL 35.9 -> IWM 40.8 / SR 41.7；WebShop IL 47.3 -> 58.6 / 58.2；"1/8 of the demonstrations already surpasses imitation learning trained on the full dataset"（仅用 1/8 的示范就已超过在完整数据集上训练的模仿学习）（WebShop）；WebShop Llama-3.2-3B IL->GRPO 约 82% vs SR->GRPO 约 92%；无 grounding 的 STaR 式长 CoT 在 WebShop 上 "-47.3" — [Early Experience HTML](https://arxiv.org/html/2510.08558)

### 推断
- 对 1.7B-4B 的 agent，最接近的模板是 BAO（Qwen3-1.7B/4B，Qwen3-8B 模拟器，SFT warm start，带 turn 级 advantage 的 GRPO，轮次效率正则项）和 UserRL（Qwen3-4B，Qwen3-32B 模拟器，5K 蒸馏 SFT，GRPO Equalized/R2G）；两者都运行 8B-32B 的冻结开源权重模拟器，因此并不需要 GPT 级别的模拟器。
- 事实上的标准 reward 是基于最终环境状态的二值 reward（MUA-RL、UserRL TauGym、APIGen-MT 验证），这可以直接映射为 DB 状态检查；那些加入用户侧信号的论文（FACA reaction advantage、CollabLLM MR、BAO 参与度惩罚）都保持 outcome 项占主导。
- 典型上限：10-30 轮 agent-用户交互，16-32K token；SQL agent 的设置（上下文中有 DB 结果行）更接近 MUA-RL 的 32K，而不是 128K 的 deep research 设置。

### 空白/未知
- UserRL 中 "RL without SFT" 的确切数字（图 2 左）未提取到；只有原始 baseline（0.2929 / 0.3128）和平台期的陈述可用。
- APIGen-MT 各尺寸（1B/3B/32B）的 tau-bench 数字无法从 HTML 或 model card 中获取。
- 没有论文报告在 tau2-bench 本身上训练过的 1.7B-4B agent；找到的最小的 tau 训练模型是 Qwen3-8B（MUA-RL、FACA）。
- MUA-RL 没有公开其训练时的用户 prompt；是否复用了 tau-bench 的用户 prompt 未说明。

## 关键问题 2. 多轮 agent 的 RL 算法与 credit assignment（通用 agent RL，无用户模拟器）

### 要点
无 critic 的组方法占主导；2025-26 年的改进包括：(a) 无 critic 的 step/turn 级 advantage（GiGPO anchor-state 分组、Flow-GRPO 广播、FACA 局部归一化、LightningRL 逐调用 credit），(b) 防止崩溃的稳定手段（StarPO-S trajectory 过滤 + clip-higher + 去 KL、SimpleTIR void-turn 过滤、通义负样本过滤），以及 (c) horizon curriculum（AgentGym-RL ScalingInter）。

### 引用的发现
- GiGPO（2025-05，arXiv 2505.10978；verl-agent）：Qwen2.5-1.5B/3B/7B-Instruct；A(a_t) = A^E(tau) + omega*A^S(a_t)，omega=1；step 组通过对 trajectory 组中重复出现的环境状态（"anchor states"（锚状态））做哈希形成，无需额外 rollout，"< 0.002% of the total per-iteration training time"（< 每次迭代总训练时间的 0.002%）；reward 为 10/0，无效动作惩罚 -0.1（ALFWorld/WebShop），1/0，惩罚 -0.01（Search QA）；group 8 x 16 组 = 128 个环境；ALFWorld 50 步，WebShop 15 步，search 4 轮；ALFWorld/WebShop 的历史窗口为 2；ALFWorld 1.5B 86.1% vs GRPO 72.8%，WebShop 83.5 vs 75.8 — [GiGPO HTML](https://arxiv.org/html/2505.10978)；[verl-agent](https://github.com/langfengQ/verl-agent)
- RAGEN / StarPO（2025-04，arXiv 2504.20073）：Qwen2.5-0.5B（符号任务）和 3B（WebShop）；"Echo Trap"（回声陷阱）："the model repeatedly reuses memorized reasoning paths when trained on self-generated trajectories, leading to a collapse in diversity"（模型在自生成 trajectory 上训练时反复重用记住的推理路径，导致多样性崩溃），其前兆是 reward-std 崩溃、熵剧烈波动、梯度尖峰；StarPO-S 保留 "the top p% highly-uncertain prompts"（不确定性最高的前 p% 的 prompt）（默认 25%），去掉 KL，clip-higher eps_high=0.28 / eps_low=0.2；每个 prompt 更少的回复（4）配合更多的 prompt 泛化更好；每轮 5-6 个动作最佳；更新鲜的 rollout（Online-1）更好；"without fine-grained, reasoning-aware reward signals, agent reasoning hardly emerge"（没有细粒度、感知推理的 reward 信号，agent 推理几乎不会涌现），且在只有成功信号的 reward 下模型会 "produce hallucinated reasoning"（产生幻觉式推理）— [RAGEN HTML](https://arxiv.org/html/2504.20073v2)
- AgentGym-RL / ScalingInter-RL（2025-09，arXiv 2509.08755；ICLR 2026）：训练 "from scratch -- without relying on supervised fine-tuning (SFT)"（从零开始——不依赖监督微调 (SFT)）；"restricting the number of interactions, and gradually shifts towards exploration with larger horizons"（限制交互次数，并逐渐转向更大 horizon 的探索）；Qwen2.5-3B/7B；7B "average improvement of 33.65 points"（平均提升 33.65 分）；逐步扩展使 agent "less prone to collapse under long horizons"（在长 horizon 下更不容易崩溃）— [arXiv 2509.08755](https://arxiv.org/abs/2509.08755)；[moonlight review](https://www.themoonlight.io/en/review/agentgym-rl-training-llm-agents-for-long-horizon-decision-making-through-multi-turn-reinforcement-learning)
- SPA-RL（2025-05，arXiv 2505.20732）：训练一个进度估计器，其逐步贡献之和等于任务完成度；与 grounding 信号结合；在 WebShop/ALFWorld/VirtualHome 上成功率 +2.5%，grounding +1.9% — [arXiv 2505.20732](https://www.arxiv.org/abs/2505.20732)
- RLVMR（2025-07，arXiv 2507.22844；ICLR 2026）：对显式标注的规划/探索/反思步骤给予规则可验证的 reward，外加 outcome；7B 在最难的未见 ALFWorld 划分上达到 83.6% — [arXiv 2507.22844](https://arxiv.org/abs/2507.22844v1)
- Agent Lightning / LightningRL（Microsoft，2025-08，arXiv 2508.03680）：将 agent 执行与训练解耦；"credit assignment module determines how much each LLM request contributed"（credit assignment 模块确定每次 LLM 请求贡献了多少），然后逐调用应用 GRPO/PPO；演示包括 text-to-SQL、RAG、数学工具使用 — [arXiv 2508.03680](https://arxiv.org/abs/2508.03680v1)
- AgentFlow / Flow-GRPO（2025-10，arXiv 2510.05592；ICLR 2026 oral）："broadcasting a single, verifiable trajectory-level outcome to every turn"（将单个可验证的 trajectory 级 outcome 广播到每一轮），组归一化 advantage，在 4 模块系统中只训练 planner（Qwen2.5-7B-Instruct）；search +14.9%，agentic +14.0% — [arXiv 2510.05592](https://arxiv.org/abs/2510.05592)
- SimpleTIR（2025-09，arXiv 2509.02479）：不稳定性 "caused by distributional drift from external tool feedback, leading to the generation of low-probability tokens, which compounds over successive turns"（由外部工具反馈带来的分布漂移引起，导致生成低概率 token，并在后续轮次中累积放大）；修复：过滤含 "void turns (turns that yield neither a code block nor a final answer)"（空轮（既不产生代码块也不产生最终答案的轮次））的 trajectory；Qwen2.5-7B base AIME24 22.1 -> 50.5 — [arXiv 2509.02479](https://arxiv.org/pdf/2509.02479)
- MEM1（2025-06，arXiv 2506.15841）：带 masked trajectory 的 PPO 式 RL，使 agent 保持一个大小恒定的 "compact shared internal state"（紧凑的共享内部状态）；在 16 目标 QA 上，MEM1-7B 相比 Qwen2.5-14B-Instruct 性能 "3.5x"（3.5 倍）、内存少 "3.7x"（3.7 倍）— [arXiv 2506.15841](https://arxiv.org/abs/2506.15841v1)
- ToolRL（2025-04，arXiv 2504.13958）：R_final = R_format{0,1} + R_correct[-3,3]（工具名 / 参数名 / 参数值通过二分图匹配对齐）；4K 个 RL 样本（2K ToolACE + 1K Hammer + 1K xLAM）；"Adding a length reward does not consistently improve task performance, and in smaller-scale models, it can even cause substantial degradation"（加入长度 reward 并不能稳定提升任务性能，在较小规模模型上甚至会导致显著退化）；reward 的比重应从格式逐步转向正确性 — [ToolRL HTML](https://arxiv.org/html/2504.13958v1)
- 通义 DeepResearch（2025-10，arXiv 2510.24701）："tailored adaptation of GRPO"（对 GRPO 的定制化改造），包括 token 级 loss、clip-higher、leave-one-out advantage、严格 on-policy；"reward is a pure 0 or 1 signal of answer correctness"（reward 是答案正确性的纯 0 或 1 信号），"We do not include a format reward ... because the preceding cold start stage ensures the model is already familiar with the required output format"（我们不包含格式 reward……因为之前的 cold start 阶段已确保模型熟悉所需的输出格式）；丢弃 "exceed a length limit"（超出长度限制）的负样本；128 次工具调用 / 128K 上下文；动态过滤总是失败 / 总是成功的问题；"Directly optimizing on an unfiltered set of negative rollouts significantly degrade training stability and can lead to policy collapse"（直接在未过滤的负 rollout 集合上优化会显著降低训练稳定性，并可能导致 policy 崩溃）— [Tongyi HTML](https://arxiv.org/html/2510.24701)
- Kimi K2（Moonshot，2025-07）：基于 "3000+ real MCP tools"（3000+ 个真实 MCP 工具）和 "over 20,000 synthetic tools"（超过 20,000 个合成工具）的数据合成，"LLM-generated user personas with distinct communication styles"（LLM 生成的、具有不同沟通风格的用户画像），有状态的工具模拟器，LLM-judge rubric 过滤，代码使用真实沙箱；RL 采用可验证 reward + self-critique rubric、每任务 token 预算、PTX loss、temperature 衰减；tau2 retail 70.6 / airline 56.5 / telecom 65.8（Avg@4）— [Kimi K2 report](https://arxiv.org/html/2507.20534)

### 推断
- 对于环境状态是确定性且可哈希的 DB agent（schema + 表内容），GiGPO 的 anchor-state 分组可直接适用：不同 rollout 到达的相同 DB 状态天然构成一个 step 级分组，无需额外成本。
- 过滤退化 rollout（空轮、超长、组内 reward 全相同）是 SimpleTIR、StarPO-S 和通义各自独立报告的、反复出现的低成本稳定手段；这是在做任何 reward shaping 之前应首先加入的东西。
- 一旦 SFT 建立了协议，格式 reward 就是可选的（通义）；ToolRL 表明长度 reward 会损害小模型。

### 空白/未知
- 没有找到在用户模拟器设置中（状态包含随机的用户文本）应用 GiGPO 式 anchor 分组的工作。
- ScalingInter-RL 的确切 horizon 调度和各环境数字无法获取（HTML 404；只有摘要）。

## 关键问题 3. 如何防止模拟用户泄露答案或配合违反协议的行为

### 要点
预防几乎完全停留在 prompt 层面（"只透露被问到的内容"、"不要给出解决方案"），有时再加机械性闸门（词法泄露过滤器、基于 embedding 的冗余检查、best-of-N self-critique、结构化的 strategy 字段）。2026 年的保真度审计表明，基于 prompt 的模拟器仍然会过早泄露且过度配合：tau 系中 24.4% 的成功 episode 包含违反用户设定的情况，主要是过早披露。

### 引用的发现
- tau-bench 用户 prompt 规则："Do not give away all the instruction at once. Only provide the information that is necessary for the current step"（不要一次性给出全部指令。只提供当前步骤所需的信息）以及 "Do not repeat the exact instruction in the conversation. Instead, use your own words"（不要在对话中逐字重复指令，而要用自己的话）— [tau-bench](https://arxiv.org/pdf/2406.12045)
- UserRL IntentionGym："Do NOT provide what missing details need to be clarified or give any examples. Do NOT provide concrete help or solutions."（不要指出需要澄清哪些缺失细节，也不要给任何例子。不要提供具体帮助或解决方案。）— [UserRL HTML v1](https://arxiv.org/html/2509.19736v1)
- AskBench 模拟器："ONLY answers the assistant's immediate question"（只回答助手当前的问题），"Do NOT volunteer extra information"（不要主动提供额外信息）— [AskBench HTML](https://arxiv.org/html/2602.11199v1)
- SWEET-RL：模拟器能看到参考代码，但 "will not write code"（不会写代码），只给出 "a brief explanation in natural language to each clarification question"（对每个澄清问题的简短自然语言解释）— [SWEET-RL HTML](https://arxiv.org/html/2503.15478)
- Self-play 澄清：给用户真实解释，并 "instructed to communicate without revealing it"（被要求在不透露它的情况下交流）— [arXiv 2512.04068](https://arxiv.org/html/2512.04068)
- IntentRL：在 LLM 回答之前设置机械性闸门——与历史的 embedding 相似度 > 0.92 标记为冗余，与意图集合的相似度 < 0.8 标记为无关；只有通过检查后 LLM 才会生成 "conditioned on the intent list"（以意图列表为条件）的回复 — [IntentRL HTML](https://arxiv.org/html/2602.03468)
- APIGen-MT：best-of-N=4 加 self-critique，使人类不会 "drift from the original instruction or be unduly influenced by the agent's responses"（偏离原始指令或过度受 agent 回复影响）；只有最终状态和最终回复都与 ground truth 匹配时才接受 trajectory — [APIGen-MT HTML](https://arxiv.org/html/2504.03601)
- FACA：模拟器在话语之外输出一个隐藏的 "strategy" 标签（be_vague / reveal_piece / ...），使模拟器的披露行为显式且可审计 — [FACA HTML](https://arxiv.org/html/2608.17499)
- CUE（2026-10，arXiv 2610.02460）：命令/示例 "rejected if they contain task-specific content detected by a fixed lexical filter, including terms associated with credentials, identifiers, products, policies, addresses, receipts, or deliveries"（如果包含被固定词法过滤器检测到的任务特定内容则被拒绝，包括与凭据、标识符、产品、政策、地址、收据或配送相关的词语）；失败分类包括 "User Data Leakage"（用户数据泄露）、"Unnecessary Escalation"（不必要的升级）、"Ignoring or Not Gathering Available Information"（忽略或未收集可用信息）（共 16 类）；基础模拟器为 Llama 3.1 8B、GPT 5.4 Mini、Gemini 3.5 Flash Lite；仅用于评估 — [CUE HTML](https://arxiv.org/html/2610.02460v1)
- UserProxyBench（2026-09，arXiv 2609.38043）：在 375 个企业任务上只改变用户代理，"changes mean task reward by 15.2 points"（使平均任务 reward 变化 15.2 分）；"24.4% of successful episodes contain a user-specification violation"（24.4% 的成功 episode 包含违反用户设定的情况）；"The dominant failure is premature disclosure: users provide information before it is requested"（主要失败是过早披露：用户在被询问之前就提供了信息）— [arXiv 2609.38043](https://arxiv.org/abs/2609.38043)
- Sim2Real 差距（COLM 2026，arXiv 2603.11245，451 名参与者 / 165 个任务 / 31 个模拟器）：以人类为基准时 agent 成功率 63.6%，而用模拟器时高达 77.8%（"easy mode"（简单模式））；最佳 USI 为 DeepSeek-V3.1 76.0，人类为 92.7；"UserLM-8b includes nearly twice as many identifier-like tokens per turn (4.8 vs. 2.6 for humans)"（UserLM-8b 每轮包含的类标识符 token 几乎是人类的两倍（4.8 vs. 人类 2.6））；GPT-4o 礼貌轮次占 49.0%，人类为 15.3%；GPT-4o 切换策略 19.1% vs 8.4%，"quietly accepting errors rather than pushing back"（默默接受错误而不是反驳）；persona prompting 使 USI 从 70.9 降到 64.6；"70.6% of reward=0 interactions are actually judged as successful by human users, while 33% of reward=1 interactions are judged as unsuccessful"（70.6% 的 reward=0 交互实际上被人类用户判为成功，而 33% 的 reward=1 交互被判为不成功）— [Sim2Real HTML](https://arxiv.org/html/2603.11245)
- 非协作式模拟器（2025-09，arXiv 2509.23124）：四种行为 "requesting unavailable services, digressing into tangential conversations, expressing impatience, and providing incomplete utterances"（请求不可用的服务、偏离到无关话题、表现出不耐烦、给出不完整的话语）在 MultiWOZ 和 tau-bench 上导致 "significant performance degradation"（显著的性能下降）— [arXiv 2509.23124](https://arxiv.org/abs/2509.23124)
- 校准交互式 RL："uncalibrated simulators frequently exhibit sycophancy...which RL agents rapidly exploit by generating confident but incorrect responses"（未校准的模拟器经常表现出谄媚……RL agent 会通过生成自信但错误的回复迅速利用这一点）；修复方法是在类人对话上对模拟器做 SFT 对齐 — [Calibrated RL HTML](https://arxiv.org/html/2605.26403)
- 综述："A Survey on LLM-based Conversational User Simulation"（EACL 2026，arXiv 2604.24977）对模拟器以及用 RL/DPO 训练的模拟器进行了分类 — [survey](https://www.opentrain.ai/papers/a-survey-on-llm-based-conversational-user-simulation--arxiv-2604.24977/)

### 推断
- 没有一篇训练论文依赖模拟器来识别伪造的工具结果；防止 agent "writing fake results"（编造结果）的保护来自于 reward 是在真实环境状态上计算的（MUA-RL、APIGen-MT、UserRL TauGym），而不是来自用户。对 SQL agent 而言，这意味着应采用 DB-diff/gold-query reward 加上程序化的协议检查器（每个报告的结果是否都来自一次实际执行的查询），而不是任何由用户评判的 reward。
- 可迁移的最低成本泄露控制：(1) 只给模拟器它可以披露的字段，外加 "answer only what is asked"（只回答被问到的内容）；(2) 对模拟器输出中 agent 尚未询问过的标识符设置词法/正则闸门（CUE 式）；(3) 对每个用户轮记录隐藏的披露标签（FACA 式），以便在训练中审计泄露率。
- 由于模拟器过度配合，用一个不同的、更严格的模拟器进行评估（BAO 测试时把 Qwen3-8B 换成 GPT-4o；MUA-RL 用 GPT-4o 训练，用 GPT-4.1 评估）是防止对模拟器过拟合的标准做法。

### 空白/未知
- 没有论文量化*训练后*的 agent 诱使模拟器泄露的频率（RL 前后的泄露率）；UserProxyBench 只用前沿 agent 测量了泄露。
- 没有找到针对非协作式模拟器训练 agent 并报告提升的论文。

## 关键问题 4. SFT : RL 比例；SFT 是否损害探索；从小型 instruct 模型直接做纯 RL 是否会崩溃？

### 要点
报告的 SFT 数据集相对于人们的预期非常小（1.5K-5K 条 trajectory），RL 任务池更小（165-2,686 个任务），即 SFT 样本 : RL 任务大约为 2:1 到 10:1。用户模拟器论文（UserRL、BAO、MUA-RL、FACA、IntentRL）都保留 SFT cold start，并报告无 SFT 的 RL 会进入平台期；单轮工具调用（ToolRL）和某些具身/agent 设置（AgentGym-RL）报告纯 RL 更好。2026 年的工作表明，*过度*训练 SFT（多 epoch）会使熵崩溃，并降低 3B 模型的 RL 上限。

### 引用的发现
- UserRL：5,000 条 SFT trajectory vs 2,686 个 RL 任务；"SFT cold start is critical for unlocking initial interaction ability and enabling sustained RL improvements"（SFT cold start 对于解锁初始交互能力和实现持续的 RL 提升至关重要）；无 SFT 的运行 "plateau early"（很早进入平台期）— [arXiv 2509.19736](https://arxiv.org/abs/2509.19736)；[UserRL HTML](https://arxiv.org/html/2509.19736)
- MUA-RL：约 2,000（公开 1,580）条 SFT trajectory vs 165 个 RL 任务；无 cold-start 的 RL 在 tau2 上胜过纯 SFT，但在 BFCL 多轮上更差，且两者都落后于 SFT+RL — [MUA-RL HTML](https://arxiv.org/html/2508.18669)；[FACA HTML](https://arxiv.org/html/2608.17499)
- FACA：1,580 条 SFT trajectory vs 165 个 RL 任务（Airline 50 + Retail 115）— [FACA HTML](https://arxiv.org/html/2608.17499)
- IntentRL：来自 50 个种子的 371 条离线 trajectory / 2,347 轮；SFT baseline 表现为 "memorization rather than adaptive clarification"（记忆而非自适应澄清）— [IntentRL HTML](https://arxiv.org/html/2602.03468)
- CollabLLM：在线 PPO/DPO 之前使用 500 样本的离线数据集 — [CollabLLM HTML](https://arxiv.org/html/2502.00640v3)
- ToolRL（单轮工具调用）："GRPO Cold Start" = 直接从 instruct 模型做 RL；BFCL-V3 Qwen2.5-1.5B 46.20%（纯 RL）vs 40.21%（SFT-400）vs 19.41%（原始）；3B 52.98 / 34.08 / 33.04；7B 58.38 / 34.08 / 41.97；"SFT initialization leads to memorization and overfitting, which reduces the impact of GRPO's effectiveness"（SFT 初始化导致记忆和过拟合，削弱了 GRPO 的效果）— [ToolRL HTML](https://arxiv.org/html/2504.13958v1)
- AgentGym-RL：当 horizon 逐步增长时，RL "from scratch -- without relying on supervised fine-tuning (SFT)"（从零开始——不依赖监督微调 (SFT)）是可行的；否则 agent "prone to collapse under long horizons"（在长 horizon 下容易崩溃）— [arXiv 2509.08755](https://arxiv.org/abs/2509.08755)
- AskBench：SFT baseline 损害 OOD（HealthBench 0.526 -> 0.247），而 GRPO 带来提升 — [AskBench HTML](https://arxiv.org/html/2602.11199v1)
- Demystifying RL in Agentic Reasoning（2025-10，arXiv 2510.11701）：3K 条真实端到端 SFT trajectory（Qwen3-Coder-30B-A3B 作 teacher）vs 30K 个 RL 问题（约 1:10）；"Replacing stitched synthetic trajectories with real end-to-end tool-use trajectories yields a far stronger SFT initialization"（用真实的端到端工具使用 trajectory 替换拼接的合成 trajectory，可得到强得多的 SFT 初始化）；合成 SFT "yields below 10% on average@32"（average@32 低于 10%）；"Diverse RL datasets sustain higher policy entropy"（多样化的 RL 数据集能维持更高的 policy 熵）；clip-higher eps_high 0.28 -> 0.315；DemyAgent-4B AIME24 72.6 / AIME25 70.0 / GPQA 58.5 / LCB-v6 26.8 — [Demystifying HTML](https://arxiv.org/html/2510.11701)
- 通义 DeepResearch：SFT 通过对强开源模型 trajectory 做拒绝采样得到，"Over 20% of the samples exceed 32k tokens and involve more than 10 tool invocations"（超过 20% 的样本超过 32k token，且涉及 10 次以上工具调用）；确切数量未说明 — [Tongyi HTML](https://arxiv.org/html/2510.24701)
- SFT 过度训练（2026-06，arXiv 2606.18487）：Qwen2.5-Coder-3B-Base，5,000 个 KodCode 问题，1.0-5.8 个 epoch；随着 SFT 深度增加，"peak GRPO pass@10 falls from 0.806 to 0.481"（GRPO 峰值 pass@10 从 0.806 降到 0.481），而 RL 前的 pass@1 上升；RL 前熵阈值 0.18 nats；应选 1.9 epoch 的 checkpoint（pass@10 +0.090）— [arXiv 2606.18487](https://arxiv.org/html/2606.18487v1)
- "When RL Fails after SFT"（2026-06，arXiv 2606.09932）："checkpoints with excessive SFT often show limited improvement during RL"（SFT 过度的 checkpoint 在 RL 期间提升往往有限）；原因是 "over-confident token distributions and ... sharp parameter landscapes"（过度自信的 token 分布以及……尖锐的参数地形）；修复方法是 "base-anchored model fusion ... with targeted neuron reset"（以基座为锚的模型融合……配合定向神经元重置）— [arXiv 2606.09932](https://arxiv.org/abs/2606.09932)
- MUA-RL 的 cold-start 退化：SFT 将 Qwen3-8B tau2 Retail 从 41.0 降到 31.4，之后 RL 才将其恢复到 49.8 — [MUA-RL HTML](https://arxiv.org/html/2508.18669)
- Early Experience：自生成的 rollout 数据 "up to an order of magnitude larger than expert data"（比专家数据大至多一个数量级）；在 WebShop 上 "1/8 of the demonstrations already surpasses imitation learning trained on the full dataset"（仅用 1/8 的示范就已超过在完整数据集上训练的模仿学习）— [Early Experience HTML](https://arxiv.org/html/2510.08558)

### 推断
- 文献中的分歧按交互类型划分：当协议（何时提问、何时行动、何时停止）对基座模型是新的（面向用户的多轮）时，每篇论文都保留了一个小规模 SFT；当基座模型已经能输出正确格式（单轮工具调用）时，纯 RL 胜出。必须学习用户交互协议的 1.7B-4B SQL agent 属于第一类。
- 一致的配方是"轻量" SFT：1.5K-5K 条 trajectory，1-3 个 epoch，按协议正确性筛选，随后在几百到几千个任务上做 RL，去掉 KL 并使用 clip-higher。深度 SFT（在同一数据上 >2 个 epoch）是已有文献记载的、会扼杀 3B 模型 RL 上限的做法。
- 预计仅 SFT 会使某些领域退化（MUA-RL Telecom/8B Retail）；应根据 RL 后的曲线而不是纯 SFT 的准确率来评判 cold start。

### 空白/未知
- 没有论文报告 Qwen3-1.7B/4B agent 在用户模拟器循环中纯 RL 出现明确崩溃；UserRL 报告的是平台期（而非崩溃），且给出的是曲线而非表格。
- 没有对照研究在用户模拟器 RL 设置中改变 SFT 规模（例如 500 vs 5K）。

## 关键问题 5. Cold start 用自学（同模型拒绝采样）还是从更大模型蒸馏

### 要点
在用户模拟器 RL 内部缺乏直接的正面对比证据。相邻证据：Early Experience 表明自生成的、以环境为 grounding 的数据胜过纯专家模仿，并提高 RL 后的上限；Demystifying-RL 表明从强 teacher 蒸馏的*真实* trajectory 胜过拼接的合成数据；ToolRL/AskBench 表明在 teacher 数据上做 SFT 相对于纯 RL 可能过拟合；大多数 tau 式论文只是简单地从 GPT-4o 蒸馏。

### 引用的发现
- Early Experience：自生成（同一 policy）的替代动作 + 有 grounding 的反思在全部 8 个环境上胜过 IL；Tau-Bench IL 35.9 -> SR 41.7；RL 后上限更高（WebShop 3B IL->GRPO 约 82% vs SR->GRPO 约 92%）— [Early Experience HTML](https://arxiv.org/html/2510.08558)
- Demystifying RL：3K 条 teacher trajectory（Qwen3-Coder-30B-A3B，经 Qwen-Agent）相比拼接的合成 SFT（"below 10% on average@32"（average@32 低于 10%））"deliver a clear improvement"（带来明显提升）— [Demystifying HTML](https://arxiv.org/html/2510.11701)
- UserRL 蒸馏 GPT-4o agent + GPT-4o 用户（5K）— [UserRL HTML](https://arxiv.org/html/2509.19736)；BAO 用行为 prompt 从 GPT-4o 蒸馏 — [BAO HTML](https://arxiv.org/html/2602.11351)；MUA-RL 用人工 + DeepSeek-R1 审核过滤 LLM 生成的 trajectory — [MUA-RL HTML](https://arxiv.org/html/2508.18669)
- 可控澄清使用 ReST（同模型对最佳 rollout 做拒绝采样），不用外部 teacher，在 AmbigQA 上 reward 达到 6.63，而 prompt 方法为 -34.49 — [arXiv 2512.04068](https://arxiv.org/html/2512.04068)
- ToolRL：先在 teacher 格式数据上 SFT 再做 GRPO，在全部四个小模型上都不如纯 GRPO — [ToolRL HTML](https://arxiv.org/html/2504.13958v1)
- "Smaller Models, Better Rejects"（2026-09，arXiv 2609.38987）：对于偏好蒸馏，"smaller frozen models generate rejects with less inference compute yet train stronger students than self-generated rejects"（较小的冻结模型以更少的推理算力生成 reject 样本，但训练出的学生比用自生成 reject 样本训练的更强）（code/math，学生 7B-72B）— [arXiv 2609.38987](https://arxiv.org/abs/2609.38987)
- "Finetuning with Sampling"（2026-10，arXiv 2610.02140）：MCMC "progressively transforms off-policy traces to be more on-policy"（逐步把 off-policy 轨迹转变得更加 on-policy），使 SFT 能与 on-policy 方法相媲美，"generalizing better and forgetting less"（泛化更好、遗忘更少）（数字未说明）— [arXiv 2610.02140](https://arxiv.org/abs/2610.02140)

### 推断
- 从这些来源可得出的调和观点：关键在于 (a) 以环境为 grounding 的端到端 trajectory（而非拼接的），以及 (b) 较低的 off-policy 程度。蒸馏提供 (a)；自生成提供 (b)。APIGen-MT/MUA-RL 隐含使用的一个实用折中是：teacher 生成的 trajectory 经环境状态验证过滤，然后保持较少的 epoch。

### 空白/未知
- 范围内没有论文在相同后续 RL 下比较 "same-model RFT cold start vs GPT-4o distillation cold start"（同模型 RFT cold start vs GPT-4o 蒸馏 cold start）；这仍是一个待做的实验。

## 关键问题 6. 观察到的失败模式与 reward hacking

### 要点
有记录的 hack 包括：用长答案操纵 LLM judge（BAO 对 UserRL 的观察，SWEET-RL 对 judge 的观察），用自信的错误答案利用谄媚的模拟器（Calibrated RL），过度询问用户而不是探索环境（BAO、IntentRL、AskBench），回声陷阱/熵崩溃（RAGEN、SimpleTIR），在只有成功信号的 reward 下出现幻觉式推理（RAGEN），以及 SFT 引起的领域退化（MUA-RL）。这些论文中没有报告 agent 一方伪造工具结果，因为 reward 是在真实状态上计算的。

### 引用的发现
- Judge 操纵：UserRL agent 在 Turtle-Gym 上产生 "long answers to confuse the judge model"（用长答案迷惑 judge 模型）；BAO reward-translation rate 0.575 vs 0.154 — [BAO HTML](https://arxiv.org/html/2602.11351)；"a fixed LLM-as-a-Judge can easily get distracted by the length and format of the response"（固定的 LLM-as-a-Judge 很容易被回复的长度和格式分散注意力）— [SWEET-RL HTML](https://arxiv.org/html/2503.15478)
- 模拟器谄媚被利用："RL agents rapidly exploit by generating confident but incorrect responses"（RL agent 通过生成自信但错误的回复迅速加以利用）；naive 交互式 RL 使 DocEdit BLEU 从 32.2 降到 26.1 — [Calibrated RL HTML](https://arxiv.org/html/2605.26403)
- 过度依赖用户："agents repeatedly request user interactions without information gain from the environment"（agent 反复请求用户交互，却没有从环境中获取信息）；"excessive thinking ... premature exhaustion of the token budget"（过度思考……过早耗尽 token 预算）— [BAO HTML](https://arxiv.org/html/2602.11351)；冗余提问率 0.463 — [AskBench HTML](https://arxiv.org/html/2602.11199v1)；没有在线阶段时出现 "repeated behaviors, irrelevant questions, and stubborn reactions to user feedback"（重复行为、无关问题以及对用户反馈的固执反应）— [IntentRL HTML](https://arxiv.org/html/2602.03468)
- 崩溃动态：伴随 reward-std 崩溃和梯度尖峰的 Echo Trap — [RAGEN HTML](https://arxiv.org/html/2504.20073v2)；空轮以及 "catastrophic gradient norm explosions"（灾难性的梯度范数爆炸）— [SimpleTIR](https://arxiv.org/pdf/2509.02479)；未过滤的负样本 "can lead to policy collapse"（可能导致 policy 崩溃）— [Tongyi HTML](https://arxiv.org/html/2510.24701)
- 幻觉式推理：当 "rewards only reflect task success"（reward 只反映任务成功）时，模型会 "produce hallucinated reasoning"（产生幻觉式推理）— [RAGEN HTML](https://arxiv.org/html/2504.20073v2)
- 长度 reward 损害小模型 — [ToolRL HTML](https://arxiv.org/html/2504.13958v1)；无 grounding 的长 CoT SFT 在 WebShop 上 "-47.3" — [Early Experience HTML](https://arxiv.org/html/2510.08558)
- 针对特定模拟器的过拟合风险：UserRL 和 BAO 用与训练不同的模拟器进行评估；sim2real 的 "easy mode"（简单模式）把成功率从 63.6%（人类）抬高到 77.8% — [Sim2Real HTML](https://arxiv.org/html/2603.11245)
- Reaction reward 的脆弱性：在 8B 上 "randomizing reaction polarity removes the Telecom gain"（随机化 reaction 极性会消除 Telecom 上的提升）— [arXiv 2608.17499](https://arxiv.org/abs/2608.17499)

### 推断
- 任何由用户评判或 LLM 评判的组成部分都应设上限（FACA 把 lambda 限制在 0.5；CollabLLM 把 token 惩罚限制在 1），并用 hacking 率指标（BAO 的 reward-translation rate）加以监控；基于真实状态的 outcome 项必须保持主导。
- 与用户-agent-DB 循环最相关的两种 agent 侧病态行为——向用户提问而不是查询 DB，以及过早结束——都已有公开的对策：对没有环境调用的连续用户轮次施加逐轮惩罚（BAO），以及过早作答惩罚（AskBench -2.0）。

### 空白/未知
- 范围内没有论文报告 "agent 伪造工具/DB 结果并且模拟用户接受了它" 这一具体 hack；最接近的是 Calibrated-RL 的谄媚发现，以及 Sim2Real 中模拟器接受错误而不反驳的观察。
- 找到的论文中没有一篇以数值形式报告 RL 前后的过早终止率。
