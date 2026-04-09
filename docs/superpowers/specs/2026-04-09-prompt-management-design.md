# Prompt Management Module Design

> Date: 2026-04-09
> Status: Draft
> Topic: Refactor bourbon's prompt management into a dedicated async-native `src/bourbon/prompt/` package

---

## Overview

Bourbon's current prompt management is a monolithic method `_build_system_prompt()` in `agent.py`. It hardcodes all system prompt content inline, rebuilds only on MCP initialization, has no static/dynamic separation, no priority/override mechanism, and no environment context injection per conversation turn.

This design introduces a dedicated `src/bourbon/prompt/` package that is async-native, modular, and structured after the architectural patterns in Claude Code's prompt system.

**Goals:**
- Extract prompt logic into a standalone, testable module
- Separate static sections (built once) from dynamic sections (rebuilt each `build()` call)
- Implement two-layer priority: `custom_prompt` replaces defaults; `append_prompt` appends
- Inject environment context (workdir, date, git status) into each user message via `<system-reminder>`
- Write the module as async-native, ready for the upcoming full-stack async migration

**Non-goals:**
- Section-level caching (deferred to future)
- API-level `cache_control` markers (deferred to future)
- Async migration of `Agent`, `LLMClient`, or `REPL` (separate task)
- Per-turn `git status` caching — accepted known cost (~5ms per turn); deferred optimization

---

## Module Structure

```
src/bourbon/prompt/
├── __init__.py       # Public API: PromptBuilder, PromptSection, PromptContext, ContextInjector, ALL_SECTIONS
├── types.py          # Core type definitions
├── builder.py        # PromptBuilder (async build)
├── sections.py       # Built-in static sections
├── dynamic.py        # Async dynamic section factories (skills, MCP)
└── context.py        # ContextInjector: git/date → <system-reminder>
```

---

## Type Definitions (`types.py`)

```python
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Callable, Awaitable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bourbon.skills import SkillManager
    from bourbon.mcp_client import MCPManager


@dataclass
class PromptContext:
    """Runtime context passed to dynamic section factories and ContextInjector."""
    workdir: Path
    skill_manager: "SkillManager | None" = None
    mcp_manager: "MCPManager | None" = None


@dataclass
class PromptSection:
    """A named, ordered unit of system prompt content.

    If `content` is a string, it is static (computed once at definition time).
    If `content` is a callable, it is dynamic (awaited on each build() call).
    """
    name: str
    order: int
    content: str | Callable[["PromptContext"], Awaitable[str]]

    @property
    def is_static(self) -> bool:
        return isinstance(self.content, str)
```

---

## PromptBuilder (`builder.py`)

```python
class PromptBuilder:
    """Assembles system prompt from ordered sections.

    Priority:
    1. If custom_prompt is set, it replaces all default sections entirely.
    2. append_prompt (if set) is always appended after the base content.
    """

    def __init__(
        self,
        sections: list[PromptSection],
        custom_prompt: str | None = None,
        append_prompt: str | None = None,
    ) -> None:
        self._sections = sorted(sections, key=lambda s: s.order)
        self._custom_prompt = custom_prompt
        self._append_prompt = append_prompt

    async def build(self, ctx: PromptContext) -> str:
        # Use `is not None` to allow empty string as a valid custom prompt
        if self._custom_prompt is not None:
            base = self._custom_prompt
        else:
            base = await self._assemble_sections(ctx)

        if self._append_prompt is not None:
            base = base + "\n\n" + self._append_prompt

        return base

    async def _assemble_sections(self, ctx: PromptContext) -> str:
        parts: list[str] = []
        for section in self._sections:
            if section.is_static:
                text = section.content
            else:
                text = await section.content(ctx)
            if text:
                parts.append(text)
        return "\n\n".join(parts)
```

---

## Sections (`sections.py`)

Sections fall into two kinds based on their `content` field type:

- **Static** (`content: str`): hardcoded string, evaluated once at module import time
- **Dynamic** (`content: Callable`): async factory called on each `build()`, receives `PromptContext`

Both kinds can appear in `DEFAULT_SECTIONS` — the distinction is about content evaluation timing, not about which list a section belongs to.

| order | name | Kind | Summary |
|-------|------|------|---------|
| 10 | `identity` | dynamic | "You are Bourbon, working in {workdir}." — needs `ctx.workdir` at build time |
| 20 | `task_guidelines` | static | Use TodoWrite; no repeated actions; always invoke tools |
| 30 | `error_handling` | static | HIGH/MEDIUM/LOW risk rules matching current `_build_system_prompt()` content |
| 40 | `task_adaptability` | static | Coding / investment / data / general task hints |

`identity` is dynamic because it embeds `ctx.workdir`:

```python
async def identity_section(ctx: PromptContext) -> str:
    return (
        f"You are Bourbon, a general-purpose AI assistant working in {ctx.workdir}.\n\n"
        "You can help with coding, data analysis, investment research, writing, "
        "and general knowledge work.\n\n"
        "You have access to:\n"
        "- Built-in tools for file operations, code search, and execution\n"
        "- Specialized Skills for domain-specific tasks\n"
        "- MCP tools for external integrations (databases, APIs, etc.)"
    )

IDENTITY = PromptSection(name="identity", order=10, content=identity_section)
```

`DEFAULT_SECTIONS` contains all four sections above (including the dynamic `identity`). The `DYNAMIC_SECTIONS` list in `dynamic.py` contains the skills and MCP sections.

---

## Dynamic Sections (`dynamic.py`)

```python
async def skills_section(ctx: PromptContext) -> str:
    """Returns skills catalog from SkillManager, or empty string if none."""
    if not ctx.skill_manager:
        return ""
    catalog = ctx.skill_manager.get_catalog()
    if not catalog:
        return ""
    # Note: activation instruction format simplified from the XML <function_calls>
    # example in the old _get_skills_section() — relies on LLM understanding
    # "use the Skill tool" from tool definitions, which is cleaner and sufficient.
    return "\n".join([
        "SKILLS",
        "======",
        "",
        "The following skills provide specialized instructions for specific tasks.",
        "When a task matches a skill's description, use the 'Skill' tool to load",
        "its full instructions before proceeding.",
        "",
        catalog,
    ])


async def mcp_tools_section(ctx: PromptContext) -> str:
    """Returns MCP tools listing grouped by server, or empty string if none."""
    if not ctx.mcp_manager:
        return ""
    summary = ctx.mcp_manager.get_connection_summary()
    if not summary.get("enabled") or summary.get("total_tools", 0) == 0:
        return ""
    mcp_tools = ctx.mcp_manager.list_mcp_tools()
    if not mcp_tools:
        return ""

    # MCPManager registers tools as "{server_name}-{tool_name}" (hyphen separator,
    # not colon) for LLM compatibility — see mcp_client/manager.py.
    # To group by server without ambiguity (server names may contain "-"),
    # match against known server prefixes rather than splitting blindly.
    server_names = [s.name for s in ctx.mcp_manager.config.servers]
    server_tools: dict[str, list[str]] = {}
    for tool_name in mcp_tools:
        matched_server = next(
            (s for s in server_names if tool_name.startswith(f"{s}-")), None
        )
        if matched_server:
            tool = tool_name[len(matched_server) + 1:]
            server_tools.setdefault(matched_server, []).append(tool)

    lines = [
        "MCP TOOLS",
        "=========",
        "",
        "The following external tools are available from MCP servers:",
        "",
    ]
    for server, tools in sorted(server_tools.items()):
        lines.append(f"  {server}:")
        for t in sorted(tools):
            lines.append(f"    - {server}-{t}")
        lines.append("")
    lines.append("Use these tools just like any other tool.")
    return "\n".join(lines)


DYNAMIC_SECTIONS: list[PromptSection] = [
    PromptSection(name="skills", order=60, content=skills_section),
    PromptSection(name="mcp_tools", order=70, content=mcp_tools_section),
]
```

---

## ContextInjector (`context.py`)

Injects environment context (workdir, date, git status) into each user message as a `<system-reminder>` block, following Claude Code's pattern of wrapping dynamic per-turn context in user messages rather than rebuilding the system prompt.

```python
import asyncio
from pathlib import Path
from datetime import date


class ContextInjector:
    """Prepends <system-reminder> with env context to each user message."""

    async def inject(self, user_message: str, ctx: PromptContext) -> str:
        env_info = await self._get_env_info(ctx)
        reminder = f"<system-reminder>\n{env_info}\n</system-reminder>"
        return f"{reminder}\n{user_message}"

    async def _get_env_info(self, ctx: PromptContext) -> str:
        parts = [
            f"Working directory: {ctx.workdir}",
            f"Today's date: {date.today().isoformat()}",
        ]
        git_info = await self._get_git_status(ctx.workdir)
        if git_info:
            parts.append(f"Git status:\n{git_info}")
        return "\n".join(parts)

    async def _get_git_status(self, workdir: Path) -> str | None:
        try:
            proc = await asyncio.create_subprocess_exec(
                "git", "-C", str(workdir), "status", "--short", "-b",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await proc.communicate()
            if proc.returncode == 0:
                return stdout.decode().strip()
            return None
        except Exception:
            return None
```

**Output example:**
```
<system-reminder>
Working directory: /home/hf/github_project/build-my-agent
Today's date: 2026-04-09
Git status:
## master
 M src/bourbon/agent.py
?? wiki/session-message-system.md
</system-reminder>
```

---

## Public API (`__init__.py`)

```python
from bourbon.prompt.types import PromptContext, PromptSection
from bourbon.prompt.builder import PromptBuilder
from bourbon.prompt.context import ContextInjector
from bourbon.prompt.sections import DEFAULT_SECTIONS
from bourbon.prompt.dynamic import DYNAMIC_SECTIONS

ALL_SECTIONS = DEFAULT_SECTIONS + DYNAMIC_SECTIONS

__all__ = [
    "PromptBuilder",
    "PromptSection",
    "PromptContext",
    "ContextInjector",
    "ALL_SECTIONS",
    "DEFAULT_SECTIONS",
    "DYNAMIC_SECTIONS",
]
```

---

## Agent Integration (`agent.py` changes)

**Removed:**
- `_build_system_prompt()` method
- `_get_skills_section()` method
- `_get_mcp_section()` method
- Manual `self.system_prompt = self._build_system_prompt()` in `_finalize_mcp_initialization()`

**Added in `__init__`:**
```python
from bourbon.prompt import ALL_SECTIONS, PromptBuilder, PromptContext, ContextInjector
from bourbon.tools import _get_async_runtime  # existing AsyncRuntime bridge

self._prompt_ctx = PromptContext(
    workdir=self.workdir,
    skill_manager=self.skills,
    mcp_manager=self.mcp,
)
self._prompt_builder = PromptBuilder(
    sections=ALL_SECTIONS,
    custom_prompt=system_prompt,   # None = use default sections
    append_prompt=None,            # Not exposed via Agent.__init__ yet; reserved for future use
)
self._context_injector = ContextInjector()

# Bridge async → sync during transition period.
# _get_async_runtime() returns the shared AsyncRuntime singleton from bourbon.tools.
# Removed once full-stack async migration lands (separate task).
self.system_prompt = _get_async_runtime().run(
    self._prompt_builder.build(self._prompt_ctx)
)
```

**In `step()` and `step_stream()`:**
```python
# Rebuild system prompt each turn (dynamic sections — skills, MCP — refresh automatically)
self.system_prompt = _get_async_runtime().run(
    self._prompt_builder.build(self._prompt_ctx)
)

# Inject env context: creates enriched string for LLM only.
# The original user_input (without injection) is stored in the transcript via session.add_message().
# enriched_input is passed to the LLM as the final user turn in _run_conversation_loop().
enriched_input = _get_async_runtime().run(
    self._context_injector.inject(user_input, self._prompt_ctx)
)
# session.add_message() uses original user_input (for clean transcript storage)
# LLM receives enriched_input (with system-reminder prepended)
```

**`_finalize_mcp_initialization()` simplification:**
```python
def _finalize_mcp_initialization(self, results: dict) -> dict:
    # No manual rebuild needed; next step() call will rebuild automatically
    return results
```

---

## Data Flow

```
Agent.__init__()
  └─ PromptBuilder(ALL_SECTIONS, custom_prompt?)
       └─ build(PromptContext) ──async──► str  →  self.system_prompt

Agent.step(user_input)
  ├─ PromptBuilder.build(ctx) ──async──► system_prompt  (refreshes dynamic sections)
  ├─ ContextInjector.inject(user_input, ctx) ──async──► enriched user message
  └─ LLM.chat(messages, system=system_prompt)
```

---

## Testing Strategy

Each component is independently testable:

- **`types.py`**: Pure dataclasses, no test needed beyond import checks
- **`builder.py`**: Test with mock sections (static + dynamic), verify ordering, custom_prompt override, append_prompt behavior
- **`sections.py`**: Snapshot tests for section content
- **`dynamic.py`**: Unit tests with mock `SkillManager` / `MCPManager`
- **`context.py`**: Test git detection (mock subprocess), date injection, fallback when not a git repo, empty `user_message` edge case
- **`agent.py` integration**: Existing tests continue to work; verify system_prompt is rebuilt on each step

---

## Migration Path

1. Create `src/bourbon/prompt/` with all new files
2. Update `agent.py` to use new module (delete 3 methods, add 3 attributes)
3. Run existing test suite — minor behavior differences to expect:
   - When no skills are available, system prompt no longer contains `"(No skills available)"` (now omitted entirely)
   - System prompt is now rebuilt on every `step()` call, not just at init/MCP connect
   - Skills activation instruction format simplified: XML `<function_calls>` example removed; LLM relies on tool definitions
   - **Bug fix**: `_get_mcp_section()` in `agent.py` never rendered any tools (used `:` separator while tools use `-`). New `mcp_tools_section()` correctly uses `-`, so MCP tools will now appear in the system prompt for the first time
4. When full-stack async migration lands, remove `_get_async_runtime().run(...)` wrappers (separate cleanup ticket)

---

## Files Changed

| File | Change |
|------|--------|
| `src/bourbon/prompt/__init__.py` | New |
| `src/bourbon/prompt/types.py` | New |
| `src/bourbon/prompt/builder.py` | New |
| `src/bourbon/prompt/sections.py` | New |
| `src/bourbon/prompt/dynamic.py` | New |
| `src/bourbon/prompt/context.py` | New |
| `src/bourbon/agent.py` | Remove 3 methods, add 3 attributes, update step() |
