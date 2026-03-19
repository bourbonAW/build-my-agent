"""Tool system for Bourbon agent.

Tools are registered in a central registry and provided to the LLM.
Each tool has a name, description, input schema, and handler function.
"""

from dataclasses import dataclass
from typing import Any, Callable

# Type for tool handlers
ToolHandler = Callable[..., str]


@dataclass
class Tool:
    """Definition of a tool available to the agent."""

    name: str
    description: str
    input_schema: dict[str, Any]
    handler: ToolHandler


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
) -> Callable[[ToolHandler], ToolHandler]:
    """Decorator to register a tool function.

    Example:
        @register_tool(
            name="bash",
            description="Run a shell command",
            input_schema={...},
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
        )
        get_registry().register(tool)
        return func

    return decorator


def tool(name: str) -> Tool | None:
    """Get a tool by name."""
    return get_registry().get(name)


def handler(name: str) -> ToolHandler | None:
    """Get a tool handler by name."""
    return get_registry().get_handler(name)


def definitions() -> list[dict]:
    """Get all tool definitions for LLM."""
    return get_registry().get_tool_definitions()
