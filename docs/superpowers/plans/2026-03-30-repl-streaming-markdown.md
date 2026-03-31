# REPL Streaming Markdown Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore streaming body output in the REPL while keeping markdown rendering stable enough to avoid raw/rendered duplication artifacts.

**Architecture:** Keep the existing Rich `Live` flow in `src/bourbon/repl.py`, but replace the current status-only renderable with an incremental markdown renderable that splits the full buffer into a stable markdown prefix and a pending tail. Render the stable prefix as markdown during the stream and the tail as plain text until it becomes render-safe.

**Tech Stack:** Python, Rich `Live`, Rich `Markdown`, pytest

---

### Task 1: Add failing tests for stable-prefix streaming

**Files:**
- Modify: `tests/test_repl_activity_indicator.py`
- Modify: `tests/test_repl_streaming.py`

- [ ] **Step 1: Write failing tests**

Cover:
- the live renderable shows streamed body output again
- incomplete markdown remains buffered in the pending tail
- final markdown still renders through the REPL path: capture all `console.print` calls, filter for `Markdown` instances, and assert the full accumulated response text appears in the final `Markdown` argument (not just that `console.print` was called at all)

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_repl_activity_indicator.py tests/test_repl_streaming.py -q`
Expected: FAIL because the live renderable is currently status-only

### Task 2: Implement stable-prefix streaming markdown

**Files:**
- Modify: `src/bourbon/repl.py`
- Modify: `tests/test_repl_activity_indicator.py` (only if minor adjustments needed to make Task 1 tests pass)
- Modify: `tests/test_repl_streaming.py` (only if minor adjustments needed to make Task 1 tests pass)

- [ ] **Step 1: Add buffer-splitting helpers**

Implement `_split_stable_markdown(buffer: str) -> tuple[str, str]` as a **module-level function** in `src/bourbon/repl.py` (not nested, not a method) so tests can import and call it directly.

Split logic:
- When `buffer` ends with `\n`: use the entire buffer as the initial stable candidate, then apply guard passes to move unsafe trailing content back into the pending tail
- When `buffer` does not end with `\n`: treat the incomplete final line as pending tail immediately
- Guard passes check for: unclosed fenced code block, unclosed table block, unbalanced inline markers (`**`, `` ` ``) on the last line

- [ ] **Step 2: Restore streamed body rendering**

Update the live renderable to show:
- animated status line
- markdown-rendered stable prefix
- raw pending tail

- [ ] **Step 3: Run focused tests**

Run: `.venv/bin/pytest tests/test_repl_activity_indicator.py tests/test_repl_streaming.py -q`
Expected: PASS

### Task 3: Regression verification

**Files:** Verify only (no modifications expected)

- [ ] **Step 1: Run regression suite**

Run: `.venv/bin/pytest tests/test_repl_activity_indicator.py tests/test_repl_streaming.py tests/test_debug_logging.py tests/test_agent_streaming.py tests/test_llm_streaming.py tests/test_repl_context_display.py -q`
Expected: PASS

- [ ] **Step 2: Run lint**

Run: `.venv/bin/ruff check src/bourbon/repl.py tests/test_repl_activity_indicator.py tests/test_repl_streaming.py`
Expected: PASS

- [ ] **Step 3: Run type check**

Run: `mypy src/bourbon/repl.py`
Expected: PASS (no new errors introduced)
