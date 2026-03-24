"""Access control for Bourbon agent tools."""

from __future__ import annotations

from pathlib import Path

from bourbon.access_control.capabilities import (
    CapabilityType,
    infer_capabilities,
)
from bourbon.access_control.policy import PolicyAction, PolicyDecision, PolicyEngine

_TOOL_CAPABILITIES: dict[str, list[CapabilityType]] = {
    "bash": [CapabilityType.EXEC],
    "read_file": [CapabilityType.FILE_READ],
    "write_file": [CapabilityType.FILE_WRITE],
    "edit_file": [CapabilityType.FILE_WRITE],
    "skill": [CapabilityType.SKILL],
    "rg_search": [CapabilityType.FILE_READ],
    "ast_grep_search": [CapabilityType.FILE_READ],
}


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
        base_caps = _TOOL_CAPABILITIES.get(tool_name, [])
        context = infer_capabilities(tool_name, tool_input, base_caps)

        if tool_name == "bash":
            return self.engine.evaluate_command(tool_input.get("command", ""), context)
        return self.engine.evaluate(tool_name, context)
