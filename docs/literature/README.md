# literature：文献调研

为训练阶段（SFT + RL）做的文献调研。报告给结论和实验设计建议，笔记是每个主题的原始材料，每个数字都带原文链接。

| 文档 | 内容 |
|---|---|
| [2026-10-07-sft-rl-cold-start-survey.md](2026-10-07-sft-rl-cold-start-survey.md) | 报告：小模型多轮 SQL agent 的 SFT 冷启动怎么选，奖励和用户模拟器怎么设计，实验该比哪几个臂，各要多少算力 |
| [2026-10-07-sft-rl-survey-notes/](2026-10-07-sft-rl-survey-notes/) | 报告依据的四份分主题笔记，见下表 |

笔记：

| 文件 | 主题 |
|---|---|
| [single-turn-text2sql-rl.zh.md](2026-10-07-sft-rl-survey-notes/single-turn-text2sql-rl.zh.md)（[英文原稿](2026-10-07-sft-rl-survey-notes/en/single-turn-text2sql-rl.md)） | 单轮 text-to-SQL 的 reasoning-RL：哪些跳过 SFT，SFT-vs-RL 消融，奖励设计 |
| [multi-turn-text2sql-rl.zh.md](2026-10-07-sft-rl-survey-notes/multi-turn-text2sql-rl.zh.md)（[英文原稿](2026-10-07-sft-rl-survey-notes/en/multi-turn-text2sql-rl.md)） | 多轮 / agentic text-to-SQL 的 RL：MTSQL-R1、SkyRL-SQL、TRUST-SQL、SQL-Trail 等的完整配方 |
| [sft-rl-methodology-small-models.zh.md](2026-10-07-sft-rl-survey-notes/sft-rl-methodology-small-models.zh.md)（[英文原稿](2026-10-07-sft-rl-survey-notes/en/sft-rl-methodology-small-models.md)） | 小模型 SFT + RL 方法学：蒸馏 vs 自举 vs 不做 SFT，混合策略方法，Qwen3 小模型的来历 |
| [user-agent-agentic-rl.zh.md](2026-10-07-sft-rl-survey-notes/user-agent-agentic-rl.zh.md)（[英文原稿](2026-10-07-sft-rl-survey-notes/en/user-agent-agentic-rl.md)） | 带模拟用户的通用 agent RL：UserRL、BAO、MUA-RL、FACA，模拟器泄漏与 reward hacking |

范围：2025-01 至 2026-09 的论文，约 90 篇。报告和笔记都是中文；笔记的英文原稿在 `en/`。
引用前请核对原文：SLM-SQL 的 BIRD 数字和 MTIR-SQL 的 Spider-dev 数字在不同版本之间不一致，报告里已标出。
