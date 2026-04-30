# Bourbon Memory 检索机制升级设计讨论记录

> Session Date: 2026-04-30  
> Participants: 用户 + Kimi Code CLI  
> 主题：以社区优秀 memory 项目为参照，聚焦「检索机制」设计，为 Bourbon Memory V3 升级提供方向

---

## 1. 背景与目标

### 1.1 核心判断

社区在 memory **存储** 上的研究已经非常深入和成熟（向量数据库、embedding、混合检索、知识图谱等），但大多数项目没有搞清楚三件更重要的事情：

1. **什么需要存储**（Write Decision）
2. **存储后怎么使用**（Context Injection Strategy）
3. **如何检索到必要的数据**（Retrieval Mechanism）

**其中「检索」是核心瓶颈**。存储了再多的信息，如果没有有效的检索机制将其召回使用，那就相当于不存在。

### 1.2 参考输入

- **人类记忆研究**：[PMC5664228](https://pmc.ncbi.nlm.nih.gov/articles/PMC5664228/) — 关于 Associative Network model、Encoding-retrieval specificity、Cue distinctiveness、Self-generated cues 的学术研究
- **Hermes Agent** 记忆系统架构分析（`wiki/hermes-agent-memory-architecture.md`）
- **Claude-mem**（thedotmack/claude-mem）— Claude Code 的持久记忆插件
- **Memory-mcp**（yuvalsuede/memory-mcp）— 轻量级 Claude Code 记忆系统

### 1.3 当前 Bourbon 记忆现状

| 能力 | 状态 |
|------|------|
| 文件优先存储（`~/.bourbon/projects/{key}/memory/`） | ✅ Phase 1 |
| `MEMORY.md` 索引（≤200 active records） | ✅ Phase 1 |
| grep 关键词召回 | ✅ Phase 1 |
| Promoted Preference Injection（USER.md managed blocks） | ✅ Phase 2 |
| 写入治理（confidence、source tracking、actor） | ✅ Phase 2 |
| 记忆安全扫描 | ❌ |
| 跨会话 FTS5/SQLite 召回 | ❌ |
| Trust scoring / 自动衰减 | ❌ |
| Agent 自主写 Skill | ❌ |
| Bundle Skill 写保护 | ❌ |

---

## 2. 从人类记忆研究提取的设计原则

基于 PMC5664228 的学术研究和认知心理学框架，提取出四条可直接映射到 Agent Memory 检索设计的原则：

### 2.1 Cue Distinctiveness Principle（线索独特性原则）

> "If retrieval cues are not recognized as being distinct from one another, cues are likely to become associated with more information, which in turn reduces the effectiveness of the cue." — Watkins & Watkins, 1975

**映射到 Agent Memory**：
- 向量 embedding 把记忆压进稠密向量空间，导致「向量层面的 cue overload」— 一个记忆节点被关联到太多 query
- 需要**显式的区分度设计**：检索线索必须能**唯一地**指向目标记忆
- **工程化方向**：写入记忆时让 LLM 同时生成未来检索用的 cues

### 2.2 Encoding-Retrieval Specificity Principle（编码-检索特异性原则）

> "The overlap between encoded information and retrieval cue predicts the likelihood of accurate recall." — Tulving & Thomson, 1973

**映射到 Agent Memory**：
- 存储时的表征和检索时的表征往往不一致（用户问"上次那个配置"，编码内容是"pytest with xdist"）
- 需要**多模态检索**：原始文本、关键词、cues、场景上下文多路径匹配
- **工程化方向**：保存编码时的上下文快照，检索时重建当前认知上下文做匹配

### 2.3 Self-Generated Cue Principle（自生成线索原则）

> "Self-generated cues consistently resulted in high levels of performance. When other-generated cues were presented performance was particularly low (around 5%)." — Mäntylä, 1986

**映射到 Agent Memory**：
- 社区项目的 retrieval cues 都是"other-generated"（系统强加的 embedding、BM25、人工标签）
- 最有效的 cues 是**编码者自己生成的**，因为它们包含了编码时的个人化、独特化信息
- **工程化方向**：Agent 在写入记忆时主动生成它认为未来有用的检索线索

### 2.4 Spreading Activation Principle（激活传播原则）

> "Memory is generally viewed as a network of interlinked nodes... activation spreads from concept nodes along associative links throughout a semantic network." — Collins & Loftus, 1975

**映射到 Agent Memory**：
- 记忆不是孤立节点，而是关联网络
- 检索应该从 cue 出发，沿着关联链路传播激活
- **工程化方向**：记忆之间建立关联（linked records），检索时做 1-2 步图遍历

---

## 3. 社区项目深度分析

### 3.1 Claude-mem（thedotmack/claude-mem）

Claude-mem 是 Claude Code 的持久记忆插件，采用 **Plugin Hook + Worker Service + SQLite + ChromaDB** 的架构。

#### 3.1.1 检索架构：策略路由设计

Claude-mem 的核心检索组件是 `SearchOrchestrator`，根据查询形状动态选择策略：

```
查询进来
  ├── 无 query 文本（纯过滤：type/concept/file/date）→ SQLite 直接过滤
  ├── 有 query 文本 + Chroma 可用 → Chroma 向量语义搜索（primary）
  └── Chroma 不可用 → FTS5 fallback
```

**关键设计**：
- **Chroma 是「排序引擎」不是「存储引擎」**：只存 embedding + 轻量 metadata，完整内容在 SQLite
- **HybridSearch = SQL 预过滤 + 向量重排**：先用 SQLite 做 metadata 过滤（concept/type/file），再用 Chroma 对候选 ID 做语义排序
- **FTS5 被策略性弃用**：文档明确说 FTS5 只保留 backward compatibility，计划 v7.0.0 移除

#### 3.1.2 3-Layer Progressive Disclosure（分层渐进检索）

| 层 | 工具 | 返回内容 | 典型 tokens |
|--|------|---------|------------|
| 1 | `search` | 索引（ID, title, type, timestamp） | ~50-100 / 条 |
| 2 | `timeline` | 锚点周围的时序上下文 | ~10 条前后记录 |
| 3 | `get_observations` | 完整 narrative + facts + files | ~500-1000 / 条 |

**设计目的**：不是用户体验优化，而是让 LLM 能「自然地」决定何时停止钻取。每层都是 LLM 的自主决策点。

#### 3.1.3 Observation Taxonomy（观察分类法）

二维分类体系：
- **Type**（工作维度）：bugfix / feature / refactor / discovery / decision / change
- **Concept**（知识维度）：how-it-works / why-it-exists / what-changed / problem-solution / gotcha / pattern / trade-off

**核心价值**：写入时由 AI 自动标注，检索时可精确过滤（"show me decisions with trade-off concept"）。这是**自生成线索的工程化落地**。

#### 3.1.4 Per-Prompt 语义注入

`POST /api/context/semantic` 端点：每次用户输入 > 20 字符时，自动用 Chroma 搜索语义相关 observation 并注入当前 prompt。

**效果**：Claude Code 调用 claude-mem 的频率显著提升，因为检索从「session 边界加载」变成了「每轮实时激活」。

#### 3.1.5 File-Aware 检索

每个 observation 记录 `files_read` 和 `files_modified`。当用户当前打开某文件时，优先返回涉及该文件的记忆。这是 **Encoding-Retrieval Specificity** 的直接落地。

### 3.2 Memory-mcp（yuvalsuede/memory-mcp）

轻量级替代方案，采用 **Two-Tier Memory** 架构：

#### 3.2.1 Two-Tier 设计

| 层级 | 载体 | 机制 | 覆盖场景 |
|-----|------|------|---------|
| Tier 1: CLAUDE.md | ~150 行，自动生成的 briefing 文档 | Claude Code 启动时自动读取 | 80% 的会话 |
| Tier 2: .memory/state.json | 完整记忆存储 | MCP tools 按需检索 | 深层回忆 |

#### 3.2.2 CLAUDE.md 预算分配

```
architecture:  25 lines
decision:      25 lines
pattern:       25 lines
gotcha:        20 lines
progress:      30 lines
context:       15 lines
─────────────────────────
Total:        ~150 lines max
```

每个 section 内按 `confidence × accessCount` 排序。这本质上是**基于访问频率和置信度的缓存淘汰策略**。

#### 3.2.3 去重与衰减

- **去重**：Jaccard similarity > 60% → 新记忆取代旧记忆
- **Confidence Decay**：
  - progress：7 天半衰期
  - context：30 天半衰期
  - architecture / decision / pattern / gotcha：永不衰减

#### 3.2.4 自动提取

在 `Stop` / `PreCompact` / `SessionEnd` hooks 触发时，用 Haiku 分析 transcript，提取 0-3 条结构化记忆。每次提取成本 ~$0.001。

### 3.3 为什么 Claude Code 调用 claude-mem 频率提升？

1. **Per-Prompt 语义注入**：每轮对话都可能激活新记忆
2. **Skill-Based Search（mem-search）**：v5.4.0+ 后检索通过 skill 进行，而非显式 MCP tool call
3. **File-Aware 相关性**：当前打开的文件自动作为隐式过滤条件

---

## 4. 社区的集体盲区：为什么没人深入做 Phase 1？

Phase 1（自生成线索、概念分类、分层检索、cue 质量优化）被系统性忽视，原因不是"没想到"，而是**结构性**的：

### 4.1 向量数据库的叙事霸权

"记忆系统 = 向量数据库 + Embedding + Top-k 相似度"成为了先验假设。Phase 1 的设计在向量的世界观里**根本不存在**。

### 4.2 LLM 的遮蔽效应

社区形成偷懒习惯："检索质量不高没关系，LLM 能从 top-k 结果里自己找答案。"这掩盖了检索层的设计责任，把所有复杂性**外包**给了 LLM。

### 4.3 产品形态错配：卖的是基础设施，不是记忆体验

社区项目的客户是 AI 工程师，评估的是 QPS、延迟、向量规模——**没有人评估「记忆被检索到的概率」或「检索结果的相关性质量」**。

### 4.4 「软工程」的估值折价

Phase 1 涉及 prompt engineering、schema design、taxonomy design，这些在工程文化中被系统性地低估："prompt 工程不是真正的工程。"

### 4.5 没有「记忆检索」的语言和框架

社区有 50 年的信息检索（IR）框架（TF-IDF、BM25、NDCG），但**完全没有「记忆检索」框架**（cue distinctiveness、encoding-retrieval match、spreading activation）。当一个问题没有名字时，它就很难被讨论和设计。

### 4.6 Agent Memory 的「基础设施层」定位

通用记忆基础设施无法预设领域特定的分类法（coding agent 的 bugfix/decision 标签对客服 agent 没有意义）。应用层认为「检索是基础设施的问题」，基础设施层认为「分类法是应用层的事」。**两边都在等对方做，结果都没做**。

---

## 5. Bourbon 的三个关键决策

### 5.1 决策一：接受轻量级本地 embedding

Bourbon 将在 Phase 2 引入轻量级本地 embedding 模型（如 `sentence-transformers/all-MiniLM-L6-v2` 或 `BAAI/bge-small-en-v1.5`），作为语义检索层。

**设计原则**：
- 纯本地，无外部 API 依赖
- Embedding 文件和 memory 文件共存（`~/.bourbon/projects/{key}/memory/.embeddings/`）
- 语义匹配作为关键词匹配的补充，而非替代

### 5.2 决策二：在 session 层增加自动提取机制

Bourbon 将在 Session End / Context Compression 时自动分析 transcript，提取值得长期保存的记忆。

**设计原则**：
- 轻量模型（Haiku-tier 或本地 Ollama）做提取
- 只提取声明性事实和用户偏好，不提取任务进度
- 提取结果经过去重检查（cosine similarity > 0.85 或 Jaccard > 0.6 → 合并/跳过）
- 配置项 `memory.auto_extract` 控制开关

### 5.3 决策三：对 Per-Prompt 记忆激活存疑

Hermes 和 claude-mem 代表了两种设计哲学：

| 维度 | Hermes（Frozen Snapshot） | claude-mem（Per-Prompt 注入） |
|-----|------------------------|---------------------------|
| 记忆角色 | 人格背景（稳定） | 实时参考资料（动态） |
| 注入时机 | Session 启动 | 每轮对话 |
| Prefix Cache | 最大化命中 | 完全失效 |
| 延迟 | 零 | 每轮累积 |
| 行为确定性 | 高 | 低（反馈回路） |

**Bourbon 选择中间路线**：

```
┌─────────────────────────────────────────────────────────────┐
│  Session 启动：Frozen Snapshot 注入                          │
│    ├── AGENTS.md（项目规则）                                  │
│    ├── USER.md（用户偏好 + promoted blocks）                  │
│    ├── MEMORY.md（精华记忆索引）                              │
│    └── Recent Timeline（最近 N 条 project 记忆标题）          │
│         ↑ 背景层：session 内不变                               │
├─────────────────────────────────────────────────────────────┤
│  对话过程中：LLM 主动按需检索                                   │
│    ├── 不需要 → 正常对话                                      │
│    └── 需要 → 调用 memory_search / memory_timeline            │
│         ↑ 按需层：LLM 控制何时检索、检索什么                    │
├─────────────────────────────────────────────────────────────┤
│  Session 结束：自动提取沉淀                                    │
│    └── 小模型分析 transcript → memory_write                   │
│         ↑ 沉淀层：把会话经验转化为长期记忆                      │
└─────────────────────────────────────────────────────────────┘
```

- **背景层** = Hermes 路线（稳定性、prefix cache、零延迟）
- **按需层** = LLM 自主触发（避免 claude-mem 的过度激活和噪声）
- **沉淀层** = 自动提取（解决 LLM 忘记写记忆的问题）

---

## 6. Bourbon Memory V3 升级路径

### Phase 1：检索增强（Retrieval-Cue-First）— 零外部依赖

**目标**：在现有文件优先架构上，把检索做到可用、好用。

1. **MemoryRecord 增加结构化字段**
   ```python
   concepts: list[str]          # e.g., ["how-it-works", "trade-off", "gotcha"]
   retrieval_cues: list[str]    # e.g., ["JWT token expiry", "auth session handling"]
   files: list[str]             # e.g., ["src/auth.py", "tests/test_auth.py"]
   encoding_context: dict       # 编码时的上下文快照
   ```

2. **`memory_write` 增强**：让 LLM 在写入时生成 cues 和 concepts

3. **`memory_search` 分层返回**
   - 默认：索引卡片（id, name, kind, concepts, snippet, file）
   - `detail: "timeline"`：时序上下文
   - `detail: "full"`：完整内容

4. **检索相关性评分**
   - 当前文件路径 → 优先匹配 `files` 字段
   - 当前对话主题 → 优先匹配 `concepts`
   - Recency → 适当提升权重

### Phase 2：轻量 Embedding（语义检索层）

**目标**：解决 query 和记忆表面形式不匹配的问题。

1. **引入轻量本地 embedding 模型**
   - `sentence-transformers/all-MiniLM-L6-v2`（~80MB，CPU < 10ms）
   - 或 `BAAI/bge-small-en-v1.5`（~30MB）

2. **混合检索策略**
   ```
   memory_search(query)
       ├── 结构化过滤（type/scope/status/files/concepts）
       ├── 关键词匹配（retrieval_cues + content）
       ├── 语义匹配（embedding cosine similarity）
       └── 融合排序（weighted fusion）
   ```

3. **Embedding 更新策略**
   - `memory_write` 时同步生成
   - Batch 脚本给已有 memory 补 embedding
   - 和 memory 文件一起存、一起删

### Phase 3：自动提取（Auto-Extract at Session End）

**目标**：解决 LLM 忘记主动写记忆的问题。

1. **Session End / Compaction Hook**
   - 读取 `TranscriptStore` 中的当前 session transcript

2. **轻量模型提取**
   - 分析 transcript，提取 0-3 条记忆
   - 格式：JSON 数组，含 `content`, `kind`, `scope`, `concepts`, `retrieval_cues`

3. **去重检查**
   - 与最近 20 条 active memory 比较
   - cosine > 0.85 或 Jaccard > 0.6 → 合并/跳过

4. **用户控制**
   - `memory.auto_extract: bool`
   - 提取结果可标记为 `pending` 等待确认，或直接进入 `active`

---

## 7. 度量框架：MERP（Memory-Enhanced Retrieval Protocol）

Phase 1 的度量不能依赖传统 IR benchmark（MS MARCO、BEIR、MTEB），因为那些衡量的是「文档检索」，不是「记忆检索」。MERP 采用三层结构：

### Layer 1：检索准确性（Retrieval Accuracy）

**方法**：构造可控测试集（20-30 条 seed memories + 15 条分级 queries）

| 难度 | 查询特征 | 示例 |
|-----|---------|------|
| Level 1 | 直接关键词匹配 | "how do we run tests in parallel?" |
| Level 2 | 语义相关但表面形式不同 | "what's our testing setup?" |
| Level 3 | 需结合当前上下文推断 | 当前打开 `src/auth.py`，问 "any known issues here?" |

**指标**：
- **Recall@k**：gold memory 是否在 top-k 中（k=3 或 5）
- **MRR**：gold memory 排名的倒数均值
- **分层检索成功率**：LLM 能否通过 ≤2 轮 tool call 找到 gold memory

**关键对比实验**：
- Baseline A：当前 Bourbon（grep 关键词，单层返回）
- Treatment B：Phase 1 增强（cues + concepts + 分层检索）
- Treatment C：Phase 1 + 轻量 embedding

### Layer 2：检索效率（Retrieval Efficiency）

| 指标 | 定义 | 目标 |
|-----|------|------|
| Token 消耗 | 每次 memory_search 返回内容的 token 数 | Layer 1 < 200 tokens |
| Tool call 次数 | 找到目标记忆所需 tool call 数 | 理想 1-2，上限 3 |
| 检索路径长度 | 分层检索中的「步数」 | 统计 P50, P90 |
| 检索延迟 | memory_search 响应时间 | < 100ms（文件系统） |

### Layer 3：端到端效用（End-to-End Utility）

**方法**：跨会话记忆任务（Cross-Session Memory Task）

```
Session 1（建立记忆）："帮我们配置 pytest，要求并行运行"
  → Agent 执行，产生记忆
Session 2（测试检索）："运行测试"
  → 观察 Agent 是否能找到记忆并正确使用 pytest -n auto
```

**指标**：
- **记忆利用率**：Agent 是否调用了 memory_search？是否找到相关记忆？
- **任务正确率**：Session 2 的任务是否符合 Session 1 的约定？
- **上下文一致性**：Agent 行为是否与 Session 1 决策一致？
- **用户干预次数**：用户是否需要纠正？

### Cue 质量专项度量

**实验：Cue Efficacy Test**
- 条件 A：只索引 `content`（Baseline）
- 条件 B：索引 `content` + `cues`（Phase 1）
- 用相同的 gold_queries 测试，比较 MRR
- **Cue 独立贡献度**：测量 cues 单独匹配的得分占比，> 30% 视为有效

### 与 Bourbon Eval 框架整合

```yaml
# evals/cases/memory-retrieval.yaml
- name: "memory_recall_level1_direct"
  vars:
    prompt: "How do we run tests in parallel?"
  assert:
    - type: javascript
      value: output.tool_calls.some(tc => tc.name === 'memory_search' && tc.output.includes('pytest xdist'))

- name: "memory_efficiency"
  vars:
    prompt: "any known issues in auth?"
    current_file: "src/auth.py"
  assert:
    - type: javascript
      value: output.tool_calls.filter(tc => tc.name === 'memory_search').length <= 2
```

### 最小可行实验（MVE）

**Cue Efficacy Smoke Test**：
1. 手工写 10 条记忆（含 content + cues）
2. 写 15 条查询（覆盖 Level 1/2/3）
3. Run A：只用 content 做 grep 匹配
4. Run B：content + cues 做匹配
5. 人工标注排名，计算 MRR 对比

预期 2 小时内完成，不需要改代码，可快速验证 Phase 1 方向。

---

## 8. 关键洞见总结

1. **检索是第一性原理**：存储再多，检索不回来等于不存在。社区过度优化存储层（向量数据库），忽视了检索层的认知科学基础。

2. **自生成线索是差异化机会**：社区所有项目的 cues 都是"other-generated"（系统强加的 embedding/标签）。让 Agent 在写入时生成自己的检索线索，是 Bourbon 可以做出差异化的方向。

3. **分层检索不是 UI 优化，而是 LLM 决策架构**：3-Layer Progressive Disclosure 的本质是给 LLM 提供自然的「停止/钻取」决策点，减少 token 浪费。

4. **Frozen Snapshot + 按需检索是最优中间路线**：Hermes 的稳定性和 claude-mem 的检索深度可以兼得，关键是把「背景知识」和「参考资料」分层处理。

5. **Phase 1 的度量需要新框架**：传统 IR benchmark 不适用。MERP 的三层框架（准确性→效率→效用）是验证 Phase 1 设计的可行路径。

6. **Bourbon 的领域优势**：Coding agent 有天然的检索锚点（文件路径、代码结构、错误类型），Phase 1 的设计可以比通用 agent 更深入、更精确。

---

## 9. 待决策事项

| 事项 | 状态 | 下一步 |
|-----|------|--------|
| Phase 1 实现（memory_write schema + memory_search scoring） | 待启动 | 需要确认是否立即开始 |
| Embedding 模型选型（MiniLM vs BGE-small） | 待验证 | 建议先跑 MVE，再选型 |
| Auto-extract 的模型选择（Haiku API vs 本地 Ollama） | 待讨论 | 涉及成本和延迟权衡 |
| Phase 1 的 eval 测试集构造 | 待启动 | 可并行于开发进行 |
| Per-Prompt 自动注入的进一步评估 | 保留判断 | 观察 claude-mem 长期效果后再决定 |

---

## 参考文档

- `wiki/hermes-agent-memory-architecture.md` — Hermes Agent 记忆系统深度分析
- `docs/superpowers/specs/2026-04-19-bourbon-memory-design.md` — Bourbon Memory Phase 1 设计 spec
- `docs/superpowers/specs/2026-04-22-bourbon-memory-phase2-design.md` — Bourbon Memory Phase 2 设计 spec
- [PMC5664228](https://pmc.ncbi.nlm.nih.gov/articles/PMC5664228/) — Self-generated cue mnemonics 学术研究
- [thedotmack/claude-mem](https://github.com/thedotmack/claude-mem) — Claude Code 持久记忆插件
- [yuvalsuede/memory-mcp](https://github.com/yuvalsuede/memory-mcp) — 轻量级 Claude Code 记忆系统
