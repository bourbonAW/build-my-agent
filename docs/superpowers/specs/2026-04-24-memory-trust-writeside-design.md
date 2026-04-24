# Memory Write-Side Trust Rules

**Date:** 2026-04-24
**Status:** Approved for implementation
**Scope:** Narrow — one prompt section, no tool / no subsystem changes

## Problem

After calling `memory_promote`, the model immediately tries `bash` / `find` / `Read` to locate `USER.md` and confirm the promotion took effect. This is a three-layer failure:

1. **Prompt gap.** The existing `TOOL_RESULT_TRUST` section (`src/bourbon/prompt/sections.py:92-109`) only covers read-side tools. The rule "don't fall back to Bash/Glob to verify" applies to `memory_search` returning empty — it says nothing about write-side operations.
2. **Return-value gap.** `memory_promote` returns `{"id": ..., "status": "promoted"}` with no guidance telling the model that the operation is done and its effects are not observable mid-session.
3. **Observability gap.** Even if the model wants to verify legitimately, there is no tool that shows "what is currently in `USER.md` managed block".

The narrow fix addresses layer 1 only; layers 2 and 3 are deliberately out of scope.

## Current State Bug

`TOOL_RESULT_TRUST` lists `memory_read` as an authoritative read-side tool. `memory_read` does not exist in `src/bourbon/tools/memory.py`. This stale reference is removed as part of the same edit.

## Design

### Changes

Single file: `src/bourbon/prompt/sections.py`. Modify the `content=` string of `TOOL_RESULT_TRUST`:

- Replace the `memory_read` reference with the accurate list `memory_search, memory_status`.
- Insert a new write-side clause between the existing read-side clause and the "surprising empty result" clause.
- Leave the remaining two clauses unchanged.
- Do not change `name`, `order`, or section position.

### Final Text

```
TRUSTING TOOL RESULTS:
- Internal read-side tools (memory_search, memory_status, TaskList, TodoRead)
  are AUTHORITATIVE for their domain. If memory_search returns an empty
  result, memory IS empty — do NOT fall back to Bash/Glob to search the
  filesystem for "memory files" to verify.
- Memory write operations (memory_write, memory_promote, memory_archive)
  modify on-disk state that is NOT observable in the current session.
  Promoted memories take effect in the next conversation's system prompt.
  Treat a success status as conclusive. Do NOT use Bash/Read/find to inspect
  USER.md, MEMORY.md, or memory files. If you need to re-query memory state,
  call memory_search — never the filesystem.
- If an authoritative tool's empty or negative result is surprising, state
  that to the user and ask for clarification. Do not run ad-hoc filesystem
  searches to double-check.
- Do not call the same tool more than twice in a row with only parameter
  variations (e.g., broader glob, deeper find, different --maxdepth). If
  two attempts have not yielded the answer, switch approach or ask the
  user — continued retrying is almost never useful.
```

### Rationale

The new clause uses a recommendation-grade pattern — ban + mechanism + legal alternative:

- **Ban:** "Do NOT use Bash/Read/find to inspect `USER.md`, `MEMORY.md`, or memory files."
- **Mechanism:** "…modify on-disk state that is NOT observable in the current session. Promoted memories take effect in the next conversation's system prompt." The model can reason about edge cases instead of blindly following.
- **Legal alternative:** "If you need to re-query memory state, call `memory_search` — never the filesystem." Redirects the "I just want to check" instinct toward a sanctioned tool.

`memory_search` already supports filtering by `scope='user'` and `status='promoted'`, so it is sufficient for the ~90% "did my write land" case without any new tool.

## Testing

Add three assertions to `tests/test_agent_error_policy.py`, following the existing `test_*_section_exists` pattern:

1. `test_memory_write_operations_rule_exists` — assert that `memory_write`, `memory_promote`, and `not observable in the current session` all appear in the rendered `system_prompt`.
2. `test_memory_read_stale_reference_removed` — assert that the substring `memory_read` is absent from `system_prompt`.
3. `test_memory_search_stays_in_trust_rules` — assert that both `TRUSTING TOOL RESULTS` and `memory_search` appear in `system_prompt` (guards against accidental over-deletion while removing the stale `memory_read` reference).

No changes to existing tests are required. No implementation-code tests are added (there is no implementation code change).

## Out of Scope

The following are explicitly **not** addressed by this spec:

- Modifying any memory tool's `description` or return JSON (e.g., adding a `hint` field on `memory_promote` response).
- Adding a `memory_inspect` tool or expanding `memory_status` to return promoted-record listings.
- Refactoring the memory subsystem, changing `MemoryManager` / `MemoryStore` behavior, or altering `USER.md` rendering.
- Modifying read-side rules beyond fixing the `memory_read` stale reference.

If post-deployment observation shows the prompt-only fix is insufficient, the write-side return-value hint (layer 2) and observability channel (layer 3) can be designed separately.

## Risks

- **Prompt drift:** The section is now ~330 tokens (up from ~180). Marginal cost acceptable; still far under any section-budget concern.
- **Over-specification:** Listing three specific memory tools (`memory_write / memory_promote / memory_archive`) couples the prompt to tool names. If any are renamed, this string must update. Mitigation: the three test assertions will fail if references drift.
- **Model ignoring the rule anyway:** Possible. If observed in practice, escalate scope to layers 2 / 3.

## Implementation Estimate

- 1 file edited (`src/bourbon/prompt/sections.py`)
- 3 test cases added (`tests/test_agent_error_policy.py`)
- ~15 minutes implementation + verification
