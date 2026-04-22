# Bourbon Memory Phase 2 Design: MemoryPromote & MemoryArchive

**Date**: 2026-04-22  
**Status**: Draft  
**Scope**: Phase 2 of the bourbon memory system — centered on `memory_promote` and `memory_archive`, with the minimum prompt/render/search changes needed to manage promoted records. SQLite FTS deferred to Phase 3.

---

## 1. Background & Motivation

Phase 1 delivered `memory_write`, `memory_search`, and `memory_status`. Records are stored as individual `.md` files under `~/.bourbon/projects/{key}/memory/`, indexed by `MEMORY.md`.

The critical limitation Phase 1 left open: **only the MEMORY.md index (one-line summaries) is injected into the system prompt**, not the full content of each memory record. This means behavioral preferences like "always use uv" are injected as a weak one-liner, and the agent may not enforce them reliably.

Phase 1 spec explicitly deferred the solution: `MemoryPromote → MEMORY.md / USER.md` would be Phase 2.

**Phase 2 goal**: give the agent a path to promote stable cross-project user preferences from the index-only layer into global `USER.md`, where promoted blocks are rendered first within the existing `USER.md` prompt budget so they are reliably injected.

---

## 2. Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Phase 2 scope | MemoryPromote + MemoryArchive only | SQLite FTS not needed at current memory volume |
| User confirmation | None — agent auto-promotes | Simplest UX; agent knows when a preference is stable |
| Promotion target | `USER.md` managed section | Stronger prompt injection than the one-line MEMORY.md index |
| Trigger mechanism | Agent proactive tool call | No background infrastructure needed; LLM judges timing |
| Source file after promote | Kept on disk, status → `promoted` | Audit trail preserved |
| Duplicate injection | Prevented via `promoted` status | Promoted records exit MEMORY.md index |
| USER.md render contract | Promoted managed blocks are a separate global layer rendered before merged freeform USER.md content, with reserved token budget | Prevent promoted preferences from being truncated out of the prompt; Phase 1 heading merge still applies to human-authored USER.md content only |
| Promote eligibility | `user` / `feedback` kinds with `scope=user` only | Phase 2 writes only to global `~/.bourbon/USER.md`, so project/session-scoped memories must remain index-only |
| Promoted discoverability | Promoted records remain searchable via `memory_search(status=["promoted"])` | Records excluded from MEMORY.md still need a deterministic recovery path for archive/review |
| Archive vs Reject naming | Tool named `memory_archive` (status ∈ {stale, rejected}) | Neutral name avoids semantic mismatch with temporary stale state |

---

## 3. Architecture

Phase 2 adds no new modules. It extends the existing memory/prompt/tool files below:

```
src/bourbon/memory/
  models.py    ← add MemoryStatus.PROMOTED
  files.py     ← add USER.md managed section parse / upsert / block-status update / merged render
  store.py     ← add update_status() and _rebuild_index()
  manager.py   ← add promote() / archive() coordination and manager-level permission checks
  policy.py    ← add check_promote_permission() / check_archive_permission()
  prompt.py    ← use merged USER.md renderer with managed-first budgeting

src/bourbon/tools/
  memory.py    ← register memory_promote and memory_archive tools
  __init__.py  ← ensure imports for new tools
```

### Data Flow

```
User expresses preference
  ↓
LLM calls memory_write → source file status=active → MEMORY.md index (weak, one-liner)
  ↓  (later, LLM judges preference is stable)
LLM calls memory_promote(memory_id)
  ↓
  ├─ manager: validate actor + kind + scope (user/feedback + scope=user only)
  ├─ files: global USER.md managed block upsert    (managed-first injection path)
  └─ store: source file status: active|stale → promoted  + rebuild MEMORY.md index
  ↓  (if preference becomes invalid or temporarily suspended)
LLM calls memory_archive(memory_id, status="stale"|"rejected")
  ↓
  ├─ files: if previously promoted, update USER.md block status
  └─ store: source file status → stale/rejected + rebuild MEMORY.md index
```

---

## 4. Data Model

### 4.1 New `MemoryStatus.PROMOTED`

```python
class MemoryStatus(StrEnum):
    ACTIVE   = "active"
    STALE    = "stale"
    REJECTED = "rejected"
    PROMOTED = "promoted"   # NEW in Phase 2
```

### 4.2 Status × Injection Layer Matrix

| status | Disk file | MEMORY.md index | USER.md managed section |
|---|---|---|---|
| `active` | ✅ kept | ✅ appears | ❌ |
| `promoted` | ✅ kept (audit) | ❌ excluded | ✅ injected from managed block (subject to USER.md budget) |
| `stale` | ✅ kept | ❌ | ❌ |
| `rejected` | ✅ kept | ❌ | ❌ (block marked rejected if was promoted) |

### 4.3 Promoted Record Discoverability

Promoted records are intentionally removed from `MEMORY.md` to avoid duplicate prompt injection, but they must remain manageable after promotion.

- `memory_search` continues to default to `status=["active"]` for backward compatibility.
- Phase 2 extends `memory_search` so callers may explicitly pass `status`, including `["promoted"]`, `["stale"]`, and `["rejected"]`.
- Agents that need to revisit or archive a promoted memory whose `memory_id` is no longer in the prompt should first call `memory_search(status=["promoted"], ...)`.

---

## 5. USER.md Managed Section

Bourbon writes a machine-readable managed section in `~/.bourbon/USER.md` only. `{workdir}/USER.md` remains fully user-managed and is never mutated by Phase 2.

### 5.1 Format

```markdown
<!-- User's own handwritten preferences above — never modified by Bourbon -->

<!-- bourbon-managed:start section="preferences" -->
## Bourbon Managed Preferences

> Managed by Bourbon. Marker lines must be preserved. Manual edits inside a block may be overwritten the next time Bourbon upserts that same memory.

<!-- bourbon-memory:start id="mem_b4c2c06f" -->
### User Preference: mem_b4c2c06f

- status: promoted
- kind: user
- promoted_at: 2026-04-22T10:00:00Z
- note: Confirmed across 5+ turns; user consistently prefers uv over pip

用户已全面拥抱 uv 工具，要求所有 Python 生态相关操作都通过 uv 执行，不再直接使用 python/pip 等命令。
<!-- bourbon-memory:end id="mem_b4c2c06f" -->
<!-- bourbon-managed:end section="preferences" -->
```

### 5.2 Mutation Rules

- **Upsert**: if `id` not in managed section → append new block; if already present → replace block in place (start..end).
- **Update block status**: `memory_archive` updates `status:` inside the block to `stale` or `rejected`. Blocks are not deleted (audit trail).
- **User edits**: content outside `<!-- bourbon-managed:start/end -->` is never rewritten.
- **Edits inside a managed block**: allowed, but not preserved on the next `memory_promote` for the same `memory_id`; upsert rewrites the full block body and metadata together.
- **Section creation**: if the managed section wrapper does not exist, `memory_promote` creates it at the end of `~/.bourbon/USER.md`.
- **File creation**: if `~/.bourbon/USER.md` does not exist, it is created with just the managed section.
- **Content length guard**: if a memory record body exceeds 150 tokens, `upsert_managed_block` stores a truncated summary (≤150 tokens) plus a backlink to the source file (`Source: ~/.bourbon/projects/{key}/memory/{filename}`) instead of the full body. This prevents a single long-form memory from consuming the entire USER.md budget.

### 5.3 Prompt Injection

Phase 1's merge contract remains intact for **human-authored** USER.md content: global `~/.bourbon/USER.md` and project-local `{workdir}/USER.md` are still merged by heading, with project-local content winning on conflicts inside that human-authored layer.

Phase 2 intentionally treats promoted managed blocks as a separate global prompt layer so they are not lost to prefix truncation:

1. Read `~/.bourbon/USER.md` and extract the Bourbon-managed section by `<!-- bourbon-managed:start/end -->`.
2. Keep only managed blocks with `status: promoted`. Blocks with `status: stale` or `status: rejected` are excluded from prompt injection.
3. Remove the managed section from the global file text, then pass the remaining user-authored global content into the existing `merge_user_md(global, project)` flow with `{workdir}/USER.md`.
4. Render the managed section first, with a reserved budget of `min(300, user_md_token_limit // 2)` tokens. If there are no promoted blocks, the full budget remains available to user-authored content.
5. **Budget overflow handling**: if promoted blocks exceed the reserved budget, render them ordered by `promoted_at` descending (newest first) and truncate at the budget boundary. Older promoted blocks remain in `USER.md` on disk but are omitted from the current prompt. They are eligible for reinjection in future turns if newer blocks are archived and free up budget.
6. Render the merged user-authored content with the remaining budget.
7. Final output order is: promoted managed section first, then merged user-authored content.

This preserves Phase 1 merge semantics for handwritten USER.md content while making promoted preferences reliably injectable. It does **not** give project-local `USER.md` a way to suppress a promoted global managed block in Phase 2; project-specific exceptions remain out of scope for this phase.

---

## 6. Implementation Details

### 6.1 `models.py` — Add PROMOTED status

Add `PROMOTED = "promoted"` to `MemoryStatus`. No other model changes needed.

### 6.2 `files.py` — Managed section operations

Add three public functions:

```python
def upsert_managed_block(user_md_path: Path, record: MemoryRecord, note: str = "") -> None:
    """Insert or replace a bourbon-managed block in USER.md."""

def update_managed_block_status(
    user_md_path: Path,
    memory_id: str,
    status: Literal["promoted", "stale", "rejected"],
) -> None:
    """Update status field inside an existing managed block."""

def render_merged_user_md_for_prompt(
    global_path: Path | None,
    project_path: Path | None,
    token_limit: int,
) -> str:
    """Render USER.md for prompt injection with managed-first budgeting."""
```

Parser uses the outer wrapper `<!-- bourbon-managed:start/end -->` to isolate the global managed section, and regex on `<!-- bourbon-memory:start id="mem_XXXX" -->` / `<!-- bourbon-memory:end id="mem_XXXX" -->` to isolate individual blocks by `id`.

`render_merged_user_md_for_prompt()` replaces the current `merge_user_md()` + `_truncate_to_tokens()` path for USER.md in `memory_anchors_section()`. It:

- extracts promoted blocks from global `USER.md`,
- filters out blocks whose status is not `promoted`,
- strips the managed section before calling `merge_user_md()`,
- renders managed content first with reserved budget,
- renders merged human-authored content second with the remaining budget.

### 6.3 `store.py` — `update_status()` and index exclusion

```python
def update_status(self, memory_id: str, status: MemoryStatus) -> MemoryRecord:
    """Load record, rewrite status/updated_at, atomic-write back, then rebuild MEMORY.md."""

def _rebuild_index(self) -> bool:
    """Rewrite MEMORY.md from all active records only, preserving the 200-line cap."""
```

`_rebuild_index()` is new in Phase 2. It rewrites `MEMORY.md` from all `status=active` records only, sorted by `updated_at` descending (most recently updated first) and truncated to the 200-line cap. This ensures the index always surfaces the most relevant active memories while maintaining a bounded size. `promoted`, `stale`, and `rejected` records are excluded. The line format stays unchanged.

`write()` may keep Phase 1's incremental `update_index()` fast path. `update_status()` must call `_rebuild_index()` because status transitions remove entries from the index.

### 6.4 `manager.py` — `promote()` and `archive()`

```python
def promote(self, memory_id: str, actor: MemoryActor, note: str = "") -> MemoryRecord:
    record = self._store.read_record(memory_id)
    if record is None:
        raise KeyError(f"Unknown memory id: {memory_id}")
    if record.kind not in {MemoryKind.USER, MemoryKind.FEEDBACK}:
        raise ValueError(f"Cannot promote memory kind {record.kind}")
    if record.scope != MemoryScope.USER:
        raise ValueError("Only user-scope records can be promoted to global USER.md")
    if record.status not in {MemoryStatus.ACTIVE, MemoryStatus.STALE}:
        raise ValueError(f"Cannot promote record with status {record.status}")
    check_promote_permission(actor, record)
    global_user_md = Path("~/.bourbon/USER.md").expanduser()
    upsert_managed_block(
        global_user_md,
        replace(record, status=MemoryStatus.PROMOTED),
        note=note,
    )
    updated = self._store.update_status(memory_id, MemoryStatus.PROMOTED)
    self._record_audit(EventType.MEMORY_PROMOTE, tool_input_summary=record.name, ...)
    return updated

def archive(self, memory_id: str, status: MemoryStatus, actor: MemoryActor, reason: str = "") -> MemoryRecord:
    record = self._store.read_record(memory_id)
    if record is None:
        raise KeyError(f"Unknown memory id: {memory_id}")
    check_archive_permission(actor, record)
    was_promoted = record.status == MemoryStatus.PROMOTED
    if was_promoted:
        global_user_md = Path("~/.bourbon/USER.md").expanduser()
        update_managed_block_status(global_user_md, memory_id, str(status))
    updated = self._store.update_status(memory_id, status)
    self._record_audit(EventType.MEMORY_REJECT, tool_input_summary=record.name, ...)
    return updated
```

Ordering is intentional:

- `promote()` writes `USER.md` first, then updates the source record status and rebuilds `MEMORY.md`.
- `archive()` updates `USER.md` first only when the record was previously promoted; non-promoted records go straight through store status update.

This guarantees that a promoted preference is never considered successful unless it already exists in the USER.md injection path.

### 6.5 `memory.py` — Tool registration

**`memory_promote`**

```python
@register_tool(
    name="memory_promote",
    description=(
        "Promote a promotable memory record to USER.md for strong behavioral enforcement. "
        "Call this when a user/feedback memory with scope='user' has proven stable across multiple turns — "
        "e.g., a tool preference, output format, or workflow rule the user consistently expects. "
        "After promotion: the record exits the MEMORY.md index; its managed block is rendered "
        "before freeform USER.md content in future prompts. "
        "Only promote records with kind in {'user', 'feedback'}, scope='user', "
        "and status in {'active', 'stale'}."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "memory_id": {"type": "string", "description": "ID of the record to promote, e.g. 'mem_b4c2c06f'"},
            "note": {"type": "string", "description": "Optional reason for promoting"},
        },
        "required": ["memory_id"],
    },
    risk_level=RiskLevel.MEDIUM,
    required_capabilities=["file_write"],
)
```

**`memory_archive`**

```python
@register_tool(
    name="memory_archive",
    description=(
        "Archive a memory record by marking it stale or rejected. "
        "If the record was previously promoted to USER.md, also updates the managed block "
        "status so it is removed from prompt injection. "
        "Use 'rejected' for incorrect or outdated facts; 'stale' for temporarily suspended preferences."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "memory_id": {"type": "string"},
            "status": {"type": "string", "enum": ["rejected", "stale"]},
            "reason": {"type": "string"},
        },
        "required": ["memory_id", "status"],
    },
    risk_level=RiskLevel.MEDIUM,
    required_capabilities=["file_write"],
)
```

**Loading policy**: both tools are always-loaded alongside Phase 1 tools. Add imports to `tools/__init__.py` `_ensure_imports()`.

**`memory_search` adjustment**

Phase 2 also extends the existing `memory_search` tool schema to expose the store's `status` filter:

```python
"status": {
    "type": "array",
    "items": {"type": "string", "enum": ["active", "promoted", "stale", "rejected"]},
    "description": "Optional status filter. Defaults to ['active'] when omitted.",
}
```

This keeps promoted records discoverable for later review and archival without reintroducing them into `MEMORY.md`.

---

## 7. Error Handling

| Scenario | Behavior |
|---|---|
| `memory_promote` on `rejected` or already `promoted` record | Raise `ValueError` with clear message; tool returns error string |
| `memory_promote` on unknown id | `read_record()` returns `None`; manager raises `KeyError`; tool returns error string |
| `memory_promote` on `project` / `reference` record | Raise `ValueError`; tool returns error string |
| `memory_promote` on non-`user` scope record | Raise `ValueError`; tool returns error string |
| USER.md write failure (permissions) | Raise `OSError`; tool returns error; source file status is not changed |
| `memory_archive` on non-promoted record | Update store status only; skip USER.md mutation silently |
| `memory_archive(status="stale")` on promoted record | Managed block status becomes `stale`; block remains on disk but is excluded from prompt injection |
| Corrupt managed section (unpaired markers) | If `start` exists without `end`, parser closes the section at end-of-file before appending the new block. If `end` exists without `start`, parser ignores the orphaned marker and appends a new well-formed section. Always logs warning. |

**Atomicity**:

- `promote()` writes global `USER.md` first, then updates the source file status and rebuilds `MEMORY.md`.
- `archive()` writes global `USER.md` first only for previously promoted records, then updates the source file status and rebuilds `MEMORY.md`.
- If the `USER.md` mutation fails, the source file status is unchanged.
- If the store write fails after the `USER.md` mutation succeeds, the managed block may already reflect the desired state while the source file does not. Retry is idempotent because managed blocks are keyed by `memory_id`, and the subsequent successful store update will reconcile `MEMORY.md`.

---

## 8. Access Control

- `memory_promote` and `memory_archive` require `file_write` capability.
- Tool capability metadata is not sufficient by itself. `MemoryManager.promote()` and `MemoryManager.archive()` must enforce manager-level permission checks via `check_promote_permission()` / `check_archive_permission()`.
- Subagents cannot promote or archive records in Phase 2.
- `memory_search` remains readable by the same actors as Phase 1, including explicit status filters for promoted/stale/rejected records.
- Main agent, user actor, and system actor may promote only `user` / `feedback` records with `scope=user` and status in `{active, stale}`.
- Main agent, user actor, and system actor may archive any record they can already read.

No new capability types needed.

---

## 9. Testing

### Unit tests (`tests/test_memory_phase2.py`)

**Managed section operations (`files.py`):**
- `upsert_managed_block` on empty file → creates file with section and block
- `upsert_managed_block` on existing block → replaces in place, no duplicate
- `update_managed_block_status(..., status="rejected")` → updates status field, block remains
- `update_managed_block_status(..., status="stale")` → updates status field, block remains
- `render_merged_user_md_for_prompt` → excludes non-`promoted` blocks, preserves project-local USER.md merge semantics for human-authored content
- Long handwritten `USER.md` content does not truncate promoted blocks out of the prompt
- User content outside managed section wrapper is never modified by any operation
- Manual edits inside a managed block are overwritten on the next upsert for that `memory_id`
- Missing `end` marker (corrupt file) → append fallback, warning logged

**Status transitions (`store.py`):**
- `update_status` → frontmatter rewritten, all other fields preserved
- `update_status(..., promoted)` triggers `_rebuild_index()` and removes the record from MEMORY.md
- MEMORY.md index excludes `promoted` records
- MEMORY.md index excludes `stale` and `rejected` records (regression)
- `memory_search(status=["promoted"])` returns promoted records excluded from MEMORY.md

**Manager coordination (`manager.py`):**
- `promote()` happy path → store status=promoted, USER.md block present
- `promote()` on `stale` record → store status=promoted, USER.md block updated in place
- `promote()` on `rejected` or already `promoted` record → raises ValueError, no file modified
- `promote()` on `project` / `reference` record → raises ValueError, no file modified
- `promote()` on non-`user` scope record → raises ValueError, no file modified
- `promote()` from subagent actor → raises PermissionError
- `promote()` USER.md write fails → source file status remains unchanged
- `archive()` on active record → store updated, USER.md not touched
- `archive()` on promoted record with `status="rejected"` → store updated, USER.md block marked rejected
- `archive()` on promoted record with `status="stale"` → store updated, USER.md block marked stale

**Tool handlers (`memory.py`):**
- `memory_promote` tool call → returns success with file path
- `memory_promote` unknown id → returns error string, no crash
- `memory_promote` on invalid kind → returns error string
- `memory_promote` on non-`user` scope → returns error string
- `memory_archive` tool call → returns success
- `memory_search(status=["promoted"])` tool call → returns promoted records

### Integration test

- Full lifecycle: `memory_write` → `memory_promote` → check USER.md managed-first injection → `memory_archive` → check USER.md block marked rejected/stale, not injected.
- Global managed section renders ahead of project-local USER.md content; project-local heading merge still applies to handwritten USER.md content.
- Multiple promoted blocks competing for reserved budget: verify `promoted_at` descending order and graceful truncation of older blocks.
- Re-promote a previously archived (`stale`) record: verify USER.md block is resurrected with `status: promoted` and no duplicates.
- Promote a record with body >150 tokens: verify stored block contains truncated summary + backlink, not full body.
- Promoted record omitted from the current prompt due to budget overflow can still be found via `memory_search(status=["promoted"])`.
- Empty or missing global `USER.md`: verify file creation and correct rendering with project-local `USER.md`.

---

## 10. What Phase 2 Does NOT Include

- SQLite FTS search index (deferred to Phase 3)
- Background/automatic promote (agent decides proactively via tool call)
- Project-scope managed USER.md writes (only `~/.bourbon/USER.md` global for now; `{workdir}/USER.md` remains manual-only)
- `MemoryPromote` for `project`/`reference` kind records — the primary use case is `user` and `feedback` kinds; `project`/`reference` records are better kept in the index
- Promotion of `scope=project` or `scope=session` memories into global `USER.md`
- Project-local suppression/override of promoted global managed blocks
- UI or `/memory` command changes
- **Demote tool** (`promoted` → `active`): No direct path to demote a promoted record back to the MEMORY.md index without going through `memory_archive(status="stale")`. If needed, users can archive the old record and re-write a new one.

---

## 11. File Change Summary

| File | Change type | Description |
|---|---|---|
| `src/bourbon/memory/models.py` | Modify | Add `MemoryStatus.PROMOTED` |
| `src/bourbon/memory/files.py` | Modify | Add managed section upsert/status-update helpers and merged USER.md prompt renderer |
| `src/bourbon/memory/store.py` | Modify | Add `update_status()` and `_rebuild_index()` to remove non-active records from MEMORY.md |
| `src/bourbon/memory/manager.py` | Modify | Add `promote()` / `archive()` with explicit ordering and audit integration |
| `src/bourbon/memory/policy.py` | Modify | Add manager-level permission checks for promote/archive |
| `src/bourbon/memory/prompt.py` | Modify | Use `render_merged_user_md_for_prompt()` for USER.md |
| `src/bourbon/tools/memory.py` | Modify | Register `memory_promote` and `memory_archive` tools; expose `memory_search` status filter for promoted-record discovery |
| `src/bourbon/tools/__init__.py` | Modify | Add memory_promote/archive to `_ensure_imports()` |
| `tests/test_memory_phase2.py` | Create | All Phase 2 unit and integration tests |
