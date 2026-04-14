# Bourbon ↔ Claude Code 对齐设计：并发工具执行 + 任务管理

**日期**：2026-04-14（v7，已整合第六轮 code review 修正）
**范围**：三个特性的对齐实现
1. 并发工具执行（`ToolExecutionQueue` + `concurrent_safe_for`）
2. Subagent 工具可见性（`SubagentMode` 区分 teammate / async）
3. Task Nudge 机制（10 轮阈值注入 `task_reminder`）

---

## 背景

Claude Code 采用 **LLM-centric** 设计哲学：LLM 是唯一的 orchestrator，系统模块只提供原子性辅助。bourbon 作为对齐 Claude Code 设计的学习项目，本次需要补齐三个关键机制。

---

## 特性一：并发工具执行

### 1.1 `Tool` dataclass 扩展（向后兼容）

`is_concurrency_safe: bool = False` 保持不变（测试断言 bool 值）。新增私有 `_concurrency_fn` 字段和公开 `concurrent_safe_for()` 方法：

```python
@dataclass
class Tool:
    # 所有现有字段不变
    is_concurrency_safe: bool = False
    _concurrency_fn: Callable[[dict], bool] | None = field(default=None, repr=False)

    def concurrent_safe_for(self, tool_input: dict) -> bool:
        """_concurrency_fn 优先，否则回退 bool 字段。"""
        if self._concurrency_fn is not None:
            try:
                return bool(self._concurrency_fn(tool_input))
            except Exception:
                return False
        return self.is_concurrency_safe
```

`register_tool` 新增 `concurrency_fn` 参数，不改 `is_concurrency_safe: bool`。必须在内部构造 `Tool` 时显式传递，否则 bash 等工具的动态判断逻辑将静默失效：

```python
def register_tool(
    name: str,
    description: str,
    input_schema: dict,
    risk_level: RiskLevel = RiskLevel.LOW,
    is_concurrency_safe: bool = False,
    concurrency_fn: Callable[[dict], bool] | None = None,  # 新增
    ...
) -> Callable:
    def decorator(handler):
        tool = Tool(
            name=name,
            description=description,
            input_schema=input_schema,
            handler=handler,
            risk_level=risk_level,
            is_concurrency_safe=is_concurrency_safe,
            _concurrency_fn=concurrency_fn,  # 必须显式传递
            ...
        )
        _registry.register(tool)
        return handler
    return decorator
```

**各工具标注**：

| 工具（精确注册名） | is_concurrency_safe | concurrency_fn |
|-------------------|---------------------|----------------|
| `Agent` | `True` | 无 |
| `Read` | `True` | 无 |
| `Glob` | `True` | 无 |
| `Grep` | `True` | 无 |
| `AstGrep` | `True` | 无 |
| `WebFetch` | `True` | 无 |
| `ToolSearch` | `False` | 无（会更新 discovered tool set，不是幂等只读操作） |
| `Bash` | `False` | `_is_readonly_bash`（两阶段） |
| 其余 | `False` | 无 |

**`_is_readonly_bash(input: dict) -> bool`** — 两阶段，均通过才返回 `True`：

1. **Shell 控制符检测（优先）**：命令字符串含以下任一字符/序列时立即返回 `False`（`shell=True` 下均可组合副作用）：
   `;`、`|`、`&&`、`||`、`>`、`>>`、`<`、`$()`、反引号（`` ` ``）、换行（`\n`）、单独 `&`（后台执行）。

2. **解析后精确命令白名单 + 参数黑名单**：通过第一阶段后，用 `shlex.split(command, posix=True)` 解析 argv；解析失败、空命令、`argv[0]` 含 `/`、或 `argv[0]` 不在精确白名单时返回 `False`。白名单是命令名精确匹配，不允许前缀匹配（避免 `catwrite` / `sort-and-delete` / 工作区可执行文件伪装成只读命令）。白名单命令还必须拒绝已知写入/长阻塞参数，例如 `tail -f`、`sort -o`、`uniq input output`、`find -fprint/-fprintf/-fls`。

```python
import re
import shlex

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
    # 多字符 token 先列出；单独 & 用 regex 排除 &&。
    if any(token in command for token in ("&&", "||", ">>", "$(", "`", "\n")):
        return True
    if any(token in command for token in (";", "|", ">", "<")):
        return True
    return bool(re.search(r"(?<!&)&(?!&)", command))

def _has_forbidden_readonly_arg(argv: list[str]) -> bool:
    command = argv[0]
    forbidden = READONLY_BASH_FORBIDDEN_ARGS.get(command, set())
    for arg in argv[1:]:
        if arg in forbidden:
            return True
        if any(arg.startswith(f"{flag}=") for flag in forbidden if flag.startswith("--")):
            return True

    if command == "uniq":
        operands = [arg for arg in argv[1:] if not arg.startswith("-")]
        return len(operands) >= 2

    return False

def _is_readonly_bash(input: dict) -> bool:
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

### 1.2 `ToolExecutionQueue` 类

新建 `src/bourbon/tools/execution_queue.py`。

**Callback 线程安全**：REPL callback（`_on_tool_start`/`_on_tool_end`）调用 Rich `console.print()`，不是线程安全的。Queue 内部通过 `_callback_lock` 串行化所有 callback 调用，保证并发工具的 callback 不交错：

```python
self._callback_lock = threading.Lock()   # 单独 lock，专门串行化 callback
```

**Callback 异常隔离**：callback 抛异常不能让整个 future 失败（否则 execute_all() 会抛出、整轮结果丢失）：

```python
def _safe_callback(self, fn, *args):
    if fn is None:
        return
    with self._callback_lock:
        try:
            fn(*args)
        except Exception:
            pass   # callback 异常隔离，不影响工具结果
```

**完整实现**：

```python
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum

from bourbon.tools import Tool

class ToolStatus(Enum):
    QUEUED = "queued"
    EXECUTING = "executing"
    COMPLETED = "completed"

@dataclass
class TrackedTool:
    block: dict
    tool: Tool
    concurrent: bool
    original_index: int
    status: ToolStatus = ToolStatus.QUEUED
    result: dict | None = None
    future: Future | None = None

class ToolExecutionQueue:
    MAX_CONCURRENT_WORKERS = 10

    def __init__(
        self,
        execute_fn: Callable[[dict], str],
        on_tool_start: Callable | None = None,
        on_tool_end: Callable | None = None,
    ):
        self._tools: list[TrackedTool] = []
        self._lock = threading.Lock()           # 保护 _tools 状态
        self._callback_lock = threading.Lock()  # 串行化 callback（线程安全）
        self._thread_pool = ThreadPoolExecutor(
            max_workers=self.MAX_CONCURRENT_WORKERS,
            thread_name_prefix="tool_queue_"
        )
        self._execute_fn = execute_fn
        self._on_tool_start = on_tool_start
        self._on_tool_end = on_tool_end

    def add(self, block: dict, tool: Tool, index: int) -> None:
        concurrent = tool.concurrent_safe_for(block.get("input", {}))
        with self._lock:
            self._tools.append(TrackedTool(
                block=block, tool=tool, concurrent=concurrent, original_index=index
            ))

    def execute_all(self) -> list[dict]:
        try:
            self._process_queue()
            self._wait_all()
            with self._lock:
                return [t.result for t in sorted(self._tools, key=lambda t: t.original_index)]
        finally:
            self._thread_pool.shutdown(wait=True)

    def _can_execute(self, concurrent: bool) -> bool:
        # 须在 _lock 内调用
        executing = [t for t in self._tools if t.status == ToolStatus.EXECUTING]
        return (
            len(executing) == 0
            or (concurrent and all(t.concurrent for t in executing))
        )

    def _process_queue(self) -> None:
        # 持锁时只标记状态，收集待启动工具；锁外再 submit + add_done_callback。
        # 这样避免 future 已完成时 add_done_callback 同步触发 _on_tool_done →
        # _process_queue 再次抢同一把非 reentrant lock 而死锁。
        to_start: list[TrackedTool] = []
        with self._lock:
            for tool in self._tools:
                if tool.status != ToolStatus.QUEUED:
                    continue
                if self._can_execute(tool.concurrent):
                    tool.status = ToolStatus.EXECUTING   # 仅标记，不 submit
                    to_start.append(tool)
                elif not tool.concurrent:
                    break   # 串行工具被阻塞：保持 QUEUED，等 done_callback 唤醒
        # 锁外 submit + 注册 callback（此时 future 完成也只是把 _on_tool_done 入队，不会死锁）
        for tool in to_start:
            tool.future = self._thread_pool.submit(self._run_tool, tool)
            if tool.concurrent:
                tool.future.add_done_callback(lambda _t=tool: self._on_tool_done(_t))

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

    def _safe_callback(self, fn, *args):
        if fn is None:
            return
        with self._callback_lock:
            try:
                fn(*args)
            except Exception:
                pass

    def _on_tool_done(self, tool: TrackedTool) -> None:
        self._process_queue()

    def _wait_all(self) -> None:
        while True:
            with self._lock:
                pending = [t for t in self._tools
                           if t.future is not None and t.status != ToolStatus.COMPLETED]
            if not pending:
                break
            for t in pending:
                t.future.result()
            self._process_queue()
```

### 1.3 `_execute_tools` 改造

**Callback 对称性**：denial / compress / DENY / ASK 路径都需要完整的 `on_tool_start` + `on_tool_end` 调用，与现有行为一致。

**Suspend 前 flush 队列**：防止已入队工具的结果在 resume 时永久丢失。

```python
def _execute_tools(
    self,
    tool_use_blocks,
    *,
    source_assistant_uuid,
    task_nudge_tool_use_blocks=None,
):
    if task_nudge_tool_use_blocks is None:
        task_nudge_tool_use_blocks = tool_use_blocks

    n = len(tool_use_blocks)
    results = [None] * n    # 按原始索引预分配 slot
    manual_compact = False

    def _new_queue() -> ToolExecutionQueue:
        return ToolExecutionQueue(
            execute_fn=lambda block: self._execute_regular_tool(
                block.get("name", ""), block.get("input", {}), skip_policy_check=True
            ),
            # 已入队工具的 start/end 都由 queue 在实际执行时发出。
            on_tool_start=self.on_tool_start,
            on_tool_end=self.on_tool_end,
        )

    queue: ToolExecutionQueue | None = None

    def _ensure_queue() -> ToolExecutionQueue:
        nonlocal queue
        if queue is None:
            queue = _new_queue()
        return queue

    def _safe_direct_callback(fn, *args):
        if fn is None:
            return
        try:
            fn(*args)
        except Exception:
            pass

    def _direct_start(tool_name: str, tool_input: dict) -> None:
        _safe_direct_callback(self.on_tool_start, tool_name, tool_input)

    def _direct_end(tool_name: str, output: str) -> None:
        _safe_direct_callback(self.on_tool_end, tool_name, output)

    def _fill_queue_results() -> None:
        """Drain queue, then fill returned results by tool_use_id into result slots."""
        nonlocal queue
        if queue is None:
            return
        drained_queue = queue
        queue = None   # execute_all() shuts down the executor; never reuse it.
        for r in drained_queue.execute_all():
            uid = r.get("tool_use_id")
            for j, b in enumerate(tool_use_blocks):
                if b.get("id") == uid and results[j] is None:
                    results[j] = r
                    break

    for index, block in enumerate(tool_use_blocks):
        tool_name = block.get("name", "")
        tool_input = block.get("input", {})
        tool_id = block.get("id", "")

        # denial
        denial = self._subagent_tool_denial(tool_name)
        if denial is not None:
            _fill_queue_results()
            _direct_start(tool_name, tool_input)
            results[index] = {"type": "tool_result", "tool_use_id": tool_id,
                              "content": str(denial)[:50000], "is_error": True}
            _direct_end(tool_name, str(denial))
            continue

        # compress
        if tool_name == "compress":
            _fill_queue_results()
            _direct_start(tool_name, tool_input)
            manual_compact = True
            results[index] = {"type": "tool_result", "tool_use_id": tool_id,
                              "content": "Compressing context..."}
            _direct_end(tool_name, "Compressing context...")
            continue

        # permission
        permission = self._permission_decision_for_tool(tool_name, tool_input)
        if permission.action == PermissionAction.DENY:
            _fill_queue_results()
            _direct_start(tool_name, tool_input)
            msg = f"Denied: {permission.reason}"
            results[index] = {"type": "tool_result", "tool_use_id": tool_id,
                              "content": msg}
            _direct_end(tool_name, msg)
            continue
        if permission.action == PermissionAction.ASK:
            # suspend 前先 flush 已入队工具；再展示 ASK 工具，保持 callback 顺序。
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
                    tool_name=tool_name, tool_input=tool_input,
                    tool_use_id=tool_id, decision=permission, workdir=self.workdir,
                ),
            )
            _direct_end(tool_name, "Requires permission")
            return completed

        # 入队工具由 queue 负责 callback，避免主循环和 worker 重复 start。
        tool_obj = get_tool_with_metadata(tool_name)
        if tool_obj:
            _ensure_queue().add(block, tool_obj, index)
        else:
            _fill_queue_results()
            _direct_start(tool_name, tool_input)
            msg = f"Unknown tool: {tool_name}"
            results[index] = {"type": "tool_result", "tool_use_id": tool_id,
                              "content": msg, "is_error": True}
            _direct_end(tool_name, msg)

    # 执行队列
    _fill_queue_results()

    if manual_compact:
        self._manual_compact()

    return [r for r in results if r is not None]
```

**注意**：已入队工具的 `on_tool_start` / `on_tool_end` 只由 queue 发出；denial / compress / DENY / ASK / unknown 这些非入队路径在主循环中直接发出。主循环处理任何非入队路径前必须先 `_fill_queue_results()`，保证前序已入队工具的 callback 与结果先落地，尤其是 ASK suspend 前不能先显示待授权工具再显示前序工具。

---

## 特性二：Subagent 工具可见性

### 2.0 共享任务工具常量

新增 `src/bourbon/tasks/constants.py`，由 `src/bourbon/subagent/tools.py` 和 `src/bourbon/agent.py` 共同导入，避免 `TASK_V2_TOOLS` 在多个模块里重复硬编码：

```python
TASK_V2_TOOLS = {"TaskCreate", "TaskUpdate", "TaskList", "TaskGet"}
```

### 2.1 `SubagentMode` 枚举

`src/bourbon/subagent/types.py` 新增：

```python
class SubagentMode(Enum):
    NORMAL = "normal"
    TEAMMATE = "teammate"
    ASYNC = "async"
```

### 2.2 `Agent` 新增 `task_list_id_override`

**修复 teammate 任务列表问题**：config 是共享对象引用，不能直接修改。改为在 `Agent` 上添加独立字段，并修改 `_resolve_task_list_id` 优先读取它：

```python
# Agent.__init__
self.subagent_mode: SubagentMode = SubagentMode.NORMAL
self.task_list_id_override: str | None = None   # 新增
```

修改 `src/bourbon/tools/task_tools.py` 中的 `_resolve_task_list_id`：

```python
def _resolve_task_list_id(ctx: ToolContext, task_list_id: str | None) -> str:
    if task_list_id:
        return task_list_id
    agent = ctx.agent
    if agent is not None:
        # 优先：agent 级别显式覆盖（用于 teammate 继承父任务列表）
        override = getattr(agent, "task_list_id_override", None)
        if override:
            return str(override)
        # 其次：session id
        session_id = getattr(getattr(agent, "session", None), "session_id", None)
        if session_id:
            return str(session_id)
        # 再次：config
        default_list_id = getattr(getattr(getattr(agent, "config", None), "tasks", None),
                                  "default_list_id", None)
        if default_list_id:
            return str(default_list_id)
    return "default"
```

### 2.3 `SubagentRun` 携带 mode 和 parent_task_list_id

`SubagentRun` dataclass 新增两个字段：

```python
subagent_mode: SubagentMode = SubagentMode.NORMAL
parent_task_list_id: str | None = None
```

`spawn()` 计算并写入：

```python
def spawn(self, ..., agent_type: str, run_in_background: bool):
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

    run = SubagentRun(..., subagent_mode=mode, parent_task_list_id=parent_task_list_id)
```

`_create_subagent()` 从 run 读取，设置到子 agent（不修改 config）。`agent_factory` 是测试/扩展 hook，也必须经过同一个 runtime 配置 helper；否则 factory 返回的 agent 会绕过 `subagent_mode` 和 `task_list_id_override`：

```python
def _create_subagent(self, run, agent_def, agent_factory):
    if agent_factory is not None:
        subagent = agent_factory(run, agent_def)
        self._configure_subagent_runtime(subagent, run, agent_def, attach_session=False)
        return subagent

    ...
    subagent = Agent(config=self.config, ...)   # config 不改
    self._configure_subagent_runtime(subagent, run, agent_def, attach_session=True)
    return subagent

def _configure_subagent_runtime(self, subagent, run, agent_def, *, attach_session: bool):
    subagent._max_tool_rounds = run.max_turns
    subagent.subagent_mode = run.subagent_mode
    subagent._subagent_agent_def = agent_def
    subagent._subagent_tool_filter = ToolFilter()
    if run.parent_task_list_id:
        subagent.task_list_id_override = run.parent_task_list_id
    if attach_session:
        ...
```

`attach_session=False` 的 factory 分支不替换 factory 自己创建的 session；factory 返回对象的 session 生命周期仍由 factory 负责，但 mode/filter/task-list override 不能绕过。

### 2.4 `ToolFilter` + 调用点更新

**`ToolFilter.is_allowed()`** 接受 `subagent_mode`，保留 `ALL_AGENT_DISALLOWED_TOOLS` 最高优先：

```python
from bourbon.tasks.constants import TASK_V2_TOOLS

class ToolFilter:
    def is_allowed(self, tool_name: str, agent_def: AgentDefinition,
                   subagent_mode: SubagentMode | None = None) -> bool:
        if tool_name in ALL_AGENT_DISALLOWED_TOOLS:   # 最高优先，任何 mode 不例外
            return False
        if tool_name in agent_def.disallowed_tools:
            return False
        if subagent_mode == SubagentMode.ASYNC and tool_name in TASK_V2_TOOLS:
            return False
        if subagent_mode == SubagentMode.TEAMMATE and tool_name in TASK_V2_TOOLS:
            return True   # 绕过白名单
        if agent_def.allowed_tools is not None:
            return tool_name in agent_def.allowed_tools
        return True

    def filter_tools(self, tools: list[dict], agent_def: AgentDefinition,
                     subagent_mode: SubagentMode | None = None) -> list[dict]:
        return [
            tool for tool in tools
            if self.is_allowed(
                str(tool.get("name", "")),
                agent_def,
                subagent_mode=subagent_mode,
            )
        ]
```

**调用点明确更新**：

`Agent._tool_definitions()`：
```python
filtered_tools = filter_engine.filter_tools(tool_defs, agent_def,
                                            subagent_mode=self.subagent_mode)
```

`Agent._subagent_tool_denial()`：
```python
if filter_engine.is_allowed(tool_name, agent_def, subagent_mode=self.subagent_mode):
    return None
```

`ToolFilter.filter_tools()` 必须同步接受并向下传递 `subagent_mode`，否则 `Agent._tool_definitions()` 的关键字参数调用会直接 `TypeError`。

### 2.5 `AGENT_TYPE_CONFIGS` + `subagent_type` schema enum

对外工具 schema 字段名保持现状：`subagent_type`。内部 `SubagentManager.spawn()` 参数仍叫 `agent_type`，`agent_tool.py` handler 负责把 `subagent_type` 透传为 `agent_type=subagent_type`。

```python
# subagent/tools.py
"teammate": AgentDefinition(
    agent_type="teammate",
    description="In-process teammate for task claiming and parallel execution",
    allowed_tools=None,
    max_turns=100,
),

# tools/agent_tool.py input_schema
"subagent_type": {
    "type": "string",
    "enum": ["default", "coder", "explore", "plan", "quick_task", "teammate"],
}

# tools/agent_tool.py handler
manager.spawn(..., agent_type=subagent_type, ...)
```

---

## 特性三：Task Nudge 机制

### 3.1 注入位置

附加到 `tool_turn_msg.content`，不注入独立 USER message。注入只能发生在 tool result transcript 真正写入 session 之前；如果 `_execute_tools()` 因 ASK suspend 返回，当前 loop 不注入，等 `resume_permission_request()` 最终构造同一个 tool result transcript 时再判断：

```python
tool_results = self._execute_tools(tool_use_blocks, ...)
tool_turn_msg = self._build_tool_results_transcript_message(tool_results, ...)

self._append_task_nudge_if_due(tool_turn_msg, tool_use_blocks)
self.session.add_message(tool_turn_msg)
```

三条提交 tool result transcript 的路径都必须调用同一个 helper：

1. `_run_conversation_loop`
2. `_run_conversation_loop_stream`
3. `resume_permission_request`

`resume_permission_request()` 使用 suspend 时保存的原始 `task_nudge_tool_use_blocks`，避免一个 LLM tool round 因多次权限暂停被重复计数或只按 remaining blocks 计数。

### 3.2 计数器

计数器是 `Agent` 实例状态，不是 loop 局部变量。这样 streaming / non-streaming fallback、permission suspend / resume 都不会重置阈值进度。

```python
from bourbon.tasks.constants import TASK_V2_TOOLS

TASK_NUDGE_THRESHOLD = 10

# Agent.__init__
self._rounds_without_task = 0

# SuspendedToolRound 新增字段，用于权限恢复后按原始 LLM tool round 计数
# 使用 default_factory=list 避免破坏现有测试（object.__new__ 绕过 __init__ 的场景）
task_nudge_tool_use_blocks: list[dict] = field(default_factory=list)

# resume 时取原始列表；若字段未设（旧构造点）则回退到 suspended.tool_use_blocks
nudge_blocks = suspended.task_nudge_tool_use_blocks or suspended.tool_use_blocks

def _suspend_tool_round(..., task_nudge_tool_use_blocks: list[dict]) -> None:
    self.suspended_tool_round = SuspendedToolRound(
        ...,
        task_nudge_tool_use_blocks=task_nudge_tool_use_blocks,
    )

def _append_task_nudge_if_due(
    self,
    tool_turn_msg: TranscriptMessage,
    tool_use_blocks: list[dict],
) -> None:
    if not tool_use_blocks:
        return

    # 防御式读取：object.__new__(Agent) 绕过 __init__ 时该属性不存在
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
    # 无论是否有 pending 任务，都重置计数器，避免每轮重复构造 TaskService
    self._rounds_without_task = 0
```

`resume_permission_request()` 继续执行 remaining blocks 时，如果再次触发 ASK，需要把已有 suspend 的 `task_nudge_tool_use_blocks` 传入 `_execute_tools(..., task_nudge_tool_use_blocks=suspended.task_nudge_tool_use_blocks)`，并由新的 `_suspend_tool_round()` 继续保存这个原始列表。

```python
results.extend(
    self._execute_tools(
        remaining_blocks,
        source_assistant_uuid=source_assistant_uuid,
        task_nudge_tool_use_blocks=suspended.task_nudge_tool_use_blocks,
    )
)
if self.active_permission_request:
    return ""

tool_turn_msg = self._build_tool_results_transcript_message(results, source_assistant_uuid)
self._append_task_nudge_if_due(
    tool_turn_msg,
    suspended.task_nudge_tool_use_blocks,
)
self.session.add_message(tool_turn_msg)
```

### 3.3 `_build_task_reminder_block()`

task_list_id 与 `_resolve_task_list_id` 完全对齐（override → session_id → config → "default"）：

```python
def _build_task_reminder_block(self) -> TextBlock | None:
    from bourbon.tasks.service import TaskService
    from bourbon.tasks.store import TaskStore

    # 与 REPL /tasks 路径一致，每次按配置构造轻量 service；
    # 避免在 Agent 上缓存 TaskService 后引入额外生命周期状态。
    storage_dir = Path(self.config.tasks.storage_dir).expanduser()
    service = TaskService(TaskStore(storage_dir))

    task_list_id = (
        self.task_list_id_override
        or getattr(getattr(self, "session", None), "session_id", None)
        or getattr(getattr(getattr(self, "config", None), "tasks", None),
                   "default_list_id", None)
        or "default"
    )

    tasks = service.list_tasks(str(task_list_id))
    pending = [t for t in tasks if t.status != "completed"]   # status 是 str
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
        f"Please update with TaskUpdate or create with TaskCreate.\n\n{lines}\n"
        f"</task_reminder>"
    ))
```

---

## 变更文件清单

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `src/bourbon/tools/__init__.py` | 修改 | `_concurrency_fn` + `concurrent_safe_for()`；`register_tool` 新增 `concurrency_fn` |
| `src/bourbon/tools/execution_queue.py` | **新建** | `ToolStatus` / `TrackedTool` / `ToolExecutionQueue`；双 Lock（状态 + callback 串行化）；callback 异常隔离；finally shutdown |
| `src/bourbon/tasks/constants.py` | **新建** | 定义 `TASK_V2_TOOLS = {"TaskCreate", "TaskUpdate", "TaskList", "TaskGet"}`，供 subagent filter 和 nudge 共用 |
| `src/bourbon/tools/base.py` | 修改 | `Bash` 标注 `concurrency_fn=_is_readonly_bash`（两阶段：控制符含 `\n`/`&` + shlex 精确命令白名单 + 写入/阻塞参数黑名单）；`Read`/`Glob`/`Grep`/`AstGrep`/`WebFetch` 标注 `is_concurrency_safe=True`；`ToolSearch` 保持 `False` |
| `src/bourbon/tools/agent_tool.py` | 修改 | `Agent` 工具标注 `is_concurrency_safe=True`；`subagent_type` schema enum 新增 "teammate"；handler 继续映射到内部 `agent_type` |
| `src/bourbon/tools/task_tools.py` | 修改 | `_resolve_task_list_id` 新增 `task_list_id_override` 最高优先检查 |
| `src/bourbon/agent.py` | 修改 | `__init__` 新增 `subagent_mode`/`task_list_id_override`/`_rounds_without_task`；`_execute_tools` 重构（queue lazy create + queued callbacks 只由 queue 发出 + 非入队路径先 flush + flush on suspend）；两条 loop 和 `resume_permission_request()` 增 nudge；新增 `_append_task_nudge_if_due()` / `_build_task_reminder_block()` |
| `src/bourbon/permissions/runtime.py` | 修改 | `SuspendedToolRound` 新增 `task_nudge_tool_use_blocks`，权限多次暂停时保留原始 LLM tool round |
| `src/bourbon/subagent/types.py` | 修改 | 新增 `SubagentMode`；`SubagentRun` 新增 `subagent_mode`/`parent_task_list_id` |
| `src/bourbon/subagent/tools.py` | 修改 | `AGENT_TYPE_CONFIGS` 新增 "teammate"；`ToolFilter` 接受 `subagent_mode`，`filter_tools` 传递 mode；导入共享 `TASK_V2_TOOLS` |
| `src/bourbon/subagent/manager.py` | 修改 | `spawn()` 计算 mode/parent_task_list_id 写入 run；`_create_subagent()` 的默认和 `agent_factory` 分支都调用同一 runtime 配置 helper |
| `tests/test_tool_execution_queue.py` | **新建** | `ToolStatus` 定义 + 并发 + serial 阻塞 + 顺序 + callback 串行化 + 异常隔离 + shutdown + queued start 不重复 + 空队列返回空结果 |
| `tests/test_subagent/test_subagent_mode.py` | **新建** | teammate/async 双路径 + task_list_id 继承 + factory 分支继承 mode/override + `subagent_type` schema |
| `tests/test_task_nudge.py` | **新建** | 阈值 + 重置 + 无 pending 跳过 + session_id 路由 + permission resume 保持计数 |

---

## 设计原则对照

| 维度 | Claude Code | bourbon v7 |
|------|-------------|------------|
| `isConcurrencySafe` | interface 方法 | `concurrent_safe_for()` + `_concurrency_fn` 优先 |
| bool 向后兼容 | — | `is_concurrency_safe: bool` 不变 |
| Callback 线程安全 | 单线程 async | `_callback_lock` 串行化，隔离异常 |
| Suspend 保序 | streaming id 追踪 | suspend 前 flush 队列 |
| Teammate task list | parent session | `task_list_id_override` 最高优先，不修改 config |
| SubagentMode 传递 | run 对象 | `SubagentRun.subagent_mode`，`_create_subagent()` 写入 agent |
| SubagentMode 执行层 | allowlist | `ToolFilter` 双路径均传 `subagent_mode` |
| Bash 安全判断 | `isReadOnly` | 两阶段：控制符（含 `\n`/`&`）+ `shlex.split` 精确命令白名单 + 写入/阻塞参数黑名单 |

---

*设计文档作者：Claude Sonnet 4.6*
*v7：整合第六轮 code review 修正（2026-04-14）*
*基于 Claude Code `main` 分支源码分析*
