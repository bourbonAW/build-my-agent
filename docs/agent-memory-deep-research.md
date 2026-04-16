# Agent Memory 深度研究报告
## 为 Bourbon 挑选下一代 Memory 架构

> 研究日期: 2026-04-16  
> 研究范围: 2024-2025 社区主流 Agent Memory 设计范式、实现细节与生产实践

---

## 1. 执行摘要

LLM Agent 的上下文窗口虽在扩张，但 **"无限上下文 ≠ 有效记忆"**。社区在 2024-2025 年的核心共识是：Agent Memory 不是简单的对话历史存储，而是一套**分层、结构化、可检索、可演化**的上下文工程系统。

本报告系统研究了当前社区 6 大主流 Memory 架构范式，从 OS 级虚拟内存（MemGPT/Letta）、到 Drop-in Memory Layer（Mem0）、到图原生记忆（Neo4j/MAGMA）、再到时序知识图谱（Zep）。

**对 Bourbon 的核心推荐**：
- **短期**：采用 **OS 式分层 Memory（Letta 风格）** 管理单会话上下文——Core Memory Blocks + Recall Memory + Archival Memory
- **长期**：构建 **Hybrid Graph + Vector Memory（Mem0/Neo4j 风格）** 作为持久记忆层，支持语义搜索 + 图遍历 + 多作用域隔离
- **多 Agent**：引入 **Shared Memory Pool + Namespace Scoping**，让主 Agent 与 Subagent 共享状态而非传递全量上下文

---

## 2. Agent Memory 全景图谱

### 2.1 为什么传统方案不够？

| 方案 | 问题 |
|------|------|
| 纯对话历史 (Message Buffer) | 上下文溢出、成本线性增长、LLM 易受 stale content 干扰 |
| 纯 Vector RAG | 丢失关系、无法表达因果/时序、多跳推理弱 |
| 纯 KV Store | 快速查找但无法表达实体间关系 |
| 纯 Prompt Engineering | 无法跨会话持久化、难以规模化 |

### 2.2 社区演进的三阶段

```
Stage 1 (2023): 上下文拼接
  └── 把对话历史塞进 prompt

Stage 2 (2024): RAG + 向量记忆
  └── 向量数据库存储历史，按语义检索注入上下文

Stage 3 (2025): 结构化、分层、自主管理的 Memory 系统
  └── OS 式内存管理 + 知识图谱 + 多作用域共享 + Sleep-Time Consolidation
```

---

## 3. 六大主流架构范式深入研究

### 3.1 MemGPT / Letta —— "LLM as an Operating System"

**核心哲学**：将 LLM 的有限上下文窗口视为稀缺计算资源（RAM），通过 OS 式的 paging 机制在 Primary Context 和 External Storage 之间动态交换数据，创造"无限内存"的幻觉。

#### 3.1.1 三层内存架构

```
┌─────────────────────────────────────────────────────────┐
│                  PRIMARY CONTEXT (RAM)                  │
│  ├─ Static System Prompt                                │
│  ├─ Dynamic Working Context (scratchpad)                │
│  └─ FIFO Message Buffer (recent turns)                  │
├─────────────────────────────────────────────────────────┤
│                EXTERNAL CONTEXT (Disk)                  │
│  ├─ Recall Storage: 完整对话历史的 searchable log       │
│  └─ Archival Storage: 向量化的长期抽象知识              │
└─────────────────────────────────────────────────────────┘
```

#### 3.1.2 自管理 Write-Back 循环

当 Primary Context 的 token 使用率接近阈值（如 70%），系统插入 memory pressure alert。LLM 暂停当前推理，自主决定：
- 哪些内容不重要 → 直接丢弃
- 哪些需要摘要 → 写入 Recall
- 哪些需要长期保存 → 写入 Archival

**优点**：
- 优雅地抽象了有限上下文问题
- 单 Agent 可实现自主记忆管理

**缺点**：
- 记忆管理消耗 LLM 的认知带宽
- 存储非结构化，复杂关系查询困难

#### 3.1.3 Letta 的演进：Memory Blocks + Sleep-Time Compute

Letta（MemGPT 的继任者）引入了 **Memory Blocks** 作为核心抽象：
- 每个 Block 有 `label` / `description` / `value` / `limit`
- Agent 可通过工具（`core_memory_append`, `core_memory_replace`）自主编辑自己的 memory
- **Sleep-Time Agents**：在空闲时异步整理、重组记忆，避免阻塞用户交互

> **关键洞察**：Memory Blocks 把上下文窗口从"一坨文本"变成了"结构化、可寻址、可编辑的单元"。

---

### 3.2 Mem0 —— "通用记忆抽象层"

**核心哲学**：不做 Agent 框架，只做 Memory Layer。通过一行代码 (`client.add(messages)`) 给任何现有 Agent 注入持久记忆。

#### 3.2.1 两阶段处理流水线

```
Extraction Phase          Update Phase
     │                         │
     ▼                         ▼
 LLM 分析对话，提取事实    混合存储架构更新记忆
 (偏好、身份、上下文)      ├─ Vector DB: 语义检索
                           ├─ Graph DB: 关系建模  
                           └─ KV Store: 快速精确查找
```

Mem0 的研究论文声称相比全上下文方法：**+26% 准确率，91% 更低延迟，90% 更少 token**。

#### 3.2.2 四级作用域 (Scoping)

这是 Mem0 最具工程价值的设计：

| 维度 | 标识符 | 用途 |
|------|--------|------|
| User | `user_id` | 跨所有会话的用户级长期记忆 |
| Session | `run_id` | 单次会话的临时上下文 |
| Agent | `agent_id` | 特定 bot/角色的专用记忆 |
| Application | `app_id` | 应用级默认值 |

通过 `AND` 过滤器组合这些维度，实现精确的上下文隔离：
```python
client.search("What plan is this customer on?",
    filters={"AND": [{"user_id": "cust_123"}, {"agent_id": "billing_agent"}]})
```

**优点**：
- 零摩擦集成，与 LangGraph/CrewAI/AutoGen 等框架兼容
- 作用域设计直接解决多 Agent 的上下文污染问题

**缺点**：
- 作为外部依赖增加了架构复杂度
- 早期作用域决策难以后期重构

---

### 3.3 LangGraph Memory —— "Checkpoint + Store 双轨制"

**核心哲学**：把"会话状态持久化"（short-term）和"跨会话知识存储"（long-term）严格分离成两个原语。

#### 3.3.1 Checkpointer：Thread-Scoped 短期记忆

- 每个 `thread_id` 对应一条会话线
- 在每次 super-step（图的一个 tick）边界自动保存 `StateSnapshot`
- 支持 Time Travel（从任意 checkpoint 恢复）、Human-in-the-loop、Fault Tolerance

```python
StateSnapshot(
    values={'foo': 'b', 'bar': ['a', 'b']},
    next=(),
    config={'thread_id': '1', 'checkpoint_id': '...'},
    metadata={'step': 2, 'source': 'loop'},
    created_at='2024-08-29T19:19:38+00:00'
)
```

#### 3.3.2 Store：Cross-Thread 长期记忆

- `InMemoryStore` / `PostgresStore` / `RedisStore`
- 支持**语义搜索**：配置 embedding provider 后可用自然语言查询
- Namespace 为 `tuple`，如 `(user_id, "memories")`

LangGraph 明确区分了三种长期记忆类型：

| 类型 | 内容 | 更新策略 |
|------|------|---------|
| Semantic | 用户事实/偏好 | Profile 整体更新 或 Collection 增量更新 |
| Episodic | 过去的行动/经验 | 作为 few-shot examples 检索 |
| Procedural | Agent 指令/行为规则 | Reflection 更新 system prompt |

**优点**：
- 概念清晰，短期/长期分离降低了心智负担
- 与图执行模型天然集成

**缺点**：
- Store 本身不解决"如何自动提取和更新记忆"的问题，需要开发者自己实现

---

### 3.4 Zep —— "时序知识图谱 (Temporal KG)"

**核心哲学**：事实会变化，传统记忆系统要么丢失历史（覆盖写入），要么积累矛盾（只追加）。Zep 通过**双时序模型**追踪每一条知识的有效时间。

#### 3.4.1 Graphiti 引擎与 Bi-Temporal 模型

每条边携带两个时间轴：
- **Event Time**：事实在现实世界中何时发生
- **Transaction Time**：事实何时被记录到系统中

```
(Alice)-[:works_at {valid: 2020-2023, recorded: 2023-01}]->(Company A)
(Alice)-[:works_at {valid: 2023-present, recorded: 2023-06}]->(Company B)
```

查询"Alice 现在在哪工作？" → Company B  
查询"2022 年 Alice 在哪工作？" → Company A

#### 3.4.2 混合检索

Zep 同时结合：
- **Vector Similarity**：语义匹配
- **Graph Traversal**：基于关系的路径查询

**优点**：
- 对时变信息（用户偏好、组织架构、状态流转）极为精确
- 历史可追溯，不会丢失旧信息

**缺点**：
- 引入 Neo4j 等图数据库，运维成本较高
- 对非时变场景是过度设计

---

### 3.5 Neo4j Agent Memory —— "Graph-Native 三层记忆"

**核心哲学**：用单一的 Neo4j 图数据库同时承载三种记忆，并通过显式关系连接它们。

#### 3.5.1 三层记忆模型

```
┌─────────────────────────────────────────────┐
│              Short-Term Memory              │
│  (:Message)-[:NEXT]->(:Message) chains      │
│  按 session 组织，支持语义搜索              │
├─────────────────────────────────────────────┤
│              Long-Term Memory               │
│  POLE+O 实体图: Person, Organization,       │
│  Location, Event, Object + 偏好节点         │
├─────────────────────────────────────────────┤
│              Reasoning Memory               │
│  (:ReasoningTrace)-[:HAS_STEP]->            │
│  (:ReasoningStep) with provenance links     │
└─────────────────────────────────────────────┘
```

#### 3.5.2 多阶段实体提取管道

结合 spaCy + GLiNER2 + GLiREL + LLM，可配置 8 种领域 schema。

#### 3.5.3 可审计性与溯源链

由于图遍历是确定性的，监管场景下可以回答"为什么批准了这笔贷款？"：

```cypher
MATCH (decision:Message)-[:MENTIONS]->(entity:Entity)
MATCH (entity)<-[:MENTIONS]-(finding:Message)
RETURN decision.content, entity.name, finding.content
```

这比向量相似度搜索的"概率性召回"更可靠。

---

### 3.6 MAGMA —— "多图正交记忆架构"

**核心哲学**：不同类型的关系应该存储在不同的图中，而不是塞进一张大杂烩图里。

#### 3.6.1 四图分层

```
┌─────────────┬─────────────┬────────┬────────────┐
│  Semantic   │  Temporal   │ Causal │   Entity   │
│   Graph     │   Graph     │ Graph  │   Graph    │
├─────────────┼─────────────┼────────┼────────────┤
│ 概念关联    │ 事件时序    │ 因果链 │ 实体关系   │
│ (related_to)│ (follows)   │(causes)│ (works_at) │
└─────────────┴─────────────┴────────┴────────────┘
```

#### 3.6.2 双流速记忆演化

借鉴人脑的海马体-新皮层模型：
- **Fast Stream（突触摄入）**：新信息立即进入短期记忆，保证实时可用
- **Slow Stream（结构巩固）**：在后台分析短期记忆，去重、消解矛盾、推断关系，再写入长期图

#### 3.6.3 自适应遍历策略

根据查询意图动态切换图遍历权重：
- 事实核查 → 优先 Entity + Semantic Graph
- 时间线追踪 → 优先 Temporal Graph
- 根因分析 → 优先 Causal Graph

**Benchmark 结果**：在 LoCoMo 长对话基准上达到 **0.700**，远超 Full Context (0.563) 和纯 RAG (0.542)。

---

## 4. 头部 End-Product Agent 的 Memory 实践

前述 6 大范式主要来自 middleware / 框架层的研究。但社区真正跑通生产环境的往往是**端到端 Agent 产品**自身的 memory 设计。本节深度拆解 2024-2025 年最受关注的 6 款 Agent（OpenClaw、DeerFlow、Hermes、Claude Code、Kimi CLI、Manus）的内部实现，提炼可直接复用的工程模式。

---

### 4.1 OpenClaw —— "文件即记忆" (File-as-Memory)

**核心哲学**：把 durable memory 完全外化到磁盘文件，上下文窗口只保留临时对话。如果信息没有写入文件，就等于不存在。

#### 4.1.1 四层记忆栈

```
┌─────────────────────────────────────────────────────────┐
│  Bootstrap Files    ← 永久注入 (SOUL.md, AGENTS.md,     │
│                       USER.md, MEMORY.md, TOOLS.md)     │
├─────────────────────────────────────────────────────────┤
│  Session Transcript ← JSONL 持久化，但可被 compaction    │
│                       摘要替换                            │
├─────────────────────────────────────────────────────────┤
│  LLM Context Window ← 200K token 的临时战场               │
├─────────────────────────────────────────────────────────┤
│  Retrieval Index    ← 本地 hybrid search / QMD          │
│                       (memory/YYYY-MM-DD.md + MEMORY.md)│
└─────────────────────────────────────────────────────────┘
```

#### 4.1.2 Compaction 与 Pre-Compaction Flush

- **Compaction**：上下文接近上限时，将旧对话无损摘要，替换原始消息。OpenClaw 明确区分 *compaction*（lossy、永久改写上下文）和 *pruning*（仅临时裁剪 tool result）。
- **Memory Flush**：在 compaction 触发前，自动运行一个 silent agent turn，提示模型把关键信息写入 `memory/YYYY-MM-DD.md`。
- **配置实践**：`reserveTokensFloor: 40000` 为 flush 预留足够 headroom，避免 overflow recovery（bad path）导致信息丢失。

#### 4.1.3 对 Bourbon 的启示

> **"If it's not written to a file, it doesn't exist."** 这对 Bourbon 极其重要：Bourbon 已有 `.kimi/skills/` 和 `AGENTS.md`，只需再引入 `MEMORY.md` + `USER.md` + daily logs，就能立即获得跨会话持久记忆，无需任何数据库。

---

### 4.2 DeerFlow —— "异步事实提取 + Token Budget 注入"

**核心哲学**：不存对话，只存**理解**。用 LLM 把对话蒸馏成结构化事实，按置信度排序，在 2,000 token budget 内注入新会话。

#### 4.2.1 MemoryMiddleware 异步流水线

DeerFlow 的 Lead Agent 跑在 LangGraph 上，MemoryMiddleware 位于中间件链第 8 位：

```
User Message → Agent Response → MemoryMiddleware
                                    │
                                    ▼ (30s debounce)
                              Async Queue
                                    │
                                    ▼
                         LLM Extractor (facts diff)
                         ├─ newFacts[]
                         ├─ factsToRemove[]
                         └─ shouldUpdate summaries
                                    │
                                    ▼
                         backend/.deer-flow/memory.json
```

#### 4.2.2 JSON Memory 结构

- **本地文件**：`backend/.deer-flow/memory.json`
- **上限**：100 facts，按置信度 eviction（<0.7 的不注入）
- **注入策略**：每轮新会话把高置信度事实按 token budget（2,000 tokens）逐个加入 system prompt 的 `<memory>` 标签
- **去重**：文本级 exact match（strip whitespace），非语义去重

#### 4.2.3 优劣与启示

| 优点 | 缺点 |
|------|------|
| 零外部依赖，单 JSON 文件 | 无语义搜索，注入按置信度而非相关性 |
| 异步不阻塞用户响应 | 无向量嵌入，无法做相似度召回 |
| 轻量、易读、可手动编辑 | 100 facts 上限对大项目可能吃紧 |

> **启示**：Bourbon 可以先用 DeerFlow 模式做**用户 profile 记忆**（异步提取 + JSON 文件 + token budget 注入），比上一整套 Vector DB 更简单、更可控。

---

### 4.3 Hermes Agent —— "四层分离 + 自主技能生成"

**核心哲学**：混合一切进一个 memory store 会导致可靠性随时间衰减，因此把记忆严格拆成四层，每层有独立的存储、更新和读取时机。

#### 4.3.1 四层记忆系统

```
┌─────────────────────────────────────────────────────────┐
│  Prompt Memory      ← 始终注入 (MEMORY.md + USER.md)    │
│  容量限制: 3,575 chars (~1,300 tokens)                  │
├─────────────────────────────────────────────────────────┤
│  Session Search     ← SQLite + FTS5 + LLM summarization │
│  按需检索 episodic memory                               │
├─────────────────────────────────────────────────────────┤
│  Skills (Procedural)← ~/.hermes/skills/                 │
│  默认只注入 name+summary，按需加载全文                  │
├─────────────────────────────────────────────────────────┤
│  Honcho (User Model)← 12 层身份建模，可选               │
│  被动构建用户画像，非显式写入                           │
└─────────────────────────────────────────────────────────┘
```

#### 4.3.2 Agent-Curated Memory

Hermes 通过 **periodic nudge** 机制，在会话中定时向 agent 发送系统级提示：
> "回顾刚才发生的事，判断是否有值得持久化的内容。"

Agent 自主决定写入 MEMORY.md / USER.md，或留在 session archive 中。这样 memory 保持**策展式**（curated）而非**倾倒式**（dump）。

#### 4.3.3 自主技能生成与 Patch 更新

当任务满足触发条件（≥5 个 tool call、从错误恢复、用户纠正、非显然工作流），Hermes 会自动在 `~/.hermes/skills/` 下生成新 skill（遵循 agentskills.io 规范）。后续改进默认用 `patch` 而非 `edit`，只改差异文本，既安全又省 token。

#### 4.3.4 对 Bourbon 的启示

> **Prompt Memory 必须设硬上限**。Hermes 的 3,575 chars 强制 agent 做信息压缩，避免 prompt 膨胀。
> **Session Search 与 Prompt Memory 的职责分离**：永久高频事实进 `MEMORY.md`，低频 episodic 查询走 FTS5。
> **Progressive Skill Disclosure**：Bourbon 已有 `.kimi/skills/`，但当前可能注入完整 SKILL.md；应改为默认只注入 metadata，需要时再通过工具读取全文。

---

### 4.4 Claude Code —— "Harness Engineering 典范"

**核心哲学**：把 Memory 视为 Context Engineering 的三大原语之一（Compaction / Tool-Result Clearing / Memory Tool），而不是一个独立的"记忆模块"。

#### 4.4.1 三大上下文管理原语

| 原语 | 作用 | 触发方式 |
|------|------|---------|
| **Compaction** | 整段对话摘要，释放上下文 | 自动（~98% 阈值）或手动 `/compact` |
| **Tool-Result Clearing** | 仅替换旧的 `tool_result` 为占位符，保留 `tool_use` 记录 | 自动（token 阈值） |
| **Memory Tool** | 结构化笔记，跨会话持久化 | Agent 主动调用 `memory` tool |

#### 4.4.2 CLAUDE.md 作为持久锚点

Claude Code 高度重视 `CLAUDE.md`：
- 每一轮都重新读取
- compaction 会丢失对话中的临时规则，但 `CLAUDE.md` 中的规则始终存在
- 这是其**对抗 compaction 信息丢失**的核心策略

#### 4.4.3 MCP Tool Search

连接大量 MCP 服务器时，Claude Code 不在会话开始时加载所有 tool schema，而是：
1. 只加载 tool names
2. 任务需要时通过 search 发现相关 tools
3. 仅把实际使用的 tools 注入上下文

这显著降低了 MCP 的上下文开销。

#### 4.4.4 对 Bourbon 的启示

> Bourbon 已经有 `AGENTS.md`，可以引入 **CLAUDE.md / MEMORY.md 作为 compaction-proof 锚点**。
> **MCP Tool Search** 对 Bourbon 尤为重要：随着 MCP 生态扩展，必须在上下文管理层面做 tool discovery，而不是无脑注入所有 schema。

---

### 4.5 Kimi CLI —— "Checkpoint 时间旅行"

**核心哲学**：在 Agent 循环中引入**可回滚的 checkpoint**，让 agent 能向"过去的自己"发消息（D-Mail），修正错误决策而不丢失上下文。

#### 4.5.1 Checkpoint 机制

KimiSoul 引擎在每步前写入 checkpoint：

```python
async def checkpoint(self):
    checkpoint_id = self._next_checkpoint_id
    # 写入 JSONL checkpoint 记录
    await f.write(json.dumps({"role": "_checkpoint", "id": checkpoint_id}) + "\n")
```

当后续步骤发现之前的决策错误时，可发送 **D-Mail**（DenwaRenji）回退到任意 checkpoint，然后带着新指示继续执行。

#### 4.5.2 上下文压缩

Kimi CLI 同样支持自动压缩（auto-compact）和手动 `/compact`，并在状态栏显示 `context: xx.x%`，让用户感知上下文消耗。

#### 4.5.3 对 Bourbon 的启示

> **Checkpoint + Revert 对 Subagent 极具价值**。Bourbon 的 Subagent 如果能在失败时回滚到任务开始前的 checkpoint，而不是让父 agent 重新委派，将大幅提升复杂任务的可靠性。

---

### 4.6 Manus —— "文件系统是终极上下文"

**核心哲学**：现代 LLM 的 128K+ 上下文窗口在真实 agent 场景中仍不够用，而且**任何不可逆的压缩都有风险**。因此 Manus 把文件系统当作"无限大小、持久、可由 agent 直接操作的外部记忆"。

#### 4.6.1 可恢复的压缩策略

Manus 的 context 管理遵循一个原则：
> 只有当原始内容仍可通过文件系统恢复时，才允许从上下文中删除它。

例如：
- 网页内容可以丢弃，但 URL 必须保留（agent 可重新 fetch）
- 文档内容可以省略，但文件路径必须保留（agent 可重新 read）

#### 4.6.2 todo.md 作为注意力操控器

Manus 在执行复杂任务时会主动创建并更新 `todo.md`。这不仅是为了进度追踪，更是**把全局目标不断复读到上下文的最近端**，对抗 long-context 中的 "lost in the middle" 问题。

#### 4.6.3 保留错误轨迹

Manus 明确不清理失败的操作记录。它认为：
> 当模型看到失败 action 和 resulting observation 时，会隐式更新其信念，降低未来犯同样错误的概率。

这与大多数框架"隐藏错误、直接重试"的做法相反。

#### 4.6.4 对 Bourbon 的启示

> **Bourbon 应该教导 agent 更积极地使用文件系统做外部记忆**：把大型 tool result 写入临时文件，只在上下文中保留文件路径引用。
> **错误轨迹不应被自动清理**：当前很多 agent 框架会在 retry 前截断错误；Bourbon 应保留错误上下文，让模型从中学习。

---

### 4.7 头部 Agent Memory 设计共识

综合以上 6 款产品，可以总结出 2025 年生产级 Agent Memory 的**最大公约数**：

| 共识 | 体现 |
|------|------|
| **1. 文件是记忆的根基** | OpenClaw/Hermes/Claude Code 都用 `.md` 文件作为 durable memory；Manus 把文件系统视为终极上下文 |
| **2. Compaction 是必要之恶** | 所有产品都用 compaction，但都有配套机制（pre-flush、CLAUDE.md、checkpoint）对抗信息丢失 |
| **3. 异步提取优于同步存储** | DeerFlow 的 30s debounce、Hermes 的 periodic nudge，都把记忆更新移出热路径 |
| **4. 技能/工具需要渐进披露** | Hermes 的 progressive skill loading、Claude Code 的 MCP tool search，都是控制上下文膨胀的关键 |
| **5. 错误轨迹是记忆的一部分** | Manus 和 Hermes 都主张保留失败记录，而不是清理后重试 |
| **6. Prompt Memory 必须有硬上限** | Hermes 的 3,575 chars、DeerFlow 的 2,000 token budget，强制做信息策展 |

---

### 4.8 头部产品对比矩阵

| 维度 | OpenClaw | DeerFlow | Hermes | Claude Code | Kimi CLI | Manus |
|------|----------|----------|--------|-------------|----------|-------|
| **Durable Memory** | Bootstrap `.md` files | `memory.json` facts | `MEMORY.md` + `USER.md` | `CLAUDE.md` + Memory Tool | Session JSONL | File system + `todo.md` |
| **Session Management** | Compaction + pruning | No compaction (facts only) | Compaction + SQLite FTS5 | Compaction + tool clearing | Compaction + checkpoint | Restorable compression |
| **记忆更新方式** | Pre-compaction flush | Async 30s debounce extract | Periodic nudge (agent curated) | Agent-driven memory tool | Auto + manual `/compact` | File writes during loop |
| **技能/工具加载** | Skill selective inject | Skill archives | Progressive disclosure | MCP tool search | Agent config loading | CodeAct (Python as action) |
| **Subagent 策略** | Session routing | Sub-agents in harness | Context isolation | Context isolation | Checkpoint revert | Multi-agent parallel sandbox |
| **核心创新** | 4-layer file architecture | Confidence-scored JSON facts | 4-layer memory + auto skill | Harness engineering 3 primitives | D-Mail time travel | File system as ultimate context |

---

## 5. 设计维度对比矩阵

### 5.1 Middleware / 框架层对比

| 维度 | MemGPT/Letta | Mem0 | LangGraph | Zep | Neo4j | MAGMA |
|------|-------------|------|-----------|-----|-------|-------|
| **核心抽象** | OS Memory Paging | Memory Layer | Checkpoint + Store | Temporal KG | Graph-Native 3-Layer | Multi-Graph Orthogonal |
| **短期记忆** | Core Blocks + FIFO | Session-scoped | Checkpointer (thread) | Session messages | Message chains | Fast Stream |
| **长期记忆** | Archival Vector DB | Vector+Graph+KV | Store (JSON docs) | Temporal Graph | POLE+O KG | Slow Stream (4 graphs) |
| **结构化程度** | 中 (Blocks) | 中高 (Entities) | 低 (自由 JSON) | 高 (KG) | 高 (KG) | 极高 (4 层分离) |
| **多 Agent 支持** | 共享 Blocks | Scoped queries | Namespace | 共享图 | 共享图 | 共享图池 |
| **时序支持** | 弱 | 弱 | 弱 | **极强** | 中 | 强 (Temporal Graph) |
| **自主管理** | Agent 自我管理 | 自动提取+更新 | 需开发者实现 | 自动图构建 | 自动实体提取 | 双 Stream 自动演化 |
| **集成成本** | 高（需迁移到 Letta）| 低（drop-in）| 中（需 LangGraph）| 中（需 Neo4j）| 中（需 Neo4j）| 高（研究级）|
| **审计/溯源** | 弱 | 弱 | 弱 | 强 | **极强** | 强 |

---

## 5. 社区共识与关键趋势

### 5.1 五大共识

1. **Memory ≠ RAG**：RAG 是检索工具，Memory 是持久化、可演化、带作用域的状态层。
2. **分层是必然的**：Working Memory（上下文窗口）/ Short-term（会话级）/ Long-term（跨会话）三层分工明确。
3. **结构化优于纯文本**：从 flat vector 转向 Graph/Blocks/Profile，以支持多跳推理和关系查询。
4. **多 Agent 需要共享 Memory Pool**：传递全量上下文是反模式，共享状态 + 作用域隔离才是正解。
5. **Sleep-Time / Background Consolidation 是最佳实践**：不要在热路径上把所有记忆操作塞给用户交互流程。

### 5.2 2025 年的新兴方向

- **Memory as Infrastructure**：Letta 提出的"Stateful Programming"——Agent 不是无状态函数调用，而是持久化对象。
- **Agent Cache Sharing Protocol**：多 Agent 之间共享 KV-cache 和上下文摘要，降低重复计算。
- **Multi-Agent Memory Consistency**：从计算机体系结构借鉴一致性模型，解决并发读写下的可见性和冲突。

---

## 6. 对 Bourbon 的推荐方案（修订版）

### 6.1 推荐架构："Bourbon Memory Stack v2"

基于对 middleware 范式与头部 end-product agent 的双重研究，我们将推荐架构从"纯分层模型"演进为 **"File-as-Memory 地基 + OS 式上下文管理 + 渐进式检索"** 的混合模型。这一修订更贴合 Bourbon 作为通用 Agent 平台的工程实际。

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         BOURBON AGENT                                   │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │              WORKING CONTEXT (Context Window)                   │   │
│  │  ├─ System Prompt                                               │   │
│  │  ├─ Bootstrap Files  [AGENTS.md, MEMORY.md, USER.md]            │   │
│  │  ├─ Core Memory Blocks  [persona, human, project, task]         │   │
│  │  ├─ Active Tool Schemas  ( progressive disclosure )             │   │
│  │  └─ Recent Message Buffer (FIFO, compaction-aware)              │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                              │                                          │
│         ┌────────────────────┼────────────────────┐                    │
│         ▼                    ▼                    ▼                    │
│  ┌─────────────┐      ┌─────────────┐      ┌─────────────┐            │
│  │   RECALL    │      │   MEMORY    │      │   SKILL     │            │
│  │   MEMORY    │◄────►│    STORE    │◄────►│   INDEX     │            │
│  │ (session    │      │ (user facts,│      │ (procedural,│            │
│  │  archive)   │      │  profiles)  │      │  progressive│            │
│  └─────────────┘      └──────┬──────┘      └─────────────┘            │
│                               │                                         │
│         ┌─────────────────────┼─────────────────────┐                  │
│         ▼                     ▼                     ▼                  │
│  ┌────────────┐        ┌────────────┐        ┌────────────┐           │
│  │  SQLite    │        │  Vector    │        │  File      │           │
│  │  (FTS5)    │        │  DB (opt)  │        │  System    │           │
│  │  episodic  │        │  semantic  │        │  external  │           │
│  └────────────┘        └────────────┘        └────────────┘           │
└─────────────────────────────────────────────────────────────────────────┘
```

**架构哲学的转变**：
- **以前**：把 memory 当作一个需要专门数据库的"子系统"
- **现在**：把 **文件系统** 作为 durable memory 的根基，数据库（SQLite/Vector/Graph）作为按需增强的检索层

### 6.2 为什么做这次修订？

#### (1) 头部产品的共识：文件是最可靠的持久记忆

OpenClaw、Hermes、Claude Code 都用 `.md` 文件作为跨会话的 durable anchor。相比数据库，文件的优势是：
- **零运维**：无需安装/配置额外服务
- **用户可读可编辑**：用户可以手动修改 `MEMORY.md` 纠正 agent 的错误认知
- **版本控制友好**：`git diff` 即可审计记忆变化
- **与现有生态无缝集成**：Bourbon 已经有 `AGENTS.md` 和 `.kimi/skills/`

#### (2) 轻量级异步提取足以支撑大部分长期记忆场景

DeerFlow 证明：一个 JSON 文件 + LLM 异步提取 + token budget 注入，就能实现有效的用户画像记忆，无需立刻引入 Vector DB。这对 Bourbon 的 Stage B 阶段极其重要——可以先验证价值，再决定是否上向量存储。

#### (3) 上下文管理比"记忆存储"更紧迫

Claude Code 和 Kimi CLI 的核心创新不是存储技术，而是 **Harness Engineering** —— compaction、tool clearing、checkpoint、progressive disclosure。Bourbon 当前最痛的其实是长会话上下文爆炸和 MCP 工具膨胀，这些应该优先解决。

### 6.3 具体设计建议（按优先级排序）

#### A. File-as-Memory 基础层（立即实施，零依赖）

在 Bourbon 工作目录（或 `~/.bourbon/`）引入以下文件约定：

| 文件 | 作用 | 注入策略 | 容量建议 |
|------|------|---------|---------|
| `AGENTS.md` | Agent 行为规则、工具使用约定 | 每会话始终注入 | 无硬上限（但需监控） |
| `MEMORY.md` | 跨会话持久的事实、偏好、修正 | 每会话始终注入 | ~2,200 chars (~800 tok) |
| `USER.md` | 用户画像、沟通风格、环境信息 | 每会话始终注入 | ~1,375 chars (~500 tok) |
| `memory/YYYY-MM-DD.md` | 当日工作日志、决策记录 | 按需检索 / 近两天自动注入 | 无上限 |

> **关键规则**："If it's not written to a file, it doesn't exist." —— 任何在对话中给出的重要指令、偏好或决策，agent 都应主动写入上述文件。

#### B. 上下文压缩与 Pre-Compaction Flush（高优先级）

基于 OpenClaw 和 Claude Code 的最佳实践，修订 Bourbon 的 `compression.py`：

1. **区分 Compaction 与 Pruning**
   - **Pruning**：仅临时裁剪旧的 tool result（保留 tool use 记录），不写入持久存储
   - **Compaction**：当上下文接近上限（如 85%）时，摘要旧对话并永久替换

2. **Pre-Compaction Memory Flush**
   - 在触发 compaction 前，自动运行一个 silent agent turn
   - 提示："Session nearing compaction. Write any durable notes to memory files now."
   - 将提取出的关键事实写入 `memory/YYYY-MM-DD.md` 或更新 `MEMORY.md`

3. **保留错误轨迹**
   - 不在 retry 前清理失败的 tool call 和 error observation
   - 让模型从错误中学习，这是 Manus 和 Hermes 的明确共识

#### C. 渐进式技能与工具披露（高优先级）

Bourbon 的 `.kimi/skills/` 和 MCP 工具生态正在快速扩展，必须控制上下文膨胀：

**技能加载策略**：
- 默认只向 prompt 注入技能的 `name` + `description`（1-2 句话）
- 提供 `skill_search` 工具，让 agent 根据当前任务查询相关技能
- 仅当 agent 明确调用 `skill_search` 并选择某技能后，才注入该技能的完整 `SKILL.md`

**MCP 工具策略**：
- 默认只加载 MCP server 的 tool names
- 提供 `mcp_tool_search` 或让 agent 通过 `memory_search` 发现相关工具
- 仅把 agent 实际决定使用的 tools 的完整 schema 注入上下文

#### D. 异步用户画像提取（中优先级）

引入 DeerFlow 风格的轻量级用户记忆：

```
backend/.bourbon/profile.json
```

- **更新时机**：会话结束后（或 30s debounce），由后台 extractor LLM 扫描当轮对话
- **输出格式**：结构化 facts，带 `confidence` 和 `timestamp`
- **注入策略**：新会话开始时，按 token budget（如 1,000 tokens）从高置信度 fact 开始注入
- **上限**：100 facts，超出时按置信度 eviction

这比直接上 Vector DB 更简单、更可控，适合 Bourbon 的当前阶段。

#### E. Session Search（中优先级）

参考 Hermes 的 Session Search 层：
- 所有会话历史写入本地 **SQLite + FTS5**
- 提供 `session_search` 工具，agent 可主动查询过去的对话
- 检索结果经 LLM summarization 后再注入上下文
- 职责边界：**Prompt Memory（文件）** 负责始终可用的高频事实；**Session Search** 负责按需召回的 episodic 记忆

#### F. Checkpoint / Time-Travel 机制（中优先级）

借鉴 Kimi CLI 的 D-Mail 设计，为 Bourbon 的 Subagent 引入可回滚 checkpoint：

```python
class Checkpoint:
    checkpoint_id: int
    context_snapshot: list[Message]
    created_at: datetime

# 在 Subagent 每步前创建 checkpoint
await checkpoint()

# 当后续发现前置决策错误时，回滚并附带新指令
await revert_to_checkpoint(checkpoint_id, dmail_message="请先备份再执行")
```

这对复杂代码重构、多步部署等高风险任务极具价值。

#### G. 文件系统作为外部记忆（即刻可行）

教导 Bourbon agent 更积极地使用文件系统管理大段信息：
- 大型 tool result（如 web fetch、大文件 read、数据库 schema）默认**写入临时文件**，上下文中只保留文件路径
- 复杂任务使用 `todo.md` 或 `plan.md` 跟踪进度，通过不断复写把目标锚定在上下文最近端
- 长文档生成时分段写入草稿文件，最后合并，而不是一次性输出超大文本

### 6.4 实施路线图（修订版）

```
Phase 1 (2-4 周): File-as-Memory 地基
  ├─ 引入 MEMORY.md + USER.md 约定，与 AGENTS.md 并列
  ├─ 实现自动/手动 memory 写入工具（memory_write, memory_update）
  ├─ 创建 `memory/YYYY-MM-DD.md` 的 daily log 机制
  ├─ 修改 compression.py：实现 pre-compaction flush
  └─ 保留错误轨迹：不在 retry 前清理 failed observations

Phase 2 (4-6 周): 上下文工程与渐进披露
  ├─ 实现 Core Memory Blocks 抽象，设硬上限
  ├─ 实现 FIFO Message Buffer + smart eviction
  ├─ 技能系统改为 progressive disclosure（默认只注入 metadata）
  ├─ MCP 工具上下文优化（names only → search → full schema）
  └─ 引入大型 tool result 的"落盘引用"模式

Phase 3 (4-6 周): 会话持久化与轻量长期记忆
  ├─ SQLite session archive + FTS5 session_search 工具
  ├─ 异步 profile.json 事实提取（DeerFlow 模式）
  ├─ Subagent checkpoint / time-travel 基础版
  ├─ Memory 读写与 access_control/ 集成
  └─ Audit logging：记忆访问轨迹

Phase 4 (8+ 周): 高级记忆层（按需）
  ├─ 可选 Vector DB 集成（Chroma/pgvector）
  ├─ 可选 Graph DB 集成（代码实体关系、项目依赖）
  ├─ Sleep-Time Consolidation Agent
  ├─ 从记忆中自动发现技能 gaps 并生成新 Skills
  └─ 多模态记忆（文档、图片摘要）
```

### 6.5 关键成功指标

| 指标 | 目标 | 测量方式 |
|------|------|---------|
| **长会话可用性** | 50+ 轮对话不触发 overflow | 压力测试 |
| **记忆召回准确率** | 跨会话用户偏好 recall >90% | 人工评估 |
| **上下文膨胀率** | 每轮平均 token 增长 <5% | 日志分析 |
| **MCP 工具开销** | 接入 10+ MCP 后上下文增幅 <20% | 基准测试 |
| **Subagent 成功率** | 复杂任务 retry 率 <15% | eval cases |

---

## 7. 结论

Agent Memory 正在从"简单的对话历史"进化为"结构化、分层、可共享、可演化的基础设施"。

对 Bourbon 而言，**最务实的路径**不是盲目照搬 Letta 或 Mem0，而是结合 **middleware 的前沿理论**与**头部产品的工程验证**，形成自己的 Memory 哲学：

**从 Middleware 范式中学习：**
- **Letta 的 Memory Blocks 和 OS 式上下文管理**
- **Mem0 的 Namespace Scoping 和 Drop-in 集成思想**
- **Neo4j/MAGMA 的 Graph-native 长期记忆理念**
- **Zep 的时序追踪意识（在需要时引入）**

**从 End-Product Agent 中学习：**
- **OpenClaw/Hermes 的文件即记忆**——`AGENTS.md` / `MEMORY.md` / `USER.md` 是成本最低、收益最高的持久化层
- **Claude Code 的 Harness Engineering**——上下文压缩不是坏事，关键是 pre-flush 和错误轨迹保留
- **DeerFlow 的异步轻量提取**——用 JSON facts + token budget 就能做出可用的用户画像，无需急着上向量数据库
- **Kimi CLI 的 Checkpoint**——给 Subagent 可回滚的能力，比给它无限上下文更重要
- **Manus 的文件系统外包**——把大段信息写出去，让上下文保持"可操作"的紧致状态

Bourbon 的下一个 level，不在于拥有一个比 Mem0 更好的 Memory Layer，而在于让 **Memory 成为 Bourbon 平台的一等公民**——与 Skills、Sandbox、MCP、Access Control 平起平坐，共同构成通用 Agent 的基础设施。

---

## 附录：核心参考资源

1. **MemGPT Paper**: Packer et al., "MemGPT: Towards LLMs as Operating Systems", arXiv:2310.08560
2. **Mem0 Research**: Chhikara et al., "Mem0: Building Production-Ready AI Agents with Scalable Long-Term Memory", arXiv:2504.19413
3. **LangGraph Persistence**: https://docs.langchain.com/oss/python/langgraph/persistence
4. **Zep / Graphiti**: https://github.com/getzep/graphiti
5. **Neo4j Agent Memory**: https://neo4j.com/labs/agent-memory/
6. **MAGMA**: "Memory-Augmented Graph-based Multi-Agent Architecture", arXiv:2601.03236
7. **Multi-Agent Memory Survey**: Yu & Zhao, "Multi-Agent Memory from a Computer Architecture Perspective", arXiv:2603.10062
8. **Graph-Based Agent Memory Survey**: "A Survey on Graph-based Agentic Memory", arXiv:2602.05665
9. **OpenClaw**: https://github.com/minutesbeforesix/openclaw (bootstrap file memory + compaction pre-flush)
10. **DeerFlow**: https://github.com/mshumer/deerflow (async fact extraction + MemoryMiddleware)
11. **Hermes Agent**: https://github.com/Blaizzy/hermes (4-layer memory + autonomous skill creation)
12. **Claude Code**: Anthropic, "Building effective agents" blog (harness engineering + MCP tool search)
13. **Kimi CLI**: Moonshot AI (checkpoint / D-Mail time-travel mechanism)
14. **Manus**: Manus AI (file system as ultimate context + CodeAct paradigm)
