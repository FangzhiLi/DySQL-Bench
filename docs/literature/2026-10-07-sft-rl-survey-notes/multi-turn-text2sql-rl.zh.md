# 基于 RL 的多轮 / agentic text-to-SQL（2025-01 至 2026-10）：训练配方、SFT cold start、reward

范围说明：只收录 policy 在多个回合中与数据库交互（执行、观察、重试）和/或与（模拟）用户交互的系统。单轮推理 RL（SQL-R1、Reasoning-SQL、Graph-Reward-SQL、CogniSQL-R1-Zero、RLVR-on-verified-data）留给另一位研究者，仅在某篇多轮论文把它们用作 baseline 时提及。月份为根据 arXiv ID（YYMM）推断的 arXiv 首次提交月份，除非页面另有注明日期。

调研中记录的一处更正：第一遍 PDF 摘要报告 MTSQL-R1 Qwen3-1.7B 的分数为 "20.2 -> 26.8 EX"。对同一 PDF（arXiv 2510.12831v3，Table 2）做 `pdftotext` 导出后显示，1.7B 各行在 CoSQL 上为 73.0 -> 77.3 EX；下文使用核实后的表格数值。

## 关键问题 1：MTSQL-R1（多轮 text-to-SQL，CoSQL/SParC，1.7B 与 4B checkpoint）—— 精确配方

### 要点
MTSQL-R1（Amazon / ACL 2026，arXiv 2025 年 10 月）把 Qwen3-1.7B 和 Qwen3-4B 训练成一个 propose -> execute -> verify -> refine 的 agent，作用于一个 SQLite DB 外加一个 "dialogue memory"（对话记忆）工具，每个问题最多 4 次工具交互。它严格采用先 SFT 后 RL：先做 3 轮 self-taught 拒绝采样 SFT（19,416 条 CoSQL / 29,710 条 SParC trajectory，来自模型自己的正确 rollout，无外部 teacher），再用 GRPO 训练，reward 为 outcome（EX+EM）加上逐动作的 process reward。没有 SFT warm start 时，未训练的 1.7B agent 在长程（long-horizon）格式下在 CoSQL 上只有 22.6% EX；SFT+RL 后达到 77.3% EX（4B：79.9%）。论文未报告长程格式下仅 RL（无 SFT）的 ablation。

### 引用的发现
- 论文："MTSQL-R1: Towards Long-Horizon Multi-Turn Text-to-SQL via Agentic Training"，arXiv 2510.12831（2025 年 10 月；v3 日期为 2026 年 4 月），ACL 2026 长文；Amazon Science 有对应的发表页面 —— [arXiv HTML](https://arxiv.org/html/2510.12831)；[ACL Anthology](https://aclanthology.org/2026.acl-long.1563/)；[Amazon Science](https://www.amazon.science/publications/mtsql-r1-towards-long-horizon-multi-turn-text-to-sql-via-agentic-training)
- 基座模型：以 Qwen3-1.7B 和 Qwen3-4B 为 backbone；在 LLaMA3.2-3B-Instruct 上做泛化检验；在单节点 8 张 NVIDIA A100 GPU 上训练 —— [arXiv HTML](https://arxiv.org/html/2510.12831)
- 环境 / MDP：state = 对话历史、schema、当前问题、对话记忆、中间 SQL、累积的执行观察；离散动作为 PROPOSE、EXECUTE（在 DB 上运行 SQL，返回行/错误）、E-VERIFY（判断执行结果）、M-VERIFY（对照先前问题/SQL/约束的记忆检查一致性）、SELF-CORRECT、FINALIZE。通过 verl multi-turn 暴露两个工具：`exec_sql` 和 `memory_retrieve`（"retrieving the historical questions and ground-truth SQL in this dialogue"（检索本对话中的历史问题和 ground-truth SQL））。verl 配置 `multi_turn.max_turns: 4  # Important Max-turns`；论文原文："maximum interaction between agent and tools is set to 4"（agent 与工具之间的最大交互次数设为 4）—— [arXiv HTML](https://arxiv.org/html/2510.12831)；[arXiv PDF v3, Appendix C](https://arxiv.org/pdf/2510.12831v3)
- 没有模拟用户："用户"回合就是 CoSQL/SParC 中固定的对话问题；在标准设置下，记忆工具提供先前回合的 gold SQL。一个鲁棒性变体用模型自己预测的 SQL 作为先前回合历史：Direct RL 75.2（gold 先前历史）-> 71.2（预测的先前历史），而 MTSQL-R1 为 79.9 -> 76.5 EX（CoSQL，Table 6）—— [arXiv PDF v3](https://arxiv.org/pdf/2510.12831v3)
- SFT 阶段（"Self-Taught Warm-Start SFT"）：用长程格式对所有训练问题 prompt 基座模型，每个问题 20 个 rollout，temperature 0.7，只保留最终 SQL 正确的 trajectory；难度感知的拒绝采样对简单题最多保留 2 条短 trajectory（<=2 次交互），对难题保留 3 条较长 trajectory（>=2 次交互）的聚类代表；重复 3 轮，每一轮用新微调的模型重新采样。覆盖率（Table 9）：CoSQL 9,337 个训练样本 -> 第 1/2/3 轮后覆盖 6,311 / 7,409 / 7,555，最终 19,416 条 trajectory；SParC 11,905 -> 9,132 / 10,103 / 10,285，最终 29,710 条 trajectory。未使用外部 teacher 模型 —— [arXiv PDF v3, Table 9](https://arxiv.org/pdf/2510.12831v3)；[arXiv HTML](https://arxiv.org/html/2510.12831)
- SFT 超参数：LlamaFactory + DeepSpeed ZeRO-3 offload，全参数，lr 5e-6 cosine，每卡 batch 2；loss masking 只监督动作/SQL token，屏蔽指令和工具输出 —— [arXiv HTML](https://arxiv.org/html/2510.12831)
- RL 阶段：通过 verl 0.4.1 跑 GRPO，SGLang 做 rollout；train batch 256；`rollout.n=5`；lr 1e-6；最大 prompt 4,000 token，最大 response 8,000 token；`use_kl_in_reward=False`；curriculum 按 easy -> hard 划分，并丢弃 SFT 模型已经 20/20 解出的样本；配置中列有 `trainer.total_epochs=60` —— [arXiv PDF v3, Appendix C.2](https://arxiv.org/pdf/2510.12831v3)；[GitHub taichengguo/MTSQL-R1](https://github.com/taichengguo/MTSQL-R1)
- Reward：R_all = w1 * (R_EX + R_EM) + w2 * (R_Propose/Self-Correct + R_E-Verify + R_M-Verify)。Outcome：执行结果与 gold 一致则 R_EX = 1，SQL 完全匹配则 R_EM = 1。Process：PROPOSE/SELF-CORRECT = 预测 SQL 与 gold SQL 在 SELECT/WHERE/JOIN/GROUP/ORDER 上的子句级 F1 平均值；E-VERIFY = 一个查找表，按（执行 ok/null/error）x（判定 pass/fail）取值 {0, 0.1, 1}；M-VERIFY = 判定 pass 时取平均子句 F1，否则取 1 - 平均 F1。"weights are selected via grid search on a small validation set"（权重通过在一个小验证集上做网格搜索选出）—— 未给出 w1、w2 的具体值 —— [arXiv HTML](https://arxiv.org/html/2510.12831)；[arXiv PDF v3](https://arxiv.org/pdf/2510.12831v3)
- 训练任务来源：CoSQL（3,007 段对话 / 15,598 个问题）和 SParC（4,298 / 12,726）的训练集，约 200 个数据库 —— [arXiv HTML](https://arxiv.org/html/2510.12831)
- 主要结果，Table 2，域内问题级 EX / EM（CoSQL dev，SParC dev），Qwen3-1.7B：仅 prompting 的 Qwen3-1.7B 59.9/49.3，61.5/46.5；短程 SFT 68.1/59.3，74.3/69.2；短程 Direct RL 72.8/59.0，72.1/65.5；未训练的长程基座 agent 22.6/16.3，23.9/17.8；仅 warm-start SFT 第 1 轮 69.9/57.6，70.6/62.0；第 2 轮 72.2/60.5，72.3/63.0；第 3 轮 73.0/62.1，72.8/65.7；SFT + RL（仅 outcome）76.6/62.7，76.2/66.1；SFT + RL（outcome + process）77.3/63.5，76.2/66.1 —— [arXiv PDF v3, Table 2](https://arxiv.org/pdf/2510.12831v3)
- Table 2，Qwen3-4B：仅 prompting 64.0/50.7，62.9/49.8；短程 SFT 73.1/64.8，78.3/71.5；短程 Direct RL 75.2/64.8，75.8/66.5；未训练的长程基座 agent 60.3/45.6，57.6/44.1；warm-start SFT 第 3 轮 75.2/63.0，75.1/65.6；SFT + RL（仅 outcome）79.1/64.5，78.1/67.8；SFT + RL（outcome + process）79.9/65.2，79.0/68.7 —— [arXiv PDF v3, Table 2](https://arxiv.org/pdf/2510.12831v3)
- 同表中的前沿模型 prompting baseline：GPT-4.1 60.9/32.1（CoSQL），61.8/33.3（SParC）；OpenAI-o3 59.8/29.1，57.0/30.3；DeepSeek-R1 58.5/36.0，57.6/37.2；Qwen3-32B 66.8/54.4，74.0/53.4；LangGraph SQL agent 69.9/32.5，69.6/34.6 —— [arXiv PDF v3, Table 2](https://arxiv.org/pdf/2510.12831v3)
- LLaMA3.2-3B-Instruct（Table 11，CoSQL / SParC EX）：基座 22.9 / 24.4；短程 RL 70.4 / 70.9；MTSQL-R1 长程 74.8 / 75.2 —— [arXiv PDF v3, Table 11](https://arxiv.org/pdf/2510.12831v3)
- 工具 ablation（Table 3，Qwen3-4B SFT+RL，CoSQL）：完整版 79.9 EX；去掉 Execute 工具 74.6；去掉 Memory-Verify 工具 77.8 —— [arXiv PDF v3, Table 3](https://arxiv.org/pdf/2510.12831v3)
- Reward ablation（Table 10，Qwen3-4B CoSQL，均值 +- 标准差）：仅 outcome 79.1 +- 0.15 EX；+ verify reward 79.7；+ propose/correction reward 79.4；全部 79.9 +- 0.11 —— [arXiv PDF v3, Table 10](https://arxiv.org/pdf/2510.12831v3)
- 小模型观察："Result 5: Small LLMs struggle to follow long-horizon function-calling instructions (Table 2)"（结果 5：小 LLM 难以遵循长程 function-calling 指令（Table 2））；在长程能力分析中："(iii) The 1.7B base model is much weaker than the 4B model primarily..."（(iii) 1.7B 基座模型比 4B 模型弱得多，主要是因为……）—— [arXiv PDF v3](https://arxiv.org/pdf/2510.12831v3)
- 长度限制：输出上限为 2,000 token 时 "performance drops drastically ... the agent often cannot complete its full reasoning process, so we must extract intermediate SQL"（性能急剧下降……agent 常常无法完成完整推理过程，因此我们必须抽取中间 SQL）；8,000 token 上限被认为是剩余 6 个失败案例的原因；每条查询最大延迟约 28 s —— [arXiv PDF v3, Appendix D](https://arxiv.org/pdf/2510.12831v3)；[arXiv HTML](https://arxiv.org/html/2510.12831)
- 关于 pipeline："A frequent industry pipeline is to RL-post-train a very large model and then use it to generate SFT/distillation data ... We have not explored such pipelines due to computational constraints ... our self-taught SFT-then-RL pipeline trains stably even when the initial model lacks frontier-level reasoning"（业界常见的 pipeline 是对一个超大模型做 RL 后训练，再用它生成 SFT/蒸馏数据……由于算力限制我们没有探索这类 pipeline……我们的 self-taught 先 SFT 后 RL pipeline 即使在初始模型缺乏前沿级推理能力时也能稳定训练）—— [arXiv PDF v3, Appendix C.3](https://arxiv.org/pdf/2510.12831v3)
- 代码/checkpoint：GitHub 仓库在 Hugging Face 上提供 CoSQL-1.7B、SParC-1.7B、CoSQL-4B、SParC-4B checkpoint；SFT 用 LLaMA-Factory 0.9.3，RL 用 verl 0.4.1，reward 文件为 `text2sql_process.py`；数据库位于 `database/cosql/` 和 `database/sparc/` —— [GitHub](https://github.com/taichengguo/MTSQL-R1)

### 推断
- MTSQL-R1 的 SFT cold start 是纯自蒸馏（从 policy 自身拒绝采样），所以它的 1.7B 配方不依赖更强的 teacher；代价是第 1 轮只覆盖约 68%（CoSQL）/ 约 77%（SParC）的训练问题，三轮后增长到约 81% / 约 86%。
- 未训练的 1.7B 长程 agent 只有 22.6% EX，而同一模型在普通 prompting 下有 59.9%，说明 SFT 之前的瓶颈是格式/工具协议，而非 SQL 能力；这是论文中最有力的证据，表明 1.7B 模型在多轮 RL 之前需要 warm start。
- 在 4B 上 process reward 相比仅 outcome 只提升 +0.7 EX（79.1 -> 79.9），在 1.7B 上也是 +0.7（76.6 -> 77.3）；大部分收益来自长程任务形式加 outcome GRPO。

### 空白/未知
- 未给出 reward 权重 w1/w2 的具体值、实际运行的 RL 步数，以及 curriculum 过滤后的 RL 训练 prompt 数量。
- 未报告长程格式下的仅 RL（无 warm start）运行；"Direct RL" 各行是短程单轮 RL。
- 在抽取到的文本中未找到 1.7B/4B 模型的交互级（IM）指标。

## 关键问题 2：SkyRL-SQL（NovaSky）—— 约 650 个样本，无 SFT

### 要点
SkyRL-SQL（博客 2025 年 5 月 20 日）直接对 Qwen2.5-Coder-7B-Instruct 做 RL 训练（文中未描述任何 SFT 阶段），采用 GRPO 风格的多轮 RL，训练数据为取自 SynSQL-2.5M/Spider 数据库的 653 个 prompt，最多 5 回合，14 个 epoch，reward 只在终止时给出（结果集匹配 +1，错误 0，solution 格式错误 -1）。NovaSky 声称该 7B 模型在若干 Spider/BIRD 划分上胜过 GPT-4o、o4-mini 和 OmniSQL-7B（在 2.5M 样本上 SFT），相对基座 "up to 8.7%"（最多 8.7%）的提升；各 benchmark 的具体数字在一个无法抓取的 Notion 页面上。

### 引用的发现
- 博客文章 "SkyRL-SQL: Simple and Data Efficient Multi-Turn RL for Text2SQL"，发布于 2025-05-20（页面更新于 2026-03-14）；完整说明是 SkyRL README 中链接的一个 Notion 页面 —— [NovaSky blog index](https://novasky-ai.github.io/posts/skyrl-sql/)；[SkyRL GitHub README](https://github.com/NovaSky-AI/SkyRL)
- NovaSky 公告："a simple, data-efficient RL pipeline for Text-to-SQL that trains LLMs to interactively probe, refine, and verify SQL queries with a real database ... trained on just ~600 samples, SkyRL-SQL-7B outperforms GPT-4o, o4-mini, and SFT model trained with 2.5M samples"（一个简单、数据高效的 Text-to-SQL RL pipeline，训练 LLM 借助真实数据库交互式地探查、改进和验证 SQL 查询……仅用约 600 个样本训练，SkyRL-SQL-7B 就胜过 GPT-4o、o4-mini 以及用 2.5M 样本训练的 SFT 模型）—— [NovaSky on X](https://x.com/NovaSkyAI/status/1925592895010246863)
- 配方摘要（SkyRL 文档的 recipe 页面，按索引所见）："SkyRL-SQL-7B was trained on top of Qwen2.5-Coder-7B-Instruct with 653 samples, using simple rewards (format + execution), for 5 turns and 14 epochs"（SkyRL-SQL-7B 在 Qwen2.5-Coder-7B-Instruct 基础上用 653 个样本训练，使用简单 reward（格式 + 执行），5 回合、14 个 epoch）；"Using just 653 training samples, SkyRL-SQL-7B can improve accuracy by up to 8.7% compared to the base model, outperforming GPT-4o, o4-mini, and open-source SFT model trained on 2.5 million samples"（仅用 653 个训练样本，SkyRL-SQL-7B 相比基座模型准确率最多提升 8.7%，胜过 GPT-4o、o4-mini 以及在 250 万样本上训练的开源 SFT 模型）—— [SkyRL docs (old readthedocs URL, now redirects)](https://skyrl.readthedocs.io/en/latest/recipes/skyrl-sql.html)；[SkyRL docs recipe](https://docs.skyrl.ai/docs/recipes/skyrl-sql)
- 数据：数据集 `NovaSky-AI/SkyRL-SQL-653-data` 有 654 行（653 训练 + 1 验证），字段为 data_source、prompt、db_id、reward_model、extra_info、synsql；数据库 "from SynSQL-2.5M and Spider, sourced from OmniSQL dataset collections"（来自 SynSQL-2.5M 和 Spider，取自 OmniSQL 的数据集合集）；训练脚本路径 `examples/train/text_to_sql/run_skyrl_sql.sh` —— [HF dataset](https://huggingface.co/datasets/NovaSky-AI/SkyRL-SQL-653-data)；[SkyRL docs recipe](https://docs.skyrl.ai/docs/recipes/skyrl-sql)
- 环境（skyrl-gym `envs/sql/env.py`）：模型输出 `<think>`、`<sql>...</sql>`（通过 `SQLCodeExecutorToolGroup` 在 SQLite 上执行）以及用于结束的 `<solution>...</solution>`；执行结果或错误字符串以 `user` 消息的形式追加；`max_turns` 默认为 5；"No reward for intermediate steps for SQL tasks"（SQL 任务的中间步骤没有 reward）—— [env.py](https://raw.githubusercontent.com/NovaSky-AI/SkyRL/main/skyrl-gym/skyrl_gym/envs/sql/env.py)
- Reward（`envs/sql/utils.py`，`compute_score_single`）：格式检查要求恰好一对 `<solution>`，之前有 `<think>`，且没有嵌套标签，否则 `reward = -1.0`；预测 SQL 和 gold SQL 以 30 s 超时执行，并以 `frozenset(cur.fetchall())` 比较（与顺序无关）；匹配则 `reward = 1.0`，不匹配、执行错误或超时则 `0.0`；没有单独的正向格式 reward，也没有逐回合惩罚 —— [utils.py](https://raw.githubusercontent.com/NovaSky-AI/SkyRL/main/skyrl-gym/skyrl_gym/envs/sql/utils.py)
- 模型卡 `NovaSky-AI/SkyRL-SQL-7B`："No model card"（无模型卡），safetensors BF16，标注为 8B 参数（Qwen2 架构）—— [HF model](https://huggingface.co/NovaSky-AI/SkyRL-SQL-7B)
- 作为 baseline 的独立使用：SQL-Trail 引用了 SkyRL 风格的多轮 RL，并报告了自己的 Qwen2.5-Coder-7B 多轮结果（见关键问题 4）—— [SQL-Trail ACL PDF](https://aclanthology.org/2026.acl-long.1677.pdf)

### 推断
- 文档/X 帖子中没有任何 SFT 步骤，且对比对象是 "SFT model trained on 2.5M samples"（用 2.5M 样本训练的 SFT 模型，即 OmniSQL），说明这是从 instruct 模型直接 RL、没有 cold start；Qwen2.5-Coder-7B-Instruct 基座已经能足够好地遵循标签格式，-1 的格式惩罚就够用了。
- Reward 完全是终止时的稀疏 reward；文档中的 "format + execution"（格式 + 执行）对应代码中的 -1 / 0 / +1 方案，而不是单独塑形的格式奖励。

### 空白/未知
- 各 benchmark 的数字（Spider-dev/test/DK/Realistic/Syn、BIRD-dev）以及 653 个样本的选取标准在 Notion 页面 (https://novasky-ai.notion.site/skyrl-sql) 上，抓取器渲染出来是空的；X 帖子串和文档只给出 "up to 8.7%"（最多 8.7%）和定性的说法。
- RL 算法名称、learning rate、batch size 和 GPU 数量均无法获取（在猜测的路径上训练脚本 README 返回 404）。

## 关键问题 3：DySQL-Bench —— 它训练了什么吗？

### 要点
没有。DySQL-Bench（arXiv 2025 年 10 月，ACL Findings 2026）只做评测：在 13 个 BIRD/Spider 2 数据库上自动合成 1,072 个任务，由一个三角色循环（Qwen2.5-72B-Instruct 模拟用户、被测模型、SQLite）评判，最多 30 个对话回合，使用 Pass^k 指标；它评测现成模型，不包含任何 SFT 或 RL。

### 引用的发现
- 论文："Rethinking Text-to-SQL: Dynamic Multi-turn SQL Interaction for Real-world Database Exploration"，arXiv 2510.26495（2025 年 10 月；v2 2025 年 11 月 13 日），ACL 2026 Findings；代码位于 github.com/Aurora-slz/DySQL-Bench —— [arXiv](https://arxiv.org/abs/2510.26495)；[ACL Anthology](https://aclanthology.org/2026.findings-acl.1654/)；[GitHub](https://github.com/Aurora-slz/DySQL-Bench)
- "The paper does not train or fine-tune any models"（该论文没有训练或微调任何模型）（在 HTML 中未找到任何关于对新模型进行训练、微调或 RL 的句子）—— [arXiv HTML](https://arxiv.org/html/2510.26495)
- 评测框架：模拟用户 = 带任务特定指令的 Qwen2.5-72B-Instruct；被评测模型接收 DDL schema；可执行的 SQLite 数据库；最大对话回合数 eta = 30；采样 temperature 0.6，top_p 0.95，top_k 20 —— [arXiv HTML](https://arxiv.org/html/2510.26495)
- 规模与构建：13 个领域，1,072 个任务；两阶段 pipeline（数据库 -> 层次树结构；LLM 生成任务 + 验证过滤）；由 10 位领域专家做人工验证，标注者间一致率 >99.5% —— [arXiv HTML](https://arxiv.org/html/2510.26495)
- 指标 / 结果：Pass^k，k = 1, 3, 5；GPT-4o "58.34% overall accuracy and 23.81% on the Pass^5 metric"（总体准确率 58.34%，Pass^5 指标上 23.81%）；被评测模型：Qwen2.5-Max、Qwen2.5-72B-Instruct、Llama-3.1-70B-Instruct、OmniSQL-32B、Qwen3-32B、DeepSeek-V3、GPT-4o、Gemini-2.5-Flash —— [arXiv HTML](https://arxiv.org/html/2510.26495)；[arXiv abstract](https://arxiv.org/abs/2510.26495)
- 任务需要状态操作："not just information retrieval (SELECT) but continuous state manipulation (INSERT, UPDATE, DELETE)"（不仅是信息检索（SELECT），还包括持续的状态操作（INSERT、UPDATE、DELETE））—— [arXiv abstract](https://arxiv.org/abs/2510.26495)
- 搜索在 DySQL-Bench 上做 RL 训练的后续工作，没有找到相关结果（只有通用的 SWE-agent RL 和 ReToolSQL 的结果）—— [search context: ReToolSQL](https://arxiv.org/pdf/2608.27796)

### 推断
- DySQL-Bench 的三角色循环（LLM 用户 + policy + 带写操作的 DB）与 tau-bench 风格的 RL 环境形态相同，但截至 2026 年 10 月没有已发表的工作把它用作训练环境；它的 30 回合预算和 Qwen2.5-72B 用户是仅有的可直接照搬的具体环境参数。

### 空白/未知
- 未抽取开源模型（如 Qwen3-32B、OmniSQL-32B）各自的 Pass^1/3/5；未记录论文的错误分类。
- 没有关于作者打算如何把该 benchmark 用于训练的任何内容。

## 关键问题 4：BIRD-Interact 及在其上训练的 agent；Spider 2.0 agent；其他交互式/对话式系统（Interactive-T2S、T2S-Agent、TIDE-Bench、Agentar）

### 要点
BIRD-Interact（2025 年 10 月）没有训练任何模型；找到的唯一以它为目标的训练系统是 "Learning to Retrieve"（2026 年 6 月），它保持 GPT-5 作为 policy，只用 PPO 训练 Qwen3-4B 的记忆检索选择器（episode reward = 任务成功；turn reward = 一个 7B PRM）。RL 训练的开源 agent 在 Spider 2.0 上的数字很少：SQL-ASTRA（OmniSQL-7B，Spider 2.0 17.7%）和 SERL-SQL（32B，Spider 2.0-SQLite 26.78%）。除 MTSQL-R1 外，2025-26 年没有论文在 CoSQL/SParC 上做 RL 训练；TIDE-Bench 和 Interactive-T2S 只做评测/prompting；没有找到任何在 text-to-SQL 中通过 RL 训练 agent 向模拟用户提澄清问题的系统。

### 引用的发现
- BIRD-Interact（arXiv 2510.05318，2025 年 10 月；v3 2026 年 3 月 24 日）：600 个任务的 Full 版（11,796 次交互）和 300 个任务的 Lite 版；函数驱动的用户模拟器（测试了 GPT-4o 和 Gemini-2.0-Flash）把请求路由到 AMB（标注的歧义）/ LOC（可从 gold SQL AST 定位的细节）/ UNA（拒绝）；c-Interact = 对话式，每个子任务一次 debug 机会；a-Interact = ReAct，9 种动作，预算 B = 6 + 2*m_amb + 2*lambda_pat（patience 默认为 3）；评分 = 在线 Success Rate，离线归一化 reward 主任务 70% / 后续任务 30% —— [arXiv HTML](https://arxiv.org/html/2510.05318)；[arXiv abstract](https://arxiv.org/abs/2510.05318)
- BIRD-Interact-Full 结果（c-Interact SR / a-Interact SR / 归一化 reward）：GPT-5 14.50 / 29.17 / 25.52；Gemini-2.5-Pro 25.00 / 20.33 / 20.92；Claude-Sonnet-4 22.33 / 27.83 / 23.28；o3-mini 24.00 / 19.83 / 16.43；Qwen3-Coder-480B 22.00 / 13.33 / 10.58；DeepSeek-V3.1 18.50 / 17.17 / 13.47。摘要/Lite 数字："GPT-5 completes only 8.67% of tasks in c-Interact and 17.00% in a-Interact"（GPT-5 在 c-Interact 中只完成 8.67% 的任务，在 a-Interact 中 17.00%）—— [arXiv HTML](https://arxiv.org/html/2510.05318)；[arXiv abstract](https://arxiv.org/abs/2510.05318)
- BIRD-Interact 的训练状况："No models were trained/fine-tuned in this paper"（本文没有训练/微调任何模型）；未来工作提到一个 "post-trained, human-aligned local user simulator"（经过后训练、与人类对齐的本地用户模拟器）。模拟器泄漏：函数驱动设计把 baseline 在不可回答查询上的失败率从 54-67.4% 降到 2.7%；与人类的 Pearson 相关 0.84，朴素模拟器为 0.61 —— [arXiv HTML](https://arxiv.org/html/2510.05318)
- Learning to Retrieve: Dual-Level Long-Term Memory for Text-to-SQL Agents（arXiv 2606.00547，按 ID 为 2026 年 6 月）：policy = GPT-5（low reasoning）；用户模拟器 = GPT-4o；PRM = 在 5,346 个 teacher 标注的 state-memory 对上 SFT 的 DeepSeek-R1-Distill-Qwen-7B；episode 级和 turn 级检索选择器 = LoRA Qwen3-4B-Instruct-2507，用 PPO 训练，4 个 epoch，batch 128，lr 1e-7；reward：终止时的任务成功（episode）和稠密的 PRM 效用（turn）。BIRD-Interact phase-1 成功率 33.01%，无记忆为 23.33%；phase-2 22.17% vs 13.17%；平均回合数 7.84 vs 8.93；迁移到 Spider2-Snow 69.29% —— [arXiv HTML](https://arxiv.org/html/2606.00547)
- RL 训练的开源模型在 Spider 2.0 上：SQL-ASTRA OmniSQL-7B 在 Spider 2.0 上 17.7%，二值 reward GRPO 约 15% —— [arXiv HTML](https://arxiv.org/html/2603.16161v1)；SERL-SQL-32B 在 Spider 2.0-SQLite 上 26.78% —— [arXiv HTML](https://arxiv.org/html/2608.00485v3)
- FlexSQL（arXiv 2605.02815，按 ID 为 2026 年 5 月）：基于 gpt-oss-120b/20b 的纯 prompting agent，有六个工具（GetSchema、GetTableCol、GetColValues、FindRows、SQLExecutor、PythonExecutor）；无 SFT 或 RL；Spider2-Snow 55.15% Pass@1（120b），59.74% Maj@8，65.44% Maj@16；Spider2-SQLite 57.78% Pass@1 —— [arXiv HTML](https://arxiv.org/html/2605.02815)
- 针对 Spider 2.0 搜索 RL 训练的 agent，只找到单轮 RL 工作（RingSQL 合成数据；"Human-Level Text-to-SQL via RL on Verified Data"，2026 年 3 月，Qwen3-235B/Kimi-K2.6，单轮，2.5k 个经验证的 BIRD-Platinum 实例，Spider2 提升 "0.6-16%"）—— [arXiv 2603.20004](https://arxiv.org/abs/2603.20004)；[search](https://arxiv.org/pdf/2601.05451)
- Interactive-T2S（arXiv 2408.11062，2024 年 8 月，在时间窗之外）：带四个通用工具的 prompting 框架；在 BIRD-dev 上 "state-of-the-art results with only two exemplars"（只用两个示例就达到 state-of-the-art 结果）；无训练 —— [arXiv PDF](https://arxiv.org/pdf/2408.11062)
- TIDE-Bench，"Evaluating LLMs on Conversational Text-to-SQL under Chain Ambiguity and Intent Drift"（arXiv 2608.29543，2026 年 8 月）：来自 514 条 BIRD 锚点 SQL 的 1,542 个样本；评测 12 个 LLM；摘要中未报告训练 —— [arXiv](https://arxiv.org/abs/2608.29543)
- T2S-Agent，"Text-to-SQL Agent: An Iterative Question Rewriting Framework Based on Reinforcement Learning"（ACM DL）：RL 应用于问题改写阶段，agent "progressively approximating the user's true intent through dynamic interaction"（通过动态交互逐步逼近用户的真实意图）（搜索摘要片段）；ACM 页面返回 HTTP 403 —— [ACM DL](https://dl.acm.org/doi/10.1145/3811238.3811548)
- Agentar-Scale-SQL（arXiv 2509.24403，2025 年 9 月）：test-time scaling 框架，其 "Intrinsic Reasoning SQL Generator"（内在推理 SQL 生成器）经 GRPO 做 RL 增强，外加迭代改进和锦标赛式选择；BIRD dev 74.90% EX，test 81.67%；RL 组件是单轮的 —— [arXiv PDF](https://arxiv.org/pdf/2509.24403)
- 搜索 "SQL-Agent RL"、"DB-Agent" RL 以及用 RL 训练的 tau-bench 风格 DB 写操作 agent，只得到通用工具使用 agent 的 RL（MUA-RL，2508.18669），不在本范围内 —— [MUA-RL](https://arxiv.org/pdf/2508.18669)

### 推断
- 截至 2026 年 10 月，没有论文在 BIRD-Interact 或 DySQL-Bench 的用户在环（user-in-the-loop）环境中 RL 训练 policy；最接近的是围绕冻结的前沿 policy 训练辅助组件（记忆选择器）。
- CoSQL/SParC 意义上的对话式 text-to-SQL RL 基本上是只有一篇论文的领域（MTSQL-R1）；较新的"对话式" benchmark（TIDE-Bench、BIRD-Interact c-mode）还没有训练过的 baseline。

### 空白/未知
- 无法读取 T2S-Agent 的细节（发表时间、模型、reward、模拟用户）（403）。
- 没有找到任何 "Interactive-T2S" 式 RL 扩展的证据，也没有找到以 "DB-Agent" 或 "SQL-Agent RL" 为名的论文。
- Spider-Agent / ReFoRCE 的 RL 变体：未找到；上面的 Spider 2.0 数字来自在 BIRD/Spider-1 上训练、zero-shot 评测的模型。

## 关键问题 5：2025-26 年其他多轮/agentic text-to-SQL RL 系统 —— 配方与 SFT 处理方式（SQL-Trail、TRUST-SQL、MTIR-SQL、MARS-SQL、SQL-ASTRA、SERL-SQL、ReToolSQL、DualSQL、AGRO-SQL、ReEx-SQL）

### 要点
另外找到十个多轮 RL 系统，全部属于 GRPO 家族，全部以最终执行匹配作为 reward，大多把 episode 限制在 5-10 个工具回合。它们在 cold start 上清晰分为两类：先蒸馏 SFT 再 RL（SQL-Trail：1,000 条 Claude-Sonnet-3.7 trajectory；TRUST-SQL：由 GPT-4.1-mini/GPT-4o-mini/DeepSeek-R1 在 9,217 个 SynSQL 问题上生成的 70,970 条 trajectory；AGRO-SQL：DeepSeek-V3.2；ReToolSQL：带特权信息的自身 trace；DualSQL：3,755 个 BIRD 样本），以及直接从 instruct 模型做 RL（SkyRL-SQL、MTIR-SQL、MARS-SQL、SQL-ASTRA、SERL-SQL、ReEx-SQL）。对此做过 ablation 的三篇论文（SQL-Trail、TRUST-SQL、ReToolSQL）都发现 SFT->RL > 仅 RL > 仅 SFT，差距在 14B 时缩小，在 3B 时反转。

### 引用的发现

SQL-Trail（Amazon，arXiv 2601.17699，2026 年 1 月；ACL 2026 长文）
- 基座：Qwen2.5-Coder-Instruct 3B/7B/14B；两阶段 SFT -> RL；trajectory 上限 10 回合；G = 6 个 rollout，temperature 1.0；观察结果以 `<observation>` 标签返回，带列名 —— [ACL PDF](https://aclanthology.org/2026.acl-long.1677.pdf)；[arXiv HTML](https://arxiv.org/html/2601.17699)
- SFT 数据："sample 3,000 Spider-train questions, generate multi-turn trajectories with Claude-Sonnet-3.7 using our agent template, and retain 1,000 trajectories with correct final SQL, prioritized toward medium/hard difficulty"（采样 3,000 个 Spider-train 问题，用我们的 agent 模板通过 Claude-Sonnet-3.7 生成多轮 trajectory，保留 1,000 条最终 SQL 正确的 trajectory，优先选中等/困难难度）；SFT batch 128，2 个 epoch，lr 1e-5 —— [ACL PDF, Sec. 4.2, App. A.5](https://aclanthology.org/2026.acl-long.1677.pdf)
- RL 数据：1,027 个 prompt = 700 个"难但可解"（pass@6 非退化）+ 327 个探索集（127 个 SFT 后失败样本，100 个 SynSQL pass@6 = 0，100 个特难 Spider pass@6 = 0）；训练集共 1,873 个样本；RL batch 128，lr 1e-6，top-p 0.99，在第 108 步评测；带 "clip-higher" 的 GRPO —— [ACL PDF](https://aclanthology.org/2026.acl-long.1677.pdf)；[arXiv HTML](https://arxiv.org/html/2601.17699)
- Reward：R = 5*r_exec + 2*r_turns + r_schema + r_bigram + r_syntax + r_format；r_turns = 1 当（simple 且 t <= 2）或（medium 且 t <= 3）或（hard/extra 且 r_exec = 1 且 t < T），否则为 0；r_schema = 表/列名上的 Jaccard；r_bigram = SQL 2-gram 的 Jaccard；r_syntax = 可执行；r_format = 标签合规 —— [ACL PDF, Eq. 4 and 7](https://aclanthology.org/2026.acl-long.1677.pdf)
- 主要结果（Table 1，EX greedy/majority；Spider-dev、Spider-test、BIRD-dev）：SQL-Trail-3B 76.3/83.1，77.7/84.3，50.1/55.1；SQL-Trail-7B 85.2/86.8，86.0/87.6，60.1/64.2；SQL-Trail-14B 85.1/87.1，86.8/88.5，63.6/66.7；baseline：Sonnet-3.7 单次生成 78.3/78.9，82.0/83.2，58.5/60.1；Sonnet-3.7 作为未调优的多轮 agent 77.2/77.9，81.9/82.0，60.0/60.8；Qwen2.5-Coder-7B-Instruct 单次生成 73.4/77.1，82.2/85.6，50.9/61.3；SQL-R1-7B 81.9/84.5，83.5/86.1，58.9/63.1；OmniSQL-7B 81.2/81.6，87.9/88.9，63.9/66.1 —— [ACL PDF, Table 1](https://aclanthology.org/2026.acl-long.1677.pdf)
- Cold-start ablation（Table 7，EX Spider-dev / Spider-test / BIRD-dev）：3B 仅 SFT 83.1/82.9/55.7，仅 RL 84.6/83.1/55.2，SFT+RL 84.6/84.3/55.2；7B 仅 SFT 83.6/83.5/58.7，仅 RL 85.8/86.8/61.7，SFT+RL 86.5/87.0/64.2；14B 仅 SFT 83.3/86.1/64.8，仅 RL 86.9/87.2/65.4，SFT+RL 87.1/88.5/66.7；"RL with SFT cold-start yields the highest performance, surpassing both the RL model trained without cold-start and the SFT-only baseline"（带 SFT cold start 的 RL 性能最高，超过无 cold start 训练的 RL 模型和仅 SFT 的 baseline）—— [ACL PDF, Table 7](https://aclanthology.org/2026.acl-long.1677.pdf)
- 单次生成 vs 多轮 RL，数据/超参数相同（Table 2，majority EX）：单次生成 82.8 / 85.1 / 56.3；多轮 84.5 / 86.1 / 59.3 —— [ACL PDF, Table 2](https://aclanthology.org/2026.acl-long.1677.pdf)
- Reward ablation（Table 6，7B，BIRD-dev greedy/majority，平均回合数）：全部 reward 60.1/64.2（2.26 回合）；去掉 turns 59.3/63.2（3.19 回合，标准差 2.12）；去掉 n-gram 57.2/61.6；去掉 schema 58.5/62.6；去掉 syntax 59.1/63.8；去掉 format 59.8/62.9；去掉 execution 57.9/62.8；仅 SFT 后 57.8/58.7（2.53 回合）；未调优的 Qwen2.5-Coder-7B agent 49.1/51.2，6.44 回合；未调优的 Sonnet agent 60.0/60.8，4.24 回合 —— [ACL PDF, Table 6](https://aclanthology.org/2026.acl-long.1677.pdf)
- 退化行为："both Sonnet and base Qwen generate overly long trajectories ... Sonnet wastes turns probing the schema, while base Qwen repeatedly revises flawed SQL due to weaker syntax"（Sonnet 和基座 Qwen 都生成过长的 trajectory……Sonnet 把回合浪费在探查 schema 上，而基座 Qwen 由于语法较弱反复修改有缺陷的 SQL）；"SFT improves syntax accuracy and shortens trajectories, but schema linking remains difficult; RL further improves schema identification"（SFT 提高语法准确率并缩短 trajectory，但 schema linking 仍然困难；RL 进一步改进 schema 识别）—— [ACL PDF, Sec. 5.2](https://aclanthology.org/2026.acl-long.1677.pdf)
- 数据效率指标：每 1,000 个训练样本带来的 EX 提升（百分点）；SQL-Trail-7B 1.90（Spider-test）/ 4.60（BIRD-dev），SQL-R1-7B 0.26 / 1.6，OmniSQL-7B 0.002 / 0.005；"7-18x higher efficiency"（效率高 7-18 倍）—— [ACL PDF, Table 1](https://aclanthology.org/2026.acl-long.1677.pdf)

TRUST-SQL（arXiv 2603.16448，2026 年 3 月；自称 EMNLP 主会）
- 基座：Qwen3-4B 和 Qwen3-8B；未知 schema 的 POMDP：Explore（元数据查询）-> Propose（确定已验证的 schema K）-> Generate -> Confirm；工具 `execute_sql_query` 作用于 SQLite；训练预算 10 回合（"further increasing to 12 turns causes severe training instability"（进一步增加到 12 回合会导致严重的训练不稳定））；推理时 15 回合用于 majority voting —— [arXiv HTML v1](https://arxiv.org/html/2603.16448v1)
- SFT 数据：9,217 个 SynSQL-2.5M 问题（moderate/complex/highly-complex），由 GPT-4.1-mini、GPT-4o-mini 和 DeepSeek-R1 标注，执行正确且格式合规的才保留：70,970 条 trajectory，其中 61.7%（43,803）来自 GPT-4.1-mini —— [arXiv HTML v1](https://arxiv.org/html/2603.16448v1)
- RL 数据：18,078 个 BIRD+Spider 训练问题 -> 保留 11,642 个（通过率 < 6/8 过滤），每个 8 个 rollout —— [arXiv HTML v1](https://arxiv.org/html/2603.16448v1)
- Dual-Track GRPO：schema 轨道（trajectory 截至 Propose）使用 R_schema，完整轨道使用 R_exec + R_fmt；token 级掩码 advantage（Propose 之后的 token 的 schema advantage 为零）；loss = L_full + lambda * L_schema，lambda = 0.25 —— [arXiv HTML v1](https://arxiv.org/html/2603.16448v1)
- Reward：R_exec 正确 1.0 / 可执行但错误 0.2 / 不可执行 0.0；R_fmt 0.1；R_schema 为二值 schema 匹配，仅在 R_exec = 1.0 时给出 —— [arXiv HTML v1](https://arxiv.org/html/2603.16448v1)
- 结果（greedy / majority）：TRUST-SQL-4B BIRD-dev 64.9/67.2，Spider-test 82.8/85.0，Spider-DK 71.6/73.8，Spider-Syn 74.7/77.3，Spider-Realistic 79.9/82.5；TRUST-SQL-8B BIRD-dev 65.8/67.7，Spider-test 83.9/86.5，Spider-DK 72.1/75.7，Spider-Syn 75.4/77.4，Spider-Realistic 82.1/84.1；不预填 schema 的基座 Qwen3-4B BIRD-dev 29.3%；摘要：在五个 benchmark 上相对基座的平均绝对提升为 30.6（4B）和 16.6（8B）—— [arXiv HTML v1](https://arxiv.org/html/2603.16448v1)；[arXiv abstract](https://arxiv.org/abs/2603.16448)
- SFT/RL ablation（4B，BIRD-dev）：仅 SFT 46.2；仅 RL 59.9；SFT+RL 64.9。仅 RL 会通过 "exhaustively querying all tables in turn one"（在第一回合穷举查询所有表）来 "hack"，把未知 schema 任务退化为全 schema 预填（4.23 次工具调用，有 SFT 时为 3.66）。schema reward 权重过高（lambda = 0.375）使准确率崩溃到 54.2%，平均回合数 7.66（对比 5.64）；朴素混合 schema reward 58.7；纯执行（lambda = 0）60.9；dual-track 64.5 —— [arXiv HTML v1](https://arxiv.org/html/2603.16448v1)

MTIR-SQL（arXiv 2510.25510，2025 年 10 月；ICLR 2026）
- 基座：Qwen3-4B；从基座模型直接仅 RL，未描述 SFT；SQLite 执行返回列名和最多 10 行；最多 N = 6 次工具调用；temperature 0.6；每个 prompt 5 个 rollout —— [arXiv HTML](https://arxiv.org/html/2510.25510)；[ICLR page](https://iclr.cc/virtual/2026/10017469)
- 算法："GRPO-Filter" = 去掉 KL 项的 GRPO 加上 trajectory 过滤（只保留满足预定义标准的 trajectory），以应对不稳定和分布漂移 —— [arXiv HTML](https://arxiv.org/html/2510.25510)
- Reward：格式 +0.1 / -0.1；可执行 +0.1 / -0.1；结果正确 +1 / -1 —— [arXiv HTML](https://arxiv.org/html/2510.25510)
- 数据：BIRD 和 Spider 训练集，按可执行性和低冗余过滤，去掉参考结果为空的样本（未给出数量）—— [arXiv HTML](https://arxiv.org/html/2510.25510)
- 结果：BIRD-dev 64.4%（对比 SQL-R1-7B 63.1%，Qwen2.5-Coder-3B 48.1%）；摘要中 Spider dev 为 84.6%（HTML 抽取结果还列出 dev 82.4 / test 83.4，因此两次抽取的 dev 数字不一致）；去掉执行 reward -3.9 分 —— [arXiv abstract](https://arxiv.org/abs/2510.25510)；[arXiv HTML](https://arxiv.org/html/2510.25510)

MARS-SQL（arXiv 2511.01008，2025 年 11 月；v2 2026 年 5 月）
- 基座：三个 agent（grounding、generation、validation）均用 Qwen2.5-Coder-7B-Instruct；generation agent = 带实时执行的 ReAct 循环，T = 10 回合；GRPO，无 SFT cold start；稀疏 reward 正确 1.0 / 合法但错误 0.0 / 非法 -1.0；validation agent 在约 16k 个自生成的 trajectory 偏好三元组（每个问题 16 个候选）上 SFT，通过 8 轮中 "Yes" token 的概率做选择 —— [arXiv HTML](https://arxiv.org/html/2511.01008)
- 数据：BIRD 训练集过滤 9,428 -> 8,036；所有 agent 合计约 35k 个样本；在 4x H800 上约 13 小时 —— [arXiv HTML](https://arxiv.org/html/2511.01008)
- 结果：BIRD-dev 77.84%，Spider-test 89.75%，Spider-DK 78.13%；仅 generator 66.37%；去掉 validation 68.71%；去掉 grounding 69.75%；用 self-consistency 代替 validator 72.93% —— [arXiv HTML](https://arxiv.org/html/2511.01008)

SQL-ASTRA（arXiv 2603.16161，2026 年 3 月；ACL Findings 2026）
- 基座：Qwen2.5-7B-Instruct（无 cold start）和 OmniSQL-7B（需要一次 "Format-6k" SFT 来学会工具调用格式）；Qwen2.5-Coder 因 "insufficient exploratory capabilities"（探索能力不足）被弃用；最多 3 次工具调用 —— [arXiv HTML](https://arxiv.org/html/2603.16161v1)
- Reward：逐步的 Column-Set Matching Reward（基于列值集合重叠的稠密 [0,1] 值，上限为 alpha ~0.8，只有完全匹配才得 1.0）+ 通过非对称转移矩阵（|R_high->low| > |R_low->high|）得到的 Aggregated Trajectory Reward，用于消除振荡循环；带工具输出掩码的 GRPO —— [arXiv HTML](https://arxiv.org/html/2603.16161v1)
- 数据：过滤后 BIRD 训练集 8,958；结果：BIRD 64.2%，二值 GRPO 为 58.5%（Qwen 7B）；Spider-dev 82.9 vs 79.2；OmniSQL-7B BIRD 69.1 vs 67.4，Spider 2.0 17.7 vs ~15；对称矩阵 60.1；逐步更新 61.3；agentic rollout 的墙钟时间约为单轮的 2 倍 —— [arXiv HTML](https://arxiv.org/html/2603.16161v1)

SERL-SQL（arXiv 2608.00485，2026 年 8 月；v3）
- 基座：Qwen2.5-Coder-Instruct 7B/14B/32B；默认 5 回合；无 SFT cold start；GRPO，trajectory reward +1 / 0 / -1；"selective hindsight distillation"（选择性事后蒸馏）：一个 teacher 在给定执行反馈的条件下对学生 on-policy 的 SQL/工具 token 重新打分，log-prob 差值变为有界的 advantage 权重，只作用于 SQL 和工具动作 token；只在 BIRD 上训练 —— [arXiv HTML](https://arxiv.org/html/2608.00485v3)
- 结果：BIRD-dev 75.55（7B），74.95（14B），76.56（32B）；Spider-test 89.24（7B），89.92（14B），89.78（32B）；Spider 2.0-SQLite 26.78（32B）；ablation：schema grounding -9.5，execution hindsight -3.0，weight clipping -1.8，selective masking -1.5 —— [arXiv HTML](https://arxiv.org/html/2608.00485v3)

ReToolSQL（arXiv 2608.27796，2026 年 8 月）
- 基座：Gemma 4 31B Instruct，在 Gemma 4 E4B 上做 ablation；三个只读工具（`sqlite_query` 仅 SELECT/WITH，5 s 超时；`sqlite_peek` 列分析器；`bm25_search_sqlite` 值搜索）；最多 8 回合 —— [arXiv HTML](https://arxiv.org/html/2608.27796)
- SFT：用 pass@16 识别出难样本的 "all-wrong band"（全错区间）；对这些样本在可特权访问 gold SQL 的条件下生成 teacher trace，对简单/中等样本用自身 trace，全部经执行匹配验证 —— [arXiv HTML](https://arxiv.org/html/2608.27796)
- RL：GRPO，采用 DAPO 风格的非对称 clipping（0.20 / 0.28），dynamic sampling K = 12，工具观察 loss masking，KL 衰减 0.005 -> 0.001 -> 0；reward = 执行匹配 2.0 + 格式 0.2 + 语法 0.5 + 表覆盖 0.5 + 列覆盖 0.5（Jaccard）+ 非空结果 0.1 - 长度惩罚 0.1；数据 = BIRD 训练集 6,601 个问题，1 个 epoch —— [arXiv HTML](https://arxiv.org/html/2608.27796)
- BIRD-dev EX：基座 71.19；仅 SFT 72.69；从基座 RFT 73.66（SC@16 74.12）；SFT->RFT 74.32（SC@16 74.77）；SFT 把难题上的 pass@16 提升到 81.29，RFT 保持在 81.94；E4B 68.45%，RL 提升更大（+3.33，31B 为 +1.95）；仅工具访问 +2.02，仅 RL +0.45，两者结合 +3.97 —— [arXiv HTML](https://arxiv.org/html/2608.27796)

DualSQL（arXiv 2609.18135，2026 年 9 月）
- 基座：Qwen3-4B 和 Qwen3-8B，同一个 backbone 同时扮演 schema-linker（5 回合）和 SQL-generator（10 回合），配有 SQL 执行器、全文搜索和 DB 分析工具；在 3,755 个 BIRD 样本上做 SFT cold start（去掉 2,715 个平凡样本，修正 384 处标注错误）；GRPO，使用 token-mean loss、clip-higher、序列级掩码重要性采样；reward：schema-linking F1、带工具使用奖励的执行匹配、"robust execution match"（REX，鲁棒执行匹配）、长度惩罚；32K token 上限，外加 4K 超长缓冲；针对格式错误的 trajectory 采用 "strict format checking with rollout cutoff and error-focused loss masking"（严格格式检查，配合 rollout 截断和聚焦错误的 loss masking）—— [arXiv HTML](https://arxiv.org/html/2609.18135)
- 结果：DualSQL-4B BIRD-dev EX 68.0%（REX 64.0）；DualSQL-8B BIRD-dev 71.1%，Spider 83.1%；多 agent RL 比单 agent 高 +1.5 EX —— [arXiv HTML](https://arxiv.org/html/2609.18135)

AGRO-SQL（arXiv 2512.23366，2025 年 12 月）
- 基座：Qwen3-8B-Base；多轮 action-feedback 循环（未给出最大回合数）；"Diversity-Aware Cold Start"（多样性感知 cold start）SFT，数据来自 DeepSeek-V3.2 trajectory，按 SQL 动作与推理的混合 embedding 选取（未给出数量）；合成数据只在执行结果与 gold 匹配时保留（"Generation-as-Verification"）；GRPO，reward 正确 1.0 / 格式非法 -1.0，batch 256 x 10 个 rollout，lr 5e-6，temperature 0.7；BIRD 训练集 9,428 —— [arXiv HTML](https://arxiv.org/html/2512.23366)
- 结果：BIRD-dev 72.10%，Spider-dev 89.13%；无 cold-start ablation —— [arXiv HTML](https://arxiv.org/html/2512.23366)

ReEx-SQL（arXiv 2505.12768，2025 年 5 月）
- 基座：Qwen2.5-Coder-7B-Instruct；通过 `<intermediate_sql>` / `<result>` 标签在生成过程中穿插执行，N = 10 次交互；GRPO，无 SFT；组合 reward 权重：格式 2.0，执行 3.0，完全匹配 1.0，实体匹配 1.0，探索 2.0；BIRD-dev 64.9%，Spider-test 86.6%（摘要写的是 88.8%），Spider-Realistic 85.2%；去掉执行 reward 在 BIRD 上 -6.5；基于树的解码使推理时间减少 51.9% —— [arXiv HTML](https://arxiv.org/html/2505.12768)；[arXiv abstract](https://arxiv.org/abs/2505.12768)

### 推断
- 该领域已收敛到训练时 5-10 回合的上限；推得更高的论文（TRUST-SQL 12）报告了不稳定，MTSQL-R1 发现 2,000 token 上限会让长程 agent 失效，而 8,000 基本够用。
- 使用蒸馏 SFT 时，teacher 要么是前沿闭源模型（Claude-Sonnet-3.7、GPT-4.1-mini、DeepSeek-V3.2），要么是带特权 gold SQL 的模型自身（ReToolSQL）或自身拒绝采样（MTSQL-R1）；trajectory 数量从 1,000（SQL-Trail）到 70,970（TRUST-SQL）不等，并且都按最终 SQL 的执行正确性过滤。
- 塑形的辅助 reward（schema Jaccard、n-gram、子句 F1、列集合匹配）一致被报告比二值执行 reward 高 1-6 个 EX 点，但每篇论文都让执行匹配保持为主导项（权重是塑形项的 2-5 倍）。

### 空白/未知
- MTIR-SQL 和 SQL-ASTRA 没有精确给出训练集规模；AGRO-SQL 省略了 SFT trajectory 数量和最大回合数。
- MTIR-SQL 的 Spider-dev 数字分别出现为 84.6（摘要）和 82.4（HTML 抽取）—— 尚未厘清。
- 这些论文都没有使用模拟用户；"多轮"指的是 policy 与 DB 之间的回合。

## 关键问题 6：多轮 SQL 中使用的 reward 设计

### 要点
找到的每个系统都通过执行最终 SQL 并比较结果集来给 reward（SkyRL-SQL 中是与顺序无关的 set/frozenset 相等；其他系统称为"执行匹配"）；没有一个对最终数据库状态给 reward，因为所有训练任务都只有 SELECT。塑形通过以下方式加入：(a) 逐回合/中间信号（MTSQL-R1 的子句 F1 process reward、SQL-ASTRA 的逐步列集合匹配、TRUST-SQL 的 schema 轨道），(b) 效率惩罚（SQL-Trail 的难度感知回合 reward、ReToolSQL 的长度惩罚、DualSQL 的长度惩罚），以及 (c) 格式惩罚（SkyRL-SQL/MARS-SQL/SERL-SQL/AGRO-SQL 中为 -1，MTIR-SQL 中为 +-0.1）。

### 引用的发现
- 结果集匹配，仅终止时给出：SkyRL-SQL 的 `frozenset(cur.fetchall())` 相等，+1 / 0 / -1 格式，"No reward for intermediate steps"（中间步骤没有 reward）—— [utils.py](https://raw.githubusercontent.com/NovaSky-AI/SkyRL/main/skyrl-gym/skyrl_gym/envs/sql/utils.py)；[env.py](https://raw.githubusercontent.com/NovaSky-AI/SkyRL/main/skyrl-gym/skyrl_gym/envs/sql/env.py)；MARS-SQL 1.0 / 0.0 / -1.0 —— [arXiv](https://arxiv.org/html/2511.01008)；SERL-SQL +1 / 0 / -1 —— [arXiv](https://arxiv.org/html/2608.00485v3)；AGRO-SQL 1.0 / -1.0 —— [arXiv](https://arxiv.org/html/2512.23366)
- 分级执行：TRUST-SQL 正确 1.0 / 可执行但错误 0.2 / 不可执行 0.0，外加 0.1 格式和一个以 R_exec = 1 为门控的 schema reward —— [arXiv](https://arxiv.org/html/2603.16448v1)；MTIR-SQL +-0.1 格式，+-0.1 可执行，+-1 结果 —— [arXiv](https://arxiv.org/html/2510.25510)
- 逐动作 process reward：MTSQL-R1 中 PROPOSE/SELF-CORRECT 用子句级 F1，E-VERIFY 用 {0, 0.1, 1} 查找表，M-VERIFY 用 F1 或 1-F1，组合为 w1*(EX+EM) + w2*(process)；ablation 显示在 4B 上 +0.8 EX —— [arXiv](https://arxiv.org/html/2510.12831)；[PDF Table 10](https://arxiv.org/pdf/2510.12831v3)
- 带抗振荡聚合的逐步稠密 reward：SQL-ASTRA 每回合 CSMR 取值于 [0, alpha=0.8]，配合非对称转移矩阵，使质量下降受到的惩罚大于质量恢复获得的奖励；比二值 GRPO 在 BIRD 上 +5.7 —— [arXiv](https://arxiv.org/html/2603.16161v1)
- 回合数塑形：SQL-Trail 的 r_turns（11 份权重中占 2）只在 agent 于 2 回合内（simple）、3 回合内（medium）或在上限之前答对（hard）完成时给 1；去掉它后平均回合数从 2.26 升至 3.19，标准差从 0.65 升至 2.12，同时 BIRD-dev greedy 从 60.1 降至 59.3 —— [ACL PDF, Eq. 7 and Table 6](https://aclanthology.org/2026.acl-long.1677.pdf)
- 带覆盖项的组合塑形：ReToolSQL 执行 2.0，格式 0.2，语法 0.5，表/列覆盖 Jaccard 各 0.5，非空 0.1，长度惩罚 -0.1 —— [arXiv](https://arxiv.org/html/2608.27796)；ReEx-SQL 格式 2.0，执行 3.0，EM 1.0，实体 1.0，探索 2.0 —— [arXiv](https://arxiv.org/html/2505.12768)；SQL-Trail 5 执行 + 2 回合 + schema + bigram + 语法 + 格式 —— [ACL PDF](https://aclanthology.org/2026.acl-long.1677.pdf)
- 多 agent / 多轨道的 credit assignment：TRUST-SQL 的 token 掩码 dual-track advantage（lambda = 0.25；lambda = 0.375 会崩溃到 54.2%，7.66 回合）—— [arXiv](https://arxiv.org/html/2603.16448v1)；DualSQL schema-linking F1 + 执行 + 工具使用奖励 + REX + 长度惩罚 —— [arXiv](https://arxiv.org/html/2609.18135)
- Reward hacking 报告：TRUST-SQL 仅 RL 的 policy 在第 1 回合导出所有表，把未知 schema 转化为全 schema（59.9，有 SFT 时为 64.9）—— [arXiv](https://arxiv.org/html/2603.16448v1)；SQL-Trail 未调优的 agent 刷回合（Qwen 平均 6.44 回合，Sonnet 4.24）—— [ACL PDF Table 6](https://aclanthology.org/2026.acl-long.1677.pdf)；SQL-ASTRA 记录了使用对称步 reward 时的 "repetitive generation"（重复生成）和 "numerous unnecessary loops"（大量不必要的循环）（60.1 vs 64.2）—— [arXiv](https://arxiv.org/html/2603.16161v1)；DualSQL 在格式违规时截断 rollout 以阻止格式错误的 trajectory —— [arXiv](https://arxiv.org/html/2609.18135)；MARS-SQL 报告使用稀疏 reward 时没有 reward hacking —— [arXiv](https://arxiv.org/html/2511.01008)
- 可复用于写操作任务的评测侧 reward：BIRD-Interact 归一化 reward = 0.7 主任务 + 0.3 后续任务，带 debug 惩罚，成功与否由 PostgreSQL 状态上的测试用例判定；DySQL-Bench 在 INSERT/UPDATE/DELETE 之后判定最终 DB 状态，使用 Pass^k —— [BIRD-Interact](https://arxiv.org/html/2510.05318)；[DySQL-Bench](https://arxiv.org/html/2510.26495)

### 推断
- 在 text-to-SQL 中，针对写操作任务的最终 DB 状态 reward 没有已发表的 RL 先例；最接近的类比是上面的结果集 reward，以及 BIRD-Interact 和 DySQL-Bench 的状态检查评测器。
- 两种可复现的刷回合修正办法是：显式的按难度回合 reward（SQL-Trail），或硬上限加非对称步 reward（SQL-ASTRA）；两者加进 GRPO 循环的成本都很低。

### 空白/未知
- 没有论文报告对向用户提澄清问题给 reward，也没有在通用的"不可执行 = 0"项之外对未执行的最终 SQL 施加惩罚。

## 关键问题 7：1.7B / 4B policy 能否仅靠 RL 学会多轮 SQL？

### 要点
在 4B 上，对于只读工具循环且基座已能遵循标签协议时，可以：MTIR-SQL 仅用 RL 就把 Qwen3-4B 从基座带到 BIRD-dev 64.4%；但 TRUST-SQL 显示仅 RL 的 Qwen3-4B 停滞在 59.9%（有 SFT 时为 64.9%），并学到一种退化的导出所有表策略。在 3B 上，SQL-Trail 发现在 BIRD 上仅 RL 与 SFT+RL 持平（55.2 vs 55.2），仅 SFT 略好（55.7）。在 1.7B 上，唯一的证据（MTSQL-R1）显示未训练的长程 agent 为 22.6% EX（单次 prompting 为 59.9%），作者在 GRPO 之前依赖三轮 self-taught SFT；在找到的文献中不存在 1.7B 仅 RL 的多轮结果。

### 引用的发现
- MTSQL-R1 Qwen3-1.7B：未训练的长程基座 agent 22.6 EX（CoSQL）/ 23.9（SParC）；warm-start SFT 第 1 轮 69.9 / 70.6；SFT+RL 77.3 / 76.2；"Small LLMs struggle to follow long-horizon function-calling instructions"（小 LLM 难以遵循长程 function-calling 指令）；没有长程仅 RL 的行 —— [arXiv PDF v3, Table 2](https://arxiv.org/pdf/2510.12831v3)
- MTSQL-R1 Qwen3-4B 未训练的长程基座 agent 60.3 / 57.6 EX（1.7B 为 22.6 / 23.9），即 4B 模型本来就能好得多地遵循工具协议 —— [arXiv PDF v3, Table 2](https://arxiv.org/pdf/2510.12831v3)
- MTSQL-R1 LLaMA3.2-3B-Instruct 基座 22.9 / 24.4 -> SFT+RL 74.8 / 75.2 —— [arXiv PDF v3, Table 11](https://arxiv.org/pdf/2510.12831v3)
- TRUST-SQL Qwen3-4B：BIRD-dev 上仅 SFT 46.2，仅 RL 59.9，SFT+RL 64.9；仅 RL 的 reward hack（第 1 回合查询所有表）；不预填 schema 的基座 29.3 —— [arXiv](https://arxiv.org/html/2603.16448v1)
- MTIR-SQL Qwen3-4B 仅 RL（GRPO-Filter，无 KL，5 个 rollout，6 次工具调用）：BIRD-dev 64.4，Spider-dev 84.6（摘要）—— [arXiv abstract](https://arxiv.org/abs/2510.25510)；[arXiv HTML](https://arxiv.org/html/2510.25510)
- SQL-Trail Qwen2.5-Coder-3B（Table 7，Spider-dev / Spider-test / BIRD-dev）：仅 SFT 83.1/82.9/55.7；仅 RL 84.6/83.1/55.2；SFT+RL 84.6/84.3/55.2；3B 主结果 Spider-dev 76.3/83.1，BIRD 50.1/55.1（greedy/majority），单次生成基座为 72.8/77.0，45.2/50.5 —— [ACL PDF, Tables 1 and 7](https://aclanthology.org/2026.acl-long.1677.pdf)
- DualSQL-4B（Qwen3-4B，在 3,755 个样本上 SFT + GRPO）：BIRD-dev 68.0% —— [arXiv](https://arxiv.org/html/2609.18135)
- ReToolSQL Gemma 4 E4B：从基座 RFT 得到 BIRD-dev 68.45%；"smaller model shows larger RL gains (+3.33% vs +1.95%)"（更小的模型 RL 提升更大（+3.33% vs +1.95%））—— [arXiv](https://arxiv.org/html/2608.27796)
- SQL-ASTRA：Qwen2.5-Coder-7B-Instruct 因 "insufficient exploratory capabilities"（探索能力不足）无法用于 agentic RL，OmniSQL-7B 在 RL 之前需要一次 6k 样本的格式 SFT —— [arXiv](https://arxiv.org/html/2603.16161v1)
- SkyRL-SQL：7B instruct 模型无 SFT、配合 -1 格式惩罚，在 14 个 epoch 内从 653 个 prompt 中学会了 5 回合协议 —— [SkyRL docs](https://skyrl.readthedocs.io/en/latest/recipes/skyrl-sql.html)；[utils.py](https://raw.githubusercontent.com/NovaSky-AI/SkyRL/main/skyrl-gym/skyrl_gym/envs/sql/utils.py)

### 推断
- 决定性变量是基座模型能否已经以不可忽略的成功率输出工具协议：Qwen3-4B（在 MTSQL-R1 格式下未训练即有 60%）和 Qwen2.5-Coder-7B-Instruct 能仅靠 RL 学会，而 Qwen3-1.7B（22.6%）和 LLaMA3.2-3B（22.9%）在更丰富的 6 动作 MTSQL-R1 协议下，没有 warm start 就产生不了足够多的成功 rollout 供 GRPO 使用；词汇更小的协议（SkyRL 的三个标签）会降低这一门槛。
- 当任务有可被绕过的隐藏结构时（TRUST-SQL 中的未知 schema），仅 RL 的 policy 会找到绕过方式；SFT 修正的是行为先验，而不仅是格式。
- 在 3B 上，SQL-Trail 在 BIRD 上 SFT 与 RL 数字持平，这表明对跨域迁移而言，上限在于模型容量而非训练配方。

### 空白/未知
- 没有论文在无 SFT 的情况下用多轮 RL 训练 1.7B（或更小）的模型；1.7B 的证据只有一篇论文（MTSQL-R1），且是在带 gold 历史记忆的 CoSQL/SParC 上。
- 没有研究在 1.7B-4B 上多少条 SFT trajectory 才"够"；数量从 1,000（SQL-Trail 7B）到 70,970（TRUST-SQL 4B/8B）不等，没有受控的扫描实验。
- 不存在带模拟用户在环的小模型结果。

## 关键问题 8：OmniSQL / SynSQL-2.5M 作为 SFT 或 trajectory 来源；把单轮数据转换成多轮 agent trajectory

### 要点
SynSQL-2.5M 是 agentic RL prompt 和蒸馏 trajectory 的主要种子来源：SkyRL-SQL 的 653 个 prompt 和 SQL-Trail 的 800 个 RL prompt 都来自它的数据库/问题，TRUST-SQL 用三个 teacher LLM 把 9,217 个 SynSQL 问题转换为 70,970 条多轮工具 trajectory。OmniSQL-7B 本身被用作 RL 起点（SQL-ASTRA），但需要先做一次 6k 样本的格式 SFT。标准的转换配方是：取一个单轮（问题、gold SQL、DB）三元组，让 teacher 或 policy 自身在带 SQL 执行器的 agent 模板中运行，保留最终 SQL 执行结果与 gold 结果匹配的 trajectory，并可选地按难度或 pass@k 过滤。

### 引用的发现
- SynSQL-2.5M：2,544,390 个合成样本；OmniSQL 7B/14B/32B 在其上训练（VLDB 2025）—— [OmniSQL arXiv](https://arxiv.org/pdf/2503.02240)；[VLDB](https://www.vldb.org/pvldb/vol18/p4695-li.pdf)
- TRUST-SQL：9,217 个 moderate/complex/highly-complex 难度的 SynSQL-2.5M 问题 -> 由 GPT-4.1-mini、GPT-4o-mini、DeepSeek-R1 生成 trajectory -> 按执行正确性 + 格式合规保留 70,970 条（61.7% 来自 GPT-4.1-mini）—— [arXiv](https://arxiv.org/html/2603.16448v1)
- SQL-Trail：SFT = Spider-train 上 3,000 条 Claude-Sonnet-3.7 trajectory 中的 1,000 条（最终 SQL 正确，优先中等/困难）；RL = SynSQL(0.8k) + Spider(1k)，共 1,873 个样本，按 pass@6 区间选取 —— [ACL PDF](https://aclanthology.org/2026.acl-long.1677.pdf)
- SkyRL-SQL：653 个 prompt；DB "from SynSQL-2.5M and Spider, sourced from OmniSQL dataset collections"（来自 SynSQL-2.5M 和 Spider，取自 OmniSQL 的数据集合集）；数据集各行带有 `synsql` 字段 —— [SkyRL docs](https://docs.skyrl.ai/docs/recipes/skyrl-sql)；[HF dataset](https://huggingface.co/datasets/NovaSky-AI/SkyRL-SQL-653-data)
- SQL-ASTRA：以 OmniSQL-7B 作为 RL 基座需要 "Format-6k fine-tuning step to acquire the tool-calling format"（Format-6k 微调步骤来习得工具调用格式）；RL 后 BIRD 69.1，Spider 2.0 17.7 —— [arXiv](https://arxiv.org/html/2603.16161v1)
- MTSQL-R1：通过对 policy 自身 rollout 做拒绝采样（每个问题 20 个，3 轮），以 self-taught 方式把 CoSQL/SParC 的每问题单轮数据转换为 4 次交互的工具 trajectory —— [arXiv HTML](https://arxiv.org/html/2510.12831)
- ReToolSQL：把 BIRD 单轮样本对转换为工具 trajectory，对模型在 pass@16 下失败的样本使用 "privileged access to the gold reference SQL as contextual guidance"（以特权方式访问 gold 参考 SQL 作为上下文引导），其余使用自身 trace，全部经过执行验证 —— [arXiv](https://arxiv.org/html/2608.27796)
- AGRO-SQL：DeepSeek-V3.2 trajectory，基于 SQL 动作与推理的混合 embedding 做多样性感知选取；合成样本只在执行完全匹配时保留 —— [arXiv](https://arxiv.org/html/2512.23366)
- OmniSQL 作为数据效率的 baseline：在 SynSQL(2.5M)+BIRD(9.4k)+Spider(8.7k) 上训练的 OmniSQL-7B 在 Spider-test 上每 1k 样本 0.002 个百分点，SQL-Trail-7B 为 1.90 —— [ACL PDF Table 1](https://aclanthology.org/2026.acl-long.1677.pdf)

### 推断
- 没有论文把 SynSQL 单轮数据转换成用户在环（澄清 / 追问）的对话；所有转换都是 policy-DB 工具 trajectory。
- 难度过滤（TRUST-SQL 取 moderate 及以上；SQL-Trail 取中等/困难、pass@6 在 (0,1) 之间）是普遍做法；平凡的 SynSQL 样本在生成 trajectory 之前就被丢弃。

### 空白/未知
- SkyRL-SQL 653 个样本的精确选取规则（难度 / 通过率过滤）在此处能访问到的页面中没有记录。
- 除 TRUST-SQL 的 9,217 -> 70,970（每个问题多条 trajectory；未给出逐问题接受率）之外，没有已发表的 SynSQL 上 teacher trajectory 生成的产出率数字。
