"""Agent tool registration for spawning focused subagent runs."""

from __future__ import annotations

from bourbon.subagent.result import AgentToolResult
from bourbon.tools import RiskLevel, ToolContext, register_tool


def get_manager(ctx: ToolContext):
    """Return the parent agent's SubagentManager if available."""
    agent = ctx.agent
    manager = getattr(agent, "subagent_manager", None) if agent is not None else None
    if manager is None:
        raise RuntimeError("Agent tool unavailable: no subagent manager in context")
    return manager


@register_tool(
    name="Agent",
    description="Start a focused subagent run for isolated work.",
    input_schema={
        "type": "object",
        "properties": {
            "description": {"type": "string", "description": "Short run description"},
            "prompt": {"type": "string", "description": "Complete instructions"},
            "subagent_type": {
                "type": "string",
                "enum": ["default", "coder", "explore", "plan", "quick_task"],
                "default": "default",
            },
            "model": {"type": ["string", "null"]},
            "max_turns": {"type": "integer", "default": 50},
            "run_in_background": {"type": "boolean", "default": False},
        },
        "required": ["description", "prompt"],
    },
    risk_level=RiskLevel.MEDIUM,
)
def agent_tool_handler(
    description: str,
    prompt: str,
    *,
    ctx: ToolContext,
    subagent_type: str = "default",
    model: str | None = None,
    max_turns: int = 50,
    run_in_background: bool = False,
) -> str:
    """Spawn a subagent and format the result for the parent conversation."""
    try:
        manager = get_manager(ctx)
        result = manager.spawn(
            description=description,
            prompt=prompt,
            agent_type=subagent_type,
            model=model,
            max_turns=max_turns,
            run_in_background=run_in_background,
        )
    except Exception as exc:
        return f"Error: {exc}"

    if run_in_background:
        run_id = str(result)
        return f"Started background run: {run_id}\nUse `/run-show {run_id}` to check status."

    if not isinstance(result, AgentToolResult):
        return f"Error: Expected AgentToolResult, got {type(result).__name__}"

    duration_seconds = result.total_duration_ms / 1000
    return (
        f"Subagent completed in {duration_seconds:.1f}s\n"
        f"Tokens: {result.total_tokens}, Tool calls: {result.total_tool_calls}\n\n"
        f"Result:\n{result.content}"
    )
