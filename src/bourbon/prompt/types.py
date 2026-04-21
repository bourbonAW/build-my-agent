from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from bourbon.mcp_client import MCPManager
    from bourbon.skills import SkillManager


@dataclass
class PromptContext:
    """Runtime context passed to dynamic section factories and ContextInjector."""

    workdir: Path
    skill_manager: "SkillManager | None" = None
    mcp_manager: "MCPManager | None" = None
    memory_manager: Any | None = None


@dataclass
class PromptSection:
    """A named, ordered unit of system prompt content."""

    name: str
    order: int
    content: str | Callable[["PromptContext"], Awaitable[str]]

    @property
    def is_static(self) -> bool:
        return isinstance(self.content, str)
