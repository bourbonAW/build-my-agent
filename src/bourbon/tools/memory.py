"""Memory tools."""

from __future__ import annotations

import json
from typing import Any

from bourbon.tools import RiskLevel, ToolContext, register_tool


def _json_output(payload: dict[str, Any]) -> str:
    return json.dumps(payload)


def _disabled() -> str:
    return _json_output({"error": "Memory system is not enabled"})


@register_tool(
    name="memory_search",
    aliases=["MemorySearch"],
    description="Search stored memory records by keyword.",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query keywords"},
            "target": {
                "type": "string",
                "enum": ["user", "project"],
                "description": "Optional target filter",
            },
            "limit": {"type": "integer", "default": 8, "description": "Maximum results"},
            "debug_terms": {
                "type": "boolean",
                "default": False,
                "description": "Include expanded query terms used for search",
            },
        },
        "required": ["query"],
    },
    risk_level=RiskLevel.LOW,
    is_read_only=True,
    required_capabilities=["file_read"],
)
def memory_search(query: str, *, ctx: ToolContext, **kwargs: Any) -> str:
    if ctx.memory_manager is None:
        return _disabled()
    results = ctx.memory_manager.search(
        query,
        target=kwargs.get("target"),
        limit=kwargs.get("limit"),
    )
    payload: dict[str, Any] = {
        "results": [
            {
                "id": result.id,
                "target": result.target,
                "snippet": result.snippet,
                "why_matched": result.why_matched,
            }
            for result in results
        ]
    }
    if kwargs.get("debug_terms"):
        get_terms = getattr(ctx.memory_manager, "get_last_expanded_terms", None)
        if callable(get_terms):
            payload["expanded_terms"] = list(get_terms())
    return _json_output(payload)


@register_tool(
    name="memory_write",
    aliases=["MemoryWrite"],
    description=(
        "Write a memory record for future recall. Use target='user' for durable user "
        "preferences and target='project' for repository decisions, files, workflows, "
        "and references. Do not write ephemeral task state to memory."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "target": {
                "type": "string",
                "enum": ["user", "project"],
                "description": "Memory target",
            },
            "content": {"type": "string", "description": "Memory content"},
        },
        "required": ["target", "content"],
    },
    risk_level=RiskLevel.MEDIUM,
    required_capabilities=["file_write"],
)
def memory_write(target: str, content: str, *, ctx: ToolContext, **kwargs: Any) -> str:
    del kwargs
    if ctx.memory_manager is None:
        return _disabled()
    from bourbon.memory.models import MemoryActor, MemoryRecordDraft, validate_memory_target

    try:
        draft = MemoryRecordDraft(target=validate_memory_target(target), content=content)
        actor = ctx.memory_actor or MemoryActor(kind="agent")
        record = ctx.memory_manager.write(draft, actor=actor)
    except (PermissionError, RuntimeError, ValueError) as exc:
        return _json_output({"error": str(exc)})
    return _json_output(
        {
            "id": record.id,
            "target": record.target,
            "status": "written",
            "file": f"{record.id}.md",
        }
    )


@register_tool(
    name="memory_delete",
    aliases=["MemoryDelete"],
    description="Delete a stored memory record by id.",
    input_schema={
        "type": "object",
        "properties": {
            "memory_id": {"type": "string", "description": "ID of the memory record to delete"},
        },
        "required": ["memory_id"],
    },
    risk_level=RiskLevel.MEDIUM,
    required_capabilities=["file_write"],
)
def memory_delete(memory_id: str, *, ctx: ToolContext, **kwargs: Any) -> str:
    del kwargs
    if ctx.memory_manager is None:
        return _disabled()
    from bourbon.memory.models import MemoryActor

    try:
        actor = ctx.memory_actor or MemoryActor(kind="agent")
        ctx.memory_manager.delete(memory_id, actor=actor)
    except (KeyError, PermissionError) as exc:
        return _json_output({"error": str(exc)})
    return _json_output({"id": memory_id, "status": "deleted"})


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
    del kwargs
    if ctx.memory_manager is None:
        return _disabled()
    from bourbon.memory.models import MemoryActor

    actor = ctx.memory_actor or MemoryActor(kind="agent")
    status = ctx.memory_manager.get_status(actor=actor)
    return _json_output(
        {
            "readable_targets": status.readable_targets,
            "writable_targets": status.writable_targets,
            "index_at_capacity": status.index_at_capacity,
            "memory_file_count": status.memory_file_count,
            "recent_writes": [
                {
                    "id": write.id,
                    "target": write.target,
                    "preview": write.preview,
                }
                for write in status.recent_writes
            ],
        }
    )
