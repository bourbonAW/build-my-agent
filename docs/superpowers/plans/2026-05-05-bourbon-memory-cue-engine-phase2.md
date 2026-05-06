# Bourbon Memory Cue Engine Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Backfill cue metadata for existing memory records and add deterministic generation-quality evaluation.

**Architecture:** Keep Phase 2 offline and batch-oriented. Add a small backfill module that reads records through `MemoryStore`, generates missing or forced `MemoryCueMetadata` via `CueEngine.generate_for_records()`, and atomically rewrites the existing records. Add a CLI wrapper under `scripts/` and extend deterministic eval helpers with cue coverage and generation quality reports.

**Tech Stack:** Python dataclasses, argparse, JSON output, existing `MemoryStore`, existing `CueEngine`, pytest, ruff.

---

## Implementation Status

**Phase:** Phase 2

**Status:** Completed

**Started:** 2026-05-05

**Completed:** 2026-05-05

**Verification:** `uv run pytest tests/test_memory_cue_backfill.py tests/test_memory_cue_backfill_script.py tests/test_memory_cue_eval.py tests/test_memory_store.py -q` -> 53 passed; Phase 2 ruff -> passed; `uv run mypy src/bourbon/memory/cues scripts/backfill_memory_cues.py` -> passed.

**Task Progress:**

- [x] Task 1: Store Cue Metadata Update API
- [x] Task 2: Backfill Service
- [x] Task 3: Backfill CLI Script
- [x] Task 4: Cue Coverage And Generation Quality Eval
- [x] Task 5: Final Verification And Status Update

**Completion Notes:**

- 2026-05-05: Phase 2 plan created after Phase 0/1 completion.
- 2026-05-05: Phase 2 completed. Review finding about failed generated metadata was fixed: failed metadata is counted as `failed` and not written, allowing future retries.

---

## Task 1: Store Cue Metadata Update API

**Files:**

- Modify: `src/bourbon/memory/store.py`
- Test: `tests/test_memory_store.py`

Steps:

- [ ] Add a failing test `test_update_cue_metadata_rewrites_existing_record_without_changing_status()`.
- [ ] Implement `MemoryStore.update_cue_metadata(memory_id: str, cue_metadata: MemoryCueMetadata) -> MemoryRecord`.
- [ ] Preserve record id, status, timestamps except `updated_at`, content, and filename identity.
- [ ] Run `uv run pytest tests/test_memory_store.py -q`.

## Task 2: Backfill Service

**Files:**

- Create: `src/bourbon/memory/cues/backfill.py`
- Modify: `src/bourbon/memory/cues/__init__.py`
- Test: `tests/test_memory_cue_backfill.py`

Steps:

- [ ] Add tests for dry-run, skip existing cue metadata, force regeneration, and limit.
- [ ] Implement `BackfillStats` dataclass.
- [ ] Implement `backfill_memory_cues(store: MemoryStore, engine: CueEngine, *, runtime_context_factory=None, dry_run=False, force=False, limit=None) -> BackfillStats`.
- [ ] Use `CueEngine.generate_for_records()` for batch generation.
- [ ] Run `uv run pytest tests/test_memory_cue_backfill.py -q`.

## Task 3: Backfill CLI Script

**Files:**

- Create: `scripts/backfill_memory_cues.py`
- Test: `tests/test_memory_cue_backfill_script.py`

Steps:

- [ ] Add tests that call the script through `subprocess.run()`.
- [ ] CLI arguments: `--memory-dir`, `--dry-run`, `--force`, `--limit`, `--json`.
- [ ] Human output should summarize scanned/backfilled/skipped/failed counts.
- [ ] JSON output should be a stable object with the same counters.
- [ ] Run `uv run pytest tests/test_memory_cue_backfill_script.py -q`.

## Task 4: Cue Coverage And Generation Quality Eval

**Files:**

- Modify: `src/bourbon/memory/cues/eval.py`
- Test: `tests/test_memory_cue_eval.py`

Steps:

- [ ] Add `CueCoverageCase` and `CueCoverageResult`.
- [ ] Implement `evaluate_cue_coverage(cases: list[CueCoverageCase]) -> CueCoverageResult`.
- [ ] Add `GenerationQualityReport`.
- [ ] Implement `build_generation_quality_report(records: Mapping[str, MemoryCueMetadata]) -> GenerationQualityReport`.
- [ ] Run `uv run pytest tests/test_memory_cue_eval.py -q`.

## Task 5: Final Verification And Status Update

Steps:

- [ ] Run `uv run pytest tests/test_memory_cue_backfill.py tests/test_memory_cue_backfill_script.py tests/test_memory_cue_eval.py tests/test_memory_store.py -q`.
- [ ] Run `uv run ruff check src/bourbon/memory/cues src/bourbon/memory/store.py scripts/backfill_memory_cues.py tests/test_memory_cue_backfill.py tests/test_memory_cue_backfill_script.py tests/test_memory_cue_eval.py tests/test_memory_store.py`.
- [ ] Run `uv run mypy src/bourbon/memory/cues scripts/backfill_memory_cues.py`.
- [ ] Update this plan’s status and checkbox list.

---

## Notes

- This phase does not add background workers. The CLI/backfill service is the batch/deferred path for Phase 2.
- This phase does not change `memory_search`.
- Existing records with cue metadata are skipped unless `force=True`.
