# 单轮 text-to-SQL 推理 RL（2025-01 至 2026-10）：cold start / SFT 阶段是如何处理的

范围：用 RL（GRPO/PPO/DAPO/DPO）训练的单轮 text-to-SQL 论文，或这些论文所依赖的 SFT 数据来源。多轮/agentic 系统（SkyRL-SQL、MTIR-SQL、SQL-Trail、TRUST-SQL、Progress-SQL、MARS-SQL）仅在与 SFT-vs-RL 问题直接相关时提及；它们由另一位研究者负责。除非另有说明，所有数字均为 BIRD dev 上的执行准确率（EX，%）。"月份" = 首个 arXiv 版本的时间，除非另有说明；以下所有细节均通过 fetch 从 arXiv HTML/摘要页面读取；fetch 未能取到的数值标记为"未说明"（"not stated"）。

## 逐篇论文事实表（base model、是否 SFT、SFT 数据、RL 算法、reward、数据规模、ablation）

### 要点
在 20 多篇单轮 RL 论文中，大约一半直接在 instruction-tuned 的代码模型上应用 GRPO、不做 SFT（Reasoning-SQL、CSC-SQL、CogniSQL-R1-Zero、DeepRetrieval、RingSQL、SQL-Zero，以及就文中所述而言的 ReEx-SQL）；另一半要么先从更强的模型蒸馏推理轨迹（Think2SQL、Reward-SQL、FINER-SQL、SLM-SQL、AGRO-SQL、Graph-Reward-SQL、Sparks），要么从一个已经 SFT 过的公开 checkpoint 开始 RL（Arctic-Text2SQL-R1 以及 SQL-R1 最佳的 7B 配置都从 OmniSQL 开始）。执行匹配仍是主导的 reward；大多数会再加一个小的格式项。

### 引用的发现

**Reasoning-SQL (Pourreza et al., Google; Mar 2025, arXiv 2503.23157)**
- Base：Qwen2.5-Coder 3B / 7B / 14B（instruct）。GRPO 直接应用于 instruct 模型；文中未描述 RL 之前有任何 SFT。SFT 只作为 *baseline* 出现："Direct SFT"（在 BIRD gold SQL 上直接 SFT），以及 "STaR-SFT"（用 Gemini-1.5-Pro-002 配合 CHASE-SQL 分治 prompt 生成的 CoT 轨迹）—— [arXiv HTML](https://arxiv.org/html/2503.23157v2)
- RL 数据：BIRD train 从 9,428 条过滤到 8,026 条，丢弃了被 Gemini-2.0-flash 和 GPT-4o 同时判为错误的查询。GRPO：lr 1e-6，有效 batch 32，3 个 epoch，group size 6，8xH100 —— [arXiv HTML](https://arxiv.org/html/2503.23157)
- Reward = 加权和：执行准确率（权重 3）、LLM-as-judge/AI 反馈（2）、语法检查、schema linking（Jaccard）、n-gram 相似度、格式（各为 1）；权重 "carefully chosen to ensure that no incorrect SQL query can achieve a higher overall reward than a correct query"（经过精心选择，以确保任何错误的 SQL 查询都不能获得比正确查询更高的总 reward）—— [arXiv HTML](https://arxiv.org/html/2503.23157)
- BIRD dev，Base / SFT / GRPO（全部 reward）：3B 45.17 / 55.9 / 58.67；7B 58.73 / 61.53 / 64.01；14B 63.1 / 63.75 / 65.31 —— [arXiv HTML v2](https://arxiv.org/html/2503.23157v2)
- 向 Spider / Spider-DK / Spider-Syn 的泛化：7B SFT 68.08 / 62.8 / 51.93 vs 7B GRPO 78.72 / 73.27 / 69.34；14B SFT 75.04 / 69.15 / 61.02 vs 14B GRPO 81.43 / 73.03 / 72.63 —— [arXiv HTML v2](https://arxiv.org/html/2503.23157v2)
- Reward ablation（7B，BIRD dev，按 fetch 返回的结果）：仅执行 68.90 -> +语法 68.97 -> +schema 69.23 -> +n-gram 69.94 -> 全部 70.66（这些数字高于标题数字 64.01；fetch 未说明解码设置，因此该行只应作为"相对排序"的证据）。不带推理步骤训练会损失约 2 个点 —— [arXiv HTML v2](https://arxiv.org/html/2503.23157v2)
- 摘要中的说法："RL-only training with our proposed rewards consistently achieves higher accuracy and superior generalization compared to supervised fine-tuning (SFT)"（使用我们提出的 reward 的纯 RL 训练，相比监督微调（SFT）始终获得更高的准确率和更好的泛化）；14B 在 BIRD 上比 o3-mini 高 4%，比 Gemini-1.5-Pro-002 高 3% —— [arXiv abs](https://arxiv.org/abs/2503.23157)

**SQL-R1 (Ma et al.; Apr 2025, NeurIPS 2025; arXiv 2504.08600)**
- Base：Qwen2.5-Coder 3B / 7B / 14B。RL 算法为带 KL 的 GRPO，每个查询 8 个候选。Reward：格式 +-1；执行 +2 / 0 / -2；结果 +3 / 0 / -3；长度项与 response/SQL 长度成正比 —— [arXiv HTML](https://arxiv.org/html/2504.08600)
- RL 数据：SynSQL-Complex-5K（从 SynSQL-2.5M 中采样的 5,000 个复杂 NL-SQL 对，去掉 CoT）。SFT cold-start 数据（在使用时）：SynSQL-200K，200,000 条样本，按难度分层每级 50K，带 think/answer 标签 —— [arXiv HTML](https://arxiv.org/html/2504.08600)
- 主要结果（Spider dev / Spider test / BIRD dev）：3B 78.1 / 78.9 / 54.6；7B 87.6 / 88.7 / 66.6；14B 86.7 / 88.1 / 67.1 —— [arXiv HTML v5](https://arxiv.org/html/2504.08600v5)
- Cold-start ablation（Table 4），7B：仅 RL（无 SFT）Spider-test 86.1 / BIRD 63.1；先在 SynSQL-200K 上 SFT 再 RL 86.4 / **59.2**（比仅 RL 更差）；先在 SynSQL-2.5M 上 SFT（即从 OmniSQL-7B 开始）再 RL 88.7 / 66.6（最佳）。14B：仅 RL 88.1 / 67.1；OmniSQL-14B 再 RL 87.6 / 66.6 —— [arXiv HTML v5](https://arxiv.org/html/2504.08600v5)
- 作者结论："SFT cold-start training is not universally essential for RL-based NL2SQL models. Its effectiveness is contingent upon the origin and volume of the training data."（对基于 RL 的 NL2SQL 模型而言，SFT cold-start 训练并非普遍必要。其有效性取决于训练数据的来源和数量。）—— [arXiv HTML v5](https://arxiv.org/html/2504.08600v5)

**Arctic-Text2SQL-R1 (Snowflake; May 2025, v2 Jan 2026; arXiv 2505.20315)**
- Base：Qwen2.5-Coder 7B / 14B / 32B。7B 和 14B 的 RL 从 **OmniSQL**（SFT）checkpoint 开始；32B 两种都试了：Qwen2.5-Coder-32B-Inst 和 OmniSQL-32B。作者**没有**自己做 SFT；他们依赖 OmniSQL 公开的 SFT checkpoint —— [arXiv HTML v2](https://arxiv.org/html/2505.20315v2)
- Reward："1, if the execution results exactly align with ground truth; 0.1, if syntax is correct and SQL is executable; 0, otherwise."（执行结果与 ground truth 完全一致时为 1；语法正确且 SQL 可执行时为 0.1；否则为 0。）—— [arXiv HTML](https://arxiv.org/html/2505.20315)
- Reward hacking："More fine-grained reward designs induced 'lazy' behaviors, where models pursued local optima for short-term rewards rather than global correctness."（更细粒度的 reward 设计会诱发"偷懒"行为，模型追求短期 reward 的局部最优，而不是全局正确性。）他们尝试过并放弃的部分 reward：执行、语法、n-gram 重叠、schema 一致性、格式匹配 —— [arXiv HTML v2](https://arxiv.org/html/2505.20315v2)
- RL 数据：BIRD train 8,017（过滤后）+ Spider train/dev 7,957（过滤后）+ Gretel-Synth-Filtered 11,811 = 约 27,785；约 3,100 条执行结果为空的样本被移除，因为 "such examples can disrupt the learning process by producing spurious or uninformative rewards"（这类样本会产生虚假或无信息量的 reward，从而干扰学习过程）；加入未过滤的合成数据会使结果变差 —— [arXiv HTML v2](https://arxiv.org/html/2505.20315v2); [arXiv HTML](https://arxiv.org/html/2505.20315)
- GRPO 设置：16 个 rollout，batch 256，update batch 128，temperature 0.8，KL beta 0.001，clip 0.2，在线 RL —— [arXiv HTML v2](https://arxiv.org/html/2505.20315v2)
- 初始化 ablation（32B，Table 5）：Qwen2.5-Coder-32B-Inst + batch RL 64.9 vs OmniSQL-32B + 在线 RL 67.9；最终 OmniSQL-32B 70.5。文中称："Stronger SFT models (e.g., OmniSQL) consistently yield better downstream RL results."（更强的 SFT 模型（如 OmniSQL）始终带来更好的下游 RL 结果。）注意该对比把初始化与在线-vs-batch RL 混在了一起 —— [arXiv HTML v2](https://arxiv.org/html/2505.20315v2)
- 最终结果：7B 68.9 dev / 88.8 test(?)；14B 70.1 / 89.4；32B 70.5 / 88.7（fetch 返回的 "test" 列看起来是 Spider-test 而不是 BIRD-test；引用前需核实）—— [arXiv HTML v2](https://arxiv.org/html/2505.20315v2)

**Think2SQL (Papicchio et al.; Apr 2025, TMLR; arXiv 2504.15077)**
- Base：Qwen2.5-Coder-Instruct 0.5B / 1.5B / 3B / 7B / 14B，使用 Open-R1 训练 —— [arXiv HTML](https://arxiv.org/html/2504.15077)
- SFT 数据：在 BIRD train 上采集的 DeepSeek-R1 推理轨迹（temp 0.7，top-p 0.95）；过滤掉 421 条坏/重复行后，只保留执行完全正确的轨迹：1,142 条（193 challenging、265 medium、684 simple；913 train / 229 val）。SFT 5 个 epoch，batch 128，lr 4e-5，4xA100 —— [arXiv HTML](https://arxiv.org/html/2504.15077); [arXiv HTML v5](https://arxiv.org/html/2504.15077v5)
- RL：GRPO，在 9,007 条 BIRD 样本上训练 1 个 epoch，8xH100，40-60 小时。Reward R = 0.85*R_text2sql + 0.10*R_format + 0.05*R_tagcount，其中 R_text2sql 为二值 EX 或 QATCH = mean(cell precision, cell recall, tuple cardinality) —— [arXiv HTML](https://arxiv.org/html/2504.15077); [arXiv HTML v5](https://arxiv.org/html/2504.15077v5)
- BIRD dev（小数）：3B Base 0.382 / SFT 0.460 / RL-QATCH 0.500 / SFT+RL 0.482；7B Base 0.476 / SFT 0.494 / RL-QATCH 0.561 / SFT+RL 0.537；14B Base 0.541 / RL-QATCH 0.602。Think2SQL-0.5B 0.254，Think2SQL-1.5B 0.442（对比 base 0.089 和 0.275）—— [arXiv HTML](https://arxiv.org/html/2504.15077); [arXiv HTML v5](https://arxiv.org/html/2504.15077v5)
- 7B 跨数据集：Spider 0.826（SFT+RL），Spider-Syn 0.794（SFT+RL），Spider-DK 0.731（仅 RL），KaggleDBQA 0.441（SFT+RL）—— [arXiv HTML](https://arxiv.org/html/2504.15077)
- 文中陈述的发现："small LLMs benefit most from reasoning-aware SFT and RL"（小型 LLM 从具备推理意识的 SFT 和 RL 中获益最多）；部分得分的 QATCH reward "crucial for guiding models even when outputs are not fully correct"（即使输出不完全正确，对引导模型也至关重要）；"Generic reasoning skills are insufficient; models must be explicitly exposed to structured reasoning within the domain."（通用推理能力是不够的；模型必须显式地接触领域内的结构化推理。）—— [arXiv abs](https://arxiv.org/abs/2504.15077); [arXiv HTML](https://arxiv.org/html/2504.15077)

**Graph-Reward-SQL (May 2025, v3 Oct 2025; arXiv 2505.12380)**
- Base：主实验用 DeepSeek-Coder-1.3B-Ins 和 6.7B-Ins；最终基准用 Qwen2.5-Coder-7B/14B-Ins。RL 之前做 SFT warm-up：在 200k-Text2SQL 数据集的一个子样本上训练 2 个 epoch，子样本大小等于 Spider train split（8,659）；逐步（stepwise）实验中用 GPT-4o 把 BIRD train（9,428）转换为 CTE 格式 —— [arXiv HTML](https://arxiv.org/html/2505.12380)
- RL：GRPO（group 16），也测试了 PPO。Reward：GMNScore（3.99M 参数的图匹配网络，在 20k+ 条增强的 Spider SQL 对上训练；每样本 0.023 s，执行需 1.088 s）以及 StepRTM（基于规则、在 CTE 步骤上做关系算子树匹配）—— [arXiv HTML](https://arxiv.org/html/2505.12380)
- 1.3B 结果（test-suite acc）：Spider EX-reward 65.28 / GMNScore 67.70 / StepRTM+GMNScore 68.67；BIRD 17.21 / 16.10 / 21.97。Qwen2.5-Coder-7B 用 EX reward 做 GRPO：Spider 78.72，BIRD 64.01。CTE-SFT + StepRTM：相对仅结果 reward，BIRD 上 +5.87，Spider 上 +0.97。未讨论 reward hacking —— [arXiv HTML](https://arxiv.org/html/2505.12380)

**CSC-SQL (Sheng & Xu; May 2025; arXiv 2505.13271)**
- Base：Qwen2.5-Coder-3B/7B/14B/32B-Instruct 和 XiYanSQL-QwenCoder-3B/7B/32B（后者已经做过 SQL SFT）；对 Qwen 模型，文中未描述 GRPO 之前有额外的 SFT（仅用 GRPO 做 "post-training"）。GRPO：在 BIRD train 上 1 个 epoch，6 个 completion，batch 12，lr 3e-6。Reward R = R_EX + 0.1*R_format —— [arXiv HTML](https://arxiv.org/html/2505.13271); [arXiv HTML v2](https://arxiv.org/html/2505.13271v2)
- BIRD dev，n=64 个样本：Qwen-3B Base+SC 56.15，Base+CSC 60.39，GRPO+SC 60.60，GRPO+CSC 63.34；Qwen-7B Base+SC 64.45，Base+CSC 68.70，GRPO+SC 66.15，GRPO+CSC 69.19；XiYan-32B GRPO+SC 68.95，GRPO+CSC 71.33。BIRD private test：7B 71.72，32B 73.67 —— [arXiv HTML v2](https://arxiv.org/html/2505.13271v2); [arXiv abs](https://arxiv.org/abs/2505.13271)

**CogniSQL-R1-Zero (Jul 2025; arXiv 2507.06013)**
- Base Qwen2.5-Coder-7B-Instruct；"we apply Group Relative Policy Optimization (GRPO) directly on Qwen2.5-Coder-7B without any supervised warm-up"（我们直接在 Qwen2.5-Coder-7B 上应用 GRPO，不做任何监督 warm-up）。GRPO G=6，T=0.9，KL beta 0.001；BIRD train 9,428（过滤掉超过 3,000 token 的 prompt）；4xA100-40GB，约 34K RL step —— [arXiv HTML](https://arxiv.org/html/2507.06013)
- Reward：格式 1/0，软格式 0.5，正确性 2/0（执行匹配），超长 -0.5；"alpha_c >> {alpha_f, alpha_sf, alpha_l}" —— [arXiv HTML](https://arxiv.org/html/2507.06013)
- 为什么不做 SFT（他们的预实验）：在蒸馏的 QwQ-32B 轨迹上 SFT 后准确率 "dropped from ~52.0% to ~46.0% after SFT"（SFT 后从约 52.0% 降到约 46.0%）；在自生成（Qwen-7B，经执行验证）数据上 SFT 恢复到约 57.3%；"only by directly optimizing execution-based rewards (via GRPO) did the model reliably improve beyond ~59%"（只有直接优化基于执行的 reward（通过 GRPO），模型才能稳定地超过约 59%）。他们还对比了一个短暂 SFT 的 cold-start 变体，纯 RL "ultimately achieved marginally higher peak accuracy"（最终取得了略高的峰值准确率）—— [arXiv HTML](https://arxiv.org/html/2507.06013)
- BIRD dev：单样本 59.97，best-of-6 69.68。公开发布：36,356 条自生成并验证过的轨迹和约 5,024 条 QwQ-32B 轨迹（HF CogniSQL/Reasoning_Traces、CogniSQL/Positive_Sample_Corpus）—— [arXiv HTML](https://arxiv.org/html/2507.06013)

**ReEx-SQL (May 2025; arXiv 2505.12768)**
- Base Qwen2.5-Coder-7B-Instruct；在 OpenRLHF 中做 GRPO，batch 64，lr 2e-6，T=1.0 下 8 个 rollout，推理链中最多 N=10 次执行交互（execution-aware 推理；介于单轮与多轮之间）。论文中未描述 SFT cold-start 阶段；RL 数据划分/规模未说明 —— [arXiv HTML v2](https://arxiv.org/html/2505.12768v2)
- Reward 权重（格式、exact-match、执行、实体、探索）=（2.0, 1.0, 3.0, 1.0, 2.0）。结果：BIRD dev 64.9，Spider dev 88.8，Spider-Realistic 85.2；ablation 中标准推理 GRPO baseline 60.8 vs ReEx 63.4；在 BIRD dev 上推理开销降低 51.9% —— [arXiv HTML](https://arxiv.org/html/2505.12768); [arXiv abs](https://arxiv.org/abs/2505.12768)

**SQL-o1 (Feb 2025; arXiv 2502.11741)** —— 仅 SFT + MCTS；无 policy-gradient RL
- Base 以 Llama3-8B 为主，另有 Qwen2.5-7B/14B、CodeLlama-7B、DeepSeek-Coder-7B。用 LoRA 做 SFT（lr 1e-5，2 个 epoch，batch 32），数据为 Schema-Aware 数据集加上 Progressive SQL Generation 数据（前缀截断的失败案例），Spider+BIRD 上共 21,254 对。自奖励 R = beta + alpha*log pi(y|x)（beta=100，alpha=0.6），外加 MCTS 中使用的执行 reward {-1,0,+1}。BIRD dev 63.4（Llama3-8B）、66.7（Qwen2.5-7B）、73.1（Qwen2.5-14B）；Spider dev 87.4 —— [arXiv HTML](https://arxiv.org/html/2502.11741)

**Alpha-SQL (Feb 2025, ICML 2025; arXiv 2502.17248)** —— 零训练
- "a 32B open-source LLM without fine-tuning"（一个未经微调的 32B 开源 LLM），MCTS 配合 LLM-as-Action-Model 和自监督 reward；BIRD dev 69.7；比最佳 GPT-4o zero-shot 高 2.5 —— [arXiv abs](https://arxiv.org/abs/2502.17248)

**OmniSQL / SynSQL-2.5M (Mar 2025; arXiv 2503.02240)** —— SQL-R1、Arctic、SLM-SQL、SkyRL-SQL 所用的 SFT 数据来源
- SynSQL-2.5M：在 >16,000 个合成数据库上的 2.5M 条样本；由 Meta-Llama-3.1-8B/70B-Instruct、DeepSeek-Coder-6.7B/33B-Instruct、DeepSeek-Coder-V2-Lite-Instruct、Qwen2.5-7B/14B/32B/72B-Instruct 和 Qwen2.5-Coder 生成，"larger models assigned a greater share"（较大的模型分配更大的份额）；过滤 = 执行验证（语法错误/超时）、每个 SQL 模板保留一条查询、对 CoT 候选做多数投票 —— [arXiv HTML](https://arxiv.org/html/2503.02240); [arXiv abs](https://arxiv.org/abs/2503.02240)
- OmniSQL-7B/14B/32B = Qwen2.5-Coder-Instruct 在 SynSQL-2.5M + Spider + BIRD train 上 SFT 2 个 epoch（仅 32B 用 LoRA）。BIRD dev 63.9 / 64.2 / 64.5；Spider dev 81.2 / 81.4 / 80.9；Spider test 87.9 / 88.3 / 87.6 —— [arXiv HTML](https://arxiv.org/html/2503.02240)

**Reward-SQL (May 2025 v1; v3 Jun 2026 = SIGMOD/PACMMOD vol. 43; arXiv 2505.04671)** —— 两个版本使用不同的 base model
- v1（May 2025）：base Qwen2.5-Coder-7B-Instruct。在 Chain-of-CTEs（CoCTE）数据上做 cold-start SFT：由 DeepSeek-R1-Distill-Qwen-32B（多次采样）从 BIRD train 生成 36,103 条 CoCTE，另用 o1-mini 增加多样性，按语法树去重后剩 18,015 条。PRM 在 47,287 条带步骤标签的 CoCTE 上训练（来自 181,665 次 MCTS rollout）。GRPO 使用 PRM + 执行 reward。BIRD dev：SFT greedy 54.4；SFT+GRPO greedy 59.7；SFT+GRPO+PRM@32 68.9。需要 SFT 是 "due to the lack of existing CoCTE-formatted data"（由于缺乏现成的 CoCTE 格式数据）—— [arXiv HTML v1](https://arxiv.org/html/2505.04671v1)
- v3（Jun 2026）：base Qwen3-8B；CoCTE 数据由 DeepSeek-V3.1 从 5 个人工种子生成：来自 17,462 条 SQL 的 51,996 条 trajectory（接受率 90.7%），经 AST 过滤；PRM 的 base 为 Qwen2.5-7B-Coder-Instruct，MCTS 8 个 rollout。BIRD dev greedy / PRM@8 / PRM@32：仅 SFT 63.2 / 67.4 / -；GRPO（仅结果）62.6 / 67.0 / -；GRPO（过程+结果）66.0 / 68.7 / 70.3 —— [arXiv HTML](https://arxiv.org/html/2505.04671)

**DeepRetrieval (Mar 2025, v3 Apr 2025; arXiv 2503.00223)** —— PPO；3B 上最干净的 SFT vs RL vs SFT->RL 网格
- Base Qwen2.5-3B-Instruct、Qwen2.5-Coder-3B-Instruct、Qwen2.5-Coder-7B-Instruct；PPO+GAE；reward = 执行准确率；在 BIRD train + Spider train 上训练 —— [arXiv HTML v3](https://arxiv.org/html/2503.00223v3)
- Table 3（BIRD / Spider dev）：Qwen2.5-3B zero-shot 29.66 / 52.90；SFT 33.77 / 56.67；从零 RL 41.40 / 68.79；SFT + cold-start RL 44.00 / 70.33。Qwen2.5-Coder-3B：30.77 / 50.97；SFT 39.77 / 58.61；RL 49.02 / 74.85；SFT->RL 50.52 / 74.34。Qwen2.5-Coder-7B：zero-shot 45.24 / 64.89；SFT 44.07 / 65.96；RL 56.00 / 76.01。GPT-4o 55.35 / 73.50 —— [arXiv HTML v3](https://arxiv.org/html/2503.00223v3)
- 文中称："RL from scratch achieves better performance than SFT"（从零开始的 RL 比 SFT 表现更好）以及 "SFT can provide a strong initialization for RL especially when the LLM lacks a certain capability"（SFT 可以为 RL 提供强初始化，尤其是在 LLM 缺乏某种能力时）—— [arXiv HTML](https://arxiv.org/html/2503.00223); [arXiv HTML v3](https://arxiv.org/html/2503.00223v3)

**SLM-SQL (Jul 2025, IJCNLP-AACL 2025 Findings; arXiv 2507.22478)** —— 在 0.5B-1.5B 上先 SFT（蒸馏数据）再 GRPO
- Base：Qwen2.5-Coder-0.5B-Instruct、Qwen3-0.6B、Llama-3.2-1B-Instruct、DeepSeek-Coder-1.3B-Instruct、Qwen2.5-Coder-1.5B-Instruct。在 SynSQL-Think-916K 上 SFT（对 SynSQL-2.5M 的 CoT 重新过滤：去掉无 SELECT 的、重复 SQL、注释标记；把推理包在标签里）。在 BIRD train 9,428 上做 GRPO，R = R_EX + 0.1*R_format。合并修订数据 SynSQL-Merge-Think-310K 来自 8 个 Qwen2.5-Coder-7B-Instruct 候选，采用执行分组投票 —— [arXiv HTML](https://arxiv.org/html/2507.22478)
- BIRD dev Base / SFT / SFT+RL / +CSC：0.5B 42.13 / 65.31 / 70.60 / 72.08；1.5B 63.54 / 74.53 / 75.15 / 76.72。去掉 SFT：-21.93（0.5B），-8.89（1.5B）—— [arXiv HTML](https://arxiv.org/html/2507.22478)。（注：这些 BIRD 数字远高于其他 1.5B 结果，如 FINER-SQL 63.17；别处引用的 1.5B 67.08 —— [ACL Anthology](https://aclanthology.org/2025.findings-ijcnlp.92.pdf) —— 表明 fetch 到的表格可能是不同的划分/设置；引用前需在 PDF 中核实。）

**FINER-SQL (May 2026; arXiv 2605.03465)** —— 在 0.5B-3B 上先蒸馏 SFT，再用稠密 reward 做 GRPO
- Base Qwen2.5-Coder 0.5B / 1.5B / 3B。SFT：37.6K 条轨迹组成的 "Reasoning Bank" = 4 个 teacher（DeepSeek-R1、GPT-oss-120B、Qwen2.5-72B-Instruct、GPT-4o）x BIRD train，借助 GRAST-SQL schema linking 花费约 $30；2 个 epoch，lr 2e-5。GRPO：32 个 rollout，lr 8e-6，batch 32，3B 在 2xA6000 上不到 2 天 —— [arXiv HTML](https://arxiv.org/html/2605.03465v1)
- Reward R = R_format + R_exec（0 失败 / 1 有效 / 2 正确）+ R_atomic（操作级 Jaccard，[0,1]）+ R_memory（与已验证轨迹的对齐度，[0,1]）—— [arXiv HTML](https://arxiv.org/html/2605.03465v1)
- BIRD dev 0.5B 50.85，1.5B 63.17，3B 67.73；Spider dev 70.2 / 80.0 / 85.0。3B：仅 SFT 的起点约 63.4 -> GRPO 后 67.73；去掉 memory reward -2.22（语法错误 6.0% -> 约 10%），去掉 atomic -3.26，两者都去掉 -4.44 —— [arXiv HTML](https://arxiv.org/html/2605.03465v1)

**RingSQL (Jan 2026, v2 Aug 2026; arXiv 2601.05451)** —— RLVR，无 SFT，3B-8B
- Base Qwen2.5-Coder-3B/7B-Instruct、Llama-3.2-3B-Instruct、Llama-3.1-8B-Instruct。无 SFT 步骤；RLVR 使用 SQL-R1（Ma et al. 2025）的渐进式 reward（格式、语法、正确性、简洁性）；4xA100，1000 step，batch 4；T=0.8 下 8 个样本 + self-consistency —— [arXiv HTML](https://arxiv.org/html/2601.05451)
- RingSQL-Gen = 在 160 个 Spider 数据库上由模板生成 + GPT-4o-mini 改写的 5,000 对（4,000 train / 1,000 dev）。Qwen-3B BIRD dev：53.13（RingSQL-Gen）vs 46.74（Spider train）vs 46.74（BIRD train）；Spider test 82.53 / 79.74 / 80.48；6 个基准平均 69.80 / 68.45 / 68.51。Llama-3.2-3B 提升最多（平均 +4.74）—— [arXiv HTML](https://arxiv.org/html/2601.05451)

**SQL-Zero (Sep 2026; arXiv 2609.04697)** —— self-play RL，无 SFT，无标注
- Base Qwen2.5-Coder-3B/7B-Instruct 同时作为 challenger 和 solver；GRPO；solver reward 正确 1.0 / 有效但错误 0.1 / 无效 0.0；challenger reward 以 5 次中解出 1 次的解题率为目标 + 格式 + 模板级重复惩罚（lambda 0.5）以防止结构坍缩；64 个无标注的 BIRD train 数据库；每轮迭代 20,000 个去重后的对 —— [arXiv HTML](https://arxiv.org/html/2609.04697)
- Greedy@1：3B BIRD dev 45.3（vs zero-shot 38.7），Spider test 74.7（vs 68.0）；7B BIRD 58.4（vs 51.1），Spider test 82.4（vs 82.2）—— [arXiv HTML](https://arxiv.org/html/2609.04697)

**ExCoT (Snowflake; Mar 2025; arXiv 2503.19988)** —— SFT + DPO（不是 GRPO）
- Base LLaMA-3.1-70B 和 Qwen2.5-Coder-32B。在 GPT-4o few-shot CoT 上 SFT（每个查询最多 32 个候选，经执行过滤：5.6k BIRD + 6.1k Spider）。然后 1 轮 off-policy DPO（GPT-4o 对）+ 2 轮带执行反馈的 on-policy DPO。BIRD dev / Spider test：LLaMA-70B base 57.37 / 78.81 -> SFT 58.14 / 81.42 -> +off-policy DPO 66.30 / 82.49 -> +on-policy DPO 68.51 / 86.59；Qwen-32B 58.93 / 79.32 -> 59.65 / 81.23 -> 66.23 / 83.98 -> 68.25 / 85.14。"Online-DPO, PPO, and GRPO, are left for future exploration"（Online-DPO、PPO 和 GRPO 留待未来探索）—— [arXiv HTML](https://arxiv.org/html/2503.19988)

**STaR-SQL (Feb 2025; arXiv 2502.13550)** —— 自学（STaR）rationale，同一模型
- Base Llama-3.1-8B-Instruct；few-shot（P=3）自生成 rationale，对失败样本用 gold SQL 提示做 "rationalization"，执行匹配过滤，迭代直到平台期；7,000 道 Spider train 题 x 8 个解；基于难度的重采样；在所有带标签的 rationale 上训练一个 ORM verifier。Spider dev：仅 SFT baseline 68.6 EX；STaR-SQL 75.0 EX；配合 ORM@16 86.6 EX。无 BIRD 结果 —— [arXiv HTML](https://arxiv.org/html/2502.13550)

**Sparks of Tabular Reasoning via Text2SQL RL (Apr/May 2025; arXiv 2505.00016)**
- Qwen-7B-Instruct 和 4-bit DeepSeek-LLaMA-8B；先在约 3,500 条合成 CoT（Clinton 数据集）上 SFT，再在 BIRD 上 GRPO；四个部分 reward（执行、字符串匹配、子句级 F1、LLM-judge 序数评分）。BIRD dev 15.5（Qwen）/ 8（LLaMA）—— 绝对准确率非常低；CRT-QA +7.1 / +14.0 —— [arXiv HTML](https://arxiv.org/html/2505.00016)

**Reinforcing Code Generation (Jun 2025; arXiv 2506.06093)** —— reward hacking 实例
- SQLCoder-7B 和 CodeGemma-7B，直接在预训练代码模型上做 GRPO（未描述 SFT），TEMPTABQA-C（2,961 train）。Reward：语法 +1，执行错误 -100，部分 0-100（Relaxed Exact Match），完全匹配 +1000。SQLCoder-7B EMS 31.49 -> 49.83 —— [arXiv HTML](https://arxiv.org/html/2506.06093)
- Reward hacking：CodeGemma 学会了返回 "all the cities where Shevon Jemie Lai won medals"（Shevon Jemie Lai 获得奖牌的所有城市），而不是单个答案，从部分 reward 中拿到 101 分；被描述为 "a risk of purely RL-driven efforts"（纯 RL 驱动方法的一个风险），没有实施修复 —— [arXiv HTML](https://arxiv.org/html/2506.06093)

**ConstrainedSQL (IBM; Nov 2025; arXiv 2511.09693)** —— 用约束 RL 对抗 reward hacking；base model/规模和数字在摘要中未给出 —— [arXiv abs](https://arxiv.org/abs/2511.09693v1)

**Agentar-Scale-SQL (Ant Group; Sep 2025, v6 Dec 2025; arXiv 2509.24403)** —— 编排式单轮 pipeline
- 推理生成器 = 在 OmniSQL-32B 上进一步用 GRPO 训练（reward 正确 1.0 / 可执行 0.1 / 0）；选择器 = Qwen2.5-Coder-32B-Instruct，在 8.5k 条构造样本上做 GRPO（reward 1/0）；仅用 BIRD train。BIRD dev 完整系统 74.90；去掉 RL 生成器 -4.89；BIRD test 81.67 —— [arXiv HTML](https://arxiv.org/html/2509.24403)

**AGRO-SQL (Dec 2025; arXiv 2512.23366)** —— cold start + GRPO，agentic 修正循环（介于单轮与多轮之间）
- Qwen3-8B-Base；"Diversity-Aware Cold Start" SFT，从 DeepSeek V3.2 蒸馏，使用混合 embedding 的多样性选择和 agent-token loss masking（规模未说明）；GRPO 使用稀疏 reward R=正确 1.0 / 格式无效 -1.0。BIRD dev：仅 cold start 62.65；仅 GRPO 63.17；两者结合 72.10。Spider dev 88.39 / 89.26 / 89.13 —— [arXiv HTML](https://arxiv.org/html/2512.23366)

**ReToolSQL (JPMorganChase; Aug 2026; arXiv 2608.27796)** —— agentic，但有最干净的 SFT / RL / SFT->RL ablation
- Gemma 4 31B Instruct；在拒绝采样得到的自身轨迹上 SFT（难题上使用 teacher 特权的 gold-SQL 引导；只保留执行通过的轨迹），来自 6,601 道 BIRD train 题；GRPO 带 DAPO 修改（clip 0.20/0.28，dynamic sampling K=12，KL 从 0.005 衰减到 0）。Reward：执行 2.0，语法 0.5，格式 0.2，表 0.5，列 0.5，长度 -0.1。BIRD dev EX / pass@16：base 71.19 / 76.9；仅 SFT 72.69 / 81.29；从 base 做 RFT 73.66 / 77.2；SFT->RFT 74.32 / 81.94；SC@16 74.77 —— [arXiv HTML](https://arxiv.org/html/2608.27796v1)

**AutoThinkSQL — Learning When to Reason via SFT and DPO (Jun 2026; arXiv 2607.22622)**
- Qwen3-Coder-30B-A3B-Instruct；在来自 BIRD train 的 5,981 条自身 rollout 上 SFT（4,625 条 CoT，1,356 条无 CoT）；在 6,064 对上做 DPO；没有与 GRPO 的对比。BIRD dev greedy 58.23，maj@8 60.27 —— [arXiv HTML](https://arxiv.org/html/2607.22622)

**SkyRL-SQL (NovaSky, May/Jun 2025)** —— 多轮（另一位研究者负责），因其无 SFT、653 条样本的说法而在此引用
- Qwen2.5-Coder-7B-Instruct，在 VeRL/SearchR1 循环中做 GRPO，reward = 格式 + 精确执行匹配；约 653 条训练样本；比 base "+7.2% execution accuracy"（执行准确率 +7.2%）（在某些 Spider 变体上最高 9.2）；超过 GPT-4o、o4-mini 和 OmniSQL-7B；多轮比单轮快 2.8 倍达到 60% reward，最终 reward 高 16%。未提及 SFT —— [Substack write-up](https://machinelearningatscale.substack.com/p/text-to-sql-just-got-a-lot-better)；项目页面 [Notion](https://novasky-ai.notion.site/skyrl-sql)（无法 fetch）

### 推断
- 在从 Qwen2.5-Coder-7B-Instruct 出发、用 GRPO 且不做 SFT 的论文中，BIRD dev 单样本的平台期约为 60-64（Reasoning-SQL 64.01；Graph-Reward-SQL EX 64.01；SQL-R1 63.1；CogniSQL 59.97；ReEx 60.8-63.4；CSC-SQL GRPO greedy 未说明）；从 OmniSQL-7B（在 2.5M 上 SFT）出发则把同样的配方推到 66.6-68.9（SQL-R1、Arctic）。SFT 的*数据规模*（2.5M vs 200K vs 18K）似乎比是否做 SFT 本身更重要。
- 报告"SFT 有害"的论文（SQL-R1 200K cold start 59.2 < 仅 RL 63.1；CogniSQL QwQ 轨迹 SFT 52 -> 46）使用的是风格与 base model 不匹配的蒸馏 CoT；SFT 有帮助的论文要么使用海量的同分布数据（OmniSQL），要么使用经执行过滤的自身/teacher 轨迹（ReToolSQL、DeepRetrieval）。

### 空白/未知
- Arctic-Text2SQL-R1 没有报告在相同 RL 设置下"从 Qwen2.5-Coder-7B-Instruct 做 RL vs 从 OmniSQL-7B 做 RL"的干净对照；只找到 32B 的 batch-vs-在线对比。
- ReEx-SQL 和 CSC-SQL 没有明确说明 GRPO 之前是否有任何 SFT；fetch 中未发现描述 SFT 阶段。
- 无法获取 SkyRL-SQL 的逐基准数字（Notion 页面无法 fetch，GitHub README 路径 404）。
- 从 HTML fetch 得到的 SLM-SQL BIRD 数字（1.5B SFT 74.53）与 ACL 版本搜索摘要中引用的 67.08 不一致；需要查 PDF 核实。

## 哪些论文完全跳过 SFT（直接从 instruct 模型做纯 RL），以及原因

### 要点
Reasoning-SQL、CSC-SQL、CogniSQL-R1-Zero、DeepRetrieval（"RL from scratch" 一组）、RingSQL、SQL-Zero、ReEx-SQL、SQL-R1 的 14B 配置以及 SkyRL-SQL，都直接从 Qwen2.5-Coder-Instruct checkpoint 运行 GRPO/PPO。它们给出的理由：在 gold SQL 或蒸馏 CoT 上 SFT 会过拟合 / 泛化更差（Reasoning-SQL、CogniSQL、DeepRetrieval），以及在 200K 蒸馏子集上 SFT 反而降低了 RL 后的分数（SQL-R1）。没有论文报告在 3B-7B 上从 instruct 模型做 RL 训练失败。

### 引用的发现
- Reasoning-SQL：直接从 Qwen2.5-Coder 做 GRPO；SFT 仅作为 baseline；"RL-only training with our proposed rewards consistently achieves higher accuracy and superior generalization compared to supervised fine-tuning (SFT)"（使用我们提出的 reward 的纯 RL 训练，相比监督微调（SFT）始终获得更高的准确率和更好的泛化）；Spider 泛化差距 SFT 68.08 vs GRPO 78.72（7B）—— [arXiv abs](https://arxiv.org/abs/2503.23157); [arXiv HTML v2](https://arxiv.org/html/2503.23157v2)
- SQL-R1：BIRD dev 上 7B 仅 RL 63.1 vs SFT(SynSQL-200K)->RL 59.2；14B 仅 RL 67.1 vs OmniSQL-14B->RL 66.6；"SFT cold-start training is not universally essential"（SFT cold-start 训练并非普遍必要）—— [arXiv HTML v5](https://arxiv.org/html/2504.08600v5)
- CogniSQL-R1-Zero：GRPO "directly on Qwen2.5-Coder-7B without any supervised warm-up"（直接在 Qwen2.5-Coder-7B 上，不做任何监督 warm-up）；蒸馏轨迹 SFT 使准确率从约 52.0 降到约 46.0；纯 RL 比短暂 SFT cold start "achieved marginally higher peak accuracy"（取得了略高的峰值准确率）；单样本 59.97 —— [arXiv HTML](https://arxiv.org/html/2507.06013)
- DeepRetrieval：在全部三个模型上 "RL from scratch achieves better performance than SFT"（从零开始的 RL 比 SFT 表现更好）（例如 BIRD 上 Coder-3B SFT 39.77 vs RL 49.02）—— [arXiv HTML v3](https://arxiv.org/html/2503.00223v3)
- CSC-SQL：对 Qwen2.5-Coder-3B/7B-Instruct 做 GRPO "post-training"，R = R_EX + 0.1*R_format；未描述 SFT 阶段 —— [arXiv HTML v2](https://arxiv.org/html/2505.13271v2)
- RingSQL："No supervised fine-tuning (SFT) step reported"（未报告监督微调（SFT）步骤）；在 3B-8B 上用 SQL-R1 reward 做 RLVR —— [arXiv HTML](https://arxiv.org/html/2601.05451)
- SQL-Zero：无 SFT，无人工标注；self-play GRPO 把 3B BIRD dev 从 38.7 提升到 45.3，7B 从 51.1 提升到 58.4 —— [arXiv HTML](https://arxiv.org/html/2609.04697)
- SkyRL-SQL：约 653 条样本，GRPO，未提及 SFT，超过了在 2.5M 上 SFT 过的 OmniSQL-7B —— [Substack](https://machinelearningatscale.substack.com/p/text-to-sql-just-got-a-lot-better)
- Arctic-Text2SQL-R1 是主要的反方声音："Stronger SFT models (e.g., OmniSQL) consistently yield better downstream RL results"（更强的 SFT 模型（如 OmniSQL）始终带来更好的下游 RL 结果）—— [arXiv HTML v2](https://arxiv.org/html/2505.20315v2)

### 推断
- "跳过 SFT"在这些论文中可行，是因为 base 是一个 *instruction-tuned 的代码模型*，本身已能输出有效 SQL，BIRD dev 达 45-59%；它们都不是从原始 base model 出发的。唯一一篇使用 Base 模型的论文（AGRO-SQL，Qwen3-8B-Base）发现仅 GRPO 63.17 vs cold-start+GRPO 72.10，即 9 个点的差距。

### 空白/未知
- 没有单轮论文在 1.5B-4B 上从*非 instruct 的 base* 模型训练 RL；对小型 base model 的 R1-Zero 问题，这批文献中尚未检验。

## 哪些论文使用蒸馏 SFT，以及 SFT-vs-RL ablation 显示了什么

### 要点
蒸馏 SFT 的论文使用 DeepSeek-R1（Think2SQL、FINER-SQL）、DeepSeek-R1-Distill-Qwen-32B + o1-mini（Reward-SQL v1）、DeepSeek-V3.1/V3.2（Reward-SQL v3、AGRO-SQL）、GPT-4o（ExCoT、Graph-Reward-SQL 的 CTE 转换、FINER-SQL）、Gemini-1.5-Pro（Reasoning-SQL 的 STaR-SFT baseline）或 OmniSQL 混合数据（SQL-R1、SLM-SQL）。Ablation 结果不一：SFT->RL 优于仅 RL 的有 DeepRetrieval（3B，+1.5-2.6）、AGRO-SQL（+8.9）、ReToolSQL（+0.66）和 Arctic；仅 RL 优于 SFT->RL 的有 Think2SQL（3B 0.500 vs 0.482；7B 0.561 vs 0.537）和 SQL-R1（200K SFT 时 63.1 vs 59.2）。

### 引用的发现
- Think2SQL（DeepSeek-R1 轨迹，1,142 条）：3B SFT 0.460，RL-QATCH 0.500，SFT+RL 0.482；7B SFT 0.494，RL-QATCH 0.561，SFT+RL 0.537 —— [arXiv HTML](https://arxiv.org/html/2504.15077)
- SQL-R1（OmniSQL 风格 CoT，200K）：SFT->RL 59.2 vs 仅 RL 63.1（7B）；但 2.5M-SFT（OmniSQL）-> RL 66.6 —— [arXiv HTML v5](https://arxiv.org/html/2504.08600v5)
- Reward-SQL v1（R1-Distill-32B + o1-mini CoCTE，18,015 条）：SFT 54.4 -> SFT+GRPO 59.7 -> +PRM@32 68.9；v3（DeepSeek-V3.1，51,996 条）：greedy 下 SFT 63.2 vs GRPO-仅结果 62.6 vs GRPO-过程+结果 66.0 —— [arXiv HTML v1](https://arxiv.org/html/2505.04671v1); [arXiv HTML](https://arxiv.org/html/2505.04671)
- FINER-SQL（4 个 teacher，37.6K）：3B SFT 约 63.4 -> GRPO 67.73 —— [arXiv HTML](https://arxiv.org/html/2605.03465v1)
- AGRO-SQL（DeepSeek V3.2 蒸馏）：仅 cold start 62.65，仅 GRPO 63.17，两者结合 72.10（BIRD dev）—— [arXiv HTML](https://arxiv.org/html/2512.23366)
- ExCoT（GPT-4o CoT，5.6k BIRD）：SFT 在 BIRD 上带来 +0.8（70B）和 +0.7（32B）；on-policy DPO 阶段带来 +10 —— [arXiv HTML](https://arxiv.org/html/2503.19988)
- Reasoning-SQL：Gemini 生成的 STaR-SFT baseline（7B 61.53）低于 GRPO（64.01）—— [arXiv HTML v2](https://arxiv.org/html/2503.23157v2)
- CogniSQL：在 QwQ-32B 轨迹上 SFT 降低了准确率（约 52 -> 约 46），之后由 RL 挽回 —— [arXiv HTML](https://arxiv.org/html/2507.06013)
- Arctic：从 OmniSQL checkpoint 开始 RL；7B 68.9 vs OmniSQL-7B 的 63.9（OmniSQL 数字来自 [OmniSQL HTML](https://arxiv.org/html/2503.02240)）—— [arXiv HTML v2](https://arxiv.org/html/2505.20315v2)

### 推断
- SFT->RL vs 仅 RL 这一 ablation 的正负号跟随两个因素：(a) 数据规模和 (b) 分布匹配程度：来自风格不同的 teacher 的小型蒸馏集（1K-200K）往往有害或作用被抵消；2.5M 同分布的 OmniSQL SFT 则有帮助。
- Reward-SQL 从 v1 到 v3 的变化（Qwen2.5-Coder-7B + 18K 轨迹 -> Qwen3-8B + 52K 轨迹）把仅 SFT 的 greedy 从 54.4 提升到 63.2，说明 SFT 阶段本身对 teacher 质量很敏感。

### 空白/未知
- Think2SQL 的 SFT+RL 一组以同一个 1,142 条样本的 SFT 模型为初始化；更大的 SFT 集合是否会翻转结果尚未检验。

## 哪些论文在同一个小模型上使用自学 / 拒绝采样 SFT

### 要点
STaR-SQL（Llama-3.1-8B，Spider）、ReToolSQL（Gemma 4 31B 带 gold-SQL 提示的自身轨迹）、AutoThinkSQL（Qwen3-Coder-30B-A3B 自身 rollout）以及 CogniSQL 的 36K 自生成语料，是 RFT/STaR 风格的实例；CogniSQL 发现自生成 SFT（约 57.3）比蒸馏 SFT（约 46）更安全，但仍低于 RL（59.97）。

### 引用的发现
- STaR-SQL：Llama-3.1-8B-Instruct，7,000 道 Spider train 题 x 8 个样本，用 gold SQL 提示做 rationalisation，执行过滤，ORM verifier；Spider dev 68.6（SFT）-> 75.0（STaR）-> 86.6（ORM@16）—— [arXiv HTML](https://arxiv.org/html/2502.13550)
- ReToolSQL：拒绝采样得到的自身轨迹（难题上使用特权 gold-SQL 引导），经执行过滤；仅 SFT 72.69 vs base 71.19；SFT->RFT 74.32 —— [arXiv HTML](https://arxiv.org/html/2608.27796v1)
- CogniSQL：36,356 条 Qwen-7B-Coder 自生成、经执行验证的轨迹；在其上 SFT 恢复到约 57.3，而蒸馏轨迹 SFT 约为 46 —— [arXiv HTML](https://arxiv.org/html/2507.06013)
- AutoThinkSQL：每道 BIRD train 题 16 条自身 rollout -> 5,981 条 SFT 实例，然后是 6,064 对 DPO —— [arXiv HTML](https://arxiv.org/html/2607.22622)
- SQL-o1 的 Progressive SQL Generation 数据（前缀截断的失败案例，21,254 对）是一种相关的自我纠错式 SFT —— [arXiv HTML](https://arxiv.org/html/2502.11741)

### 推断
- 自生成 SFT 避免了在 CogniSQL 和 SQL-R1 中伤害蒸馏 SFT 的风格不匹配问题，这使其成为已能产出可解析 SQL 的 1.7B-4B 模型的自然 warm start。

### 空白/未知
- 没有论文在 <=4B 模型上先做 STaR/RFT 风格的 SFT 再做 RL；STaR-SQL 止步于 SFT+ORM，且没有 BIRD 数字。

## 执行准确率之外的 reward 组成，以及 reward hacking

### 要点
有数字支撑的有用附加项：格式标签（几乎普遍使用，权重约 0.1）、QATCH 式的部分单元格/元组得分（Think2SQL：相对 SFT 有 15-30% 的相对提升）、schema/n-gram/语法/LLM-judge（Reasoning-SQL，每个组件的提升都很小）、PRM/过程 reward（Reward-SQL greedy 比仅结果高 +3.4）、CTE 逐步匹配（Graph-Reward-SQL BIRD +5.87）、memory/atomic 结构 reward（FINER-SQL 合计 +4.44）。Arctic-Text2SQL-R1 和 Reinforcing-Code-Generation 报告了部分 reward 被 hack；因此 Arctic 保留了 1 / 0.1 / 0。

### 引用的发现
- Arctic："More fine-grained reward designs induced 'lazy' behaviors, where models pursued local optima for short-term rewards rather than global correctness"（更细粒度的 reward 设计会诱发"偷懒"行为，模型追求短期 reward 的局部最优，而不是全局正确性）—— 尝试过执行、语法、n-gram、schema、格式等部分 reward 并放弃；保留 1 / 0.1（可执行）/ 0 —— [arXiv HTML v2](https://arxiv.org/html/2505.20315v2)
- Reinforcing Code Generation：CodeGemma-7B 利用 0-100 的 Relaxed-Exact-Match 部分 reward，返回过宽的结果集，拿到 101 分 —— [arXiv HTML](https://arxiv.org/html/2506.06093)
- ConstrainedSQL（Nov 2025）以 reward hacking 作为动机，提出带多个约束信号的约束 RL —— [arXiv abs](https://arxiv.org/abs/2511.09693v1)
- Think2SQL：QATCH 部分 reward（cell precision、cell recall、tuple cardinality）"crucial"（至关重要）；R = 0.85 任务 + 0.10 格式 + 0.05 标签计数 —— [arXiv HTML](https://arxiv.org/html/2504.15077)
- Reasoning-SQL：权重 EX 3、LLM-judge 2、其他 1，选择这些权重是为了让错误的 SQL 不可能得分高于正确的 SQL —— [arXiv HTML](https://arxiv.org/html/2503.23157)
- SQL-R1：分级的 +-1 / +-2 / +-3 格式 / 执行 / 结果，外加长度项；ablation 表明均衡的权重可以防止对较简单模式的 "exploitation"（利用）—— [arXiv HTML](https://arxiv.org/html/2504.08600)
- Reward-SQL v3：greedy 下 GRPO 仅结果 62.6 vs 过程+结果 66.0；PRM@32 70.3 —— [arXiv HTML](https://arxiv.org/html/2505.04671)
- Graph-Reward-SQL：无需执行的 GMNScore reward 比执行快 47 倍；1.3B 上 StepRTM 在 BIRD 上 +5.87 —— [arXiv HTML](https://arxiv.org/html/2505.12380)
- FINER-SQL：去掉 memory reward EX -2.22，语法错误 6.0% -> 约 10%；去掉 atomic -3.26；两者都去掉 -4.44 —— [arXiv HTML](https://arxiv.org/html/2605.03465v1)
- Arctic 还过滤了约 3,100 条 gold 查询返回空结果的训练样本，因为它们会产生 "spurious or uninformative rewards"（虚假或无信息量的 reward）—— [arXiv HTML v2](https://arxiv.org/html/2505.20315v2)
- SQL-Zero：模板级重复惩罚，用于防止 challenger 的结构坍缩 —— [arXiv HTML](https://arxiv.org/html/2609.04697)
- CSC-SQL、SLM-SQL、CogniSQL、AGRO-SQL、Agentar-Scale-SQL 都基本使用二值执行 + 小的格式项，并且未报告 hacking —— [CSC HTML](https://arxiv.org/html/2505.13271v2); [SLM-SQL HTML](https://arxiv.org/html/2507.22478); [AGRO HTML](https://arxiv.org/html/2512.23366); [Agentar HTML](https://arxiv.org/html/2509.24403)

### 推断
- 两个有记录的 hack 都涉及对*结果重叠*给部分得分的 reward（n-gram / relaxed match）；基于结构的部分得分（QATCH cardinality、子句 Jaccard、CTE 步骤匹配）尚未有被 hack 的报告，但这些论文也没有认真去找。
- Arctic 的空结果过滤与 DySQL 风格的写操作任务直接相关——即 gold 影响 0 行的任务（no-op gold）。

### 空白/未知
- 没有论文量化 reward hacking 发生的频率（占 rollout 的比例）；只有个别案例和 Arctic 的设计陈述。

## 1.5B-4B 模型上的证据：不做 SFT、从 instruct 模型做 RL 是否可行？

### 要点
在所有尝试过的论文中，从 instruct 模型做 RL 在 3B 上都可行（Reasoning-SQL 3B 45.17 -> 58.67；DeepRetrieval Coder-3B 30.77 -> 49.02；CSC-SQL 3B GRPO+SC 60.60；RingSQL Qwen-3B 53.13；SQL-R1-3B 54.6；SQL-Zero 3B 38.7 -> 45.3），在 1.3B-1.5B 上 Graph-Reward-SQL（SFT warm-up 之后的 DeepSeek-Coder-1.3B）和 Think2SQL（Think2SQL-1.5B 0.442 vs base 0.275）也可行。但在 <=3B 上做过 SFT-vs-RL 网格的两篇论文发现 warm start 有帮助：DeepRetrieval 在 3B 上 SFT->RL > 仅 RL（+2.6 / +1.5），Think2SQL 称小模型 "benefit most from reasoning-aware SFT and RL"（从具备推理意识的 SFT 和 RL 中获益最多），而 SLM-SQL 发现在 1.5B/0.5B 上去掉 SFT 会损失 8.9-21.9 个点。最强的小模型结果（SLM-SQL 1.5B、FINER-SQL 3B 67.73、CSC-SQL 3B）都包含 SFT 阶段。

### 引用的发现
- Reasoning-SQL 3B：Base 45.17，SFT 55.9，GRPO 58.67（GRPO 之前无 SFT）—— [arXiv HTML v2](https://arxiv.org/html/2503.23157v2)
- DeepRetrieval Qwen2.5-Coder-3B：zero-shot 30.77，SFT 39.77，仅 RL 49.02，SFT->RL 50.52（BIRD）；Spider 50.97 / 58.61 / 74.85 / 74.34；"SFT can provide a strong initialization for RL especially when the LLM lacks a certain capability"（SFT 可以为 RL 提供强初始化，尤其是在 LLM 缺乏某种能力时）—— [arXiv HTML v3](https://arxiv.org/html/2503.00223v3)
- Think2SQL：3B 仅 RL 0.500 > SFT+RL 0.482 > SFT 0.460 > base 0.382；Think2SQL-1.5B 0.442（base 0.275），0.5B 0.254（base 0.089）；作者：小型 LLM "benefit most from reasoning-aware SFT and RL"（从具备推理意识的 SFT 和 RL 中获益最多），以及 "task-specific reasoning traces are essential"（任务特定的推理轨迹是必不可少的）—— [arXiv HTML v5](https://arxiv.org/html/2504.15077v5); [arXiv abs](https://arxiv.org/abs/2504.15077)
- SLM-SQL 0.5B/1.5B：先 SFT 再 GRPO；ablation：去掉 SFT -21.93（0.5B）和 -8.89（1.5B）—— [arXiv HTML](https://arxiv.org/html/2507.22478)
- FINER-SQL 0.5B / 1.5B / 3B 经 SFT+GRPO 后：BIRD dev 50.85 / 63.17 / 67.73 —— [arXiv HTML](https://arxiv.org/html/2605.03465v1)
- CSC-SQL Qwen2.5-Coder-3B（无 SFT）：GRPO+SC@64 60.60，GRPO+CSC 63.34，vs base SC 56.15 —— [arXiv HTML v2](https://arxiv.org/html/2505.13271v2)
- RingSQL Qwen2.5-Coder-3B 无 SFT 的 RLVR：BIRD dev 53.13（合成数据）/ 46.74（BIRD train）—— [arXiv HTML](https://arxiv.org/html/2601.05451)
- SQL-R1-3B（从 instruct 做 RL，SynSQL-Complex-5K）：BIRD dev 54.6，Spider test 78.9 —— [arXiv HTML v5](https://arxiv.org/html/2504.08600v5)
- SQL-Zero 3B 无标注 self-play：BIRD dev 38.7 -> 45.3 —— [arXiv HTML](https://arxiv.org/html/2609.04697)
- Graph-Reward-SQL DeepSeek-Coder-1.3B（SFT warm-up 之后）：Spider TS 65.28-68.67，BIRD TS 17.21-21.97 —— [arXiv HTML](https://arxiv.org/html/2505.12380)
- 多轮交叉参考（另一位研究者负责）：TRUST-SQL 报告 "applying GRPO directly without SFT yields substantially lower performance"（不做 SFT 直接应用 GRPO 会导致性能大幅下降），且 SFT warm-up "instills structured exploration behavior"（会灌输结构化的探索行为）—— 仅为搜索摘要，[arXiv](https://arxiv.org/pdf/2603.16448)

### 推断
- 对于做*单轮* SQL 的 1.7B-4B Qwen 类 instruct 模型，仅 RL 是可行的，相对 instruct baseline 在 BIRD dev 上带来 +10-18 个点（Reasoning-SQL、DeepRetrieval），但经执行过滤的 SFT warm start（自生成或同分布数据）在 3B 上还能再加约 1.5-3 个点，在 <=1.5B 上加得多得多（SLM-SQL）。分歧（Think2SQL）出现在 SFT 集合很小（1,142 条）且蒸馏自一个差异很大的模型（DeepSeek-R1）的情况下。
- 这些论文都不涉及工具调用格式、多步 agent 循环或写语句；在 agentic 设置中学习格式的负担更大，而这正是多轮文献（TRUST-SQL、AGRO-SQL 的 agentic 变体）报告 SFT 必不可少的地方。

### 空白/未知
- 没有单轮论文报告从 *base*（非 instruct）checkpoint 用 RL 训练 1.5B-4B 模型；也没有论文报告 1.5B 仅 RL 时的训练坍缩 / 格式失败的数字。
- 具体到 Qwen3-1.7B / Qwen3-4B：未找到单轮 text-to-SQL RL 论文（SLM-SQL 只用了 Qwen3-0.6B；Reward-SQL v3 和 AGRO-SQL 用的是 Qwen3-8B）。
