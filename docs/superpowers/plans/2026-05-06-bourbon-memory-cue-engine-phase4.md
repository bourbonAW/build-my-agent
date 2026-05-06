# Bourbon Memory Cue Engine Phase 4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic cue retrieval evaluation for ablation, density curves, and field metrics without changing Bourbon runtime retrieval.

**Architecture:** Extend `bourbon.memory.cues.eval` with fixture-based retrieval variants that compare baseline content search against record-side and query-side cue representations. Add a promptfoo smoke provider/case that runs the deterministic harness over a static fixture; keep promptfoo for end-to-end smoke and Python tests for precise metrics.

**Tech Stack:** Python dataclasses, `StrEnum`, JSON fixtures, promptfoo provider YAML, pytest, ruff, mypy.

---

## Implementation Status

**Phase:** Phase 4

**Status:** Completed

**Started:** 2026-05-06

**Completed:** 2026-05-06

**Verification:** Passed

**Task Progress:**

- [x] Task 1: Retrieval Variant Harness
- [x] Task 2: Density Curve And Field Metrics
- [x] Task 3: Promptfoo Smoke Assets
- [x] Task 4: Final Verification And Status Update

**Completion Notes:**

- 2026-05-06: Phase 4 plan created after Phase 3 implementation verification.
- 2026-05-06: Added deterministic retrieval variants, ablation metrics, density curve, field metrics, promptfoo smoke provider/case/fixture, and public eval exports.
- 2026-05-06: Fixed review findings: provider mypy import handling is stable; smoke fixture now enforces `Noise@8 <= 0.35`, has non-zero baseline MRR, and verifies `record_query_cues` MRR lift over baseline.
- 2026-05-06: Verification passed: `uv run pytest tests/test_memory_cue_eval.py -q` -> 14 passed; focused ruff passed; provider and combined mypy passed.
- 2026-05-06: Promptfoo CLI smoke was attempted with `npx promptfoo@latest eval --filter-pattern "Memory Cue Retrieval"` but npm failed before install with `ECONNRESET`; deterministic provider behavior is covered by pytest.

---

## Task 1: Retrieval Variant Harness

**Files:**

- Modify: `src/bourbon/memory/cues/eval.py`
- Test: `tests/test_memory_cue_eval.py`

Steps:

- [x] Add `RetrievalVariant` enum with `baseline_content`, `record_cues`, `query_cues`, `record_query_cues`, `ablation_concepts`, `ablation_files`, `ablation_llm_cues`, and `ablation_runtime_cues`.
- [x] Add fixture dataclasses for memory records and eval cases.
- [x] Implement deterministic ranking over selected query fields and selected record fields per variant.
- [x] Implement `evaluate_retrieval_variants()` returning Recall@K, MRR, Noise@K, and lift over baseline.
- [x] Add tests showing `record_query_cues` improves MRR over `baseline_content` on a curated fixture.
- [x] Run `uv run pytest tests/test_memory_cue_eval.py -q`.

## Task 2: Density Curve And Field Metrics

**Files:**

- Modify: `src/bourbon/memory/cues/eval.py`
- Test: `tests/test_memory_cue_eval.py`

Steps:

- [x] Add `DensityCurvePoint` and `evaluate_density_curve()` for densities such as 10, 50, 100, and 200 active records.
- [x] Add `CueEvalEvent` and `FieldCueMetricsReport`.
- [x] Implement `build_field_metrics_report()` with fallback rate, result use rate, query interpreter latency p50/p95, cue counts, and quality flag counts.
- [x] Add tests proving density harness runs against synthetic decoys and cue-based retrieval degrades slower than baseline.
- [x] Add tests proving field metrics do not require raw query text or memory content.
- [x] Run `uv run pytest tests/test_memory_cue_eval.py -q`.

## Task 3: Promptfoo Smoke Assets

**Files:**

- Create: `evals/memory_cue_retrieval_provider.py`
- Create: `evals/cases/memory-cue-retrieval.yaml`
- Create: `evals/fixtures/memory_cues/retrieval-smoke.json`
- Modify: `promptfooconfig.yaml`
- Test: `tests/test_memory_cue_eval.py`

Steps:

- [x] Add JSON fixture containing records, query cues, expected ids, and MVP thresholds.
- [x] Add promptfoo provider that loads the fixture, runs `evaluate_retrieval_variants()`, and returns JSON metrics.
- [x] Add promptfoo case assertions for Recall@8, Recall@3, MRR, Noise@8, and `record_query_cues` MRR lift.
- [x] Register `evals/cases/memory-cue-retrieval.yaml` in `promptfooconfig.yaml`.
- [x] Add a unit smoke test for the provider output shape and key metrics.
- [x] Run `uv run pytest tests/test_memory_cue_eval.py -q`.

## Task 4: Final Verification And Status Update

Steps:

- [x] Run `uv run pytest tests/test_memory_cue_eval.py -q`.
- [x] Run `uv run ruff check src/bourbon/memory/cues/eval.py evals/memory_cue_retrieval_provider.py tests/test_memory_cue_eval.py`.
- [x] Run `uv run mypy src/bourbon/memory/cues/eval.py evals/memory_cue_retrieval_provider.py`.
- [x] Update this plan’s status and checkbox list.

---

## Notes

- Phase 4 must not alter `MemoryManager.search()` behavior.
- Promptfoo smoke is deterministic and does not call the Bourbon agent or an external LLM.
- The harness measures candidate retrieval quality, not final answer quality.
