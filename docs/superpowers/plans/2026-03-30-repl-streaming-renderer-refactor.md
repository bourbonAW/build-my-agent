# REPL Streaming Renderer Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Bourbon's current `Rich Live + custom stable_prefix/pending_tail` streaming path with a `prompt_toolkit`-owned transcript UI backed by a community-supported streaming markdown renderer.

**Architecture:** Convert `bourbon.repl` from a monolithic module into a package-backed REPL surface. Introduce a dedicated renderer adapter around `md2term`, a transcript buffer for all REPL output, and a stream controller that bridges `agent.step_stream()` to a thread-safe UI event queue. Remove `Rich Live` and all product-owned incremental markdown heuristics from the main streaming path once the new transcript path is verified.

**Tech Stack:** Python 3.12+, prompt_toolkit, md2term, pytest, ruff

---

## Planned File Structure

**Create:**
- `src/bourbon/repl/__init__.py`
- `src/bourbon/repl/app.py`
- `src/bourbon/repl/commands.py`
- `src/bourbon/repl/renderers.py`
- `src/bourbon/repl/stream_controller.py`
- `src/bourbon/repl/transcript.py`
- `tests/repl/test_public_api.py`
- `tests/repl/test_renderers.py`
- `tests/repl/test_stream_controller.py`
- `tests/repl/test_transcript.py`
- `tests/repl/test_app.py`

**Modify:**
- `pyproject.toml`
- `src/bourbon/cli.py`
- `src/bourbon/debug.py`
- `tests/test_debug_logging.py`
- `tests/test_repl_context_display.py`
- `tests/test_repl_streaming.py`
- `tests/test_mcp_sync_runtime.py`

**Remove or replace during migration:**
- `src/bourbon/repl.py`
- `tests/test_repl_activity_indicator.py`

## Notes Before Implementation

- `bourbon.repl` currently exists as `src/bourbon/repl.py`. To add helper modules under `bourbon.repl.*`, the implementation must convert this module into a package while preserving the public import path `from bourbon.repl import REPL`.
- Do not carry the existing `stable_prefix/pending_tail` helpers forward into the new path. Delete them once the transcript path is green.
- Treat `md2term` as a renderer dependency, not as a new UI owner. `prompt_toolkit` remains the only interactive terminal controller.

### Task 1: Add a protective public API test before restructuring `bourbon.repl`

**Files:**
- Create: `tests/repl/test_public_api.py`
- Test: `tests/repl/test_public_api.py`

- [ ] **Step 1: Write the failing test that locks the future package API**

```python
from bourbon.repl import REPL


def test_repl_public_import_stays_stable():
    assert REPL.__name__ == "REPL"
```

- [ ] **Step 2: Run the test to verify the new test file is wired up**

Run: `.venv/bin/pytest tests/repl/test_public_api.py -q`
Expected: PASS

- [ ] **Step 3: Commit the guardrail**

```bash
git add tests/repl/test_public_api.py
git commit -m "test: lock bourbon.repl public import"
```

### Task 2: Add failing tests for the `md2term` renderer adapter

**Files:**
- Modify: `pyproject.toml`
- Create: `src/bourbon/repl/renderers.py`
- Create: `tests/repl/test_renderers.py`
- Test: `tests/repl/test_renderers.py`

- [ ] **Step 1: Write failing tests for incremental markdown rendering**

```python
def test_renderer_streams_list_without_custom_tail_heuristics():
    renderer = StreamingMarkdownRendererAdapter()
    renderer.append_chunk("## Title\n- item\n")
    assert "item" in renderer.snapshot()


def test_renderer_keeps_incomplete_link_stable():
    renderer = StreamingMarkdownRendererAdapter()
    renderer.append_chunk("A [link](https://example.com")
    assert "A" in renderer.snapshot()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/repl/test_renderers.py -q`
Expected: FAIL with import or implementation errors because the adapter does not exist yet

- [ ] **Step 3: Add the runtime dependency**

Modify `pyproject.toml` to include `md2term`.

- [ ] **Step 4: Install dependencies into the local environment**

Run: `uv pip install -e ".[dev]"`
Expected: PASS with `md2term` available in `.venv`

- [ ] **Step 5: Implement the minimal adapter**

Create `src/bourbon/repl/renderers.py` with:
- `StreamingMarkdownRendererAdapter`
- `reset()`
- `append_chunk(text: str)`
- `snapshot() -> str`
- `finalize(text: str) -> str`

Keep all `md2term` specifics inside this file.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/repl/test_renderers.py -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml src/bourbon/repl/renderers.py tests/repl/test_renderers.py
git commit -m "feat: add streaming markdown renderer adapter"
```

### Task 3: Add transcript models and lifecycle tests

**Files:**
- Create: `src/bourbon/repl/transcript.py`
- Create: `tests/repl/test_transcript.py`
- Test: `tests/repl/test_transcript.py`

- [ ] **Step 1: Write the failing tests**

Cover:
- appending `user_message`
- creating an `assistant_draft`
- promoting `assistant_draft` to `assistant_final`
- inserting `tool_event` and `confirmation_prompt`
- state transitions `thinking -> replying -> completed`

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/repl/test_transcript.py -q`
Expected: FAIL because transcript models do not exist yet

- [ ] **Step 3: Implement the minimal transcript module**

Create in `src/bourbon/repl/transcript.py`:
- transcript item dataclasses or pydantic models
- `TranscriptBuffer`
- helper methods for draft creation, chunk append, finalization, and confirmation insertion

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/repl/test_transcript.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/bourbon/repl/transcript.py tests/repl/test_transcript.py
git commit -m "feat: add repl transcript model"
```

### Task 4: Add a stream controller that bridges `agent.step_stream()` to UI events

**Files:**
- Create: `src/bourbon/repl/stream_controller.py`
- Create: `tests/repl/test_stream_controller.py`
- Test: `tests/repl/test_stream_controller.py`

- [ ] **Step 1: Write the failing tests**

Cover:
- `step_stream()` text chunks become normalized queue events
- tool callbacks become `tool_event` records
- exceptions become `error` events
- pending confirmation becomes `confirmation_prompt`

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/repl/test_stream_controller.py -q`
Expected: FAIL because the controller does not exist yet

- [ ] **Step 3: Implement the minimal stream controller**

Create `src/bourbon/repl/stream_controller.py` with:
- a worker wrapper around `agent.step_stream()`
- a thread-safe queue interface
- event normalization for `chunk`, `tool_start`, `tool_end`, `complete`, `error`, `confirmation`

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/repl/test_stream_controller.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/bourbon/repl/stream_controller.py tests/repl/test_stream_controller.py
git commit -m "feat: add repl stream controller"
```

### Task 5: Convert `bourbon.repl` from a module into a package without changing public imports

**Files:**
- Modify: `src/bourbon/repl.py`
- Create: `src/bourbon/repl/__init__.py`
- Create: `src/bourbon/repl/commands.py`
- Modify: `src/bourbon/cli.py`
- Modify: `tests/repl/test_public_api.py`
- Modify: `tests/test_repl_context_display.py`
- Modify: `tests/test_mcp_sync_runtime.py`

- [ ] **Step 1: Move the existing public REPL surface into a package**

Convert:
- `src/bourbon/repl.py` -> `src/bourbon/repl/__init__.py`

Keep `REPL` exported from `bourbon.repl`.

- [ ] **Step 2: Add a small `commands.py` helper module**

Move command parsing and dispatch helpers out of `__init__.py` while keeping behavior unchanged.

- [ ] **Step 3: Run the guard tests**

Run: `.venv/bin/pytest tests/repl/test_public_api.py tests/test_repl_context_display.py tests/test_mcp_sync_runtime.py -q`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/bourbon/repl.py src/bourbon/repl/__init__.py src/bourbon/repl/commands.py src/bourbon/cli.py tests/repl/test_public_api.py tests/test_repl_context_display.py tests/test_mcp_sync_runtime.py
git commit -m "refactor: convert bourbon.repl into package"
```

### Task 6: Add the `prompt_toolkit` transcript application shell

**Files:**
- Create: `src/bourbon/repl/app.py`
- Create: `tests/repl/test_app.py`
- Modify: `src/bourbon/repl/__init__.py`
- Modify: `tests/test_repl_streaming.py`
- Modify: `tests/test_debug_logging.py`

- [ ] **Step 1: Write the failing app tests**

Cover:
- transcript pane renders transcript items instead of direct `console.print`
- input pane remains editable while transcript updates
- toolbar still shows context usage
- app can enter `thinking`, `replying`, and `awaiting_confirmation`

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/repl/test_app.py tests/test_repl_streaming.py tests/test_debug_logging.py -q`
Expected: FAIL because the app shell does not exist yet

- [ ] **Step 3: Implement the minimal app shell**

Create `src/bourbon/repl/app.py` with:
- `prompt_toolkit.Application`
- transcript pane
- input pane
- toolbar binding to current context logic
- queue consumption and `invalidate()` repaint flow

- [ ] **Step 4: Rewire `REPL` to use the app shell**

Update `src/bourbon/repl/__init__.py` so `REPL.run()` and streaming entry points route through `ReplApplication`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/repl/test_app.py tests/test_repl_streaming.py tests/test_debug_logging.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/bourbon/repl/__init__.py src/bourbon/repl/app.py tests/repl/test_app.py tests/test_repl_streaming.py tests/test_debug_logging.py
git commit -m "feat: add prompt_toolkit transcript app"
```

### Task 7: Route tool events and high-risk confirmation through transcript items

**Files:**
- Modify: `src/bourbon/repl/__init__.py`
- Modify: `src/bourbon/repl/app.py`
- Modify: `src/bourbon/repl/stream_controller.py`
- Modify: `src/bourbon/repl/transcript.py`
- Modify: `tests/repl/test_app.py`
- Modify: `tests/test_agent_streaming.py`

- [ ] **Step 1: Write the failing tests**

Cover:
- tool start/end messages appear as transcript entries
- pending confirmation enters confirmation mode without imperative `console.print`
- selection returns control to the normal input prompt after completion

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/repl/test_app.py tests/test_agent_streaming.py -q`
Expected: FAIL because the old print-based confirmation flow still exists

- [ ] **Step 3: Implement the minimal routing changes**

Remove direct `console.print` from tool and confirmation paths in the interactive REPL flow and replace them with transcript updates.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/repl/test_app.py tests/test_agent_streaming.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/bourbon/repl/__init__.py src/bourbon/repl/app.py src/bourbon/repl/stream_controller.py src/bourbon/repl/transcript.py tests/repl/test_app.py tests/test_agent_streaming.py
git commit -m "feat: route repl tool and confirmation events through transcript"
```

### Task 8: Delete the legacy Rich Live path and heuristic-specific tests

**Files:**
- Modify: `src/bourbon/repl/__init__.py`
- Delete: `tests/test_repl_activity_indicator.py`
- Modify: `tests/test_repl_streaming.py`
- Modify: `tests/test_debug_logging.py`

- [ ] **Step 1: Write the failing regression tests for the new steady state**

Cover:
- no `Live(...)` dependency in the assistant streaming path
- no `_split_stable_markdown()` helpers
- final response is not duplicated
- streaming output still appears before completion

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_repl_streaming.py tests/test_debug_logging.py -q`
Expected: FAIL because the old path is still present

- [ ] **Step 3: Remove the legacy code**

Delete from the main REPL path:
- `StreamingDisplay`
- `_split_stable_markdown()`
- `_buffer_unclosed_fence()`
- `_buffer_unbalanced_last_line()`
- `_buffer_incomplete_table_block()`
- `Rich Live`-driven streaming output

- [ ] **Step 4: Replace heuristic-specific tests**

Remove `tests/test_repl_activity_indicator.py` and replace any remaining coverage with transcript/app tests.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/repl/test_app.py tests/repl/test_renderers.py tests/repl/test_stream_controller.py tests/repl/test_transcript.py tests/test_repl_streaming.py tests/test_debug_logging.py tests/test_repl_context_display.py tests/test_agent_streaming.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/bourbon/repl/__init__.py tests/repl/test_app.py tests/repl/test_renderers.py tests/repl/test_stream_controller.py tests/repl/test_transcript.py tests/test_repl_streaming.py tests/test_debug_logging.py tests/test_repl_context_display.py tests/test_agent_streaming.py
git rm tests/test_repl_activity_indicator.py
git commit -m "refactor: remove legacy rich live repl path"
```

### Task 9: Final verification and cleanup

**Files:**
- Modify: `docs/superpowers/specs/2026-03-30-repl-streaming-renderer-refactor-design.md`
- Modify: `docs/superpowers/plans/2026-03-30-repl-streaming-renderer-refactor.md`

- [ ] **Step 1: Run the focused regression suite**

Run: `.venv/bin/pytest tests/repl/test_public_api.py tests/repl/test_renderers.py tests/repl/test_stream_controller.py tests/repl/test_transcript.py tests/repl/test_app.py tests/test_repl_streaming.py tests/test_debug_logging.py tests/test_repl_context_display.py tests/test_agent_streaming.py tests/test_mcp_sync_runtime.py -q`
Expected: PASS

- [ ] **Step 2: Run lint**

Run: `.venv/bin/ruff check src/bourbon/repl src/bourbon/cli.py tests/repl tests/test_repl_streaming.py tests/test_debug_logging.py tests/test_repl_context_display.py tests/test_agent_streaming.py tests/test_mcp_sync_runtime.py`
Expected: PASS

- [ ] **Step 3: Update the spec and plan checkboxes if reality changed**

Keep the design docs accurate if file names or module boundaries changed during implementation.

- [ ] **Step 4: Commit the final verification**

```bash
git add docs/superpowers/specs/2026-03-30-repl-streaming-renderer-refactor-design.md docs/superpowers/plans/2026-03-30-repl-streaming-renderer-refactor.md
git commit -m "docs: finalize repl streaming renderer refactor plan"
```
