"""Memory access policy helpers."""

from __future__ import annotations

from bourbon.memory.models import MemoryActor, MemoryKind, MemoryRecord, MemoryScope

_SUBAGENT_ALLOWED_KINDS: dict[str, set[MemoryKind]] = {
    "explore": {MemoryKind.PROJECT, MemoryKind.REFERENCE},
    "coder": {MemoryKind.PROJECT, MemoryKind.REFERENCE},
    "plan": {MemoryKind.PROJECT},
}


def check_write_permission(
    actor: MemoryActor,
    *,
    kind: MemoryKind,
    scope: MemoryScope,
) -> bool:
    """Return whether the actor can write a memory of the given kind and scope."""
    # scope-based restrictions are reserved for Phase 2
    _ = scope

    if actor.kind in {"user", "system"}:
        return True
    if actor.kind == "agent" and not actor.agent_type:
        return True

    agent_type = actor.agent_type or "default"
    if agent_type == "default":
        return True

    allowed_kinds = _SUBAGENT_ALLOWED_KINDS.get(
        agent_type,
        {MemoryKind.PROJECT, MemoryKind.REFERENCE},
    )
    return kind in allowed_kinds


def check_promote_permission(actor: MemoryActor, record: MemoryRecord) -> None:
    """Raise when the actor cannot promote the record."""
    if actor.kind == "subagent":
        raise PermissionError("Subagents cannot promote memory records")
    if record.kind not in {MemoryKind.USER, MemoryKind.FEEDBACK}:
        raise PermissionError(f"Cannot promote memory kind {record.kind}")
    if record.scope != MemoryScope.USER:
        raise PermissionError("Only user-scope records can be promoted")


def check_archive_permission(actor: MemoryActor, record: MemoryRecord) -> None:
    """Raise when the actor cannot archive the record."""
    _ = record
    if actor.kind == "subagent":
        raise PermissionError("Subagents cannot archive memory records")
