# Eval Validator Contract Gaps Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring the eval validator implementation back into alignment with the approved Phase 1/2 contracts for report schema, artifact schema, config plumbing, and debug behavior.

**Architecture:** Keep the existing validator flow intact (`runner -> artifact -> evaluator subprocess -> report`) and patch only the contract gaps identified in review. Add tests first for each contract, then implement the minimal code needed in `evals/validator/*`, `evals/runner.py`, and `evals/README.md`.

**Tech Stack:** Python 3.10+, pytest, existing Bourbon eval runner and validator modules

---

### Task 1: Report Contract

**Files:**
- Modify: `evals/validator/report.py`
- Test: `tests/evals/validator/test_report.py`

- [ ] Add failing tests for report metadata fields and weight normalization behavior.
- [ ] Implement `version`, `timestamp`, `evaluator_focus`, `skills_used`, and `telemetry` support.
- [ ] Implement weight normalization with warning when weights do not sum to `1.0`.
- [ ] Run `uv run pytest tests/evals/validator/test_report.py -q`.

### Task 2: Artifact Contract And Runner Plumbing

**Files:**
- Modify: `evals/validator/artifact.py`
- Modify: `evals/runner.py`
- Test: `tests/evals/validator/test_artifact.py`
- Test: `tests/evals/test_validation_integration.py`

- [ ] Add failing tests for `generator_version`, `tool_calls`, `errors`, and exclude-pattern plumbing.
- [ ] Implement artifact field support and runner wiring for evaluator exclude patterns.
- [ ] Run focused artifact and integration tests.

### Task 3: Debug Retention

**Files:**
- Modify: `evals/runner.py`
- Test: `tests/evals/test_validation_integration.py`

- [ ] Add failing tests for `EVAL_KEEP_ARTIFACTS=1`.
- [ ] Implement conditional workspace cleanup for debug mode.
- [ ] Run focused integration tests.

### Task 4: Docs Sync

**Files:**
- Modify: `evals/README.md`

- [ ] Update README to describe current Phase 2 evaluator path and the real remaining gaps.
- [ ] Run the validator test suite plus README-adjacent integration coverage.
