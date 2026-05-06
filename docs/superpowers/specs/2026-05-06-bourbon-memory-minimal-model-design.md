# Bourbon Memory Minimal Model Design

> Status: Draft for review
> Date: 2026-05-06

## Context

Bourbon memory recently added a cue engine, query cue interpretation, backfill, eval, and debug support. The feature passes tests, but the model surface has become harder to maintain than the product value justifies.

The current design mixes several concerns in the same dataclasses:

- memory content and ownership
- source, actor, audit, and provenance metadata
- lifecycle state such as promoted, stale, and rejected
- cue generation telemetry such as schema version, generator version, generated_at, generation status, and quality flags
- query interpretation fields such as recall need, time hints, uncertainty, kind hints, and scope hints

This spec intentionally cuts the design back to a small, inspectable memory system. Memory has not been adopted as real user data yet, so this cleanup does not preserve old frontmatter compatibility and does not include a migration path.

## Goals

- Make the core memory model obvious at a glance.
- Keep only fields that are required to write, store, search, and inspect a memory.
- Treat cue data as a small attached search aid, not a taxonomy, telemetry, or migration framework.
- Remove unused lifecycle and promotion concepts until product behavior proves they are needed.
- Keep audit/runtime metadata out of `MemoryRecord`.

## Non-Goals

- No backward compatibility with current memory frontmatter.
- No migration script for current memory files.
- No promote/archive lifecycle.
- No cue schema versioning.
- No record/query cue taxonomy registry.
- No generation quality telemetry in persisted memory records.
- No session-target memory. Temporary session facts stay in the active session/task context and do not go through the persisted memory system.

## Core Model

The new core model is:

```python
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

MemoryTarget = Literal["user", "project"]


@dataclass(frozen=True)
class MemoryRecordDraft:
    target: MemoryTarget
    content: str


@dataclass(frozen=True)
class MemoryRecord:
    id: str
    target: MemoryTarget
    content: str
    created_at: datetime
    cues: tuple[str, ...] = ()
```

`content` is the only memory body. It replaces `name`, `description`, `summary`, and `text` variants.

`target` replaces both `kind` and `scope`. The current distinction is not earning its complexity. A memory is for the user or for the project.

`created_at` is retained for chronological review and deterministic display. `updated_at` is removed because cue regeneration, lifecycle changes, and content edits have different semantics. If a memory changes, create a new memory or rewrite the record intentionally.

`cues` is a tuple of extra searchable terms. It is empty when no useful terms exist.

Temporary session facts are not memory records. They should remain in the active session, task state, todo state, or transcript. If a session fact becomes durable enough to remember later, it must be written explicitly as `target="user"` or `target="project"`.

## Removed Record Fields

`title` is removed. Display labels are derived from the first line or first N characters of `content`.

`summary` and `description` are removed. Any short display text is derived from `content`.

`kind` is removed. Classification beyond target is premature.

`scope` is removed. `target` is the only ownership dimension.

`source` is removed. Provenance belongs in runtime audit events, not in the memory record.

`source_ref` is removed from the core record. If transcript/file/tool provenance becomes necessary, it should be introduced as audit data or a separate evidence layer, not as a default field on every memory.

`created_by` is removed. The writer is an audit concern.

`confidence` is removed. Persisted memory should be accepted memory. Uncertainty should stay out of memory or be written explicitly in `content`.

`status` is removed. The memory store contains active memories only. Unneeded memories are deleted. Archive/reject/promote states can be added later if real product behavior requires them.

Legacy `feedback` and `reference` kinds do not get replacement model fields. There is no automatic conversion. Future writes should choose `target="user"` when the memory is about user preference or behavior, and `target="project"` when the memory is about project context, decisions, files, workflows, or references.

## Cue Model

The cue model is intentionally just:

```python
cues: tuple[str, ...]
```

A cue is any extra string that should help retrieve the memory. There is no `MemoryCues` wrapper in the core model.

Examples:

```python
(
    "dark mode",
    "ui preference",
    "memory cleanup",
    "src/bourbon/memory/models.py",
)
```

The implementation normalizes cues by trimming whitespace, dropping empty strings, deduplicating while preserving order, and enforcing `MAX_CUES = 12`.

Cue generation happens synchronously before the memory record is first written. Record cues are write-once in this design. If cue generation fails, the record is written with empty cues and no retry/backfill is scheduled. There is no async cue mutation path.

The following cue concepts are removed:

- `MemoryConcept`
- `CueKind`
- `CueSource`
- `CueGenerationStatus`
- `CueQualityFlag`
- `DomainConcept`
- `schema_version`
- `generator_version`
- `generated_at`

If a file path, symbol, or domain concept is useful for search, it is represented as a plain cue string. Structured channels can be reintroduced later only after ranking/search behavior proves they are necessary.

## Query Expansion

`QueryCue` is removed.

Query-side logic becomes a simple term expansion helper:

```python
def expand_query_terms(query: str) -> tuple[str, ...]:
    ...
```

Rules:

- The first term is always the normalized original query.
- Additional terms are plain strings.
- If no useful expansion exists, return only the original query.
- There is no recall need, uncertainty, fallback flag, quality flag, time hint, kind hint, scope hint, schema version, or interpreter version.

Debug output reports expanded terms, not a query cue object.

## Storage Format

Each memory remains one Markdown file with YAML frontmatter:

```yaml
---
id: mem_abc123
target: user
created_at: 2026-05-06T14:30:00+00:00
cues:
  - dark mode
  - ui preference
---

User prefers dark mode for UI components.
```

The body is the memory content. `content` is not duplicated in frontmatter.

Files are named by id:

```text
mem_abc123.md
```

The filename does not repeat target, title, kind, or slug semantics.

`MEMORY.md` is a derived index. It renders from current records:

```markdown
- [user] User prefers dark mode for UI components. ([mem_abc123.md](mem_abc123.md))
- [project] Prefer append-only memory records. ([mem_def456.md](mem_def456.md))
```

The display text is derived from `content`, not stored separately.

The store rebuilds `MEMORY.md` from scratch after every successful write and delete. Incremental index edits are unnecessary because there is no status lifecycle and each memory file is small.

## Tool Surface

`memory_write` should accept:

```json
{
  "target": "user",
  "content": "User prefers dark mode for UI components."
}
```

Runtime metadata such as session id, platform, tool name, write origin, or agent identity belongs in audit logs. It must not be copied into `MemoryRecord`.

`memory_write` MUST emit an audit event for every successful write. The audit event records the actor, session id when available, origin/tool name when available, target, memory id, and a short content preview. This audit requirement is the replacement for persisted `source`, `source_ref`, and `created_by` fields.

`memory_search` should accept:

```python
search(query: str, *, target: str | None = None, limit: int = 8)
```

The search path matches against:

- `content`
- `cues`

`target` is only a hard filter.

`memory_delete` should delete a record by id. There is no archive state in the record model.

## Manager And Policy

The manager surface becomes:

```python
write(draft: MemoryRecordDraft, *, actor: MemoryActor) -> MemoryRecord
search(query: str, *, target: str | None = None, limit: int | None = None) -> list[MemorySearchResult]
delete(memory_id: str, *, actor: MemoryActor) -> None
get_status(*, actor: MemoryActor) -> MemorySystemInfo
```

The user-facing `memory_status` tool name may remain, but the returned model should not be named like a record lifecycle state.

`MemorySystemInfo` replaces `MemoryStatusInfo` as the returned status model. It reports system-level information such as readable targets, writable targets, recent writes, index capacity, and memory file count. It does not represent record lifecycle state.

Permissions are target-based:

- user, main agent, and system may write `user` and `project`
- subagents may write `project`
- subagents may not write `user`
- subagents may not delete memory

The following manager/policy concepts are removed:

- `promote`
- `archive`
- `check_promote_permission`
- `check_archive_permission`
- subagent write policy by memory kind
- kind/scope/status audit fields
- `actor_to_created_by`

## Eval And Debug

Eval should measure retrieval behavior, not the shape of cue telemetry.

Keep retrieval variants:

- `content_only`
- `content_plus_cues`
- `expanded_query_plus_cues`

Remove reports and fields that only exist to support the old cue schema:

- generation status counts
- quality flag counts
- generator version counts
- interpreter version counts
- fallback rate based on `QueryCue`
- concept drift based on `CueQualityFlag`

Debug output should be small and directly useful:

```json
{
  "query": "dark mode preference",
  "expanded_terms": ["dark mode preference", "dark mode"],
  "matched_memory_ids": ["mem_abc123"],
  "why_matched": "matched cue: dark mode"
}
```

## Testing Strategy

Model tests should verify:

- `MemoryRecordDraft` only requires target and content.
- `MemoryRecord` only persists id, target, content, created_at, and cues.
- cue normalization trims, deduplicates, drops empty strings, and enforces count limits.

Store tests should verify:

- minimal frontmatter round trip
- body-as-content round trip
- `MEMORY.md` index rendering from derived display text
- delete removes a memory file and updates the index

Manager tests should verify:

- write/search/delete happy paths
- target filtering
- subagent target permissions
- search over content and cues

Cue tests should verify:

- write-time cue generation returns tuple strings
- query expansion returns tuple strings
- failed cue generation results in empty cues

Tests to remove for concepts that no longer exist:

- promote/archive lifecycle tests
- backfill tests
- query cue model tests
- generation quality report tests
- schema/generator/interpreter version tests
- malformed old cue metadata compatibility tests

## Module Shape

The `src/bourbon/memory/cues/` package is removed as a package. The old package split across `models.py`, `query.py`, `runtime.py`, `backfill.py`, and `eval.py` is the main source of cue over-design.

If cue logic is still useful after the cleanup, keep it in a single small module:

```text
src/bourbon/memory/cues.py
```

That module may expose only simple helpers such as cue normalization, write-time cue generation, and query term expansion. It must not define persisted cue models, query cue models, backfill workflows, generation telemetry reports, or schema versioning.

## Implementation Notes

This is a breaking cleanup. The implementation should update code and tests directly to the new model. Do not keep old dataclass names, compatibility branches, or old frontmatter parsing unless they are still required by the new design.

The expected result is a smaller memory package whose main model file can be understood without learning a taxonomy, lifecycle state machine, or cue telemetry system first.
