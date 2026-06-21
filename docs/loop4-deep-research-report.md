# Loop 4 / Hill Climbing Loop 深度研究报告
**LLM Agent 自动改进层的现状全景**

---

## 1. 执行摘要

Loop 4（Hill Climbing Loop）的核心理念是：将生产环境的 agent traces 自动喂入分析 agent，后者识别失败模式并生成 harness（提示词、工具、技能等）改进方案，循环反复。截至 2026 年 6 月，**这一层在开源生态中存在明确空白**：成熟的可观测性工具（Langfuse、Arize Phoenix、MLflow）覆盖 Loops 1-3，而真正端到端的 Loop 4 管道——从生产 traces 到自动失败归因，再到 harness 代码/提示更新并验证回归——目前只有 LangSmith Engine（专有闭源）最接近完整实现。开源侧已有多个强相关项目涌现（HALO、Meta-Harness、RHO、EPOCH、MOSS 等），但多数仍在学术论文阶段，尚未形成一个成熟的"全栈 Loop 4 开源工具"。学术界在 2025-2026 年爆发了大量研究，ICLR 2026 首次设立递归自我改进专题 Workshop，社区共识是：这一层的自动化是最高价值杠杆，但也是最危险的，需要人类保留最终审核权。

---

## 2. Loop 4 专项工具盘点

### 2.1 商业闭源方案（最接近完整 Loop 4）

#### LangSmith Engine（LangChain，2026年5月发布）

**定位**：目前最接近完整 Loop 4 的产品实现。

**工作机制**：
- 自动聚类生产失败 traces 为命名 Issue（而非逐条显示每次失败）
- 对每个 Issue 执行根因分析，定位到具体代码/提示行
- 草拟修复方案（提示词改写或代码修改），支持直接向关联 GitHub 仓库开 PR
- 循环：改进上线 → 新 traces 产生 → Engine 再次分析

**可用性**：公测 Beta 阶段，LangSmith Plus / Enterprise Cloud 客户可用，**不开源**。

**相关链接**：
- [Introducing LangSmith Engine](https://www.langchain.com/blog/introducing-langsmith-engine)
- [Improve agent quality with Insights Agent and Multi-turn Evals](https://blog.langchain.com/insights-agent-multiturn-evals-langsmith/)
- [VentureBeat 分析](https://venturebeat.com/orchestration/langsmith-engine-closes-the-agent-debugging-loop-automatically-but-multi-model-enterprises-still-need-a-neutral-layer)

#### Braintrust Loop（商业 SaaS）

**定位**：接近 Loop 4 的半自动工具。

**工作机制**：
- Topics 功能用 ML 聚类生产流量，自动浮现用户意图、情绪分布和 emerging failures
- "Loop" 是内置 AI Agent，分析 eval 失败模式，自动提议更优提示词版本，生成针对薄弱环节的测试用例，并自动迭代运行 evals
- 生产 traces 一键转为测试用例

**注意**：纯 SaaS，无自托管选项，所有 trace 数据存储在 Braintrust 基础设施上。

**链接**：[Braintrust](https://www.braintrust.dev/)

---

### 2.2 开源/学术方案（直接针对 Loop 4 核心场景）

| 项目 | 核心方法 | 是否需要预标注数据集 | 目标改进范围 | 状态 |
|---|---|---|---|---|
| **HALO** (context-labs) | RLM 分析执行 traces，生成改进建议报告喂给 coding agent | 否（分析生产 traces） | 提示词、工具定义、路由逻辑 | 开源，有 PyPI 包 |
| **RHO** (arXiv 2606.05922) | 自监督，从无标签过去轨迹自我优化，用 self-preference 选最佳 harness 变更 | 否（完全无标签） | 提示词、工具、工作流 | 学术论文 + GitHub 代码 |
| **Meta-Harness** (Stanford, arXiv 2603.28052) | 给 coding agent 完全文件系统访问权限访问原始执行 traces，迭代改写 harness | 需要评估标准 | 检索逻辑、内存管理、提示装配 | 学术论文 + GitHub |
| **EPOCH** (arXiv 2603.09049) | 将优化组织为"基线构建 + 迭代自改进"两阶段，角色约束隔离规划/实现/评估 | 需要验证基准 | 提示词、模型配置、代码、规则 | 学术论文 |
| **MOSS** (arXiv 2605.22794) | 从生产失败证据中自动策划批次，通过多阶段管道进行源码级别自我重写 | 否（生产失败为锚点） | 源码级别（最广泛的改进范围） | 学术论文 |
| **GEPA** (gepa-ai/gepa, ICLR 2026 Oral) | LLM 读取完整执行 traces（错误、分析日志）诊断失败，提议 Pareto 优化的提示词变体 | 需要 eval 指标，不需要预标注 | 提示词优化 | 开源 MIT，集成进 MLflow |
| **ROAD** (arXiv 2512.24040) | 多智能体架构（Analyzer + Optimizer + Coach），将非结构化错误模式转化为刚性逻辑框架 | 否（处理 messy 生产日志） | 提示词 | 学术论文 |
| **SkillClaw** (arXiv 2604.08377) | 聚合使用过程中产生的轨迹，自动演化 skill 集合（精炼现有 skill 或新建） | 否（跨用户交互为信号） | Skills（代码级工具定义） | 学术论文 |
| **SkillSmith** (arXiv 2606.01314) | Skill + Tool 联合演化，用 Lotka–Volterra 生态效用模型指导突变优先级 | 需执行反馈 | Skills + Tools 协同 | 学术论文 |
| **AgentFactory** (arXiv 2603.18000) | 将成功任务解决方案保存为可执行 subagent 代码，持续根据执行反馈精炼 | 否（执行反馈即信号） | 子智能体代码库 | 开源（Peking U） |
| **Darwin Gödel Machine** (Sakana AI, 2025) | 达尔文进化式，coding agent 修改自身代码库，用编程 benchmark 验证变更 | 需要 benchmark | 完整 agent 代码库 | 开源 GitHub |
| **VeRO** (Scale AI, arXiv 2602.22480) | 外层评估 harness，提供版本化快照、预算受控评估、结构化执行 traces | 需要参考评估过程 | Harness 代码优化 | 学术论文 + GitHub |

#### HALO 详细说明（最接近生产可用的开源 Loop 4 工具）

HALO（Hierarchical Agent Loop Optimizer）是目前**最接近生产可用**的开源 Loop 4 工具：
- **输入**：生产 agent 执行 traces（无需预标注）
- **分析**：识别幻觉工具调用、冗余参数、拒绝循环、语义正确性问题
- **输出**：结构化 HALO 报告 → 喂给 Cursor/Claude Code 等 coding agent → 生成 harness 变更
- **反馈**：重新部署 → 收集更多 traces → 循环

**Benchmark 结果**：在 AppWorld benchmark 上，对 Gemini 3 Flash 提升 +15.8pp（dev），对 Claude Sonnet 4.6 提升 +15.8pp（dev）。

**可用性**：GitHub `context-labs/HALO`，PyPI `halo-engine`。

---

### 2.3 相关观测/评估平台（覆盖 Loop 4 部分子任务）

| 工具 | 许可 | Loop 4 覆盖范围 | 关键差距 |
|---|---|---|---|
| **Langfuse** (29.5k stars) | MIT | Traces + Evals + Prompt 管理 | 无自动失败分析 → 改进提案流程 |
| **MLflow** (30M+ 月下载) | Apache 2.0 | Traces + GEPA/MIPROv2 提示优化 | 需手动触发优化，无自动聚类失败 |
| **Arize Phoenix** | Elastic 2.0 | Traces + 50+ eval 指标 + 多步 agent 轨迹分析 | 无 auto-improve 建议 |
| **Laminar** | Apache 2.0 | Traces + Signals + SQL-over-traces | 无 auto-improve |
| **Traceloop** | Apache 2.0 | 生产级 agent 可观测性 | 专注可观测，无优化层 |

---

## 3. 社区视角

### 3.1 LangChain 的框架定义（最权威的 Loop 4 公开阐述）

Harrison Chase（LangChain CEO）和 Sydney Runkle 在["The Art of Loop Engineering"](https://www.langchain.com/blog/the-art-of-loop-engineering) 中首次系统性地将 Loop 4 命名为"Hill Climbing Loop"，核心思想是：

> "每次 agent 运行都会产生 trace，Hill Climbing Loop 用分析 agent 分析这些 traces，并用发现的问题重写 harness 配置。"

swyx 将这一实践称为 **"loopcraft"**，并认为"价值应向第 3、4 环路倾斜，在那里 agent 不断响应你的标准而持续改进"。

随后 LangChain 在 2026 年 4 月发布 ["Better Harness: A Recipe for Harness Hill-Climbing with Evals"](https://blog.langchain.com/better-harness-a-recipe-for-harness-hill-climbing-with-evals/)，提出了六步操作方法论，核心观点是：**evals 是 harness 工程师的训练数据**。

### 3.2 Karpathy 的 AutoResearch Loop（2026 年最具影响力的 Loop 4 实践案例）

Andrej Karpathy 于 2026 年 3 月发布 [`karpathy/autoresearch`](https://github.com/karpathy/autoresearch)（约 630 行 Python），在 5 天内累积 25,000 GitHub Stars，4 月初超过 80,000 Stars。

**工作模式**：给 coding agent 一个可编辑文件 + 冻结的评估器 + 一个标量指标 → 运行 keep-or-revert 循环。一夜之间执行 700 次实验，发现 20 个优化，使大型模型加速 11%。

该项目被命名为 **"Karpathy Loop"**，随后扩散到提示优化、GPU 内核调优、构建时间减少、测试套件加速等多个领域。

**关键启示**：Loop 4 的本质不依赖特定框架，只需 3 个原语：(1) 可变目标文件，(2) 冻结的客观评估器，(3) 标量分数，其余全部可 DIY。

### 3.3 Langfuse 的警告：防范"Agent Slop"

Langfuse 在 2026 年 6 月 9 日的博文 ["AI is eating the AI engineering loop"](https://langfuse.com/blog/2026-06-09-ai-is-eating-ai-engineering) 中发出了最权威的反向警告：

> **"Agent slop" = 由其他 AI agent 大规模生产的低质量 AI agent**。这是 agent 在不完美 eval 和数据集上过度优化的结果。

> "如果你只读 agent 或已设置的 evaluator 标记给你看的 traces，你只能看到它已经被告知去寻找的东西。你需要定期抽样 traces 并亲自阅读它们。"

Langfuse 的立场是：**AI 可以接管 Loop 4 的大部分步骤，但自动化超过人类能为输出质量背书的范围会导致灾难**。

### 3.4 Airbnb 的生产案例

Airbnb 工程团队在 ["Agent-in-the-Loop: A Data Flywheel for Continuous Improvement in LLM-based Customer Support"](https://arxiv.org/abs/2510.06674)（EMNLP 2025 Industry Track）中记录了真实产品级 Loop 4：

- **框架**：AITL（Agent-in-the-Loop），将成对回答偏好、人工客服采纳信号、知识相关性检查等 4 类标注直接整合进实时客服操作
- **结果**：检索准确率 +11.7%（recall@75），生成质量 +8.4%（helpfulness），客服采纳率 +4.5%
- **关键**："闭环反馈将模型再训练周期从月缩短到周"

### 3.5 OpenAI 的 Codex Cookbook 实现

OpenAI 在其 Cookbook 中发布 ["Build an Agent Improvement Loop with Traces, Evals, and Codex"](https://developers.openai.com/cookbook/examples/agents_sdk/agent_improvement_loop)，展示了一个完整 Loop 4 DIY 实现：
- 从真实 traces 出发 → 添加人工和模型反馈 → 转化为 evals → 生成 `codex_handoff.md` → 交给 Codex 实施下一次 harness 变更

---

## 4. 学术研究动态

### 4.1 ICLR 2026 递归自我改进专题 Workshop

[ICLR 2026 Workshop on AI with Recursive Self-Improvement](https://iclr.cc/virtual/2026/workshop/10000796)（2026 年 4 月 26 日，里约热内卢）是学术界首个将递归自我改进作为独立工程学科的重要会场，共收录 110 篇论文，涵盖自我博弈、自动化 AI 研究、持续学习和自我演化 agent 等。

### 4.2 关键论文梳理

**[Meta-Harness: End-to-End Optimization of Model Harnesses](https://arxiv.org/abs/2603.28052)**（Stanford, 2026 年 3 月）
- 给 coding agent 原始执行 traces 的完整文件系统访问权限，迭代编程定制检索逻辑、内存管理和提示装配架构
- 在 IMO 级数学题上平均提升 4.7 分，在 TerminalBench-2 编码任务上超越最优手工基线
- **关键洞察**：现有文本优化器压缩反馈过于激进，将原始执行 traces 直接暴露给 coding agent proposer 比仅用 benchmark 分数驱动改进更有效

**[RHO: Evolving Agents in the Dark](https://arxiv.org/abs/2606.05922)**（City Univ. Hong Kong + Microsoft Research Asia, 2026 年 6 月）
- **最接近 Loop 4 "完全无标注"场景**的算法
- 从过去轨迹中用行列式点过程选取多样性难题子集，并行重解，通过 self-validation + self-consistency + pairwise self-preference 选出最佳 harness 变更
- SWE-Bench Pro pass rate: 59% → 78%（无外部评分）
- **关键价值**：真实部署中几乎没有标注验证集，RHO 填补了这一空白

**[MOSS: Self-Evolution through Source-Level Rewriting](https://arxiv.org/abs/2605.22794)**（2026 年 5 月）
- 批评现有自演化 agent 只改文本可变 artifact（skill 文件、提示配置），留下 agent harness 本身不动
- MOSS 实现源码级别适应，每次演化锚定自动策划的生产失败证据批次
- 在 claweval benchmark 上单轮迭代将 mean grader score 从 0.25 提升到 0.61

**[EPOCH: An Agentic Protocol for Multi-Round System Optimization](https://arxiv.org/abs/2603.09049)**（ProRata.ai, 2026 年 3 月）
- 将优化结构化为两阶段：基线构建 + 迭代自改进
- 通过角色约束的阶段分离（规划、实现、评估），同时优化提示词、模型配置、代码和规则组件
- 保留稳定性、可复现性、可追溯性和评估完整性

**[GEPA: Reflective Prompt Evolution Can Outperform RL](https://arxiv.org/abs/2507.19457)**（ICLR 2026 Oral）
- LLM 读取**完整执行 traces**（错误消息、分析数据、推理链），而非像 RL 方法那样将 trace 压缩为单一奖励标量
- 比 MIPROv2 高 10+ 个百分点（AIME-2025 上 +12pp）
- 开源，已集成进 MLflow；关键差异是 GEPA **需要 eval 指标**，仍非完全从生产 traces 端到端

**[ROAD: Reflective Optimization via Automated Debugging](https://arxiv.org/abs/2512.24040)**（2025 年 12 月）
- 专门针对 **cold start 场景**：在 agent 开发初期，curated dataset 还不存在，只有杂乱的生产日志
- 三 agent 架构（Analyzer / Optimizer / Coach），将非结构化错误模式转为刚性逻辑框架

**[SePO: Self-Evolving Prompt Agent](https://arxiv.org/html/2606.04465)**（2026 年 6 月）
- 自我指涉设计：优化目标包括提示 agent 自身，使改进能突破手工设计提示 agent 的上限

**[Darwin Gödel Machine](https://arxiv.org/abs/2505.22954)**（Sakana AI, 2025 年 5 月，ICLR 2026 发表）
- 开放性进化，迭代修改自身代码并用编程 benchmark 实证验证
- SWE-bench: 20% → 50%，Polyglot: 14.2% → 30.7%
- 开源：[github.com/jennyzzt/dgm](https://github.com/jennyzzt/dgm)

**[Self-Evolving Agents 综合综述](https://arxiv.org/abs/2507.21046)**（2026 年 1 月更新）
- 从"什么演化/何时演化/如何演化/在哪演化"四维组织领域
- 区分 intra-test-time vs inter-test-time 自演化，总结奖励/模仿/种群三大方法族
- 关联 GitHub awesome list：[XMUDeepLIT/Awesome-Self-Evolving-Agents](https://github.com/XMUDeepLIT/Awesome-Self-Evolving-Agents)

**[Airbnb Agent-in-the-Loop: Data Flywheel](https://arxiv.org/abs/2510.06674)**（EMNLP 2025）
- 唯一大规模产业级 Loop 4 案例研究，直接从实时客服操作中提取 4 类信号形成持续训练飞轮

**[SkillClaw: Let Skills Evolve Collectively](https://arxiv.org/abs/2604.08377)**（2026 年 4 月）
- 将跨用户、随时间的交互作为 skill 改进的主信号，在共享仓库中同步改进，一用户的发现传播给所有用户

**[SkillSmith: Co-Evolving Skills and Tools](https://arxiv.org/abs/2606.01314)**（2026 年 6 月）
- Lotka–Volterra 生态效用模型估计 skill 间互补/冲突，同时演化 skills 和 tools

**[VCC: View-oriented Conversation Compiler for Agent Trace Analysis](https://arxiv.org/abs/2603.29678)**（2026 年 3 月，Lvmin Zhang & Maneesh Agrawala）
- 将原始 agent JSONL 日志编译成结构化视图族，是 Loop 4 分析工具链的基础设施层

**[Failure Attribution in Multi-Agent Systems](https://arxiv.org/abs/2505.00212)**
- 自动归因方法：对失败多 agent 交互提供完整执行轨迹，找出负责任的 agent 和决定性错误步骤
- 当前准确率：53.5%（识别失败 agent）/ 14.2%（定位失败步骤）——仍有巨大改进空间

---

## 5. 实践模式：团队如何 DIY Loop 4

### 模式 A：Karpathy Loop（最简单，适用于有标量指标的场景）

**原语**：可变目标文件 + 冻结评估器 + 标量分数

```
agent 运行 → 提议变更 → 评估 → 分数提升则提交，否则回滚 → 循环
```

**典型案例**：Karpathy autoresearch（overnight 700 次实验，11% 性能提升）

**局限**：需要预先有可量化的冻结评估器，不能处理无标签生产 traces 场景。

### 模式 B：Airbnb Data Flywheel 模式（最成熟的产业实践）

```
生产 traces → 人工客服内嵌标注（偏好/采纳/知识检查）→ 形成训练信号 → 模型微调/提示改进 → 重新部署
```

**关键**：将标注工作整合进现有人工流程（不是额外工作），飞轮自然转动。

**适用场景**：有人工在回路的高流量生产环境（客服、内容审核等）。

### 模式 C：OpenAI Codex Cookbook 模式（结合 LLM-as-judge + coding agent）

```
生产 traces → LLM-as-judge 评分 → 人工审核高价值失败案例 → 生成 codex_handoff.md → 交给 Codex/Claude Code 实施 harness 变更 → PR 审核合并
```

**关键创新**：用 `codex_handoff.md` 作为结构化交接文件，保留每次循环的学习成果。

**适用场景**：有 DevOps 文化的工程团队，希望保持人工审核。

### 模式 D：HALO 驱动的自动化 Loop 4（最接近端到端开源实现）

```
生产 traces → HALO Engine 分析（识别幻觉调用/冗余参数/语义问题）→ 结构化报告 → 喂给 Claude Code/Cursor → 生成 harness 变更 → 重新部署 → 收集更多 traces → 循环
```

**特点**：
- 无需人工阅读 traces，HALO 负责模式识别
- 保留人工审核差异（diff review 后合并）
- 已有 benchmark 验证（AppWorld: +15.8pp）

### 模式 E：合成数据飞轮（硬核版，适用于无人工标注环境）

```
agent traces → 合成 eval 集生成（hill-climb eval set 本身）→ skill 文件作为约束条件 → coding agent proposer → 新 eval → 循环
```

**特点**：整个系统随时间改善（dataset 扩展、skill 文件精化、失败 cluster 收缩），但没有任何单个组件在编辑自身。

---

## 6. 结论与空白：bourbon 在设计自己的 Loop 4 之前需要知道的

### 6.1 当前 OSS 生态空白的精确定位

```
生产 traces               ← 已有很多工具（Langfuse, Phoenix, MLflow）
      ↓
自动失败聚类 + 根因归因   ← HALO（实验性），LangSmith Engine（闭源）
      ↓
生成改进提案              ← HALO/EPOCH/Meta-Harness（学术）
      ↓
实施到 harness（PR/diff） ← 无成熟 OSS 工具（OpenAI Cookbook 是 notebook 示例）
      ↓
回归验证                  ← 需手动，无自动化 OSS 工具
      ↓
上线 → 新 traces          ← 循环闭合，无成熟 OSS 工具
```

**最大空白**：从"失败聚类"到"harness PR"再到"自动回归验证"的**端到端闭合管道**，目前没有成熟的开源实现。

### 6.2 核心技术挑战

1. **无标签 traces 的质量信号提取**：大多数工具仍需要某种形式的 eval 指标；RHO（self-preference）和 MOSS（生产失败自动策划）是目前最前沿的解法。

2. **失败归因的准确性问题**：当前 SOTA 只能以 53.5% 准确率定位到失败 agent，14.2% 定位到失败步骤——这是自动化 Loop 4 最薄弱的环节。

3. **Overfitting/Agent Slop 风险**：自动优化很容易让 agent 对不完美的 eval 过拟合。Langfuse、LangChain 等都在强调**人工最终审核**的不可或缺性。

4. **源码级 vs 文本级改进的权衡**：改文本 artifact（提示词、skill 文件）风险低但范围有限；改源码（MOSS 路线）范围最广但风险最高，需要强健的回滚机制。

### 6.3 bourbon 的设计建议

1. **分层设计**：先实现"trace 聚类 + 人工审核"，再逐步自动化到"改进提案生成"，最后才考虑"自动实施 + 回归验证"，切忌跳步。

2. **冻结评估器先于自动改进**：bourbon 若要做 Loop 4，必须先有可靠的 eval 层（`promptfoo` 已存在），Loop 4 的价值完全依赖 eval 层的质量。

3. **优先实现 HALO 类 pattern**：HALO 的思路最务实——不尝试完全自动化，而是生成结构化诊断报告交给 coding agent（Claude Code 自身！）执行。bourbon 可以利用自身已有的 subagent 系统和 memory 层实现类似闭环。

4. **将 "harness 变更建议" 作为 Memory 的一等公民**：bourbon 的 `MemoryStore` 可以存储演化历史，每次循环的发现作为 memory 写入，形成可追溯的改进日志。

5. **参考 MOSS 的"生产失败锚定"机制**：bourbon 已有 `pre-compact flush` 机制，可以在压缩前提取失败信号，这正是 MOSS 自动失败证据策划的核心理念。

6. **警惕 "agent slop" 风险**：任何自动改进 harness 的变更，必须经过人工 diff 审核后才能生效，不应完全绕开人工。

---

## 参考链接汇总

**核心概念**
- [The Art of Loop Engineering (LangChain)](https://www.langchain.com/blog/the-art-of-loop-engineering)
- [Better Harness: A Recipe for Harness Hill-Climbing with Evals (LangChain)](https://blog.langchain.com/better-harness-a-recipe-for-harness-hill-climbing-with-evals/)
- [AI is eating the AI engineering loop (Langfuse, Jun 2026)](https://langfuse.com/blog/2026-06-09-ai-is-eating-ai-engineering)

**商业工具**
- [LangSmith Engine](https://www.langchain.com/langsmith/engine)
- [Introducing LangSmith Engine (blog)](https://www.langchain.com/blog/introducing-langsmith-engine)
- [Insights Agent (LangSmith)](https://blog.langchain.com/insights-agent-multiturn-evals-langsmith/)
- [Braintrust Loop feature](https://www.braintrust.dev/)

**开源工具**
- [HALO: Hierarchical Agent Loop Optimizer (GitHub)](https://github.com/context-labs/halo)
- [Darwin Gödel Machine (GitHub)](https://github.com/jennyzzt/dgm)
- [GEPA (GitHub)](https://github.com/gepa-ai/gepa)
- [AgentFactory (GitHub)](https://github.com/zzatpku/AgentFactory)
- [RHO: Retrospective Harness Optimization (GitHub)](https://github.com/wbopan/retro-harness)
- [VCC: View-oriented Conversation Compiler (GitHub)](https://github.com/lllyasviel/VCC)
- [Karpathy autoresearch (GitHub)](https://github.com/karpathy/autoresearch)
- [MLflow Prompt Optimization (GEPA/MIPROv2)](https://mlflow.org/prompt-optimization)

**学术论文**
- [Meta-Harness (arXiv:2603.28052)](https://arxiv.org/abs/2603.28052)
- [RHO: Evolving Agents in the Dark (arXiv:2606.05922)](https://arxiv.org/abs/2606.05922)
- [MOSS: Self-Evolution through Source-Level Rewriting (arXiv:2605.22794)](https://arxiv.org/abs/2605.22794)
- [EPOCH: An Agentic Protocol for Multi-Round System Optimization (arXiv:2603.09049)](https://arxiv.org/abs/2603.09049)
- [GEPA: Reflective Prompt Evolution (arXiv:2507.19457)](https://arxiv.org/abs/2507.19457)
- [ROAD: Reflective Optimization via Automated Debugging (arXiv:2512.24040)](https://arxiv.org/abs/2512.24040)
- [SePO: Self-Evolving Prompt Agent (arXiv:2606.04465)](https://arxiv.org/html/2606.04465)
- [SkillClaw: Let Skills Evolve Collectively (arXiv:2604.08377)](https://arxiv.org/abs/2604.08377)
- [SkillSmith: Co-Evolving Skills and Tools (arXiv:2606.01314)](https://arxiv.org/abs/2606.01314)
- [VeRO: A Harness for Agents to Optimize Agents (arXiv:2602.22480)](https://arxiv.org/abs/2602.22480)
- [AgentFactory: A Self-Evolving Framework (arXiv:2603.18000)](https://arxiv.org/abs/2603.18000)
- [Darwin Gödel Machine (arXiv:2505.22954)](https://arxiv.org/abs/2505.22954)
- [VCC: View-oriented Conversation Compiler (arXiv:2603.29678)](https://arxiv.org/abs/2603.29678)
- [Failure Attribution in Multi-Agent Systems (arXiv:2505.00212)](https://arxiv.org/abs/2505.00212)
- [Airbnb Agent-in-the-Loop Data Flywheel (arXiv:2510.06674)](https://arxiv.org/abs/2510.06674)
- [Survey of Self-Evolving Agents (arXiv:2507.21046)](https://arxiv.org/abs/2507.21046)

**社区讨论**
- [ICLR 2026 Workshop on AI with Recursive Self-Improvement](https://iclr.cc/virtual/2026/workshop/10000796)
- [The Self-Improving AI Agent Is a Production Pattern Now (Adaline Labs)](https://labs.adaline.ai/p/self-improving-ai-agent-production-pattern)
- [Karpathy AutoResearch Guide (DataCamp)](https://www.datacamp.com/tutorial/guide-to-autoresearch)
- [A Synthetic Data Generation Harness (Saulius)](https://saulius.io/blog/synthetic-data-generation-harness-ai-agents)
- [Build an Agent Improvement Loop with Traces, Evals, and Codex (OpenAI)](https://developers.openai.com/cookbook/examples/agents_sdk/agent_improvement_loop)
- [Awesome Self-Evolving Agents (GitHub)](https://github.com/XMUDeepLIT/Awesome-Self-Evolving-Agents)
- [Awesome Agent Harness (GitHub)](https://github.com/Gloriaameng/Awesome-Agent-Harness)
