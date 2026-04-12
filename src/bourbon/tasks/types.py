"""Persistent workflow task record types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TaskRecord:
    """Persistent task record stored on disk."""

    id: str
    subject: str
    description: str
    status: str = "pending"
    active_form: str | None = None
    owner: str | None = None
    blocks: list[str] = field(default_factory=list)
    blocked_by: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize using the expected on-disk key names."""
        return {
            "id": self.id,
            "subject": self.subject,
            "description": self.description,
            "status": self.status,
            "activeForm": self.active_form,
            "owner": self.owner,
            "blocks": list(self.blocks),
            "blockedBy": list(self.blocked_by),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskRecord":
        """Deserialize a task record from JSON-compatible data."""
        return cls(
            id=str(data["id"]),
            subject=data["subject"],
            description=data["description"],
            status=data.get("status", "pending"),
            active_form=data.get("activeForm"),
            owner=data.get("owner"),
            blocks=[str(task_id) for task_id in data.get("blocks", [])],
            blocked_by=[str(task_id) for task_id in data.get("blockedBy", [])],
            metadata=dict(data.get("metadata", {})),
        )
