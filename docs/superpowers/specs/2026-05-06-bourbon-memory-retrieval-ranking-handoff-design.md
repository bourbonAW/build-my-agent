# Bourbon Memory Retrieval / Ranking Handoff Design

**日期**：2026-05-06
**状态**：Handoff Spec
**范围**：定义 Memory Cue Engine 之后的检索与排序层如何消费 `MemoryCueMetadata` 和 `QueryCue`。本文是 Phase 5 交付，不实现代码，不改变当前 `memory_search` tool schema。

---

## 1. 背景

Memory Phase 1/2 已经完成文件优先的 memory stack：

- 每条 memory 是一个可审计 Markdown 文件。
- `MEMORY.md` 是 active memory 的 prompt index。
- `USER.md` managed block 承载 promoted preference。
- `memory_search` 当前仍以文件 grep 为主。

Cue Engine Phase 0-4 已经把“未来如何找回”从非结构化正文中拆出来：

- record-side：`MemoryCueMetadata` 持久化在 memory record frontmatter 中。
- query-side：`QueryCue` 在检索时临时生成。
- runtime evidence：文件、symbol、source_ref 优先于 LLM 猜测。
- eval：已有 generation quality、cue coverage、retrieval ablation、density curve 和 promptfoo smoke。

下一步不是继续增强 CueEngine，而是设计一个独立 retrieval/ranking layer，让 cue representation 进入候选召回和排序，同时保留 Bourbon 当前 file-first、audit-first、local-first 的优势。

---

## 2. 核心结论

推荐路线：

```text
Phase R1: Local FTS/BM25 candidate retrieval
Phase R2: Cue-aware fusion/ranking
Phase R3: Optional semantic channel via derived text
Phase R4: Optional embedding backend
```

不推荐直接进入 embedding-first。

原因：

- 当前 memory 规模主要是 10-200 active records，本地 FTS/BM25 已足够解决 grep 的粗糙匹配和排序问题。
- Bourbon 的 memory 是治理对象，不只是 RAG corpus；可解释性、权限、scope/status 过滤、source_ref 审计比纯语义召回更重要。
- Cue metadata 已经结构化，先让 FTS/BM25 消费 cue fields，可以最快验证 cue representation 的 ROI。
- HyDE-like semantic text 应作为 `QueryCue` / `MemoryCueMetadata` 的派生表示，不应成为 canonical interface。

---

## 3. 目标

1. **保持 CueEngine 边界**：CueEngine 只生成表示，不做 ranking，不返回最终 memory ids。
2. **提升候选召回**：让 search 不只搜 memory body，也搜 concepts、retrieval cues、files、symbols 和 query cue phrases。
3. **保持权限正确**：scope、kind、status 是硬过滤，不是 ranking signal。
4. **保持可解释性**：每条结果必须能解释命中 channel 和主要 cue。
5. **本地优先**：第一版 retrieval index 是可重建的本地派生索引，不引入外部服务。
6. **可评测演进**：所有 ranking 调整必须先通过 Phase 4 harness 和 density curve。

---

## 4. 非目标

- 不在本文实现 SQLite FTS、BM25、embedding 或 reranker。
- 不改变 `memory_write` / `memory_search` / `memory_status` 的用户可见基本语义。
- 不把 promoted USER.md injection 改造成按需 retrieval。
- 不让 LLM 直接决定最终排序。
- 不把不存在的 LLM-suggested file path 变成权威文件引用。
- 不把 semantic text / HyDE document 作为 source of truth。

---

## 5. 分层架构

```text
memory_search tool
  ↓
MemoryManager.search()
  ↓
MemoryRetriever
  ├─ QueryCueAdapter
  ├─ CandidateGenerators
  │   ├─ content channel
  │   ├─ record cue channel
  │   ├─ query cue expansion channel
  │   ├─ file/symbol exact channel
  │   └─ semantic channel (future)
  ├─ FusionRanker
  └─ SearchTelemetry
  ↓
MemoryStore / MemoryIndex
  ├─ markdown files: authoritative source
  └─ local derived index: rebuildable acceleration
```

职责边界：

| 组件 | 负责 | 不负责 |
|---|---|---|
| CueEngine | 生成 `MemoryCueMetadata` / `QueryCue` | ranking、权限、最终结果 |
| MemoryStore | 读写权威 Markdown records | 复杂排序 |
| MemoryIndex | 派生索引、FTS/BM25 查询 | 权威状态 |
| MemoryRetriever | 候选召回、融合排序、解释 | 写 memory |
| MemoryManager | tool-facing orchestration、权限过滤、audit | 具体 ranking 算法 |

---

## 6. 数据流

### 6.1 写入后索引

```text
memory_write
  ↓
MemoryManager.write()
  ↓
MemoryStore.write_record(markdown)
  ↓
CueEngine.generate_for_record()         # config gated
  ↓
MemoryStore.update_cue_metadata()
  ↓
MemoryIndex.upsert(record)              # future retrieval phase
```

索引是派生物。Markdown memory record 仍是 source of truth。索引损坏时可以从 memory files 全量重建。

### 6.2 查询

```text
memory_search(query, filters)
  ↓
MemoryManager.search()
  ↓
CueEngine.interpret_query(query, runtime_context)   # optional, cached
  ↓
MemoryRetriever.search(SearchRequest)
  ↓
CandidateGenerators produce channel candidates
  ↓
FusionRanker merges candidates
  ↓
MemorySearchResult[] with why_matched / debug info
```

`recall_need` 是 policy signal，不是 hard switch：

- `none`：仍可执行 search，但不主动扩大搜索预算。
- `weak`：使用默认候选预算。
- `strong`：扩大候选预算，保留更多低分候选供 fusion 判断。

---

## 7. SearchRequest / SearchResponse

内部接口建议：

```python
@dataclass(frozen=True)
class SearchRequest:
    query: str
    query_cue: QueryCue | None
    scope: str | None
    kinds: list[str] | None
    statuses: list[str]
    limit: int
    runtime_context: CueRuntimeContext | None
    debug: bool = False


@dataclass(frozen=True)
class RetrievalCandidate:
    memory_id: str
    channel: str
    raw_score: float
    matched_terms: list[str]
    matched_fields: list[str]


@dataclass(frozen=True)
class RankedMemoryResult:
    memory_id: str
    score: float
    candidates: list[RetrievalCandidate]
    why_matched: str
```

外部 tool 输出仍可映射为当前 `MemorySearchResult`：

```text
id, name, kind, scope, status, confidence, snippet, why_matched
```

`debug_retrieval` 可以以后作为 opt-in 字段加入，不应默认输出完整 ranking trace。

---

## 8. Index 设计

### 8.1 权威数据与派生索引

权威数据：

```text
~/.bourbon/projects/{project}/memory/*.md
```

派生索引：

```text
~/.bourbon/projects/{project}/memory/index.sqlite
```

原则：

- index 可删除、可重建。
- index version 必须记录 cue schema version。
- index 不保存比 Markdown record 更高权限的信息。
- index rebuild 不能修改 memory records。

### 8.2 推荐 SQLite schema

```sql
CREATE TABLE memory_index_meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE memory_records (
  id TEXT PRIMARY KEY,
  path TEXT NOT NULL,
  kind TEXT NOT NULL,
  scope TEXT NOT NULL,
  status TEXT NOT NULL,
  confidence REAL NOT NULL,
  updated_at TEXT NOT NULL,
  cue_schema_version TEXT,
  cue_generation_status TEXT
);

CREATE VIRTUAL TABLE memory_fts USING fts5(
  memory_id UNINDEXED,
  name,
  description,
  content,
  concepts,
  retrieval_cues,
  files,
  symbols,
  domain_concepts,
  tokenize='unicode61'
);

CREATE TABLE cue_terms (
  memory_id TEXT NOT NULL,
  term TEXT NOT NULL,
  kind TEXT NOT NULL,
  source TEXT NOT NULL,
  confidence REAL NOT NULL,
  field TEXT NOT NULL
);
```

`memory_fts` 服务于 BM25-style full text search。`cue_terms` 服务于 explainability、ablation、exact cue matching 和 future telemetry。

---

## 9. Candidate Channels

### 9.1 content channel

输入字段：

- `name`
- `description`
- `content`

用途：

- 保持当前 grep 行为的语义连续性。
- 支持没有 cue metadata 的旧 memory。

### 9.2 record cue channel

输入字段：

- `MemoryCueMetadata.concepts`
- `domain_concepts`
- `retrieval_cues.text`
- `files`
- `symbols`

用途：

- 让写入时编码的未来检索表达参与召回。
- 在 memory density 上升时减少正文关键词碰撞。

### 9.3 query cue expansion channel

输入字段：

- `QueryCue.cue_phrases`
- `QueryCue.concepts`
- `QueryCue.file_hints`
- `QueryCue.symbol_hints`
- `QueryCue.kind_hints`
- `QueryCue.scope_hint`

规则：

- `kind_hints` / `scope_hint` 只能作为 soft hints，除非用户/tool 参数显式传入 `kind` / `scope`。
- `file_hints` / `symbol_hints` 可以强 boost，但不能绕过 scope/status 过滤。
- `uncertainty` 高时扩大候选数，降低 query cue 权重。

### 9.4 file/symbol exact channel

输入字段：

- runtime current/touched/modified files
- `source_ref.file_path`
- `MemoryCueMetadata.files`
- `MemoryCueMetadata.symbols`

规则：

- runtime-derived file/symbol exact match 是高置信 boost。
- LLM-suggested non-existing path 不能进入 authoritative `files`，只能作为低置信 cue text。

### 9.5 semantic channel

后续可选。

输入文本必须从结构化 cue 派生：

```text
semantic_memory_text = render(MemoryCueMetadata + record name/description)
semantic_query_text = render(QueryCue + original query)
```

语义通道不得替代结构化 cue，也不得成为唯一召回通道。

---

## 10. Fusion Ranking

推荐第一版使用 weighted reciprocal rank fusion，而不是手写单一大公式。

```python
score(memory_id) =
  w_content * rrf_rank(content_channel)
  + w_record_cue * rrf_rank(record_cue_channel)
  + w_query_cue * rrf_rank(query_cue_channel)
  + w_file_exact * exact_file_match
  + w_symbol_exact * exact_symbol_match
  + w_recency * bounded_recency_boost
```

初始权重建议：

| Signal | Weight |
|---|---:|
| content channel | 1.0 |
| record cue channel | 1.4 |
| query cue channel | 1.2 |
| runtime file exact | 2.0 |
| runtime symbol exact | 1.8 |
| source_ref exact | 2.5 |
| recency bounded boost | 0.2 |

调整规则：

- `QueryCue.uncertainty >= 0.7`：query cue weight 乘以 0.6，candidate budget 乘以 1.5。
- `recall_need == strong`：candidate budget 乘以 2.0，不直接改变最终 score。
- `recall_need == none`：candidate budget 维持最小值，不禁用 search。
- `CueGenerationStatus.FAILED`：record cue channel 不参与该 record，content channel 仍参与。

---

## 11. Filtering Rules

硬过滤：

- `status`
- explicit `scope`
- explicit `kind`
- actor permissions
- project key / memory directory boundary

软信号：

- `QueryCue.scope_hint`
- `QueryCue.kind_hints`
- concepts
- recency
- uncertainty
- recall_need

重要边界：

```text
用户/tool 明确传入的 filter > QueryCue hints
```

例如：用户搜索 `scope="project"` 时，即使 `QueryCue.scope_hint == user`，也不能返回 user scope memory。

---

## 12. Explainability

每个结果的 `why_matched` 应包含：

```text
content: pytest
record cue: never mock database
query cue: persistence policy
file exact: src/bourbon/memory/store.py
```

debug 模式可以额外返回：

```json
{
  "retrieval_debug": {
    "query_cue": {"recall_need": "weak", "uncertainty": 0.2},
    "channels": [
      {"name": "content", "candidates": 12},
      {"name": "record_cue", "candidates": 8}
    ],
    "ranker": "weighted_rrf_v1"
  }
}
```

默认不返回：

- 完整 query text hash 以外的 telemetry payload。
- memory body。
- hidden prompt。
- full ranking trace。

---

## 13. Telemetry

沿用 Phase 4 `CueEvalEvent` 的安全字段：

```text
event_type
schema_version
generator_version
interpreter_version
query_hash
concept_count
cue_count
memory_ids_returned
memory_ids_used
latency_ms
fallback_used
quality_flags
```

新增 retrieval 事件建议：

```text
memory_retrieval_candidates_generated
memory_retrieval_ranked
memory_retrieval_result_used
```

不得默认记录：

- raw query
- memory content
- user-authored USER.md content
- full tool arguments containing secrets

---

## 14. Eval Gates

进入 R1/R2 实现前必须保留 Phase 4 deterministic harness，并新增真实 index path 的测试。

最低验收线沿用 cue spec：

```text
Recall@8 >= 0.90
Recall@3 >= 0.75
MRR >= 0.65
Noise@8 <= 0.35
record_query_cues MRR lift >= 20% over baseline_content
```

新增 retrieval gates：

```text
legacy_active_search_regression = 0
scope_filter_leakage = 0
status_filter_leakage = 0
promoted_memory_default_leakage = 0
p95_search_latency_200_active_records <= 150ms
index_rebuild_200_records <= 2s
```

Density curve 应比较：

```text
baseline_content
content_fts
record_cues
record_query_cues
record_query_cues + file/symbol exact
```

---

## 15. Rollout Plan For Future Implementation

### R1：MemoryIndex + FTS

交付：

- `src/bourbon/memory/index.py`
- rebuild / upsert / delete API
- content + cue FTS fields
- index versioning
- old grep fallback

验收：

- 旧 memory 无 cue metadata 仍可搜索。
- index 删除后可自动重建。
- status/scope/kind 过滤与当前行为一致。

### R2：MemoryRetriever + FusionRanker

交付：

- `src/bourbon/memory/retrieval.py`
- `SearchRequest`
- `RetrievalCandidate`
- weighted RRF v1
- explainable `why_matched`
- debug retrieval opt-in

验收：

- Phase 4 eval 阈值通过。
- 当前 `memory_search` 默认输出兼容。
- `recall_need` 不变成 hard switch。

### R3：Runtime Context Adapter

交付：

- Session/tool trace -> `CueRuntimeContext`
- current/touched/modified files
- recent tool names
- task subject from session state, not raw query text

验收：

- query cue cache 不被 raw query duplicate fingerprint 破坏。
- file-aware boost 在 CLI REPL 场景可用。

### R4：Semantic Channel

交付：

- `render_semantic_memory_text()`
- `render_semantic_query_text()`
- optional local/vector backend adapter

验收：

- semantic channel 只作为 fusion candidate source。
- 关闭 semantic channel 时系统行为可完全回退。
- semantic channel 对 Phase 4 density curve 有正向 lift。

---

## 16. Backend Decision

### 16.1 FTS/BM25：推荐先做

优点：

- 本地、可审计、可重建。
- 无外部 API key。
- latency 可控。
- 与 structured cue fields 天然匹配。

限制：

- 同义词和跨语言语义召回有限。
- query interpretation 的质量仍影响召回。

### 16.2 Embedding：后做

适用条件：

- Phase 4 density curve 显示 FTS/BM25 在 100-200 active records 下不够。
- 用户 memory 出现大量 paraphrase / cross-domain semantic queries。
- 有明确本地或可配置 embedding backend。

限制：

- 可解释性较弱。
- index 更新和模型版本管理更复杂。
- 隐私与成本边界需要单独设计。

### 16.3 HyDE-like text：只做派生表示

保留方向：

- 从 `QueryCue` 派生 `semantic_query_text`。
- 从 `MemoryCueMetadata` 派生 `semantic_memory_text`。
- 用于 semantic channel，不作为 source of truth。

不采用方向：

- query -> hypothetical memory document -> direct authoritative retrieval。
- LLM 输出的 hypothetical document 覆盖结构化 cue。

---

## 17. 风险与缓解

| 风险 | 缓解 |
|---|---|
| Ranking 权重过拟合小 fixture | Phase 4 density curve + ablation 必须保留 |
| QueryCue hallucination 放大错误召回 | `uncertainty` 降权，runtime evidence 优先 |
| FTS index 与 Markdown record 不一致 | index 可重建，record updated_at / schema version 校验 |
| Scope/status 过滤被 soft hint 绕过 | filters 在 candidate generation 前后都验证 |
| Debug 输出泄漏过多 | 默认只输出 compact why_matched，debug opt-in 仍白名单 |
| Embedding 过早引入复杂依赖 | R1/R2 不依赖 embedding |

---

## 18. Open Design Hooks

这些不是阻塞项，但下一份 implementation plan 应明确：

- `MemoryIndex` 是否在 `MemoryStore.write_record()` 后同步更新，还是 search 时 lazy rebuild。
- SQLite FTS tokenizer 是否需要 CJK 增强；第一版可以接受 unicode61 的英文/路径优先能力。
- `MemoryRetriever` 是否允许返回 more-than-limit candidates 给 agent debug tool。
- `memory_search(debug_cue=true)` 是否扩展为 `debug_retrieval=true`，还是新增 internal-only debug API。

---

## 19. Handoff Summary

Cue Engine 已经回答“记忆应该如何被编码成可检索线索”。下一层 retrieval/ranking 应回答“如何用这些线索稳定、可解释、低延迟地找回正确 memory”。

推荐实现顺序是：

```text
local FTS/BM25 index
  -> cue-aware candidate channels
  -> weighted fusion ranker
  -> runtime context adapter
  -> optional semantic/embedding channel
```

这条路径避免了 embedding-first 的复杂度，同时让当前已经完成的 `MemoryCueMetadata`、`QueryCue`、Phase 4 eval harness 立刻产生工程价值。
