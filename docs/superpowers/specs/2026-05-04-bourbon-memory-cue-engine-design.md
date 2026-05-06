# Bourbon Memory Cue Engine 设计

**日期**：2026-05-04  
**状态**：Draft，待用户审阅  
**范围**：Bourbon Memory V3 的 cue 表示层设计，覆盖 record-side cue generation、query-side cue interpretation、runtime evidence policy、eval/telemetry 和分阶段落地。本文不实现完整 retrieval ranking，不替代现有 MemoryManager / MemoryStore / memory_search。

---

## 1. 背景

Bourbon 当前 memory 已经完成两层基础能力：

- Phase 1：文件优先存储、`MEMORY.md` 索引、`memory_write` / `memory_search` / `memory_status`、pre-compact deterministic flush。
- Phase 2：`memory_promote` / `memory_archive`，将稳定 user / feedback memory 投射到全局 `USER.md` managed block，作为更强的 prompt anchor。

这些能力解决了“记忆存在哪里”和“高置信偏好如何注入”的问题，但还没有真正解决“未来如何找回正确记忆”的问题。当前 `memory_search` 仍主要是 grep over memory files，`MemoryRecord` 还没有结构化检索线索，query 侧也没有把用户当前问题解释成与 memory record 同构的检索表示。

前三份 V3 讨论文档已经收敛出一个核心判断：

> Bourbon Memory V3 的关键不是先上 embedding，也不是每轮自动注入 top-k memory，而是把 cue 当成一等资产，在写入时编码未来检索线索，在检索时把当前 query 解释成同一套 cue representation。

这和认知心理学里的几个原则直接对应：

- **Encoding-retrieval specificity**：写入时编码的信息和检索时使用的线索越重合，召回越可靠。
- **Cue distinctiveness**：检索线索越独特，越不容易在记忆密度升高时被相似内容淹没。
- **Self-generated cues**：由编码者生成的线索往往更适合未来召回。
- **Spreading activation**：记忆不是孤立文本，而是概念、文件、决策、风险之间的关联网络。

因此，V3 不应只是在 `MemoryRecord` 上加几个字段，而应引入一个共享的 **Cue Engine**。它统一负责：

```text
MemoryRecordDraft + CueRuntimeContext -> MemoryCueMetadata
UserQuery + CueRuntimeContext -> QueryCue
```

其中 `MemoryCueMetadata` 是持久化在 memory record 上的写入侧 cue，`QueryCue` 是每次检索时的临时 query-side cue。两者共享同一套 concept taxonomy 和 cue schema，但生命周期不同。

---

## 2. 设计目标

1. **Cue-first memory retrieval**：把 cue 作为 memory 的核心索引资产，而不是 embedding 或 grep 的附属输入。
2. **双向表示层**：record-side 和 query-side 都由 LLM / 小模型生成同构 cue representation，减少写入表达和检索表达之间的鸿沟。
3. **Runtime-first evidence**：文件、符号、source_ref、tool trace 等强事实优先来自 runtime，LLM 只补充和归一化。
4. **Controlled taxonomy**：`concepts` 使用受控枚举，保证长期一致性、可评测性和 query-side 稳定性。
5. **不接管 search/ranking**：Cue Engine 止于表示层；ranking、fusion、timeline 和 result injection 属于后续 retrieval spec。
6. **可版本化和可回填**：cue schema、record generator、query interpreter 都带版本，支持 backfill 和质量迭代。
7. **Eval first**：把 eval 和 telemetry 作为设计核心，验证 cue 是否提升未来召回，而不是只验证 JSON 是否合法。
8. **兼容现有 memory stack**：不破坏现有 Markdown memory 文件、`MEMORY.md` 索引、promoted lifecycle、audit 和 prompt anchors。

---

## 3. 非目标

- 不在本文设计完整 search ranking、BM25、FTS、embedding fusion 或 reranker。
- 不设计 per-prompt fixed top-k memory injection。
- 不替代 `MemoryManager`、`MemoryStore`、`memory_search` 或 `memory_promote`。
- 不让 LLM 直接决定 memory status、promote/archive 或 scope 权限。
- 不让 cue metadata 绕过 stale/rejected/promoted 的现有生命周期规则。
- 不把 HyDE-style hypothetical document 作为 canonical representation。
- 不在 MVP 中强制新增独立向量库、SQLite FTS 或后台 daemon。

---

## 4. 方案比较与推荐

### 4.1 方案 A：Write-Side Cue Metadata Only

只在 record 写入时生成 `MemoryCueMetadata`，例如 `concepts`、`retrieval_cues`、`files`、`symbols`。

优点：

- 最容易落地。
- 不影响 search 热路径。
- 立即改善 memory record 的编码质量。

缺点：

- query-side 仍然只是原始字符串。
- “编码 cue”和“检索 cue”没有真正闭环。
- 只能解决 encoding-retrieval specificity 的一半。

结论：适合作为 MVP 的一部分，不适合作为 V3 主线。

### 4.2 方案 B：Canonical Bidirectional Cue Engine

record-side 和 query-side 都通过模型生成同构 cue representation：

```text
memory -> MemoryCueMetadata
query -> QueryCue
```

优点：

- 完整表达“cue 是 memory 核心资产”的设计判断。
- record-side 和 query-side 共享 taxonomy。
- 可以直接做 record cue、query cue、bidirectional cue 的 eval 和 ablation。
- 未来可以平滑接入 grep、BM25、FTS、embedding 或 hybrid retrieval。

缺点：

- query-side 引入小模型调用。
- 需要缓存、超时、fallback 和 telemetry。
- prompt 与 schema 需要持续迭代。

结论：推荐作为本文主线。

### 4.3 方案 C：HyDE-Like Semantic Cue Engine

query-side 直接生成 hypothetical memory text 或 semantic query document，优先服务 embedding / hybrid retrieval。

优点：

- 对语义检索自然。
- 对表面形式差异大的 query 可能提升明显。

缺点：

- 太早把 V3 绑定到 embedding。
- hypothetical text 不适合作为 Bourbon 的治理源，难以表达 scope、status、source_ref、runtime evidence。
- 可解释性和 eval 难度更高。

结论：不作为主线。可以在未来从 `QueryCue` 派生 `semantic_query_text`，用于 embedding 实验。

### 4.4 推荐结论

本文采用方案 B，MVP 借用方案 A 的落地顺序，保留方案 C 的派生接口：

> Bourbon Memory Cue Engine V3 defines a canonical bidirectional cue representation layer. The source of truth is structured cue metadata. HyDE-like semantic text is an optional derived representation for future semantic retrieval experiments, not the canonical interface.

---

## 5. 架构边界

`CueEngine` 是 memory 的表示层，不是新的 memory store，不是 search/ranking engine，也不是 auto-extract subsystem。

它只做两件事：

```text
MemoryRecordDraft + CueRuntimeContext -> MemoryCueMetadata
UserQuery + CueRuntimeContext -> QueryCue
```

它不负责：

- 决定一条 memory 是否该写入。
- 决定 memory 的 status / promote / archive。
- 执行 search。
- 排序、fusion、rerank。
- 把结果注入 prompt。
- 自动提取 session transcript。

现有边界保持：

- `MemoryManager` 仍负责 write/search/promote/archive 编排。
- `MemoryStore` 仍负责文件落盘和索引。
- `memory_search` 仍是用户可见 retrieval 工具。
- 未来 search pipeline 可以使用 `QueryCue`，但 ranking 归 search 模块。

这样设计的原因是：cue prompt、taxonomy、eval 会频繁变化。如果 Cue Engine 同时拥有 ranking，任何 cue prompt 调整都会改变检索行为，回归成本过高。

---

## 6. 模块设计

新增 package：

```text
src/bourbon/memory/cues/
  __init__.py
  models.py          # MemoryConcept, CueKind, RetrievalCue, MemoryCueMetadata, QueryCue
  engine.py          # CueEngine facade
  runtime.py         # runtime evidence extraction
  prompts.py         # record/query cue prompts
  normalize.py       # deterministic normalization
  quality.py         # validation and coverage helpers
```

核心接口：

```python
class CueEngine:
    def generate_for_record(
        self,
        draft: MemoryRecordDraft,
        *,
        runtime_context: CueRuntimeContext,
    ) -> MemoryCueMetadata:
        ...

    def interpret_query(
        self,
        query: str,
        *,
        runtime_context: CueRuntimeContext,
    ) -> QueryCue:
        ...

    def normalize_metadata(
        self,
        metadata: MemoryCueMetadata,
    ) -> MemoryCueMetadata:
        ...

    def validate_metadata(
        self,
        metadata: MemoryCueMetadata,
    ) -> CueValidationResult:
        ...
```

职责：

- `generate_for_record()`：模型参与，生成 record-side cue，合并 runtime evidence。
- `interpret_query()`：模型参与，将当前 query 解释成 `QueryCue`。
- `normalize_metadata()`：不调模型，做去重、路径规范化、长度限制、枚举校验。
- `validate_metadata()`：不调模型，返回 schema 错误和质量问题。

---

## 7. Cue 数据模型

### 7.1 MemoryConcept

`concepts` 使用受控 taxonomy。v1 刻意保持小而稳定：

```python
class MemoryConcept(StrEnum):
    USER_PREFERENCE = "user_preference"
    BEHAVIOR_RULE = "behavior_rule"
    PROJECT_CONTEXT = "project_context"
    ARCHITECTURE_DECISION = "architecture_decision"
    IMPLEMENTATION_PATTERN = "implementation_pattern"
    WORKFLOW = "workflow"
    RISK_OR_LESSON = "risk_or_lesson"
    TRADE_OFF = "trade_off"
    HOW_IT_WORKS = "how_it_works"
    EXTERNAL_REFERENCE = "external_reference"
```

含义：

- `USER_PREFERENCE`：用户个人偏好，如语言、格式、工具偏好。
- `BEHAVIOR_RULE`：对 agent 的稳定行为约束。
- `PROJECT_CONTEXT`：项目背景事实。
- `ARCHITECTURE_DECISION`：已确认的设计决策。
- `IMPLEMENTATION_PATTERN`：可复用工程模式。
- `WORKFLOW`：操作流程、测试流程、发布流程。
- `RISK_OR_LESSON`：风险、踩坑、失败案例、调试经验。
- `TRADE_OFF`：明确的设计取舍。
- `HOW_IT_WORKS`：机制解释。
- `EXTERNAL_REFERENCE`：外部文档、论文、dashboard、issue、URL。

v1 将 gotcha、failure case、debugging note 合并为 `RISK_OR_LESSON`。如果 eval 显示它们有明显不同的召回/使用行为，后续 schema version 再拆分。

### 7.1.1 Domain Extension Policy

Bourbon 不是纯 coding agent。投资分析、文档解析、数据分析、笔记管理等 skill domain 可能需要自己的 memory concept。v1 的 `MemoryConcept` 是全局核心 taxonomy，不应强迫所有 domain-specific memory 都塞进 coding-oriented concepts。

扩展策略：

```python
@dataclass
class DomainConcept:
    namespace: str
    value: str
    source: Literal["skill", "project", "user"]
    schema_version: str
```

`MemoryCueMetadata` 的 v1 主字段仍使用受控 `MemoryConcept`，并预留：

```python
domain_concepts: list[DomainConcept] = field(default_factory=list)
```

规则：

```text
- global concepts 必须来自 MemoryConcept，用于跨 domain 的稳定检索和 eval。
- domain_concepts 只作为补充，不替代 global concepts。
- 每条 memory 仍必须有 1-3 个 global concepts，domain_concepts 可为 0-5 个。
- skill-level 扩展必须带 namespace，例如 investment:risk_model、data:csv_schema。
- query-side 也可以输出 domain_concepts，但 search/ranking 不得依赖它绕过 scope/status policy。
```

MVP 可以先实现字段和验证，不必实现 skill-level taxonomy discovery。这样为非 coding domain 预留路径，同时不牺牲 v1 taxonomy 稳定性。

### 7.2 RetrievalCue

`retrieval_cues` 不使用纯字符串，而使用轻量对象：

```python
class CueKind(StrEnum):
    USER_PHRASE = "user_phrase"
    TASK_PHRASE = "task_phrase"
    PROBLEM_PHRASE = "problem_phrase"
    FILE_OR_SYMBOL = "file_or_symbol"
    DECISION_QUESTION = "decision_question"
    SYNONYM = "synonym"


class CueSource(StrEnum):
    LLM = "llm"
    RUNTIME = "runtime"
    USER = "user"
    BACKFILL = "backfill"


@dataclass
class RetrievalCue:
    text: str
    kind: CueKind
    source: CueSource
    confidence: float
```

`CueKind` 含义：

- `USER_PHRASE`：用户未来可能直接说的话。
- `TASK_PHRASE`：任务型查询表达。
- `PROBLEM_PHRASE`：问题、错误、异常型查询表达。
- `FILE_OR_SYMBOL`：文件、函数、类名、工具名。
- `DECISION_QUESTION`：设计决策型查询。
- `SYNONYM`：同义改写或表面形式不同但应命中的表达。

设计理由：

- `kind` 支持 eval ablation，能区分哪类 cue 贡献最大。
- `source` 避免 LLM 输出和 runtime evidence 混在一起。
- `confidence` 支持后续阈值过滤和 trust scoring。
- embedding 可选择只 embed 某些 cue kind，而不是整个 memory body。

`files` / `symbols` 与 `FILE_OR_SYMBOL` cue 的边界：

```text
files/symbols:
  authoritative references
  用于精确路径匹配、当前文件关联、用户可见 related files、runtime evidence 校验

FILE_OR_SYMBOL retrieval cues:
  retrieval expressions
  用于 keyword/cue 匹配，可包含 basename、部分路径、符号别名、低置信相关文件
```

Search/ranking consumer 不应把二者混为同一个信号。`files/symbols` 是事实引用，`FILE_OR_SYMBOL` cue 是检索入口。

### 7.3 MemoryCueMetadata

record-side 的 canonical 持久模型：

```python
class CueGenerationStatus(StrEnum):
    GENERATED = "generated"
    PARTIAL = "partial"
    FAILED = "failed"
    NOT_RUN = "not_run"


class CueQualityFlag(StrEnum):
    LLM_GENERATION_FAILED = "llm_generation_failed"
    LLM_INTERPRETATION_FAILED = "llm_interpretation_failed"
    PARTIAL_OUTPUT = "partial_output"
    LOW_CUE_COVERAGE = "low_cue_coverage"
    NO_DECISION_QUESTION_CUE = "no_decision_question_cue"
    MISSING_RUNTIME_FILE_CUE = "missing_runtime_file_cue"
    OVERBROAD_CUE = "overbroad_cue"
    CONCEPT_MISMATCH = "concept_mismatch"
    INVALID_FILE_HINT = "invalid_file_hint"
    MALFORMED_CUE_METADATA = "malformed_cue_metadata"
    FALLBACK_USED = "fallback_used"


@dataclass
class MemoryCueMetadata:
    schema_version: str
    generator_version: str
    concepts: list[MemoryConcept]
    retrieval_cues: list[RetrievalCue]
    files: list[str]
    symbols: list[str]
    generation_status: CueGenerationStatus
    domain_concepts: list[DomainConcept] = field(default_factory=list)
    generated_at: datetime | None = None
    quality_flags: list[CueQualityFlag] = field(default_factory=list)
```

验证规则：

```text
concepts: 1-3 values, all from MemoryConcept
domain_concepts: 0-5 values, namespace-qualified when source=skill/project
retrieval_cues: 3-8 values by default
retrieval_cue.text: non-empty, <= 80 characters
files/symbols: normalized, deduplicated
runtime-derived FILE_OR_SYMBOL cues: preserved unless invalid
llm-derived file hints: lower confidence than runtime-derived hints
generation_status: required
schema_version: required, starts with "cue.v"
generator_version: required
quality_flags: values from CueQualityFlag only
```

### 7.4 QueryCue

query-side 的 canonical 临时模型：

```python
class RecallNeed(StrEnum):
    NONE = "none"
    WEAK = "weak"
    STRONG = "strong"


class TimeHint(StrEnum):
    NONE = "none"
    RECENT = "recent"
    LAST_SESSION = "last_session"
    OLDER = "older"
    EXPLICIT_RANGE = "explicit_range"


@dataclass
class QueryCue:
    schema_version: str
    interpreter_version: str
    recall_need: RecallNeed
    concepts: list[MemoryConcept]
    cue_phrases: list[RetrievalCue]
    file_hints: list[str]
    symbol_hints: list[str]
    kind_hints: list[MemoryKind]
    scope_hint: MemoryScope | None
    uncertainty: float
    domain_concepts: list[DomainConcept] = field(default_factory=list)
    time_hint: TimeHint = TimeHint.NONE
    time_range: tuple[datetime, datetime] | None = None
    generated_at: datetime | None = None
    fallback_used: bool = False
    quality_flags: list[CueQualityFlag] = field(default_factory=list)
```

验证规则：

```text
recall_need: required
concepts: 0-3 values
domain_concepts: 0-5 values, namespace-qualified when source=skill/project
cue_phrases: 0-8 values
file_hints/symbol_hints: normalized, deduplicated
uncertainty: 0.0-1.0
fallback_used: true when model interpretation failed or deterministic fallback was used
time_hint: required, one of TimeHint
time_range: required only when time_hint=EXPLICIT_RANGE
quality_flags: values from CueQualityFlag only
```

`MemoryCueMetadata` 和 `QueryCue` 不使用同一个类。前者是持久资产，后者是一次检索意图。

`uncertainty` 是 query representation 的稳定性信号，不是检索排序的必用字段。V3 MVP 中它用于 telemetry、debug 和 retrieval policy hint；后续 ranking spec 可以决定是否将它用于权重调整。高 `uncertainty` 表示 search 层应扩大候选，而不是过度依赖解释后的 cue。

`time_hint` 在 v1 中只使用粗粒度枚举。`EXPLICIT_RANGE` 仅在 query 明确包含可解析时间范围时使用；否则不得让 LLM 自由写自然语言时间字符串。具体时间过滤是否执行属于 retrieval spec。

### 7.5 Frontmatter Shape

Memory files 仍是 Markdown + YAML frontmatter。`cue_metadata` 是嵌套对象：

```yaml
cue_metadata:
  schema_version: "cue.v1"
  generator_version: "record-cue-v1"
  generation_status: "generated"
  generated_at: "2026-05-04T12:00:00Z"
  concepts:
    - architecture_decision
    - trade_off
  domain_concepts: []
  retrieval_cues:
    - text: "why not per-prompt memory injection"
      kind: decision_question
      source: llm
      confidence: 0.84
    - text: "src/bourbon/memory/prompt.py"
      kind: file_or_symbol
      source: runtime
      confidence: 1.0
  files:
    - src/bourbon/memory/prompt.py
  symbols: []
  quality_flags: []
```

缺少 `cue_metadata` 的旧 memory 文件仍然合法。

---

## 8. HyDE 边界

本设计和 HyDE 相似的地方在于：二者都使用模型生成“更适合检索的中间表征”。但 Bourbon Cue Engine 不把 hypothetical document 当作 source of truth。

HyDE 典型流程：

```text
query -> hypothetical document -> embedding -> dense retrieval
```

Bourbon Cue Engine 流程：

```text
query + runtime context -> QueryCue -> search pipeline
```

如果未来 semantic retrieval 需要一段可 embedding 的文本，可以从 `QueryCue` 派生：

```python
def render_semantic_query_text(query_cue: QueryCue) -> str:
    parts = []
    if query_cue.concepts:
        parts.append("Concepts: " + ", ".join(str(c) for c in query_cue.concepts))
    if query_cue.cue_phrases:
        parts.append("Likely retrieval phrases: " + "; ".join(c.text for c in query_cue.cue_phrases))
    if query_cue.file_hints:
        parts.append("Related files: " + ", ".join(query_cue.file_hints))
    if query_cue.symbol_hints:
        parts.append("Related symbols: " + ", ".join(query_cue.symbol_hints))
    return "\n".join(parts)
```

该派生文本可用于 embedding 实验，但不是 canonical interface，不写入 memory truth，也不能绕过 cue schema。

---

## 9. Runtime Evidence Policy

Cue Engine 是 model-backed，但不是 model-trusting。Runtime evidence 的权威性高于 LLM 输出。

### 9.1 Evidence Priority

最终 cue metadata 按以下优先级合并：

```text
1. source_ref
2. explicit runtime context
3. deterministic extraction
4. LLM output
```

例如：

```text
source_ref.file_path > touched_files > deterministic path extraction > LLM file suggestion
modified_files > LLM "probably related file"
runtime symbols > LLM symbol guess
```

### 9.2 CueRuntimeContext

```python
@dataclass
class CueRuntimeContext:
    workdir: Path
    current_files: list[str]
    touched_files: list[str]
    modified_files: list[str]
    symbols: list[str]
    source_ref: SourceRef | None
    recent_tool_names: list[str]
    task_subject: str | None
    session_id: str | None
```

权威字段：

```text
SourceRef:
  file_path
  tool_call_id
  session_id
  message_uuid / transcript range

CueRuntimeContext:
  current_files
  touched_files
  modified_files
  symbols
  recent_tool_names
  task_subject
```

LLM 可以补充这些字段，但不能删除或覆盖它们。

### 9.2.1 Session Context Adapter

CLI REPL 没有 IDE 里的“当前打开文件”概念。因此 `CueRuntimeContext` 不能依赖 UI state，必须由 Agent 从 session chain、tool use 和 tool result 中推断。

新增适配层：

```text
src/bourbon/memory/cues/runtime.py
  build_runtime_context(agent, *, source_ref=None, task_subject=None) -> CueRuntimeContext
```

构建责任：

```text
Agent:
  拥有 session chain、tool trace、workdir、task reminder，是默认构建者。

MemoryManager:
  接收 CueRuntimeContext，不主动读取 session chain，避免 MemoryManager -> Agent/Session 的反向耦合。

Tool handlers:
  通过 ToolContext.agent 或 ToolContext 中未来新增的 cue_runtime_context_factory 获取 runtime context。
```

推断规则：

```python
READ_TOOLS = {"read", "Read", "rg_search", "grep", "glob", "ast_grep_search", "csv_analyze", "json_query", "pdf_to_text", "docx_to_markdown"}
WRITE_TOOLS = {"write", "write_file", "edit", "edit_file"}
SEARCH_TOOLS = {"rg_search", "glob", "ast_grep_search"}

def build_runtime_context_from_recent_tools(chain, workdir, *, source_ref=None, task_subject=None):
    tool_uses = recent_tool_uses(chain, limit=20)
    current_files = paths_from_last_successful_reads(tool_uses, limit=3)
    touched_files = paths_from_tools(tool_uses, READ_TOOLS | WRITE_TOOLS | SEARCH_TOOLS, limit=10)
    modified_files = paths_from_tools(tool_uses, WRITE_TOOLS, limit=10)
    recent_tool_names = [tool.name for tool in tool_uses[-10:]]
    return CueRuntimeContext(...)
```

`current_files` 是启发式字段，不是事实字段。它表示“最近工作上下文中最可能相关的文件”，优先来自最近成功 read/edit 的路径。`modified_files` 和 `source_ref.file_path` 权威性更高。

Fingerprint 规则：

```python
def fingerprint(ctx: CueRuntimeContext) -> str:
    return stable_hash({
        "current_files": sorted(ctx.current_files),
        "touched_files": sorted(ctx.touched_files),
        "modified_files": sorted(ctx.modified_files),
        "symbols": sorted(ctx.symbols),
        "recent_tool_names": ctx.recent_tool_names[-5:],
        "task_subject": ctx.task_subject or "",
        "source_ref_file": ctx.source_ref.file_path if ctx.source_ref else "",
    })
```

不进入 fingerprint：

```text
- timestamps
- session_id，除非 future eval 证明跨 session cache 污染
- raw tool outputs
- full query text 之外的敏感内容；full query text 只进入 cache key 的 query hash，不进入 runtime fingerprint
```

如果用户在同一 session 中从 `auth.py` 切到 `search.py`，`current_files/touched_files/modified_files` 变化必须导致 fingerprint 变化，从而避免 query cue cache 返回过时解释。

### 9.3 Path Handling

文件 hint 规则：

```text
- prefer repo-relative paths
- reject paths outside workdir unless source_ref explicitly points outside
- remove duplicate path spellings
- preserve exact casing if filesystem path exists
- store non-existing LLM-suggested paths only as low-confidence cue text, not authoritative files
```

如果 LLM 建议 `src/memory/store.py`，但该路径不存在，则不能加入 `files`。它最多作为低置信 `RetrievalCue(source=llm)` 保留。

### 9.4 Symbol Handling

symbols 在 V1 中弱于文件路径。来源：

```text
runtime:
  symbols explicitly supplied by tools or context

deterministic:
  simple extraction of class/function/tool names from memory content

llm:
  low-confidence supplemental symbol hints
```

V1 不要求 AST 索引，符号提取应保守。

### 9.5 Scope And Kind Hints

LLM 可以为 `QueryCue` 生成 `kind_hints` 和 `scope_hint`，但它们只是 retrieval hint，不是权限。

约束：

```text
- stale/rejected records remain excluded unless explicitly requested
- subagent scope restrictions still apply
- promoted records require status-aware search
- project memory must not leak across project keys
```

### 9.6 Model Output Safety

模型输出必须先 validation 再持久化或使用：

```text
- unknown concepts are rejected
- unknown cue kinds are rejected
- too-long cue text is truncated or rejected
- empty cue text is rejected
- malformed files are rejected from authoritative files
- confidence is clamped to [0.0, 1.0]
```

Validation failure 不应导致 memory write 失败，除非完全没有可用 fallback。

---

## 10. Record-Side Cue Generation

Record-side cue generation 在 Bourbon 即将持久化 durable memory record 时触发。

主调用路径：

```text
memory_write -> MemoryManager.write()
  -> CueEngine.generate_for_record()
  -> MemoryStore.write_record()
```

未来可复用调用点：

```text
backfill existing memory files
auto-extract staged candidates
manual memory migration
```

### 10.1 Generation Flow

```text
MemoryRecordDraft + CueRuntimeContext
  -> extract runtime evidence
  -> build model prompt
  -> LLM returns candidate concepts and retrieval cues
  -> normalize candidate metadata
  -> merge runtime-derived cues
  -> validate metadata
  -> return MemoryCueMetadata
```

Runtime-derived fields：

```text
files:
  source_ref.file_path
  current_files
  touched_files
  modified_files

symbols:
  symbols from runtime context
  explicit class/function/tool names if extracted deterministically

retrieval_cues:
  FILE_OR_SYMBOL cues for files/symbols
  source=runtime
  confidence=1.0
```

LLM-derived fields：

```text
concepts:
  1-3 MemoryConcept values

retrieval_cues:
  USER_PHRASE
  TASK_PHRASE
  PROBLEM_PHRASE
  DECISION_QUESTION
  SYNONYM

optional file/symbol suggestions:
  accepted only as low-confidence supplements
```

### 10.2 Prompt Requirements

record-side prompt 的目标不是总结 memory，而是生成未来检索表达。

差的 cue：

```text
memory cue design
```

更好的 cue：

```text
why should memory cues be generated at write time
how does Bourbon avoid per-prompt memory injection
where is promoted USER.md rendering handled
```

prompt 应强制三个视角：

```text
1. What would the user say when trying to recall this?
2. What would the agent search for while working on a related task?
3. What files, symbols, or decisions make this memory distinctive?
```

### 10.3 Failure Behavior

Cue generation failure 不阻断 memory 写入。

模型调用失败时：

```python
MemoryCueMetadata(
    schema_version="cue.v1",
    generator_version="record-cue-v1",
    concepts=[],
    retrieval_cues=runtime_derived_cues,
    files=runtime_files,
    symbols=runtime_symbols,
    generation_status=CueGenerationStatus.FAILED,
    quality_flags=[CueQualityFlag.LLM_GENERATION_FAILED],
)
```

模型输出部分有效时：

```text
generation_status = "partial"
quality_flags include concrete validation issues
valid fields are preserved
runtime evidence is still merged
```

### 10.4 Versioning

每个 `MemoryCueMetadata` 存：

```text
schema_version = "cue.v1"
generator_version = "record-cue-v1"
generated_at = timestamp
```

Backfill 和 future prompt revision 可以通过 `generator_version` 判断是否需要重算。

### 10.5 Latency Policy

`CueEngine.generate_for_record()` 位于 `MemoryManager.write()` 的写入路径上。同步模型调用会直接增加 `memory_write` 延迟，因此 MVP 必须明确延迟策略。

默认策略：

```text
interactive write:
  synchronous generation with timeout
  timeout_ms = generation_timeout_ms
  failure writes fallback metadata

compact flush / auto-extract batch:
  prefer deferred or batch generation
  never block compaction hot path on multiple sequential cue model calls

backfill:
  batch generation allowed
  not latency sensitive
```

MVP 中 `memory_write` 可以同步调用 cue generation，因为主动 durable memory 写入频率通常较低。但 pre-compact flush 可能一次写多条 candidate，不应串行等待多次 1500ms 模型调用。

### 10.6 Deferred And Batch Interfaces

为 backfill、auto-extract 和 compaction 场景预留 batch API：

```python
class CueEngine:
    def generate_for_records(
        self,
        drafts: list[MemoryRecordDraft],
        *,
        runtime_contexts: list[CueRuntimeContext],
    ) -> list[MemoryCueMetadata]:
        ...
```

Phase 1 可只实现单条 `generate_for_record()`。Phase 2 backfill 前应实现 batch 或 worker-style deferred generation。

Deferred 策略：

```text
1. 先写 memory content + minimal runtime cue metadata。
2. 将 generation_status 标记为 NOT_RUN 或 PARTIAL。
3. 后台/脚本补全 LLM-derived cues。
4. 原子更新 frontmatter。
```

这避免 compaction、auto-extract 或批量导入时产生累计延迟。

---

## 11. Query-Side Cue Interpretation

Query-side interpretation 将当前用户请求和 runtime context 转换成结构化 `QueryCue`。

主调用路径：

```text
memory_search(query)
  -> CueEngine.interpret_query(query, runtime_context)
  -> QueryCue
  -> MemoryManager.search(query, query_cue=...)
```

Cue Engine 仍然止于 representation。它不 rank、不 rerank、不注入结果、不决定最终相关性。

### 11.1 为什么 query-side 小模型是核心

如果只有 record-side 用 LLM，Bourbon 只是拥有更好的 memory metadata，但仍用原始 query 搜索。这只解决一半 encoding-retrieval specificity。

Query-side interpretation 将用户当前表达映射到和 record-side 同一套 taxonomy：

```text
record-side: memory -> concepts + retrieval cues
query-side: query -> concepts + cue phrases
```

这才构成真正的双向 cue representation。

### 11.2 Recall Need

Interpreter 必须判断当前 query 是否真的需要长期记忆：

```text
none:
  no memory search needed

weak:
  memory may help but should not dominate

strong:
  memory is central to the request
```

`recall_need` 是 search/agent policy 的信号，不是强制行为。

边界规则：

```text
- CueEngine 只输出 recall_need，不决定是否执行 memory_search。
- 如果用户显式调用 memory_search 或 agent 已经决定搜索，即使 recall_need=none，search 仍可执行。
- retrieval policy 可以用 recall_need 调整搜索预算、结果权重、是否主动建议进一步钻取。
- recall_need=none 的推荐消费方式是降低 memory 结果影响，而不是跳过用户明确请求。
```

这保持 Cue Engine 的表示层边界：它提供 policy signal，不拥有 retrieval decision。

### 11.3 Query Prompt Requirements

query-side prompt 不应让模型回答用户问题，只提取 retrieval intent。

它应输出：

```text
- whether this query needs long-term memory
- relevant MemoryConcept values
- possible alternate retrieval phrases
- file/symbol hints from runtime context
- likely memory kind/scope
- uncertainty
```

它应避免：

```text
- generating factual answers
- inventing project facts
- treating every query as memory-worthy
- producing hypothetical documents as canonical output
```

### 11.4 Query Interpretation Trigger Policy

Query-side 小模型解释是长期核心能力，但不应对所有 query 无条件触发。MVP 增加 deterministic fast path，降低延迟和无收益模型调用。

```python
def should_interpret_query(query: str, runtime_context: CueRuntimeContext) -> bool:
    normalized = query.strip()
    if not normalized:
        return False
    if len(normalized.split()) < 3 and not has_memory_recall_marker(normalized):
        return False
    if looks_like_file_path(normalized):
        return False
    if looks_like_code_snippet(normalized):
        return False
    if only_contains_command_or_test_invocation(normalized):
        return False
    return True
```

`has_memory_recall_marker()` 应覆盖中英文回忆表达，例如：

```text
last time, previously, earlier, remember, memory, 上次, 之前, 记得, 当时, 以前讨论
```

Fast path 输出 fallback-style `QueryCue`：

```text
recall_need = weak 或 none
cue_phrases = original query
file_hints/symbol_hints = runtime-derived only
fallback_used = true
quality_flags include FALLBACK_USED
```

这不是削弱 query-side 小模型的架构地位，而是工程上的热路径保护。Field metrics 必须分别记录 model interpretation、fast path fallback 和 failure fallback。

### 11.5 Caching

Query interpretation 可以缓存。

推荐 cache key：

```text
hash(
  normalized_query,
  runtime_context.fingerprint(),
  schema_version,
  interpreter_version,
)
```

`runtime_context.fingerprint()` 只包含稳定且检索相关的字段，例如 current files、touched files、task subject、recent tool names。不包含 volatile timestamps。

Cache invalidation 要求：

```text
- current_files 变化必须导致 fingerprint 变化。
- touched_files / modified_files 变化必须导致 fingerprint 变化。
- task_subject 变化必须导致 fingerprint 变化。
- interpreter_version 变化必须导致 cache miss。
- schema_version 变化必须导致 cache miss。
```

不建议把 `session_id` 默认放入 fingerprint。相同 query + 相同 runtime context 在同一项目内可复用；如果 field metrics 显示跨 session 污染，再加入 session component。

### 11.6 Failure Behavior

解释失败时：

```python
QueryCue(
    schema_version="cue.v1",
    interpreter_version="query-cue-v1",
    recall_need=RecallNeed.WEAK,
    concepts=[],
    cue_phrases=[
        RetrievalCue(
            text=original_query,
            kind=CueKind.USER_PHRASE,
            source=CueSource.USER,
            confidence=1.0,
        )
    ],
    file_hints=runtime_files,
    symbol_hints=runtime_symbols,
    kind_hints=[],
    scope_hint=None,
    uncertainty=1.0,
    time_hint=TimeHint.NONE,
    fallback_used=True,
    quality_flags=[CueQualityFlag.LLM_INTERPRETATION_FAILED, CueQualityFlag.FALLBACK_USED],
)
```

`memory_search` 继续使用原始 query 和 runtime-derived hints。

---

## 12. 与现有系统的集成

### 12.1 Model Changes

在现有 memory models 中增加可选字段：

```python
@dataclass
class MemoryRecordDraft:
    ...
    cue_metadata: MemoryCueMetadata | None = None


@dataclass
class MemoryRecord:
    ...
    cue_metadata: MemoryCueMetadata | None = None


@dataclass
class MemorySearchResult:
    ...
    cue_match_summary: str | None = None
```

`cue_metadata` 可选，以兼容旧 memory 文件。

### 12.2 Store Changes

`MemoryStore` 需要在 YAML frontmatter 中 serialize / deserialize `cue_metadata`。

要求：

```text
- old memory files with no cue_metadata parse normally
- malformed cue_metadata is ignored or marked invalid without losing the record
- _rebuild_index remains active-record-only
- MEMORY.md index line format does not need to change in MVP
```

MVP 不新增独立 cue index 文件，仍保持 file-first。

错误处理层级：

```python
def _parse_file(path: Path) -> tuple[dict[str, Any], str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    try:
        fm = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        # 整个 frontmatter 损坏：保留正文，不尝试解析 metadata。
        return {}, parts[2] if len(parts) >= 3 else text
    return fm, parts[2]

def parse_optional_cue_metadata(fm: dict[str, Any]) -> MemoryCueMetadata | None:
    raw = fm.get("cue_metadata")
    if raw is None:
        return None
    try:
        return MemoryCueMetadata.from_frontmatter(raw)
    except (KeyError, TypeError, ValueError, ValidationError):
        return None
```

策略：

```text
- YAML frontmatter 整体损坏时，按现有容错路径处理，不让 cue_metadata 解析扩大 blast radius。
- cue_metadata 子对象损坏时，只丢弃 cue_metadata，不丢弃 MemoryRecord。
- 如果 record 其余必需字段完整，record 仍可读写/search。
- 如果需要保留损坏信号，可在 audit/debug event 中记录 MALFORMED_CUE_METADATA。
```

不要因为 cue metadata 损坏导致 `MEMORY.md` index rebuild 或 `memory_search` 失败。

### 12.3 Manager Changes

`MemoryManager.write()` 是 record-side 主集成点：

```text
MemoryRecordDraft
  -> CueEngine.generate_for_record()
  -> MemoryRecord(cue_metadata=...)
  -> MemoryStore.write_record()
```

`MemoryManager.search()` 可接受可选 `QueryCue`：

```python
def search(
    self,
    query: str,
    *,
    scope: str | None = None,
    kind: list[str] | None = None,
    status: list[str] | None = None,
    limit: int | None = None,
    query_cue: QueryCue | None = None,
) -> list[MemorySearchResult]:
    ...
```

本文不设计 ranking 细节。Search 可以先用 `QueryCue` 做最小增强，例如扩大候选查询词、记录 `cue_match_summary`，完整 ranking 留给 retrieval spec。

### 12.4 Tool Changes

`memory_write` 不要求 LLM 在 tool input 中手写 cue metadata。用户可见 schema 应保持稳定，cue 由内部生成。

`memory_search` 可以内部调用 query interpretation：

```text
memory_search(query)
  -> CueEngine.interpret_query(query, runtime_context)
  -> MemoryManager.search(query, query_cue=query_cue)
```

工具输出保持兼容。可添加调试字段：

```json
{
  "results": [
    {
      "id": "mem_xxx",
      "name": "...",
      "snippet": "...",
      "why_matched": "...",
      "cue_match_summary": "concept:trade_off + cue:decision_question"
    }
  ],
  "query_cue": {
    "recall_need": "strong",
    "concepts": ["trade_off"]
  }
}
```

MVP 中 `query_cue` 默认可不输出，除非 debug mode 开启。

### 12.5 Prompt Changes

Tool descriptions 应教模型行为，不暴露完整内部结构。

建议：

- `memory_write` 描述中说明 Bourbon 会根据 memory 内容和 runtime context 自动生成 retrieval cues。
- `memory_search` 描述中说明 Bourbon 可能先将 query 解释成 memory cues 再搜索。
- 不把完整 taxonomy 注入 system prompt；taxonomy 应存在于 cue prompt、schema、docs 和 eval 中。

### 12.6 Config

新增配置：

```toml
[memory.cues]
enabled = true
record_generation = true
query_interpretation = true
record_generator_model = "small"
query_interpreter_model = "small"
generation_timeout_ms = 1500
query_interpret_timeout_ms = 800
query_interpret_cache_size = 512
persist_failed_metadata = true
```

模型绑定应尽量复用现有 LLM provider config，不引入第二套 provider 系统。

### 12.7 Backfill

后续增加脚本：

```text
scripts/backfill_memory_cues.py
```

行为：

```text
- scan active/promoted/stale records
- skip records with current schema_version + generator_version unless --force
- generate cue_metadata using source_ref and file content where available
- write updated frontmatter atomically
- emit a summary report
```

Backfill 必须存在，因为 Bourbon 已经有无 cue metadata 的 memory 文件。

### 12.8 Subagents

Subagent 不获得特殊 cue 权限。

如果 subagent 写 memory，仍使用同一个 Cue Engine，但 actor policy 仍由 memory policy 决定。Subagent 不能通过 cue metadata promote memory 或扩大 scope。

---

## 13. Eval And Telemetry

Cue Engine 的成功标准不是“模型生成了合法 JSON”，而是生成的 cue 是否可度量地提升未来召回。

### 13.1 Layer 1：Schema And Generation Quality

目的：验证 cue metadata 合法、稳定、保留 runtime evidence。

指标：

```text
valid_json_rate
schema_valid_rate
concept_count_distribution
cue_count_distribution
runtime_evidence_preservation_rate
invalid_file_hint_rate
duplicate_cue_rate
generation_failure_rate
partial_generation_rate
```

MVP 验收线：

```text
schema_valid_rate >= 0.98
runtime_evidence_preservation_rate = 1.00
invalid_file_hint_rate <= 0.05
generation_failure_rate <= 0.05
```

核心断言：

```text
- concepts 全部属于 MemoryConcept
- concepts 数量 1-3
- retrieval_cues 数量 3-8
- FILE_OR_SYMBOL cues 中 runtime-derived cues 被保留
- LLM-derived file hints 不覆盖 runtime-derived evidence
- cue text 长度 <= 80 chars
- generation_status 正确记录
```

### 13.2 Layer 2：Retrieval Effectiveness

目的：验证 record-side 和 query-side cue 是否提升召回。

测试变体：

```text
baseline_content:
  name + description + content

record_cues:
  baseline + MemoryCueMetadata.retrieval_cues

query_cues:
  baseline + QueryCue.cue_phrases

record_query_cues:
  record-side cues + query-side cues

ablation_concepts:
  remove concepts

ablation_files:
  remove files/symbols

ablation_llm_cues:
  remove source=llm cues

ablation_runtime_cues:
  remove source=runtime cues
```

指标：

```text
Recall@3
Recall@8
MRR
Noise@8
Cue Lift
Query Expansion Lift
Runtime Evidence Lift
```

MVP 验收线：

```text
Recall@8 >= 0.90
Recall@3 >= 0.75
MRR >= 0.65
Noise@8 <= 0.35
record_query_cues MRR lift >= 20% over baseline_content
```

这里不要求证明最终 ranking 完成，只验证 cue representation 对候选召回和粗排序有帮助。

### 13.3 Layer 3：Field Metrics

目的：衡量真实使用，而不是只依赖 curated golden set。

事件：

```python
@dataclass
class CueEvalEvent:
    event_type: Literal[
        "record_cue_generated",
        "query_cue_interpreted",
        "memory_search_with_cues",
        "memory_result_used",
    ]
    schema_version: str
    generator_version: str | None
    interpreter_version: str | None
    query_hash: str | None
    concept_count: int
    cue_count: int
    memory_ids_returned: list[str]
    memory_ids_used: list[str]
    latency_ms: int
    fallback_used: bool
    quality_flags: list[CueQualityFlag]
```

Telemetry 落盘时可以序列化为 flag string；内存模型和 eval harness 应保留 `CueQualityFlag` 枚举，避免新 flag 随意漂移。

Field 指标：

```text
cue_utilization_rate
result_use_rate
searches_per_recall_need
query_interpreter_latency_p50
query_interpreter_latency_p95
fallback_rate
record_cue_regeneration_rate
concept_drift
```

默认 telemetry 不记录完整 query 文本或 memory 内容。默认只记录 hash、计数、版本、latency、fallback 和 quality flags。debug mode 可以选择更丰富的本地日志。

### 13.4 Cue Coverage Test

这是 write-time quality gate，但 MVP 可先在 eval harness 中运行。

流程：

```text
1. Write or load a memory record with MemoryCueMetadata.
2. Generate 3-5 hypothetical future queries for that record.
3. Interpret each hypothetical query into QueryCue.
4. Run candidate retrieval variants.
5. Check whether the source memory appears in top 3.
6. Mark coverage score.
```

指标：

```text
cue_coverage = successful_top3_queries / generated_future_queries
```

Quality flags：

```text
low_cue_coverage
no_decision_question_cue
missing_runtime_file_cue
overbroad_cue
concept_mismatch
```

验收线：

```text
cue_coverage >= 0.80 for seed suite
```

这与 HyDE 相邻，但仍保持结构化：future queries 是测试探针，不是 canonical metadata。

### 13.5 Memory Density Curve

在不同 active memory 数量下运行 retrieval eval：

```text
10 active records
50 active records
100 active records
200 active records
```

比较：

```text
baseline_content vs record_query_cues
```

核心问题：

```text
Does cue-based retrieval degrade more slowly as memory gets denser?
```

这是最重要的长期信号。Cue 的价值不主要体现在 10 条 memory，而体现在 100-200 条 active memory 下减少关键词碰撞和噪声。

### 13.6 Eval Assets

新增：

```text
evals/cases/memory-cue-retrieval.yaml
evals/fixtures/memory_cues/
tests/test_memory_cue_models.py
tests/test_memory_cue_engine.py
tests/test_memory_cue_eval.py
```

Promptfoo eval 用于端到端行为 smoke。Python harness 用于 deterministic variants、ablation 和 density curve。

### 13.7 Non-Goals For Eval

本 spec 不需要证明所有 memory 任务最终成功。它需要证明：

```text
- cue generation is valid and evidence-preserving
- query interpretation produces stable structured cues
- bidirectional cue representation improves recall metrics
- improvement persists or grows as memory density increases
```

端到端任务成功属于更广义的 memory retrieval spec。

---

## 14. Observability

新增 local/audit-compatible events：

```text
record_cue_generated
record_cue_generation_failed
query_cue_interpreted
query_cue_interpretation_failed
memory_search_with_query_cue
```

必填字段：

```text
schema_version
generator_version / interpreter_version
latency_ms
fallback_used
concept_count
cue_count
quality_flags
```

可选 debug 字段：

```text
query_cue
cue_metadata
candidate memory ids
why_matched details
```

默认不外发，不记录完整敏感内容。

---

## 15. 配置

建议配置：

```toml
[memory.cues]
enabled = true
record_generation = true
query_interpretation = true
query_interpretation_fast_path = true
record_generator_model = "small"
query_interpreter_model = "small"
generation_timeout_ms = 1500
query_interpret_timeout_ms = 800
query_interpret_cache_size = 512
persist_failed_metadata = true
record_generation_mode = "sync"  # sync | deferred
batch_generation = false
debug_output = false
```

配置行为：

```text
enabled=false:
  no cue generation, no query interpretation

record_generation=false:
  no cue metadata generated on write, but existing metadata may still be read

query_interpretation=false:
  memory_search uses original query and runtime hints only

query_interpretation_fast_path=true:
  should_interpret_query() may skip model interpretation for short/path/code/command-like queries

persist_failed_metadata=true:
  failed/partial metadata persists with quality_flags for audit/eval

record_generation_mode=sync:
  memory_write waits for cue generation up to generation_timeout_ms

record_generation_mode=deferred:
  memory_write persists core record first and fills cue metadata later
```

---

## 16. 分阶段交付

### Phase 0：Spec And Eval Harness

交付：

- 本 spec。
- cue taxonomy 和 data model 测试草案。
- memory cue retrieval eval fixture 草案。
- 明确 baseline_content / record_cues / query_cues / record_query_cues 的评测方法。

目标：

- 在实现前明确成功标准。
- 避免 cue prompt 调整只能靠主观感觉。

### Phase 1：Record-Side Cue Metadata

交付：

- `src/bourbon/memory/cues/models.py`
- `CueEngine.generate_for_record()`
- `MemoryRecord.cue_metadata`
- `MemoryStore` frontmatter serialization。
- `MemoryManager.write()` 集成。
- `CueRuntimeContext` adapter from Agent/session/tool trace。
- generation validation 和 fallback。
- 基础 unit/integration tests。

目标：

- 新写入 memory 自动获得 cue metadata。
- 不改变 `memory_search` 行为或只做最小兼容。

### Phase 2：Backfill And Generation Eval

交付：

- `scripts/backfill_memory_cues.py`
- `CueEngine.generate_for_records()` 或等价 batch/deferred worker。
- schema/generation quality eval。
- cue coverage harness。
- 生成质量 report。

目标：

- 给已有 memory 补 cue metadata。
- 用真实 Bourbon memory 检查 cue prompt 质量。

### Phase 3：Query-Side Interpretation

交付：

- `CueEngine.interpret_query()`
- `should_interpret_query()` fast path。
- QueryCue cache。
- query interpreter timeout/fallback。
- `memory_search` 内部可选 query cue。
- query-side telemetry。

目标：

- record-side 和 query-side 形成双向 cue representation。
- 保持 search/ranking 归属不变。

### Phase 4：Cue-Based Retrieval Evaluation

交付：

- `evals/cases/memory-cue-retrieval.yaml`
- Python ablation harness。
- density curve。
- field metrics report。

目标：

- 验证 bidirectional cue representation 对 Recall@K、MRR、Noise@K 的提升。
- 决定后续是否进入 FTS/BM25/embedding retrieval spec。

### Phase 5：Retrieval Spec Handoff

交付：

- 使用 `QueryCue` 和 `MemoryCueMetadata` 的 retrieval/ranking spec。
- 决定是否引入 FTS、BM25、embedding、HyDE-like semantic text。

目标：

- 把 cue engine 的输出接入完整 retrieval pipeline。
- 不在 cue spec 中提前绑定 retrieval backend。

---

## 17. 风险与缓解

### 风险：query-side 小模型增加热路径延迟

缓解：

- timeout。
- cache。
- `should_interpret_query()` fast path，跳过短查询、纯路径、代码片段、纯命令。
- fallback to original query。
- field telemetry 跟踪 p50/p95 latency。
- field telemetry 分开记录 fast path fallback、model failure fallback、timeout fallback。
- config 可关闭 query interpretation。

### 风险：record-side cue generation 阻塞 memory_write

缓解：

- interactive `memory_write` 使用 bounded sync timeout。
- compaction/auto-extract 不串行等待多条模型调用。
- backfill 使用 batch API。
- 支持 `record_generation_mode=deferred`。
- failed/partial metadata 可持久化，后续补全。

### 风险：LLM 生成虚假 files/symbols

缓解：

- runtime evidence priority。
- non-existing LLM path 不进入 authoritative `files`。
- source/confidence 必填。
- invalid_file_hint_rate 纳入验收。

### 风险：taxonomy 过细导致 query-side 摇摆

缓解：

- v1 只保留 10 个 concepts。
- 合并 gotcha/failure/debugging 为 `RISK_OR_LESSON`。
- concept_drift 纳入 field metrics。

### 风险：cue prompt 调整破坏旧 memory 一致性

缓解：

- schema_version。
- generator_version。
- backfill script。
- density/effectiveness eval。

### 风险：Cue Engine 偷偷变成 search engine

缓解：

- 明确 architecture boundary。
- `CueEngine` 不返回 ranked memory ids。
- ranking/fusion 在后续 retrieval spec 中设计。

### 风险：Telemetry 记录敏感内容

缓解：

- 默认只记录 hash、计数、版本、latency 和 flags。
- debug output 需要显式配置开启。
- 不外发默认 telemetry。

---

## 18. 测试策略

### Unit Tests

```text
tests/test_memory_cue_models.py
  MemoryConcept/CueKind/CueSource values
  CueQualityFlag values
  DomainConcept validation
  RetrievalCue validation
  MemoryCueMetadata validation
  QueryCue validation
  TimeHint validation
  schema_version/generator_version requirements

tests/test_memory_cue_normalize.py
  cue text truncation/rejection
  duplicate removal
  path normalization
  confidence clamping
  unknown concept/kind rejection

tests/test_memory_cue_runtime.py
  source_ref file extraction
  touched/modified/current file merging
  runtime evidence preservation
  LLM path downgrade behavior
  Agent/session/tool trace adapter
  runtime_context.fingerprint changes when current files change
```

### Integration Tests

```text
tests/test_memory_cue_engine.py
  generate_for_record success
  generate_for_record partial output
  generate_for_record model failure fallback
  generate_for_records batch behavior
  interpret_query success
  should_interpret_query skips short/path/code/command-like query
  interpret_query failure fallback
  query interpretation cache

tests/test_memory_store.py
  cue_metadata frontmatter roundtrip
  old memory file without cue_metadata remains valid
  malformed cue_metadata does not lose record
  malformed YAML frontmatter does not crash parser

tests/test_memory_manager.py
  write integrates CueEngine
  write succeeds when CueEngine fails
  search accepts optional QueryCue without breaking current behavior
```

### Eval Tests

```text
tests/test_memory_cue_eval.py
  baseline_content vs record_cues fixture
  record_query_cues MRR lift smoke
  cue coverage calculation
  density curve harness can run with synthetic records
```

---

## 19. 已收敛决策与剩余问题

剩余待决策：

1. `record_generator_model = "small"` 应映射到哪个现有 provider/model 配置？
2. `memory_search` 是否在 debug mode 输出 `query_cue`，还是只落 telemetry？
3. record-side deferred/batch worker 具体复用现有 executor、task system，还是新增 memory-local queue？

本轮已收敛：

1. query interpretation 默认不对所有 `memory_search` 无条件开启；MVP 使用 `should_interpret_query()` fast path，只对有足够语义内容或明显 recall marker 的 query 调模型。
2. `CueRuntimeContext.current_files` 在 CLI 环境中由 Agent/session/tool trace adapter 推断，优先来自最近成功 read/edit，其次来自 search/glob/data/document tools。
3. MVP 默认持久化 `generation_status=failed` / `partial` 的 metadata，并通过 `CueQualityFlag` 暴露原因；config 可关闭。
4. `semantic_query_text` 在 V3 不作为 canonical output，可保留 `render_semantic_query_text(QueryCue)` 派生函数供后续 embedding 实验。
5. `MemoryConcept` v1 使用全局受控 taxonomy，同时通过 `DomainConcept(namespace, value, source, schema_version)` 预留 skill/project domain 扩展。
6. record-side generation 在 interactive write 中默认同步，但 compaction、auto-extract、backfill 应使用 deferred 或 batch 策略。

---

## 20. 最终建议

Bourbon Memory V3 应将 cue engine 作为独立表示层，而不是作为 search backend 的附属功能。

推荐主线：

```text
Structured bidirectional cue representation
  record-side: MemoryCueMetadata
  query-side: QueryCue
  shared: controlled MemoryConcept taxonomy
  evidence: runtime-first, LLM-supplemented
  eval: recall lift + density curve
```

不建议现在直接做：

```text
embedding-first memory retrieval
per-prompt fixed top-k injection
HyDE document as canonical representation
cue engine owning ranking
```

最小落地顺序：

```text
1. cue models + taxonomy
2. CueRuntimeContext adapter
3. record-side generation and persistence
4. generation eval + backfill/batch
5. query-side interpretation + fast path/cache
6. bidirectional cue retrieval eval
7. retrieval/ranking spec
```

这条路线保留 Bourbon 当前 file-first、audit-first、prompt-anchor-stable 的优势，同时把记忆系统最薄弱的部分从“搜正文”升级为“写入和检索共享一套可评测的 cue representation”。
