# REPL Activity Indicator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an animated Bourbon-themed activity indicator to the REPL streaming area so the UI visibly remains alive while the agent loop is running.

**Architecture:** Keep the change local to the REPL by introducing a small dynamic Rich renderable that owns streamed text and computes animation frames from elapsed monotonic time. Use the renderable as the `Live` target so animation continues even before the first chunk arrives.

**Tech Stack:** Python, Rich `Live`, prompt-toolkit, pytest

---

### Task 1: Add renderable tests

**Files:**
- Test: `tests/test_repl_activity_indicator.py`

- [ ] **Step 1: Write the failing tests**

Write tests that verify:
- before any chunk, the renderable shows `Bourbon is thinking`
- after a chunk is appended, the renderable shows `Bourbon is replying`
- rendering at two different times produces different animation frames

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_repl_activity_indicator.py -q`
Expected: FAIL because the renderable helper does not exist yet

### Task 2: Implement the renderable

**Files:**
- Modify: `src/bourbon/repl.py`
- Test: `tests/test_repl_activity_indicator.py`

- [ ] **Step 1: Add a focused helper class**

Implement a small helper in `src/bourbon/repl.py` that:
- stores `started_at`
- stores accumulated streamed text
- exposes `append_chunk()`
- renders an animated status line plus the current text body

- [ ] **Step 2: Wire the helper into the REPL live view**

Change `_process_input_streaming()` to:
- instantiate the helper before entering `Live`
- pass the helper as the live renderable
- append chunks into the helper
- refresh live output immediately on chunk arrival

- [ ] **Step 3: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_repl_activity_indicator.py tests/test_repl_streaming.py -q`
Expected: PASS

### Task 3: Regression verification

**Files:**
- Modify: `src/bourbon/repl.py`
- Test: `tests/test_debug_logging.py`
- Test: `tests/test_agent_streaming.py`
- Test: `tests/test_llm_streaming.py`

- [ ] **Step 1: Run focused regression checks**

Run: `.venv/bin/pytest tests/test_repl_activity_indicator.py tests/test_repl_streaming.py tests/test_debug_logging.py tests/test_agent_streaming.py tests/test_llm_streaming.py tests/test_repl_context_display.py -q`
Expected: PASS

- [ ] **Step 2: Run lint on touched files**

Run: `.venv/bin/ruff check src/bourbon/repl.py tests/test_repl_activity_indicator.py`
Expected: PASS
