"""Core data types for subagent runtime jobs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4


class RunStatus(Enum):
    """Runtime-job lifecycle states."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    KILLED = "killed"


@dataclass
class AgentDefinition:
    """Configuration for one subagent type."""

    agent_type: str
    description: str
    allowed_tools: list[str] | None = None
    disallowed_tools: list[str] = field(default_factory=list)
    max_turns: int = 50
    model: str | None = None
    system_prompt_suffix: str | None = None


@dataclass
class SubagentRun:
    """Runtime-job state for one subagent invocation."""

    description: str = ""
    prompt: str = ""
    agent_type: str = "default"
    run_id: str = field(default_factory=lambda: str(uuid4())[:8])
    model: str | None = None
    max_turns: int = 50
    status: RunStatus = RunStatus.PENDING
    created_at: datetime = field(default_factory=datetime.now)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    is_async: bool = False
    abort_controller: Any | None = None
    result: str | None = None
    error: str | None = None
    tool_call_count: int = 0
    total_tokens: int = 0
    current_activity: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to a compact dictionary for REPL rendering."""
        description = self.description
        if len(description) > 50:
            description = f"{description[:50]}..."

        return {
            "run_id": self.run_id,
            "description": description,
            "agent_type": self.agent_type,
            "status": self.status.value,
            "is_async": self.is_async,
            "created_at": self.created_at.isoformat(),
            "completed_at": (
                self.completed_at.isoformat() if self.completed_at else None
            ),
            "tool_calls": self.tool_call_count,
        }
