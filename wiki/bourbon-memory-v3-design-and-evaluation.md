# Bourbon Memory V3：设计决策与评估框架

> 本文记录了对 Bourbon Memory 系统 V3 升级的完整设计讨论，涵盖架构哲学、三阶段升级路径、Phase 1 在体系中的真正地位，以及度量难题的系统性解法。
>
> 讨论时间：2026-04-30
> 参考资料：[PMC5664228 - Memory Systems & Retrieval](https://pmc.ncbi.nlm.nih.gov/articles/PMC5664228/)、Hermes、claude-mem

---

## 1. 背景：两种记忆架构哲学

### 1.1 Hermes：Frozen Snapshot Pattern — 记忆是「人格背景」

```
Session 启动
    ↓
加载 MEMORY.md + USER.md
    ↓
生成 Frozen Snapshot（注入 system prompt）
    ↓
整个会话内 system prompt 不变 ← prefix cache 命中
    ↓
Session 结束
    ↓
下次启动重新加载
```

**核心假设**：记忆的本质是 agent 的人格、偏好、项目背景——这些东西在单次会话内不应该变来变去。

**检索角色**：记忆几乎不「被检索」，而是被注入。LLM 不需要调用工具来回忆，因为这些东西已经在 system prompt 里。

**优势**：
- Prefix cache 命中率最大化（system prompt 不变 → KV cache 复用）
- 零延迟（不需要 mid-session 检索）
- 行为一致性（同一 session 内记忆不会前后矛盾）

**代价**：
- 记忆容量硬上限（2200+1375 字符）
- 当前会话的新发现不能立即被感知
- 跨会话历史（SQLite FTS5）需要显式查询

### 1.2 claude-mem：Per-Prompt 语义注入 — 记忆是「实时参考资料」

```
用户输入 > 20 字符
    ↓
Chroma 语义搜索相关 observations
    ↓
top-N 相关记忆注入当前 prompt 的 additionalContext
    ↓
LLM 生成回复
    ↓
下一轮 → 再次搜索 → 再次注入
```

**核心假设**：记忆的本质是项目历史、代码变更、debug 记录——这些东西和当前任务高度相关，应该「需要时出现」。

**检索角色**：记忆是被检索的，且检索是自动的、每轮触发的。

**优势**：
- 高度情境化
- 没有容量上限
- 新记忆可以被立即利用

**代价**：
- Prefix cache 完全失效
- 检索延迟累积
- 「过度激活」风险（语义相似但实质无关的记忆被拉进来）
- 推理成本上升

### 1.3 Per-Prompt 自动注入的隐藏陷阱

社区低估的几个问题：

1. **混淆了「工作记忆」和「长期记忆」的边界**：claude-mem 的 observation 本质属于会话内工作记忆的延伸，但被当成长期记忆每轮注入，会污染 context window。

2. **「相关性」不等于「必要性」**：向量搜索返回语义相似的记忆，但 LLM 当前轮次不一定需要。自动注入剥夺了 LLM「判断是否需要」的权利。

3. **Frozen Snapshot 的隐性价值：确定性**：同一 session 内，给定相同输入，agent 行为可预测。Per-Prompt 注入引入非确定性——上一轮的注入改变行为，下一轮注入不同的记忆，形成「记忆漂移」反馈环。

---

## 2. Bourbon 的中间路线：Frozen Snapshot + 按需检索

```
┌──────────────────────────────────────────────────────────────┐
│  Session 启动                                                │
│    Frozen Snapshot 注入                                       │
│    ├── AGENTS.md（项目规则）                                  │
│    ├── USER.md（用户偏好 + promoted blocks）                  │
│    ├── MEMORY.md（精华记忆索引，≤200 条 active）              │
│    └── Recent Timeline（最近 N 条 project 记忆标题）          │
│         ↑ 这是「背景层」，session 内不变                       │
└──────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────┐
│  对话过程中                                                  │
│    LLM 自主决策                                              │
│    ├── 不需要额外记忆 → 正常对话                               │
│    └── 需要深层记忆 → 主动调用 memory_search / memory_timeline │
│         ↑ 这是「按需层」，LLM 控制何时检索、检索什么            │
└──────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────┐
│  Session 结束 / Context Compression                           │
│    自动提取（Auto-Extract）                                    │
│    ├── Compaction hook 触发                                   │
│    ├── 小模型分析 transcript                                   │
│    └── 生成 0-3 条 observations → memory_write                │
│         ↑ 这是「沉淀层」，把会话经验转化为长期记忆              │
└──────────────────────────────────────────────────────────────┘
```

### 2.1 三层架构对应关系

| 层级 | 对应人类记忆 | 机制 | 是否自动 |
|------|------------|------|---------|
| 背景层 | 长期人格/知识 | Frozen Snapshot 注入 | 是（session 边界） |
| 按需层 | 回忆/联想 | LLM 主动调用 memory_search | 否（LLM 自主） |
| 沉淀层 | 经验固化 | Auto-Extract at session end | 是（自动化） |

- **背景层**：解决「我是谁、我在哪、用户偏好什么」——Hermes 路线
- **按需层**：解决「上次那个配置是怎么设的」——claude-mem 的检索能力，但由 LLM 主动触发
- **沉淀层**：解决「把这次的经验记下来下次用」——自动提取，不需要 LLM 每轮都想着写记忆

---

## 3. V3 三阶段升级路径

### Phase 1：检索增强（Retrieval-Cue-First）

**目标**：在现有文件优先架构上，把「检索」做到可用、好用。

**改动点**：

1. `MemoryRecord` 增加 `concepts` 和 `retrieval_cues` 字段：
   ```python
   @dataclass
   class MemoryRecord:
       # ... existing fields ...
       concepts: list[str] = field(default_factory=list)
       # e.g., ["how-it-works", "trade-off", "gotcha"]
       retrieval_cues: list[str] = field(default_factory=list)
       # e.g., ["JWT token expiry", "auth session handling"]
       files: list[str] = field(default_factory=list)
   ```

2. `memory_write` 工具增强：让 LLM 在写入时生成 cues 和 concepts，引导生成「未来检索时会用的关键词」。

3. `memory_search` 分层返回：
   - 默认：索引卡片（id, name, kind, concepts, snippet, file）
   - `detail: "timeline"`：按时间排序 + 前后上下文
   - `detail: "full"`：完整内容

4. 检索相关性增强：
   - 当前打开的文件路径 → 优先匹配 `files` 字段
   - 当前对话主题 → 优先匹配 `concepts`
   - recency → 适当提升权重

**技术方案**：纯关键词 + 结构化字段匹配，不需要向量数据库。
评分公式：`match_score = keyword_match + concept_boost + file_boost + recency_decay`

### Phase 2：轻量 Embedding（语义检索层）

**目标**：解决「query 和记忆表面形式不匹配」的问题。

**改动点**：

1. 引入轻量本地 embedding：
   - `sentence-transformers/all-MiniLM-L6-v2`（~80MB，CPU 推理 < 10ms）
   - 或更轻量：`BAAI/bge-small-en-v1.5`（~30MB）

2. 混合检索策略：
   ```
   memory_search(query)
    ├── 结构化过滤（type/scope/status/file/concepts）
    ├── 关键词匹配（retrieval_cues + content grep）
    └── 语义匹配（embedding cosine similarity）
        └── 融合排序（weighted fusion）
   ```

3. Embedding 存储：建议集中式（`memory/.embeddings/index.json`），而不是 200 个独立 `.npy` 文件。

### Phase 3：自动提取（Auto-Extract at Session End）

**目标**：解决「LLM 忘记主动写记忆」的问题。

**改动点**：

1. Session End / Compaction Hook 触发，读取当前 session 的 transcript
2. 使用 cheap 模型（Haiku-tier）分析 transcript：
   - Prompt：「从这段对话中提取 0-3 条值得长期保存的记忆。只提取声明性事实和用户偏好，不提取任务进度。」
   - 输出：JSON 数组，每条包含 `content, kind, scope, concepts, retrieval_cues`
3. 去重检查：cosine similarity > 0.85 → 视为重复，跳过；或关键词 Jaccard > 0.6 → 合并

**重要 caveat**：Bourbon 当前的 `compact.py` 已实现了一个**确定性版本**的沉淀层（关键词正则匹配 "remember"/"always"/"never" + 中文等价词）。Phase 3 的 LLM 提取应作为增强而非替换，否则引入了新的模型依赖、非确定性、延迟。

**更保守的 Phase 3 方案**：增强现有 `compact.py` 的提取规则（加入 tool call 结果分析、用户确认模式识别），同时在 compaction 时对已有记忆做去重检查。

---

## 4. 与 Bourbon 现有架构的兼容性

| 现有组件 | Phase 1 | Phase 2 | Phase 3 |
|---------|---------|---------|---------|
| memory/ 目录 | ✅ 直接兼容 | ✅ 增加 .embeddings/ 子目录 | ✅ 直接兼容 |
| MEMORY.md 索引 | ✅ 增加 concepts 字段 | ✅ 不变 | ✅ 自动提取的也会进索引 |
| memory_write | ✅ 增加可选参数 | ✅ 同步生成 embedding | ✅ 不变 |
| memory_search | ✅ 增加 scoring | ✅ 增加语义匹配 | ✅ 不变 |
| memory_promote | ✅ 不变 | ✅ 不变 | ✅ 不变 |
| SessionManager | ✅ 不变 | ✅ 不变 | ✅ 增加 auto-extract hook |
| TranscriptStore | ✅ 不变 | ✅ 不变 | ✅ 作为 auto-extract 输入 |
| Prompt Builder | ✅ 增加 timeline section | ✅ 不变 | ✅ 不变 |

**所有改动都是增量式的，不需要推翻现有架构。**

Bourbon 现状（截至 2026-04）：
- ✅ Frozen Snapshot 注入（`memory_anchors_section`）
- ✅ memory_search / memory_write / memory_status 工具
- ✅ 关键词驱动的 compact.py
- ✅ Phase 2 promote/reject lifecycle（USER.md managed blocks）
- ❌ retrieval_cues / concepts 字段
- ❌ embedding 语义检索
- ❌ LLM 驱动的 auto-extract

---

## 5. 核心洞察：Phase 1 不是锦上添花，而是体系基础

### 5.1 社区的认知盲区

90% 的 memory 项目把工程资源投在「检索机制」上：
```
向量数据库 → BM25 → 混合搜索 → Reranker → ...
```

但真正的瓶颈往往在**写入时编码了什么**。这是经典的数据库 schema 设计问题——再强的查询优化器也救不了糟糕的表结构。

### 5.2 编码特异性原则的工程翻译

PMC 文章的编码特异性原则（Encoding-Specificity Principle）：

> **检索时用的 query 语言，必须和写入时编码的信息有足够重叠**

工程现实中，这两者天然存在语义鸿沟：

```
写入时的表达：
"用户偏好使用 uv 管理 Python 依赖，因为 pip 导致过依赖冲突"

检索时的 query：
"怎么安装这个包？"
```

这两句话的 embedding cosine similarity 并不高——即使最好的 Phase 2 语义搜索也可能失效。但如果写入时存了：

```yaml
retrieval_cues: ["package installation", "dependency management", "python tooling", "pip alternative"]
```

检索就稳了。**Phase 1 的本质是在编码时预计算「未来的检索上下文」**。

### 5.3 Phase 1 × Phase 2 = 乘法关系，不是先后关系

正确的关系：

```
Phase 2（embedding）对什么做 embedding，决定了检索质量的上限。

如果 embed 的是原始内容 → 只能捕获内容本身的语义
如果 embed 的是 retrieval_cues → 捕获的是"未来会怎么找它"的语义
```

接近 RAG 领域的 HyDE（Hypothetical Document Embeddings）思路——不直接 embed 内容，而是 embed「这个内容会在什么问题下被检索到」。

**Phase 1 不是 Phase 2 的前置准备，而是让 Phase 2 的上限提高一个数量级的关键输入**。

### 5.4 concepts 字段的双重作用

绝大多数系统只把 metadata 当过滤器用。但 `concepts` 字段实际承担两个职责：

**职责一：检索时的过滤信号**
```python
memory_search(query="JWT token", concept_filter=["gotcha"])
```

**职责二：检索后的使用指南**

不同 concepts 触发不同的推理模式：
- `gotcha` → 警告式推理（「这个地方之前踩过坑，要小心」）
- `how-it-works` → 参考式推理（「这是背景知识，按需引用」）
- `trade-off` → 权衡式推理（「这里有取舍，需要结合当前需求判断」）

这不仅是「找到」的问题，而是「找到后怎么用」的问题。claude-mem 的 concepts 字段（`how-it-works`、`gotcha`、`trade-off`、`pattern`）正是这个逻辑的落地。

### 5.5 为什么大多数项目没做 Phase 1

不是没意识到，是几个现实原因：

1. **写入时的 LLM 调用成本**——生成 retrieval_cues 需要 LLM 在写入时额外推理，成本可见
2. **收益延迟性**——效果要到几十条记忆之后才明显，早期看不出来
3. **schema 设计难**——「什么是好的 retrieval cue」没有现成答案，需要对使用场景的深度理解
4. **「检索机制」更容易 demo**——换个向量库、调调参数，benchmark 数字立竿见影

### 5.6 修订后的结论

```
Phase 1（写入质量）× Phase 2（检索机制）= 实际可用的记忆系统
```

两者缺一只有半个系统。**先把 Phase 1 做好，Phase 2 的收益才能完全释放**。反过来 Phase 2 先上，用在质量不高的 embedding 内容上，收益会很有限。

---

## 6. 度量难题：如何验证 Phase 1 的有效性

### 6.1 为什么传统 IR benchmark 失效

传统检索评估（NDCG、MRR、Recall@K）的隐含前提：**存在已知的 ground truth 标注**。

Phase 1 的问题域不满足这个前提：

| 传统 IR 假设 | Phase 1 记忆检索的现实 |
|-------------|---------------------|
| Query 是明确的、完整的 | Agent 的检索触发往往是隐式的、不完整的 |
| Doc 集合是静态的 | 记忆是动态增长的，新记忆可能改变旧记忆的检索相关性 |
| Relevance 是二元或分级的 | 记忆的相关性取决于当前任务上下文，同一记忆在不同任务中价值不同 |
| 评估目标是最小化 ranking error | 评估目标是最大化 agent 任务成功率 |

最严重的失败模式是**沉默**（该检索的没检索到），而不是错误（检索到了但不对）。**沉默是不可观测的**——你不知道 LLM 在某一刻"需要"但没找到什么记忆。这是 Phase 1 度量难题的核心。

### 6.2 MERP 三层度量框架

```
┌─────────────────────────────────────────────────────────────┐
│  Layer 3: 端到端效用层（End-to-End Utility）                  │
│  「有 Phase 1 检索的 agent 是否比没有的完成任务更好？」          │
│  指标：任务成功率、上下文利用度、用户满意度                     │
├─────────────────────────────────────────────────────────────┤
│  Layer 2: 检索效率层（Retrieval Efficiency）                  │
│  「检索过程本身消耗了多少资源？LLM 是否能有效导航分层检索？」    │
│  指标：token 消耗、tool call 次数、检索路径长度                 │
├─────────────────────────────────────────────────────────────┤
│  Layer 1: 检索准确性层（Retrieval Accuracy）                  │
│  「给定一个明确的检索需求，系统能否找到正确的记忆？」            │
│  指标：Recall@k、MRR、分层检索成功率                          │
└─────────────────────────────────────────────────────────────┘
```

#### Layer 1：检索准确性（构造可控测试集）

**测试集构造**：
- 写入 20-30 条 seed memories，覆盖不同 kind、concepts、files
- 设计三个难度等级的查询：
  - **Level 1（直接匹配）**：query 包含记忆内容中的关键词
  - **Level 2（语义扩展）**：语义相关但表面形式不同
  - **Level 3（上下文推断）**：需要结合当前上下文（如打开的文件）才能推断

**关键指标**：
- Recall@k（k=3 或 k=5）
- MRR
- 分层检索成功率：LLM 能否通过 ≤2 轮 tool call 找到 gold memory

**关键对比**：
- Baseline A：当前 Bourbon（grep 关键词）
- Treatment B：Phase 1（cues + concepts + 分层检索）
- Treatment C：Phase 1 + 轻量 embedding

#### Layer 2：检索效率

| 指标 | 测量方法 | 目标 |
|------|---------|------|
| Token 消耗 | 每次 memory_search 返回内容的 token 数 | Layer 1 应 < 200 tokens |
| Tool call 次数 | 找到目标记忆所需调用数 | 理想 1-2，上限 3 |
| 检索路径长度 | 分层检索的步数 | P50, P90 分布 |
| 检索延迟 | memory_search 响应时间 | 文件系统检索 < 100ms |

```python
search_log = {
    "query": query,
    "detail_level": "index" | "timeline" | "full",
    "results_count": len(results),
    "tokens_returned": count_tokens(results),
    "layer_reached": 1 | 2 | 3,
    "found_target": bool,
}
```

#### Layer 3：端到端效用（跨会话记忆任务）

```
Session 1（建立记忆）：
  "帮我们配置 pytest，要求并行运行"
  → Agent 修改 pytest.ini，安装 xdist
  → 写入 Memory A

Session 2（测试检索）：
  "运行测试"
  → 观察 Agent 是否通过 memory_search 找到 Memory A
  → 观察是否正确使用 pytest -n auto

对照组：Session 2 中无 memory_search 上下文 → Agent 用默认 pytest
```

**评估指标**：记忆利用率、任务正确率、上下文一致性、用户干预次数。

### 6.3 MERP 框架的内在矛盾

Kimi 的 MERP 在开篇正确指出「传统 IR benchmark 失效是因为有静态标注数据集」，但 Layer 1 的解法又是**手工构造 20-30 条 seed memories + 设计 Level 1/2/3 查询**——这就是个静态标注数据集，只是换了一层皮。

具体问题：

1. **测试匹配算法，不测真实使用模式**：手工设计的 query 永远滞后于真实分布，LLM 实际形成的 query 可能完全不同。

2. **测试 cue 的匹配能力，不测 cue 的生成质量**：MVE 里手工写 retrieval_cues，但 Phase 1 实际跑起来时 cues 是 LLM 在 memory_write 时生成的。整个系统的瓶颈很可能在 cue 生成质量。

3. **假设 Phase 1 的 cues 设计已经正确，只验证收益**：但你真正需要的信号是「我的 cues 字段设计应该是什么形态」。

### 6.4 改进方案：从合成数据 → 真实回放

**Layer 1 重构**：
1. 当前 Bourbon 加 memory_search 的完整 telemetry（query / results / 后续是否被引用）
2. 跑 2 周收集真实调用
3. 对每条调用做事后标注（人工/LLM-as-judge）
4. 对比 Run A（当前实现）vs Run B（Phase 1 增强）

**补回 Cue 生成质量度量**（Kimi 漏掉的）：

```
对同一条 memory_write 输入：
  让 LLM 生成 cues v1（无引导 prompt）
  让 LLM 生成 cues v2（带 few-shot example）
  让 LLM 生成 cues v3（写完后让 LLM 自己生成「我未来会用什么 query 找它」）

测试：哪个版本的 cues 在真实查询集上召回率更高？
```

输出不是「Phase 1 行不行」，而是「memory_write 工具的 prompt 应该怎么写」——这才是 Phase 1 落地最关键的工程决策。

**Layer 3 简化**：单组运行 + 自我对比。同一组 cross-session task 跑两次（无 Phase 1 vs 有 Phase 1），10 个任务足够。

### 6.5 行为代理指标（不依赖标注）

| 指标 | 含义 | 实现成本 |
|------|------|---------|
| Utilization Rate（利用率）| 检索后被实际引用的记忆 / 总检索 | 低，audit log 已有 |
| Search Efficiency（搜索效率）| 完成一个信息需求的 search 次数 | 低 |
| Post-hoc Coverage（事后覆盖率）| compaction 时主动探测漏检 | 中，compaction 扩展 |
| Cue Coverage Test（写入时）| LLM 生成假设 query，看记忆是否能被找到 | 中，Haiku 调用 |

**Cue Coverage Test 详解**：

```
写入一条记忆时：
  1. 已有 retrieval_cues
  2. 用 cheap 模型生成 N 条这条记忆「应该被找到」的假设 query
  3. 对每条假设 query 执行关键词匹配 + embedding 搜索
  4. 检查该记忆是否在 top-3 中出现

覆盖率 = 该记忆出现在 top-3 / N 条假设 query
```

优雅之处：**写入时自测，不需要等到真正的检索事件**。如果覆盖率低，立即提示 LLM 补充 retrieval_cues，形成 write-time 的质量反馈环。

### 6.6 MERP 漏掉的关键维度：记忆密度

Phase 1 的真正价值在于：当记忆从 10 条 → 100 条 → 200 条时，关键词/语义碰撞越来越多，系统应该退化得比 baseline 慢。

任何 Phase 1 的度量都应包含「记忆密度」维度——不是「Phase 1 比 baseline 好多少」，而是「Phase 1 在 50/100/200 条记忆下分别比 baseline 好多少」。

如果差距随记忆数量扩大，说明 Phase 1 的 retrieval cue 设计真正抵抗了规模带来的噪声。这是单点 benchmark 抓不到的结构性收益，也是 Bourbon 200 条 active 上限设计下最值得验证的假设。

### 6.7 evals/ 目录的资产分类

把 eval 拆成两类资产：

- **Regression suite（合成、稳定）**：手工构造的小测试集，用于检测代码改动是否破坏检索逻辑。目标是 stable 而不是真实。
- **Field metrics（真实、流动）**：从日常使用中收集的 telemetry，定期生成报告。目标是真实而不是稳定。

很多项目把这两件事混在一起，导致 eval 既不严谨（数据是合成的）又不实用（不能反映真实使用）。

---

## 7. 推荐实施顺序

修订后的优先级：

```
Phase 2（embedding，社区已有成熟方案，直接采纳）
  ↓
Phase 1（cue 生成质量是 Bourbon 真正需要原创的部分）
  ↓
Phase 3（增强现有规则，而不是 LLM 化）
```

**实施路径**：

1. **诊断阶段**（1 周）：在当前 Bourbon 加 memory_search telemetry，收集真实使用数据
2. **MVE 验证**（半天）：对 MEMORY.md 中实际记忆，让 Haiku 生成假设 query，跑当前系统，看召回率基线和失败案例
3. **Phase 2 实施**：引入 sentence-transformers，集中式 embedding 存储
4. **Phase 1 实施**：基于诊断阶段的失败案例，设计 retrieval_cues schema 和 memory_write prompt
5. **Cue Coverage Test 集成**：写入时自测反馈环
6. **Phase 3 增量**：增强 compact.py 规则，加入去重检查

---

## 8. 关键参考文献

- **PMC5664228**：Memory Systems & Retrieval（Encoding-Specificity Principle、Cue Distinctiveness、Spreading Activation）
- **Hermes**：Frozen Snapshot Pattern 的代表实现
- **claude-mem**：Per-Prompt 语义注入 + 结构化 metadata（concepts/facts/title）的代表实现
- **Bourbon Memory Phase 1/2 Specs**：`docs/superpowers/specs/2026-04-19-bourbon-memory-design.md`、`docs/superpowers/specs/2026-04-22-bourbon-memory-phase2-design.md`

---

## 9. 关键决策摘要

1. ✅ **架构哲学**：Frozen Snapshot + 按需检索 + 自动沉淀，三层结构
2. ✅ **Phase 1 是基础设施而非锦上添花**：解决编码特异性问题，与 Phase 2 是乘法关系
3. ✅ **concepts 双重作用**：检索过滤 + 使用指南
4. ⚠️ **度量必须基于真实使用数据**：MERP 框架结构正确，但 Layer 1 应改用 telemetry-driven 而非合成数据集
5. ⚠️ **核心未解问题**：cue 生成质量的 prompt 工程——Phase 1 落地的最关键决策
6. 📊 **必测维度**：记忆密度（10/100/200 条下的退化曲线），这是 Phase 1 真正的差异化收益所在
