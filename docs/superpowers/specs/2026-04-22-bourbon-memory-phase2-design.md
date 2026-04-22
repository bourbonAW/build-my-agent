# Bourbon Memory Phase 2 Design: MemoryPromote & MemoryReject

**Date**: 2026-04-22  
**Status**: Draft  
**Scope**: Phase 2 of the bourbon memory system — `memory_promote` and `memory_reject` tools only. SQLite FTS deferred to Phase 3.

---

## 1. Background & Motivation

Phase 1 delivered `memory_write`, `memory_search`, and `memory_status`. Records are stored as individual `.md` files under `~/.bourbon/projects/{key}/memory/`, indexed by `MEMORY.md`.

The critical limitation Phase 1 left open: **only the MEMORY.md index (one-line summaries) is injected into the system prompt**, not the full content of each memory record. This means behavioral preferences like "always use uv" are injected as a weak one-liner, and the agent may not enforce them reliably.

Phase 1 spec explicitly deferred the solution: `MemoryPromote → MEMORY.md / USER.md` would be Phase 2.

**Phase 2 goal**: give the agent a path to promote stable preferences from the index-only layer into `USER.md`, which is injected **in full** into every system prompt.

---

## 2. Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Phase 2 scope | MemoryPromote + MemoryReject only | SQLite FTS not needed at current memory volume |
| User confirmation | None — agent auto-promotes | Simplest UX; agent knows when a preference is stable |
| Promotion target | `USER.md` managed section | Full-text injection; spec original design |
| Trigger mechanism | Agent proactive tool call | No background infrastructure needed; LLM judges timing |
| Source file after promote | Kept on disk, status → `promoted` | Audit trail preserved |
| Duplicate injection | Prevented via `promoted` status | Promoted records exit MEMORY.md index |

---

## 3. Architecture

Phase 2 adds no new modules. All changes are in four existing files:

```
src/bourbon/memory/
  models.py    ← add MemoryStatus.PROMOTED
  files.py     ← add USER.md managed section parse / upsert / mark_rejected
  store.py     ← add update_status(); exclude promoted from MEMORY.md index
  manager.py   ← add promote() / reject() coordinating store + files

src/bourbon/tools/
  memory.py    ← register memory_promote and memory_reject tools
```

### Data Flow

```
User expresses preference
  ↓
LLM calls memory_write → source file status=active → MEMORY.md index (weak, one-liner)
  ↓  (later, LLM judges preference is stable)
LLM calls memory_promote(memory_id)
  ↓
  ├─ store: source file status: active → promoted  (exits MEMORY.md index)
  └─ files: USER.md managed section upsert         (full-text injection, strong)
  ↓  (if preference becomes invalid)
LLM calls memory_reject(memory_id)
  ↓
  ├─ store: source file status → rejected
  └─ files: if previously promoted, mark block rejected in USER.md
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
| `promoted` | ✅ kept (audit) | ❌ excluded | ✅ full-text injected |
| `stale` | ✅ kept | ❌ | ❌ |
| `rejected` | ✅ kept | ❌ | ❌ (block marked rejected if was promoted) |

---

## 5. USER.md Managed Section

Bourbon writes a machine-readable managed section at the end of `~/.bourbon/USER.md`. User content above this section is never touched.

### 5.1 Format

```markdown
<!-- User's own handwritten preferences above — never modified by Bourbon -->

## Bourbon Managed Preferences

> Managed by Bourbon. Edit content inside blocks freely; do not remove the marker lines.

<!-- bourbon-memory:start id="mem_b4c2c06f" -->
### User Preference: mem_b4c2c06f

- status: promoted
- kind: user
- promoted_at: 2026-04-22T10:00:00Z

用户已全面拥抱 uv 工具，要求所有 Python 生态相关操作都通过 uv 执行，不再直接使用 python/pip 等命令。
<!-- bourbon-memory:end id="mem_b4c2c06f" -->
```

### 5.2 Mutation Rules

- **Upsert**: if `id` not in managed section → append new block; if already present → replace block in place (start..end).
- **Mark rejected**: update `status: promoted` → `status: rejected` inside the block. Block is not deleted (audit trail). Rejected blocks are not injected into the prompt.
- **User edits**: content outside `<!-- bourbon-memory:start/end -->` markers is never rewritten.
- **Section creation**: if `## Bourbon Managed Preferences` section does not exist, `memory_promote` creates it at the end of the file.
- **File creation**: if `~/.bourbon/USER.md` does not exist, it is created with just the managed section.

### 5.3 Prompt Injection

`memory_anchors_section()` already calls `merge_user_md()` which reads `~/.bourbon/USER.md` in full. No changes needed to the injection path — promoted records are automatically included as soon as they appear in USER.md.

Rejected blocks inside the managed section are excluded at render time: `files.py` strips blocks with `status: rejected` before returning content for prompt injection.

---

## 6. Implementation Details

### 6.1 `models.py` — Add PROMOTED status

Add `PROMOTED = "promoted"` to `MemoryStatus`. No other model changes needed.

### 6.2 `files.py` — Managed section operations

Add three functions:

```python
def upsert_managed_block(user_md_path: Path, record: MemoryRecord, note: str = "") -> None:
    """Insert or replace a bourbon-managed block in USER.md."""

def mark_block_rejected(user_md_path: Path, memory_id: str) -> None:
    """Update status field inside an existing managed block to rejected."""

def render_user_md_for_prompt(user_md_path: Path, token_limit: int) -> str:
    """Read USER.md, strip rejected managed blocks, truncate to token limit."""
```

Parser uses regex on `<!-- bourbon-memory:start id="mem_XXXX" -->` and `<!-- bourbon-memory:end id="mem_XXXX" -->` comment markers, capturing the `id` attribute. The `## Bourbon Managed Preferences` heading is the human-visible section wrapper; the comment markers are the machine-readable delimiters.

`render_user_md_for_prompt()` replaces the current `read_file_anchor()` call for USER.md in `memory_anchors_section()`. It filters out rejected blocks so they never reach the prompt.

### 6.3 `store.py` — `update_status()` and index exclusion

```python
def update_status(self, memory_id: str, status: MemoryStatus) -> MemoryRecord:
    """Load record, update status field, atomic-write back."""
```

`_rebuild_index()` (called after every write/update) already filters records by status. Add `MemoryStatus.PROMOTED` to the exclusion list alongside `STALE` and `REJECTED`.

### 6.4 `manager.py` — `promote()` and `reject()`

```python
def promote(self, memory_id: str, actor: MemoryActor, note: str = "") -> MemoryRecord:
    record = self._store.get(memory_id)
    if record.status != MemoryStatus.ACTIVE:
        raise ValueError(f"Cannot promote record with status {record.status}")
    updated = self._store.update_status(memory_id, MemoryStatus.PROMOTED)
    user_md = Path("~/.bourbon/USER.md").expanduser()
    upsert_managed_block(user_md, updated, note=note)
    self._audit(actor, "promote", memory_id)
    return updated

def reject(self, memory_id: str, status: MemoryStatus, actor: MemoryActor, reason: str = "") -> MemoryRecord:
    record = self._store.get(memory_id)
    was_promoted = record.status == MemoryStatus.PROMOTED
    updated = self._store.update_status(memory_id, status)
    if was_promoted:
        user_md = Path("~/.bourbon/USER.md").expanduser()
        mark_block_rejected(user_md, memory_id)
    self._audit(actor, "reject", memory_id, reason=reason)
    return updated
```

### 6.5 `memory.py` — Tool registration

**`memory_promote`**

```python
@register_tool(
    name="memory_promote",
    description=(
        "Promote an active memory record to USER.md for strong behavioral enforcement. "
        "Call this when a user/feedback memory has proven stable across multiple turns — "
        "e.g., a tool preference, output format, or workflow rule the user consistently expects. "
        "After promotion: the record exits the MEMORY.md index; its full content is injected "
        "into every future system prompt via USER.md. "
        "Only promote records with status='active'."
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

**`memory_reject`**

```python
@register_tool(
    name="memory_reject",
    description=(
        "Mark a memory record as rejected or stale. "
        "If the record was previously promoted to USER.md, also removes it from injection. "
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

---

## 7. Error Handling

| Scenario | Behavior |
|---|---|
| `memory_promote` on non-active record | Raise `ValueError` with clear message; tool returns error string |
| `memory_promote` on unknown id | `store.get()` raises `KeyError`; tool returns error string |
| USER.md write failure (permissions) | Raise `OSError`; tool returns error; source file status NOT changed (atomic: store write happens only after USER.md write succeeds) |
| `memory_reject` on non-promoted record | Update store status only; skip USER.md mutation silently |
| Corrupt managed section (markers missing) | `upsert_managed_block` falls back to appending a new block; logs warning |

**Atomicity**: `promote()` writes USER.md first, then updates store status. If USER.md write fails, the source file remains `active`. If store write fails after USER.md write, the managed block is present but the source file is still `active` — on next call, `memory_promote` detects the block already exists (via id lookup) and updates it idempotently.

---

## 8. Access Control

Follows existing Phase 1 policy:

- `memory_promote` and `memory_reject` require `file_write` capability.
- Subagents (explore type) cannot call `memory_promote` or `memory_reject` — enforced via `MemoryPolicy` scope restrictions (subagents can only write `project`-scope records, not promote `user`/`feedback`).
- Main agent and user-sourced tools can promote any `active` record.

No new capability types needed.

---

## 9. Testing

### Unit tests (`tests/test_memory_phase2.py`)

**Managed section operations (`files.py`):**
- `upsert_managed_block` on empty file → creates file with section and block
- `upsert_managed_block` on existing block → replaces in place, no duplicate
- `mark_block_rejected` → updates status field, block remains
- `render_user_md_for_prompt` → strips rejected blocks, preserves user content above managed section
- User content above managed section → never modified by any operation
- Missing `end` marker (corrupt file) → append fallback, warning logged

**Status transitions (`store.py`):**
- `update_status` → frontmatter rewritten, all other fields preserved
- MEMORY.md index excludes `promoted` records
- MEMORY.md index excludes `stale` and `rejected` records (regression)

**Manager coordination (`manager.py`):**
- `promote()` happy path → store status=promoted, USER.md block present
- `promote()` on non-active record → raises ValueError, no file modified
- `promote()` USER.md write fails → source file remains active
- `reject()` on active record → store updated, USER.md not touched
- `reject()` on promoted record → store updated, USER.md block marked rejected

**Tool handlers (`memory.py`):**
- `memory_promote` tool call → returns success with file path
- `memory_promote` unknown id → returns error string, no crash
- `memory_reject` tool call → returns success

### Integration test

- Full lifecycle: `memory_write` → `memory_promote` → check USER.md injection → `memory_reject` → check USER.md block marked rejected, not injected.

---

## 10. What Phase 2 Does NOT Include

- SQLite FTS search index (deferred to Phase 3)
- Background/automatic promote (agent decides proactively via tool call)
- Project-scope USER.md (only `~/.bourbon/USER.md` global for now)
- `MemoryPromote` for `project`/`reference` kind records — the primary use case is `user` and `feedback` kinds; `project`/`reference` records are better kept in the index
- UI or `/memory` command changes

---

## 11. File Change Summary

| File | Change type | Description |
|---|---|---|
| `src/bourbon/memory/models.py` | Modify | Add `MemoryStatus.PROMOTED` |
| `src/bourbon/memory/files.py` | Modify | Add `upsert_managed_block`, `mark_block_rejected`, `render_user_md_for_prompt` |
| `src/bourbon/memory/store.py` | Modify | Add `update_status()`; exclude `promoted` from MEMORY.md index |
| `src/bourbon/memory/manager.py` | Modify | Add `promote()` and `reject()` methods |
| `src/bourbon/memory/prompt.py` | Modify | Use `render_user_md_for_prompt` instead of `read_file_anchor` for USER.md |
| `src/bourbon/tools/memory.py` | Modify | Register `memory_promote` and `memory_reject` tools |
| `src/bourbon/tools/__init__.py` | Modify | Add memory_promote/reject to `_ensure_imports()` |
| `tests/test_memory_phase2.py` | Create | All Phase 2 unit and integration tests |
