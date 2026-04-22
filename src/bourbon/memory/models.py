"""Memory data models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal


class MemoryKind(StrEnum):
    USER = "user"
    FEEDBACK = "feedback"
    PROJECT = "project"
    REFERENCE = "reference"


class MemoryScope(StrEnum):
    USER = "user"
    PROJECT = "project"
    SESSION = "session"


class MemorySource(StrEnum):
    USER = "user"
    AGENT = "agent"
    SUBAGENT = "subagent"
    COMPACTION = "compaction"
    MANUAL = "manual"


class MemoryStatus(StrEnum):
    ACTIVE = "active"
    STALE = "stale"
    REJECTED = "rejected"
    PROMOTED = "promoted"


@dataclass(frozen=True)
class MemoryActor:
    """Identifies who is performing a memory operation."""

    kind: Literal["user", "agent", "subagent", "system"]
    session_id: str | None = None
    run_id: str | None = None
    agent_type: str | None = None


def actor_to_created_by(actor: MemoryActor) -> str:
    """Derive created_by string from actor."""
    if actor.kind == "user":
        return "user"
    if actor.kind == "agent":
        return f"agent:{actor.session_id}"
    if actor.kind == "subagent":
        return f"subagent:{actor.run_id}"
    return f"system:{actor.kind}"


@dataclass(frozen=True)
class SourceRef:
    """Reference to the origin of a memory record."""

    kind: Literal["transcript", "transcript_range", "file", "tool_call", "manual"]
    project_name: str | None = None
    session_id: str | None = None
    message_uuid: str | None = None
    start_message_uuid: str | None = None
    end_message_uuid: str | None = None
    file_path: str | None = None
    tool_call_id: str | None = None

    def __post_init__(self) -> None:
        # Mutual exclusion: message_uuid vs range
        if self.message_uuid and (self.start_message_uuid or self.end_message_uuid):
            raise ValueError(
                "message_uuid and start_message_uuid/end_message_uuid are mutually exclusive"
            )

        # Range requires both start and end
        if bool(self.start_message_uuid) != bool(self.end_message_uuid):
            raise ValueError(
                "start_message_uuid and end_message_uuid must both be provided or both omitted"
            )

        # Kind-specific required fields
        if self.kind == "transcript":
            if not self.session_id:
                raise ValueError("session_id is required for transcript SourceRef")
            if not self.message_uuid:
                raise ValueError("message_uuid is required for transcript SourceRef")
        elif self.kind == "transcript_range":
            if not self.session_id:
                raise ValueError("session_id is required for transcript_range SourceRef")
            if not self.start_message_uuid or not self.end_message_uuid:
                raise ValueError(
                    "start_message_uuid and end_message_uuid are required"
                    " for transcript_range SourceRef"
                )
        elif self.kind == "file":
            if not self.file_path:
                raise ValueError("file_path is required for file SourceRef")
        elif self.kind == "tool_call":
            if not self.tool_call_id:
                raise ValueError("tool_call_id is required for tool_call SourceRef")


@dataclass
class MemoryRecordDraft:
    """Input for creating a new memory record (no id, timestamps, or created_by)."""

    kind: MemoryKind
    scope: MemoryScope
    content: str
    source: MemorySource
    confidence: float = 1.0
    name: str | None = None
    description: str | None = None
    source_ref: SourceRef | None = None


@dataclass
class MemoryRecord:
    """A persisted memory record with full metadata."""

    id: str
    name: str
    description: str
    kind: MemoryKind
    scope: MemoryScope
    confidence: float
    source: MemorySource
    status: MemoryStatus
    created_at: datetime
    updated_at: datetime
    created_by: str
    content: str
    source_ref: SourceRef | None = None


@dataclass
class MemorySearchResult:
    """A single search result returned by MemorySearch."""

    id: str
    name: str
    kind: MemoryKind
    scope: MemoryScope
    snippet: str
    confidence: float
    status: MemoryStatus
    source_ref: SourceRef | None = None
    why_matched: str = ""


@dataclass
class RecentWriteSummary:
    """Summary of a recent memory write for MemoryStatus display."""

    id: str
    name: str
    kind: MemoryKind
    created_at: datetime


@dataclass
class MemoryStatusInfo:
    """Runtime memory status information."""

    readable_scopes: list[str]
    writable_scopes: list[str]
    prompt_anchor_tokens: int
    recent_writes: list[RecentWriteSummary]
    index_at_capacity: bool
    memory_file_count: int
    transcript_search_slow: bool = False
