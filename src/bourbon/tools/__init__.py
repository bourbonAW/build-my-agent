"""Tool system for Bourbon agent.

Tools are registered in a central registry and provided to the LLM.
Each tool has a name, description, input schema, and handler function.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable


class RiskLevel(Enum):
    """Risk levels for tool operations."""
    
    LOW = "low"           # Safe exploration, can auto-recover
    MEDIUM = "medium"     # File modifications, ask before alternatives
    HIGH = "high"         # System changes, destructive ops, MUST ask user


# Type for tool handlers
ToolHandler = Callable[..., str]


@dataclass
class Tool:
    """Definition of a tool available to the agent."""

    name: str
    description: str
    input_schema: dict[str, Any]
    handler: ToolHandler
    risk_level: RiskLevel = RiskLevel.LOW
    risk_patterns: list[str] | None = None
    
    def __post_init__(self):
        """Initialize default risk patterns based on risk level."""
        if self.risk_patterns is None:
            if self.risk_level == RiskLevel.HIGH:
                # Default high-risk patterns for bash-like tools
                if self.name == "bash":
                    self.risk_patterns = [
                        "pip install", "pip3 install", "pip uninstall", "pip3 uninstall",
                        "apt ", "apt-get ", "yum ", "brew ", "pacman ", "dnf ",
                        "rm ", "rm -", "rmdir ",
                        "sudo ", "su ",
                        "shutdown", "reboot", "halt", "poweroff",
                        "mkfs.", "fdisk", "dd ",
                        "> /dev", "> /sys", "> /proc",
                        "curl ", "wget ", "| sh", "| bash",
                    ]
                else:
                    self.risk_patterns = []
            else:
                self.risk_patterns = []
    
    def is_high_risk_operation(self, tool_input: dict) -> bool:
        """Check if this specific tool invocation is high-risk.
        
        For bash tool, checks command content against risk patterns.
        For other tools, returns based on risk_level.
        """
        if self.risk_level == RiskLevel.HIGH and self.name == "bash":
            command = tool_input.get("command", "")
            return any(pattern in command for pattern in self.risk_patterns)
        return self.risk_level == RiskLevel.HIGH


class ToolRegistry:
    """Registry of available tools."""

    def __init__(self):
        """Initialize empty registry."""
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register a tool."""
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def get_handler(self, name: str) -> ToolHandler | None:
        """Get a tool handler by name."""
        tool = self._tools.get(name)
        return tool.handler if tool else None
    
    def get_tool(self, name: str) -> Tool | None:
        """Get a full Tool object by name (includes metadata)."""
        return self._tools.get(name)

    def list_tools(self) -> list[Tool]:
        """List all registered tools."""
        return list(self._tools.values())

    def get_tool_definitions(self) -> list[dict]:
        """Get tool definitions for LLM API."""
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema,
            }
            for tool in self._tools.values()
        ]


# Global registry instance
_registry: ToolRegistry | None = None


def get_registry() -> ToolRegistry:
    """Get or create global tool registry."""
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
    return _registry


def register_tool(
    name: str,
    description: str,
    input_schema: dict[str, Any],
    risk_level: RiskLevel = RiskLevel.LOW,
    risk_patterns: list[str] | None = None,
) -> Callable[[ToolHandler], ToolHandler]:
    """Decorator to register a tool function.

    Args:
        name: Tool name
        description: Tool description
        input_schema: JSON schema for tool inputs
        risk_level: Risk level (LOW/MEDIUM/HIGH)
        risk_patterns: Patterns that make operation high-risk (for bash-like tools)

    Example:
        @register_tool(
            name="bash",
            description="Run a shell command",
            input_schema={...},
            risk_level=RiskLevel.HIGH,
        )
        def bash_handler(command: str) -> str:
            ...
    """

    def decorator(func: ToolHandler) -> ToolHandler:
        tool = Tool(
            name=name,
            description=description,
            input_schema=input_schema,
            handler=func,
            risk_level=risk_level,
            risk_patterns=risk_patterns,
        )
        get_registry().register(tool)
        return func

    return decorator


def tool(name: str) -> Tool | None:
    """Get a tool by name."""
    return get_registry().get(name)


def handler(name: str) -> ToolHandler | None:
    """Get a tool handler by name."""
    # Import tool modules to trigger registration
    from bourbon.tools import base, search, skill_tool  # noqa: F401
    
    return get_registry().get_handler(name)


def get_tool_with_metadata(name: str) -> Tool | None:
    """Get a tool with full metadata (including risk level)."""
    # Import tool modules to trigger registration
    from bourbon.tools import base, search, skill_tool  # noqa: F401
    
    return get_registry().get_tool(name)


def definitions() -> list[dict]:
    """Get all tool definitions for LLM."""
    # Import tool modules to trigger registration
    # This must be done lazily to avoid circular imports
    from bourbon.tools import base, search, skill_tool  # noqa: F401
    
    return get_registry().get_tool_definitions()
