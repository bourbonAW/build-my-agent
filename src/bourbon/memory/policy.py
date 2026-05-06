"""Memory access policy helpers."""

from __future__ import annotations

from bourbon.memory.models import MemoryActor, MemoryTarget


def check_write_permission(
    actor: MemoryActor,
    *,
    target: MemoryTarget,
) -> bool:
    """Return whether the actor can write a memory for the target."""
    if actor.kind == "subagent":
        return target == "project"
    return actor.kind in {"user", "agent", "system"}


def check_delete_permission(actor: MemoryActor) -> None:
    """Raise when the actor cannot delete a memory record."""
    if actor.kind == "subagent":
        raise PermissionError("Subagents cannot delete memory records")
