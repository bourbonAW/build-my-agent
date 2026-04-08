# Tool 架构对齐 Claude Code 实施计划

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 重构 bourbon agent 的 built-in tool 系统，对齐 Claude Code 架构：引入 ToolContext、Tool 类型属性、alias-aware registry、deferred 工具发现机制（ToolSearch）及 PascalCase 工具命名。

**Architecture:** 分三步分层演进：Step 1 重构 `tools/__init__.py` 基础设施（ToolContext、新 Tool 字段、ToolRegistry）；Step 2 重命名核心工具（base/search/skill_tool）、新增 Glob、更新 Stage-B 工具和 access_control；Step 3 新增 ToolSearch 工具并修改 agent.py 接入 deferred 发现机制。每步可独立验证、独立 commit。

**Tech Stack:** Python 3.11+, dataclasses, pathlib, asyncio, pytest；复用仓库已有 `AsyncRuntime`（`src/bourbon/mcp_client/runtime.py`）

**Spec:** `docs/superpowers/specs/2026-04-08-tool-architecture-alignment-design.md`

---

## 关键设计约束（实施前必读）

1. **原 helper 函数保留不动**：`run_bash()`、`read_file()`、`fetch_url()` 等函数签名不变，供现有测试直接调用。重命名只新增 ctx-aware 注册 handler 包装层。
2. **定义新工具名为主名，旧名注册为 aliases**：`definitions()` 返回主名（`Bash`、`Read` 等）；alias-aware lookup 保证旧名（`bash`、`read_file`）路由正确。
3. **两类测试需同步更新**：
   - `tests/test_tools_registry.py`：检查旧工具名，需改为新名 + 新增 alias lookup 测试
   - `tests/test_capabilities.py`：直接调用 `infer_capabilities("read_file", ...)` 使用旧名，需改为新名（`"Read"`）
4. **其他测试无需修改**：`test_tools_base.py`、`tests/tools/test_web.py`、`test_data.py`、`test_documents.py`、`test_skills_new.py` 测试 helper 函数，不受 handler 层变更影响。
5. **`tools/__init__.py` 引入 `_async_runtime` 单例**：`AsyncRuntime`（来自 `bourbon.mcp_client.runtime`），模块级初始化，`ToolRegistry.call()` 用它处理 async handler。

---

## Chunk 1: 基础设施重构（tools/__init__.py）

### Task 1: ToolContext + Tool 新字段 + ToolRegistry 重构

**Files:**
- Modify: `src/bourbon/tools/__init__.py`
- Modify: `tests/test_tools_registry.py`

- [ ] **Step 1: 写失败测试——ToolContext 存在且有正确字段**

新增到 `tests/test_tools_registry.py`：

```python
from pathlib import Path
from bourbon.tools import ToolContext, Tool, RiskLevel, ToolRegistry, get_registry

class TestToolContext:
    def test_tool_context_fields(self):
        ctx = ToolContext(workdir=Path("/tmp"))
        assert ctx.workdir == Path("/tmp")
        assert ctx.skill_manager is None
        assert ctx.on_tools_discovered is None

    def test_tool_context_with_callbacks(self):
        discovered = set()
        ctx = ToolContext(
            workdir=Path("/tmp"),
            on_tools_discovered=discovered.update,
        )
        ctx.on_tools_discovered({"WebFetch"})
        assert "WebFetch" in discovered
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd /home/hf/github_project/build-my-agent
pytest tests/test_tools_registry.py::TestToolContext -v
```

期望：`ImportError: cannot import name 'ToolContext'`

- [ ] **Step 3: 实现 ToolContext**

在 `src/bourbon/tools/__init__.py` 顶部，`class RiskLevel` 之前添加（需要先 import 相关模块）：

```python
from __future__ import annotations

import inspect
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
```

同时更新 `ToolHandler` 类型别名以支持 async handler（mypy 兼容）：

```python
# 原来：ToolHandler = Callable[..., str]
# 改为：
ToolHandler = Callable[..., str | Coroutine[Any, Any, str]]
```

然后添加 `ToolContext` 类：

```python
@dataclass
class ToolContext:
    """统一工具执行上下文，替换各处零散的 workdir kwarg。"""
    workdir: Path
    skill_manager: Any | None = None
    on_tools_discovered: Callable[[set[str]], None] | None = None
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/test_tools_registry.py::TestToolContext -v
```

期望：PASS

---

- [ ] **Step 5: 写失败测试——Tool 新字段**

追加到 `tests/test_tools_registry.py`：

```python
class TestToolNewFields:
    def test_tool_has_new_fields_with_defaults(self):
        def dummy_handler(*, ctx: ToolContext) -> str:
            return "ok"

        t = Tool(
            name="TestTool",
            description="test",
            input_schema={"type": "object", "properties": {}},
            handler=dummy_handler,
        )
        assert t.aliases == []
        assert t.always_load is True
        assert t.should_defer is False
        assert t.is_concurrency_safe is False
        assert t.is_read_only is False
        assert t.is_destructive is False
        assert t.search_hint is None

    def test_tool_is_destructive_drives_risk_patterns(self):
        """is_destructive=True + HIGH risk → risk_patterns auto-populated."""
        def dummy(*, ctx: ToolContext) -> str: return "ok"

        t = Tool(
            name="DangerTool",
            description="d",
            input_schema={"type": "object", "properties": {}},
            handler=dummy,
            risk_level=RiskLevel.HIGH,
            is_destructive=True,
        )
        assert len(t.risk_patterns) > 0
        assert "rm " in t.risk_patterns

    def test_tool_is_high_risk_operation_uses_is_destructive(self):
        def dummy(*, ctx: ToolContext) -> str: return "ok"

        t = Tool(
            name="BashLike",
            description="d",
            input_schema={"type": "object", "properties": {}},
            handler=dummy,
            risk_level=RiskLevel.HIGH,
            is_destructive=True,
        )
        assert t.is_high_risk_operation({"command": "rm -rf /tmp/foo"}) is True
        assert t.is_high_risk_operation({"command": "echo hello"}) is False
```

- [ ] **Step 6: 运行确认失败**

```bash
pytest tests/test_tools_registry.py::TestToolNewFields -v
```

期望：`TypeError` 或字段不存在

- [ ] **Step 7: 为 Tool dataclass 新增字段**

在 `src/bourbon/tools/__init__.py` 的 `Tool` dataclass 中新增字段（在 `required_capabilities` 之后）：

```python
# 新增字段
aliases: list[str] = field(default_factory=list)
always_load: bool = True
should_defer: bool = False
is_concurrency_safe: bool = False
is_read_only: bool = False
is_destructive: bool = False
search_hint: str | None = None
```

修改 `__post_init__`，将 `self.name == "bash"` 改为 `is_destructive`：

```python
def __post_init__(self):
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
                "pip install", "pip3 install", "pip uninstall", "pip3 uninstall",
                "apt ", "apt-get ", "yum ", "brew ", "pacman ", "dnf ",
                "rm ", "rm -", "rmdir ", "sudo ", "su ",
                "shutdown", "reboot", "halt", "poweroff",
                "mkfs.", "fdisk", "dd ", "> /dev", "> /sys", "> /proc",
                "curl ", "wget ", "| sh", "| bash",
            ]
        else:
            self.risk_patterns = []
```

修改 `is_high_risk_operation()`：

```python
def is_high_risk_operation(self, tool_input: dict) -> bool:
    if self.risk_level == RiskLevel.HIGH and self.is_destructive:
        command = tool_input.get("command", "")
        return any(pattern in command for pattern in self.risk_patterns)
    return self.risk_level == RiskLevel.HIGH
```

- [ ] **Step 8: 运行确认通过**

```bash
pytest tests/test_tools_registry.py::TestToolNewFields -v
```

期望：PASS

---

- [ ] **Step 9: 写失败测试——ToolRegistry alias-aware + call()**

追加到 `tests/test_tools_registry.py`：

```python
class TestToolRegistryAliases:
    def setup_method(self):
        """每个测试用独立 registry，避免全局污染。"""
        self.registry = ToolRegistry()

    def _make_tool(self, name: str, aliases: list[str] | None = None) -> Tool:
        def handler(*, ctx: ToolContext) -> str:
            return f"called {name}"
        return Tool(
            name=name,
            description="test",
            input_schema={"type": "object", "properties": {}},
            handler=handler,
            aliases=aliases or [],
        )

    def test_alias_lookup_via_resolve(self):
        tool = self._make_tool("NewName", aliases=["old_name"])
        self.registry.register(tool)
        assert self.registry._resolve("NewName") is tool
        assert self.registry._resolve("old_name") is tool
        assert self.registry._resolve("nonexistent") is None

    def test_get_is_alias_aware(self):
        tool = self._make_tool("Read", aliases=["read_file"])
        self.registry.register(tool)
        assert self.registry.get("read_file") is tool

    def test_get_handler_is_alias_aware(self):
        tool = self._make_tool("Bash", aliases=["bash"])
        self.registry.register(tool)
        h = self.registry.get_handler("bash")
        assert h is not None

    def test_call_injects_ctx(self):
        called_with = {}
        def handler(command: str, *, ctx: ToolContext) -> str:
            called_with["ctx"] = ctx
            called_with["command"] = command
            return "done"
        tool = Tool(
            name="Bash", description="d",
            input_schema={"type": "object", "properties": {}},
            handler=handler,
            aliases=["bash"],
        )
        self.registry.register(tool)
        ctx = ToolContext(workdir=Path("/tmp"))
        result = self.registry.call("bash", {"command": "echo hi"}, ctx)
        assert result == "done"
        assert called_with["ctx"] is ctx
        assert called_with["command"] == "echo hi"

    def test_call_unknown_tool_returns_error(self):
        ctx = ToolContext(workdir=Path("/tmp"))
        result = self.registry.call("nonexistent", {}, ctx)
        assert "Unknown tool" in result

    def test_get_tool_definitions_filters_always_load(self):
        core = self._make_tool("CoreTool")
        core.always_load = True
        deferred = self._make_tool("DeferredTool")
        deferred.always_load = False
        deferred.should_defer = True
        self.registry.register(core)
        self.registry.register(deferred)

        defs = self.registry.get_tool_definitions()
        names = {d["name"] for d in defs}
        assert "CoreTool" in names
        assert "DeferredTool" not in names

    def test_get_tool_definitions_includes_discovered(self):
        core = self._make_tool("CoreTool")
        deferred = self._make_tool("DeferredTool")
        deferred.always_load = False
        deferred.should_defer = True
        self.registry.register(core)
        self.registry.register(deferred)

        defs = self.registry.get_tool_definitions(discovered={"DeferredTool"})
        names = {d["name"] for d in defs}
        assert "DeferredTool" in names
```

- [ ] **Step 10: 运行确认失败**

```bash
pytest tests/test_tools_registry.py::TestToolRegistryAliases -v
```

期望：`AttributeError: 'ToolRegistry' object has no attribute '_alias_map'`

- [ ] **Step 11: 重构 ToolRegistry**

替换 `src/bourbon/tools/__init__.py` 中的 `ToolRegistry` 类：

```python
# 在模块顶部添加（AsyncRuntime 单例）
from bourbon.mcp_client.runtime import AsyncRuntime
_async_runtime = AsyncRuntime()


class ToolRegistry:
    """Registry of available tools."""

    def __init__(self):
        self._tools: dict[str, Tool] = {}
        self._alias_map: dict[str, str] = {}  # alias → canonical name

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool
        for alias in (tool.aliases or []):
            self._alias_map[alias] = tool.name

    def _resolve(self, name: str) -> Tool | None:
        """按主名或 alias 查找工具。"""
        if name in self._tools:
            return self._tools[name]
        canonical = self._alias_map.get(name)
        return self._tools.get(canonical) if canonical else None

    def get(self, name: str) -> Tool | None:
        return self._resolve(name)

    def get_handler(self, name: str) -> ToolHandler | None:
        tool = self._resolve(name)
        return tool.handler if tool else None

    def get_tool(self, name: str) -> Tool | None:
        return self._resolve(name)

    def list_tools(self) -> list[Tool]:
        return list(self._tools.values())

    def call(self, name: str, tool_input: dict, ctx: ToolContext) -> str:
        """调用工具，注入 ToolContext，透明支持 async handler。"""
        tool = self._resolve(name)
        if not tool:
            return f"Error: Unknown tool '{name}'"
        result = tool.handler(**tool_input, ctx=ctx)
        if inspect.isawaitable(result):
            result = _async_runtime.run(result)
        return result

    def get_tool_definitions(self, discovered: set[str] | None = None) -> list[dict]:
        discovered = discovered or set()
        return [
            {"name": t.name, "description": t.description, "input_schema": t.input_schema}
            for t in self._tools.values()
            if t.always_load or t.name in discovered
        ]
```

- [ ] **Step 12: 运行确认通过**

```bash
pytest tests/test_tools_registry.py::TestToolRegistryAliases -v
```

期望：全部 PASS

---

- [ ] **Step 13: 更新 register_tool 装饰器 + _ensure_imports() + 顶层函数**

替换 `src/bourbon/tools/__init__.py` 中的 `register_tool`、`handler`、`get_tool_with_metadata`、`definitions` 函数：

```python
def register_tool(
    name: str,
    description: str,
    input_schema: dict[str, Any],
    risk_level: RiskLevel = RiskLevel.LOW,
    risk_patterns: list[str] | None = None,
    required_capabilities: list[str] | None = None,
    aliases: list[str] | None = None,
    always_load: bool = True,
    should_defer: bool = False,
    is_concurrency_safe: bool = False,
    is_read_only: bool = False,
    is_destructive: bool = False,
    search_hint: str | None = None,
) -> Callable[[ToolHandler], ToolHandler]:
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
            is_read_only=is_read_only,
            is_destructive=is_destructive,
            search_hint=search_hint,
        )
        get_registry().register(tool)
        return func
    return decorator


def _ensure_imports() -> None:
    """懒加载所有工具模块，触发注册。"""
    from bourbon.tools import base, search, skill_tool  # noqa: F401
    try:
        from bourbon.tools import tool_search  # noqa: F401
    except ImportError:
        pass
    try:
        from bourbon.tools import web  # noqa: F401
    except ImportError:
        pass
    try:
        from bourbon.tools import data  # noqa: F401
    except ImportError:
        pass
    try:
        from bourbon.tools import documents  # noqa: F401
    except ImportError:
        pass


def handler(name: str) -> ToolHandler | None:
    _ensure_imports()
    return get_registry().get_handler(name)


def get_tool_with_metadata(name: str) -> Tool | None:
    _ensure_imports()
    return get_registry().get_tool(name)


def definitions(discovered: set[str] | None = None) -> list[dict]:
    _ensure_imports()
    return get_registry().get_tool_definitions(discovered=discovered)


def tool(name: str) -> Tool | None:
    return get_registry().get(name)
```

- [ ] **Step 14: 运行全量测试确认基础设施完好**

```bash
pytest tests/test_tools_registry.py tests/test_tools_base.py tests/test_tools_search.py tests/test_risk_level.py tests/test_capabilities.py -v
```

期望：全部 PASS（原有测试因 handler 签名未变，仍可通过）

- [ ] **Step 15: 确认既有工具名测试无需改动（工具重命名在 Chunk 2）**

Chunk 1 只新增基础设施层，不改变工具的实际注册名。`test_tools_are_registered` 中的旧名（`bash`、`read_file` 等）和 `test_alias_lookup_via_global_functions` 的别名测试，均在 Chunk 2 完成工具重命名后一并更新（见 Task 2 Step 1）。

此步骤确认现有 registry 测试仍可通过：

```bash
pytest tests/test_tools_registry.py -v
```

期望：全部 PASS（新增的 TestToolContext、TestToolNewFields、TestToolRegistryAliases 通过；旧测试不受影响）

- [ ] **Step 16: Commit Step 1**

```bash
git add src/bourbon/tools/__init__.py tests/test_tools_registry.py
git commit -m "feat(tools): add ToolContext, Tool new fields, alias-aware ToolRegistry

- Add ToolContext dataclass (workdir, skill_manager, on_tools_discovered)
- Add Tool fields: aliases, always_load, should_defer, is_concurrency_safe,
  is_read_only, is_destructive, search_hint
- Fix __post_init__/is_high_risk_operation to use is_destructive (not name=='bash')
- ToolRegistry: _alias_map, _resolve(), call()+AsyncRuntime, get_tool_definitions(discovered=)
- register_tool() new params; _ensure_imports() with Stage-B try/except
- All lookups (get/get_handler/get_tool) now alias-aware"
```

---

## Chunk 2: 核心工具重命名（base.py / search.py / skill_tool.py）

> **前提：Chunk 1 已完成**（ToolContext、新 register_tool 参数、alias-aware ToolRegistry 均已就位）。

### Task 2: 重命名 base.py 工具，新增 ctx-aware handlers

**Files:**
- Modify: `src/bourbon/tools/base.py`
- No test changes needed (test_tools_base.py tests helper functions directly)

- [ ] **Step 1: 写失败测试——新工具名注册 + handler 包装调用 ctx.workdir**

追加到 `tests/test_tools_registry.py`（新 class + 更新已有测试）：

```python
class TestBaseToolsRenamed:
    def test_new_names_in_definitions(self):
        from bourbon.tools import definitions
        defs = definitions()
        names = {d["name"] for d in defs}
        assert "Bash" in names
        assert "Read" in names
        assert "Write" in names
        assert "Edit" in names

    def test_read_handler_uses_ctx_workdir(self, tmp_path):
        from bourbon.tools import get_registry, ToolContext
        ctx = ToolContext(workdir=tmp_path)
        # create a file in tmp_path to read
        (tmp_path / "test.txt").write_text("hello")
        result = get_registry().call("Read", {"path": "test.txt"}, ctx)
        assert "hello" in result

    def test_bash_is_destructive(self):
        from bourbon.tools import get_tool_with_metadata
        t = get_tool_with_metadata("Bash")
        assert t.is_destructive is True
        assert t.risk_level.value == "high"

    def test_read_is_read_only(self):
        from bourbon.tools import get_tool_with_metadata
        t = get_tool_with_metadata("Read")
        assert t.is_read_only is True
        assert t.is_concurrency_safe is True

    def test_write_edit_not_read_only(self):
        from bourbon.tools import get_tool_with_metadata
        assert get_tool_with_metadata("Write").is_read_only is False
        assert get_tool_with_metadata("Edit").is_read_only is False
```

同时更新已有的 `test_tools_are_registered`（改为新主名），并新增 alias 查找测试：

```python
# 更新 test_tools_are_registered（改为 PascalCase 主名）
def test_tools_are_registered(self):
    defs = tools.definitions()
    assert len(defs) >= 6
    tool_names = {d["name"] for d in defs}
    expected_tools = {"Bash", "Read", "Write", "Edit", "Grep", "AstGrep"}
    for expected in expected_tools:
        assert expected in tool_names, f"Expected tool '{expected}' not registered"

# 新增 alias 查找测试
def test_alias_lookup_via_global_functions(self):
    """旧工具名通过 alias 仍可查到。"""
    tools.definitions()
    assert tools.handler("bash") is not None
    assert tools.handler("read_file") is not None
    assert tools.handler("rg_search") is not None
    assert tools.get_tool_with_metadata("edit_file") is not None

def test_handler_returns_correct_function(self):
    tools.definitions()
    bash = tools.handler("Bash")   # 新主名
    assert bash is not None
    bash_alias = tools.handler("bash")  # 旧别名
    assert bash_alias is not None
```

- [ ] **Step 2: 运行确认失败**

```bash
pytest tests/test_tools_registry.py::TestBaseToolsRenamed -v
```

期望：`AssertionError: 'Bash' not in ...`

- [ ] **Step 3: 修改 base.py——保留 helper 函数，新增 ctx-aware 注册 handler**

在 `src/bourbon/tools/base.py` 中，**保留所有现有 helper 函数不变**（`safe_path`、`run_bash`、`read_file`、`write_file`、`edit_file`）。

替换文件底部的 `@register_tool` 注册代码（4 个工具）：

```python
# ── 注册工具 ──────────────────────────────────────────────────────────────────
# 原 helper 函数保留不变（供测试直接调用）。
# 注册层是薄包装：接收 ctx，调用原 helper，传入 ctx.workdir。

@register_tool(
    name="Bash",
    aliases=["bash"],
    description="Run a shell command in the workspace.",
    input_schema={
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Shell command to execute"},
        },
        "required": ["command"],
    },
    risk_level=RiskLevel.HIGH,
    is_destructive=True,
    required_capabilities=["exec"],
)
def bash_handler(command: str, *, ctx: ToolContext) -> str:
    return run_bash(command, workdir=ctx.workdir)


@register_tool(
    name="Read",
    aliases=["read_file"],
    description="Read the contents of a file.",
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the file (relative to workspace)"},
            "limit": {"type": "integer", "description": "Maximum number of lines to read"},
        },
        "required": ["path"],
    },
    risk_level=RiskLevel.LOW,
    is_read_only=True,
    is_concurrency_safe=True,
    required_capabilities=["file_read"],
)
def read_handler(path: str, limit: int | None = None, *, ctx: ToolContext) -> str:
    return read_file(path, workdir=ctx.workdir, limit=limit)


@register_tool(
    name="Write",
    aliases=["write_file"],
    description="Write content to a file (creates directories if needed).",
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the file"},
            "content": {"type": "string", "description": "Content to write"},
        },
        "required": ["path", "content"],
    },
    risk_level=RiskLevel.MEDIUM,
    required_capabilities=["file_write"],
)
def write_handler(path: str, content: str, *, ctx: ToolContext) -> str:
    return write_file(path, content, workdir=ctx.workdir)


@register_tool(
    name="Edit",
    aliases=["edit_file"],
    description="Replace exact text in a file (only first occurrence).",
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the file"},
            "old_text": {"type": "string", "description": "Text to find"},
            "new_text": {"type": "string", "description": "Text to replace with"},
        },
        "required": ["path", "old_text", "new_text"],
    },
    risk_level=RiskLevel.MEDIUM,
    required_capabilities=["file_write"],
)
def edit_handler(path: str, old_text: str, new_text: str, *, ctx: ToolContext) -> str:
    return edit_file(path, old_text, new_text, workdir=ctx.workdir)
```

在文件顶部补充导入：

```python
from bourbon.tools import RiskLevel, ToolContext, register_tool
```

- [ ] **Step 4: 运行确认通过**

```bash
pytest tests/test_tools_registry.py::TestBaseToolsRenamed tests/test_tools_base.py -v
```

期望：全部 PASS

- [ ] **Step 5: Commit**

```bash
git add src/bourbon/tools/base.py tests/test_tools_registry.py
git commit -m "feat(tools): rename base tools to PascalCase with ctx-aware handlers

Bash/Read/Write/Edit replace bash/read_file/write_file/edit_file.
Original helper functions preserved for direct test access.
Bash: is_destructive=True; Read: is_read_only=True + is_concurrency_safe=True"
```

---

### Task 3: 重命名 search.py 工具，新增 Glob

**Files:**
- Modify: `src/bourbon/tools/search.py`
- No test changes needed (test_tools_search.py tests helper functions directly)

- [ ] **Step 1: 写失败测试——Grep/AstGrep/Glob 注册**

追加到 `tests/test_tools_registry.py`：

```python
class TestSearchToolsRenamed:
    def test_grep_glob_registered(self):
        from bourbon.tools import definitions
        defs = definitions()
        names = {d["name"] for d in defs}
        assert "Grep" in names
        assert "AstGrep" in names
        assert "Glob" in names

    def test_glob_finds_files(self, tmp_path):
        from bourbon.tools import get_registry, ToolContext
        (tmp_path / "a.py").write_text("")
        (tmp_path / "b.py").write_text("")
        (tmp_path / "c.txt").write_text("")
        ctx = ToolContext(workdir=tmp_path)
        result = get_registry().call("Glob", {"pattern": "*.py"}, ctx)
        assert "a.py" in result
        assert "b.py" in result
        assert "c.txt" not in result

    def test_glob_truncates_at_100(self, tmp_path):
        from bourbon.tools import get_registry, ToolContext
        for i in range(110):
            (tmp_path / f"f{i}.py").write_text("")
        ctx = ToolContext(workdir=tmp_path)
        result = get_registry().call("Glob", {"pattern": "*.py"}, ctx)
        assert "truncated" in result.lower() or "100" in result

    def test_grep_is_read_only_and_concurrency_safe(self):
        from bourbon.tools import get_tool_with_metadata
        t = get_tool_with_metadata("Grep")
        assert t.is_read_only is True
        assert t.is_concurrency_safe is True
```

- [ ] **Step 2: 运行确认失败**

```bash
pytest tests/test_tools_registry.py::TestSearchToolsRenamed -v
```

期望：`AssertionError: 'Grep' not in ...`

- [ ] **Step 3: 修改 search.py——保留 helper 函数，重命名注册 + 新增 Glob**

在 `src/bourbon/tools/search.py` 底部，替换 `@register_tool` 注册代码：

```python
from bourbon.tools import RiskLevel, ToolContext, register_tool


@register_tool(
    name="Grep",
    aliases=["rg_search"],
    description="Search files using ripgrep (regex-based text search).",
    input_schema={
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Regex pattern to search for"},
            "path": {"type": "string", "description": "Directory or file to search (default: current directory)"},
            "glob": {"type": "string", "description": "File glob pattern, e.g., '*.py'"},
            "case_sensitive": {"type": "boolean", "description": "Case-sensitive search"},
        },
        "required": ["pattern"],
    },
    risk_level=RiskLevel.LOW,
    is_read_only=True,
    is_concurrency_safe=True,
    required_capabilities=["file_read"],
)
def grep_handler(
    pattern: str,
    path: str = ".",
    glob: str | None = None,
    case_sensitive: bool = False,
    *,
    ctx: ToolContext,
) -> str:
    # 将相对路径解析为相对于 ctx.workdir 的绝对路径
    from pathlib import Path
    resolved_path = str(ctx.workdir / path) if not Path(path).is_absolute() else path
    return rg_search(pattern, resolved_path, glob, case_sensitive)


@register_tool(
    name="AstGrep",
    aliases=["ast_grep_search"],
    description="Search code using ast-grep (structural/AST-based search).",
    input_schema={
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "ast-grep pattern (e.g., 'class $NAME:', 'def $FUNC($$$ARGS):')"},
            "path": {"type": "string", "description": "Directory or file to search"},
            "language": {"type": "string", "description": "Language hint (python, javascript, rust, etc.)"},
        },
        "required": ["pattern"],
    },
    risk_level=RiskLevel.LOW,
    is_read_only=True,
    is_concurrency_safe=True,
    required_capabilities=["file_read"],
)
def ast_grep_handler(
    pattern: str,
    path: str = ".",
    language: str | None = None,
    *,
    ctx: ToolContext,
) -> str:
    from pathlib import Path
    resolved_path = str(ctx.workdir / path) if not Path(path).is_absolute() else path
    return ast_grep_search(pattern, resolved_path, language)


def glob_files(pattern: str, path: str = ".", *, workdir: Path | None = None) -> str:
    """Find files matching a glob pattern.

    Args:
        pattern: Glob pattern, e.g. "**/*.py"
        path: Base directory to search (relative to workdir or absolute)
        workdir: Workspace root

    Returns:
        Newline-separated list of matching file paths (truncated at 100)
    """
    cwd = workdir or Path.cwd()
    base = Path(path) if Path(path).is_absolute() else cwd / path

    try:
        matches = sorted(base.glob(pattern))
    except Exception as e:
        return f"Error: {e}"

    truncated = len(matches) > 100
    matches = matches[:100]

    if not matches:
        return f"No files matching '{pattern}'"

    lines = [str(m.relative_to(cwd) if m.is_relative_to(cwd) else m) for m in matches]
    if truncated:
        lines.append("... (results truncated to 100 files)")
    return "\n".join(lines)


@register_tool(
    name="Glob",
    description="Find files matching a glob pattern (e.g. '**/*.py', 'src/**/*.ts').",
    input_schema={
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Glob pattern, e.g. '**/*.py'"},
            "path": {"type": "string", "description": "Base directory to search (default: workspace root)"},
        },
        "required": ["pattern"],
    },
    risk_level=RiskLevel.LOW,
    is_read_only=True,
    is_concurrency_safe=True,
    required_capabilities=["file_read"],
)
def glob_handler(pattern: str, path: str = ".", *, ctx: ToolContext) -> str:
    return glob_files(pattern, path, workdir=ctx.workdir)
```

在 `search.py` 顶部添加 `from pathlib import Path`（如未有）。

- [ ] **Step 4: 运行确认通过**

```bash
pytest tests/test_tools_registry.py::TestSearchToolsRenamed tests/test_tools_search.py -v
```

期望：全部 PASS

- [ ] **Step 5: Commit**

```bash
git add src/bourbon/tools/search.py tests/test_tools_registry.py
git commit -m "feat(tools): rename search tools + add Glob

Grep/AstGrep replace rg_search/ast_grep_search (aliases preserved).
New Glob tool: pathlib.Path.glob(), relative to ctx.workdir, truncates at 100 files.
All tools: is_read_only=True, is_concurrency_safe=True"
```

---

### Task 4: 重命名 skill_tool.py，接入 ctx.skill_manager

**Files:**
- Modify: `src/bourbon/tools/skill_tool.py`

- [ ] **Step 1: 写失败测试——Skill/SkillResource 注册 + ctx.skill_manager 优先**

追加到 `tests/test_tools_registry.py`：

```python
class TestSkillToolRenamed:
    def test_skill_skillresource_registered(self):
        from bourbon.tools import definitions
        defs = definitions()
        names = {d["name"] for d in defs}
        assert "Skill" in names
        assert "SkillResource" in names

    def test_skill_is_not_read_only(self):
        from bourbon.tools import get_tool_with_metadata
        t = get_tool_with_metadata("Skill")
        assert t.is_read_only is False

    def test_skill_uses_ctx_skill_manager_when_provided(self, tmp_path):
        """ctx.skill_manager 优先于全局 _skill_manager。"""
        from unittest.mock import MagicMock
        from bourbon.tools import get_registry, ToolContext
        mock_manager = MagicMock()
        mock_manager.is_activated.return_value = False
        mock_manager.activate.return_value = "mocked skill content"
        ctx = ToolContext(workdir=tmp_path, skill_manager=mock_manager)
        result = get_registry().call("Skill", {"name": "nonexistent-skill"}, ctx)
        mock_manager.activate.assert_called_once_with("nonexistent-skill")
        assert "mocked skill content" in result
```

- [ ] **Step 2: 运行确认失败**

```bash
pytest tests/test_tools_registry.py::TestSkillToolRenamed -v
```

期望：`AssertionError: 'Skill' not in ...`

- [ ] **Step 3: 修改 skill_tool.py**

保留原有函数 `get_skill_manager()`、`skill_tool()`、`skill_read_resource_tool()` **不变**（这些是被测试直接调用的 helper）。

在文件底部，替换 `@register_tool` 注册代码：

```python
@register_tool(
    name="Skill",
    aliases=["skill"],
    description="""Activate a skill to load specialized instructions and capabilities.

When to use:
- When starting a task that matches a skill's domain
- When the user mentions a specific domain or technology covered by a skill
- When you need guidance on best practices for a specific task type

The skill will provide detailed instructions, examples, and may include scripts or references.
""",
    input_schema={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Name of the skill to activate (as shown in available_skills catalog)",
            },
        },
        "required": ["name"],
    },
    risk_level=RiskLevel.LOW,
    is_read_only=False,
    required_capabilities=["skill"],
)
def skill_handler(name: str, *, ctx: ToolContext) -> str:
    """ctx.skill_manager 优先，降级到全局 _skill_manager。"""
    manager = ctx.skill_manager if ctx.skill_manager is not None else get_skill_manager()

    try:
        if manager.is_activated(name):
            return f'<skill_already_loaded name="{name}"/>\n\nSkill \'{name}\' is already active.'
        return manager.activate(name)
    except Exception as e:
        return f"Error activating skill '{name}': {e}"


@register_tool(
    name="SkillResource",
    aliases=["skill_read_resource"],
    description="""Read a resource file from an activated skill.

Use this to load scripts, references, or assets referenced by skill instructions.
""",
    input_schema={
        "type": "object",
        "properties": {
            "skill_name": {"type": "string", "description": "Name of the skill containing the resource"},
            "path": {
                "type": "string",
                "description": "Relative path to resource (e.g., 'scripts/extract.py', 'references/guide.md')",
            },
        },
        "required": ["skill_name", "path"],
    },
    risk_level=RiskLevel.LOW,
    is_read_only=True,
    is_concurrency_safe=True,
)
def skill_resource_handler(skill_name: str, path: str, *, ctx: ToolContext) -> str:
    manager = ctx.skill_manager if ctx.skill_manager is not None else get_skill_manager()
    skill = manager.get_skill(skill_name)
    if not skill:
        return f"Error: Skill '{skill_name}' not found"
    resource_path = skill.get_resource_path(path)
    if not resource_path:
        resources = skill.list_resources()
        available = []
        for _category, files in resources.items():
            available.extend(files)
        return (
            f"Error: Resource '{path}' not found in skill '{skill_name}'. "
            f"Available: {available or '(none)'}"
        )
    try:
        return resource_path.read_text(encoding="utf-8")
    except Exception as e:
        return f"Error reading resource: {e}"
```

在文件顶部补充导入：

```python
from bourbon.tools import RiskLevel, ToolContext, register_tool
```

- [ ] **Step 4: 运行确认通过**

```bash
pytest tests/test_tools_registry.py::TestSkillToolRenamed tests/test_skills_new.py -v
```

期望：全部 PASS

- [ ] **Step 5: Commit**

```bash
git add src/bourbon/tools/skill_tool.py tests/test_tools_registry.py
git commit -m "feat(tools): rename skill tools to Skill/SkillResource, add ctx.skill_manager support

Skill/SkillResource replace skill/skill_read_resource (aliases preserved).
Skill handler uses ctx.skill_manager when available, falls back to global manager.
Skill: is_read_only=False (aligns with Claude Code semantics)"
```

---

## Chunk 3: Stage-B 工具 + access_control 更新

### Task 5: 重命名 Stage-B 工具，标注 should_defer=True

**Files:**
- Modify: `src/bourbon/tools/web.py`
- Modify: `src/bourbon/tools/data.py`
- Modify: `src/bourbon/tools/documents.py`

- [ ] **Step 1: 写失败测试——Stage-B 工具注册为 deferred**

新建 `tests/test_tools_stage_b.py`：

```python
"""Tests for Stage-B deferred tools registration."""

import pytest

pytest.importorskip("aiohttp", reason="Stage-B web dependencies not installed")

from bourbon.tools import definitions, get_tool_with_metadata


class TestStageBDeferred:
    def test_web_fetch_registered_as_deferred(self):
        defs_default = definitions()
        names_default = {d["name"] for d in defs_default}
        assert "WebFetch" not in names_default, "WebFetch should NOT be in default prompt"

        t = get_tool_with_metadata("WebFetch")
        assert t is not None
        assert t.should_defer is True
        assert t.always_load is False

    def test_stage_b_visible_when_discovered(self):
        defs = definitions(discovered={"WebFetch"})
        names = {d["name"] for d in defs}
        assert "WebFetch" in names

    def test_aliases_preserved(self):
        t = get_tool_with_metadata("fetch_url")   # 旧名 alias
        assert t is not None
        assert t.name == "WebFetch"
```

- [ ] **Step 2: 运行确认失败**

```bash
pytest tests/test_tools_stage_b.py -v
```

期望：失败（WebFetch 不存在或仍在默认 prompt 中）

- [ ] **Step 3: 修改 web.py**

保留原 `fetch_url()` helper 函数不变。替换底部注册代码：

```python
from bourbon.tools import RiskLevel, ToolContext, register_tool


@register_tool(
    name="WebFetch",
    aliases=["fetch_url"],
    description="Fetch and extract content from a URL.",
    input_schema={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL to fetch"},
        },
        "required": ["url"],
    },
    risk_level=RiskLevel.MEDIUM,
    always_load=False,
    should_defer=True,
    search_hint="web fetch url http download browser",
    required_capabilities=["net"],
)
async def web_fetch_handler(url: str, *, ctx: ToolContext) -> str:
    result = await fetch_url(url)
    if isinstance(result, dict) and not result.get("success"):
        return f"Error: {result.get('error', 'Unknown error')}"
    if isinstance(result, dict):
        return result.get("text", str(result))
    return str(result)
```

- [ ] **Step 4: 修改 data.py**

保留原 helper 函数（`csv_analyze`、`json_query`）及其 schema 常量（`CSV_ANALYZE_SCHEMA`、`JSON_QUERY_SCHEMA`）不变。在文件顶部 import 行增加 `ToolContext`，在文件底部替换 `@register_tool` 注册代码：

```python
from bourbon.tools import RiskLevel, ToolContext, register_tool


@register_tool(
    name="CsvAnalyze",
    aliases=["csv_analyze"],
    description="Analyze CSV file with statistics and grouping.",
    input_schema=CSV_ANALYZE_SCHEMA,
    risk_level=RiskLevel.LOW,
    always_load=False,
    should_defer=True,
    is_read_only=True,
    search_hint="csv data analyze statistics spreadsheet",
    required_capabilities=["file_read"],
)
def csv_analyze_handler(
    file_path: str,
    operations: list[str] | None = None,
    *,
    ctx: ToolContext,
) -> str:
    import json
    from pathlib import Path
    resolved = str(ctx.workdir / file_path) if not Path(file_path).is_absolute() else file_path
    result = csv_analyze(resolved, operations)
    if isinstance(result, dict) and not result.get("success"):
        return f"Error: {result.get('error', 'Unknown error')}"
    return json.dumps(result, indent=2, default=str)


@register_tool(
    name="JsonQuery",
    aliases=["json_query"],
    description="Query JSON file with path expression.",
    input_schema=JSON_QUERY_SCHEMA,
    risk_level=RiskLevel.LOW,
    always_load=False,
    should_defer=True,
    is_read_only=True,
    search_hint="json query filter jq data",
    required_capabilities=["file_read"],
)
def json_query_handler(
    file_path: str,
    query: str | None = None,
    *,
    ctx: ToolContext,
) -> str:
    import json
    from pathlib import Path
    resolved = str(ctx.workdir / file_path) if not Path(file_path).is_absolute() else file_path
    result = json_query(resolved, query)
    if isinstance(result, dict) and not result.get("success"):
        return f"Error: {result.get('error', 'Unknown error')}"
    return json.dumps(result, indent=2, default=str)
```

- [ ] **Step 5: 修改 documents.py**

保留原 helper 函数（`pdf_to_text`、`docx_to_markdown`）及其 schema 常量不变。在文件顶部 import 行增加 `ToolContext`，在文件底部替换 `@register_tool` 注册代码：

```python
from bourbon.tools import RiskLevel, ToolContext, register_tool


@register_tool(
    name="PdfRead",
    aliases=["pdf_to_text"],
    description="Extract text from PDF file.",
    input_schema=PDF_TO_TEXT_SCHEMA,
    risk_level=RiskLevel.LOW,
    always_load=False,
    should_defer=True,
    is_read_only=True,
    search_hint="pdf document read extract text",
    required_capabilities=["file_read"],
)
def pdf_read_handler(
    file_path: str,
    page_range: list[int] | None = None,
    *,
    ctx: ToolContext,
) -> str:
    from pathlib import Path
    resolved = str(ctx.workdir / file_path) if not Path(file_path).is_absolute() else file_path
    result = pdf_to_text(resolved, page_range)
    if isinstance(result, dict) and not result.get("success"):
        return f"Error: {result.get('error', 'Unknown error')}"
    if isinstance(result, dict):
        return result.get("text", str(result))
    return str(result)


@register_tool(
    name="DocxRead",
    aliases=["docx_to_markdown"],
    description="Convert Word document to markdown.",
    input_schema=DOCX_TO_MARKDOWN_SCHEMA,
    risk_level=RiskLevel.LOW,
    always_load=False,
    should_defer=True,
    is_read_only=True,
    search_hint="docx word document read convert markdown",
    required_capabilities=["file_read"],
)
def docx_read_handler(
    file_path: str,
    *,
    ctx: ToolContext,
) -> str:
    from pathlib import Path
    resolved = str(ctx.workdir / file_path) if not Path(file_path).is_absolute() else file_path
    result = docx_to_markdown(resolved)
    if isinstance(result, dict) and not result.get("success"):
        return f"Error: {result.get('error', 'Unknown error')}"
    if isinstance(result, dict):
        return result.get("text", str(result))
    return str(result)
```

- [ ] **Step 6: 运行确认通过**

```bash
pytest tests/test_tools_stage_b.py tests/tools/test_web.py tests/tools/test_data.py tests/tools/test_documents.py -v
```

期望：全部 PASS

- [ ] **Step 7: Commit**

```bash
git add src/bourbon/tools/web.py src/bourbon/tools/data.py src/bourbon/tools/documents.py tests/test_tools_stage_b.py
git commit -m "feat(tools): rename Stage-B tools, mark should_defer=True

WebFetch/CsvAnalyze/JsonQuery/PdfRead/DocxRead replace old snake_case names.
all: always_load=False, should_defer=True → not in default prompt.
Original helper functions preserved for direct test access.
WebFetch async handler wrapped by AsyncRuntime in ToolRegistry.call()"
```

---

### Task 6: access_control 同步新工具名

**Files:**
- Modify: `src/bourbon/access_control/capabilities.py`
- Modify: `src/bourbon/access_control/__init__.py`
- Modify: `tests/test_capabilities.py`

- [ ] **Step 1: 写失败测试——新工具名 capability 推断**

在 `tests/test_capabilities.py` 末尾追加（同时保留旧测试——通过 canonicalize 后旧名路由到新名，access_control 集成测试覆盖）：

```python
class TestCapabilitiesNewNames:
    def test_new_names_infer_file_capabilities(self):
        """新工具名（主名）能正确推断 capabilities。"""
        ctx = infer_capabilities("Read", {"path": "src/app.py"}, [])
        assert CapabilityType.FILE_READ in ctx.capabilities
        assert ctx.file_paths == ["src/app.py"]

        ctx = infer_capabilities("Write", {"path": "out.txt"}, [])
        assert CapabilityType.FILE_WRITE in ctx.capabilities

        ctx = infer_capabilities("Edit", {"path": "notes.md"}, [])
        assert CapabilityType.FILE_WRITE in ctx.capabilities

        ctx = infer_capabilities("Grep", {"path": "src/"}, [])
        assert CapabilityType.FILE_READ in ctx.capabilities

        ctx = infer_capabilities("Glob", {}, [])
        assert CapabilityType.FILE_READ in ctx.capabilities

    def test_bash_new_name_infers_net_capability(self):
        ctx = infer_capabilities("Bash", {"command": "curl https://example.com"}, [])
        assert CapabilityType.NET in ctx.capabilities

    def test_glob_uses_workdir_default_path(self):
        ctx = infer_capabilities("AstGrep", {}, [])
        assert "." in ctx.file_paths

    def test_stage_b_tools_infer_file_read(self):
        """Stage-B 工具通过 file_path 键正确推断 FILE_READ。"""
        for tool_name in ("CsvAnalyze", "JsonQuery", "PdfRead", "DocxRead"):
            ctx = infer_capabilities(tool_name, {"file_path": "data/file.csv"}, [])
            assert CapabilityType.FILE_READ in ctx.capabilities, f"{tool_name} should have FILE_READ"
            assert ctx.file_paths == ["data/file.csv"]
```

- [ ] **Step 2: 运行确认失败**

```bash
pytest tests/test_capabilities.py::TestCapabilitiesNewNames -v
```

期望：各 capability 推断返回 0（新名不在旧 _FILE_TOOL_CAPABILITIES 中）

- [ ] **Step 3: 更新 capabilities.py**

替换 `_FILE_TOOL_CAPABILITIES`、`_SEARCH_TOOLS_WITH_WORKDIR_DEFAULT_PATH`，更新 `infer_capabilities()` 中的 `if tool_name == "bash":` 分支：

```python
_FILE_TOOL_CAPABILITIES = {
    "Read":       CapabilityType.FILE_READ,
    "Write":      CapabilityType.FILE_WRITE,
    "Edit":       CapabilityType.FILE_WRITE,
    "Grep":       CapabilityType.FILE_READ,
    "AstGrep":    CapabilityType.FILE_READ,
    "Glob":       CapabilityType.FILE_READ,
    # Stage-B tools（使用 file_path 字段）
    "CsvAnalyze": CapabilityType.FILE_READ,
    "JsonQuery":  CapabilityType.FILE_READ,
    "PdfRead":    CapabilityType.FILE_READ,
    "DocxRead":   CapabilityType.FILE_READ,
}

_SEARCH_TOOLS_WITH_WORKDIR_DEFAULT_PATH = {"Grep", "AstGrep"}


def infer_capabilities(
    tool_name: str,
    tool_input: object,
    base_capabilities: Sequence[CapabilityType],
) -> InferredContext:
    capabilities = list(base_capabilities)
    file_paths: list[str] = []

    if tool_name == "Bash":           # 改为新主名
        command = _bash_command(tool_input)
        if _contains_any(command, _BASH_NET_PATTERNS):
            capabilities.append(CapabilityType.NET)
        if _contains_any(command, _BASH_FILE_READ_PATTERNS):
            capabilities.append(CapabilityType.FILE_READ)
        if _contains_any(command, _BASH_FILE_WRITE_PATTERNS):
            capabilities.append(CapabilityType.FILE_WRITE)
    elif tool_name in _FILE_TOOL_CAPABILITIES:
        capabilities.append(_FILE_TOOL_CAPABILITIES[tool_name])
        path = _extract_path(tool_input)
        if path is not None:
            file_paths.append(path)
        elif tool_name in _SEARCH_TOOLS_WITH_WORKDIR_DEFAULT_PATH:
            file_paths.append(".")
    else:
        return InferredContext(capabilities, file_paths)

    return InferredContext(_dedupe(capabilities), file_paths)
```

同时扩展 `_extract_path()` 以支持 Stage-B 工具使用的 `file_path` 字段：

```python
def _extract_path(tool_input: object) -> str | None:
    if isinstance(tool_input, Mapping):
        # 支持 path（核心工具）和 file_path（Stage-B 工具）两种键
        path = tool_input.get("path") or tool_input.get("file_path")
        if isinstance(path, str) and path:
            return path
        return None
    if isinstance(tool_input, str) and tool_input:
        return tool_input
    return None
```

- [ ] **Step 4: 更新 access_control/__init__.py——加 canonicalize**

替换 `evaluate()` 方法：

```python
def evaluate(self, tool_name: str, tool_input: dict) -> PolicyDecision:
    tool_metadata = get_tool_with_metadata(tool_name)
    # canonicalize: 旧 alias（如 "bash"）→ 主名（"Bash"），保证 capability 推断用主名
    canonical_name = tool_metadata.name if tool_metadata else tool_name
    base_caps: list[CapabilityType] = (
        list(tool_metadata.required_capabilities or []) if tool_metadata else []
    )
    context = infer_capabilities(canonical_name, tool_input, base_caps)

    if canonical_name == "Bash":
        return self.engine.evaluate_command(tool_input.get("command", ""), context)
    return self.engine.evaluate(canonical_name, context)
```

- [ ] **Step 5: 更新 tests/test_capabilities.py 旧测试**

将旧测试中所有直接调用 `infer_capabilities` 时使用的旧名（`"read_file"`、`"write_file"`、`"edit_file"`、`"rg_search"`、`"ast_grep_search"`、`"bash"`）替换为新主名。示例：

```python
# 原 test_extracts_paths_for_file_tools 改为新名
def test_extracts_paths_for_file_tools():
    read_context = infer_capabilities("Read", {"path": "src/app.py"}, [CapabilityType.EXEC])
    assert CapabilityType.FILE_READ in read_context.capabilities
    assert read_context.file_paths == ["src/app.py"]

    write_context = infer_capabilities("Write", {"path": "notes/todo.txt"}, [])
    assert CapabilityType.FILE_WRITE in write_context.capabilities
    assert write_context.file_paths == ["notes/todo.txt"]

    edit_context = infer_capabilities("Edit", {"path": "docs/spec.md"}, [])
    assert CapabilityType.FILE_WRITE in edit_context.capabilities
    assert edit_context.file_paths == ["docs/spec.md"]
```

对 `test_capabilities.py` 中其他直接调用 `infer_capabilities` 的测试做同样替换（逐一确认文件中所有旧名引用）。

- [ ] **Step 6: 运行确认通过**

```bash
pytest tests/test_capabilities.py tests/test_access_controller.py tests/test_agent_security_integration.py -v
```

期望：全部 PASS

- [ ] **Step 7: Commit**

```bash
git add src/bourbon/access_control/capabilities.py src/bourbon/access_control/__init__.py tests/test_capabilities.py
git commit -m "feat(access_control): sync to new tool names, add canonicalize in evaluate()

capabilities.py: _FILE_TOOL_CAPABILITIES uses Read/Write/Edit/Grep/AstGrep/Glob.
access_control/__init__.py: evaluate() canonicalizes tool_name via get_tool_with_metadata()
before passing to infer_capabilities() — old aliases route correctly.
test_capabilities.py: updated to use new canonical names"
```

---

## Chunk 4: Deferred 发现机制 + Agent 修改

### Task 7: 新建 ToolSearch 工具

**Files:**
- Create: `src/bourbon/tools/tool_search.py`
- Create: `tests/test_tool_search.py`

- [ ] **Step 1: 写失败测试**

新建 `tests/test_tool_search.py`：

```python
"""Tests for ToolSearch deferred tool discovery."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from bourbon.tools import ToolContext, get_registry, definitions


@pytest.fixture(autouse=True)
def ensure_tools_registered():
    """Ensure all tools are registered before each test.

    get_registry().call() does NOT call _ensure_imports(). Only definitions(),
    handler(), get_tool_with_metadata() do. Call definitions() first to trigger
    lazy import and populate the global registry.
    """
    definitions()


class TestToolSearch:
    def test_tool_search_registered_as_always_load(self):
        defs = definitions()
        names = {d["name"] for d in defs}
        assert "ToolSearch" in names

    def test_tool_search_finds_deferred_tools(self):
        discovered: set[str] = set()
        ctx = ToolContext(
            workdir=Path("/tmp"),
            on_tools_discovered=discovered.update,
        )
        result = get_registry().call("ToolSearch", {"query": "csv analyze"}, ctx)
        # 如果 Stage-B 依赖已安装，应该发现 CsvAnalyze
        # 如果没安装，返回 "No tools found"（两种都可以接受）
        assert isinstance(result, str)
        assert len(result) > 0

    def test_token_scoring_matches_webfetch(self):
        """'fetch web' query 应命中 WebFetch（若已注册）。"""
        pytest.importorskip("aiohttp")
        discovered: set[str] = set()
        ctx = ToolContext(
            workdir=Path("/tmp"),
            on_tools_discovered=discovered.update,
        )
        result = get_registry().call("ToolSearch", {"query": "fetch web page"}, ctx)
        if "WebFetch" in result:
            assert "WebFetch" in discovered

    def test_no_match_returns_helpful_message(self):
        discovered: set[str] = set()
        ctx = ToolContext(
            workdir=Path("/tmp"),
            on_tools_discovered=discovered.update,
        )
        result = get_registry().call(
            "ToolSearch", {"query": "xxxxxxxxnothing"}, ctx
        )
        assert "No tools found" in result

    def test_on_tools_discovered_callback_called(self):
        """ToolSearch 发现工具后调用 on_tools_discovered 回调（需 pandas）。"""
        pytest.importorskip("pandas")  # CsvAnalyze 依赖 pandas
        discovered: set[str] = set()
        ctx = ToolContext(
            workdir=Path("/tmp"),
            on_tools_discovered=discovered.update,
        )
        get_registry().call("ToolSearch", {"query": "csv analyze"}, ctx)
        assert len(discovered) > 0, "on_tools_discovered should have been called with matched tools"
        assert all(isinstance(n, str) for n in discovered)
```

- [ ] **Step 2: 运行确认失败**

```bash
pytest tests/test_tool_search.py -v
```

期望：`AssertionError: 'ToolSearch' not in ...`

- [ ] **Step 3: 创建 tool_search.py**

新建 `src/bourbon/tools/tool_search.py`：

```python
"""ToolSearch: deferred tool discovery for Bourbon agent."""

from bourbon.tools import RiskLevel, Tool, ToolContext, get_registry, register_tool


def _score(tool: Tool, tokens: list[str]) -> int:
    """Score a tool against query tokens.

    Scoring:
    - Token in tool name: +10
    - Token in search_hint: +4
    - Token in description: +2
    """
    s = 0
    name_lower = tool.name.lower()
    desc_lower = tool.description.lower()
    hint_lower = (tool.search_hint or "").lower()
    for token in tokens:
        if token in name_lower:
            s += 10
        if hint_lower and token in hint_lower:
            s += 4
        if token in desc_lower:
            s += 2
    return s


@register_tool(
    name="ToolSearch",
    description=(
        "Discover and load additional tools by keyword. "
        "Use when you need capabilities not in the current tool list "
        "(e.g., web fetching, CSV analysis, PDF reading)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Keywords describing the capability you need (e.g., 'fetch web page', 'analyze csv')",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of tools to return (default: 5)",
            },
        },
        "required": ["query"],
    },
    risk_level=RiskLevel.LOW,
    is_read_only=True,
    is_concurrency_safe=True,
    always_load=True,
    search_hint="discover find tools capabilities load enable",
)
def tool_search_handler(query: str, max_results: int = 5, *, ctx: ToolContext) -> str:
    registry = get_registry()
    deferred = [t for t in registry.list_tools() if t.should_defer]

    if not deferred:
        return "No additional tools available."

    tokens = [w for w in query.lower().split() if len(w) > 1]
    if not tokens:
        return f"No tools found matching '{query}'"

    scored = sorted(deferred, key=lambda t: _score(t, tokens), reverse=True)
    matches = [t for t in scored if _score(t, tokens) > 0][:max_results]

    if ctx.on_tools_discovered and matches:
        ctx.on_tools_discovered({t.name for t in matches})

    if not matches:
        return f"No tools found matching '{query}'"

    lines = [f"Found {len(matches)} tool(s) matching '{query}':\n"]
    for t in matches:
        lines.append(f"- {t.name}: {t.description}")
    lines.append("\nThese tools are now available for use.")
    return "\n".join(lines)
```

- [ ] **Step 4: 运行确认通过**

```bash
pytest tests/test_tool_search.py -v
```

期望：全部 PASS（`test_token_scoring_matches_webfetch` 和 `test_on_tools_discovered_callback_called` 在依赖未装时会 skip）

- [ ] **Step 5: Commit**

```bash
git add src/bourbon/tools/tool_search.py tests/test_tool_search.py
git commit -m "feat(tools): add ToolSearch for deferred tool discovery

ToolSearch (always_load=True) searches should_defer=True tools by keyword.
Per-token scoring: name match +10, search_hint +4, description +2.
Calls ctx.on_tools_discovered(matched_names) to update Agent's discovered set."
```

---

### Task 8: Agent 修改——接入 deferred 发现机制

**Files:**
- Modify: `src/bourbon/agent.py`
- Modify: `tests/test_agent_streaming.py` (可能需要补充测试)

- [ ] **Step 1: 写失败测试——_discovered_tools 和 definitions 调用**

新建 `tests/test_agent_tool_discovery.py`：

```python
"""Tests for agent deferred tool discovery."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestAgentDiscoveredTools:
    def _make_agent(self, tmp_path):
        """Create Agent via real __init__, patching create_client to avoid LLM init.

        Agent.__init__ calls create_client(config) which raises if no API key.
        Match the pattern used in test_agent_streaming.py and
        test_agent_security_integration.py: bypass LLM creation with a mock.
        """
        from bourbon.agent import Agent
        from bourbon.config import Config

        with patch("bourbon.agent.create_client", return_value=MagicMock()):
            agent = Agent(config=Config(), workdir=tmp_path)
        return agent

    def test_agent_has_discovered_tools_attr(self, tmp_path):
        agent = self._make_agent(tmp_path)
        assert hasattr(agent, "_discovered_tools")
        assert isinstance(agent._discovered_tools, set)
        assert len(agent._discovered_tools) == 0

    def test_make_tool_context_passes_workdir(self, tmp_path):
        agent = self._make_agent(tmp_path)
        ctx = agent._make_tool_context()
        assert ctx.workdir == tmp_path

    def test_make_tool_context_passes_skill_manager(self, tmp_path):
        agent = self._make_agent(tmp_path)
        ctx = agent._make_tool_context()
        assert ctx.skill_manager is agent.skills

    def test_make_tool_context_on_tools_discovered_updates_set(self, tmp_path):
        agent = self._make_agent(tmp_path)
        ctx = agent._make_tool_context()
        ctx.on_tools_discovered({"WebFetch", "CsvAnalyze"})
        assert "WebFetch" in agent._discovered_tools
        assert "CsvAnalyze" in agent._discovered_tools

    def test_definitions_called_with_discovered(self, tmp_path):
        agent = self._make_agent(tmp_path)
        # __init__ already creates session; limit rounds and inject WebFetch
        agent._discovered_tools.add("WebFetch")
        agent._max_tool_rounds = 1

        with patch("bourbon.agent.definitions") as mock_defs:
            mock_defs.return_value = []
            try:
                agent._run_conversation_loop()  # 无参数
            except Exception:
                pass
            # 验证 definitions 被调用时传入了 discovered
            found = False
            for call in mock_defs.call_args_list:
                if call.kwargs.get("discovered") is not None:
                    assert "WebFetch" in call.kwargs["discovered"]
                    found = True
                    break
            assert found, "definitions() was never called with discovered= kwarg"
```

- [ ] **Step 2: 运行确认失败**

```bash
pytest tests/test_agent_tool_discovery.py -v
```

期望：`AttributeError: 'Agent' object has no attribute '_discovered_tools'`

- [ ] **Step 3: 修改 agent.py——添加 _discovered_tools 和 _make_tool_context()**

在 `Agent.__init__()` 中（找到合适位置，如 `self.skills` 初始化之后）添加：

```python
self._discovered_tools: set[str] = set()
```

添加新方法（在 `_execute_regular_tool` 之前）：

```python
def _make_tool_context(self) -> "ToolContext":
    """构造工具执行上下文。"""
    from bourbon.tools import ToolContext
    return ToolContext(
        workdir=self.workdir,
        skill_manager=self.skills,
        on_tools_discovered=self._discovered_tools.update,
    )
```

- [ ] **Step 4: 修改 agent.py——更新 3 处 definitions() 调用**

先确认所有调用点：

```bash
grep -n "definitions()" src/bourbon/agent.py
```

对输出的每一行（应有 3 处），将 `definitions()` 改为 `definitions(discovered=self._discovered_tools)`：

```python
# 改前
tools=definitions(),
# 改后
tools=definitions(discovered=self._discovered_tools),
```

替换完成后再次运行 grep 确认结果数量为 0：

```bash
grep -n "definitions()" src/bourbon/agent.py  # 应无输出
grep -n "definitions(discovered=" src/bourbon/agent.py  # 应有 3 处
```

- [ ] **Step 5: 运行部分测试确认通过**

```bash
pytest tests/test_agent_tool_discovery.py::TestAgentDiscoveredTools::test_agent_has_discovered_tools_attr tests/test_agent_tool_discovery.py::TestAgentDiscoveredTools::test_make_tool_context_passes_workdir -v
```

期望：PASS

- [ ] **Step 6: 修改 _execute_regular_tool()——改为 registry.call()**

在 `_execute_regular_tool()` 中（行 833 附近），替换旧的 handler 调用：

```python
def _execute_regular_tool(
    self,
    tool_name: str,
    tool_input: dict,
    *,
    skip_policy_check: bool = False,
) -> str:
    """Execute one tool call with policy, audit, and sandbox integration."""
    # === 保留：policy 检查 ===
    tool_metadata = get_tool_with_metadata(tool_name)

    if not skip_policy_check:
        decision = self.access_controller.evaluate(tool_name, tool_input)
        self._record_policy_decision(
            tool_name=tool_name,
            tool_input=tool_input,
            decision=decision,
        )
        if decision.action == PolicyAction.DENY:
            return f"Denied: {decision.reason}"
        if decision.action == PolicyAction.NEED_APPROVAL:
            self.pending_confirmation = PendingConfirmation(
                tool_name=tool_name,
                tool_input=tool_input,
                error_output=f"Requires approval: {decision.reason}",
                options=["Approve and execute", "Skip this operation"],
                confirmation_type="policy_approval",
            )
            return f"Requires approval: {decision.reason}"

    # === 保留：sandbox 路由（只有 is_destructive 工具走 sandbox）===
    if tool_metadata and tool_metadata.is_destructive and getattr(self.sandbox, "enabled", False):
        sandbox_result = self.sandbox.execute(
            tool_input.get("command", ""), tool_name=tool_name
        )
        output = self._format_sandbox_output(sandbox_result)
        self.audit.record(
            AuditEvent.tool_call(
                tool_name=tool_name,
                tool_input_summary=str(tool_input)[:200],
                sandboxed=True,
            )
        )
        return output

    # === 修改：通过 registry.call() 注入 ctx，替换旧的 workdir 注入逻辑 ===
    try:
        from bourbon.tools import get_registry
        ctx = self._make_tool_context()
        output = get_registry().call(tool_name, tool_input, ctx)
    except Exception as e:
        return f"Error executing {tool_name}: {e}"

    # === 保留：audit 记录 ===
    self.audit.record(
        AuditEvent.tool_call(
            tool_name=tool_name,
            tool_input_summary=str(tool_input)[:200],
        )
    )

    # === 保留：high-risk 失败确认 ===
    if (
        tool_metadata
        and output.startswith("Error")
        and tool_metadata.is_high_risk_operation(tool_input)
    ):
        self.pending_confirmation = PendingConfirmation(
            tool_name=tool_name,
            tool_input=tool_input,
            error_output=output,
            options=self._generate_options(tool_name, tool_input, output),
            confirmation_type="high_risk_failure",
        )

    return output
```

- [ ] **Step 7: 修改 _execute_tools()——删除 skill 手动分支，保留其他**

在 `_execute_tools()` 中找到 `elif tool_name == "skill":` 分支（行 947 附近），删除它：

```python
# 删除以下代码块：
elif tool_name == "skill":
    # skill tool is handled by registered handler, but we keep
    # this for backward compatibility during transition
    ...（整个 elif 块）
```

保留 `compress`、`TodoWrite` 的特殊处理路径不变。`Skill` 工具现在统一走 `_execute_regular_tool()` → `registry.call()` 路径。

删除后，验证 skill 工具的 ctx 路径端到端可通：

```bash
pytest tests/test_skills_new.py -v
# 确保 skill 相关测试通过（Skill 现在走 registry.call() + ctx.skill_manager）
```

- [ ] **Step 8: 修改 _generate_options() 中的工具名检查（行 1024）**

```python
# 改前
elif tool_name in ("write_file", "edit_file"):
# 改后
elif tool_metadata and not tool_metadata.is_read_only and not tool_metadata.is_destructive:
```

- [ ] **Step 9: 运行全量测试**

```bash
pytest tests/ -v --tb=short 2>&1 | tail -100
```

期望：全部 PASS（或仅 stage-b 相关依赖 skip）

- [ ] **Step 10: 若有测试失败，逐一修复后重新运行**

常见问题：
- `test_agent_streaming.py` 中若有直接调用旧工具名 → 通过 alias 应该能工作
- `test_agent_security_integration.py` 中的 "bash" → alias 路由应正常

- [ ] **Step 11: Commit**

```bash
git add src/bourbon/agent.py tests/test_agent_tool_discovery.py
git commit -m "feat(agent): add _discovered_tools + ToolContext integration

- _discovered_tools: set[str] tracks ToolSearch-discovered deferred tools
- _make_tool_context(): constructs ToolContext with workdir, skills, callback
- 3 definitions() calls updated to definitions(discovered=self._discovered_tools)
- _execute_regular_tool(): uses registry.call()+ctx, removes workdir kwarg injection
- skill manual branch removed from _execute_tools() (Skill routes via registry)
- _generate_options() line 1024: uses tool attributes instead of name strings"
```

---

### Task 9: 最终回归验证

- [ ] **Step 1: 运行完整测试套件**

```bash
cd /home/hf/github_project/build-my-agent
pytest tests/ -v --tb=short 2>&1 | tee /tmp/test_results.txt
grep -E "PASSED|FAILED|ERROR|SKIPPED" /tmp/test_results.txt | tail -20
```

- [ ] **Step 2: 运行 linter 和类型检查**

```bash
ruff check src tests
ruff format --check src tests
mypy src
```

- [ ] **Step 3: 若有失败，逐一修复**

参考：
- `FAILED` → 查看具体错误，通常是工具名引用未更新
- `mypy` 错误 → 多为 ToolContext 类型注解未引入
- `ruff` 错误 → 格式化或未使用导入

- [ ] **Step 4: 最终 commit（若有小修复）**

```bash
git add -A
git commit -m "fix: final regression fixes after tool architecture alignment"
```

- [ ] **Step 5: 验证 ToolSearch 端到端流程（可选手动测试）**

```bash
python -c "
from pathlib import Path
from bourbon.tools import ToolContext, get_registry, definitions

# 默认 prompt 不含 Stage-B
defs = definitions()
names = {d['name'] for d in defs}
print('Default tools:', sorted(names))
assert 'WebFetch' not in names

# ToolSearch 发现后加入 discovered
discovered = set()
ctx = ToolContext(workdir=Path('.'), on_tools_discovered=discovered.update)
result = get_registry().call('ToolSearch', {'query': 'fetch web'}, ctx)
print('ToolSearch result:', result)
print('Discovered:', discovered)

# 发现后出现在 prompt
defs2 = definitions(discovered=discovered)
names2 = {d['name'] for d in defs2}
print('After discovery:', sorted(names2))
"
```

---

## 附录：工具重命名速查表

| 旧名 | 新主名 | always_load | should_defer |
|------|--------|:-----------:|:------------:|
| `bash` | `Bash` | ✅ | ❌ |
| `read_file` | `Read` | ✅ | ❌ |
| `write_file` | `Write` | ✅ | ❌ |
| `edit_file` | `Edit` | ✅ | ❌ |
| `rg_search` | `Grep` | ✅ | ❌ |
| `ast_grep_search` | `AstGrep` | ✅ | ❌ |
| `skill` | `Skill` | ✅ | ❌ |
| `skill_read_resource` | `SkillResource` | ✅ | ❌ |
| *(新)* | `Glob` | ✅ | ❌ |
| *(新)* | `ToolSearch` | ✅ | ❌ |
| `fetch_url` | `WebFetch` | ❌ | ✅ |
| `csv_analyze` | `CsvAnalyze` | ❌ | ✅ |
| `json_query` | `JsonQuery` | ❌ | ✅ |
| `pdf_to_text` | `PdfRead` | ❌ | ✅ |
| `docx_to_markdown` | `DocxRead` | ❌ | ✅ |
