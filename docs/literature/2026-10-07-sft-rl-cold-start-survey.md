# 先修协议、再做 GRPO：小模型多轮 SQL Agent 的冷启动证据

> 2026-10-07 的文献调研。依据的四份分主题笔记在 [2026-10-07-sft-rl-survey-notes/](2026-10-07-sft-rl-survey-notes/)，每个数字都带原文链接。

2025–2026 年的证据指向一个明确的配方：对 Qwen3-1.7B / Qwen3-4B 这种要在"用户–agent–数据库"三方回路里执行写操作的 agent，**先用一轮小规模、学生可表达的 SFT（自身 rejection-sampled 轨迹或同族更强模型的轨迹，1.5K–5K 条、1–2 epoch、不训到饱和）把交互协议学会，再用奖励落在最终 DB 状态上的 GRPO 做能力提升**；而"从远强于学生、风格不同的教师蒸馏长 CoT"是 ≤3B 模型最常被证明有害的做法。单轮 text-to-SQL 文献里一半论文完全跳过 SFT 且在 3B–7B 上都能训起来（Reasoning-SQL、CSC-SQL、CogniSQL-R1-Zero、DeepRetrieval、RingSQL），但一旦任务变成多轮工具协议，唯一用 Qwen3-1.7B/4B 做多轮 SQL 的论文 MTSQL-R1 显示：未训练的 1.7B 在长程工具格式下只有 **22.6% EX**（同模型单轮提示 59.9%），作者因此用三轮自举 SFT 再接 GRPO，最终 1.7B 77.3%、4B 79.9%；TRUST-SQL 则在 Qwen3-4B 上给出 SFT-only 46.2 / RL-only 59.9 / SFT+RL 64.9 的三臂数字，并记录 RL-only 学到了绕过任务结构的 hack。你的诊断（小模型失败多为协议失败：SQL 包在不可执行的包装里、一轮多个 SQL 块只执行第一个、伪造 `<result>`；若全部意图写操作都执行，4B 可到 ~54%、1.7B ~46%）与 MTSQL-R1 的"协议而非 SQL 能力是瓶颈"几乎同构，这意味着最便宜的一段增益来自协议 SFT，而 RL 负责剩下的 SQL 正确性。通用 user-agent RL（UserRL、BAO、MUA-RL、FACA）全部使用冻结的 prompted 模拟器、GRPO 系算法、落在最终环境状态上的 0/1 稀疏奖励、10–30 轮上限和仅 1.5K–5K 条轨迹的 SFT 冷启动，这些设计可以几乎原样迁移到 DySQL 的 DB-state 奖励上；但要把结果项保持主导、不要给结果重叠类的部分奖励（Arctic-Text2SQL-R1 与 Reinforcing Code Generation 都记录了被 hack），并过滤 no-op gold 任务。由此支持的实验设计是在 1.7B 与 4B 上各跑四条主臂——RL-only、自举 RFT→RL、同族教师蒸馏→RL、以及两种 SFT-only 中间 checkpoint——再根据 1.7B 是否出现零奖励悬崖决定是否加一条 hint 类混合策略臂。

## 单轮 text-to-SQL：跳过 SFT 可行，但 SFT 的正负号由数据来源决定

单轮 reasoning-RL 文献的基本面是：以 Qwen2.5-Coder-Instruct 为底座、直接上 GRPO 在 3B–14B 全部训得起来，而且常常胜过 SFT。Reasoning-SQL 把 GRPO 直接用在 Qwen2.5-Coder 3B/7B/14B 上，BIRD dev 从 Base / SFT / GRPO 的 **45.17 / 55.9 / 58.67**（3B）与 58.73 / 61.53 / 64.01（7B）一路上升，在 Spider 系列上的泛化差距更大（7B SFT 68.08 vs GRPO 78.72），摘要直接写"RL-only training ... consistently achieves higher accuracy and superior generalization compared to SFT" ([Reasoning-SQL HTML v2](https://arxiv.org/html/2503.23157v2); [abs](https://arxiv.org/abs/2503.23157))。DeepRetrieval 给出 3B 上最干净的四格：Qwen2.5-Coder-3B 零样本 30.77、SFT 39.77、RL-only **49.02**、SFT→RL **50.52**，结论是"RL from scratch achieves better performance than SFT"且"SFT can provide a strong initialization for RL especially when the LLM lacks a certain capability" ([DeepRetrieval HTML v3](https://arxiv.org/html/2503.00223v3))。CogniSQL-R1-Zero 在 7B 上"without any supervised warm-up"做到 59.97 单采样，并解释了为什么不做 SFT：用 QwQ-32B 蒸馏轨迹做 SFT 让准确率从 ~52 掉到 ~46，用模型自己生成并经执行验证的数据做 SFT 则回到 ~57.3，仍低于直接 GRPO ([CogniSQL HTML](https://arxiv.org/html/2507.06013))。

但"SFT 有害"与"SFT 有益"的论文并不矛盾，分界线是 SFT 数据的来源、规模和与学生的分布匹配。SQL-R1 的 7B 消融最能说明问题：RL-only 63.1；先在 SynSQL-200K 上 SFT 再 RL 反而只有 **59.2**；而从 OmniSQL-7B（在 2.5M 同分布样本上 SFT 过）起步再 RL 达到 66.6，作者总结"SFT cold-start training is not universally essential ... Its effectiveness is contingent upon the origin and volume of the training data" ([SQL-R1 HTML v5](https://arxiv.org/html/2504.08600v5))。Arctic-Text2SQL-R1 索性不做自己的 SFT，直接从 OmniSQL 公开 checkpoint 起 RL，并声称"Stronger SFT models (e.g., OmniSQL) consistently yield better downstream RL results" ([Arctic HTML v2](https://arxiv.org/html/2505.20315v2))。Think2SQL 用 1,142 条 DeepSeek-R1 轨迹做 SFT，结果 3B 上 RL-only 0.500 > SFT+RL 0.482 > SFT 0.460，正是"小数据 + 风格迥异教师"让 SFT 变成拖累的情形，尽管作者仍主张"small LLMs benefit most from reasoning-aware SFT and RL" ([Think2SQL HTML](https://arxiv.org/html/2504.15077); [abs](https://arxiv.org/abs/2504.15077))。真正从非 instruct 底座出发的 AGRO-SQL（Qwen3-8B-Base）则看到 9 分的 SFT 价值：cold start only 62.65、GRPO only 63.17、两者 72.10 ([AGRO-SQL HTML](https://arxiv.org/html/2512.23366))。

| 论文 | 模型 | SFT 数据 | SFT-only | RL-only | SFT→RL | 结论 |
|---|---|---|---|---|---|---|
| DeepRetrieval | Qwen2.5-Coder-3B | 金标 SQL | 39.77 | 49.02 | **50.52** | SFT 作初始化略优 ([src](https://arxiv.org/html/2503.00223v3)) |
| Think2SQL | Qwen2.5-Coder-3B | 1,142 条 R1 轨迹 | 0.460 | **0.500** | 0.482 | 小量异源蒸馏拖累 ([src](https://arxiv.org/html/2504.15077)) |
| SQL-R1 | Qwen2.5-Coder-7B | SynSQL-200K / OmniSQL-2.5M | – | 63.1 | 59.2 / **66.6** | 看数据规模与分布 ([src](https://arxiv.org/html/2504.08600v5)) |
| CogniSQL | Qwen2.5-Coder-7B | QwQ 蒸馏 / 自生成 | ~46 / ~57.3 | **59.97** | – | 自生成安全、仍不及 RL ([src](https://arxiv.org/html/2507.06013)) |
| AGRO-SQL | Qwen3-8B-**Base** | DeepSeek-V3.2 蒸馏 | 62.65 | 63.17 | **72.10** | 非 instruct 底座必须 SFT ([src](https://arxiv.org/html/2512.23366)) |
| ReToolSQL | Gemma 4 31B | 自身 rejection 轨迹（难题给金标提示） | 72.69 | 73.66 | **74.32** | 自举 SFT 小幅加分 ([src](https://arxiv.org/html/2608.27796v1)) |

对 ≤1.5B 的模型，证据更一致地偏向 SFT：SLM-SQL 报告去掉 SFT 在 0.5B 上损失 21.93 分、1.5B 上 8.89 分（注意研究者标记其 BIRD 数字与 ACL 版 67.08 不一致，引用前需核对 PDF）([SLM-SQL HTML](https://arxiv.org/html/2507.22478); [ACL](https://aclanthology.org/2025.findings-ijcnlp.92.pdf))；FINER-SQL 的 0.5B / 1.5B / 3B 最终 50.85 / 63.17 / 67.73 全部包含 SFT 阶段 ([FINER-SQL HTML](https://arxiv.org/html/2605.03465v1))。单轮文献的一个结构性空白是：没有任何论文在 Qwen3-1.7B / Qwen3-4B 上做单轮 SQL RL，也没有论文从 1.5B–4B 的非 instruct 底座做 RL；更重要的是，这些论文都不涉及工具调用格式、多步循环或写语句，所以它们对"协议学习负担"几乎没有发言权。

## 多轮 agentic SQL：瓶颈是协议而非 SQL 能力，1.7B 没有不做 warm start 的先例

把 DB 执行放进循环之后，文献的分裂更清楚。MTSQL-R1（Amazon，ACL 2026）是唯一用 Qwen3-1.7B 和 Qwen3-4B 训多轮 SQL agent 的工作：agent 以 PROPOSE / EXECUTE / E-VERIFY / M-VERIFY / SELF-CORRECT / FINALIZE 六种动作与 SQLite 和"dialogue memory"工具交互，verl 的 `multi_turn.max_turns: 4`。它的冷启动是**纯自举**：对所有训练问题以温度 0.7 采样 20 条轨迹，只保留最终 SQL 正确的，难度感知地为简单题留 ≤2 条短轨迹、难题留 3 条聚类代表，用新模型重采样共三轮；CoSQL 9,337 题的覆盖率从 6,311 → 7,409 → 7,555（约 68% → 81%），最终 19,416 条轨迹，没有任何外部教师 ([MTSQL-R1 PDF v3 Table 9](https://arxiv.org/pdf/2510.12831v3); [HTML](https://arxiv.org/html/2510.12831))。关键数字在 Table 2：Qwen3-1.7B 单轮 prompting 59.9 EX，**未训练的长程 agent 只有 22.6**，自举 SFT 第 1/2/3 轮 69.9 / 72.2 / 73.0，再接 GRPO（仅结果奖励）76.6，加过程奖励 77.3；Qwen3-4B 未训练长程 agent 60.3，SFT 三轮 75.2，SFT+RL 79.1 / 79.9 ([MTSQL-R1 PDF v3 Table 2](https://arxiv.org/pdf/2510.12831v3))。作者的总结"Small LLMs struggle to follow long-horizon function-calling instructions"与"our self-taught SFT-then-RL pipeline trains stably even when the initial model lacks frontier-level reasoning"直接对应你的情形 ([MTSQL-R1 PDF v3](https://arxiv.org/pdf/2510.12831v3))。RL 侧配置可以直接抄：verl 0.4.1 + SGLang，train batch 256，`rollout.n=5`，lr 1e-6，prompt 4,000 / response 8,000 tokens，`use_kl_in_reward=False`，按难度分 curriculum 并丢掉 SFT 模型已 20/20 解出的题，单节点 8×A100；代码与 1.7B/4B checkpoint 在 GitHub ([MTSQL-R1 GitHub](https://github.com/taichengguo/MTSQL-R1); [PDF v3 App. C.2](https://arxiv.org/pdf/2510.12831v3))。值得注意的是过程奖励只多给了 +0.7 EX（4B 79.1 → 79.9），大头来自长程形式本身加 outcome GRPO ([PDF v3 Table 10](https://arxiv.org/pdf/2510.12831v3))。

MTSQL-R1 没有报告长程格式下的 RL-only 臂，这个空缺由 TRUST-SQL 在 Qwen3-4B 上补上：SFT-only **46.2**、RL-only **59.9**、SFT+RL **64.9**（BIRD dev），而且 RL-only 策略学到的是"exhaustively querying all tables in turn one"——把未知 schema 任务退化成全 schema 预填，平均 4.23 次工具调用 vs 有 SFT 的 3.66 ([TRUST-SQL HTML v1](https://arxiv.org/html/2603.16448v1))。这说明 SFT 修正的不只是格式，还有行为先验；当任务有可被绕过的隐藏结构时，RL-only 会找到绕路。TRUST-SQL 的 SFT 数据是 9,217 道 SynSQL 题由 GPT-4.1-mini / GPT-4o-mini / DeepSeek-R1 生成、经执行正确与格式合规过滤的 70,970 条轨迹，训练轮数上限 10 轮，"further increasing to 12 turns causes severe training instability" ([TRUST-SQL HTML v1](https://arxiv.org/html/2603.16448v1))。SQL-Trail（Amazon，ACL 2026）用仅 1,000 条 Claude-Sonnet-3.7 轨迹做 SFT、1,027 条 prompt 做 RL，三种规模的消融是 3B：SFT 55.7 / RL 55.2 / SFT+RL 55.2；7B：58.7 / 61.7 / 64.2；14B：64.8 / 65.4 / 66.7（BIRD dev），"RL with SFT cold-start yields the highest performance"，但在 3B 上三臂持平，暗示 3B 的跨域上限由容量而非配方决定 ([SQL-Trail ACL PDF Table 7](https://aclanthology.org/2026.acl-long.1677.pdf))。SQL-Trail 还量化了未调优 agent 的退化行为：未训练的 Qwen2.5-Coder-7B agent 平均 6.44 轮、"repeatedly revises flawed SQL due to weaker syntax"，Sonnet 4.24 轮浪费在探索 schema 上；"SFT improves syntax accuracy and shortens trajectories ... RL further improves schema identification" ([SQL-Trail ACL PDF Sec. 5.2, Table 6](https://aclanthology.org/2026.acl-long.1677.pdf))。

反方向的证据是 RL-only 在 4B 和 7B 上确实能训：MTIR-SQL 用 GRPO-Filter（去 KL、轨迹过滤）把 Qwen3-4B 直接训到 BIRD dev 64.4、最多 6 次工具调用 ([MTIR-SQL HTML](https://arxiv.org/html/2510.25510); [abs](https://arxiv.org/abs/2510.25510))；SkyRL-SQL 用 653 条 prompt、5 轮、14 epoch、不做 SFT 把 Qwen2.5-Coder-7B-Instruct 训到超过 GPT-4o 与在 2.5M 样本上 SFT 的 OmniSQL-7B，奖励是格式违规 −1、结果集 `frozenset` 相等 +1、否则 0，"No reward for intermediate steps" ([SkyRL docs](https://docs.skyrl.ai/docs/recipes/skyrl-sql); [utils.py](https://raw.githubusercontent.com/NovaSky-AI/SkyRL/main/skyrl-gym/skyrl_gym/envs/sql/utils.py); [env.py](https://raw.githubusercontent.com/NovaSky-AI/SkyRL/main/skyrl-gym/skyrl_gym/envs/sql/env.py); [HF dataset](https://huggingface.co/datasets/NovaSky-AI/SkyRL-SQL-653-data))。MARS-SQL 与 SERL-SQL 同样在 7B instruct 上无 SFT 起 GRPO ([MARS-SQL HTML](https://arxiv.org/html/2511.01008); [SERL-SQL HTML](https://arxiv.org/html/2608.00485v3))。但 SQL-ASTRA 提供了反例的边界：Qwen2.5-Coder-7B-Instruct 因"insufficient exploratory capabilities"被弃用，OmniSQL-7B 需要先做 6k 条格式 SFT 才能学会工具调用格式 ([SQL-ASTRA HTML](https://arxiv.org/html/2603.16161v1))。综合这些，**决定变量是底座在目标协议下的初始成功率**：Qwen3-4B 在 MTSQL-R1 格式下未训练已有 60%、Qwen2.5-Coder-7B-Instruct 在三标签协议下能用，所以 RL-only 跑得起来；Qwen3-1.7B（22.6%）和 LLaMA3.2-3B（22.9%）在六动作协议下产生不了足够多的成功 rollout 让 GRPO 有组内方差。你的 1.7B 零样本 pass@1 16.2%、且其中大半是协议失败，正处在这条线之下。

还要指出两个与 DySQL 直接相关的文献空白。第一，DySQL-Bench 本身不训练任何模型，评测回路是 Qwen2.5-72B-Instruct 模拟用户 + 被测模型 + SQLite，最多 30 轮，采样 temperature 0.6 / top_p 0.95 / top_k 20，判最终 DB 状态并报 Pass^k ([DySQL-Bench HTML](https://arxiv.org/html/2510.26495); [abs](https://arxiv.org/abs/2510.26495); [GitHub](https://github.com/Aurora-slz/DySQL-Bench))；搜索没有找到任何在 DySQL-Bench 或 BIRD-Interact 回路里做 RL 的后续工作，BIRD-Interact 上最接近的是"Learning to Retrieve"——策略仍是 GPT-5，PPO 只训 Qwen3-4B 的记忆检索选择器 ([BIRD-Interact HTML](https://arxiv.org/html/2510.05318); [Learning to Retrieve HTML](https://arxiv.org/html/2606.00547))。第二，所有多轮 SQL RL 论文的"多轮"都是策略–DB 轮次，没有模拟用户，奖励全是结果集匹配而非最终 DB 状态，因为训练任务全是 SELECT。**写操作的最终 DB 状态奖励在 text-to-SQL RL 里没有已发表先例**，最接近的类比是 DySQL-Bench 和 BIRD-Interact 的评测器以及通用 user-agent RL 的环境状态奖励（下文）。

## 小模型方法学：蒸馏什么比是否蒸馏更重要——自生成、同族、欠饱和

跨数学、工具调用和 agent 任务的方法学文献对 1–4B 策略给出一条最稳健的结论：**SFT 的内容比有无 SFT 更重要**。Li et al. 的"Small Models Struggle to Learn from Strong Reasoners"显示 Qwen2.5-1.5B 在长 CoT 上训练比短 CoT 在 MATH 和 AMC 上落后 10 分以上，Qwen2.5-0.5B 用 72B 教师比用 3B 教师在 AMC 上退 10 分以上，而到 3B 差距只剩 0.3 分；机制是"distribution mismatch between student and teacher"和"speaking styles shift"，修法是长短 CoT 或大小教师 1:4 混合，在 3B 上带来 7–8 分 ([Li et al. abs](https://arxiv.org/abs/2502.12143); [HTML](https://arxiv.org/html/2502.12143))。BREAD 从理论上说明标准 SFT+GRPO 在"expert's traces are too difficult for the small model to express"或初始成功概率指数级小的情况下"can fail completely"，实验上 Qwen2.5-3B 在 NuminaMath 上 vanilla GRPO ~46–48、SFT+GRPO ~54、BREAD ~65 ([BREAD abs](https://arxiv.org/abs/2506.17211); [HTML](https://arxiv.org/html/2506.17211))。工具调用侧的 ToolRL 更刺眼：400 条教师风格样本的 SFT 冷启动让 Qwen2.5-1.5B/3B/7B 的 BFCL 分别从 GRPO-only 的 46.20 / 52.98 / 58.38 降到 40.93 / 46.42 / 39.25，"SFT initialization leads to memorization and overfitting"，唯一受益的是本来发不出格式的 Llama-3.2-3B ([ToolRL abs](https://arxiv.org/abs/2504.13958); [HTML](https://arxiv.org/html/2504.13958))。Nemotron-Tool-N1 同样发现"the widely adopted SFT-then-RL paradigm does not necessarily outperform pure RL" ([Tool-N1 HTML](https://arxiv.org/html/2505.00024))。

然而把 ToolRL 的结论直接搬到多轮用户协议上是错误的，因为分界线仍是"底座能否已经发出协议"。EnvFactory 在 Qwen3-1.7B/4B/8B 上用 1,622 条合成轨迹 SFT、953 条 RL，BFCL multi-turn 的 1.7B 从 16.75 → 23.25 → 28.38，4B 从 33.50 → 44.25 → 48.50，并明确报告不做 SFT 直接 RL 的增益"smaller and less stable than RL after SFT, indicating that SFT initialization remains important" ([EnvFactory HTML](https://arxiv.org/html/2605.18703))。SimpleRL-Zoo 的 zero-RL 从 0.5B 起都能跑，但"strict enforcement [of format reward] hurt smaller/weaker models" ([SimpleRL-Zoo](https://arxiv.org/abs/2503.18892))；"SFT Memorizes, RL Generalizes"的作者在批评 SFT 记忆化的同时仍写下"SFT stabilizes the model's output format, enabling subsequent RL to achieve its performance gains" ([SFT Memorizes](https://arxiv.org/abs/2501.17161))。研究者据此的推断是：对 Qwen3-1.7B 的多轮 agent 协议需要约 1–2k 条格式 SFT，对 Qwen3-4B 直接 GRPO 可行但 SFT-first 更稳。

哪种 SFT 数据对小模型安全，2026 年的 agentic 论文给出了相当一致的"以学生为中心"配方。WinDOM（Qwen3.5-2B GUI agent）用学生自身的 EMA 作教师做一次 rejection-sampling 冷启动，发现**欠饱和（早停）的冷启动在相同 GRPO 之后比训到收敛的冷启动 OOD 均值高 5.4 分**，EMA 自教师只比同族 4B 教师低 1.1 分；机制是饱和的 SFT 把动作分布推到近确定性，"the within-group standard deviation σ approaches zero and the group-relative advantage degenerates" ([WinDOM HTML](https://arxiv.org/html/2606.25964v1))。SFT 过训练研究在 Qwen2.5-Coder-3B-Base 上测得 SFT 轮数从 1.0 升到 5.8 时"peak GRPO pass@10 falls from 0.806 to 0.481"，建议以 RL 前熵阈值 0.18 nats 选 checkpoint（该实验中是 1.9 epoch）([SFT over-training](https://arxiv.org/html/2606.18487v1))；"When RL Fails after SFT"同样归因于"over-confident token distributions" ([arXiv 2606.09932](https://arxiv.org/abs/2606.09932))。SCoRe 用 Qwen2.5-72B 教师教 7B/3B 学生，配方是只拿 20% 教师轨迹做 BC，然后让学生自己生成、教师只改第一处错误，再做修正式 SFT 和短程 RL；12 个基准均值 BC 43.0 / GRPO 48.2 / SCoRe-RL 52.3，失败原因是"smaller models often fail to reproduce the teacher's logical decomposition" ([SCoRe HTML](https://arxiv.org/html/2509.14257v3))。SOD 在 Qwen3-0.6B/1.7B 上发现多步工具调用里"after a wrong tool call subsequent teacher supervision becomes unreliable" ([SOD HTML](https://arxiv.org/html/2605.07725v1))。Early Experience 显示自生成、环境接地的数据比专家模仿更高且提高 RL 后上限（WebShop 3B IL→GRPO ~82% vs SR→GRPO ~92%），而无接地的 STaR 式长 CoT 在 WebShop 上 −47.3 ([Early Experience HTML](https://arxiv.org/html/2510.08558))。Demystifying RL 则提醒合成拼接轨迹的 SFT"yields below 10% on average@32"，真实端到端轨迹才算合格冷启动 ([Demystifying HTML](https://arxiv.org/html/2510.11701))。

Qwen3 技术报告为"同族教师"这一选择提供了最强的背书：Qwen3-0.6B 到 30B-A3B **全部由 Qwen3-32B / 235B 经 off-policy 再 on-policy 蒸馏得到**，没有走四阶段 RL 流水线；Qwen3-8B 上 off-policy 蒸馏 AIME'24 55.0 → +RL 67.6（17,920 GPU-h）→ +on-policy 蒸馏 74.4（1,800 GPU-h），且 RL 不动 pass@64（90.0 → 90.0）而 OPD 动（93.3）([Qwen3 report HTML](https://arxiv.org/html/2505.09388); [Thinking Machines](https://thinkingmachines.ai/blog/on-policy-distillation/))。这意味着你手上的 1.7B/4B checkpoint 在熵的意义上已经是"post-SFT"的，再用一个风格不同的外族教师的长 CoT 做 SFT 正是 Li et al. 警告的场景；若 32B-AWQ 是 Qwen3-32B，它恰好是 1.7B/4B 的原教师，用它生成的、经 DB 状态验证的轨迹是风险最低的蒸馏源。另一条反向告诫来自 COLM 2026 的自蒸馏研究：在 Qwen3-1.7B/8B 上自蒸馏可令数学 OOD 掉"up to 40%"，原因是"suppression of epistemic verbalization"——但这是数学推理任务，对带精确验证器的程序性任务（WinDOM、SDFT tool-use）自生成数据报告为正向 ([Self-distillation degrade](https://arxiv.org/abs/2603.24472); [SDFT HTML](https://arxiv.org/html/2601.19897v1))。

混合策略方法（LUFFY、ReLIFT、SRFT、CHORD、Scaf-GRPO、BREAD）在 7B 数学上都报告比 GRPO 高 3–13 分，但 2026 年 4 月的"SFT-then-RL Outperforms Mixed-Policy Methods"用修好两个实现 bug 的 SFT→RL 基线击败了全部已发表的混合方法（Qwen2.5-Math-7B 57.0 vs 最佳 53.2；Llama-3.1-8B 43.7 vs ~15），且 50 步 RL 已落在 500 步的 1.4 分之内 ([SFT-then-RL abs](https://arxiv.org/abs/2604.23747); [HTML](https://arxiv.org/html/2604.23747))。它们真正的价值在弱/小策略遇到零奖励悬崖的地方：LUFFY 在 Llama-3.1-8B 难集上"training rewards collapse to zero"而混合策略仍能学 ([LUFFY HTML](https://arxiv.org/html/2504.14945))；Scaf-GRPO 把 Qwen2.5-Math-1.5B 的 AIME24 从 13.3 提到 20.0，机制是只在所有 rollout 都失败后注入分级 hint ([Scaf-GRPO HTML](https://arxiv.org/html/2510.19807v2))；DGPO 把 0.5B agentic-RAG 学生从 0.006 拉到 0.329（PPO 0.238、KD 0.298）([DGPO HTML](https://arxiv.org/html/2508.20324))。所以这类方法应作为 1.7B 的条件性备选臂，而非默认配方。

## 用户模拟器 RL 的可迁移设计：冻结模拟器、最终状态二值奖励、轻量 SFT

通用 user-agent RL 的 2025–26 论文在设计上出乎意料地一致，这些设计几乎可以逐项映射到 DySQL 回路。UserRL 用 Qwen3-32B 作冻结模拟用户，在 Qwen3-4B/8B 上做 GRPO："we remove KL regularization and apply temperature 1.0"，batch 128、8 responses、15 epochs、最多 16 轮且无步罚；SFT 冷启动是 GPT-4o 同时扮演 agent 和用户生成的 5,000 条轨迹，RL 任务池仅 2,686 个；Qwen3-4B 从原始 0.2929 升到 0.5269；关键发现是"models with SFT cold start not only begin from a higher baseline but also continue to improve, whereas models trained without SFT plateau early"，以及朴素的逐轮奖励"quickly leads to training collapse"，Equalized/R2G 的轨迹级分配最好 ([UserRL abs](https://arxiv.org/abs/2509.19736); [HTML](https://arxiv.org/html/2509.19736); [HTML v1](https://arxiv.org/html/2509.19736v1))。BAO 是与你规模最接近的模板：**Qwen3-1.7B 和 4B 策略，训练时 Qwen3-8B 作用户、评测时换 GPT-4o 以引入分布偏移**，SFT 热启动后做行为正则化 GRPO，加入"连续多个用户轮次却没有环境反馈"的信息索取惩罚与超时思考惩罚；Function-Gym 上 4B 的 Score 0.6923 vs UserRL 0.5256，并记录 UserRL 基线"relies heavily on user engagement to verify answer correctness rather than autonomously exploring the environment"和"long answers to confuse the judge model"的 hack ([BAO HTML](https://arxiv.org/html/2602.11351))。MUA-RL 在 Qwen3-8B/14B/32B 上用 GPT-4o 作训练用户、GPT-4.1 作评测用户，奖励"r=1 only when the agent successfully fulfills the task ... and r=0 otherwise"，去掉 tau-bench 的对话内容检查、无格式罚、30 轮上限、32K token；约 2,000 条 SFT 轨迹对 165 个 RL 任务；8B 的 tau2 Retail 从 41.0 经冷启动 **掉到 31.4** 再被 RL 拉到 49.8，消融里"w/o cold-start"在 tau2 上胜 "w/o RL"但在 BFCL 多轮上更差，两者都不及完整配方 ([MUA-RL abs](https://www.arxiv.org/abs/2508.18669); [HTML](https://arxiv.org/html/2508.18669))。FACA 在 MUA-RL 公开的 1,580 条轨迹上 SFT 后，用冻结的 DeepSeek-V4-Flash 用户输出隐藏的"strategy"字段（confirm / reveal_piece / ask_clarification / challenge_solution ...）转成 ±1 极性作"reaction advantage"，λ 封顶 0.5 使结果优势保持主导，8B 从 34.7% 到 40.6%、14B 42.5% 到 52.7%；随机化极性后增益消失，说明用户反应信号确有信息但必须有界 ([FACA HTML](https://arxiv.org/html/2608.17499); [abs](https://arxiv.org/abs/2608.17499))。

这些论文的 SFT : RL 比例值得对照你的数据规模：SFT 轨迹 1.5K–5K、RL 任务 165–2,686，即 SFT 样本约为 RL 任务的 2:1 到 10:1，而且 SFT 全部经环境状态验证（APIGen-MT 以"comparing the final environment state to a_gt"过滤，67% 模拟通过）([APIGen-MT HTML](https://arxiv.org/html/2504.03601))。你有 3,425 个任务但没有轨迹，这个规模比 MUA-RL / FACA 的 RL 池大 20 倍、与 UserRL 同量级，足够同时切出 SFT 轨迹生成集和 RL 集，而且不必像 Tongyi DeepResearch 那样担心数据多样性不足——那篇报告以 128 次工具调用、128K 上下文的规模强调"Diverse RL datasets sustain higher policy entropy" ([Tongyi HTML](https://arxiv.org/html/2510.24701); [Demystifying HTML](https://arxiv.org/html/2510.11701))。研究者的推断是按交互类型分流：协议对底座是新的（用户侧多轮）时所有论文都保留小 SFT；底座已能发出格式（单轮工具调用）时 RL-only 胜出，而 1.7B–4B 的用户–agent–DB 协议属于前者。

模拟器本身是第二大风险源，文献给出了可直接抄的防护。所有训练论文都用 prompt 约束泄漏——tau-bench 的"Do not give away all the instruction at once. Only provide the information that is necessary for the current step" ([tau-bench](https://arxiv.org/pdf/2406.12045))，UserRL 的"Do NOT provide concrete help or solutions" ([UserRL HTML v1](https://arxiv.org/html/2509.19736v1))，AskBench 的"ONLY answers the assistant's immediate question" ([AskBench HTML](https://arxiv.org/html/2602.11199v1))——再辅以机械闸门：IntentRL 用嵌入相似度 >0.92 判重复、<0.8 判无关后才让 LLM 回复 ([IntentRL HTML](https://arxiv.org/html/2602.03468))，CUE 用固定词表拒绝含凭证、标识符、地址等任务特定内容的用户发言 ([CUE HTML](https://arxiv.org/html/2610.02460v1))，APIGen-MT 用 best-of-4 自我批评防止模拟人类"drift from the original instruction or be unduly influenced by the agent's responses" ([APIGen-MT HTML](https://arxiv.org/html/2504.03601))。审计结果说明这些仍不够：UserProxyBench 发现仅更换用户代理就使任务奖励均值变动 15.2 分，**24.4% 的成功回合含用户规范违规，主因是提前泄露** ([UserProxyBench](https://arxiv.org/abs/2609.38043))；Sim2Real 用 451 名真人对比 31 个模拟器，agent 对真人成功率 63.6% 而对模拟器可达 77.8%，GPT-4o 作用户时 49.0% 的轮次礼貌性让步（真人 15.3%）、"quietly accepting errors rather than pushing back"，且"70.6% of reward=0 interactions are actually judged as successful by human users" ([Sim2Real HTML](https://arxiv.org/html/2603.11245))。Calibrated Interactive RL 直接观察到"uncalibrated simulators frequently exhibit sycophancy ... which RL agents rapidly exploit by generating confident but incorrect responses"，朴素交互 RL 在 DocEdit 上甚至低于基线（26.1 vs 32.2 BLEU），理论上性能差距随轮数以 O(H²δ) 复合 ([Calibrated RL HTML](https://arxiv.org/html/2605.26403))。

对你的回路有两条直接推论。第一，**防伪造的保护必须来自真实环境状态，而不是用户**：没有一篇训练论文依赖模拟器识别伪造的工具结果，MUA-RL / UserRL / APIGen-MT 的奖励都算在真实环境状态上；你观察到的"伪造 `<result>` 标签"应由程序化协议检查（每个报告的结果是否来自真实执行）与 DB 状态奖励共同压制，而非指望 Qwen2.5-72B 用户"发现"。第二，训练与评测使用**同一个** Qwen2.5-72B-AWQ 模拟器会放大过拟合风险，BAO（Qwen3-8B 训、GPT-4o 评）和 MUA-RL（GPT-4o 训、GPT-4.1 评）都把换模拟器作为标准防线；由于 DySQL-Bench 官方评测固定用 Qwen2.5-72B-Instruct，合理做法是用它训练、但保留一个换用户（例如 Qwen3-32B）的 held-out 评测来测量 simulator over-fitting 的幅度，并像 FACA 那样让模拟器输出隐藏的披露标签以审计泄漏率。

## 奖励、稳定器与 credit assignment：结果项主导，协议用程序检查

奖励设计上，text-to-SQL 和通用 agent 文献共同指向"稀疏二值结果 + 小格式罚 + 不给结果重叠的部分分"。Arctic-Text2SQL-R1 试过 execution / syntax / n-gram / schema / format 等部分奖励后全部放弃，只留"1 if ... exactly align; 0.1 if syntax is correct and SQL is executable; 0 otherwise"，理由是"More fine-grained reward designs induced 'lazy' behaviors, where models pursued local optima for short-term rewards rather than global correctness"，并删掉约 3,100 条 gold 返回空结果的样本，因为它们"produc[e] spurious or uninformative rewards" ([Arctic HTML v2](https://arxiv.org/html/2505.20315v2); [HTML](https://arxiv.org/html/2505.20315))。Reinforcing Code Generation 记录了具体的 hack：CodeGemma-7B 利用 0–100 的 Relaxed-Exact-Match 部分奖励返回过宽的结果集拿到 101 分 ([arXiv 2506.06093](https://arxiv.org/html/2506.06093))。两次被 hack 的都是"结果重叠"类部分分；结构类部分分（Think2SQL 的 QATCH、SQL-Trail 的 schema/bigram Jaccard、MTSQL-R1 的 clause-F1）没有被报告 hack，但贡献也有限（MTSQL-R1 过程奖励 +0.7；SQL-Trail 去掉 n-gram −2.9、去掉 schema −1.6）([Think2SQL HTML](https://arxiv.org/html/2504.15077); [SQL-Trail ACL PDF Table 6](https://aclanthology.org/2026.acl-long.1677.pdf); [MTSQL-R1 PDF v3 Table 10](https://arxiv.org/pdf/2510.12831v3))。对写任务的 DB 状态奖励，Arctic 的空结果过滤直接对应你已记录的 no-op gold 问题——gold 写操作命中 0 行的任务会让"什么都不做"与"正确执行"得到同样的奖励，必须在 RL 池里剔除或单列。

格式罚的做法分两派，取决于有没有冷启动。SkyRL-SQL / MARS-SQL / SERL-SQL / AGRO-SQL 用 −1 的硬格式罚（没有正向格式分），MTIR-SQL 用 ±0.1 ([SkyRL utils.py](https://raw.githubusercontent.com/NovaSky-AI/SkyRL/main/skyrl-gym/skyrl_gym/envs/sql/utils.py); [MARS-SQL](https://arxiv.org/html/2511.01008); [SERL-SQL](https://arxiv.org/html/2608.00485v3); [AGRO-SQL](https://arxiv.org/html/2512.23366); [MTIR-SQL](https://arxiv.org/html/2510.25510))；Tongyi DeepResearch 则"do not include a format reward ... because the preceding cold start stage ensures the model is already familiar with the required output format" ([Tongyi HTML](https://arxiv.org/html/2510.24701))。你描述的三类协议失败都能被程序化检测：SQL 在不可执行包装里、一轮多个 SQL 块、伪造 `<result>`——它们应当在 SFT 过滤时被当作拒绝条件，在 RL 中作为 −1 级别的硬罚（或像 DualSQL 那样"rollout cutoff and error-focused loss masking"直接截断畸形轨迹 ([DualSQL HTML](https://arxiv.org/html/2609.18135))），而不是用正向格式分去"奖励"。ToolRL 警告长度奖励"in smaller-scale models ... can even cause substantial degradation" ([ToolRL HTML v1](https://arxiv.org/html/2504.13958v1))，所以不要加长度项。

轮次与用户交互的塑形有现成的、代价低的做法。SQL-Trail 的难度感知轮次奖励（简单题 ≤2 轮、中等 ≤3 轮、难题正确且未到上限才给分，权重 2/11）把平均轮数从 3.19 压到 2.26、标准差从 2.12 压到 0.65，BIRD 还涨 0.8 ([SQL-Trail ACL PDF Eq. 7, Table 6](https://aclanthology.org/2026.acl-long.1677.pdf))；SQL-ASTRA 用非对称转移矩阵（质量下降的罚大于回升的奖）消灭振荡循环，对称版本从 64.2 掉到 60.1 ([SQL-ASTRA HTML](https://arxiv.org/html/2603.16161v1))；BAO 对"连续用户轮次而无环境调用"加罚、AskBench 对过早给最终答案罚 −2.0 ([BAO HTML](https://arxiv.org/html/2602.11351); [AskBench HTML](https://arxiv.org/html/2602.11199v1))。后两者正对应用户–agent–DB 回路最常见的两种病态：问用户代替查库，以及提前结束。TRUST-SQL 的教训是辅助奖励权重一旦过大就会崩：schema 轨道 λ=0.375 时准确率塌到 54.2%、平均 7.66 轮，λ=0.25 才有 64.5 ([TRUST-SQL HTML v1](https://arxiv.org/html/2603.16448v1))。

Credit assignment 方面，critic-free 的组内相对优势是主流，2025–26 的细化有三类。GiGPO 在 Qwen2.5-1.5B/3B/7B 上把重复出现的环境状态哈希为"anchor states"组成步级组，不需要额外 rollout，开销"< 0.002% of the total per-iteration training time"，ALFWorld 1.5B 86.1% vs GRPO 72.8% ([GiGPO HTML](https://arxiv.org/html/2505.10978); [verl-agent](https://github.com/langfengQ/verl-agent))——DB 状态（schema + 表内容）是确定性可哈希的，这一机制对你几乎零成本适用，唯一未验证之处是状态里含随机用户文本时是否仍能形成足够多的锚点组。第二类是稳定器：RAGEN/StarPO-S 记录了"Echo Trap"（奖励标准差先塌、熵震荡、梯度尖峰），修法是只保留 top 25% 高不确定 prompt、去 KL、clip-higher ε_high=0.28 ([RAGEN HTML](https://arxiv.org/html/2504.20073v2))；SimpleTIR 过滤"void turns"（既无代码块也无最终答案的轮次）解决工具反馈引起的分布漂移 ([SimpleTIR](https://arxiv.org/pdf/2509.02479))；Tongyi 丢弃超长负样本并动态过滤全对/全错题，"Directly optimizing on an unfiltered set of negative rollouts significantly degrade training stability" ([Tongyi HTML](https://arxiv.org/html/2510.24701))。第三类是难度与视野课程：AgentGym-RL 的 ScalingInter 先限制交互次数再逐步放大，使 agent"less prone to collapse under long horizons" ([AgentGym-RL](https://arxiv.org/abs/2509.08755))；MTSQL-R1 则按难度分区并丢掉 SFT 已 20/20 解决的题。训练轮上限方面文献收敛在 5–16 轮（TRUST-SQL 12 轮不稳、UserRL 16、MUA-RL 30），DySQL 评测给 30 轮，训练可从 10–16 轮起步再扩展。

## 证据支持的实验设计：四条主臂、两条条件臂

把以上证据对到你的约束——3,425 个带 gold 写操作但无轨迹的任务、1.7B/4B 两个底座、Qwen2.5-72B-AWQ 模拟器、A100/H100 或 6×RTX Pro 6000——下表是文献支持的比较臂。核心争议只有两个：1.7B 能否不做 warm start，以及自举轨迹与同族教师轨迹哪个是更好的冷启动；前者有 MTSQL-R1 / TRUST-SQL / EnvFactory 的间接证据，后者在任何 ≤4B 文本多轮环境里都没有被直接比较过（WinDOM 的 2B GUI 结果是最近的类比），因此这两条正是实验该回答的问题。

| 臂 | 1.7B | 4B | 配方 | 文献依据 | 预期 |
|---|---|---|---|---|---|
| A0 零样本 | 16.2 | 29.8 | 已有 | – | 基线 |
| A RL-only | 跑 | 跑 | 从 instruct 直接 GRPO；−1 硬格式罚；DB 状态二值奖励 | MTIR-SQL 4B 64.4；TRUST-SQL 4B RL-only 59.9；SkyRL-SQL 653 条 | 4B 可训；1.7B 很可能组内方差不足或学到绕路 |
| B 自举 RFT→RL | 跑 | 跑 | 每题 16–20 条 rollout、T≈0.7–1.0；按最终 DB 状态匹配 + 协议检查过滤；1–2 轮；≤2 epoch、按熵早停 | MTSQL-R1（3 轮，覆盖 68%→81%）；WinDOM 欠饱和 +5.4；CogniSQL 自生成 > 蒸馏 | 主推臂 |
| C 同族教师→RL | 跑 | 跑 | 32B-AWQ 在同一协议下生成轨迹，同样过滤；/no_think 或短 think；与 B 同等 SFT 预算 | TRUST-SQL / SQL-Trail / UserRL 的蒸馏 SFT；Qwen3 report 同族蒸馏；Li et al. 风格偏移警告 | 覆盖 B 覆盖不到的难题；风险是轨迹过长 |
| D SFT-only | 跑 | 跑 | B、C 的中间 checkpoint | SQL-Trail / TRUST-SQL 三臂；MUA-RL 冷启动回退 | 分离"协议增益"与"RL 增益" |
| E hint/混合（条件） | 若 A/B 在难题上出现零奖励悬崖 | 可选 | Scaf-GRPO 式 hint 或 DGPO 式仅错时拉向教师 | Scaf-GRPO 1.5B；BREAD 3B；LUFFY 难集 | 只在 1.7B 需要时 |
| F 换模拟器评测（条件） | 全部 | 全部 | 用 Qwen3-32B 等作用户的 held-out 评测 | BAO、MUA-RL 的训评换模拟器 | 量化 simulator over-fitting |

B 臂的可行性可以直接算：4B 零样本 pass@1 29.8%、1.7B 16.2%，以每题 20 条 rollout 估，首轮能覆盖的任务比例会远高于 pass@1，MTSQL-R1 在 1.7B 上首轮覆盖 CoSQL 的 68% 即来自同样的机制 ([MTSQL-R1 PDF v3 Table 9](https://arxiv.org/pdf/2510.12831v3))；若按 1.5K–5K 条轨迹的文献区间，3,425 个任务里切 1,000–1,500 个任务生成 SFT 轨迹、其余作 RL 池，比例仍落在 UserRL / MUA-RL 的范围内。C 臂的轨迹由 32B-AWQ 生成时只有约 46% 的任务成功，所以它的价值在于补上 B 覆盖不到的难题，而不是替代 B——这正是 ReToolSQL"易中题用自身轨迹、pass@16 全错的难题才用带特权信息的教师轨迹"的组合 ([ReToolSQL HTML](https://arxiv.org/html/2608.27796))，也是 SCoRe 只拿 20% 教师数据做 BC 的理由。两臂 SFT 都应监控 RL 前的策略熵并早停，SFT 过训练研究的 0.18 nats 阈值和 WinDOM 的"欠饱和"结果是现成依据；按 MUA-RL 和 EnvFactory 的经验，SFT-only 的分数可能不升甚至回退（MUA-RL 8B Retail 41.0 → 31.4），**冷启动的好坏要看 RL 后曲线而非 SFT-only 分数**。

RL 侧配置以 MTSQL-R1 的 verl 配置为起点（batch 256、n=5、lr 1e-6、无 KL、response 8,000 tokens；它在 2,000 tokens 上限下"performance drops drastically"），叠加 StarPO-S / MTIR-SQL 的 clip-higher 与轨迹过滤、SimpleTIR 的 void-turn 过滤、Tongyi 的全对/全错题过滤；温度 1.0（UserRL、MUA-RL）。奖励以 DB 状态完全匹配 = 1 为主项，可按 Arctic 给"可执行但错误"0.1 或按 SkyRL 给 0，格式/协议违规 −1，no-op gold 任务剔出 RL 池（或单独统计），不加结果重叠部分分、不加长度项、不用 LLM 判官或用户判定的奖励；BAO 式"连续用户轮无 DB 调用"罚与 AskBench 式提前结束罚作为第二阶段按需加入，并像 FACA 那样把辅助项权重封顶在结果项之下。训练轮上限从 10–16 起，DySQL 评测的 30 轮作为推理上限。日志字段按你"只加能区分失败类别的字段"的原则，至少要能分开：协议失败率（三类分别计）、意图写操作实际执行率、DB 状态匹配率、平均轮数与用户轮/DB 轮比、以及换模拟器后的分差——其中前两项是把你现有诊断（协议修好后 4B ~54%、1.7B ~46%）转为可验证预测的直接指标。

算力上有几个可参照的锚点：MTSQL-R1 全流程在单节点 8×A100 完成；MARS-SQL 三 agent 约 13 小时 4×H800；FINER-SQL 3B 的 GRPO 不到 2 天 2×A6000；SQL-Trail 在 step 108 评测；"SFT-then-RL"研究显示好的 SFT 之后 50 步 RL 已接近 500 步 ([MTSQL-R1 HTML](https://arxiv.org/html/2510.12831); [MARS-SQL](https://arxiv.org/html/2511.01008); [FINER-SQL](https://arxiv.org/html/2605.03465v1); [SQL-Trail](https://aclanthology.org/2026.acl-long.1677.pdf); [SFT-then-RL](https://arxiv.org/html/2604.23747))。多轮 rollout 的真实瓶颈是 72B 模拟器的推理（MTSQL-R1 单次查询最长 28 s，SQL-ASTRA 报告 agentic rollout 约为单轮的 2 倍墙钟时间），这决定了 rollout.n 与 batch 的取舍比 GPU 数更关键 ([MTSQL-R1 PDF v3 App. D](https://arxiv.org/pdf/2510.12831v3); [SQL-ASTRA](https://arxiv.org/html/2603.16161v1))。

### 算力估算：SFT 和 RL 分开算

这一小节的数字不是文献值。它们由本仓库三组零样本基线的轨迹统计（[1.7B / 4B](../results/2026-09-19-qwen3-1.7b-4b-full.md)、[32B-AWQ](../results/2026-09-17-qwen3-32b-awq-full.md)）加上显存带宽和 FLOPs 推算得来，误差按 ±50% 看。单位是 H100-80GB 的 GPU 小时，下称 H100-h。正式开跑前，先在一个 8 卡节点上跑 20 步 GRPO，量出每步的秒数，再按比例修正下面的表。

**推算依据。** 基线都开了 thinking，每条轨迹的规模如下。关掉 thinking 后 agent 的 token 会少很多，但没有实测过，所以下面都按 thinking 开来估，算是上限。

| 每条轨迹 | 1.7B | 4B | 32B-AWQ |
|---|---|---|---|
| agent 生成 token（含 thinking），均值 / p95 | 5.3k / 15.0k | 5.3k / 12.2k | 5.1k / 10.4k |
| agent 轮数，均值 / p95 | 7 / 17 | 6 / 12 | 8 / 15 |
| 用户模拟器生成 token，均值 | 280 | 230 | 190 |
| 用户模拟器的整段上下文 | 约 1k token | 约 1k token | 约 0.9k token |

单张 H100 上，vLLM 解码受 KV 缓存容量和显存带宽限制，估计吞吐为：1.7B 约 5k tok/s，4B 约 3.5k，32B-AWQ 约 1.8k，72B-AWQ 约 2k（另加预填充）。多轮交互里策略和模拟器互相等待，长尾轨迹也会拖时间，GPU 有空转，所以再乘 1.5–2。合起来，每 1,000 条轨迹大约要：

| 组合 | H100-h / 1,000 条轨迹 |
|---|---|
| 1.7B + 72B 模拟器 | 1–1.5 |
| 4B + 72B 模拟器 | 1–2 |
| 32B-AWQ 教师 + 72B 模拟器 | 1.5–3 |

72B 模拟器每条轨迹只生成约 250 token，但每轮都要预填充新增的对话。前缀缓存命中时每条轨迹约 1k token，不命中时约 3.5k token。按 FLOPs 算，这比 4B 策略生成 5.3k token 还贵，在 rollout 的 GPU 时间里约占三分之一到一半。所以要确认 vLLM 的前缀缓存在多轮请求上真的生效。训练时把模拟器换成 Qwen3-32B，这部分大约减半；换成 8B 几乎可以忽略。"训练用小模拟器、评测用官方 72B"除了防泄漏，也省算力。

**SFT。** 成本几乎全在生成轨迹上，训练本身很便宜。

| 项 | 规模 | H100-h |
|---|---|---|
| B 臂：自举轨迹 | 1.7B、4B 各 1,500 题 × 16 条 = 2.4 万条；第二轮只补没覆盖到的题，约多 30% | 60–90 |
| C 臂：教师轨迹 | 32B-AWQ，1,500 题 × 8 条 = 1.2 万条，两个学生共用 | 20–35 |
| SFT 训练 | 每次 1.5k–5k 条轨迹 × 约 10k token × 最多 2 epoch，最多约 1 亿 token。4B 全参约 2.5 H100-h/次，1.7B 约 1。B、C 两臂 × 两个模型，再加 epoch 和数据量的扫描，约 12 次 | 20–40 |
| 合计 | | **100–170** |

硬件要求：

- 4B 全参训练时，权重、梯度和 AdamW 状态约 64 GB，要用 FSDP 分到至少 2 张 80 GB 卡上。序列超过 16k 时要开 gradient checkpointing。
- 生成轨迹是纯推理，可以用便宜一些的卡。但 72B-AWQ 光权重就有 39 GB，单卡至少要 48 GB 显存。
- GB10 不适合做这一步。基线时 1.7B 和 4B 每小时各约 45 题，2.4 万条要跑三周以上。

**RL。** 参考配置如下。

- 每步 64 题 × n=8 = 512 条轨迹，跑 200 步，相当于在 2,000–2,500 题的 RL 池上过 4–6 遍。
- 每条轨迹最多 16 轮、16k token。这个上限覆盖了 4B 基线约 95% 的轨迹。
- 用一个 8×H100 节点：6 张卡跑 actor 和 rollout（verl 同卡部署），2 张卡跑 72B-AWQ 模拟器（TP=2）。

| 每步 | 4B | 1.7B |
|---|---|---|
| rollout：受最长轨迹的延迟限制，不受吞吐限制 | 3–5 min | 3–5 min |
| 训练：actor 前向和反向、old logprob；不加 KL，所以不需要 ref；约 500 万 token | 1.5–2 min | 约 1 min |
| 权重同步等 | 约 0.5 min | 约 0.5 min |
| 每步合计 | 5–8 min | 4–6 min |
| 200 步的墙钟时间 | 17–27 h | 13–20 h |
| 一次运行（8 卡） | 140–215 H100-h | 110–160 H100-h |

| 项 | 次数 | H100-h |
|---|---|---|
| 校准和调试，每次 20–50 步 | 2–3 | 约 100 |
| A、B、C 三条主臂 × 1.7B、4B | 6 | 750–1,100 |
| E 臂：条件臂，只在 1.7B 需要时才跑 | 0–2 | 0–300 |
| B 臂再加两个种子：可选，GRPO 的方差大 | 0–4 | 0–750 |
| 合计 | | **850–1,200**；E 臂和多种子都跑约 2,200 |

**评测。** 用官方 72B 模拟器跑一遍完整的 DySQL（1,062 题）约要 2–3 H100-h。训练途中只用 200 题的内部 dev 集，每次约 0.5 H100-h。完整评测只留给以下几类 checkpoint，约 40 次，共 100–150 H100-h：

- 每次运行的终点，以及两三个中间 checkpoint；
- D 臂的 SFT checkpoint；
- F 臂换模拟器的复测。

终点评测也可以放在 GB10 上跑。基线时 1.7B 和 4B 并行跑完一遍约要 25 h。

**总量和换算。**

- 核心计划包括 SFT、RL 主臂和评测，约要 1,000–1,500 H100-h。E 臂和多种子都跑，约 2,500。
- 换成 A100-80GB 大约乘 2。解码吞吐看显存带宽，H100 是 A100 的 1.7 倍；训练看算力，两者差 2.5–3 倍。
- 不建议用 A100-40GB。72B-AWQ 光权重就有 39 GB，4B 全参的状态有 64 GB，也要至少 4 张卡。
- 6×RTX Pro 6000（每张 96 GB，没有 NVLink）：
  - 72B 模拟器只放 1 张卡时，预填充会成为瓶颈，所以给它 2 张卡，策略用剩下 4 张。
  - rollout 大致按 A100-80GB 估。FSDP 训练走 PCIe，会慢一些。
  - 一次 200 步的运行，4B 约 2 天，1.7B 约 1 天多。核心计划顺序跑完，约要 2–3 周机时。
- ACCESS 队列单次作业上限约 48 h，一次 4B 运行勉强装得下。每 20–25 步存一次 checkpoint，并确认能断点续训。

## 结论

这批文献改变了"要不要 SFT"这个问题的提法：对 1.7B/4B 的多轮用户–agent–DB 协议，SFT 的作用不是教 SQL，而是把 GRPO 需要的组内方差从"协议失败淹没一切"的状态里解放出来；一旦协议学会，所有 agentic SQL 论文都显示 RL 的增益来自 schema 定位和 SQL 正确性，而不是格式。你的诊断把这两段增益已经拆开了——协议修复值 ~24 分（4B）/ ~30 分（1.7B），RL 要争的是剩下到 32B 水平的那一段——所以实验的首要目标不是找最高分，而是验证"B 臂 SFT-only 就能兑现大半协议增益、RL 再给几分 SQL 增益"这条路径是否成立，以及 1.7B 是否真的站在 RL-only 的悬崖之下。

有两个前沿空白值得在写作时主动占位：写操作的最终 DB 状态奖励在 text-to-SQL RL 中没有先例，带模拟用户的小模型 SQL agent 训练也没有先例，你的实验若把"同族自举 vs 同族蒸馏"的冷启动对照和换模拟器的过拟合测量一并报告，就同时填上方法学文献（WinDOM 之后无 ≤4B 文本环境对照）和 SQL 文献的两个缺口。需要诚实标注的不确定性是：Qwen3 小模型在 thinking / non-thinking 模式下做 GRPO 的熵动态只有间接证据（GRPO 在 Qwen3 上早期熵塌缩、non-think 模式探索困难均为搜索摘要级），以及 GiGPO 的锚点分组在含随机用户文本的状态上是否仍有效，这两点应在首轮小规模实验中先测再定。

## 附录：文献索引（按主题）

| 主题 | 论文 | 基座 / 规模 | 冷启动 | 链接 |
|---|---|---|---|---|
| 单轮 SQL RL | Reasoning-SQL | Qwen2.5-Coder 3/7/14B | 无（SFT 仅作基线） | [abs](https://arxiv.org/abs/2503.23157) · [HTML](https://arxiv.org/html/2503.23157) · [v2](https://arxiv.org/html/2503.23157v2) |
| 单轮 SQL RL | SQL-R1 | Qwen2.5-Coder 3/7/14B | 无 / SynSQL-200K / OmniSQL | [HTML](https://arxiv.org/html/2504.08600) · [v5](https://arxiv.org/html/2504.08600v5) |
| 单轮 SQL RL | Arctic-Text2SQL-R1 | Qwen2.5-Coder 7/14/32B | OmniSQL checkpoint | [HTML](https://arxiv.org/html/2505.20315) · [v2](https://arxiv.org/html/2505.20315v2) |
| 单轮 SQL RL | Think2SQL | Qwen2.5-Coder 0.5–14B | 1,142 条 R1 轨迹 | [abs](https://arxiv.org/abs/2504.15077) · [HTML](https://arxiv.org/html/2504.15077) · [v5](https://arxiv.org/html/2504.15077v5) |
| 单轮 SQL RL | Graph-Reward-SQL | DeepSeek-Coder 1.3/6.7B | SFT warm-up | [HTML](https://arxiv.org/html/2505.12380) |
| 单轮 SQL RL | CSC-SQL | Qwen2.5-Coder 3–32B | 无 | [abs](https://arxiv.org/abs/2505.13271) · [HTML](https://arxiv.org/html/2505.13271) · [v2](https://arxiv.org/html/2505.13271v2) |
| 单轮 SQL RL | CogniSQL-R1-Zero | Qwen2.5-Coder-7B | 无 | [HTML](https://arxiv.org/html/2507.06013) |
| 单轮 SQL RL | ReEx-SQL | Qwen2.5-Coder-7B | 无 | [abs](https://arxiv.org/abs/2505.12768) · [HTML](https://arxiv.org/html/2505.12768) · [v2](https://arxiv.org/html/2505.12768v2) |
| 单轮 SQL | SQL-o1 | Llama3-8B 等 | SFT + MCTS | [HTML](https://arxiv.org/html/2502.11741) |
| 单轮 SQL | Alpha-SQL | 32B 零训练 | – | [abs](https://arxiv.org/abs/2502.17248) |
| SFT 数据源 | OmniSQL / SynSQL-2.5M | Qwen2.5-Coder 7/14/32B | 2.5M SFT | [abs](https://arxiv.org/abs/2503.02240) · [HTML](https://arxiv.org/html/2503.02240) · [PDF](https://arxiv.org/pdf/2503.02240) · [VLDB](https://www.vldb.org/pvldb/vol18/p4695-li.pdf) |
| 单轮 SQL RL | Reward-SQL | Qwen2.5-Coder-7B / Qwen3-8B | CoCTE 蒸馏 | [v1](https://arxiv.org/html/2505.04671v1) · [HTML](https://arxiv.org/html/2505.04671) |
| 单轮 SQL RL | DeepRetrieval | Qwen2.5(-Coder) 3B/7B | 四格消融 | [HTML](https://arxiv.org/html/2503.00223) · [v3](https://arxiv.org/html/2503.00223v3) |
| 单轮 SQL RL | SLM-SQL | 0.5–1.5B | SynSQL-Think-916K | [HTML](https://arxiv.org/html/2507.22478) · [ACL](https://aclanthology.org/2025.findings-ijcnlp.92.pdf) |
| 单轮 SQL RL | FINER-SQL | Qwen2.5-Coder 0.5–3B | 四教师 37.6K | [HTML](https://arxiv.org/html/2605.03465v1) |
| 单轮 SQL RL | RingSQL | 3–8B | 无 | [HTML](https://arxiv.org/html/2601.05451) · [PDF](https://arxiv.org/pdf/2601.05451) |
| 单轮 SQL RL | SQL-Zero | Qwen2.5-Coder 3/7B | 无（自博弈） | [HTML](https://arxiv.org/html/2609.04697) |
| 单轮 SQL | ExCoT | 70B / 32B | SFT + DPO | [HTML](https://arxiv.org/html/2503.19988) |
| 单轮 SQL | STaR-SQL | Llama-3.1-8B | 自举 | [HTML](https://arxiv.org/html/2502.13550) |
| 单轮 SQL RL | Sparks of Tabular Reasoning | 7B/8B | 3.5K 合成 CoT | [HTML](https://arxiv.org/html/2505.00016) |
| Reward hacking | Reinforcing Code Generation | SQLCoder/CodeGemma-7B | 无 | [HTML](https://arxiv.org/html/2506.06093) |
| Reward hacking | ConstrainedSQL | – | – | [abs](https://arxiv.org/abs/2511.09693v1) |
| 单轮 SQL RL | Agentar-Scale-SQL | OmniSQL-32B | OmniSQL | [HTML](https://arxiv.org/html/2509.24403) · [PDF](https://arxiv.org/pdf/2509.24403) |
| 多轮 SQL RL | AGRO-SQL | Qwen3-8B-Base | DeepSeek-V3.2 蒸馏 | [HTML](https://arxiv.org/html/2512.23366) |
| 多轮 SQL RL | ReToolSQL | Gemma 4 31B / E4B | 自身 rejection 轨迹 | [HTML](https://arxiv.org/html/2608.27796) · [v1](https://arxiv.org/html/2608.27796v1) · [PDF](https://arxiv.org/pdf/2608.27796) |
| 单轮 SQL | AutoThinkSQL | Qwen3-Coder-30B-A3B | 自身 rollout SFT+DPO | [HTML](https://arxiv.org/html/2607.22622) |
| 多轮 SQL RL | SkyRL-SQL | Qwen2.5-Coder-7B | 无 | [Substack](https://machinelearningatscale.substack.com/p/text-to-sql-just-got-a-lot-better) · [Notion](https://novasky-ai.notion.site/skyrl-sql) · [blog](https://novasky-ai.github.io/posts/skyrl-sql/) · [GitHub](https://github.com/NovaSky-AI/SkyRL) · [X](https://x.com/NovaSkyAI/status/1925592895010246863) · [docs(old)](https://skyrl.readthedocs.io/en/latest/recipes/skyrl-sql.html) · [docs](https://docs.skyrl.ai/docs/recipes/skyrl-sql) · [HF data](https://huggingface.co/datasets/NovaSky-AI/SkyRL-SQL-653-data) · [env.py](https://raw.githubusercontent.com/NovaSky-AI/SkyRL/main/skyrl-gym/skyrl_gym/envs/sql/env.py) · [utils.py](https://raw.githubusercontent.com/NovaSky-AI/SkyRL/main/skyrl-gym/skyrl_gym/envs/sql/utils.py) · [HF model](https://huggingface.co/NovaSky-AI/SkyRL-SQL-7B) |
| 多轮 SQL RL | MTSQL-R1 | Qwen3-1.7B / 4B | 三轮自举 SFT | [HTML](https://arxiv.org/html/2510.12831) · [PDF v3](https://arxiv.org/pdf/2510.12831v3) · [ACL](https://aclanthology.org/2026.acl-long.1563/) · [Amazon Science](https://www.amazon.science/publications/mtsql-r1-towards-long-horizon-multi-turn-text-to-sql-via-agentic-training) · [GitHub](https://github.com/taichengguo/MTSQL-R1) |
| 评测 | DySQL-Bench | – | 无训练 | [abs](https://arxiv.org/abs/2510.26495) · [HTML](https://arxiv.org/html/2510.26495) · [ACL](https://aclanthology.org/2026.findings-acl.1654/) · [GitHub](https://github.com/Aurora-slz/DySQL-Bench) |
| 评测 | BIRD-Interact | – | 无训练 | [abs](https://arxiv.org/abs/2510.05318) · [HTML](https://arxiv.org/html/2510.05318) |
| 多轮 SQL | Learning to Retrieve | GPT-5 策略 + Qwen3-4B 选择器 | PPO 选择器 | [HTML](https://arxiv.org/html/2606.00547) |
| 多轮 SQL | FlexSQL | gpt-oss-120b/20b | 无训练 | [HTML](https://arxiv.org/html/2605.02815) |
| 单轮 SQL RL | Human-Level Text-to-SQL via RL on Verified Data | Qwen3-235B / Kimi-K2.6 | – | [abs](https://arxiv.org/abs/2603.20004) |
| 多轮 SQL | Interactive-T2S | – | 提示 | [PDF](https://arxiv.org/pdf/2408.11062) |
| 评测 | TIDE-Bench | – | 无训练 | [abs](https://arxiv.org/abs/2608.29543) |
| 多轮 SQL | T2S-Agent | – | RL 改写 | [ACM DL](https://dl.acm.org/doi/10.1145/3811238.3811548) |
| 多轮 SQL RL | SQL-Trail | Qwen2.5-Coder 3/7/14B | 1,000 条 Claude 轨迹 | [ACL PDF](https://aclanthology.org/2026.acl-long.1677.pdf) · [HTML](https://arxiv.org/html/2601.17699) |
| 多轮 SQL RL | TRUST-SQL | Qwen3-4B / 8B | 70,970 条三教师轨迹 | [HTML v1](https://arxiv.org/html/2603.16448v1) · [abs](https://arxiv.org/abs/2603.16448) · [PDF](https://arxiv.org/pdf/2603.16448) |
| 多轮 SQL RL | MTIR-SQL | Qwen3-4B | 无 | [abs](https://arxiv.org/abs/2510.25510) · [HTML](https://arxiv.org/html/2510.25510) · [ICLR](https://iclr.cc/virtual/2026/10017469) |
| 多轮 SQL RL | MARS-SQL | Qwen2.5-Coder-7B | 无 | [HTML](https://arxiv.org/html/2511.01008) |
| 多轮 SQL RL | SQL-ASTRA | Qwen2.5-7B / OmniSQL-7B | 无 / Format-6k | [HTML](https://arxiv.org/html/2603.16161v1) |
| 多轮 SQL RL | SERL-SQL | Qwen2.5-Coder 7/14/32B | 无 | [HTML](https://arxiv.org/html/2608.00485v3) |
| 多轮 SQL RL | DualSQL | Qwen3-4B / 8B | 3,755 BIRD | [HTML](https://arxiv.org/html/2609.18135) |
| 小模型蒸馏 | Small Models Struggle to Learn from Strong Reasoners | Qwen2.5 0.5–32B | – | [abs](https://arxiv.org/abs/2502.12143) · [HTML](https://arxiv.org/html/2502.12143) |
| 小模型蒸馏 | BREAD | Qwen2.5-1.5B/3B | – | [abs](https://arxiv.org/abs/2506.17211) · [HTML](https://arxiv.org/html/2506.17211) |
| SFT vs RL | SFT or RL? (LVLM) | 2–7B | – | [HTML](https://arxiv.org/html/2504.11468v1) |
| 工具 RL | Nemotron-Tool-N1 | Qwen2.5 0.5–14B | 5,518 R1 轨迹 | [abs](https://arxiv.org/abs/2505.00024) · [HTML](https://arxiv.org/html/2505.00024) |
| 小模型蒸馏 | LS-Mixture SFT | – | – | [abs](https://arxiv.org/abs/2505.03469) |
| 小模型蒸馏 | Efficient Long CoT in SLMs | – | – | [abs](https://arxiv.org/abs/2505.18440) |
| 小模型蒸馏 | P-ALIGN | – | – | [abs](https://arxiv.org/abs/2601.10064) |
| 小模型蒸馏 | Distribution-Aligned Sequence Distillation | Qwen3-4B | – | [HTML](https://arxiv.org/html/2601.09088v1) |
| 小模型蒸馏 | HEAL | – | – | [abs](https://arxiv.org/abs/2603.10359) |
| SFT vs RL | RL vs Distillation | – | – | [abs](https://arxiv.org/abs/2505.14216) |
| 基础 | DeepSeek-R1 | – | 数千条冷启动 | [HTML](https://arxiv.org/html/2501.12948v1) |
| 自举 | RAFT revisit | – | – | [PDF](https://arxiv.org/pdf/2504.11343) |
| 自举 | WinDOM | Qwen3.5-2B | EMA 自教师 | [HTML](https://arxiv.org/html/2606.25964v1) |
| 自举 | RLoop | – | RFT 重初始化 | [abs](https://arxiv.org/abs/2511.04285) |
| 自举 | GLM-4.5 | – | 迭代自蒸馏 | [PDF](https://arxiv.org/pdf/2508.06471) |
| 自举 | SDFT | Qwen2.5-3/7/14B | 在线自蒸馏 | [HTML](https://arxiv.org/html/2601.19897v1) |
| 自举 | Stage-1 Controls the Entropy Regime | Qwen2.5-VL-7B | OPD vs SFT | [HTML](https://arxiv.org/html/2606.09059) |
| 自举 | CurioSFT | Qwen2.5-Math-7B / Qwen3-4B-Base | – | [HTML](https://arxiv.org/html/2602.02244v3) |
| 自举 | TS-OPSD | Qwen3-4B/8B-Base | – | [abs](https://arxiv.org/abs/2606.00755) |
| 自举 | Why Self-Distillation Degrades | Qwen3-1.7B/8B | – | [abs](https://arxiv.org/abs/2603.24472) |
| 理论 | RL's Razor | – | – | [abs](https://arxiv.org/abs/2509.04259) |
| 理论 | Tailor | – | – | [abs](https://arxiv.org/abs/2511.12429) |
| OPD | Thinking Machines On-Policy Distillation | Qwen3-8B | – | [blog](https://thinkingmachines.ai/blog/on-policy-distillation/) |
| SFT vs RL | SFT Memorizes, RL Generalizes | – | – | [abs](https://arxiv.org/abs/2501.17161) |
| SFT vs RL | RL Squeezes, SFT Expands | 1.5–14B | – | [abs](https://arxiv.org/abs/2509.21128v1) · [HTML](https://arxiv.org/html/2509.21128v1) |
| pass@k | Does RL Really Incentivize Reasoning | 7–32B | – | [abs](https://arxiv.org/abs/2504.13837) · [HTML](https://arxiv.org/html/2504.13837) |
| pass@k | The Invisible Leash | – | – | [abs](https://arxiv.org/abs/2507.14843) |
| pass@k | ProRL | 1.5B | – | [abs](https://arxiv.org/abs/2505.24864) |
| RL 细节 | Beyond the 80/20 Rule | Qwen3-8/14/32B | – | [abs](https://arxiv.org/abs/2506.01939) |
| zero-RL | SimpleRL-Zoo | Qwen2.5 0.5–32B | 无 | [abs](https://arxiv.org/abs/2503.18892) |
| SFT→RL | SFT-then-RL Outperforms Mixed-Policy | Qwen2.5-Math-7B / Llama-3.1-8B | 46k R1 | [abs](https://arxiv.org/abs/2604.23747) · [HTML](https://arxiv.org/html/2604.23747) |
| SFT→RL | Non-decoupling of SFT and RL | Qwen3-0.6B | – | [abs](https://www.arxiv.org/abs/2601.07389) |
| SFT→RL | Practical Two-Stage Recipe | – | 10 epoch SFT | [abs](https://arxiv.org/abs/2507.08267) |
| SFT→RL | Light-R1 | 14B | 课程 SFT | [HTML](https://arxiv.org/html/2503.10460v1) |
| SFT | SFT Doesn't Always Hurt | – | – | [abs](https://arxiv.org/abs/2509.20758) |
| 混合策略 | LUFFY | Qwen2.5-Math-7B 等 | – | [abs](https://arxiv.org/abs/2504.14945) · [HTML](https://arxiv.org/html/2504.14945) |
| 混合策略 | SRFT | Qwen2.5-Math-7B | – | [abs](https://arxiv.org/abs/2506.19767) · [HTML](https://arxiv.org/html/2506.19767) |
| 混合策略 | ReLIFT | Qwen2.5-Math-7B 等 | – | [abs](https://arxiv.org/abs/2506.07527) · [HTML](https://arxiv.org/html/2506.07527) |
| 混合策略 | CHORD | Qwen2.5-7B / 1.5B / Llama-3.2-3B | – | [abs](https://arxiv.org/abs/2508.11408) · [HTML](https://arxiv.org/html/2508.11408) |
| 混合策略 | SASR | – | – | [abs](https://arxiv.org/abs/2505.13026) |
| 混合策略 | TAPO / TemplateRL | – | – | [abs](https://arxiv.org/abs/2505.15692) |
| 混合策略 | BRIDGE | – | – | [abs](https://arxiv.org/abs/2509.06948) |
| 混合策略 | Scaf-GRPO | Qwen2.5-Math-1.5B/7B | – | [PDF](https://arxiv.org/pdf/2510.19807) · [HTML](https://arxiv.org/html/2510.19807v2) |
| 混合策略 | Guide | 0.5–72B | – | [abs](https://arxiv.org/abs/2506.13923) |
| 混合策略 | HiLL | – | – | [abs](https://arxiv.org/abs/2604.00698) |
| 混合策略 | DGPO | Qwen2.5-0.5B | KD 冷启动 | [HTML](https://arxiv.org/html/2508.20324) |
| 基座 | Qwen3 Technical Report | 0.6B–235B | 强到弱蒸馏 | [HTML](https://arxiv.org/html/2505.09388) · [PDF](https://arxiv.org/pdf/2505.09388) · [blog](https://qwenlm.github.io/blog/qwen3/) |
| OPD | SOD | Qwen3-0.6B/1.7B | 步级 OPD | [HTML](https://arxiv.org/html/2605.07725v1) |
| OPD | SEED | – | – | [PDF](https://arxiv.org/pdf/2607.14777) |
| 混合策略 | PACT | – | – | [abs](https://arxiv.org/abs/2606.16215) |
| RL 动态 | Entropy dynamics by base family / Agentic tool-calling RL efficiency | – | – | [PDF](https://arxiv.org/pdf/2606.00135) |
| RL 动态 | GEPO | Qwen3 | – | [PDF](https://arxiv.org/pdf/2508.17850) |
| RL 数据 | RLVR data-allocation (Qwen3-4B non-thinking) | Qwen3-4B | – | [PDF](https://arxiv.org/pdf/2605.26934) |
| 少样本 SFT | LIMO | Qwen2.5-32B | 817 条 | [abs](https://arxiv.org/abs/2502.03387) |
| 工具 RL | ToolRL | Qwen2.5-1.5/3/7B, Llama-3.2-3B | SFT-400 vs 无 | [abs](https://arxiv.org/abs/2504.13958) · [HTML](https://arxiv.org/html/2504.13958) · [HTML v1](https://arxiv.org/html/2504.13958v1) |
| 工具 RL | EnvFactory | Qwen3-1.7B/4B/8B | 1,622 条 SFT | [HTML](https://arxiv.org/html/2605.18703) |
| 基础 | Magistral | 24B | – | [abs](https://arxiv.org/abs/2506.10910) |
| 学生中心蒸馏 | SCoRe | Qwen2.5-3B/7B, Qwen3-8B | 20% BC + 教师修正 | [HTML](https://arxiv.org/html/2509.14257v3) |
| agentic 小模型 | AgenticQwen | 8B / 30B-A3B | – | [HTML](https://arxiv.org/html/2604.21590v1) |
| SFT 深度 | SFT over-training | Qwen2.5-Coder-3B-Base | – | [HTML](https://arxiv.org/html/2606.18487v1) |
| SFT 深度 | When RL Fails after SFT | – | – | [abs](https://arxiv.org/abs/2606.09932) |
| 用户模拟 RL | UserRL | Qwen3-4B/8B | 5K GPT-4o 轨迹 | [abs](https://arxiv.org/abs/2509.19736) · [HTML](https://arxiv.org/html/2509.19736) · [HTML v1](https://arxiv.org/html/2509.19736v1) |
| 用户模拟 评测 | UserBench | – | – | [abs](https://arxiv.org/abs/2507.22034) |
| 用户模拟 RL | BAO | Qwen3-1.7B/4B | GPT-4o 行为提示 SFT | [HTML](https://arxiv.org/html/2602.11351) |
| 用户模拟 RL | MUA-RL | Qwen3-8/14/32B | ~2,000 条 | [abs](https://www.arxiv.org/abs/2508.18669) · [HTML](https://arxiv.org/html/2508.18669) · [PDF](https://arxiv.org/pdf/2508.18669) |
| 用户模拟 RL | FACA | Qwen3-8B/14B | MUA-RL 1,580 条 | [HTML](https://arxiv.org/html/2608.17499) · [abs](https://arxiv.org/abs/2608.17499) |
| 用户模拟 数据 | APIGen-MT / xLAM-2 | Llama / Qwen2.5 1B–70B | 5K 轨迹 BC | [HTML](https://arxiv.org/html/2504.03601) · [abs v4](https://arxiv.org/abs/2504.03601v4) · [HF](https://huggingface.co/Salesforce/Llama-xLAM-2-8b-fc-r) |
| 用户模拟 RL | SWEET-RL / ColBench | Llama-3.1-8B | 离线 | [HTML](https://arxiv.org/html/2503.15478) · [abs](https://arxiv.org/abs/2503.15478) |
| 用户模拟 RL | CollabLLM | Llama-3.1-8B | 500 样本 | [HTML](https://arxiv.org/html/2502.00640v3) |
| 用户模拟 RL | IntentRL | Qwen2.5-7B | 371 条离线 | [HTML](https://arxiv.org/html/2602.03468) |
| 用户模拟 RL | AskBench | Qwen2.5-7B | 无 | [HTML](https://arxiv.org/html/2602.11199v1) |
| 用户模拟 RL | Steerable clarification self-play | Gemma 2 2B/9B, Qwen3-4B | ReST | [HTML](https://arxiv.org/html/2512.04068) |
| 用户模拟 RL | Calibrated Interactive RL | Gemma-3-4B | – | [HTML](https://arxiv.org/html/2605.26403) |
| 用户模拟 RL | WMG-RL | 1.7B | – | [abs](https://arxiv.org/abs/2609.01067v1) |
| agent RL | EnvACE | – | – | [PDF](https://arxiv.org/pdf/2608.06197) |
| agent RL | Early Experience | Llama-3.2-3B 等 | 自生成 | [HTML](https://arxiv.org/html/2510.08558) |
| credit | GiGPO | Qwen2.5-1.5/3/7B | 无 | [HTML](https://arxiv.org/html/2505.10978) · [verl-agent](https://github.com/langfengQ/verl-agent) |
| 稳定器 | RAGEN / StarPO | Qwen2.5-0.5B/3B | – | [HTML](https://arxiv.org/html/2504.20073v2) |
| 课程 | AgentGym-RL | Qwen2.5-3B/7B | 无 | [abs](https://arxiv.org/abs/2509.08755) · [review](https://www.themoonlight.io/en/review/agentgym-rl-training-llm-agents-for-long-horizon-decision-making-through-multi-turn-reinforcement-learning) |
| credit | SPA-RL | – | – | [abs](https://www.arxiv.org/abs/2505.20732) |
| credit | RLVMR | 7B | – | [abs](https://arxiv.org/abs/2507.22844v1) |
| 框架 | Agent Lightning | – | – | [abs](https://arxiv.org/abs/2508.03680v1) |
| credit | AgentFlow / Flow-GRPO | Qwen2.5-7B | – | [abs](https://arxiv.org/abs/2510.05592) |
| 稳定器 | SimpleTIR | Qwen2.5-7B | – | [PDF](https://arxiv.org/pdf/2509.02479) |
| 记忆 | MEM1 | 7B | – | [abs](https://arxiv.org/abs/2506.15841v1) |
| 大规模 | Tongyi DeepResearch | – | rejection SFT | [HTML](https://arxiv.org/html/2510.24701) |
| 大规模 | Kimi K2 | – | – | [HTML](https://arxiv.org/html/2507.20534) |
| 大规模 | Demystifying RL in Agentic Reasoning | 4B | 3K 真实轨迹 | [HTML](https://arxiv.org/html/2510.11701) |
| 模拟器 | tau-bench | – | – | [PDF](https://arxiv.org/pdf/2406.12045) |
| 模拟器 | CUE | – | – | [HTML](https://arxiv.org/html/2610.02460v1) |
| 模拟器 | UserProxyBench | – | – | [abs](https://arxiv.org/abs/2609.38043) |
| 模拟器 | Sim2Real gap | – | – | [HTML](https://arxiv.org/html/2603.11245) |
| 模拟器 | Non-collaborative simulators | – | – | [abs](https://arxiv.org/abs/2509.23124) |
| 模拟器 | Survey on LLM-based User Simulation | – | – | [survey](https://www.opentrain.ai/papers/a-survey-on-llm-based-conversational-user-simulation--arxiv-2604.24977/) |
| 蒸馏 | Smaller Models, Better Rejects | 7–72B | – | [abs](https://arxiv.org/abs/2609.38987) |
| 蒸馏 | Finetuning with Sampling | – | – | [abs](https://arxiv.org/abs/2610.02140) |
