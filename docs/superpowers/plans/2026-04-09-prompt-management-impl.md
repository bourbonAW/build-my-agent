# Prompt Management Module Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract prompt logic from `agent.py` into a dedicated async-native `src/bourbon/prompt/` package with static/dynamic section separation, two-layer priority override, and per-turn environment context injection.

**Architecture:** Create a `src/bourbon/prompt/` package with five modules (`types.py`, `builder.py`, `sections.py`, `dynamic.py`, `context.py`) and a public `__init__.py`. The `PromptBuilder` assembles ordered `PromptSection` objects (static strings or async callables); `ContextInjector` prepends a `<system-reminder>` to each human-authored user message. Agent uses `_get_async_runtime().run()` to bridge async → sync during the transition period.

**Tech Stack:** Python 3.12, asyncio, dataclasses, `bourbon.tools._get_async_runtime` (existing AsyncRuntime bridge), pytest + pytest-asyncio

---

## File Structure

**New files:**
- `src/bourbon/prompt/__init__.py` — public API re-exports
- `src/bourbon/prompt/types.py` — `PromptContext`, `PromptSection` dataclasses
- `src/bourbon/prompt/builder.py` — `PromptBuilder` async build logic
- `src/bourbon/prompt/sections.py` — `DEFAULT_SECTIONS` (identity, task_guidelines, error_handling, task_adaptability)
- `src/bourbon/prompt/dynamic.py` — `DYNAMIC_SECTIONS` (skills, mcp_tools)
- `src/bourbon/prompt/context.py` — `ContextInjector` (git/date → `<system-reminder>`)
- `tests/test_prompt_builder.py` — unit tests for builder
- `tests/test_prompt_sections.py` — snapshot tests for static sections
- `tests/test_prompt_dynamic.py` — unit tests for dynamic sections
- `tests/test_prompt_context.py` — unit tests for ContextInjector
- `tests/test_prompt_agent_integration.py` — agent-level integration tests (step() rebuild, enriched session message, pending_confirmation path)

**Modified files:**
- `src/bourbon/agent.py` — remove 3 methods, add 3 attributes, update `step()` and `step_stream()`
- `tests/test_agent_error_policy.py` — update fixture and assertions
- `tests/test_mcp_sync_runtime.py` — update fixture and assertions
- `tests/test_agent_streaming.py` — add 3 prompt attributes to `__new__` fixture
- `tests/test_debug_logging.py` — add 3 prompt attributes to `__new__` fixture

---

## Task 1: Create `types.py`

**Files:**
- Create: `src/bourbon/prompt/types.py`

- [ ] **Step 1: Write the file**

```python
# src/bourbon/prompt/types.py
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

- [ ] **Step 2: Verify it imports cleanly**

```bash
cd /home/hf/github_project/build-my-agent
python -c "from bourbon.prompt.types import PromptContext, PromptSection; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/bourbon/prompt/types.py
git commit -m "feat(prompt): add PromptContext and PromptSection type definitions"
```

---

## Task 2: Create `builder.py`

**Files:**
- Create: `src/bourbon/prompt/builder.py`
- Create: `tests/test_prompt_builder.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_prompt_builder.py
import asyncio
from pathlib import Path
from bourbon.prompt.types import PromptContext, PromptSection
from bourbon.prompt.builder import PromptBuilder


CTX = PromptContext(workdir=Path("/tmp/test"))


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_static_sections_assembled_in_order():
    sections = [
        PromptSection(name="b", order=20, content="second"),
        PromptSection(name="a", order=10, content="first"),
    ]
    builder = PromptBuilder(sections=sections)
    result = run(builder.build(CTX))
    assert result.index("first") < result.index("second")


def test_dynamic_section_called_with_context():
    calls = []

    async def factory(ctx: PromptContext) -> str:
        calls.append(ctx)
        return "dynamic content"

    sections = [PromptSection(name="dyn", order=10, content=factory)]
    builder = PromptBuilder(sections=sections)
    result = run(builder.build(CTX))
    assert result == "dynamic content"
    assert calls[0] is CTX


def test_custom_prompt_replaces_all_sections():
    sections = [PromptSection(name="a", order=10, content="should not appear")]
    builder = PromptBuilder(sections=sections, custom_prompt="custom")
    result = run(builder.build(CTX))
    assert result == "custom"
    assert "should not appear" not in result


def test_empty_string_custom_prompt_is_valid():
    sections = [PromptSection(name="a", order=10, content="should not appear")]
    builder = PromptBuilder(sections=sections, custom_prompt="")
    result = run(builder.build(CTX))
    assert result == ""


def test_append_prompt_appended_after_base():
    sections = [PromptSection(name="a", order=10, content="base")]
    builder = PromptBuilder(sections=sections, append_prompt="extra")
    result = run(builder.build(CTX))
    assert result == "base\n\nextra"


def test_append_prompt_appended_after_custom_prompt():
    builder = PromptBuilder(sections=[], custom_prompt="custom", append_prompt="extra")
    result = run(builder.build(CTX))
    assert result == "custom\n\nextra"


def test_empty_section_content_excluded():
    async def empty_factory(ctx: PromptContext) -> str:
        return ""

    sections = [
        PromptSection(name="a", order=10, content="present"),
        PromptSection(name="b", order=20, content=empty_factory),
    ]
    builder = PromptBuilder(sections=sections)
    result = run(builder.build(CTX))
    assert result == "present"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /home/hf/github_project/build-my-agent
pytest tests/test_prompt_builder.py -v 2>&1 | head -30
```

Expected: `ModuleNotFoundError: No module named 'bourbon.prompt.builder'`

- [ ] **Step 3: Write `builder.py`**

```python
# src/bourbon/prompt/builder.py
from bourbon.prompt.types import PromptContext, PromptSection


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

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd /home/hf/github_project/build-my-agent
pytest tests/test_prompt_builder.py -v
```

Expected: `7 passed`

- [ ] **Step 5: Commit**

```bash
git add src/bourbon/prompt/builder.py tests/test_prompt_builder.py
git commit -m "feat(prompt): add PromptBuilder with static/dynamic section assembly"
```

---

## Task 3: Create `sections.py`

**Files:**
- Create: `src/bourbon/prompt/sections.py`
- Create: `tests/test_prompt_sections.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_prompt_sections.py
import asyncio
from pathlib import Path
from bourbon.prompt.sections import DEFAULT_SECTIONS, IDENTITY, TASK_GUIDELINES, ERROR_HANDLING, TASK_ADAPTABILITY
from bourbon.prompt.types import PromptContext

CTX = PromptContext(workdir=Path("/home/user/myproject"))


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_default_sections_has_four_entries():
    assert len(DEFAULT_SECTIONS) == 4


def test_identity_is_dynamic():
    assert not IDENTITY.is_static


def test_task_guidelines_is_static():
    assert TASK_GUIDELINES.is_static


def test_error_handling_is_static():
    assert ERROR_HANDLING.is_static


def test_task_adaptability_is_static():
    assert TASK_ADAPTABILITY.is_static


def test_identity_contains_workdir():
    result = run(IDENTITY.content(CTX))
    assert str(CTX.workdir) in result
    assert "Bourbon" in result


def test_task_guidelines_contains_todo():
    assert "TodoWrite" in TASK_GUIDELINES.content


def test_error_handling_contains_risk_levels():
    assert "HIGH RISK" in ERROR_HANDLING.content
    assert "LOW RISK" in ERROR_HANDLING.content
    assert "MEDIUM RISK" in ERROR_HANDLING.content
    assert "CRITICAL ERROR HANDLING RULES" in ERROR_HANDLING.content


def test_sections_ordered_correctly():
    orders = [s.order for s in DEFAULT_SECTIONS]
    assert orders == sorted(orders)
    assert IDENTITY.order == 10
    assert TASK_GUIDELINES.order == 20
    assert ERROR_HANDLING.order == 30
    assert TASK_ADAPTABILITY.order == 40
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /home/hf/github_project/build-my-agent
pytest tests/test_prompt_sections.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'bourbon.prompt.sections'`

- [ ] **Step 3: Write `sections.py`**

```python
# src/bourbon/prompt/sections.py
from bourbon.prompt.types import PromptContext, PromptSection


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

TASK_GUIDELINES = PromptSection(
    name="task_guidelines",
    order=20,
    content=(
        "When working on multi-step tasks, use TodoWrite to track progress.\n\n"
        "IMPORTANT: Do not repeat the same actions. If you've already explored or analyzed,\n"
        "provide a summary and move forward. Avoid getting stuck in loops.\n\n"
        "CRITICAL: When you want to use a tool, you MUST use the tool_calls format.\n"
        "Do not just describe what you plan to do - actually invoke the tools."
    ),
)

ERROR_HANDLING = PromptSection(
    name="error_handling",
    order=30,
    content=(
        "CRITICAL ERROR HANDLING RULES:\n"
        "1. HIGH RISK operations (software install/uninstall, version changes, "
        "system commands, destructive operations):\n"
        "   - If the operation fails (e.g., version not found, package unavailable), "
        "you MUST STOP and ask the user for confirmation\n"
        "   - NEVER automatically switch versions, install alternatives, or change "
        "parameters without user approval\n"
        "   - Examples: pip install package==wrong_version, apt install "
        "nonexistent-package, rm important-files\n"
        "\n"
        "2. LOW RISK operations (Read, Grep, AstGrep, Glob, exploration):\n"
        "   - If a file is not found, you MAY search for similar files and "
        "attempt to read the correct one\n"
        "   - If search returns no results, you MAY adjust patterns and retry\n"
        "   - Always report what you found and what action you took\n"
        "\n"
        "3. MEDIUM RISK operations (file modifications):\n"
        "   - If write/edit fails, report the error and ask before attempting alternatives"
    ),
)

TASK_ADAPTABILITY = PromptSection(
    name="task_adaptability",
    order=40,
    content=(
        "TASK ADAPTABILITY:\n"
        "- For coding tasks: Use code search, file editing, and testing tools\n"
        "- For investment tasks: Activate investment-agent skill for portfolio analysis\n"
        "- For data tasks: Use file operations and data processing tools\n"
        "- For general questions: Use your knowledge and available tools as needed"
    ),
)

DEFAULT_SECTIONS: list[PromptSection] = [
    IDENTITY,
    TASK_GUIDELINES,
    ERROR_HANDLING,
    TASK_ADAPTABILITY,
]
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd /home/hf/github_project/build-my-agent
pytest tests/test_prompt_sections.py -v
```

Expected: `10 passed`

- [ ] **Step 5: Commit**

```bash
git add src/bourbon/prompt/sections.py tests/test_prompt_sections.py
git commit -m "feat(prompt): add DEFAULT_SECTIONS (identity, task_guidelines, error_handling, task_adaptability)"
```

---

## Task 4: Create `dynamic.py`

**Files:**
- Create: `src/bourbon/prompt/dynamic.py`
- Create: `tests/test_prompt_dynamic.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_prompt_dynamic.py
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from bourbon.prompt.dynamic import skills_section, mcp_tools_section, DYNAMIC_SECTIONS
from bourbon.prompt.types import PromptContext


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_skills_section_returns_empty_when_no_manager():
    ctx = PromptContext(workdir=Path("/tmp"), skill_manager=None)
    result = run(skills_section(ctx))
    assert result == ""


def test_skills_section_returns_empty_when_catalog_empty():
    mock_skills = MagicMock()
    mock_skills.get_catalog.return_value = ""
    ctx = PromptContext(workdir=Path("/tmp"), skill_manager=mock_skills)
    result = run(skills_section(ctx))
    assert result == ""


def test_skills_section_returns_catalog_content():
    mock_skills = MagicMock()
    mock_skills.get_catalog.return_value = "my-skill: Does something"
    ctx = PromptContext(workdir=Path("/tmp"), skill_manager=mock_skills)
    result = run(skills_section(ctx))
    assert "SKILLS" in result
    assert "my-skill: Does something" in result
    assert "Skill" in result  # activation instruction mentions Skill tool


def test_mcp_tools_section_returns_empty_when_no_manager():
    ctx = PromptContext(workdir=Path("/tmp"), mcp_manager=None)
    result = run(mcp_tools_section(ctx))
    assert result == ""


def test_mcp_tools_section_returns_empty_when_disabled():
    mock_mcp = MagicMock()
    mock_mcp.get_connection_summary.return_value = {"enabled": False, "total_tools": 0}
    ctx = PromptContext(workdir=Path("/tmp"), mcp_manager=mock_mcp)
    result = run(mcp_tools_section(ctx))
    assert result == ""


def test_mcp_tools_section_returns_empty_when_no_tools():
    mock_mcp = MagicMock()
    mock_mcp.get_connection_summary.return_value = {"enabled": True, "total_tools": 0}
    ctx = PromptContext(workdir=Path("/tmp"), mcp_manager=mock_mcp)
    result = run(mcp_tools_section(ctx))
    assert result == ""


def test_mcp_tools_section_groups_tools_by_server():
    mock_mcp = MagicMock()
    mock_mcp.get_connection_summary.return_value = {"enabled": True, "total_tools": 2}
    mock_mcp.list_mcp_tools.return_value = ["myserver-tool1", "myserver-tool2"]
    mock_mcp.config.servers = [SimpleNamespace(name="myserver")]
    ctx = PromptContext(workdir=Path("/tmp"), mcp_manager=mock_mcp)
    result = run(mcp_tools_section(ctx))
    assert "MCP TOOLS" in result
    assert "myserver:" in result
    assert "myserver-tool1" in result
    assert "myserver-tool2" in result


def test_mcp_tools_section_longest_prefix_match():
    """Server name 'foo-bar' must be matched before 'foo'."""
    mock_mcp = MagicMock()
    mock_mcp.get_connection_summary.return_value = {"enabled": True, "total_tools": 2}
    mock_mcp.list_mcp_tools.return_value = ["foo-bar-baz", "foo-qux"]
    mock_mcp.config.servers = [
        SimpleNamespace(name="foo"),
        SimpleNamespace(name="foo-bar"),
    ]
    ctx = PromptContext(workdir=Path("/tmp"), mcp_manager=mock_mcp)
    result = run(mcp_tools_section(ctx))
    assert "foo-bar:" in result
    assert "foo:" in result
    assert "foo-bar-baz" in result
    assert "foo-qux" in result


def test_dynamic_sections_has_two_entries():
    assert len(DYNAMIC_SECTIONS) == 2
    names = [s.name for s in DYNAMIC_SECTIONS]
    assert "skills" in names
    assert "mcp_tools" in names


def test_dynamic_sections_ordered_after_defaults():
    orders = [s.order for s in DYNAMIC_SECTIONS]
    assert min(orders) > 40  # all default sections have order <= 40
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /home/hf/github_project/build-my-agent
pytest tests/test_prompt_dynamic.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'bourbon.prompt.dynamic'`

- [ ] **Step 3: Write `dynamic.py`**

```python
# src/bourbon/prompt/dynamic.py
from bourbon.prompt.types import PromptContext, PromptSection


async def skills_section(ctx: PromptContext) -> str:
    """Returns skills catalog from SkillManager, or empty string if none."""
    if not ctx.skill_manager:
        return ""
    catalog = ctx.skill_manager.get_catalog()
    if not catalog:
        return ""
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

    # Use longest-prefix-first matching to handle server names that share a prefix
    # (e.g., servers "foo" and "foo-bar": "foo-bar-baz" must match "foo-bar", not "foo").
    server_names = sorted(
        [s.name for s in ctx.mcp_manager.config.servers],
        key=len,
        reverse=True,   # longest first
    )
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

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd /home/hf/github_project/build-my-agent
pytest tests/test_prompt_dynamic.py -v
```

Expected: `10 passed`

- [ ] **Step 5: Commit**

```bash
git add src/bourbon/prompt/dynamic.py tests/test_prompt_dynamic.py
git commit -m "feat(prompt): add DYNAMIC_SECTIONS (skills, mcp_tools) with longest-prefix-first server matching"
```

---

## Task 5: Create `context.py`

**Files:**
- Create: `src/bourbon/prompt/context.py`
- Create: `tests/test_prompt_context.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_prompt_context.py
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch
from bourbon.prompt.context import ContextInjector
from bourbon.prompt.types import PromptContext


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_inject_prepends_system_reminder():
    injector = ContextInjector()
    ctx = PromptContext(workdir=Path("/tmp/proj"))

    with patch.object(injector, "_get_git_status", new=AsyncMock(return_value=None)):
        result = run(injector.inject("hello", ctx))

    assert result.startswith("<system-reminder>")
    assert "</system-reminder>" in result
    assert "hello" in result
    # reminder must come before the user message
    assert result.index("</system-reminder>") < result.index("hello")


def test_inject_includes_workdir():
    injector = ContextInjector()
    ctx = PromptContext(workdir=Path("/home/user/project"))

    with patch.object(injector, "_get_git_status", new=AsyncMock(return_value=None)):
        result = run(injector.inject("msg", ctx))

    assert "/home/user/project" in result


def test_inject_includes_today_date():
    from datetime import date
    injector = ContextInjector()
    ctx = PromptContext(workdir=Path("/tmp"))

    with patch.object(injector, "_get_git_status", new=AsyncMock(return_value=None)):
        result = run(injector.inject("msg", ctx))

    assert date.today().isoformat() in result


def test_inject_includes_git_status_when_available():
    injector = ContextInjector()
    ctx = PromptContext(workdir=Path("/tmp/repo"))

    with patch.object(injector, "_get_git_status", new=AsyncMock(return_value="## main\n M file.py")):
        result = run(injector.inject("msg", ctx))

    assert "## main" in result
    assert " M file.py" in result


def test_inject_omits_git_section_when_none():
    injector = ContextInjector()
    ctx = PromptContext(workdir=Path("/tmp/not-a-repo"))

    with patch.object(injector, "_get_git_status", new=AsyncMock(return_value=None)):
        result = run(injector.inject("msg", ctx))

    assert "Git status" not in result


def test_get_git_status_returns_none_on_timeout():
    """ContextInjector must kill the subprocess and return None on timeout."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    injector = ContextInjector()

    mock_proc = MagicMock()
    mock_proc.kill = MagicMock()
    mock_proc.wait = AsyncMock(return_value=None)
    # communicate() hangs forever — simulate by raising TimeoutError via wait_for
    mock_proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError)

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc), \
         patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
        result = run(injector._get_git_status(Path("/any")))

    assert result is None
    mock_proc.kill.assert_called_once()


def test_get_git_status_returns_none_outside_repo(tmp_path):
    """Non-git directory should return None, not raise."""
    injector = ContextInjector()
    # tmp_path is a fresh dir with no .git
    result = run(injector._get_git_status(tmp_path))
    assert result is None


def test_inject_empty_user_message():
    """inject() must work correctly when user_message is empty string."""
    injector = ContextInjector()
    ctx = PromptContext(workdir=Path("/tmp"))

    with patch.object(injector, "_get_git_status", new=AsyncMock(return_value=None)):
        result = run(injector.inject("", ctx))

    assert result.startswith("<system-reminder>")
    assert "</system-reminder>" in result
    # Empty message is appended after the reminder block
    assert result.endswith("\n")


def test_truncate_git_status_caps_output():
    """_truncate_git_status must cap at _GIT_STATUS_MAX_LINES and append notice."""
    injector = ContextInjector()
    many_lines = "\n".join([f" M file{i}.py" for i in range(200)])

    result = injector._truncate_git_status(many_lines)

    lines = result.splitlines()
    assert len(lines) == injector._GIT_STATUS_MAX_LINES + 1  # kept lines + notice
    assert "truncated" in lines[-1]
    assert "150" in lines[-1]  # 200 - 50 omitted


def test_truncate_git_status_passthrough_when_short():
    """_truncate_git_status must return text unchanged when within the limit."""
    injector = ContextInjector()
    short = "\n".join([f" M file{i}.py" for i in range(10)])

    result = injector._truncate_git_status(short)

    assert result == short
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /home/hf/github_project/build-my-agent
pytest tests/test_prompt_context.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'bourbon.prompt.context'`

- [ ] **Step 3: Write `context.py`**

```python
# src/bourbon/prompt/context.py
import asyncio
from datetime import date
from pathlib import Path

from bourbon.prompt.types import PromptContext


class ContextInjector:
    """Prepends <system-reminder> with env context to a human-authored user message."""

    _GIT_TIMEOUT = 2.0      # seconds; large repos on slow I/O should not block user input
    _GIT_STATUS_MAX_LINES = 50  # cap status output to avoid transcript token bloat

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
            try:
                stdout, _ = await asyncio.wait_for(
                    proc.communicate(), timeout=self._GIT_TIMEOUT
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()  # reap zombie to avoid resource leak
                return None
            if proc.returncode != 0:
                return None
            text = stdout.decode().strip()
            return self._truncate_git_status(text)
        except Exception:
            return None

    def _truncate_git_status(self, text: str) -> str:
        """Cap git status to _GIT_STATUS_MAX_LINES to prevent transcript token bloat."""
        lines = text.splitlines()
        if len(lines) <= self._GIT_STATUS_MAX_LINES:
            return text
        kept = lines[:self._GIT_STATUS_MAX_LINES]
        omitted = len(lines) - self._GIT_STATUS_MAX_LINES
        kept.append(f"[... {omitted} more lines truncated ...]")
        return "\n".join(kept)
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd /home/hf/github_project/build-my-agent
pytest tests/test_prompt_context.py -v
```

Expected: `11 passed` (5 inject tests + 3 git_status tests + 1 empty_message + 2 truncation)

- [ ] **Step 5: Commit**

```bash
git add src/bourbon/prompt/context.py tests/test_prompt_context.py
git commit -m "feat(prompt): add ContextInjector with git status truncation at 50 lines"
```

---

## Task 6: Create `__init__.py` (public API)

**Files:**
- Create: `src/bourbon/prompt/__init__.py`

- [ ] **Step 1: Write the file**

```python
# src/bourbon/prompt/__init__.py
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

- [ ] **Step 2: Verify public API is importable**

```bash
cd /home/hf/github_project/build-my-agent
python -c "
from bourbon.prompt import (
    PromptBuilder, PromptSection, PromptContext, ContextInjector,
    ALL_SECTIONS, DEFAULT_SECTIONS, DYNAMIC_SECTIONS
)
print(f'ALL_SECTIONS count: {len(ALL_SECTIONS)}')
print('OK')
"
```

Expected:
```
ALL_SECTIONS count: 6
OK
```

- [ ] **Step 3: Commit**

```bash
git add src/bourbon/prompt/__init__.py
git commit -m "feat(prompt): wire public API in __init__.py (ALL_SECTIONS = 6 sections)"
```

---

## Task 7: Update `agent.py` — wire prompt module

**Files:**
- Modify: `src/bourbon/agent.py`

This task removes 3 methods and adds 3 attributes. Make all changes in one edit, then run tests.

- [ ] **Step 1: Update imports at top of `agent.py`**

Find the existing imports block (lines 1–37) and add:

```python
from bourbon.prompt import ALL_SECTIONS, PromptBuilder, PromptContext, ContextInjector
from bourbon.tools import (
    ToolContext,
    _get_async_runtime,  # add this to existing import
    definitions,
    get_registry,
    get_tool_with_metadata,
)
```

The existing `from bourbon.tools import` line becomes:
```python
from bourbon.tools import (
    ToolContext,
    _get_async_runtime,
    definitions,
    get_registry,
    get_tool_with_metadata,
)
```

- [ ] **Step 2: Replace `__init__` prompt setup section**

Find lines 107–109 (the current prompt setup):
```python
        # Build system prompt (will be updated after MCP connect)
        self._custom_system_prompt = system_prompt
        self.system_prompt = system_prompt or self._build_system_prompt()
```

Replace with:
```python
        # Build system prompt using prompt module
        self._prompt_ctx = PromptContext(
            workdir=self.workdir,
            skill_manager=self.skills,
            mcp_manager=self.mcp,
        )
        self._prompt_builder = PromptBuilder(
            sections=ALL_SECTIONS,
            custom_prompt=system_prompt,  # None = use default sections
            append_prompt=None,
        )
        self._context_injector = ContextInjector()
        self.system_prompt = _get_async_runtime().run(
            self._prompt_builder.build(self._prompt_ctx)
        )
```

- [ ] **Step 3: Replace `_finalize_mcp_initialization`**

Find the method (lines 221–227):
```python
    def _finalize_mcp_initialization(self, results: dict) -> dict:
        """Update prompt state after MCP initialization."""
        if results and not self._custom_system_prompt:
            summary = self.mcp.get_connection_summary()
            if summary["total_tools"] > 0:
                self.system_prompt = self._build_system_prompt()
        return results
```

Replace with:
```python
    def _finalize_mcp_initialization(self, results: dict) -> dict:
        """MCP init complete; next step() call will rebuild system_prompt automatically."""
        return results
```

- [ ] **Step 4: Delete three methods**

Delete the entire bodies of `_build_system_prompt()`, `_get_mcp_section()`, and `_get_skills_section()` (lines 229–364 in original file). These three methods span approximately 135 lines.

- [ ] **Step 5: Update `step()` to rebuild prompt and inject context**

Find `step()` (currently lines 366–387). Replace the method body:

```python
    def step(self, user_input: str) -> str:
        """Process one user input and return assistant response."""
        # Rebuild system prompt first — before any short-circuit path
        self.system_prompt = _get_async_runtime().run(
            self._prompt_builder.build(self._prompt_ctx)
        )

        # Check if we're resuming from a pending confirmation (no injection here)
        if self.pending_confirmation:
            return self._handle_confirmation_response(user_input)

        # Inject env context into the human-authored user message
        enriched_input = _get_async_runtime().run(
            self._context_injector.inject(user_input, self._prompt_ctx)
        )

        # Add enriched user message via Session
        user_msg = TranscriptMessage(
            role=MessageRole.USER,
            content=[TextBlock(text=enriched_input)],
        )
        self.session.add_message(user_msg)
        self.session.save()

        # Pre-process: micro-compact
        self.session.context_manager.microcompact()

        # Check if we need full compression
        self.session.maybe_compact()

        # Run the conversation loop
        return self._run_conversation_loop()
```

- [ ] **Step 6: Update `step_stream()` to rebuild prompt and inject context**

Find `step_stream()` (currently lines 389–445). Replace the section after the debug_log call and before "Add user message via Session":

```python
    def step_stream(
        self,
        user_input: str,
        on_text_chunk: Callable[[str], None],
    ) -> str:
        """Process user input with streaming text output."""
        started_at = time.monotonic()
        debug_log(
            "agent.step_stream.start",
            user_input_len=len(user_input),
            message_count=self.session.chain.message_count,
            has_pending_confirmation=bool(self.pending_confirmation),
        )

        # Rebuild system prompt first — before any short-circuit path
        self.system_prompt = _get_async_runtime().run(
            self._prompt_builder.build(self._prompt_ctx)
        )

        # Check if we're resuming from a pending confirmation (no injection here)
        if self.pending_confirmation:
            response = self._handle_confirmation_response(user_input)
            debug_log(
                "agent.step_stream.complete",
                response_len=len(response),
                elapsed_ms=int((time.monotonic() - started_at) * 1000),
                resumed_confirmation=True,
            )
            return response

        # Inject env context into the human-authored user message
        enriched_input = _get_async_runtime().run(
            self._context_injector.inject(user_input, self._prompt_ctx)
        )

        # Add enriched user message via Session
        user_msg = TranscriptMessage(
            role=MessageRole.USER,
            content=[TextBlock(text=enriched_input)],
        )
        self.session.add_message(user_msg)
        self.session.save()

        # Pre-process: micro-compact
        self.session.context_manager.microcompact()

        # Check if we need full compression
        self.session.maybe_compact()

        # Run the streaming conversation loop
        response = self._run_conversation_loop_stream(on_text_chunk)
        debug_log(
            "agent.step_stream.complete",
            response_len=len(response),
            elapsed_ms=int((time.monotonic() - started_at) * 1000),
            has_pending_confirmation=bool(self.pending_confirmation),
        )
        return response
```

- [ ] **Step 7: Run the full test suite to see what breaks**

```bash
cd /home/hf/github_project/build-my-agent
pytest --tb=short 2>&1 | tail -40
```

Expected: failures in `test_agent_error_policy.py`, `test_mcp_sync_runtime.py`, `test_agent_streaming.py`, `test_debug_logging.py`. All prompt module tests should pass.

- [ ] **Step 8: Commit the agent changes (tests still broken — will fix next)**

```bash
git add src/bourbon/agent.py
git commit -m "feat(prompt): wire agent.py to use PromptBuilder and ContextInjector"
```

---

## Task 8: Agent integration tests (wire-up verification)

**Files:**
- Create: `tests/test_prompt_agent_integration.py`

These tests prove the wiring in `agent.py` is correct — not just that the prompt module works in isolation. They verify:
1. `step()` rebuilds `self.system_prompt` on every call
2. The session message stored for the LLM contains `<system-reminder>`
3. `pending_confirmation` path: prompt rebuilt but no `<system-reminder>` injection

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_prompt_agent_integration.py
"""Integration tests for PromptBuilder + ContextInjector wiring in Agent.step()."""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from bourbon.agent import Agent, PendingConfirmation
from bourbon.config import Config
from bourbon.prompt import ALL_SECTIONS, PromptBuilder, PromptContext, ContextInjector
from bourbon.session.manager import SessionManager
from bourbon.session.storage import TranscriptStore
from bourbon.tools import _get_async_runtime


def _make_agent() -> Agent:
    """Minimal Agent stub for integration tests."""
    agent = object.__new__(Agent)
    agent.config = Config()
    agent.workdir = Path("/tmp/test-project")
    agent.on_tool_start = None
    agent.on_tool_end = None
    agent.todos = None
    agent.skills = MagicMock()
    agent.skills.get_catalog.return_value = ""
    agent.compressor = None
    agent._rounds_without_todo = 0
    agent._max_tool_rounds = 50
    agent.pending_confirmation = None
    agent.token_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    agent._discovered_tools = set()
    agent._tool_consecutive_failures = {}
    agent._max_tool_consecutive_failures = 3

    # Prompt attributes
    agent._prompt_ctx = PromptContext(workdir=agent.workdir, skill_manager=None, mcp_manager=None)
    agent._prompt_builder = PromptBuilder(sections=ALL_SECTIONS)
    agent._context_injector = ContextInjector()
    agent.system_prompt = _get_async_runtime().run(
        agent._prompt_builder.build(agent._prompt_ctx)
    )

    # Session
    base = Path(tempfile.mkdtemp())
    store = TranscriptStore(base_dir=base)
    mgr = SessionManager(store=store, project_name="test", project_dir=str(agent.workdir))
    agent.session = mgr.create_session()
    agent._session_manager = mgr

    # Security components (allow everything)
    from bourbon.access_control.policy import PolicyAction
    agent.access_controller = MagicMock()
    agent.access_controller.evaluate.return_value = MagicMock(action=PolicyAction.ALLOW)
    agent.audit = MagicMock()
    agent.sandbox = MagicMock()
    agent.sandbox.enabled = False

    return agent


class MockLLM:
    def chat(self, **kwargs):
        return {
            "content": [{"type": "text", "text": "done"}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }


def test_step_rebuilds_system_prompt_on_each_call():
    """system_prompt must be refreshed on every step() call."""
    agent = _make_agent()
    agent.llm = MockLLM()

    original_prompt = agent.system_prompt

    # Simulate workdir change between turns (or any dynamic section change)
    # by swapping to a PromptBuilder that returns a different string
    agent._prompt_builder = PromptBuilder(sections=[], custom_prompt="new prompt v2")

    with patch.object(agent._context_injector, "inject", new=AsyncMock(return_value="hi")):
        agent.step("hi")

    assert agent.system_prompt == "new prompt v2"
    assert agent.system_prompt != original_prompt


def test_step_stores_enriched_message_with_system_reminder():
    """The message written to session must contain <system-reminder>."""
    agent = _make_agent()
    agent.llm = MockLLM()

    with patch.object(
        agent._context_injector,
        "inject",
        new=AsyncMock(return_value="<system-reminder>\nWorking directory: /tmp\n</system-reminder>\nhello"),
    ):
        agent.step("hello")

    messages = agent.session.get_messages_for_llm()
    user_messages = [m for m in messages if m["role"] == "user"]
    assert user_messages, "No user messages found in session"
    first_user_content = user_messages[0]["content"]
    if isinstance(first_user_content, list):
        text = " ".join(
            block["text"] for block in first_user_content if block.get("type") == "text"
        )
    else:
        text = first_user_content
    assert "<system-reminder>" in text


def test_step_rebuilds_prompt_before_pending_confirmation_shortcircuit():
    """pending_confirmation path: prompt rebuilt BEFORE short-circuit, inject() never called."""
    agent = _make_agent()
    agent.pending_confirmation = PendingConfirmation(
        tool_name="Bash",
        tool_input={"command": "rm -rf /"},
        error_output="Error: permission denied",
        options=["Retry", "Skip"],
    )
    agent.llm = MockLLM()

    # Swap builder so we can detect whether a rebuild actually happened
    agent._prompt_builder = PromptBuilder(sections=[], custom_prompt="rebuilt-confirmation-prompt")

    inject_spy = AsyncMock(return_value="should not be called")
    with patch.object(agent._context_injector, "inject", new=inject_spy), \
         patch.object(agent, "_handle_confirmation_response", return_value="ok") as handle_spy:
        agent.step("yes")

    inject_spy.assert_not_called()
    handle_spy.assert_called_once_with("yes")
    # Prompt must have been rebuilt (new value, not the one set in _make_agent)
    assert agent.system_prompt == "rebuilt-confirmation-prompt"
```

- [ ] **Step 2: Run tests — they must pass immediately (Task 7 is already done)**

```bash
cd /home/hf/github_project/build-my-agent
pytest tests/test_prompt_agent_integration.py -v
```

Expected: `3 passed`. Task 7 has already wired `agent.py`; these tests verify the wire-up is correct end-to-end.

- [ ] **Step 3: Commit**

```bash
git add tests/test_prompt_agent_integration.py
git commit -m "test(prompt): add agent integration tests for step() rebuild and session enrichment"
```

---

## Task 10: Fix `test_agent_error_policy.py`

**Files:**
- Modify: `tests/test_agent_error_policy.py`

The `mock_agent` fixture calls `agent._build_system_prompt()` (removed) and does not set up the three new prompt attributes. The assertions check `mock_agent.system_prompt` for specific strings.

- [ ] **Step 1: Update the fixture**

Find the `mock_agent` fixture (lines 28–57). Replace `agent.system_prompt = agent._build_system_prompt()` with the new prompt setup:

```python
    from bourbon.prompt import ALL_SECTIONS, PromptBuilder, PromptContext, ContextInjector
    from bourbon.tools import _get_async_runtime
    agent._prompt_ctx = PromptContext(workdir=agent.workdir, skill_manager=agent.skills, mcp_manager=None)
    agent._prompt_builder = PromptBuilder(sections=ALL_SECTIONS)
    agent._context_injector = ContextInjector()
    agent.system_prompt = _get_async_runtime().run(
        agent._prompt_builder.build(agent._prompt_ctx)
    )
```

Also remove the `agent._custom_system_prompt = None` line if present (it no longer exists on Agent).

- [ ] **Step 2: Run the error policy tests**

```bash
cd /home/hf/github_project/build-my-agent
pytest tests/test_agent_error_policy.py -v
```

Expected: all tests pass. The `system_prompt` will contain `"CRITICAL ERROR HANDLING RULES"`, `"HIGH RISK"`, `"MUST STOP and ask"`, and `"LOW RISK"` from `ERROR_HANDLING` section.

- [ ] **Step 3: Commit**

```bash
git add tests/test_agent_error_policy.py
git commit -m "test(prompt): update error_policy fixture to use PromptBuilder"
```

---

## Task 11: Fix `test_mcp_sync_runtime.py`

**Files:**
- Modify: `tests/test_mcp_sync_runtime.py`

The test `test_initialize_mcp_sync_updates_system_prompt_when_tools_are_available` mocks `agent._build_system_prompt` (removed) and asserts `agent.system_prompt == "updated prompt"`. This test must be rewritten to verify that `PromptBuilder.build()` produces a result containing the MCP tool name.

- [ ] **Step 1: Rewrite the affected test**

Find `TestAgentSyncMCPInitialization` (lines 35–53). Replace the test body:

```python
class TestAgentSyncMCPInitialization(unittest.TestCase):
    """Tests for synchronous MCP initialization entry points."""

    def test_initialize_mcp_sync_completes_and_prompt_reflects_mcp_tools(self):
        """Agent should expose a sync MCP init path for the sync REPL."""
        from bourbon.prompt import ALL_SECTIONS, PromptBuilder, PromptContext, ContextInjector
        from bourbon.tools import _get_async_runtime

        agent = Agent.__new__(Agent)
        agent.workdir = Path("/tmp")

        mock_mcp = MagicMock()
        results = {"myserver": object()}
        mock_mcp.connect_all_sync.return_value = results
        mock_mcp.get_connection_summary.return_value = {"enabled": True, "total_tools": 1}
        mock_mcp.list_mcp_tools.return_value = ["myserver-mytool"]
        mock_mcp.config.servers = [SimpleNamespace(name="myserver")]
        agent.mcp = mock_mcp

        agent._prompt_ctx = PromptContext(workdir=agent.workdir, skill_manager=None, mcp_manager=agent.mcp)
        agent._prompt_builder = PromptBuilder(sections=ALL_SECTIONS)
        agent._context_injector = ContextInjector()
        agent.system_prompt = "old prompt"

        returned = Agent.initialize_mcp_sync(agent, timeout=60.0)

        agent.mcp.connect_all_sync.assert_called_once_with(timeout=60.0)
        assert returned is results

        # After init, rebuilding the prompt should include the MCP tool
        result = _get_async_runtime().run(agent._prompt_builder.build(agent._prompt_ctx))
        assert "myserver-mytool" in result
```

Also add the missing `from pathlib import Path` import at the top if not present.

- [ ] **Step 2: Run the MCP sync tests**

```bash
cd /home/hf/github_project/build-my-agent
pytest tests/test_mcp_sync_runtime.py -v
```

Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add tests/test_mcp_sync_runtime.py
git commit -m "test(prompt): update mcp_sync_runtime fixture to use PromptBuilder"
```

---

## Task 12: Fix `test_agent_streaming.py` and `test_debug_logging.py`

**Files:**
- Modify: `tests/test_agent_streaming.py`
- Modify: `tests/test_debug_logging.py`

These tests use `object.__new__(Agent)` and call `step_stream()`, which now calls `self._prompt_builder.build()`. They need the three new prompt attributes added to their fixtures.

- [ ] **Step 1: Add prompt attributes to `test_agent_streaming.py`**

Find `test_step_stream_calls_callback_for_chunks` (line ~39). After `agent.pending_confirmation = None`, add:

```python
    from bourbon.prompt import PromptBuilder, PromptContext, ContextInjector
    agent._prompt_ctx = PromptContext(workdir=agent.workdir, skill_manager=None, mcp_manager=None)
    agent._prompt_builder = PromptBuilder(sections=[], custom_prompt="test prompt")
    agent._context_injector = ContextInjector()
```

Also find any other test function in this file that constructs `Agent` via `__new__` and calls `step()` or `step_stream()`, and add the same three lines.

- [ ] **Step 2: Add prompt attributes to `test_debug_logging.py`**

Find `test_agent_step_stream_emits_debug_events` (line ~28). After `agent.system_prompt = "You are a test agent"`, add:

```python
    from bourbon.prompt import PromptBuilder, PromptContext, ContextInjector
    agent._prompt_ctx = PromptContext(workdir=agent.workdir, skill_manager=None, mcp_manager=None)
    agent._prompt_builder = PromptBuilder(sections=[], custom_prompt="test prompt")
    agent._context_injector = ContextInjector()
```

- [ ] **Step 3: Run all affected tests**

```bash
cd /home/hf/github_project/build-my-agent
pytest tests/test_agent_streaming.py tests/test_debug_logging.py -v
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add tests/test_agent_streaming.py tests/test_debug_logging.py
git commit -m "test(prompt): add prompt attributes to __new__-based agent fixtures"
```

---

## Task 13: Full test suite verification

**Files:** none (read-only verification)

- [ ] **Step 1: Run the full test suite**

```bash
cd /home/hf/github_project/build-my-agent
pytest --tb=short 2>&1 | tail -20
```

Expected: all tests pass (previously 83 tests). The count may increase due to new prompt tests.

- [ ] **Step 2: Run linting and type check**

```bash
cd /home/hf/github_project/build-my-agent
ruff check src tests && ruff format --check src tests && mypy src
```

Expected: no errors.

- [ ] **Step 3: Verify system prompt contains expected sections in correct order**

```bash
cd /home/hf/github_project/build-my-agent
python -c "
import asyncio
from pathlib import Path
from bourbon.prompt import ALL_SECTIONS, PromptBuilder, PromptContext

ctx = PromptContext(workdir=Path.cwd())
builder = PromptBuilder(sections=ALL_SECTIONS)
prompt = asyncio.run(builder.build(ctx))
print('--- SYSTEM PROMPT PREVIEW ---')
print(prompt[:800])
print('...')
assert 'Bourbon' in prompt
assert 'TodoWrite' in prompt
assert 'CRITICAL ERROR HANDLING RULES' in prompt
assert 'TASK ADAPTABILITY' in prompt
print('All assertions passed')
"
```

Expected: preview of prompt and `All assertions passed`.

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "feat(prompt): complete prompt management module implementation"
```

---

## Behavior Deltas (document these in PR description)

When reviewing or testing manually, note these intentional behavior changes:

1. **No skills available**: system prompt no longer contains `"(No skills available)"` — the skills section is omitted entirely when catalog is empty.
2. **Prompt rebuilt every `step()` call**: not just at init/MCP connect.
3. **Skills activation format simplified**: XML `<function_calls>` example removed from system prompt.
4. **Bug fix — MCP tools now appear in system prompt**: old `_get_mcp_section()` used `:` separator but tools are registered with `-` separator, so the server grouping never rendered anything. Fixed by longest-prefix matching on `-` separator.
5. **User messages in session contain `<system-reminder>` prefix**: the enriched message (with env context) is what gets stored and sent to the LLM.
