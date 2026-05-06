"""Minimal memory data models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

MemoryTarget = Literal["user", "project"]
MEMORY_TARGETS: tuple[MemoryTarget, ...] = ("user", "project")


def validate_memory_target(value: str) -> MemoryTarget:
    """Validate and return a memory target."""
    if value not in MEMORY_TARGETS:
        allowed = ", ".join(MEMORY_TARGETS)
        raise ValueError(f"Invalid memory target {value!r}; expected one of: {allowed}")
    return value  # type: ignore[return-value]


@dataclass(frozen=True)
class MemoryActor:
    """Identifies who is performing a memory operation."""

    kind: Literal["user", "agent", "subagent", "system"]
    session_id: str | None = None
    run_id: str | None = None
    agent_type: str | None = None


@dataclass(frozen=True)
class MemoryRecordDraft:
    """Input for creating a memory record."""

    target: MemoryTarget
    content: str


@dataclass(frozen=True)
class MemoryRecord:
    """A persisted memory record."""

    id: str
    target: MemoryTarget
    content: str
    created_at: datetime
    cues: tuple[str, ...] = ()


@dataclass(frozen=True)
class MemorySearchResult:
    """A single search result returned by memory search."""

    id: str
    target: MemoryTarget
    snippet: str
    why_matched: str = ""


@dataclass(frozen=True)
class RecentWriteSummary:
    """Summary of a recent memory write for memory status display."""

    id: str
    target: MemoryTarget
    preview: str
    created_at: datetime


@dataclass(frozen=True)
class MemorySystemInfo:
    """Runtime memory system information."""

    readable_targets: tuple[str, ...]
    writable_targets: tuple[str, ...]
    recent_writes: tuple[RecentWriteSummary, ...]
    index_at_capacity: bool
    memory_file_count: int
