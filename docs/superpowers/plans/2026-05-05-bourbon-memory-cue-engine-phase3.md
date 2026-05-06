# Bourbon Memory Cue Engine Phase 3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add query-side cue representation, deterministic fast path, caching, and optional `memory_search` integration without changing the retrieval backend.

**Architecture:** Extend cue models with `QueryCue`, add query interpretation utilities to `CueEngine`, and let `MemoryManager.search()` optionally interpret a query into cue phrases. Search remains grep/file-first: the interpreted cue is used as bounded query expansion only, not as a ranking engine.

**Tech Stack:** Python dataclasses, deterministic heuristics, in-memory LRU-style cache, existing `MemoryManager`, existing `memory_search` tool, pytest, ruff, mypy.

---

## Implementation Status

**Phase:** Phase 3

**Status:** Completed

**Started:** 2026-05-05

**Completed:** 2026-05-06

**Verification:** Passed

**Task Progress:**

- [x] Task 1: QueryCue Models
- [x] Task 2: Query Interpretation Fast Path And Cache
- [x] Task 3: Optional Manager Search Integration
- [x] Task 4: Tool Debug Output
- [x] Task 5: Final Verification And Status Update

**Completion Notes:**

- 2026-05-05: Phase 3 plan created after Phase 2 completion.
- 2026-05-06: Implemented `QueryCue`, deterministic query fallback/cache, optional manager query expansion, and `memory_search(debug_cue=true)` compact debug output.
- 2026-05-06: Fixed review finding where default query runtime context embedded query text in `task_subject`, which defeated normalized query cache reuse.
- 2026-05-06: Verification passed: `uv run pytest tests/test_memory_cue_models.py tests/test_memory_cue_query.py tests/test_memory_manager.py tests/test_memory_tools.py -q` -> 54 passed; focused ruff passed; `uv run mypy src/bourbon/memory/cues` passed.

---

## Task 1: QueryCue Models

**Files:**

- Modify: `src/bourbon/memory/cues/models.py`
- Modify: `src/bourbon/memory/cues/__init__.py`
- Test: `tests/test_memory_cue_models.py`

Steps:

- [x] Add `RecallNeed` and `TimeHint` enums.
- [x] Add `QueryCue` dataclass with `schema_version`, `interpreter_version`, `recall_need`, `concepts`, `cue_phrases`, `file_hints`, `symbol_hints`, `kind_hints`, `scope_hint`, `uncertainty`, `domain_concepts`, `time_hint`, `time_range`, `generated_at`, `fallback_used`, `quality_flags`.
- [x] Add validation and frontmatter-style dict round-trip helpers.
- [x] Run `uv run pytest tests/test_memory_cue_models.py -q`.

## Task 2: Query Interpretation Fast Path And Cache

**Files:**

- Create: `src/bourbon/memory/cues/query.py`
- Modify: `src/bourbon/memory/cues/engine.py`
- Modify: `src/bourbon/memory/cues/__init__.py`
- Test: `tests/test_memory_cue_query.py`

Steps:

- [x] Implement `should_interpret_query(query: str, runtime_context: CueRuntimeContext) -> bool`.
- [x] Implement deterministic fallback `build_fallback_query_cue(query, runtime_context, *, recall_need=None)`.
- [x] Add `QueryCueCache` keyed by normalized query, runtime fingerprint, schema version, interpreter version.
- [x] Add `CueEngine.interpret_query(query, runtime_context=...) -> QueryCue` using fast path and fallback semantics.
- [x] No live LLM calls in this phase.
- [x] Run `uv run pytest tests/test_memory_cue_query.py -q`.

## Task 3: Optional Manager Search Integration

**Files:**

- Modify: `src/bourbon/memory/manager.py`
- Test: `tests/test_memory_manager.py`

Steps:

- [x] Add config-gated query interpretation in `MemoryManager.search()`.
- [x] When disabled, existing search behavior must be byte-for-byte equivalent in result shape.
- [x] When enabled, interpret query with default runtime context and search original query plus a bounded number of cue phrases until limit is filled.
- [x] Deduplicate result ids and annotate `why_matched` with query cue usage.
- [x] Do not bypass scope/kind/status filters.
- [x] Run `uv run pytest tests/test_memory_manager.py -q`.

## Task 4: Tool Debug Output

**Files:**

- Modify: `src/bourbon/tools/memory.py`
- Test: `tests/test_memory_tools.py`

Steps:

- [x] Add optional `debug_cue: bool` input to `memory_search`.
- [x] If debug is false or no query cue was produced, output remains compatible.
- [x] If debug is true and manager exposes a last query cue, include a compact serialized `query_cue` object.
- [x] Run `uv run pytest tests/test_memory_tools.py -q`.

## Task 5: Final Verification And Status Update

Steps:

- [x] Run `uv run pytest tests/test_memory_cue_models.py tests/test_memory_cue_query.py tests/test_memory_manager.py tests/test_memory_tools.py -q`.
- [x] Run `uv run ruff check src/bourbon/memory/cues src/bourbon/memory/manager.py src/bourbon/tools/memory.py tests/test_memory_cue_models.py tests/test_memory_cue_query.py tests/test_memory_manager.py tests/test_memory_tools.py`.
- [x] Run `uv run mypy src/bourbon/memory/cues`.
- [x] Update this plan’s status and checkbox list.

---

## Notes

- `recall_need` remains a policy signal, not a hard search switch.
- Query interpretation is deterministic in Phase 3; real LLM query interpretation can be added later behind the same interface.
- This phase does not introduce BM25/FTS/embedding.
