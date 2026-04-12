"""Tool filtering for subagent profiles."""

from __future__ import annotations

from typing import Any

from bourbon.subagent.types import AgentDefinition

ALL_AGENT_DISALLOWED_TOOLS = {
    "Agent",  # no recursive subagents
    "TodoWrite",  # do not pollute parent agent checklist state
    "compress",  # parent controls context compression
}

READ_ONLY_TOOLS = ["Read", "Glob", "Grep", "AstGrep", "WebFetch"]

AGENT_TYPE_CONFIGS: dict[str, AgentDefinition] = {
    "default": AgentDefinition(
        agent_type="default",
        description="General purpose agent for most tasks",
        max_turns=50,
    ),
    "coder": AgentDefinition(
        agent_type="coder",
        description="Code refactoring and implementation specialist",
        allowed_tools=None,
        max_turns=100,
        system_prompt_suffix="Focus on code quality and test coverage.",
    ),
    "explore": AgentDefinition(
        agent_type="explore",
        description="Read-only codebase exploration",
        allowed_tools=READ_ONLY_TOOLS.copy(),
        max_turns=30,
        system_prompt_suffix="You are in READ-ONLY mode. Do not modify files.",
    ),
    "plan": AgentDefinition(
        agent_type="plan",
        description="Architecture and design planning",
        allowed_tools=READ_ONLY_TOOLS.copy(),
        max_turns=30,
        system_prompt_suffix=(
            "Focus on architecture, tradeoffs, and implementation planning."
        ),
    ),
    "quick_task": AgentDefinition(
        agent_type="quick_task",
        description="Fast execution for simple, bounded tasks",
        max_turns=20,
    ),
}


class ToolFilter:
    """Filters available tools based on an agent type definition."""

    def is_allowed(self, tool_name: str, agent_def: AgentDefinition) -> bool:
        """Return whether a tool can be exposed to the given subagent."""
        if tool_name in ALL_AGENT_DISALLOWED_TOOLS:
            return False
        if tool_name in agent_def.disallowed_tools:
            return False
        if agent_def.allowed_tools is not None:
            return tool_name in agent_def.allowed_tools
        return True

    def filter_tools(
        self,
        tools: list[dict[str, Any]],
        agent_def: AgentDefinition,
    ) -> list[dict[str, Any]]:
        """Filter tool definition dictionaries by their ``name`` field."""
        return [
            tool
            for tool in tools
            if self.is_allowed(str(tool.get("name", "")), agent_def)
        ]
