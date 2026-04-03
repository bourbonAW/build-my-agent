# REPL Streaming Renderer Refactor Design

## Goal

Replace Bourbon's current `prompt_toolkit + Rich Live + custom markdown
stability heuristics` streaming path with a single-owner REPL architecture:

- `prompt_toolkit` owns the full terminal UI
- streaming markdown rendering is delegated to a community-supported renderer
- the current custom incremental markdown heuristics are removed from the main
  product path

The target outcome is true streaming output without duplicated rendering,
half-rendered markdown, or split terminal ownership.

## Problem

The current REPL streaming path in [src/bourbon/repl.py](src/bourbon/repl.py)
mixes three concerns in one loop:

- `prompt_toolkit` owns input and prompt state
- `Rich Live` owns the streaming output region
- Bourbon owns a custom `stable_prefix/pending_tail` heuristic layer to decide
  when markdown is safe to render

This design has two structural problems:

1. Terminal ownership is split across incompatible rendering systems.
2. Incremental markdown correctness depends on product-specific heuristics.

The heuristics reduce visible corruption, but they are a technical debt trap:

- every new markdown edge case requires more custom buffering logic
- correctness is tied to our own partial markdown parsing
- tool output, confirmation prompts, and assistant body rendering still share a
  fragile flow

This is not a bugfix target. It is an architectural refactor.

## Design Principles

- Use one terminal UI owner during interactive REPL operation.
- Reuse community-supported incremental markdown rendering instead of extending
  Bourbon's own parser heuristics.
- Keep the existing agent and LLM streaming protocol stable.
- Separate transcript state, rendering, and stream orchestration into distinct
  modules.
- Preserve current product behavior for commands, history, context toolbar,
  tool events, and high-risk confirmations.

## Non-Goals

- Redesign the agent loop or provider streaming APIs
- Change Bourbon command semantics
- Solve upstream provider stalls or SDK compatibility issues
- Preserve Rich Markdown styling exactly if the new renderer differs slightly

## Community Basis

The refactor is grounded in existing community patterns and tooling:

- `prompt_toolkit` documents that UI-safe output should go through its own
  terminal mechanisms rather than arbitrary stdout writes during an active
  application.
- Rich discussion history shows that `Live` plus interactive prompt ownership is
  not a robust foundation for mixed input and streaming output.
- `md2term` already provides a streaming markdown renderer for terminal use
  cases and is a better fit than continuing to grow Bourbon-specific heuristics.

Primary references:

- https://python-prompt-toolkit.readthedocs.io/en/latest/pages/asking_for_input.html
- https://python-prompt-toolkit.readthedocs.io/en/3.0.18/pages/reference.html
- https://github.com/Textualize/rich/discussions/1791
- https://pypi.org/project/md2term/

## Proposed Architecture

### 1. Single REPL UI Owner

`prompt_toolkit.Application` becomes the only owner of interactive terminal
layout and repainting.

The REPL surface is split into:

- transcript pane: read-only scrollable history and streaming output
- input pane: user prompt and confirmation entry
- toolbar: context usage and optional status

`Rich Live` is removed from the streaming body path.

### 2. Transcript-Centered Rendering

Streaming output is no longer "printed" directly. Instead, the REPL maintains a
structured transcript buffer.

Transcript item kinds:

- `user_message`
- `assistant_draft`
- `assistant_final`
- `tool_event`
- `error`
- `confirmation_prompt`
- `system_status`

The output pane renders transcript items, not ad hoc stdout writes.

### 3. Renderer Adapter

A dedicated adapter wraps `md2term` and is the only module allowed to turn
streaming markdown into terminal-formatted output.

The adapter owns renderer lifecycle and exposes a small interface:

- `reset()`
- `append_chunk(text: str)`
- `snapshot() -> str`
- `finalize(text: str) -> str`

This replaces Bourbon's current custom `_split_stable_markdown()` family.

### 4. Stream Controller

Agent execution runs outside the UI render path.

A stream controller:

- invokes `agent.step_stream()`
- receives text chunks and agent-side events
- pushes normalized UI events to a thread-safe queue
- never writes directly to the terminal

The UI thread consumes these events, updates transcript state, and invalidates
the application for repaint.

## State Model

The assistant turn should be modeled explicitly:

- `idle`
- `submitting`
- `thinking`
- `replying`
- `tool_running`
- `awaiting_confirmation`
- `completed`
- `failed`

State transitions:

1. user submits input
2. transcript adds `user_message`
3. transcript adds empty `assistant_draft`
4. stream controller starts agent worker
5. first chunk transitions `thinking -> replying`
6. tool events append `tool_event` items without entering markdown body flow
7. pending confirmation transitions to `awaiting_confirmation`
8. final response seals draft as `assistant_final`
9. errors append `error` item and return to `idle`

## Module Boundaries

The current monolithic REPL module should be split into focused modules:

- `src/bourbon/repl/__init__.py`
  public REPL entry point
- `src/bourbon/repl/app.py`
  `prompt_toolkit.Application`, layout, key bindings, toolbar, focus
- `src/bourbon/repl/transcript.py`
  transcript item models and transcript buffer
- `src/bourbon/repl/renderers.py`
  `md2term` streaming renderer adapter
- `src/bourbon/repl/stream_controller.py`
  background worker and UI event queue bridge
- `src/bourbon/repl/commands.py`
  command parsing and dispatch helpers

The legacy logic below should be removed from the main streaming path:

- `StreamingDisplay`
- `_split_stable_markdown()`
- `_buffer_unclosed_fence()`
- `_buffer_unbalanced_last_line()`
- `_buffer_incomplete_table_block()`
- `Live(...)`-driven assistant body rendering

## Event Flow

### Assistant Reply

1. User presses Enter.
2. UI writes a `user_message` transcript item.
3. UI creates an `assistant_draft` item and sets status to `thinking`.
4. Worker thread runs `agent.step_stream(user_input, on_chunk)`.
5. `on_chunk` enqueues `assistant_chunk` events.
6. UI consumes chunk events, appends to renderer adapter, and refreshes the
   associated `assistant_draft`.
7. Final response event seals the draft into `assistant_final`.

### Tool Events

Tool start/end callbacks become transcript entries instead of immediate console
prints. This prevents tool messages from corrupting assistant markdown flow.

### High-Risk Confirmation

When the agent sets `pending_confirmation`, the UI emits a
`confirmation_prompt` transcript item and temporarily repurposes the input pane
for option selection. This replaces the current secondary imperative printing
flow in the REPL.

## Migration Plan

### Phase 1. Introduce Renderer Adapter

- add `md2term` dependency
- implement adapter in `src/bourbon/repl/renderers.py`
- add focused tests for streaming code fences, links, tables, and lists

No UI architecture change yet.

### Phase 2. Add Transcript Buffer and UI Event Queue

- introduce transcript item models
- route tool and assistant events through a queue
- keep old prompt behavior while transcript rendering is introduced

### Phase 3. Move Streaming Output to `prompt_toolkit`

- build transcript pane in `prompt_toolkit`
- render assistant draft snapshots via adapter
- remove `Rich Live` from the assistant streaming path

### Phase 4. Remove Legacy Heuristics

- delete `stable_prefix/pending_tail` logic
- delete `StreamingDisplay`
- remove tests that encode heuristic-specific behavior
- retain only transcript and renderer behavior tests

## Testing Strategy

### Unit Tests

- renderer adapter incremental rendering behavior
- transcript buffer item lifecycle
- stream controller event normalization

### Integration Tests

- thinking to replying transition
- streamed assistant markdown remains single-source in transcript
- tool events render as distinct transcript entries
- pending confirmation enters confirmation mode cleanly
- `/exit`, `Ctrl+C`, empty input, and toolbar still work

### Regression Tests

- no duplicated final assistant response
- no raw ANSI clear sequences
- no product-owned markdown stability heuristics in the main path

## Risks

### Renderer Style Drift

`md2term` output may not visually match Rich Markdown exactly.

Mitigation:

- treat semantic correctness and streaming stability as the primary goal
- keep styling normalization inside the adapter if small adjustments are needed

### UI Complexity

Owning the full transcript in `prompt_toolkit` increases UI code complexity.

Mitigation:

- isolate UI layout from agent orchestration
- keep the renderer adapter independent and testable

### Migration Overlap

During migration, both old and new code paths may temporarily exist.

Mitigation:

- phase work so each step is independently testable
- remove the legacy streaming path as soon as the new transcript path is stable

## Success Criteria

The refactor is complete when all of the following are true:

- Bourbon streams assistant output in real time
- incremental markdown rendering no longer depends on Bourbon-specific closure
  heuristics
- `prompt_toolkit` is the only interactive terminal UI owner
- tool output and confirmation prompts no longer share the assistant body render
  path
- REPL regression tests cover the new transcript and renderer architecture
