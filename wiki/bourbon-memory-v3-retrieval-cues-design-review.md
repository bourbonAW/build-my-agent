# Bourbon Memory V3: Retrieval-Cue-First 设计评审

> 记录时间：2026-04-30  
> 背景：本文件整理一次关于 Bourbon memory 机制升级的设计讨论，重点是是否采用 "Frozen Snapshot + 按需检索 + 自动沉淀" 的中间路线，以及如何验证 Phase 1 的检索质量。

---

## 1. 讨论结论

Bourbon Memory V3 的推荐方向是：

```
Session 启动
  -> Frozen Snapshot 注入背景层
     - AGENTS.md
     - USER.md
     - MEMORY.md index
     - 可选 Recent Timeline

对话过程中
  -> LLM 自主决定是否调用 memory_search / memory_timeline

Session 结束或 compact 前后
  -> 自动沉淀候选 memory
     - deterministic flush 保持当前保守路径
     - LLM auto-extract 后续作为 pending/staged 候选
```

核心判断：

- Bourbon 不应该走每轮固定 top-k 自动语义注入。
- Bourbon 应保持 prompt anchor 的稳定性，利用 prefix cache 和确定性。
- 检索能力应通过按需工具暴露给 LLM，由 LLM 判断何时需要深层回忆。
- Phase 1 应优先做 retrieval cues / concepts / files 这些写入端结构化字段，而不是直接进入 embedding。
- Embedding 可以作为后续 hybrid retrieval 的辅助层，但不应成为 Bourbon memory 的地基。

---

## 2. Hermes 与 claude-mem 的设计哲学

### 2.1 Hermes: Frozen Snapshot Pattern

Hermes 的记忆层更接近人格背景和稳定偏好：

```
Session 启动
  -> 加载 MEMORY.md + USER.md
  -> 生成 Frozen Snapshot
  -> 注入 system prompt
  -> session 内保持不变
```

优点：

- system prompt 稳定，prefix cache 命中率高。
- 单个 session 内行为更确定。
- 用户偏好、项目规则等稳定背景不会在一轮轮对话中漂移。

代价：

- 常驻记忆容量有限。
- 当前 session 新写入的 memory 不会立即改变 system prompt。
- 深层历史需要显式检索。

适合存放：

- 用户偏好。
- 项目规则。
- agent 身份和长期行为约束。
- 高置信度、低变化率背景信息。

### 2.2 claude-mem: Progressive Disclosure / 按需历史召回

本次讨论中最初将 claude-mem 描述为 "每轮 Chroma top-N 自动注入"。后续查阅公开文档后，需要修正这一点：

- claude-mem 公开文档强调 SessionStart 注入索引。
- 详细 observation 通过 MCP 工具按需读取。
- 其实际设计比 "每 prompt 固定自动语义注入" 更克制，更接近 progressive disclosure。

因此，Bourbon 需要反对的不是 claude-mem 整体，而是更一般的模式：

> indiscriminate fixed top-k retrieval injection

也就是每一轮都不加判断地检索并注入一批语义相似内容。

这种模式的问题：

- 相关性不等于必要性。
- 语义相似可能带来实质无关的污染。
- 每轮 context 变化削弱 prefix cache。
- 历史 observation 容易挤压当前任务上下文。
- 自动注入形成反馈回路，可能导致记忆漂移。

---

## 3. Bourbon 的中间路线

Bourbon 更适合三层记忆结构：

| 层级 | 机制 | 是否自动 | 作用 |
| --- | --- | --- | --- |
| 背景层 | Frozen Snapshot 注入 AGENTS.md / USER.md / MEMORY.md | session 边界自动 | 解决我是谁、项目规则、用户偏好 |
| 按需层 | LLM 主动调用 memory_search / memory_timeline | LLM 自主 | 解决上次怎么做、某个决策来源、历史 debug 经验 |
| 沉淀层 | compact/session-end 自动提取候选 memory | 后台自动 | 解决 LLM 忘记写 memory |

这个结构的工程收益：

- 继续利用 Bourbon 现有 file-first memory 架构。
- 不破坏 prompt anchor 的稳定性。
- 检索结果有明确调用意图，噪声更低。
- 自动沉淀只发生在 session 边界或 compact 相关路径，不污染每轮推理。

---

## 4. Phase 1: Retrieval-Cue-First

Phase 1 的目标不是做语义检索，而是让 file-first / keyword-first 检索真正可用。

建议扩展 MemoryRecord：

```python
@dataclass
class MemoryRecord:
    # existing fields...
    concepts: list[str] = field(default_factory=list)
    retrieval_cues: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
```

字段含义：

- `concepts`: 抽象主题，例如 `["memory", "compaction", "agent-session-boundary"]`。
- `retrieval_cues`: 未来用户或 agent 可能用来查这条记忆的 query，例如 `"where should memory flush hook live"`。
- `files`: 与记忆强相关的代码路径或文档路径，例如 `src/bourbon/agent.py`。

检索评分建议：

```
score =
  exact keyword match
  + retrieval_cue boost
  + concept boost
  + current/open file boost
  + source_ref/file boost
  + recency decay
  + confidence/status filters
```

默认返回应是 index card，而不是全文：

```json
{
  "id": "mem_xxx",
  "name": "Pre-compact memory flush location",
  "kind": "project",
  "scope": "project",
  "concepts": ["memory", "compaction"],
  "files": ["src/bourbon/agent.py"],
  "snippet": "...",
  "why_matched": "retrieval_cue + file"
}
```

可选 detail 模式：

- `index`: 默认，返回卡片。
- `timeline`: 按时间排序并显示前后上下文。
- `full`: 返回完整 memory body。

---

## 5. 为什么大多数项目没有做 Phase 1

Phase 1 看起来朴素，但要求系统承认：

> 检索质量很大一部分来自写入时的结构化编码，而不是检索后端本身。

社区较少做这个方向的原因：

1. 向量检索更容易讲，也更容易 demo。
2. 很多系统把 memory 当成存储问题，而不是编码问题。
3. 写入端 schema 变复杂，会增加 LLM 工具调用负担。
4. `concepts`、`retrieval_cues`、`files` 的收益不炫，但很工程化。
5. 自动 observation log 系统更关注 ingestion pipeline，而不是未来查询会怎样表达。
6. 通用聊天 agent 没有 coding agent 的强文件上下文，`files` boost 不自然。
7. 现有 benchmark 更鼓励 embedding 解决语义相似，而不是 cue engineering。

对 Bourbon 来说，这恰好是机会：

- Bourbon 是 coding agent，任务天然绑定 repo、文件、测试和设计文档。
- Bourbon 已经是 file-first / audit-first。
- 可解释检索比黑箱 embedding 更符合当前架构。

---

## 6. Phase 2: 不急于造 embedding 轮子

社区围绕 embedding / vector DB / hybrid RAG 的 benchmark 已经很多。Bourbon 不需要在 Phase 2 重新发明这部分。

更稳妥的 Phase 2 路线：

1. 先把 Phase 1 的 structured keyword search 做扎实。
2. 再考虑 SQLite FTS / BM25 作为可解释全文检索层。
3. 最后在有明确 recall miss 证据时，引入 embedding 作为辅助分数。

建议顺序：

| 阶段 | 推荐内容 |
| --- | --- |
| Phase 1 | concepts / retrieval_cues / files / weighted keyword |
| Phase 2 | SQLite FTS or BM25, 可解释排序与 ablation |
| Phase 3 | pending/staged auto-extract |
| Phase 4 | hybrid embedding retrieval |

Embedding 不应默认进入 V3 主线的原因：

- 引入模型依赖和冷启动成本。
- 增加索引一致性与重建复杂度。
- 对中文/英文混合、代码路径、局部术语的效果需要单独验证。
- 调试难度高于 keyword/cue scoring。

---

## 7. Phase 3: Auto-Extract 的保守策略

Auto-extract 解决的问题是：

> LLM 经常忘记主动写 memory。

但它也是记忆污染的主要入口。因此推荐：

- 默认不要直接写 active memory。
- 后台 LLM 提取结果先进入 `pending` 或 staged review。
- 每次 session/compact 最多提取 0-3 条。
- 只提取声明性事实、稳定偏好、项目级决策和外部引用。
- 不提取纯任务进度和临时状态。
- 做去重：embedding similarity、keyword Jaccard 或 content hash 都可以作为后续策略。

重要边界：

- 不要在 compaction hot path 同步调用 LLM。
- deterministic pre-compact flush 仍应保留，作为低风险保守路径。
- LLM auto-extract 应作为后台整合或 session end hook。

---

## 8. Phase 1 的度量难题与评测方案

Phase 1 的效果难以用传统 semantic retrieval benchmark 衡量，因为它关心的是：

> 当未来任务需要某条记忆时，Bourbon 能否用便宜、可解释、结构化的方式把它排到前面？

因此主指标不应是主观感受，而应是可回归的 retrieval quality。

### 8.1 推荐指标

| 指标 | 含义 | 用途 |
| --- | --- | --- |
| Recall@K | 目标 memory 是否出现在 top K | 主指标 |
| MRR | 目标 memory 排名倒数 | 衡量排序质量 |
| Noise@K | top K 中明显无关结果比例 | 衡量污染 |
| Cue Lift | 加 cues 前后指标提升 | 验证 Phase 1 是否值得 |
| Decision Helpfulness | 检索结果是否帮助 agent 做出正确下一步 | 端到端辅助指标 |

### 8.2 Golden Set 格式

每条 memory 配 3-5 个 query：

- 直接关键词 query。
- 同义改写 query。
- 文件路径 query。
- 问题型 query。
- 中文/英文混合 query。

示例：

```yaml
memory_record:
  id: mem_001
  content: "Pre-compact flush is coordinated in Agent._step_impl and Agent._step_stream_impl, not Session."
  concepts:
    - memory
    - compaction
    - agent-session-boundary
  retrieval_cues:
    - where should memory flush hook live
    - why not put memory dependency in SessionManager
    - streaming path compact memory flush
  files:
    - src/bourbon/agent.py
    - src/bourbon/memory/compact.py

queries:
  - compact 前 memory flush 应该挂在哪里？
  - SessionManager 能不能依赖 MemoryManager？
  - streaming mode 下 compact 会不会漏掉 memory flush？

expected:
  relevant_ids:
    - mem_001
```

### 8.3 最小评测矩阵

| 变体 | 说明 |
| --- | --- |
| baseline_grep | 当前实现，只搜 name / description / content |
| metadata_grep | 搜 name / description / content / concepts / retrieval_cues / files |
| weighted_keyword | 加权排序：cue > concept > file > content > recency |
| ablation | 分别去掉 retrieval_cues / concepts / files，观察贡献 |

### 8.4 第一版验收线

建议先设工程化门槛：

- `Recall@8 >= 0.90`
- `Recall@3 >= 0.75`
- `MRR >= 0.65`
- `Noise@8 <= 0.35`
- Phase 1 相比 baseline 的 `MRR lift >= 20%`

如果达不到，不应直接上 embedding；应先检查：

- query set 是否覆盖真实使用场景。
- retrieval cues 是否写得像未来查询，而不是当前总结。
- scoring 权重是否过度偏向 content。
- files boost 是否匹配当前任务上下文。

---

## 9. 对 Bourbon 当前实现的映射

当前 Bourbon 已经具备 V3 的基础：

- `src/bourbon/memory/models.py`: MemoryRecord / MemoryRecordDraft / MemorySearchResult。
- `src/bourbon/memory/store.py`: file-based memory store + grep search。
- `src/bourbon/memory/prompt.py`: AGENTS.md / USER.md / MEMORY.md prompt anchors。
- `src/bourbon/memory/compact.py`: deterministic pre-compact flush candidate extraction。
- `src/bourbon/config.py`: `auto_flush_on_compact = true`, `auto_extract = false`。

缺口：

- MemoryRecord 缺少 `concepts` / `retrieval_cues` / `files`。
- search 仍主要是 grep，没有结构化字段评分。
- memory_search 默认返回结果还缺少 detail mode。
- 没有 retrieval eval golden set 和 A/B harness。
- auto-extract 仍未作为 pending/staged 后台机制实现。

---

## 10. 参考资料

- Hermes Agent memory docs: https://hermes-agent.nousresearch.com/docs/user-guide/features/memory/
- claude-mem docs: https://docs.claude-mem.ai/usage/getting-started
- OpenAI API prompt caching: https://openai.com/index/api-prompt-caching/
- Wheeler & Gabbert, "Using Self-Generated Cues to Facilitate Recall": https://www.frontiersin.org/article/10.3389/fpsyg.2017.01830/full
- "Lost in the Middle: How Language Models Use Long Contexts": https://direct.mit.edu/tacl/article/doi/10.1162/tacl_a_00638/119630/Lost-in-the-Middle-How-Language-Models-Use-Long
- Self-RAG paper summary: https://huggingface.co/papers/2310.11511
- Bourbon Memory Phase 1 design: `docs/superpowers/specs/2026-04-19-bourbon-memory-design.md`
- Bourbon Memory Phase 2 design: `docs/superpowers/specs/2026-04-22-bourbon-memory-phase2-design.md`

---

## 11. Final Recommendation

Bourbon Memory V3 应该采用：

> Frozen Snapshot for stable background, retrieval-cue-first search for deep recall, staged auto-extract for durable consolidation.

Phase 1 的价值不是替代 embedding，而是在 Bourbon 最有优势的地方建立可解释检索地基：

- 文件上下文。
- 项目决策。
- debug 经验。
- 用户偏好和反馈。
- 可审计 Markdown 记忆。

真正需要验证的是：

> agent 写下 retrieval cues 之后，未来真实 coding/query 场景能不能用这些 cues 更快、更准地找回记忆。

因此，Phase 1 的成功标准应由 Recall@K、MRR、Noise@K 和 Cue Lift 定义，而不是由主观体验或通用 embedding benchmark 定义。
