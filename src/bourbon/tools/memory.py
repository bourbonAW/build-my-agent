"""Memory tools."""

from __future__ import annotations

import json
import re
from typing import Any

from bourbon.tools import RiskLevel, ToolContext, register_tool


def _json_output(payload: dict[str, Any]) -> str:
    return json.dumps(payload)


def _disabled() -> str:
    return _json_output({"error": "Memory system is not enabled"})


def _filename(kind: str, name: str, record_id: str) -> str:
    slug = name.lower().replace(" ", "-")
    slug = re.sub(r"[^a-z0-9\-]", "", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return f"{kind}_{slug[:50]}_{record_id[:8]}.md"


@register_tool(
    name="memory_search",
    aliases=["MemorySearch"],
    description="Search stored memory records by keyword.",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query keywords"},
            "scope": {
                "type": "string",
                "enum": ["user", "project", "session"],
                "description": "Optional scope filter",
            },
            "kind": {
                "type": "array",
                "items": {"type": "string", "enum": ["user", "feedback", "project", "reference"]},
                "description": "Optional memory kind filter",
            },
            "status": {
                "type": "array",
                "items": {"type": "string", "enum": ["active", "promoted", "stale", "rejected"]},
                "description": "Optional memory status filter",
            },
            "limit": {"type": "integer", "default": 8, "description": "Maximum results"},
            # from_date / to_date date filtering reserved for Phase 2
        },
        "required": ["query"],
    },
    risk_level=RiskLevel.LOW,
    is_read_only=True,
    required_capabilities=["file_read"],
)
def memory_search(query: str, *, ctx: ToolContext, **kwargs: Any) -> str:
    """Search memory records."""
    if ctx.memory_manager is None:
        return _disabled()

    results = ctx.memory_manager.search(
        query,
        scope=kwargs.get("scope"),
        kind=kwargs.get("kind"),
        status=kwargs.get("status"),
        limit=kwargs.get("limit"),
    )
    return _json_output(
        {
            "results": [
                {
                    "id": result.id,
                    "name": result.name,
                    "kind": str(result.kind),
                    "scope": str(result.scope),
                    "confidence": result.confidence,
                    "snippet": result.snippet,
                    "why_matched": result.why_matched,
                }
                for result in results
            ]
        }
    )


@register_tool(
    name="memory_write",
    aliases=["MemoryWrite"],
    description=(
        "Write a governed memory record for future recall.\n"
        "Call this PROACTIVELY — do NOT wait for the user to say 'remember this'. "
        "Trigger on any of the following signals:\n"
        "  - Preferences: language/output/tone/format the user wants "
        "(e.g. 'respond in Chinese', 'no emojis').\n"
        "  - Constraints & corrections: 'always X', 'never Y', 'must Z', "
        "'stop doing W', 'from now on ...'.\n"
        "  - Role/context: what the user does, what they're working on, "
        "domain background.\n"
        "  - External references: where bugs/dashboards/docs live "
        "(Linear project, Grafana URL, etc.).\n"
        "Choose `kind` by signal type: user (role/preferences), "
        "feedback (corrections/confirmed approaches), "
        "project (ongoing work/decisions), reference (pointers to external systems). "
        "Use scope='user' for cross-project personal preferences, "
        "scope='project' for repo-specific facts. "
        "Skip ephemeral task state — that belongs in TodoWrite, not memory."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "Memory content"},
            "kind": {
                "type": "string",
                "enum": ["user", "feedback", "project", "reference"],
                "description": "Memory kind",
            },
            "scope": {
                "type": "string",
                "enum": ["user", "project", "session"],
                "description": "Memory scope",
            },
            "source": {
                "type": "string",
                "enum": ["user", "agent", "subagent", "compaction", "manual"],
                "description": "Origin of the memory",
            },
            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0, "default": 1.0},
            "name": {"type": "string", "description": "Optional short title"},
            "description": {"type": "string", "description": "Optional one-line summary"},
            "source_ref": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string"},
                    "project_name": {"type": "string"},
                    "session_id": {"type": "string"},
                    "message_uuid": {"type": "string"},
                    "start_message_uuid": {"type": "string"},
                    "end_message_uuid": {"type": "string"},
                    "file_path": {"type": "string"},
                    "tool_call_id": {"type": "string"},
                },
            },
        },
        "required": ["content", "kind", "scope", "source"],
    },
    risk_level=RiskLevel.MEDIUM,
    required_capabilities=["file_write"],
)
def memory_write(
    content: str,
    kind: str,
    scope: str,
    source: str,
    *,
    ctx: ToolContext,
    **kwargs: Any,
) -> str:
    """Write a memory record."""
    if ctx.memory_manager is None:
        return _disabled()

    from bourbon.memory.models import (
        MemoryActor,
        MemoryKind,
        MemoryRecordDraft,
        MemoryScope,
        MemorySource,
        SourceRef,
    )

    source_ref = None
    if kwargs.get("source_ref"):
        source_ref = SourceRef(**kwargs["source_ref"])

    try:
        draft = MemoryRecordDraft(
            kind=MemoryKind(kind),
            scope=MemoryScope(scope),
            content=content,
            source=MemorySource(source),
            confidence=kwargs.get("confidence", 1.0),
            name=kwargs.get("name"),
            description=kwargs.get("description"),
            source_ref=source_ref,
        )
        actor = ctx.memory_actor or MemoryActor(kind="agent")
        record = ctx.memory_manager.write(draft, actor=actor)
    except (PermissionError, ValueError) as exc:
        return _json_output({"error": str(exc)})

    return _json_output(
        {
            "id": record.id,
            "name": record.name,
            "status": "written",
            "file": _filename(str(record.kind), record.name, record.id),
        }
    )


@register_tool(
    name="memory_promote",
    aliases=["MemoryPromote"],
    description=(
        "Promote a stable user or feedback memory with scope='user' into managed USER.md. "
        "Use this for preferences or feedback that are stable across multiple turns, such as tool choices, "
        "format expectations, or workflow rules. Promoted memories are rendered before freeform "
        "USER.md content in future prompts."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "memory_id": {
                "type": "string",
                "description": "ID of the memory record to promote",
            },
            "note": {"type": "string", "description": "Optional promotion note"},
        },
        "required": ["memory_id"],
    },
    risk_level=RiskLevel.MEDIUM,
    required_capabilities=["file_write"],
)
def memory_promote(memory_id: str, *, ctx: ToolContext, **kwargs: Any) -> str:
    """Promote a memory record into managed USER.md."""
    if ctx.memory_manager is None:
        return _disabled()

    from bourbon.memory.models import MemoryActor

    try:
        actor = ctx.memory_actor or MemoryActor(kind="agent")
        record = ctx.memory_manager.promote(
            memory_id,
            actor=actor,
            note=kwargs.get("note", ""),
        )
    except (KeyError, PermissionError, ValueError, RuntimeError) as exc:
        return _json_output({"error": str(exc)})

    return _json_output(
        {
            "id": record.id,
            "name": record.name,
            "status": str(record.status),
        }
    )


@register_tool(
    name="memory_archive",
    aliases=["MemoryArchive"],
    description=(
        "Archive a memory by marking it stale or rejected. Use 'rejected' for incorrect or "
        "outdated memories, and 'stale' for temporarily suspended preferences or guidance."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "memory_id": {
                "type": "string",
                "description": "ID of the memory record to archive",
            },
            "status": {
                "type": "string",
                "enum": ["rejected", "stale"],
                "description": "Archive status to apply",
            },
            "reason": {"type": "string", "description": "Optional archive reason"},
        },
        "required": ["memory_id", "status"],
    },
    risk_level=RiskLevel.MEDIUM,
    required_capabilities=["file_write"],
)
def memory_archive(memory_id: str, status: str, *, ctx: ToolContext, **kwargs: Any) -> str:
    """Archive a memory record."""
    if ctx.memory_manager is None:
        return _disabled()

    from bourbon.memory.models import MemoryActor, MemoryStatus

    try:
        actor = ctx.memory_actor or MemoryActor(kind="agent")
        record = ctx.memory_manager.archive(
            memory_id,
            MemoryStatus(status),
            actor=actor,
            reason=kwargs.get("reason", ""),
        )
    except (KeyError, PermissionError, ValueError, RuntimeError) as exc:
        return _json_output({"error": str(exc)})

    return _json_output(
        {
            "id": record.id,
            "name": record.name,
            "status": str(record.status),
        }
    )


@register_tool(
    name="memory_status",
    aliases=["MemoryStatus"],
    description="Return current memory system status and recent writes.",
    input_schema={"type": "object", "properties": {}},
    risk_level=RiskLevel.LOW,
    is_read_only=True,
    required_capabilities=["file_read"],
)
def memory_status(*, ctx: ToolContext, **kwargs: Any) -> str:
    """Return memory system status."""
    del kwargs
    if ctx.memory_manager is None:
        return _disabled()

    from bourbon.memory.models import MemoryActor

    actor = ctx.memory_actor or MemoryActor(kind="agent")
    status = ctx.memory_manager.get_status(actor=actor)
    return _json_output(
        {
            "readable_scopes": status.readable_scopes,
            "writable_scopes": status.writable_scopes,
            "prompt_anchor_tokens": status.prompt_anchor_tokens,
            "index_at_capacity": status.index_at_capacity,
            "memory_file_count": status.memory_file_count,
            "recent_writes": [
                {
                    "id": write.id,
                    "name": write.name,
                    "kind": str(write.kind),
                }
                for write in status.recent_writes
            ],
        }
    )
