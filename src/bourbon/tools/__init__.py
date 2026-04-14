"""Tool system for Bourbon agent.

Tools are registered in a central registry and provided to the LLM.
Each tool has a name, description, input schema, and handler function.
"""

import inspect
from collections.abc import Callable, Coroutine
from contextlib import suppress
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, cast

ToolInput = dict[str, Any]
ToolDefinition = dict[str, Any]


class RiskLevel(Enum):
    """Risk levels for tool operations."""

    LOW = "low"  # Safe exploration, can auto-recover
    MEDIUM = "medium"  # File modifications, ask before alternatives
    HIGH = "high"  # System changes, destructive ops, MUST ask user


# Type for tool handlers
ToolHandler = Callable[..., str | Coroutine[Any, Any, str]]

_async_runtime: Any | None = None


def _get_async_runtime() -> Any:
    """Get a shared async runtime without importing MCP modules at import time."""
    global _async_runtime
    if _async_runtime is None:
        from bourbon.mcp_client.runtime import AsyncRuntime

        _async_runtime = AsyncRuntime()
    return _async_runtime


@dataclass
class ToolContext:
    """Execution context shared across tool handlers."""

    workdir: Path
    agent: Any | None = None
    execution_markers: set[str] = field(default_factory=set)
    skill_manager: Any | None = None
    on_tools_discovered: Callable[[set[str]], None] | None = None


@dataclass
class Tool:
    """Definition of a tool available to the agent."""

    name: str
    description: str
    input_schema: ToolDefinition
    handler: ToolHandler
    risk_level: RiskLevel = RiskLevel.LOW
    risk_patterns: list[str] | None = None
    required_capabilities: list[str] | None = None
    aliases: list[str] = field(default_factory=list)
    always_load: bool = True
    should_defer: bool = False
    is_concurrency_safe: bool = False
    _concurrency_fn: Callable[[ToolInput], bool] | None = field(default=None, repr=False)
    is_read_only: bool = False
    is_destructive: bool = False
    search_hint: str | None = None

    def __post_init__(self) -> None:
        """Initialize default risk patterns and validate capability declarations."""
        # Enforce that deferred tools are never unconditionally loaded.
        if self.should_defer and self.always_load:
            raise ValueError(
                f"Tool '{self.name}': should_defer=True implies always_load=False; "
                "set always_load=False explicitly."
            )

        # Validate and normalise required_capabilities at construction time so
        # typos in @register_tool decorators are caught at import, not at runtime.
        if self.required_capabilities is not None:
            from bourbon.access_control.capabilities import CapabilityType

            try:
                self.required_capabilities = [
                    CapabilityType(cap) for cap in self.required_capabilities
                ]
            except ValueError as exc:
                raise ValueError(
                    f"Tool '{self.name}' declared an unknown capability: {exc}"
                ) from exc

        if self.risk_patterns is None:
            if self.risk_level == RiskLevel.HIGH and self.is_destructive:
                self.risk_patterns = [
                    "pip install",
                    "pip3 install",
                    "pip uninstall",
                    "pip3 uninstall",
                    "apt ",
                    "apt-get ",
                    "yum ",
                    "brew ",
                    "pacman ",
                    "dnf ",
                    "rm ",
                    "rm -",
                    "rmdir ",
                    "sudo ",
                    "su ",
                    "shutdown",
                    "reboot",
                    "halt",
                    "poweroff",
                    "mkfs.",
                    "fdisk",
                    "dd ",
                    "> /dev",
                    "> /sys",
                    "> /proc",
                    "curl ",
                    "wget ",
                    "| sh",
                    "| bash",
                ]
            else:
                self.risk_patterns = []

    def concurrent_safe_for(self, tool_input: ToolInput) -> bool:
        """Return whether this tool can run concurrently for the given input.

        _concurrency_fn takes priority over is_concurrency_safe bool.
        Returns False if the function raises.
        """
        if self._concurrency_fn is not None:
            try:
                return bool(self._concurrency_fn(tool_input))
            except Exception:
                return False
        return self.is_concurrency_safe

    def is_high_risk_operation(self, tool_input: ToolInput) -> bool:
        """Check if this specific tool invocation is high-risk.

        For bash tool, checks command content against risk patterns.
        For other tools, returns based on risk_level.
        """
        if self.risk_level == RiskLevel.HIGH and self.is_destructive:
            command = tool_input.get("command", "")
            return any(pattern in command for pattern in self.risk_patterns or [])
        return self.risk_level == RiskLevel.HIGH


class ToolRegistry:
    """Registry of available tools."""

    def __init__(self) -> None:
        """Initialize empty registry."""
        self._tools: dict[str, Tool] = {}
        self._alias_map: dict[str, str] = {}

    def register(self, tool: Tool) -> None:
        """Register a tool."""
        self._tools[tool.name] = tool
        for alias in tool.aliases:
            self._alias_map[alias] = tool.name

    def _resolve(self, name: str) -> Tool | None:
        """Resolve a tool by canonical name or alias."""
        if name in self._tools:
            return self._tools[name]
        canonical = self._alias_map.get(name)
        return self._tools.get(canonical) if canonical else None

    def get(self, name: str) -> Tool | None:
        """Get a tool by name."""
        return self._resolve(name)

    def get_handler(self, name: str) -> ToolHandler | None:
        """Get a tool handler by name."""
        tool = self._resolve(name)
        return tool.handler if tool else None

    def get_tool(self, name: str) -> Tool | None:
        """Get a full Tool object by name (includes metadata)."""
        return self._resolve(name)

    def list_tools(self) -> list[Tool]:
        """List all registered tools."""
        return list(self._tools.values())

    def call(self, name: str, tool_input: ToolInput, ctx: ToolContext) -> str:
        """Call a tool handler with a shared execution context."""
        tool = self._resolve(name)
        if not tool:
            return f"Error: Unknown tool '{name}'"

        result = tool.handler(**tool_input, ctx=ctx)
        if inspect.isawaitable(result):
            return cast(str, _get_async_runtime().run(result))
        return result

    def get_tool_definitions(
        self,
        discovered: set[str] | None = None,
    ) -> list[ToolDefinition]:
        """Get tool definitions for LLM API."""
        discovered = discovered or set()
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema,
            }
            for tool in self._tools.values()
            if tool.always_load or tool.name in discovered
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
    input_schema: ToolDefinition,
    risk_level: RiskLevel = RiskLevel.LOW,
    risk_patterns: list[str] | None = None,
    required_capabilities: list[str] | None = None,
    aliases: list[str] | None = None,
    always_load: bool = True,
    should_defer: bool = False,
    is_concurrency_safe: bool = False,
    concurrency_fn: Callable[[ToolInput], bool] | None = None,
    is_read_only: bool = False,
    is_destructive: bool = False,
    search_hint: str | None = None,
) -> Callable[[ToolHandler], ToolHandler]:
    """Decorator to register a tool function.

    Args:
        name: Canonical tool name (PascalCase, e.g. "Bash", "Read")
        description: Tool description shown in LLM tool list
        input_schema: JSON schema for tool inputs
        risk_level: Risk level (LOW/MEDIUM/HIGH)
        risk_patterns: Patterns that make operation high-risk (for bash-like tools)
        required_capabilities: Access control capabilities required (e.g. ["exec"])
        aliases: Legacy names that resolve to this tool (e.g. ["bash", "run_bash"])
        always_load: If True, included in every LLM call's tool list (default True)
        should_defer: If True, tool is hidden until discovered via ToolSearch;
            implies always_load=False
        is_concurrency_safe: If True, tool can be called concurrently with others
        is_read_only: If True, tool makes no side-effects (safe for parallel use)
        is_destructive: If True, enables automatic risk_patterns population for HIGH-risk tools
        search_hint: Extra keywords for ToolSearch scoring (space-separated)

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
            required_capabilities=required_capabilities,
            aliases=aliases or [],
            always_load=always_load,
            should_defer=should_defer,
            is_concurrency_safe=is_concurrency_safe,
            _concurrency_fn=concurrency_fn,
            is_read_only=is_read_only,
            is_destructive=is_destructive,
            search_hint=search_hint,
        )
        get_registry().register(tool)
        return func

    return decorator


def tool(name: str) -> Tool | None:
    """Get a tool by name."""
    return get_registry().get(name)


def _ensure_imports() -> None:
    """Lazily import tool modules to trigger registration."""
    from bourbon.tools import (  # noqa: F401
        agent_tool,
        base,
        search,
        skill_tool,
        task_tools,
        tool_search,
    )

    with suppress(ImportError):
        from bourbon.tools import web  # noqa: F401
    with suppress(ImportError):
        from bourbon.tools import data  # noqa: F401
    with suppress(ImportError):
        from bourbon.tools import documents  # noqa: F401


def handler(name: str) -> ToolHandler | None:
    """Get a tool handler by name."""
    _ensure_imports()
    return get_registry().get_handler(name)


def get_tool_with_metadata(name: str) -> Tool | None:
    """Get a tool with full metadata (including risk level)."""
    _ensure_imports()
    return get_registry().get_tool(name)


def definitions(discovered: set[str] | None = None) -> list[ToolDefinition]:
    """Get all tool definitions for LLM."""
    _ensure_imports()
    return get_registry().get_tool_definitions(discovered=discovered)
