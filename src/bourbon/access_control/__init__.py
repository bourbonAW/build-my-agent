"""Access control for Bourbon agent tools."""

from __future__ import annotations

from pathlib import Path

from bourbon.access_control.capabilities import (
    CapabilityType,
    infer_capabilities,
)
from bourbon.access_control.policy import PolicyAction, PolicyDecision, PolicyEngine
from bourbon.tools import get_tool_with_metadata


class AccessController:
    """Evaluates tool calls against configured policies."""

    def __init__(self, config: dict, workdir: Path) -> None:
        default_action = PolicyAction(config.get("default_action", "allow"))
        self.engine = PolicyEngine(
            default_action=default_action,
            file_rules=config.get("file", {}),
            command_rules=config.get("command", {}),
            workdir=workdir,
        )

    def evaluate(self, tool_name: str, tool_input: dict) -> PolicyDecision:
        tool_metadata = get_tool_with_metadata(tool_name)
        canonical_name = tool_metadata.name if tool_metadata else tool_name
        # Capabilities come exclusively from Tool.required_capabilities, which is
        # validated at @register_tool decoration time.  There is no static fallback
        # map: unknown/MCP tools that declare no capabilities produce an empty list
        # and fall through to PolicyEngine's default_action.
        base_caps: list[CapabilityType] = (
            list(tool_metadata.required_capabilities or []) if tool_metadata else []
        )
        context = infer_capabilities(canonical_name, tool_input, base_caps)

        if canonical_name == "Bash":
            return self.engine.evaluate_command(tool_input.get("command", ""), context)
        return self.engine.evaluate(canonical_name, context)
