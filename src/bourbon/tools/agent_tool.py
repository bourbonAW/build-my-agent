"""Agent tool registration for spawning focused subagent runs."""

from __future__ import annotations

import time

from bourbon.debug import debug_log
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
    description=(
        "Start a focused subagent run for isolated work. For parallel work whose "
        "results are needed before continuing, issue multiple foreground Agent tool "
        "calls in the same tool round; Bourbon waits for all results before the "
        "next reasoning step. Use background mode only for independent work."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "description": {"type": "string", "description": "Short run description"},
            "prompt": {"type": "string", "description": "Complete instructions"},
            "subagent_type": {
                "type": "string",
                "enum": ["default", "coder", "explore", "plan", "quick_task", "teammate"],
                "default": "default",
                "description": (
                    "Subagent profile. explore is restricted to read-only tools "
                    "(Read, Glob, Grep, AstGrep, WebFetch) and cannot write files, "
                    "execute code, or call MCP tools. Use default for system "
                    "information, shell commands, or mixed tool needs. "
                    "teammate runs as a peer agent that can coordinate on shared tasks."
                ),
            },
            "model": {"type": ["string", "null"]},
            "max_turns": {"type": ["integer", "null"]},
            "run_in_background": {
                "type": "boolean",
                "default": False,
                "description": (
                    "When true, return a run_id immediately instead of waiting. Use "
                    "only when the parent can proceed without the result; otherwise "
                    "leave false so the Agent call blocks until the subagent result "
                    "is available. If a background result later becomes necessary, "
                    "call AgentWait with the returned run_id."
                ),
            },
        },
        "required": ["description", "prompt"],
    },
    risk_level=RiskLevel.MEDIUM,
    is_concurrency_safe=True,
)
def agent_tool_handler(
    description: str,
    prompt: str,
    *,
    ctx: ToolContext,
    subagent_type: str = "default",
    model: str | None = None,
    max_turns: int | None = None,
    run_in_background: bool = False,
) -> str:
    """Spawn a subagent and format the result for the parent conversation."""
    started_at = time.monotonic()
    debug_log(
        "agent_tool.spawn.start",
        description=description,
        prompt_len=len(prompt),
        subagent_type=subagent_type,
        model=model,
        max_turns=max_turns,
        run_in_background=run_in_background,
    )
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
        debug_log(
            "agent_tool.spawn.error",
            description=description,
            subagent_type=subagent_type,
            error=str(exc),
            elapsed_ms=int((time.monotonic() - started_at) * 1000),
        )
        return f"Error: {exc}"

    if run_in_background:
        run_id = str(result)
        debug_log(
            "agent_tool.spawn.complete",
            run_id=run_id,
            subagent_type=subagent_type,
            run_in_background=True,
            elapsed_ms=int((time.monotonic() - started_at) * 1000),
        )
        return (
            f"Started background run: {run_id}\n"
            f'Use AgentWait with run_ids ["{run_id}"] if you need the result before continuing.'
        )

    if not isinstance(result, AgentToolResult):
        return f"Error: Expected AgentToolResult, got {type(result).__name__}"

    duration_seconds = result.total_duration_ms / 1000
    debug_log(
        "agent_tool.spawn.complete",
        run_id=result.run_id,
        subagent_type=result.agent_type,
        run_in_background=False,
        elapsed_ms=int((time.monotonic() - started_at) * 1000),
        subagent_duration_ms=result.total_duration_ms,
        total_tokens=result.total_tokens,
        total_tool_calls=result.total_tool_calls,
    )
    return (
        f"Subagent completed in {duration_seconds:.1f}s\n"
        f"Tokens: {result.total_tokens}, Tool calls: {result.total_tool_calls}\n\n"
        f"Result:\n{result.content}"
    )


@register_tool(
    name="AgentWait",
    description=(
        "Wait for one or more background Agent runs to finish and return their outputs. "
        "Use this after run_in_background=True when the parent needs those results "
        "before continuing."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "run_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Background run IDs returned by Agent. If omitted or empty, wait "
                    "for all active background runs."
                ),
            },
            "timeout_seconds": {
                "type": ["number", "null"],
                "default": None,
                "description": (
                    "Maximum seconds to wait for each run. Omit to wait until completion."
                ),
            },
        },
    },
    risk_level=RiskLevel.LOW,
)
def agent_wait_tool_handler(
    *,
    ctx: ToolContext,
    run_ids: list[str] | None = None,
    timeout_seconds: float | None = None,
) -> str:
    """Wait for background subagent runs and format their current outputs."""
    try:
        manager = get_manager(ctx)
        return manager.wait_for_runs(run_ids or None, timeout=timeout_seconds)
    except Exception as exc:
        return f"Error: {exc}"
