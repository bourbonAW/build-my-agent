"""Audit event models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class EventType(StrEnum):
    """Types of audit events."""

    POLICY_DECISION = "policy_decision"
    SANDBOX_EXEC = "sandbox_exec"
    SANDBOX_VIOLATION = "sandbox_violation"
    TOOL_CALL = "tool_call"
    MEMORY_WRITE = "memory_write"
    MEMORY_SEARCH = "memory_search"
    MEMORY_DELETE = "memory_delete"


@dataclass(slots=True)
class AuditEvent:
    """Single audit log entry."""

    timestamp: datetime
    event_type: EventType
    tool_name: str
    tool_input_summary: str
    extra: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        """Serialize the event to a flattened dictionary."""
        reserved_keys = {
            "timestamp",
            "event_type",
            "tool_name",
            "tool_input_summary",
        }
        collision_keys = reserved_keys.intersection(self.extra)
        if collision_keys:
            raise ValueError(f"extra contains reserved audit field(s): {sorted(collision_keys)}")

        payload: dict[str, object] = {
            "timestamp": self.timestamp.isoformat(),
            "event_type": self.event_type.value,
            "tool_name": self.tool_name,
            "tool_input_summary": self.tool_input_summary,
        }
        payload.update(self.extra)
        return payload

    @classmethod
    def policy_decision(
        cls,
        *,
        tool_name: str,
        tool_input_summary: str,
        **extra: object,
    ) -> AuditEvent:
        return cls(
            timestamp=datetime.now(UTC),
            event_type=EventType.POLICY_DECISION,
            tool_name=tool_name,
            tool_input_summary=tool_input_summary,
            extra=extra,
        )

    @classmethod
    def sandbox_exec(
        cls,
        *,
        tool_name: str,
        tool_input_summary: str,
        **extra: object,
    ) -> AuditEvent:
        return cls(
            timestamp=datetime.now(UTC),
            event_type=EventType.SANDBOX_EXEC,
            tool_name=tool_name,
            tool_input_summary=tool_input_summary,
            extra=extra,
        )

    @classmethod
    def sandbox_violation(
        cls,
        *,
        tool_name: str,
        tool_input_summary: str,
        **extra: object,
    ) -> AuditEvent:
        return cls(
            timestamp=datetime.now(UTC),
            event_type=EventType.SANDBOX_VIOLATION,
            tool_name=tool_name,
            tool_input_summary=tool_input_summary,
            extra=extra,
        )

    @classmethod
    def tool_call(
        cls,
        *,
        tool_name: str,
        tool_input_summary: str,
        **extra: object,
    ) -> AuditEvent:
        return cls(
            timestamp=datetime.now(UTC),
            event_type=EventType.TOOL_CALL,
            tool_name=tool_name,
            tool_input_summary=tool_input_summary,
            extra=extra,
        )
