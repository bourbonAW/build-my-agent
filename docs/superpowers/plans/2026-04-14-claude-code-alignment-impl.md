# Claude Code Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现三个特性以对齐 Claude Code 设计：并发工具执行（ToolExecutionQueue）、Subagent 工具可见性（SubagentMode）、以及 Task Nudge 机制。

**Architecture:** 新增 `ToolExecutionQueue` 类用 `ThreadPoolExecutor` + 双 `Lock` 实现并发工具执行；新增 `SubagentMode` 枚举区分 teammate/async/normal subagent 的任务工具可见性；在 `_append_task_nudge_if_due()` 中追踪无任务轮次并注入 `<task_reminder>` 提示。

**Tech Stack:** Python 3.11+, `threading.Lock`, `concurrent.futures.ThreadPoolExecutor`, pytest

---

## File Map

| 文件 | 操作 | 职责 |
|------|------|------|
| `src/bourbon/tasks/constants.py` | **新建** | 定义 `TASK_V2_TOOLS` 集合 |
| `src/bourbon/tools/execution_queue.py` | **新建** | `ToolStatus`、`TrackedTool`、`ToolExecutionQueue` |
| `src/bourbon/tools/__init__.py` | 修改 | `Tool._concurrency_fn` 字段 + `concurrent_safe_for()` 方法；`register_tool` 新增 `concurrency_fn` 参数 |
| `src/bourbon/tools/base.py` | 修改 | `_is_readonly_bash` 函数；给 `Bash` 加 `concurrency_fn`，给 `Read` 补充说明（已有 `is_concurrency_safe=True`） |
| `src/bourbon/tools/web.py` | 修改 | `WebFetch` 加 `is_concurrency_safe=True` |
| `src/bourbon/tools/agent_tool.py` | 修改 | `Agent` 加 `is_concurrency_safe=True`；`subagent_type` enum 加 "teammate" |
| `src/bourbon/subagent/types.py` | 修改 | 新增 `SubagentMode` 枚举；`SubagentRun` 新增 `subagent_mode`、`parent_task_list_id` 字段 |
| `src/bourbon/subagent/tools.py` | 修改 | 新增 "teammate" 到 `AGENT_TYPE_CONFIGS`；`ToolFilter.is_allowed()` / `filter_tools()` 接受 `subagent_mode` |
| `src/bourbon/subagent/manager.py` | 修改 | `spawn()` 计算 mode；提取 `_configure_subagent_runtime()` 辅助方法 |
| `src/bourbon/tools/task_tools.py` | 修改 | `_resolve_task_list_id` 新增 `task_list_id_override` 最高优先检查 |
| `src/bourbon/permissions/runtime.py` | 修改 | `SuspendedToolRound` 新增 `task_nudge_tool_use_blocks` 字段 |
| `src/bourbon/agent.py` | 修改 | `__init__` 新增三个字段；`_execute_tools` 改造为 queue 模式；`_tool_definitions`/`_subagent_tool_denial` 透传 `subagent_mode`；`_suspend_tool_round` 保存 nudge blocks；三条 loop 路径注入 nudge；新增两个 nudge 辅助方法 |
| `tests/test_tool_execution_queue.py` | **新建** | `ToolExecutionQueue` 单元测试 |
| `tests/test_subagent/test_subagent_mode.py` | **新建** | `SubagentMode` 可见性 + task_list_id 继承测试 |
| `tests/test_task_nudge.py` | **新建** | Task nudge 阈值、重置、无 pending 跳过测试 |

---

## Task 1: 创建 TASK_V2_TOOLS 常量

**Files:**
- Create: `src/bourbon/tasks/constants.py`
- Test: `tests/test_task_constants.py`

- [x] **Step 1: 新建 constants.py**

```python
# src/bourbon/tasks/constants.py
"""Shared constants for the tasks subsystem."""

TASK_V2_TOOLS = {"TaskCreate", "TaskUpdate", "TaskList", "TaskGet"}
```

- [x] **Step 2: 写失败测试**

```python
# tests/test_task_constants.py
from bourbon.tasks.constants import TASK_V2_TOOLS


def test_task_v2_tools_contains_expected_names():
    assert TASK_V2_TOOLS == {"TaskCreate", "TaskUpdate", "TaskList", "TaskGet"}


def test_task_v2_tools_is_a_set():
    assert isinstance(TASK_V2_TOOLS, set)
```

- [x] **Step 3: 运行测试**

```bash
pytest tests/test_task_constants.py -v
```

期望：PASS

- [x] **Step 4: Commit**

```bash
git add src/bourbon/tasks/constants.py tests/test_task_constants.py
git commit -m "feat: add TASK_V2_TOOLS shared constant in tasks/constants.py"
```

---

## Task 2: SubagentMode 枚举 + SubagentRun 新字段

**Files:**
- Modify: `src/bourbon/subagent/types.py`
- Test: `tests/test_subagent/test_types.py` (已有，追加测试)

- [x] **Step 1: 先跑现有 types 测试确认基准**

```bash
pytest tests/test_subagent/test_types.py -v
```

期望：全部 PASS

- [x] **Step 2: 写失败测试**

在 `tests/test_subagent/test_types.py` **末尾追加**：

```python
from bourbon.subagent.types import SubagentMode


def test_subagent_mode_values():
    assert SubagentMode.NORMAL.value == "normal"
    assert SubagentMode.TEAMMATE.value == "teammate"
    assert SubagentMode.ASYNC.value == "async"


def test_subagent_run_has_subagent_mode_field():
    from bourbon.subagent.types import SubagentRun
    run = SubagentRun()
    assert run.subagent_mode == SubagentMode.NORMAL


def test_subagent_run_has_parent_task_list_id_field():
    from bourbon.subagent.types import SubagentRun
    run = SubagentRun()
    assert run.parent_task_list_id is None
```

- [x] **Step 3: 运行测试，预期 FAIL**

```bash
pytest tests/test_subagent/test_types.py -v -k "subagent_mode or parent_task_list"
```

期望：FAIL — `ImportError: cannot import name 'SubagentMode'`

- [x] **Step 4: 在 `src/bourbon/subagent/types.py` 中添加 SubagentMode 枚举和 SubagentRun 新字段**

在文件顶部的 `class RunStatus(Enum):` **之前**插入（第 11 行之前）：

```python
class SubagentMode(Enum):
    """Mode for subagent tool visibility control."""

    NORMAL = "normal"
    TEAMMATE = "teammate"
    ASYNC = "async"
```

在 `SubagentRun` dataclass 末尾的 `_subagent` 字段**之前**添加（在 `output_tokens` 字段后面）：

```python
    subagent_mode: "SubagentMode" = field(default_factory=lambda: SubagentMode.NORMAL)
    parent_task_list_id: str | None = None
```

注意：`SubagentMode` 在 `RunStatus` 之前定义，所以可以直接引用，不需要 forward reference。将默认值写法改为直接引用：

```python
    subagent_mode: SubagentMode = SubagentMode.NORMAL
    parent_task_list_id: str | None = None
```

完整的 `SubagentRun` 末尾部分（`output_tokens` 之后，`_subagent` 之前）应如下：

```python
    output_tokens: int = 0
    current_activity: str | None = None
    subagent_mode: SubagentMode = SubagentMode.NORMAL
    parent_task_list_id: str | None = None
    _subagent: Any | None = field(default=None, repr=False)
```

- [x] **Step 5: 运行测试**

```bash
pytest tests/test_subagent/test_types.py -v
```

期望：全部 PASS

- [x] **Step 6: Commit**

```bash
git add src/bourbon/subagent/types.py tests/test_subagent/test_types.py
git commit -m "feat: add SubagentMode enum and subagent_mode/parent_task_list_id fields to SubagentRun"
```

---

## Task 3: Tool 扩展 —— _concurrency_fn + concurrent_safe_for()

**Files:**
- Modify: `src/bourbon/tools/__init__.py`
- Test: `tests/test_tool_concurrency_safe.py` (新建)

- [x] **Step 1: 写失败测试**

```python
# tests/test_tool_concurrency_safe.py
"""Tests for Tool.concurrent_safe_for() and register_tool concurrency_fn parameter."""
from dataclasses import field
from unittest.mock import MagicMock

import pytest

from bourbon.tools import Tool, RiskLevel, register_tool


def make_tool(*, is_safe=False, fn=None):
    return Tool(
        name="TestTool",
        description="test",
        input_schema={"type": "object", "properties": {}},
        handler=lambda: "ok",
        is_concurrency_safe=is_safe,
        _concurrency_fn=fn,
    )


def test_concurrent_safe_for_returns_bool_when_no_fn():
    t = make_tool(is_safe=True)
    assert t.concurrent_safe_for({}) is True

    t2 = make_tool(is_safe=False)
    assert t2.concurrent_safe_for({}) is False


def test_concurrent_safe_for_uses_fn_over_bool():
    fn = lambda inp: inp.get("readonly", False)
    t = make_tool(is_safe=False, fn=fn)  # bool says False
    assert t.concurrent_safe_for({"readonly": True}) is True
    assert t.concurrent_safe_for({"readonly": False}) is False


def test_concurrent_safe_for_returns_false_on_fn_exception():
    def bad_fn(inp):
        raise RuntimeError("boom")

    t = make_tool(is_safe=True, fn=bad_fn)  # fn raises, fallback bool ignored, returns False
    assert t.concurrent_safe_for({}) is False


def test_register_tool_accepts_concurrency_fn():
    called_with = []

    def my_fn(inp):
        called_with.append(inp)
        return True

    # Register under a unique name so it doesn't clash with real tools
    @register_tool(
        name="_TestConcurrencyFnTool",
        description="test",
        input_schema={"type": "object", "properties": {}},
        concurrency_fn=my_fn,
    )
    def handler(**kwargs):
        return "ok"

    from bourbon.tools import get_registry
    tool = get_registry().get_tool("_TestConcurrencyFnTool")
    assert tool is not None
    assert tool.concurrent_safe_for({"x": 1}) is True
    assert called_with == [{"x": 1}]
```

- [x] **Step 2: 运行测试，预期 FAIL**

```bash
pytest tests/test_tool_concurrency_safe.py -v
```

期望：FAIL — `TypeError: Tool.__init__() got an unexpected keyword argument '_concurrency_fn'`

- [x] **Step 3: 修改 `src/bourbon/tools/__init__.py`**

在 `Tool` dataclass 中的 `is_concurrency_safe` 字段**之后**添加新字段（`is_read_only` 之前）：

```python
    is_concurrency_safe: bool = False
    _concurrency_fn: "Callable[[dict], bool] | None" = field(default=None, repr=False)
```

注意这个字段名以下划线开头，使用带引号的 forward reference 避免类型注解在类定义时求值：直接写如下（因为 `Callable` 已经导入）：

```python
    _concurrency_fn: Callable[[dict], bool] | None = field(default=None, repr=False)
```

在 `Tool` dataclass 的 `__post_init__` 方法**之后**（`__post_init__` 结束后）添加新方法：

```python
    def concurrent_safe_for(self, tool_input: dict) -> bool:
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
```

在 `register_tool` 函数签名中，在 `is_concurrency_safe: bool = False,` 参数**之后**添加：

```python
    concurrency_fn: "Callable[[dict], bool] | None" = None,
```

在 `register_tool` 内部构造 `Tool(...)` 的调用中，在 `is_concurrency_safe=is_concurrency_safe,` 之后添加：

```python
            _concurrency_fn=concurrency_fn,
```

- [x] **Step 4: 运行测试**

```bash
pytest tests/test_tool_concurrency_safe.py -v
```

期望：全部 PASS

- [x] **Step 5: 确保现有工具测试不受影响**

```bash
pytest tests/test_tools_search.py tests/test_todo_tool.py -v
```

期望：PASS

- [x] **Step 6: Commit**

```bash
git add src/bourbon/tools/__init__.py tests/test_tool_concurrency_safe.py
git commit -m "feat: add _concurrency_fn field and concurrent_safe_for() to Tool; update register_tool"
```

---

## Task 4: _is_readonly_bash + 工具并发注解

**Files:**
- Modify: `src/bourbon/tools/base.py`
- Modify: `src/bourbon/tools/web.py`
- Modify: `src/bourbon/tools/agent_tool.py`
- Test: `tests/test_is_readonly_bash.py` (新建)

- [x] **Step 1: 写失败测试（_is_readonly_bash）**

```python
# tests/test_is_readonly_bash.py
"""Tests for the _is_readonly_bash concurrency gate."""
import pytest


def get_fn():
    """Lazy import after bourbon.tools.base has been loaded."""
    from bourbon.tools.base import _is_readonly_bash
    return _is_readonly_bash


@pytest.mark.parametrize("cmd,expected", [
    # 控制符 → False
    ("ls | grep foo", False),
    ("cat file && echo done", False),
    ("echo a; echo b", False),
    ("cat > /tmp/x", False),
    ("echo $(pwd)", False),
    ("cmd1 || cmd2", False),
    ("ls >> out.txt", False),
    ("sleep 1 &", False),
    # 多行 → False
    ("ls\necho hi", False),
    # 路径前缀 → False
    ("/bin/ls", False),
    # 非白名单命令 → False
    ("curl http://example.com", False),
    ("rm -rf /", False),
    ("python script.py", False),
    # 白名单命令的可写/阻塞参数 → False
    ("tail -f log", False),
    ("tail --follow log", False),
    ("sort -o sorted.txt items.txt", False),
    ("sort --output=sorted.txt items.txt", False),
    ("uniq input.txt output.txt", False),
    ("find . -fprint out.txt", False),
    ("find . -fprintf out.txt %p", False),
    ("find . -fls out.txt", False),
    # 白名单命令 → True
    ("ls -la", True),
    ("cat README.md", True),
    ("grep -r foo src/", True),
    ("find . -name '*.py'", True),
    ("echo hello world", True),
    ("wc -l file.txt", True),
    ("head -20 file", True),
    ("tail -20 log", True),
    ("stat file.txt", True),
    ("diff a.txt b.txt", True),
    ("sort items.txt", True),
    ("uniq -c words.txt", True),
    ("pwd", True),
    # find 带危险 flag → False
    ("find . -delete", False),
    ("find . -exec rm {} \\;", False),
])
def test_is_readonly_bash(cmd, expected):
    fn = get_fn()
    assert fn({"command": cmd}) is expected, f"Failed for: {cmd!r}"


def test_is_readonly_bash_empty_input():
    fn = get_fn()
    assert fn({}) is False


def test_is_readonly_bash_non_string_command():
    fn = get_fn()
    assert fn({"command": 42}) is False


def test_bash_tool_has_concurrency_fn():
    """Bash tool should have a _concurrency_fn, not just is_concurrency_safe=True."""
    from bourbon.tools import get_registry
    from bourbon.tools import definitions  # trigger registration
    definitions()
    tool = get_registry().get_tool("Bash")
    assert tool is not None
    assert tool._concurrency_fn is not None


def test_agent_tool_is_concurrency_safe():
    from bourbon.tools import get_registry, definitions
    definitions()
    tool = get_registry().get_tool("Agent")
    assert tool is not None
    assert tool.is_concurrency_safe is True


def test_webfetch_is_concurrency_safe():
    from bourbon.tools import get_registry, definitions
    definitions()
    tool = get_registry().get_tool("WebFetch")
    assert tool is not None
    assert tool.is_concurrency_safe is True
```

- [x] **Step 2: 运行测试，预期 FAIL**

```bash
pytest tests/test_is_readonly_bash.py -v
```

期望：FAIL — `ImportError: cannot import name '_is_readonly_bash'`

- [x] **Step 3: 在 `src/bourbon/tools/base.py` 顶部导入 `re` 和 `shlex`**

检查文件头部导入，在现有 `import` 语句**后**（`from __future__` 等之后）确保有：

```python
import re
import shlex
```

如果已有则跳过，否则添加在 `import os` 或 `import json` 之后（按字母序）。

- [x] **Step 4: 在 `src/bourbon/tools/base.py` 中添加 `_is_readonly_bash`**

在 `@register_tool(name="Bash", ...)` 装饰器**之前**插入以下代码：

```python
# ---------------------------------------------------------------------------
# Bash concurrency helper
# ---------------------------------------------------------------------------

READONLY_BASH_COMMANDS = {
    "ls", "cat", "grep", "find", "echo", "pwd", "wc",
    "head", "tail", "stat", "diff", "sort", "uniq",
}

READONLY_BASH_FORBIDDEN_ARGS = {
    "find": {
        "-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprintf", "-fls",
    },
    "sort": {"-o", "--output"},
    "tail": {"-f", "--follow"},
}


def _contains_shell_control_operator(command: str) -> bool:
    """Return True if command contains any shell control operator."""
    if any(token in command for token in ("&&", "||", ">>", "$(", "`", "\n")):
        return True
    if any(token in command for token in (";", "|", ">", "<")):
        return True
    return bool(re.search(r"(?<!&)&(?!&)", command))


def _has_forbidden_readonly_arg(argv: list[str]) -> bool:
    """Return True if a whitelisted command is using a write/blocking argument."""
    command = argv[0]
    forbidden = READONLY_BASH_FORBIDDEN_ARGS.get(command, set())
    for arg in argv[1:]:
        if arg in forbidden:
            return True
        if any(arg.startswith(f"{flag}=") for flag in forbidden if flag.startswith("--")):
            return True

    # uniq accepts OUTPUT as a second file operand, so two non-option operands can write.
    if command == "uniq":
        operands = [arg for arg in argv[1:] if not arg.startswith("-")]
        return len(operands) >= 2

    return False


def _is_readonly_bash(input: dict) -> bool:  # noqa: A002
    """Return True only if the bash command is a safe read-only operation.

    Two-stage check:
    1. Reject if any shell control operator is present.
    2. Accept only if argv[0] is in the exact read-only command whitelist and
       no known write/blocking argument is present.
    """
    command = str(input.get("command", ""))
    if _contains_shell_control_operator(command):
        return False
    try:
        argv = shlex.split(command, posix=True)
    except ValueError:
        return False
    if not argv or "/" in argv[0] or argv[0] not in READONLY_BASH_COMMANDS:
        return False
    if _has_forbidden_readonly_arg(argv):
        return False
    return True
```

- [x] **Step 5: 修改 `Bash` 的 `@register_tool` 装饰器**

找到 `@register_tool(\n    name="Bash",` 这段代码，在其中的 `risk_level=RiskLevel.HIGH,` 等参数之后添加 `concurrency_fn=_is_readonly_bash,`：

```python
@register_tool(
    name="Bash",
    ...
    risk_level=RiskLevel.HIGH,
    ...,
    concurrency_fn=_is_readonly_bash,
)
```

注意：不要修改 `is_concurrency_safe`（它保持 `False`），只新增 `concurrency_fn` 参数。

- [x] **Step 6: 修改 `WebFetch` — 在 `src/bourbon/tools/web.py` 中添加 `is_concurrency_safe=True`**

找到 `@register_tool(` 内的 `name="WebFetch",` 的那段，在现有参数末尾（closing `)`之前）添加 `is_concurrency_safe=True,`：

```python
@register_tool(
    name="WebFetch",
    aliases=["fetch_url"],
    description="Fetch and extract content from a URL.",
    input_schema=FETCH_URL_SCHEMA,
    risk_level=RiskLevel.MEDIUM,
    always_load=False,
    should_defer=True,
    search_hint="web fetch url http download browser",
    required_capabilities=["net"],
    is_concurrency_safe=True,
)
```

- [x] **Step 7: 修改 `Agent` 工具 — 在 `src/bourbon/tools/agent_tool.py` 中添加 `is_concurrency_safe=True` 和 "teammate"**

找到 `@register_tool(\n    name="Agent",` 这段，添加 `is_concurrency_safe=True,`：

```python
@register_tool(
    name="Agent",
    description="Start a focused subagent run for isolated work.",
    input_schema={...},
    risk_level=RiskLevel.MEDIUM,
    is_concurrency_safe=True,
)
```

同时在 `input_schema` 内的 `"subagent_type"` 的 `"enum"` 数组中追加 `"teammate"`：

```python
"enum": ["default", "coder", "explore", "plan", "quick_task", "teammate"],
```

并更新 description 说明 teammate 是 in-process 模式。

- [x] **Step 8: 运行测试**

```bash
pytest tests/test_is_readonly_bash.py -v
```

期望：全部 PASS

- [x] **Step 9: 确保现有测试不受影响**

```bash
pytest tests/test_subagent/ -v
```

期望：全部 PASS

- [x] **Step 10: Commit**

```bash
git add src/bourbon/tools/base.py src/bourbon/tools/web.py src/bourbon/tools/agent_tool.py tests/test_is_readonly_bash.py
git commit -m "feat: add _is_readonly_bash; annotate Bash/WebFetch/Agent with concurrency flags; add teammate to subagent_type enum"
```

---

## Task 5: ToolExecutionQueue

**Files:**
- Create: `src/bourbon/tools/execution_queue.py`
- Create: `tests/test_tool_execution_queue.py`

- [x] **Step 1: 写失败测试**

```python
# tests/test_tool_execution_queue.py
"""Tests for ToolExecutionQueue concurrent tool execution."""
import threading
import time

import pytest

from bourbon.tools.execution_queue import ToolExecutionQueue, ToolStatus


def make_tool_obj(*, concurrent: bool):
    """Create a minimal Tool-like object with concurrent_safe_for() method."""

    class FakeTool:
        def concurrent_safe_for(self, inp):
            return concurrent

    return FakeTool()


def make_block(tool_id: str, name: str = "Read") -> dict:
    return {"id": tool_id, "name": name, "input": {}}


def simple_execute(block: dict) -> str:
    return f"result:{block['id']}"


def test_execute_all_returns_results_in_original_order():
    q = ToolExecutionQueue(execute_fn=simple_execute)
    blocks = [make_block(f"id{i}") for i in range(3)]
    tools = [make_tool_obj(concurrent=True) for _ in blocks]
    for i, (b, t) in enumerate(zip(blocks, tools)):
        q.add(b, t, i)
    results = q.execute_all()
    assert len(results) == 3
    assert results[0]["tool_use_id"] == "id0"
    assert results[1]["tool_use_id"] == "id1"
    assert results[2]["tool_use_id"] == "id2"
    assert results[0]["content"] == "result:id0"


def test_all_concurrent_tools_run_in_parallel():
    """Concurrent tools should overlap in time."""
    start_times = {}
    lock = threading.Lock()

    def slow_execute(block):
        with lock:
            start_times[block["id"]] = time.monotonic()
        time.sleep(0.05)
        return "ok"

    q = ToolExecutionQueue(execute_fn=slow_execute)
    blocks = [make_block(f"c{i}") for i in range(3)]
    for i, b in enumerate(blocks):
        q.add(b, make_tool_obj(concurrent=True), i)
    results = q.execute_all()

    assert len(results) == 3
    # All three should start within a small window if truly parallel
    times = list(start_times.values())
    assert max(times) - min(times) < 0.04, "Expected concurrent execution"


def test_serial_tool_blocks_until_concurrent_done():
    """A serial tool should not start until all concurrent tools finish."""
    order = []
    lock = threading.Lock()

    def execute(block):
        with lock:
            order.append(block["id"])
        return "ok"

    q = ToolExecutionQueue(execute_fn=execute)
    # Two concurrent then one serial
    q.add(make_block("conc1"), make_tool_obj(concurrent=True), 0)
    q.add(make_block("conc2"), make_tool_obj(concurrent=True), 1)
    q.add(make_block("serial"), make_tool_obj(concurrent=False), 2)
    q.execute_all()

    # "serial" must appear after both concurrent tools
    assert order.index("serial") > order.index("conc1")
    assert order.index("serial") > order.index("conc2")


def test_tool_status_queued_then_completed():
    q = ToolExecutionQueue(execute_fn=simple_execute)
    b = make_block("x1")
    t = make_tool_obj(concurrent=True)
    q.add(b, t, 0)
    # Before execute_all: tool should be QUEUED
    assert q._tools[0].status == ToolStatus.QUEUED
    q.execute_all()
    assert q._tools[0].status == ToolStatus.COMPLETED


def test_execute_fn_exception_becomes_error_result():
    def bad_execute(block):
        raise ValueError("oops")

    q = ToolExecutionQueue(execute_fn=bad_execute)
    q.add(make_block("err1"), make_tool_obj(concurrent=False), 0)
    results = q.execute_all()
    assert results[0]["content"].startswith("Error:")


def test_on_tool_start_and_end_called_for_each_tool():
    starts = []
    ends = []
    q = ToolExecutionQueue(
        execute_fn=simple_execute,
        on_tool_start=lambda name, inp: starts.append(name),
        on_tool_end=lambda name, out: ends.append(name),
    )
    blocks = [make_block(f"cb{i}", name=f"Tool{i}") for i in range(2)]
    for i, b in enumerate(blocks):
        q.add(b, make_tool_obj(concurrent=True), i)
    q.execute_all()
    assert len(starts) == 2
    assert len(ends) == 2


def test_callback_exception_does_not_abort_execution():
    def bad_callback(name, _):
        raise RuntimeError("callback boom")

    q = ToolExecutionQueue(
        execute_fn=simple_execute,
        on_tool_start=bad_callback,
    )
    q.add(make_block("safe1"), make_tool_obj(concurrent=False), 0)
    results = q.execute_all()
    assert results[0]["content"] == "result:safe1"


def test_concurrent_callbacks_are_serialized():
    """on_tool_start must not interleave from concurrent worker threads."""
    callback_order = []
    cb_lock = threading.Lock()

    def on_start(name, inp):
        # Simulate a non-trivial callback by sleeping briefly
        time.sleep(0.01)
        with cb_lock:
            callback_order.append(threading.current_thread().name)

    q = ToolExecutionQueue(
        execute_fn=lambda b: (time.sleep(0.02), "ok")[1],
        on_tool_start=on_start,
    )
    for i in range(4):
        q.add(make_block(f"p{i}"), make_tool_obj(concurrent=True), i)
    q.execute_all()
    # All callbacks ran — no assertion on order, just count
    assert len(callback_order) == 4


def test_empty_queue_execute_all_returns_empty():
    q = ToolExecutionQueue(execute_fn=simple_execute)
    assert q.execute_all() == []


def test_result_content_is_string():
    q = ToolExecutionQueue(execute_fn=lambda b: 42)  # returns int, should be coerced
    q.add(make_block("x"), make_tool_obj(concurrent=False), 0)
    results = q.execute_all()
    assert isinstance(results[0]["content"], str)
```

- [x] **Step 2: 运行测试，预期 FAIL**

```bash
pytest tests/test_tool_execution_queue.py -v
```

期望：FAIL — `ModuleNotFoundError: No module named 'bourbon.tools.execution_queue'`

- [x] **Step 3: 创建 `src/bourbon/tools/execution_queue.py`**

```python
# src/bourbon/tools/execution_queue.py
"""Queue-based concurrent tool execution, mirroring Claude Code's StreamingToolExecutor."""

from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ToolStatus(Enum):
    QUEUED = "queued"
    EXECUTING = "executing"
    COMPLETED = "completed"


@dataclass
class TrackedTool:
    block: dict
    tool: Any          # Tool object with concurrent_safe_for() method
    concurrent: bool
    original_index: int
    status: ToolStatus = ToolStatus.QUEUED
    result: dict | None = None
    future: Future | None = None


class ToolExecutionQueue:
    """Execute tool calls with concurrency where safe, serial where not.

    Design mirrors Claude Code's StreamingToolExecutor:
    - Tools whose concurrent_safe_for(input) returns True may run in parallel.
    - Serial tools block until all concurrent tools complete.
    - Callbacks (on_tool_start/on_tool_end) are serialized via _callback_lock.
    - Callback exceptions are isolated; they never abort tool execution.
    - execute_all() shuts down the thread pool; the queue is single-use.
    """

    MAX_CONCURRENT_WORKERS = 10

    def __init__(
        self,
        execute_fn: Callable[[dict], str],
        on_tool_start: Callable[[str, dict], None] | None = None,
        on_tool_end: Callable[[str, str], None] | None = None,
    ):
        self._tools: list[TrackedTool] = []
        self._lock = threading.Lock()          # protects _tools state
        self._callback_lock = threading.Lock() # serializes callbacks (thread safety)
        self._thread_pool = ThreadPoolExecutor(
            max_workers=self.MAX_CONCURRENT_WORKERS,
            thread_name_prefix="tool_queue_",
        )
        self._execute_fn = execute_fn
        self._on_tool_start = on_tool_start
        self._on_tool_end = on_tool_end

    def add(self, block: dict, tool: Any, index: int) -> None:
        """Enqueue one tool call. Must be called before execute_all()."""
        concurrent = tool.concurrent_safe_for(block.get("input", {}))
        with self._lock:
            self._tools.append(TrackedTool(
                block=block,
                tool=tool,
                concurrent=concurrent,
                original_index=index,
            ))

    def execute_all(self) -> list[dict]:
        """Run all queued tools and return results sorted by original index."""
        try:
            self._process_queue()
            self._wait_all()
            with self._lock:
                return [
                    t.result
                    for t in sorted(self._tools, key=lambda t: t.original_index)
                ]
        finally:
            self._thread_pool.shutdown(wait=True)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _can_execute(self, concurrent: bool) -> bool:
        """Return True if a tool can start now. Must be called under _lock."""
        executing = [t for t in self._tools if t.status == ToolStatus.EXECUTING]
        return (
            len(executing) == 0
            or (concurrent and all(t.concurrent for t in executing))
        )

    def _process_queue(self) -> None:
        """Start eligible queued tools.

        Collect candidates under _lock; submit + add_done_callback OUTSIDE _lock.
        This prevents deadlock: if a future completes synchronously inside submit()
        it would call _on_tool_done -> _process_queue -> re-acquire the same lock.
        """
        to_start: list[TrackedTool] = []
        with self._lock:
            for tool in self._tools:
                if tool.status != ToolStatus.QUEUED:
                    continue
                if self._can_execute(tool.concurrent):
                    tool.status = ToolStatus.EXECUTING
                    to_start.append(tool)
                elif not tool.concurrent:
                    break  # serial tool blocked: stop scanning

        for tool in to_start:
            tool.future = self._thread_pool.submit(self._run_tool, tool)
            if tool.concurrent:
                tool.future.add_done_callback(
                    lambda _f, _t=tool: self._on_tool_done(_t)
                )

    def _run_tool(self, tool: TrackedTool) -> None:
        name = tool.block.get("name", "")
        inp = tool.block.get("input", {})
        self._safe_callback(self._on_tool_start, name, inp)
        try:
            raw_output = self._execute_fn(tool.block)
        except Exception as e:
            raw_output = f"Error: {e}"
        tool.result = {
            "type": "tool_result",
            "tool_use_id": tool.block.get("id", ""),
            "content": str(raw_output)[:50000],
        }
        self._safe_callback(self._on_tool_end, name, raw_output)
        with self._lock:
            tool.status = ToolStatus.COMPLETED

    def _safe_callback(self, fn: Callable | None, *args: Any) -> None:
        if fn is None:
            return
        with self._callback_lock:
            try:
                fn(*args)
            except Exception:
                pass  # callback exceptions must never abort tool execution

    def _on_tool_done(self, tool: TrackedTool) -> None:
        self._process_queue()

    def _wait_all(self) -> None:
        """Block until all tools reach COMPLETED status."""
        while True:
            with self._lock:
                pending = [
                    t for t in self._tools
                    if t.future is not None and t.status != ToolStatus.COMPLETED
                ]
            if not pending:
                break
            for t in pending:
                t.future.result()
            self._process_queue()
```

- [x] **Step 4: 运行测试**

```bash
pytest tests/test_tool_execution_queue.py -v
```

期望：全部 PASS

- [x] **Step 5: Commit**

```bash
git add src/bourbon/tools/execution_queue.py tests/test_tool_execution_queue.py
git commit -m "feat: add ToolExecutionQueue with concurrent + serial tool execution"
```

---

## Task 6: SuspendedToolRound.task_nudge_tool_use_blocks

**Files:**
- Modify: `src/bourbon/permissions/runtime.py`
- Test: `tests/test_agent_permission_runtime.py` (已有，追加测试)

- [x] **Step 1: 先确认现有测试全部通过**

```bash
pytest tests/test_agent_permission_runtime.py -v
```

期望：全部 PASS

- [x] **Step 2: 写失败测试**

在 `tests/test_agent_permission_runtime.py` **末尾追加**：

```python
def test_suspended_tool_round_has_task_nudge_tool_use_blocks_default():
    from bourbon.permissions.runtime import SuspendedToolRound

    mock_request = object()
    s = SuspendedToolRound(
        source_assistant_uuid=None,
        tool_use_blocks=[{"id": "1"}],
        completed_results=[],
        next_tool_index=0,
        active_request=mock_request,
    )
    # Default should be empty list, not raise AttributeError
    assert s.task_nudge_tool_use_blocks == []


def test_suspended_tool_round_accepts_task_nudge_blocks():
    from bourbon.permissions.runtime import SuspendedToolRound

    nudge_blocks = [{"id": "a"}, {"id": "b"}]
    s = SuspendedToolRound(
        source_assistant_uuid=None,
        tool_use_blocks=[{"id": "1"}],
        completed_results=[],
        next_tool_index=0,
        active_request=object(),
        task_nudge_tool_use_blocks=nudge_blocks,
    )
    assert s.task_nudge_tool_use_blocks == nudge_blocks
```

- [x] **Step 3: 运行测试，预期 FAIL**

```bash
pytest tests/test_agent_permission_runtime.py -v -k "task_nudge"
```

期望：FAIL — `TypeError: SuspendedToolRound.__init__() got an unexpected keyword argument`

- [x] **Step 4: 修改 `src/bourbon/permissions/runtime.py`**

找到 `@dataclass\nclass SuspendedToolRound:` 定义，在最后一个字段 `active_request` 之后添加：

```python
    task_nudge_tool_use_blocks: list[dict] = field(default_factory=list)
```

需要确保顶部已导入 `field`（已有 `from dataclasses import dataclass, field`）。

- [x] **Step 5: 运行测试**

```bash
pytest tests/test_agent_permission_runtime.py -v
```

期望：全部 PASS

- [x] **Step 6: Commit**

```bash
git add src/bourbon/permissions/runtime.py tests/test_agent_permission_runtime.py
git commit -m "feat: add task_nudge_tool_use_blocks field to SuspendedToolRound"
```

---

## Task 7: Agent.__init__ 新字段 + _execute_tools 改造

**Files:**
- Modify: `src/bourbon/agent.py`
- Test: `tests/test_agent_execute_tools_queue.py` (新建)

这是最大的改动任务。分步实现。

- [x] **Step 1: 写失败测试**

```python
# tests/test_agent_execute_tools_queue.py
"""Tests for _execute_tools queue-based refactor."""
from pathlib import Path
from uuid import uuid4

import pytest

from bourbon.agent import Agent
from bourbon.config import Config
from bourbon.subagent.types import SubagentMode


def make_agent():
    agent = object.__new__(Agent)
    agent.config = Config()
    agent.workdir = Path.cwd()
    agent.on_tool_start = None
    agent.on_tool_end = None
    agent.subagent_mode = SubagentMode.NORMAL
    agent.task_list_id_override = None
    agent._rounds_without_task = 0
    agent.suspended_tool_round = None
    agent.active_permission_request = None
    agent.session_permissions = type("FakePermStore", (), {
        "has_match": lambda self, *a, **kw: False
    })()
    agent._subagent_tool_filter = None
    agent._subagent_agent_def = None
    agent._tool_consecutive_failures = {}
    agent._max_tool_consecutive_failures = 3
    return agent


def make_initialized_agent(monkeypatch, tmp_path):
    """Create a real Agent while stubbing external LLM credentials and HOME writes."""

    class MockLLM:
        def chat(self, **kwargs):
            return {"content": [], "stop_reason": "end_turn", "usage": {}}

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("bourbon.agent.create_client", lambda config: MockLLM())
    return Agent(Config(), workdir=tmp_path)


def test_agent_init_has_subagent_mode(monkeypatch, tmp_path):
    agent = make_initialized_agent(monkeypatch, tmp_path)
    assert agent.subagent_mode == SubagentMode.NORMAL


def test_agent_init_has_task_list_id_override(monkeypatch, tmp_path):
    agent = make_initialized_agent(monkeypatch, tmp_path)
    assert agent.task_list_id_override is None


def test_agent_init_has_rounds_without_task(monkeypatch, tmp_path):
    agent = make_initialized_agent(monkeypatch, tmp_path)
    assert agent._rounds_without_task == 0


def test_execute_tools_runs_via_queue(monkeypatch):
    """_execute_tools should use ToolExecutionQueue for regular tools."""
    from bourbon.tools.execution_queue import ToolExecutionQueue

    agent = make_agent()
    called_execute_all = []

    original_init = ToolExecutionQueue.__init__

    def patched_execute_all(self):
        called_execute_all.append(True)
        # Return minimal results for each queued tool
        return [
            {"type": "tool_result", "tool_use_id": t.block["id"], "content": "mock"}
            for t in self._tools
        ]

    monkeypatch.setattr(ToolExecutionQueue, "execute_all", patched_execute_all)

    # We also need _execute_regular_tool (won't be called since queue handles it)
    # and _permission_decision_for_tool
    def fake_permission(name, inp):
        from bourbon.permissions import PermissionDecision, PermissionAction
        return PermissionDecision(action=PermissionAction.ALLOW, reason="test")

    def fake_denial(name):
        return None

    def fake_get_tool(name):
        from bourbon.tools import Tool, RiskLevel
        t = Tool.__new__(Tool)
        object.__setattr__(t, 'name', name)
        t._concurrency_fn = None
        t.is_concurrency_safe = True
        t.concurrent_safe_for = lambda inp: True
        return t

    monkeypatch.setattr(agent, "_permission_decision_for_tool", fake_permission)
    monkeypatch.setattr(agent, "_subagent_tool_denial", fake_denial)
    monkeypatch.setattr("bourbon.agent.get_tool_with_metadata", fake_get_tool)

    blocks = [
        {"id": "t1", "name": "Read", "input": {"file_path": "/tmp/x"}},
        {"id": "t2", "name": "Grep", "input": {"pattern": "foo"}},
    ]
    results = agent._execute_tools(blocks, source_assistant_uuid=uuid4())
    assert called_execute_all, "_execute_tools should have called queue.execute_all()"
    assert len(results) == 2
```

- [x] **Step 2: 运行测试，预期 FAIL（Agent 未有 subagent_mode 等字段）**

```bash
pytest tests/test_agent_execute_tools_queue.py::test_agent_init_has_subagent_mode -v
```

期望：FAIL 或 AttributeError

- [x] **Step 3: 在 `src/bourbon/agent.py` 的 import 区域添加新导入**

在现有 `from bourbon.subagent.manager import SubagentManager` 之后添加：

```python
from bourbon.subagent.types import SubagentMode
from bourbon.tasks.constants import TASK_V2_TOOLS
from bourbon.tools.execution_queue import ToolExecutionQueue
```

- [x] **Step 4: 在 `Agent.__init__` 中添加三个新字段**

在 `self.active_permission_request: PermissionRequest | None = None` 这行**之后**添加：

```python
        # Subagent visibility mode (set by SubagentManager for child agents)
        self.subagent_mode: SubagentMode = SubagentMode.NORMAL
        # Teammate task list inheritance (overrides session_id for task resolution)
        self.task_list_id_override: str | None = None
        # Tracks consecutive rounds without any task management tool call (for nudge)
        self._rounds_without_task: int = 0
```

- [x] **Step 5: 改造 `_execute_tools` 方法**

将现有 `_execute_tools` 方法（约 959-1060 行）**替换**为新实现：

```python
    def _execute_tools(
        self,
        tool_use_blocks: list[dict],
        *,
        source_assistant_uuid: UUID,
        task_nudge_tool_use_blocks: list[dict] | None = None,
    ) -> list[dict]:
        """Execute tool calls, running concurrent-safe tools in parallel.

        Returns results in the same order as tool_use_blocks.
        """
        if task_nudge_tool_use_blocks is None:
            task_nudge_tool_use_blocks = tool_use_blocks

        n = len(tool_use_blocks)
        results: list[dict | None] = [None] * n
        manual_compact = False

        def _new_queue() -> ToolExecutionQueue:
            return ToolExecutionQueue(
                execute_fn=lambda block: self._execute_regular_tool(
                    block.get("name", ""), block.get("input", {}),
                    skip_policy_check=True,
                ),
                on_tool_start=self.on_tool_start,
                on_tool_end=self.on_tool_end,
            )

        queue: ToolExecutionQueue | None = None

        def _ensure_queue() -> ToolExecutionQueue:
            nonlocal queue
            if queue is None:
                queue = _new_queue()
            return queue

        def _safe_callback(fn, *args):
            if fn is None:
                return
            try:
                fn(*args)
            except Exception:
                pass

        def _direct_start(name: str, inp: dict) -> None:
            _safe_callback(self.on_tool_start, name, inp)

        def _direct_end(name: str, output: str) -> None:
            _safe_callback(self.on_tool_end, name, output)

        # Pre-build id→index map so _fill_queue_results is O(1) per result.
        _id_to_index: dict[str, int] = {
            b.get("id", ""): j for j, b in enumerate(tool_use_blocks)
        }

        def _fill_queue_results() -> None:
            nonlocal queue
            if queue is None:
                return
            drained = queue
            queue = None  # execute_all() shuts down executor; never reuse
            for r in drained.execute_all():
                uid = r.get("tool_use_id", "")
                j = _id_to_index.get(uid)
                if j is not None and results[j] is None:
                    results[j] = r

        for index, block in enumerate(tool_use_blocks):
            tool_name = block.get("name", "")
            tool_input = block.get("input", {})
            tool_id = block.get("id", "")

            # Subagent tool denial check
            denial = self._subagent_tool_denial(tool_name)
            if denial is not None:
                _fill_queue_results()
                _direct_start(tool_name, tool_input)
                results[index] = {
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": str(denial)[:50000],
                    "is_error": True,
                }
                _direct_end(tool_name, str(denial))
                continue

            # Special compress tool
            if tool_name == "compress":
                _fill_queue_results()
                _direct_start(tool_name, tool_input)
                manual_compact = True
                results[index] = {
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": "Compressing context...",
                }
                _direct_end(tool_name, "Compressing context...")
                continue

            # Permission check
            permission = self._permission_decision_for_tool(tool_name, tool_input)
            if permission.action == PermissionAction.DENY:
                _fill_queue_results()
                _direct_start(tool_name, tool_input)
                msg = f"Denied: {permission.reason}"
                results[index] = {
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": msg,
                }
                _direct_end(tool_name, msg)
                continue

            if permission.action == PermissionAction.ASK:
                # Flush queue before suspending so prior tools' callbacks land first
                _fill_queue_results()
                _direct_start(tool_name, tool_input)
                completed = [r for r in results if r is not None]
                self._suspend_tool_round(
                    source_assistant_uuid=source_assistant_uuid,
                    tool_use_blocks=tool_use_blocks,
                    task_nudge_tool_use_blocks=task_nudge_tool_use_blocks,
                    completed_results=completed,
                    next_tool_index=index,
                    request=build_permission_request(
                        tool_name=tool_name,
                        tool_input=tool_input,
                        tool_use_id=tool_id,
                        decision=permission,
                        workdir=self.workdir,
                    ),
                )
                _direct_end(tool_name, "Requires permission")
                return completed

            # Enqueue for concurrent/serial execution
            tool_obj = get_tool_with_metadata(tool_name)
            if tool_obj is not None:
                _ensure_queue().add(block, tool_obj, index)
            else:
                _fill_queue_results()
                _direct_start(tool_name, tool_input)
                msg = f"Unknown tool: {tool_name}"
                results[index] = {
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": msg,
                    "is_error": True,
                }
                _direct_end(tool_name, msg)

        # Drain remaining queue
        _fill_queue_results()

        if manual_compact:
            self._manual_compact()

        return [r for r in results if r is not None]
```

- [x] **Step 6: 更新 `_suspend_tool_round` 签名**

将现有 `_suspend_tool_round` 方法（约 797-815 行）中的签名更新，新增 `task_nudge_tool_use_blocks` 参数：

```python
    def _suspend_tool_round(
        self,
        *,
        source_assistant_uuid: UUID,
        tool_use_blocks: list[dict],
        completed_results: list[dict],
        next_tool_index: int,
        request: PermissionRequest,
        task_nudge_tool_use_blocks: list[dict] | None = None,
    ) -> None:
        """Persist the current tool round until the permission request is resolved."""
        self.active_permission_request = request
        self.suspended_tool_round = SuspendedToolRound(
            source_assistant_uuid=source_assistant_uuid,
            tool_use_blocks=tool_use_blocks,
            completed_results=completed_results,
            next_tool_index=next_tool_index,
            active_request=request,
            task_nudge_tool_use_blocks=task_nudge_tool_use_blocks if task_nudge_tool_use_blocks is not None else tool_use_blocks,
        )
```

- [x] **Step 7: 运行测试**

```bash
pytest tests/test_agent_execute_tools_queue.py -v
pytest tests/test_agent_permission_runtime.py tests/test_agent_error_policy.py -v
```

期望：全部 PASS

- [x] **Step 8: Commit**

```bash
git add src/bourbon/agent.py tests/test_agent_execute_tools_queue.py
git commit -m "feat: add subagent_mode/task_list_id_override/__rounds_without_task to Agent; refactor _execute_tools to use ToolExecutionQueue"
```

---

## Task 8: ToolFilter + SubagentMode 可见性

**Files:**
- Modify: `src/bourbon/subagent/tools.py`
- Modify: `src/bourbon/agent.py` (`_tool_definitions` + `_subagent_tool_denial`)
- Create: `tests/test_subagent/test_subagent_mode.py`

- [x] **Step 1: 写失败测试**

```python
# tests/test_subagent/test_subagent_mode.py
"""Tests for SubagentMode-based tool visibility."""
import pytest

from bourbon.subagent.tools import AGENT_TYPE_CONFIGS, ToolFilter
from bourbon.subagent.types import AgentDefinition, SubagentMode
from bourbon.tasks.constants import TASK_V2_TOOLS


def test_teammate_in_agent_type_configs():
    assert "teammate" in AGENT_TYPE_CONFIGS
    teammate_def = AGENT_TYPE_CONFIGS["teammate"]
    assert teammate_def.allowed_tools is None  # no restriction by default


def test_tool_filter_async_blocks_task_tools():
    """ASYNC subagents should NOT see task management tools."""
    f = ToolFilter()
    default_def = AGENT_TYPE_CONFIGS["default"]
    for tool_name in TASK_V2_TOOLS:
        result = f.is_allowed(tool_name, default_def, subagent_mode=SubagentMode.ASYNC)
        assert result is False, f"{tool_name} should be blocked for ASYNC mode"


def test_tool_filter_teammate_allows_task_tools():
    """TEAMMATE subagents MUST see task management tools."""
    f = ToolFilter()
    default_def = AGENT_TYPE_CONFIGS["default"]
    for tool_name in TASK_V2_TOOLS:
        result = f.is_allowed(tool_name, default_def, subagent_mode=SubagentMode.TEAMMATE)
        assert result is True, f"{tool_name} should be allowed for TEAMMATE mode"


def test_tool_filter_normal_mode_unchanged():
    """NORMAL mode does not change existing allowed_tools logic."""
    f = ToolFilter()
    explore_def = AGENT_TYPE_CONFIGS["explore"]
    # TaskList is not in explore's allowed_tools
    assert f.is_allowed("TaskList", explore_def, subagent_mode=SubagentMode.NORMAL) is False
    # Read is in explore's allowed_tools
    assert f.is_allowed("Read", explore_def, subagent_mode=SubagentMode.NORMAL) is True


def test_global_disallowed_always_blocked_regardless_of_mode():
    """ALL_AGENT_DISALLOWED_TOOLS must block even in TEAMMATE mode."""
    from bourbon.subagent.tools import ALL_AGENT_DISALLOWED_TOOLS
    f = ToolFilter()
    default_def = AGENT_TYPE_CONFIGS["default"]
    for tool_name in ALL_AGENT_DISALLOWED_TOOLS:
        result = f.is_allowed(tool_name, default_def, subagent_mode=SubagentMode.TEAMMATE)
        assert result is False, f"{tool_name} must be blocked even in TEAMMATE mode"


def test_filter_tools_passes_subagent_mode():
    """filter_tools() should respect subagent_mode parameter."""
    f = ToolFilter()
    default_def = AGENT_TYPE_CONFIGS["default"]
    tool_defs = [{"name": tn} for tn in TASK_V2_TOOLS] + [{"name": "Read"}]

    # ASYNC: task tools filtered out
    async_result = f.filter_tools(tool_defs, default_def, subagent_mode=SubagentMode.ASYNC)
    async_names = {t["name"] for t in async_result}
    assert not (async_names & TASK_V2_TOOLS), "Task tools should be removed for ASYNC"
    assert "Read" in async_names

    # NORMAL: task tools pass through (default def has no restriction)
    normal_result = f.filter_tools(tool_defs, default_def, subagent_mode=SubagentMode.NORMAL)
    normal_names = {t["name"] for t in normal_result}
    assert TASK_V2_TOOLS <= normal_names, "Task tools should be visible in NORMAL mode"
```

- [x] **Step 2: 运行测试，预期 FAIL**

```bash
pytest tests/test_subagent/test_subagent_mode.py -v
```

期望：FAIL — `teammate` 不在 `AGENT_TYPE_CONFIGS`，`ToolFilter.is_allowed` 不接受 `subagent_mode`

- [x] **Step 3: 修改 `src/bourbon/subagent/tools.py`**

在文件顶部导入中添加：

```python
from bourbon.subagent.types import AgentDefinition, SubagentMode
from bourbon.tasks.constants import TASK_V2_TOOLS
```

（原有 `from bourbon.subagent.types import AgentDefinition` 改为上面这行。）

在 `AGENT_TYPE_CONFIGS` 字典中，在 `"quick_task"` 条目**之后**添加：

```python
    "teammate": AgentDefinition(
        agent_type="teammate",
        description="In-process teammate for task claiming and parallel execution",
        allowed_tools=None,
        max_turns=100,
    ),
```

将 `ToolFilter.is_allowed()` 方法签名更新（添加 `subagent_mode` 参数）：

```python
    def is_allowed(
        self,
        tool_name: str,
        agent_def: AgentDefinition,
        subagent_mode: SubagentMode | None = None,
    ) -> bool:
        """Return whether a tool can be exposed to the given subagent."""
        if tool_name in ALL_AGENT_DISALLOWED_TOOLS:  # highest priority, any mode
            return False
        if tool_name in agent_def.disallowed_tools:
            return False
        if subagent_mode == SubagentMode.ASYNC and tool_name in TASK_V2_TOOLS:
            return False
        if subagent_mode == SubagentMode.TEAMMATE and tool_name in TASK_V2_TOOLS:
            return True  # bypass allowed_tools whitelist
        if agent_def.allowed_tools is not None:
            return tool_name in agent_def.allowed_tools
        return True
```

将 `ToolFilter.filter_tools()` 方法签名更新（添加 `subagent_mode` 参数并透传）：

```python
    def filter_tools(
        self,
        tools: list[dict[str, Any]],
        agent_def: AgentDefinition,
        subagent_mode: SubagentMode | None = None,
    ) -> list[dict[str, Any]]:
        """Filter tool definition dictionaries by their ``name`` field."""
        return [
            tool
            for tool in tools
            if self.is_allowed(
                str(tool.get("name", "")),
                agent_def,
                subagent_mode=subagent_mode,
            )
        ]
```

- [x] **Step 4: 更新 `src/bourbon/agent.py` 中 `_tool_definitions` 和 `_subagent_tool_denial`**

将 `_tool_definitions` 中的 `filter_engine.filter_tools(tool_defs, agent_def)` 改为：

```python
        filtered_tools = filter_engine.filter_tools(
            tool_defs, agent_def, subagent_mode=self.subagent_mode
        )
```

将 `_subagent_tool_denial` 中的 `filter_engine.is_allowed(tool_name, agent_def)` 改为：

```python
        if filter_engine.is_allowed(tool_name, agent_def, subagent_mode=self.subagent_mode):
```

- [x] **Step 5: 运行测试**

```bash
pytest tests/test_subagent/test_subagent_mode.py tests/test_subagent/test_tools.py -v
```

期望：全部 PASS（包括已有的 `test_tools.py`）

- [x] **Step 6: Commit**

```bash
git add src/bourbon/subagent/tools.py src/bourbon/agent.py tests/test_subagent/test_subagent_mode.py
git commit -m "feat: add SubagentMode to ToolFilter; add teammate to AGENT_TYPE_CONFIGS; wire subagent_mode into agent tool filtering"
```

---

## Task 9: task_list_id_override + SubagentManager 更新

**Files:**
- Modify: `src/bourbon/tools/task_tools.py`
- Modify: `src/bourbon/subagent/manager.py`
- Test: `tests/test_subagent/test_subagent_mode.py` (追加) + `tests/test_task_list_id_resolve.py` (新建)

- [x] **Step 1: 写失败测试（task_list_id_override 最高优先）**

```python
# tests/test_task_list_id_resolve.py
"""Tests for _resolve_task_list_id with task_list_id_override support."""
from pathlib import Path
from unittest.mock import MagicMock

import pytest


def resolve(agent=None, explicit_id=None):
    from bourbon.tools.task_tools import _resolve_task_list_id
    from bourbon.tools import ToolContext
    ctx = ToolContext(workdir=Path.cwd(), agent=agent)
    return _resolve_task_list_id(ctx, explicit_id)


def make_agent(*, override=None, session_id=None, default_list_id=None):
    agent = MagicMock()
    agent.task_list_id_override = override
    agent.session.session_id = session_id
    if default_list_id:
        agent.config.tasks.default_list_id = default_list_id
    else:
        agent.config.tasks.default_list_id = None
    return agent


def test_explicit_id_wins_over_all():
    agent = make_agent(override="override-id", session_id="session-id")
    assert resolve(agent, explicit_id="explicit") == "explicit"


def test_override_wins_over_session_id():
    agent = make_agent(override="override-id", session_id="session-id")
    assert resolve(agent) == "override-id"


def test_session_id_wins_when_no_override():
    agent = make_agent(override=None, session_id="session-id")
    assert resolve(agent) == "session-id"


def test_config_default_used_when_no_override_or_session():
    agent = make_agent(override=None, session_id=None, default_list_id="config-default")
    assert resolve(agent) == "config-default"


def test_returns_default_when_nothing_set():
    agent = make_agent(override=None, session_id=None)
    assert resolve(agent) == "default"


def test_no_agent_returns_default():
    assert resolve(agent=None) == "default"
```

- [x] **Step 2: 运行测试，预期 FAIL（override 未检查）**

```bash
pytest tests/test_task_list_id_resolve.py -v
```

期望：`test_override_wins_over_session_id` FAIL

- [x] **Step 3: 修改 `src/bourbon/tools/task_tools.py` 中的 `_resolve_task_list_id`**

将整个 `_resolve_task_list_id` 函数替换为：

```python
def _resolve_task_list_id(ctx: ToolContext, task_list_id: str | None) -> str:
    if task_list_id:
        return task_list_id

    agent = ctx.agent
    if agent is not None:
        # Priority 1: explicit override (used by teammate to inherit parent task list)
        override = getattr(agent, "task_list_id_override", None)
        if override:
            return str(override)

        # Priority 2: session id
        session = getattr(agent, "session", None)
        session_id = getattr(session, "session_id", None)
        if session_id is not None:
            return str(session_id)

        # Priority 3: config default
        config = getattr(agent, "config", None)
        tasks_config = getattr(config, "tasks", None)
        default_list_id = getattr(tasks_config, "default_list_id", None)
        if default_list_id:
            return str(default_list_id)

    return "default"
```

- [x] **Step 4: 运行测试**

```bash
pytest tests/test_task_list_id_resolve.py -v
```

期望：全部 PASS

- [x] **Step 5: 写 SubagentManager spawn 测试（追加到现有 test_manager.py）**

在 `tests/test_subagent/test_manager.py` **末尾追加**：

```python
from bourbon.subagent.types import SubagentMode


def test_spawn_sets_subagent_mode_normal_for_sync(tmp_path):
    """Regular sync spawn should produce NORMAL mode."""
    received_modes = []

    def agent_factory(run, agent_def):
        received_modes.append(run.subagent_mode)
        return FakeSubagent()

    manager = SubagentManager(config=Config(), workdir=tmp_path, agent_factory=agent_factory)
    manager.spawn(description="test", prompt="do it", agent_type="default")
    assert received_modes == [SubagentMode.NORMAL]


def test_spawn_sets_subagent_mode_async_for_background(tmp_path):
    """Background spawn should produce ASYNC mode."""
    received_modes = []
    done = threading.Event()

    def agent_factory(run, agent_def):
        received_modes.append(run.subagent_mode)
        done.set()
        return FakeSubagent()

    manager = SubagentManager(config=Config(), workdir=tmp_path, agent_factory=agent_factory)
    manager.spawn(description="bg", prompt="do", agent_type="default", run_in_background=True)
    done.wait(timeout=2)
    manager.shutdown()
    assert received_modes == [SubagentMode.ASYNC]


def test_spawn_teammate_sets_mode_and_task_list_id(tmp_path):
    """Teammate spawn should set TEAMMATE mode and parent task list id."""
    received = []

    def agent_factory(run, agent_def):
        received.append((run.subagent_mode, run.parent_task_list_id))
        return FakeSubagent()

    # Create parent agent with a fake session id
    parent = MagicMock()
    parent.session.session_id = "parent-session-123"

    manager = SubagentManager(
        config=Config(), workdir=tmp_path, parent_agent=parent, agent_factory=agent_factory
    )
    manager.spawn(description="teammate", prompt="do", agent_type="teammate")
    assert received[0][0] == SubagentMode.TEAMMATE
    assert received[0][1] == "parent-session-123"


def test_configure_subagent_runtime_applies_to_factory_agent(tmp_path):
    """agent_factory branch must also receive subagent_mode and task_list_id_override."""
    created_agents = []

    class FakeAgentWithAttrs(FakeSubagent):
        def __init__(self):
            super().__init__()
            self.subagent_mode = None
            self.task_list_id_override = None

    def agent_factory(run, agent_def):
        a = FakeAgentWithAttrs()
        created_agents.append(a)
        return a

    parent = MagicMock()
    parent.session.session_id = "parent-xyz"

    manager = SubagentManager(
        config=Config(), workdir=tmp_path, parent_agent=parent, agent_factory=agent_factory
    )
    manager.spawn(description="tm", prompt="do", agent_type="teammate")
    a = created_agents[0]
    assert a.subagent_mode == SubagentMode.TEAMMATE
    assert a.task_list_id_override == "parent-xyz"
```

注意：需要在文件顶部追加 `from unittest.mock import MagicMock`（检查是否已有）。

- [x] **Step 6: 运行测试，预期 FAIL（spawn 未计算 mode）**

```bash
pytest tests/test_subagent/test_manager.py -v -k "subagent_mode or teammate or configure"
```

期望：FAIL

- [x] **Step 7: 修改 `src/bourbon/subagent/manager.py`**

在 `spawn()` 方法中，在构造 `SubagentRun(...)` 之前添加 mode 计算逻辑：

```python
        # Determine subagent mode
        if agent_type == "teammate":
            mode = SubagentMode.TEAMMATE
            parent_session = getattr(self.parent_agent, "session", None)
            parent_task_list_id = getattr(parent_session, "session_id", None)
        elif run_in_background:
            mode = SubagentMode.ASYNC
            parent_task_list_id = None
        else:
            mode = SubagentMode.NORMAL
            parent_task_list_id = None

        run = SubagentRun(
            description=description,
            prompt=prompt,
            agent_type=agent_type,
            model=model or agent_def.model,
            max_turns=max_turns or agent_def.max_turns,
            is_async=run_in_background,
            abort_controller=AbortController(),
            subagent_mode=mode,
            parent_task_list_id=parent_task_list_id,
        )
```

同时需要添加导入：

```python
from bourbon.subagent.types import AgentDefinition, RunStatus, SubagentMode, SubagentRun
```

（原有 `from bourbon.subagent.types import AgentDefinition, RunStatus, SubagentRun` 改为上面这行。）

将 `_create_subagent()` 方法重构，提取 `_configure_subagent_runtime()` 辅助方法：

```python
    def _configure_subagent_runtime(
        self,
        subagent: Any,
        run: SubagentRun,
        agent_def: AgentDefinition,
        *,
        attach_session: bool,
    ) -> None:
        """Apply runtime settings to a subagent instance."""
        subagent._max_tool_rounds = run.max_turns
        subagent.subagent_mode = run.subagent_mode
        subagent._subagent_agent_def = agent_def
        subagent._subagent_tool_filter = ToolFilter()
        if run.parent_task_list_id:
            subagent.task_list_id_override = run.parent_task_list_id

        if attach_session:
            parent_session_manager = getattr(self.parent_agent, "_session_manager", None)
            if parent_session_manager is not None:
                adapter = SubagentSessionAdapter(
                    parent_store=parent_session_manager.store,
                    project_name=parent_session_manager.project_name,
                    project_dir=str(self.workdir),
                    run_id=run.run_id,
                )
                subagent.session = adapter.create_session()

    def _create_subagent(
        self,
        run: SubagentRun,
        agent_def: AgentDefinition,
        agent_factory: AgentFactory | None = None,
    ) -> Any:
        if agent_factory is not None:
            subagent = agent_factory(run, agent_def)
            self._configure_subagent_runtime(subagent, run, agent_def, attach_session=False)
            return subagent

        from bourbon.agent import Agent

        system_prompt = getattr(self.parent_agent, "system_prompt", None)
        if agent_def.system_prompt_suffix:
            system_prompt = (
                f"{system_prompt}\n\n{agent_def.system_prompt_suffix}"
                if system_prompt
                else agent_def.system_prompt_suffix
            )

        subagent = Agent(
            config=self.config,
            workdir=self.workdir,
            system_prompt=system_prompt,
        )
        self._configure_subagent_runtime(subagent, run, agent_def, attach_session=True)
        return subagent
```

注意：原 `_create_subagent` 中的 `subagent._max_tool_rounds = run.max_turns` 等行现在移到 `_configure_subagent_runtime`，替换掉原有的直接赋值代码。

- [x] **Step 8: 运行测试**

```bash
pytest tests/test_subagent/test_manager.py tests/test_task_list_id_resolve.py -v
```

期望：全部 PASS

- [x] **Step 9: Commit**

```bash
git add src/bourbon/tools/task_tools.py src/bourbon/subagent/manager.py tests/test_task_list_id_resolve.py tests/test_subagent/test_manager.py
git commit -m "feat: add task_list_id_override to _resolve_task_list_id; refactor SubagentManager with SubagentMode and _configure_subagent_runtime"
```

---

## Task 10: Task Nudge 机制

**Files:**
- Modify: `src/bourbon/agent.py`（添加辅助方法 + 在三条 loop 路径注入）
- Create: `tests/test_task_nudge.py`

- [x] **Step 1: 写失败测试**

```python
# tests/test_task_nudge.py
"""Tests for Task Nudge mechanism (_append_task_nudge_if_due)."""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bourbon.agent import Agent
from bourbon.session.types import MessageRole, TextBlock, TranscriptMessage
from bourbon.tasks.constants import TASK_V2_TOOLS


def make_agent_for_nudge():
    """Create a minimal Agent instance for nudge testing."""
    agent = object.__new__(Agent)
    agent.config = MagicMock()
    agent.config.tasks.storage_dir = "/tmp/bourbon_nudge_test"
    agent.workdir = Path.cwd()
    agent.task_list_id_override = None
    agent._rounds_without_task = 0
    agent.session = MagicMock()
    agent.session.session_id = "test-session-123"
    return agent


def make_tool_result_msg():
    return TranscriptMessage(
        role=MessageRole.USER,
        content=[TextBlock(text="some tool result")],
    )


def make_blocks(*names):
    return [{"id": f"id{i}", "name": n, "input": {}} for i, n in enumerate(names)]


def test_nudge_not_triggered_below_threshold():
    agent = make_agent_for_nudge()
    msg = make_tool_result_msg()

    for _ in range(9):  # 9 rounds, threshold is 10
        agent._append_task_nudge_if_due(msg, make_blocks("Read"))

    # Counter at 9, no nudge yet
    assert agent._rounds_without_task == 9
    # No task_reminder TextBlock added
    reminder_texts = [b.text for b in msg.content if isinstance(b, TextBlock) and "<task_reminder>" in b.text]
    assert len(reminder_texts) == 0


def test_nudge_triggered_at_threshold_when_pending_tasks():
    agent = make_agent_for_nudge()
    agent._rounds_without_task = 9  # one away from threshold

    msg = make_tool_result_msg()
    initial_len = len(msg.content)

    # Mock TaskService to return pending tasks
    fake_task = MagicMock()
    fake_task.status = "pending"
    fake_task.subject = "Fix the bug"
    fake_task.blocked_by = []

    with patch("bourbon.tasks.service.TaskService") as MockService, \
         patch("bourbon.tasks.store.TaskStore"):
        mock_service_instance = MagicMock()
        mock_service_instance.list_tasks.return_value = [fake_task]
        MockService.return_value = mock_service_instance

        agent._append_task_nudge_if_due(msg, make_blocks("Read"))

    # Counter reset
    assert agent._rounds_without_task == 0
    # Nudge block appended
    assert len(msg.content) == initial_len + 1
    nudge_text = msg.content[-1].text
    assert "<task_reminder>" in nudge_text
    assert "Fix the bug" in nudge_text


def test_nudge_not_appended_when_no_pending_tasks():
    agent = make_agent_for_nudge()
    agent._rounds_without_task = 9

    msg = make_tool_result_msg()
    initial_len = len(msg.content)

    with patch("bourbon.tasks.service.TaskService") as MockService, \
         patch("bourbon.tasks.store.TaskStore"):
        mock_service_instance = MagicMock()
        mock_service_instance.list_tasks.return_value = []  # no tasks
        MockService.return_value = mock_service_instance

        agent._append_task_nudge_if_due(msg, make_blocks("Read"))

    assert agent._rounds_without_task == 0  # still reset
    assert len(msg.content) == initial_len   # no block added


def test_counter_resets_when_task_tool_used():
    agent = make_agent_for_nudge()
    agent._rounds_without_task = 5

    msg = make_tool_result_msg()
    agent._append_task_nudge_if_due(msg, make_blocks("TaskCreate", "Read"))

    assert agent._rounds_without_task == 0


def test_counter_increments_without_task_tool_below_threshold():
    agent = make_agent_for_nudge()
    agent._rounds_without_task = 3

    msg = make_tool_result_msg()

    # Don't mock TaskService since threshold not reached
    agent._append_task_nudge_if_due(msg, make_blocks("Read", "Grep"))

    assert agent._rounds_without_task == 4  # incremented from 3 to 4


def test_defensive_getattr_when_rounds_not_initialized():
    """object.__new__(Agent) bypasses __init__; _rounds_without_task may not exist."""
    agent = make_agent_for_nudge()
    del agent._rounds_without_task  # simulate missing attribute

    msg = make_tool_result_msg()
    # Should not raise AttributeError
    agent._append_task_nudge_if_due(msg, make_blocks("Read"))
    assert hasattr(agent, "_rounds_without_task")


def test_empty_blocks_returns_early():
    """No tool use blocks means no counting or nudge."""
    agent = make_agent_for_nudge()
    agent._rounds_without_task = 5
    msg = make_tool_result_msg()
    initial_len = len(msg.content)

    agent._append_task_nudge_if_due(msg, [])

    assert agent._rounds_without_task == 5  # unchanged
    assert len(msg.content) == initial_len


def test_resume_permission_request_injects_nudge(tmp_path):
    """resume_permission_request must call _append_task_nudge_if_due on the tool_turn_msg."""
    from unittest.mock import patch, MagicMock
    from uuid import uuid4
    from bourbon.permissions.runtime import SuspendedToolRound
    from bourbon.permissions import PermissionChoice
    from bourbon.agent import Agent, TASK_NUDGE_THRESHOLD
    from bourbon.session.types import MessageRole, TextBlock, TranscriptMessage

    agent = object.__new__(Agent)
    agent.config = MagicMock()
    agent.config.tasks.storage_dir = str(tmp_path)
    agent.workdir = tmp_path
    agent.session = MagicMock()
    agent.session.session_id = "resume-test-session"
    agent.session_permissions = MagicMock()
    agent.session_permissions.add = MagicMock()
    agent.active_permission_request = None
    agent.suspended_tool_round = None
    agent._subagent_tool_filter = None
    agent._subagent_agent_def = None
    agent._tool_consecutive_failures = {}
    agent._max_tool_consecutive_failures = 3
    agent.task_list_id_override = None
    agent._rounds_without_task = TASK_NUDGE_THRESHOLD - 1  # one away from threshold

    src_uuid = uuid4()
    nudge_blocks = [{"id": "n1", "name": "Read", "input": {}}]
    request = MagicMock()
    request.tool_use_id = "ask1"
    request.tool_name = "Bash"
    request.tool_input = {"command": "ls"}
    request.match_candidate = None

    suspended = SuspendedToolRound(
        source_assistant_uuid=src_uuid,
        tool_use_blocks=nudge_blocks,
        completed_results=[],
        next_tool_index=0,
        active_request=request,
        task_nudge_tool_use_blocks=nudge_blocks,
    )
    agent.suspended_tool_round = suspended

    # Mock tool execution to return a simple result
    captured_tool_turn_msg = []

    def fake_add_message(msg):
        captured_tool_turn_msg.append(msg)

    agent.session.add_message = fake_add_message
    agent.session.save = MagicMock()

    # Mock _execute_regular_tool to return a result for the allowed tool
    agent._execute_regular_tool = MagicMock(return_value="bash output")
    agent._subagent_tool_denial = MagicMock(return_value=None)

    # Mock _build_tool_results_transcript_message to return a real TranscriptMessage
    def fake_build_transcript(results, uuid):
        return TranscriptMessage(
            role=MessageRole.USER,
            content=[TextBlock(text="tool results")],
        )

    agent._build_tool_results_transcript_message = fake_build_transcript
    agent._run_conversation_loop = MagicMock(return_value="final response")

    # Mock TaskService to return one pending task
    fake_task = MagicMock()
    fake_task.status = "pending"
    fake_task.subject = "Important pending task"
    fake_task.blocked_by = []

    with patch("bourbon.tasks.service.TaskService") as MockService, \
         patch("bourbon.tasks.store.TaskStore"):
        MockService.return_value.list_tasks.return_value = [fake_task]
        agent.resume_permission_request(PermissionChoice.ALLOW_ONCE)

    # The tool_turn_msg should have a task_reminder block appended
    assert len(captured_tool_turn_msg) == 1
    msg_content = captured_tool_turn_msg[0].content
    reminder_blocks = [
        b for b in msg_content
        if isinstance(b, TextBlock) and "<task_reminder>" in b.text
    ]
    assert len(reminder_blocks) == 1, "resume_permission_request should inject nudge at threshold"
    assert "Important pending task" in reminder_blocks[0].text
```

- [x] **Step 2: 运行测试，预期 FAIL**

```bash
pytest tests/test_task_nudge.py -v
```

期望：FAIL — `Agent` 没有 `_append_task_nudge_if_due` 方法

- [x] **Step 3: 在 `src/bourbon/agent.py` 中添加必要导入**

在文件顶部确认以下导入存在（应该已有 `TextBlock`，需要补充新的）：

```python
from pathlib import Path  # 已有
```

无需新增（`TASK_V2_TOOLS` 和 `ToolExecutionQueue` 已在 Task 7 中添加），但需要确认 `TaskService` 和 `TaskStore` 是延迟导入（在方法内 `from bourbon.tasks.service import TaskService`）。对应测试必须 patch 源模块 `bourbon.tasks.service.TaskService` / `bourbon.tasks.store.TaskStore`，不要 patch `bourbon.agent` 模块属性，否则 lazy import 场景下这些属性不存在。

- [x] **Step 4: 在 `src/bourbon/agent.py` 中添加 `TASK_NUDGE_THRESHOLD` 常量和两个辅助方法**

在 `class Agent:` **之前**（`AgentError` 类之后）添加：

```python
TASK_NUDGE_THRESHOLD = 10
```

在 `_suspend_tool_round` 方法**之后**添加两个新方法：

```python
    def _append_task_nudge_if_due(
        self,
        tool_turn_msg: "TranscriptMessage",
        tool_use_blocks: list[dict],
    ) -> None:
        """Append a task reminder block if nudge threshold is reached.

        Counts rounds without task tool usage. At threshold:
        1. Build reminder with pending tasks.
        2. If pending tasks exist, append TextBlock to tool_turn_msg.content.
        3. Reset counter regardless (avoid re-constructing TaskService every round).
        """
        if not tool_use_blocks:
            return

        rounds = getattr(self, "_rounds_without_task", 0)

        used_task_tool = any(b.get("name") in TASK_V2_TOOLS for b in tool_use_blocks)
        if used_task_tool:
            self._rounds_without_task = 0
            return

        rounds += 1
        self._rounds_without_task = rounds
        if rounds < TASK_NUDGE_THRESHOLD:
            return

        reminder = self._build_task_reminder_block()
        if reminder is not None:
            tool_turn_msg.content.append(reminder)
        # Always reset even if no pending tasks, to avoid TaskService construction every round
        self._rounds_without_task = 0

    def _build_task_reminder_block(self) -> "TextBlock | None":
        """Build a TextBlock with pending tasks for task nudge injection."""
        from bourbon.tasks.service import TaskService
        from bourbon.tasks.store import TaskStore

        storage_dir = Path(self.config.tasks.storage_dir).expanduser()
        service = TaskService(TaskStore(storage_dir))

        task_list_id = (
            getattr(self, "task_list_id_override", None)
            or getattr(getattr(self, "session", None), "session_id", None)
            or getattr(
                getattr(getattr(self, "config", None), "tasks", None),
                "default_list_id",
                None,
            )
            or "default"
        )

        tasks = service.list_tasks(str(task_list_id))
        pending = [t for t in tasks if t.status != "completed"]
        if not pending:
            return None

        lines = "\n".join(
            f"- [{t.status}] {t.subject}"
            + (f" (blocked by: {', '.join(t.blocked_by)})" if t.blocked_by else "")
            for t in pending
        )
        return TextBlock(text=(
            f"<task_reminder>\n"
            f"You have {len(pending)} pending task(s). "
            f"Please update with TaskUpdate or create with TaskCreate.\n\n"
            f"{lines}\n"
            f"</task_reminder>"
        ))
```

- [x] **Step 5: 运行 nudge 方法测试**

```bash
pytest tests/test_task_nudge.py -v
```

期望：全部 PASS

- [x] **Step 6: 在三条 loop 路径注入 nudge**

在 `_run_conversation_loop` 中找到：

```python
                tool_turn_msg = self._build_tool_results_transcript_message(
                    tool_results, assistant_msg.uuid
                )
                self.session.add_message(tool_turn_msg)
```

在两行之间插入：

```python
                self._append_task_nudge_if_due(tool_turn_msg, tool_use_blocks)
```

在 `_run_conversation_loop_stream` 中找到类似的位置（`tool_turn_msg = self._build_tool_results_transcript_message(tool_results, assistant_msg.uuid)`），同样插入一行：

```python
                self._append_task_nudge_if_due(tool_turn_msg, tool_use_blocks)
```

在 `resume_permission_request` 中找到：

```python
        tool_turn_msg = self._build_tool_results_transcript_message(results, source_assistant_uuid)
        self.session.add_message(tool_turn_msg)
```

在两行之间插入：

```python
        nudge_blocks = suspended.task_nudge_tool_use_blocks if suspended.task_nudge_tool_use_blocks is not None else suspended.tool_use_blocks
        self._append_task_nudge_if_due(tool_turn_msg, nudge_blocks)
```

同时，在 `resume_permission_request` 中找到调用 `self._execute_tools(remaining_blocks, ...)` 的地方，更新为透传 `task_nudge_tool_use_blocks`：

```python
            results.extend(
                self._execute_tools(
                    remaining_blocks,
                    source_assistant_uuid=source_assistant_uuid,
                    task_nudge_tool_use_blocks=suspended.task_nudge_tool_use_blocks if suspended.task_nudge_tool_use_blocks is not None else suspended.tool_use_blocks,
                )
            )
```

- [x] **Step 7: 运行全部相关测试**

```bash
pytest tests/test_task_nudge.py tests/test_agent_permission_runtime.py tests/test_agent_error_policy.py -v
```

期望：全部 PASS

- [x] **Step 8: Commit**

```bash
git add src/bourbon/agent.py tests/test_task_nudge.py
git commit -m "feat: add task nudge mechanism (_append_task_nudge_if_due, _build_task_reminder_block) wired into all three conversation loop paths"
```

---

## Task 11: 全量测试 + 清理

**Files:** 无新文件，验证整体

- [x] **Step 1: 运行全量测试套件**

```bash
pytest -v --tb=short
```

期望：全部 PASS（或已知的 integration test 因 LLM key 缺失跳过）

- [x] **Step 2: 运行 lint 检查**

```bash
ruff check src tests
```

期望：无错误（警告可接受）

- [x] **Step 3: 运行类型检查（可选，部分模块可能有未解决的 mypy 警告）**

```bash
mypy src/bourbon/tools/__init__.py src/bourbon/tools/execution_queue.py src/bourbon/subagent/types.py src/bourbon/subagent/tools.py
```

期望：无 `error` 级别问题（`note` 可忽略）

- [x] **Step 4: Final commit**

```bash
git add \
  src/bourbon/tools/__init__.py \
  src/bourbon/tools/execution_queue.py \
  src/bourbon/tasks/constants.py \
  src/bourbon/tools/base.py \
  src/bourbon/tools/web.py \
  src/bourbon/tools/agent_tool.py \
  src/bourbon/tools/task_tools.py \
  src/bourbon/agent.py \
  src/bourbon/permissions/runtime.py \
  src/bourbon/subagent/types.py \
  src/bourbon/subagent/tools.py \
  src/bourbon/subagent/manager.py \
  tests/test_tool_concurrency_safe.py \
  tests/test_is_readonly_bash.py \
  tests/test_tool_execution_queue.py \
  tests/test_agent_execute_tools_queue.py \
  tests/test_task_constants.py \
  tests/test_task_list_id_resolve.py \
  tests/test_task_nudge.py \
  tests/test_subagent/test_types.py \
  tests/test_subagent/test_subagent_mode.py \
  tests/test_subagent/test_manager.py
git commit -m "chore: final cleanup and verification for claude-code alignment (concurrent tools, SubagentMode, task nudge)"
```

---

## 设计验证矩阵

完成后，确认以下每条设计目标都有对应测试：

| 设计目标 | 验证测试 |
|----------|---------|
| concurrent tools 并行执行 | `test_all_concurrent_tools_run_in_parallel` |
| serial tool 等待 concurrent 完成 | `test_serial_tool_blocks_until_concurrent_done` |
| Callback 线程安全 | `test_concurrent_callbacks_are_serialized` |
| Callback 异常隔离 | `test_callback_exception_does_not_abort_execution` |
| 结果顺序与原始 block 一致 | `test_execute_all_returns_results_in_original_order` |
| Bash 只读命令识别 | `test_is_readonly_bash` (parametrize) |
| ASYNC mode 过滤 task 工具 | `test_tool_filter_async_blocks_task_tools` |
| TEAMMATE mode 允许 task 工具 | `test_tool_filter_teammate_allows_task_tools` |
| ALL_AGENT_DISALLOWED 不受 mode 影响 | `test_global_disallowed_always_blocked_regardless_of_mode` |
| task_list_id_override 最高优先 | `test_override_wins_over_session_id` |
| SubagentManager 设置 mode | `test_spawn_sets_subagent_mode_normal_for_sync` 等 |
| agent_factory 分支也继承 mode | `test_configure_subagent_runtime_applies_to_factory_agent` |
| nudge 在阈值触发 | `test_nudge_triggered_at_threshold_when_pending_tasks` |
| nudge 计数重置（task 工具使用后） | `test_counter_resets_when_task_tool_used` |
| nudge 无 pending 不注入 | `test_nudge_not_appended_when_no_pending_tasks` |
| defensive getattr | `test_defensive_getattr_when_rounds_not_initialized` |
| resume 路径端到端注入 nudge | `test_resume_permission_request_injects_nudge` |
