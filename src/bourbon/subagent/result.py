"""Result helpers for Agent tool subagent runs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from bourbon.subagent.types import SubagentRun


@dataclass
class AgentToolResult:
    """Final result returned by a subagent run."""

    run_id: str
    agent_type: str
    content: str
    total_duration_ms: int
    total_tokens: int
    total_tool_calls: int
    description: str | None = None
    usage: dict[str, int] | None = None

    def to_notification(self) -> str:
        """Convert the result into a concise parent-session notification."""
        content_preview = self.content[:500]
        if len(self.content) > 500:
            content_preview += "..."

        description = self.description or self.run_id
        duration_seconds = self.total_duration_ms / 1000

        return f"""[Run {self.run_id}] Completed

Description: {description}
Status: Completed
Duration: {duration_seconds:.1f}s
Tokens: {self.total_tokens}
Tool Calls: {self.total_tool_calls}

Result:
{content_preview}

Use `/run-show {self.run_id}` for full details.
"""


def finalize_agent_tool(
    run: SubagentRun,
    messages: list[Any],
    final_content: str,
    start_time_ms: float,
) -> AgentToolResult:
    """Create the final Agent tool result payload for a run."""
    duration_ms = int(datetime.now().timestamp() * 1000 - start_time_ms)

    return AgentToolResult(
        run_id=run.run_id,
        agent_type=run.agent_type,
        description=run.description,
        content=final_content,
        total_duration_ms=duration_ms,
        total_tokens=run.total_tokens,
        total_tool_calls=run.tool_call_count,
        usage={
            "input_tokens": run.input_tokens,
            "output_tokens": run.output_tokens,
        },
    )
