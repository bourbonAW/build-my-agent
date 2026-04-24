# Memory Write-Side Trust Rules Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend `TOOL_RESULT_TRUST` prompt section with a write-side clause that bans filesystem verification of memory writes, explains the mechanism, and redirects to `memory_search`. Also remove the stale `memory_read` tool reference.

**Architecture:** Single-file prompt edit in `src/bourbon/prompt/sections.py` plus four assertion tests in `tests/test_agent_error_policy.py`. No tool changes, no subsystem changes. TDD cycle.

**Tech Stack:** Python, pytest, Bourbon prompt builder, existing `mock_agent` fixture.

**Spec:** `docs/superpowers/specs/2026-04-24-memory-trust-writeside-design.md`

---

## File Structure

Files touched:

- **Modify:** `src/bourbon/prompt/sections.py` — update the `content=` string of `TOOL_RESULT_TRUST` (lines 95-108). One section, no reordering, no renaming.
- **Modify:** `tests/test_agent_error_policy.py` — append three new test methods inside the existing `TestErrorHandlingPolicy` class. Reuse the existing `mock_agent` fixture.

No new files. No deletions.

---

## Task 1: Add Write-Side Trust Rule to TOOL_RESULT_TRUST

**Files:**
- Modify: `src/bourbon/prompt/sections.py:92-108`
- Test: `tests/test_agent_error_policy.py` (append to `TestErrorHandlingPolicy` class)

### - [ ] Step 1: Write the failing tests

Open `tests/test_agent_error_policy.py` and append the following methods at the end of the `TestErrorHandlingPolicy` class (after the last existing `test_*` method). Keep them inside the class — they need the `mock_agent` fixture.

```python
    def test_memory_write_operations_rule_exists(self, mock_agent):
        """System prompt must tell the agent not to bash-verify memory writes."""
        prompt = mock_agent.system_prompt
        assert "memory_write" in prompt
        assert "memory_promote" in prompt
        assert "memory_archive" in prompt
        assert "not observable in the current session" in prompt

    def test_memory_read_stale_reference_removed(self, mock_agent):
        """memory_read tool does not exist; its reference must not leak into prompt."""
        assert "memory_read" not in mock_agent.system_prompt

    def test_memory_search_stays_in_trust_rules(self, mock_agent):
        """Guard against accidental over-deletion while fixing the stale reference."""
        prompt = mock_agent.system_prompt
        assert "TRUSTING TOOL RESULTS" in prompt
        assert "memory_search" in prompt

    def test_memory_write_requery_rule_names_status_filters(self, mock_agent):
        """Re-query guidance must account for non-active memory statuses."""
        prompt = mock_agent.system_prompt
        assert "status=['promoted']" in prompt
        assert "status=['stale']" in prompt
        assert "status=['rejected']" in prompt
```

### - [ ] Step 2: Run tests to verify they fail

Run:

```bash
uv run pytest tests/test_agent_error_policy.py::TestErrorHandlingPolicy::test_memory_write_operations_rule_exists tests/test_agent_error_policy.py::TestErrorHandlingPolicy::test_memory_read_stale_reference_removed tests/test_agent_error_policy.py::TestErrorHandlingPolicy::test_memory_search_stays_in_trust_rules tests/test_agent_error_policy.py::TestErrorHandlingPolicy::test_memory_write_requery_rule_names_status_filters -v
```

Expected:
- `test_memory_write_operations_rule_exists` — **FAIL** (no `memory_write`/`memory_promote`/`memory_archive`/`not observable in the current session` text present yet).
- `test_memory_read_stale_reference_removed` — **FAIL** (current prompt still contains `memory_read`).
- `test_memory_search_stays_in_trust_rules` — **PASS** (already true before the edit). This one is a guard rail, passing pre-change is expected.
- `test_memory_write_requery_rule_names_status_filters` — **FAIL** (no explicit promoted/stale/rejected status filter guidance present yet).

If any result differs from the above, stop and investigate — your baseline is not what the plan assumes.

### - [ ] Step 3: Update the prompt section

Edit `src/bourbon/prompt/sections.py`. Replace the `content=` tuple of `TOOL_RESULT_TRUST` (lines 95-108) so the whole section reads:

```python
TOOL_RESULT_TRUST = PromptSection(
    name="tool_result_trust",
    order=35,
    content=(
        "TRUSTING TOOL RESULTS:\n"
        "- Internal read-side tools (memory_search, memory_status, TaskList, "
        "TodoRead) are AUTHORITATIVE for their domain. If memory_search returns "
        "an empty result, memory IS empty — do NOT fall back to Bash/Glob to "
        "search the filesystem for 'memory files' to verify.\n"
        "- Memory write operations (memory_write, memory_promote, memory_archive) "
        "modify on-disk state that is NOT observable in the current session. "
        "Promoted memories take effect in the next conversation's system prompt. "
        "Treat a success status as conclusive. Do NOT use Bash/Read/find to "
        "inspect USER.md, MEMORY.md, or memory files. If you need to re-query "
        "memory state, call memory_search with the status matching the operation: "
        "status=['promoted'] after memory_promote; status=['stale'] or "
        "status=['rejected'] after memory_archive — never the filesystem.\n"
        "- If an authoritative tool's empty or negative result is surprising, "
        "state that to the user and ask for clarification. Do not run ad-hoc "
        "filesystem searches to double-check.\n"
        "- Do not call the same tool more than twice in a row with only "
        "parameter variations (e.g., broader glob, deeper find, different "
        "--maxdepth). If two attempts have not yielded the answer, switch "
        "approach or ask the user — continued retrying is almost never useful."
    ),
)
```

Diff summary:
1. First bullet: `Internal tools` → `Internal read-side tools`; drop `memory_read,` from the list.
2. Insert a new second bullet (the write-side clause).
3. Third and fourth bullets unchanged.

### - [ ] Step 4: Run the three targeted tests to verify they pass

```bash
uv run pytest tests/test_agent_error_policy.py::TestErrorHandlingPolicy::test_memory_write_operations_rule_exists tests/test_agent_error_policy.py::TestErrorHandlingPolicy::test_memory_read_stale_reference_removed tests/test_agent_error_policy.py::TestErrorHandlingPolicy::test_memory_search_stays_in_trust_rules tests/test_agent_error_policy.py::TestErrorHandlingPolicy::test_memory_write_requery_rule_names_status_filters -v
```

Expected: all 3 PASS.

### - [ ] Step 5: Run the full error-policy file for regression

```bash
uv run pytest tests/test_agent_error_policy.py -v
```

Expected: all tests PASS (the file has several other `test_*_section_exists` / `test_*_policy_exists` methods that should be unaffected by our edit).

### - [ ] Step 6: Lint the touched files

```bash
uv run ruff check src/bourbon/prompt/sections.py tests/test_agent_error_policy.py
```

Expected: `All checks passed!`

If ruff reports issues, fix them inline (usually unused imports or line length) and re-run.

### - [ ] Step 7: Broader regression check

```bash
uv run pytest tests/ -q --ignore=tests/test_sandbox_docker.py --ignore=tests/test_sandbox_bwrap.py --ignore=tests/test_sandbox_seatbelt.py
```

Expected: same pass/fail count as before this change. (Baseline on this branch currently has 4 pre-existing unrelated failures in `test_agent_permission_runtime.py` and `test_agent_security_integration.py` caused by a missing `_tracer` attribute — do not attribute these to your change. Confirm by diffing pytest output against pre-change baseline; the only new passes should be the three new assertions.)

### - [ ] Step 8: Commit

```bash
git add src/bourbon/prompt/sections.py tests/test_agent_error_policy.py docs/superpowers/specs/2026-04-24-memory-trust-writeside-design.md docs/superpowers/plans/2026-04-24-memory-trust-writeside.md
git commit -m "$(cat <<'EOF'
Tighten memory write-side trust rules in system prompt

Extend TOOL_RESULT_TRUST with a clause covering memory_write,
memory_promote, and memory_archive: success status is conclusive,
filesystem inspection of USER.md/MEMORY.md is banned, and re-querying
should go through memory_search. Also remove the stale memory_read
reference (that tool does not exist in bourbon.tools.memory).
EOF
)"
```

Expected: commit succeeds; `git status` is clean for the edited files.

---

## Self-Review Checklist

### Spec coverage

- Spec § Changes — ✅ Task 1 Step 3 makes the exact three edits: replace `memory_read` reference, insert write-side clause, leave other clauses untouched.
- Spec § Final Text — ✅ Task 1 Step 3's code block reproduces the approved wording verbatim.
- Spec § Testing — ✅ Task 1 Step 1 adds all prompt guard tests with the exact assertions from the spec.
- Spec § Out of Scope — ✅ Plan does not modify any tool, subsystem, or return JSON.

### Placeholder scan

- No `TBD` / `TODO` / `implement later`.
- No vague "handle edge cases" / "add validation".
- All code shown verbatim (full section block + full test methods).
- All commands shown with explicit expected output.

### Type consistency

- Section uses `PromptSection(name=..., order=..., content=...)` — matches the existing signature (unchanged).
- Test methods use the `mock_agent` fixture and `mock_agent.system_prompt` attribute — same pattern as every existing test in the class.
- No function / type names are introduced that aren't already present.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-24-memory-trust-writeside.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent for Task 1, review the result, then final approval. Clean isolation, explicit review checkpoint.

**2. Inline Execution** — I execute all 8 steps in this session with you watching. Faster feedback, but shares context with the brainstorm conversation.

For a single-task plan this narrow, inline is perfectly reasonable. Subagent-driven is overkill unless you want the isolation practice.

Which approach?
