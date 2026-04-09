# Bourbon User Confirmation Redesign

> **For agentic workers:** Before implementation, use `superpowers:writing-plans`. During implementation, use `superpowers:test-driven-development` and `superpowers:verification-before-completion`.

**Goal:** Replace Bourbon's current unusable secondary-confirmation flow with a Claude Code-inspired confirmation architecture that supports true suspend/resume, session-scoped approvals, and a unified confirmation protocol across all tools.

**Status:** Validated design for MVP

**Scope:** CLI/REPL flow, agent execution protocol, tool permission runtime, and session-scoped approval matching. This design does not include classifier automation, hooks, batch approvals, web UI, or persistent approval rules.

---

## Problem Summary

Bourbon's current confirmation behavior is centered on `Agent.pending_confirmation` and a REPL-side text menu. This causes several structural problems:

- Approval is not part of the tool execution protocol.
- A tool call cannot truly pause and resume in place.
- Approval is effectively turned into a new user message.
- Only one pending confirmation can exist at a time.
- Confirmation content is generic and not tool-aware.
- Session-level "always allow" behavior does not exist.

This is the main reason the current interaction feels broken instead of merely rough.

---

## MVP Decisions

The following decisions are fixed for this design:

- Use true suspend/resume semantics.
- Use Claude Code-style choices: `allow once`, `allow for session`, `reject`.
- Do not persist session approvals across process restarts or `resume_last`.
- Cover all tools through one unified protocol in the first version.
- Provide richer summaries for `Bash`, `Write`, and `Edit`; other tools use the generic fallback request.
- Keep existing hard denies and sandbox/audit integration intact.
- Do not add classifier, hooks, headless approval, or persistent rule storage in MVP.

---

## Architecture

The redesign introduces a dedicated permission runtime between policy evaluation and tool execution.

### Layers

1. Tool permission evaluation
2. Agent suspend/resume runtime
3. REPL confirmation UI

### Core Model

Tool execution no longer branches directly from `allow` to execution and from `need_approval` to a text prompt. Instead, every tool call first produces a normalized permission decision:

- `allow`
- `ask`
- `deny`

When the decision is `ask`, the agent creates a runtime permission request, suspends the current tool round, and waits for an explicit resolution. The original tool call remains live and is resumed directly after user approval.

---

## Runtime Types

The MVP should introduce explicit runtime types instead of overloading `PendingConfirmation`.

### `PermissionDecision`

Normalized result of permission evaluation:

- `allow`
- `ask`
- `deny`

`ask` should carry user-facing metadata, not just a raw reason string.

### `PermissionRequest`

Represents one pending confirmation:

- `request_id`
- `tool_use_id`
- `tool_name`
- `tool_input`
- `title`
- `description`
- `reason`
- `options`
- `match_candidate`

`match_candidate` is the tool-specific shape used if the user chooses `allow for session`.

### `SuspendedToolRound`

Represents one assistant tool round paused mid-execution:

- `source_assistant_uuid`
- `tool_use_blocks`
- `completed_results`
- `next_tool_index`
- `active_request`

This is the key object that makes true resume possible.

### `SessionPermissionStore`

In-memory approval store, scoped to the current running `Agent` instance only.

- It is not written to transcript state.
- It is not written to session metadata.
- It is not written to config.
- It is lost on restart and on `resume_last`.

This matches the desired Claude Code-like behavior.

---

## Permission Resolution Order

Permission resolution must follow a strict order so temporary session approvals never weaken the safety boundary.

1. Hard deny and invalid input checks
2. Session approval match
3. Existing access-control policy evaluation
4. Tool-specific request enrichment
5. Fallback request generation

Important constraints:

- `deny` always wins.
- Session approvals may bypass `ask`, but must never bypass `deny`.
- Existing `mandatory_deny`, file deny rules, and dangerous command deny rules remain authoritative.

---

## Tool Round Suspend/Resume Protocol

This is the most important behavior change in the entire design.

### Current Failure

Today, approval is effectively implemented as:

1. Tool asks for approval
2. Agent stores one `pending_confirmation`
3. REPL asks the user
4. User input is routed back through the general input loop

This loses the original tool round semantics.

### New Protocol

1. The model emits one assistant message with one or more `tool_use` blocks.
2. The assistant message is written to transcript immediately.
3. Agent begins executing the tool blocks in order.
4. When a tool produces `ask`, the agent creates `PermissionRequest` and `SuspendedToolRound`.
5. Execution pauses before the tool call is executed.
6. REPL renders the request and collects one of the three decisions.
7. The agent resumes the exact suspended tool round:
   - `allow once`: execute the paused tool call once
   - `allow for session`: store the match rule, then execute the paused tool call
   - `reject`: emit a `tool_result` error for that `tool_use`
8. The agent continues executing the remaining tools in the same round.
9. Only after all tool results are complete does the agent append the combined tool-result user message and continue the conversation loop.

This preserves Anthropic tool protocol correctness and matches the intended UX.

---

## REPL Behavior

The REPL should stop treating confirmations as ordinary chat input.

### New REPL Responsibilities

- Detect when the agent exposes an active `PermissionRequest`
- Render the request
- Offer exactly three options:
  - `1` = allow once
  - `2` = allow for session
  - `3` = reject
- Validate user input and retry on invalid choices
- Call a dedicated resume API on the agent

### REPL Non-Responsibilities

- Do not call `_process_input()` with the selected option text
- Do not synthesize fake user messages for approval
- Do not interpret confirmation decisions itself beyond collecting the choice

The REPL is only the presentation layer. The permission state machine lives in the agent/runtime layer.

---

## Session Approval Matching

`allow for session` should use tool-aware matching, not a raw string contains check.

### Matching Principles

- Matching must be narrower than "tool-wide allow everything"
- Matching should align with the semantics of the tool
- Matching should be stable enough to reduce repetitive prompts

### Tool-Specific Matching

#### `Bash`

Use normalized command prefixes or semantic patterns, for example:

- `pip install`
- `uv run pytest`
- `git push`

The matcher may optionally include normalized working-directory context if needed, but the MVP should prefer a simple stable prefix matcher.

#### `Write`

- New-file writes: match by target parent directory
- Overwrites: match by exact file path

This keeps repetitive file creation usable without silently allowing unrelated overwrites.

#### `Edit`

- Match by exact file path

Edits should stay narrower than writes, because session-allowing one edit should not silently authorize broad edits across a directory.

#### Other Tools

Use a fallback matcher derived from:

- canonical tool name
- selected key input fields

This ensures every tool can participate in the new confirmation runtime from day one.

---

## Request Presentation

MVP does not need a large component hierarchy, but it does need structured, tool-aware content.

### `Bash`

Show:

- command
- reason for asking
- whether the request comes from policy or tool-specific heuristics

### `Write`

Show:

- target path
- whether this creates a new file or overwrites an existing file
- short content summary, not full content dump

### `Edit`

Show:

- target path
- short replacement summary
- whether target text was found during preflight if such preflight is available

### Fallback

Show:

- tool name
- sanitized input summary
- reason for asking

The purpose is clarity, not a full Claude Code UI clone.

---

## Migration Strategy

The migration should minimize risk by replacing only the approval protocol first.

### Preserve

- existing deny behavior
- access-control policy engine
- audit logging
- sandbox execution behavior

### Replace

- `PendingConfirmation` single-slot model
- REPL recursive approval flow
- approval-via-chat-input behavior

### Suggested New Modules

- `src/bourbon/permissions/runtime.py`
- `src/bourbon/permissions/matching.py`
- `src/bourbon/permissions/presentation.py`

Exact file layout can change, but the runtime should be separated from REPL rendering and from access-control policy evaluation.

---

## Testing Strategy

Implementation should be driven by tests in this order.

### 1. Permission Runtime Unit Tests

Cover:

- normalized `allow / ask / deny`
- session approval matches
- session approval does not override `deny`
- fallback matcher behavior
- tool-specific matcher behavior for `Bash`, `Write`, and `Edit`

### 2. Agent Suspend/Resume Tests

Cover:

- tool round pauses on `ask`
- completed tool results are retained
- `allow once` resumes the exact pending tool call
- `allow for session` stores approval then resumes
- `reject` emits `tool_result(is_error=true)`
- remaining tools in the same round continue after resume
- combined tool results are appended once at the end of the round

### 3. REPL Interaction Tests

Cover:

- three-option rendering
- invalid choice retry
- dedicated resume path is used
- no recursive `_process_input()` call

### 4. Security Regression Tests

Keep and adapt:

- policy deny tests
- need-approval tests
- audit event tests
- sandbox execution tests

Existing security coverage should remain valid after the protocol rewrite.

---

## Non-Goals

The following items are intentionally excluded from MVP:

- persistent approval rules
- resume-safe session approval persistence
- classifier-based auto approval
- hooks
- headless approval delegation
- web UI
- batch approval UI
- full Claude Code component parity

These can be added later on top of the same runtime model.

---

## Recommended Implementation Sequence

1. Add permission runtime types and in-memory session approval store.
2. Refactor agent tool execution to support suspended tool rounds.
3. Replace REPL confirmation handling with a dedicated resume path.
4. Add tool-aware request summaries for `Bash`, `Write`, and `Edit`.
5. Adapt and expand tests.

This order isolates the protocol change before polishing the presentation.

---

## Success Criteria

The redesign is successful when all of the following are true:

- Approvals no longer re-enter the normal chat input path.
- A tool round can pause and resume without losing its original state.
- All tools use one unified confirmation protocol.
- Users can choose `allow once`, `allow for session`, or `reject`.
- Session approvals reduce repetitive prompts within the current process only.
- Existing deny and sandbox protections still work.
- The CLI confirmation flow feels predictable and usable instead of fragile.
