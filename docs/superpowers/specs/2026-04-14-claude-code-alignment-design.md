# Bourbon ↔ Claude Code 对齐设计：并发工具执行 + 任务管理

**日期**：2026-04-14（v2，已整合 code review 修正）
**范围**：三个特性的对齐实现
1. 并发工具执行（`ToolExecutionQueue` + `is_concurrency_safe`）
2. Subagent 工具可见性（`SubagentMode` 区分 teammate / async）
3. Task Nudge 机制（10 轮阈值注入 `task_reminder`）

---

## 背景

Claude Code 采用 **LLM-centric** 设计哲学：LLM 是唯一的 orchestrator，系统模块只提供原子性辅助。bourbon 作为对齐 Claude Code 设计的学习项目，本次需要补齐三个关键机制：

- **并发工具执行**：Claude Code 的 `StreamingToolExecutor` 允许多个 `isConcurrencySafe=true` 的工具（如 AgentTool）在同一轮内并行执行。bourbon 目前是串行 for loop。
- **Subagent 工具可见性**：Claude Code 区分 in-process teammate（强制注入 Task V2 工具）和普通 async subagent（剥离 Task 工具）。bourbon 没有这种区分。
- **Task Nudge**：Claude Code 在 LLM 超过 10 轮未操作任务时注入 `task_reminder`。bourbon 的 `TASK_GUIDELINES` prompt 文档了这个机制但未实现。

---

## 特性一：并发工具执行

### 1.1 `Tool.is_concurrency_safe` 字段（类型扩展）

`Tool` dataclass（`src/bourbon/tools/__init__.py`）已有 `is_concurrency_safe: bool = False` 字段和 `register_tool` 的同名参数。

**变更**：将字段类型从 `bool` 扩展为 `Callable[[dict], bool] | bool`，在 `__post_init__` 中归一化为 `Callable[[dict], bool]`，并新增 `concurrent_safe_for(input: dict) -> bool` 方法供调用方使用。

保持向后兼容：现有 `is_concurrency_safe=True/False` 的调用无需修改。

```python
@dataclass
class Tool:
    name: str
    # ...
    is_concurrency_safe: Callable[[dict], bool] | bool = False  # 类型扩展

    def __post_init__(self):
        # 归一化：bool → callable
        if isinstance(self.is_concurrency_safe, bool):
            _val = self.is_concurrency_safe
            self.is_concurrency_safe = lambda _: _val
        # ... 其余 __post_init__ 逻辑不变 ...

    def concurrent_safe_for(self, tool_input: dict) -> bool:
        """判断此工具调用是否可与其他工具并行执行。

        镜像 Claude Code Tool.isConcurrencySafe(input)。
        """
        try:
            return bool(self.is_concurrency_safe(tool_input))
        except Exception:
            return False
```

**`register_tool` 装饰器**：`is_concurrency_safe` 参数类型同步扩展为 `Callable[[dict], bool] | bool`。

**各工具标注**（镜像 Claude Code）：

| 工具 | is_concurrency_safe 值 | 说明 |
|------|------------------------|------|
| `agent` (AgentTool) | `lambda _: True` | 始终可并行，镜像 CC |
| `read` | `lambda _: True` | 只读，天然安全 |
| `glob` / `grep` / `search` | `lambda _: True` | 只读 |
| `bash` | `_is_readonly_bash` | 动态判断（见下文） |
| `write` / `edit` | `False`（默认） | 写操作，串行 |
| Task 工具 | `False`（默认） | 状态变更，串行 |
| `skill` | `False`（默认） | 串行 |

**`_is_readonly_bash(input: dict) -> bool`**：使用明确只读命令**白名单**（非前缀推断），仅以下命令前缀视为安全：`ls`、`cat`、`grep`、`find`（不含 `-delete`/`-exec rm`）、`echo`（不含重定向 `>`）、`pwd`、`wc`、`head`、`tail`、`stat`、`file`、`diff`、`sort`、`uniq`。其他命令一律返回 `False`（fail-closed）。

### 1.2 `ToolExecutionQueue` 类

新建文件 `src/bourbon/tools/execution_queue.py`，镜像 Claude Code `StreamingToolExecutor`。

**数据结构：**

```python
class ToolStatus(Enum):
    QUEUED = "queued"
    EXECUTING = "executing"
    COMPLETED = "completed"

@dataclass
class TrackedTool:
    block: dict                    # 原始 tool_use block
    tool: Tool
    concurrent: bool               # concurrent_safe_for() 的结果（入队时计算一次）
    status: ToolStatus = ToolStatus.QUEUED
    result: dict | None = None     # tool_result block
    future: Future | None = None
```

**队列主体（含线程安全修正）：**

```python
class ToolExecutionQueue:
    MAX_CONCURRENT_WORKERS = 10

    def __init__(self, execute_fn: Callable[[dict], dict], ...):
        self._tools: list[TrackedTool] = []
        self._lock = threading.Lock()           # 保护 _tools 的所有读写
        self._thread_pool = ThreadPoolExecutor(
            max_workers=self.MAX_CONCURRENT_WORKERS,
            thread_name_prefix="tool_queue_"
        )
        self._execute_fn = execute_fn

    def add(self, block: dict, tool: Tool) -> None:
        concurrent = tool.concurrent_safe_for(block.get("input", {}))
        tracked = TrackedTool(block=block, tool=tool, concurrent=concurrent)
        with self._lock:
            self._tools.append(tracked)

    def execute_all(self) -> list[dict]:
        """执行所有入队工具，返回有序结果。"""
        self._process_queue()
        # 等待所有 future 完成（含后续被触发的工具）
        self._wait_all()
        with self._lock:
            return [t.result for t in self._tools]

    def _can_execute(self, concurrent: bool) -> bool:
        """镜像 StreamingToolExecutor.canExecuteTool()
        调用前必须已持有 self._lock。
        """
        executing = [t for t in self._tools if t.status == ToolStatus.EXECUTING]
        return (
            len(executing) == 0
            or (concurrent and all(t.concurrent for t in executing))
        )

    def _process_queue(self) -> None:
        """镜像 StreamingToolExecutor.processQueue()。加锁后操作 _tools。"""
        with self._lock:
            for tool in self._tools:
                if tool.status != ToolStatus.QUEUED:
                    continue
                if self._can_execute(tool.concurrent):
                    self._start_tool_locked(tool)
                elif not tool.concurrent:
                    # 串行工具遇到正在执行的 concurrent 工具时：
                    # 保持 QUEUED 状态，等 concurrent 工具完成后 done_callback
                    # 会再次触发 _process_queue，届时串行工具才会被执行。
                    # 不在这里阻塞，也不标记 COMPLETED。
                    break

    def _start_tool_locked(self, tool: TrackedTool) -> None:
        """在 self._lock 已持有的情况下启动工具执行。"""
        tool.status = ToolStatus.EXECUTING
        if tool.concurrent:
            tool.future = self._thread_pool.submit(self._run_tool, tool)
            tool.future.add_done_callback(lambda _: self._on_tool_done(tool))
        else:
            # 串行工具：需要先释放锁再执行（避免死锁），执行完再重新获锁
            # 通过 submit + future.result() 实现（仍在当前调用链等待）
            tool.future = self._thread_pool.submit(self._run_tool, tool)
            # 注意：这里不加 done_callback，_process_queue 调用者会 wait_all

    def _run_tool(self, tool: TrackedTool) -> None:
        tool.result = self._execute_fn(tool.block)
        with self._lock:
            tool.status = ToolStatus.COMPLETED

    def _on_tool_done(self, tool: TrackedTool) -> None:
        """concurrent 工具完成时回调，触发队列继续推进。"""
        self._process_queue()

    def _wait_all(self) -> None:
        """等待所有 future 完成（处理 concurrent 完成后触发的串行工具）。"""
        while True:
            with self._lock:
                pending = [t for t in self._tools if t.future and t.status != ToolStatus.COMPLETED]
            if not pending:
                break
            for t in pending:
                if t.future:
                    t.future.result()
            # 等待后再触发一次，捡起可能因串行工具解锁而新进入 EXECUTING 的工具
            self._process_queue()
```

**关键设计说明**：
- `_process_queue` 遇到"串行工具被 concurrent 工具阻塞"时，将串行工具保持 `QUEUED`（不执行、不标 COMPLETED）
- 当前面的 concurrent 工具完成，`done_callback` 触发 `_process_queue()`，此时串行工具条件满足，才被执行
- `_lock` 保护所有 `_tools` 读写，`_run_tool` 在线程池中执行（锁外），完成后重新获锁更新状态

### 1.3 `_execute_tools` 改造

```python
def _execute_tools(self, tool_use_blocks, *, source_assistant_uuid):
    results = []
    queue = ToolExecutionQueue(
        execute_fn=lambda block: self._execute_regular_tool(
            block.get("name", ""), block.get("input", {}), skip_policy_check=True
        ),
        on_tool_start=self.on_tool_start,
        on_tool_end=self.on_tool_end,
    )
    manual_compact = False

    for index, block in enumerate(tool_use_blocks):
        tool_name = block.get("name", "")
        tool_input = block.get("input", {})
        tool_id = block.get("id", "")

        # denial / special tool 检查（串行，不进队列）
        denial = self._subagent_tool_denial(tool_name)
        if denial is not None:
            results.append({"type": "tool_result", "tool_use_id": tool_id,
                            "content": str(denial)[:50000], "is_error": True})
            continue

        if tool_name == "compress":
            manual_compact = True
            results.append({"type": "tool_result", "tool_use_id": tool_id,
                            "content": "Compressing context..."})
            continue

        # permission 检查（串行）
        permission = self._permission_decision_for_tool(tool_name, tool_input)
        if permission.action == PermissionAction.DENY:
            results.append({"type": "tool_result", "tool_use_id": tool_id,
                            "content": f"Denied: {permission.reason}"})
            continue
        if permission.action == PermissionAction.ASK:
            self._suspend_tool_round(
                source_assistant_uuid=source_assistant_uuid,
                tool_use_blocks=tool_use_blocks,
                completed_results=results,
                next_tool_index=index,
                request=build_permission_request(...),
            )
            return results

        # 通过所有检查 → 入队
        tool = self._registry.get(tool_name)
        queue.add(block, tool)

    # 执行队列
    queued_results = queue.execute_all()
    results.extend(queued_results)

    if manual_compact:
        self._manual_compact()

    return results
```

---

## 特性二：Subagent 工具可见性

### 2.1 `SubagentMode` 枚举

在 `src/bourbon/subagent/types.py` 新增：

```python
class SubagentMode(Enum):
    NORMAL = "normal"
    TEAMMATE = "teammate"   # in-process teammate：强制 Task V2 工具
    ASYNC = "async"         # 纯执行型：剥离 Task 工具
```

### 2.2 `AGENT_TYPE_CONFIGS` 新增 teammate

在 `src/bourbon/subagent/tools.py` 的 `AGENT_TYPE_CONFIGS` 中新增：

```python
"teammate": AgentDefinition(
    agent_type="teammate",
    description="In-process teammate for task claiming and parallel execution",
    allowed_tools=None,   # 不设白名单，依赖 SubagentMode 注入 Task 工具
    max_turns=100,
)
```

### 2.3 双路径过滤：`_tool_definitions()` + `ToolFilter`

**路径一**：`Agent._tool_definitions()` 控制 LLM 看到的工具定义（影响 LLM 是否会生成该工具的 tool_use）。

```python
TASK_V2_TOOLS = frozenset({"TaskCreate", "TaskUpdate", "TaskList", "TaskGet"})

def _tool_definitions(self) -> list[dict]:
    tools = self._registry.definitions()

    if self.subagent_mode == SubagentMode.TEAMMATE:
        present = {t["name"] for t in tools}
        for name in TASK_V2_TOOLS - present:
            tool = self._registry.get(name)
            if tool:
                tools = tools + [tool.to_definition()]

    elif self.subagent_mode == SubagentMode.ASYNC:
        tools = [t for t in tools if t["name"] not in TASK_V2_TOOLS]

    return tools
```

**路径二**：`ToolFilter`（`src/bourbon/subagent/tools.py`）控制执行层 denial。需同步更新：

```python
class ToolFilter:
    def is_allowed(self, tool_name: str, agent_def: AgentDefinition,
                   subagent_mode: SubagentMode | None = None) -> bool:
        if tool_name in agent_def.disallowed_tools:
            return False

        # SubagentMode.ASYNC 强制拒绝 Task 工具
        if subagent_mode == SubagentMode.ASYNC and tool_name in TASK_V2_TOOLS:
            return False

        # SubagentMode.TEAMMATE 强制允许 Task 工具（绕过 allowed_tools 白名单）
        if subagent_mode == SubagentMode.TEAMMATE and tool_name in TASK_V2_TOOLS:
            return True

        if agent_def.allowed_tools is not None:
            return tool_name in agent_def.allowed_tools
        return True
```

`Agent._subagent_tool_denial()` 调用 `ToolFilter.is_allowed()` 时传入 `self.subagent_mode`。

### 2.4 `spawn()` 决定 mode

```python
def spawn(self, ..., agent_type: str, run_in_background: bool) -> ...:
    if agent_type == "teammate":
        mode = SubagentMode.TEAMMATE
    elif run_in_background:
        mode = SubagentMode.ASYNC
    else:
        mode = SubagentMode.NORMAL
    run = SubagentRun(..., subagent_mode=mode)
```

**与 Claude Code 对齐：**

| Claude Code | bourbon |
|-------------|---------|
| `inProcessRunner.ts:982` 硬注入 Task V2 | `SubagentMode.TEAMMATE`：定义层 + 执行层双保证 |
| `ASYNC_AGENT_ALLOWED_TOOLS` 排除 Task V2 | `SubagentMode.ASYNC`：定义层 + 执行层双拒绝 |
| 主线程/sync subagent 跟随 session | `SubagentMode.NORMAL`：继承父 agent |

---

## 特性三：Task Nudge 机制

### 3.1 注入位置：附加在 tool_results user message 内

**不能**将 `task_reminder` 注入为独立 USER message（会破坏 tool_use → tool_result 配对协议）。

正确做法：在构建 `tool_turn_msg` 时，将 reminder 作为额外 `TextBlock` 附加到同一条 user message 中：

```python
# agent.py _run_conversation_loop 内
tool_results = self._execute_tools(tool_use_blocks, ...)

# 构建 tool_results message
tool_turn_msg = self._build_tool_results_transcript_message(tool_results, assistant_msg.uuid)

# 若需要 nudge，附加到同一条 user message 的 content
if rounds_without_task >= TASK_NUDGE_THRESHOLD:
    reminder_block = self._build_task_reminder_block()
    if reminder_block:
        tool_turn_msg.content.append(reminder_block)
        rounds_without_task = 0

self.session.add_message(tool_turn_msg)
```

这样 `task_reminder` 和 `tool_result` blocks 在**同一条 user message** 里，不破坏协议。

### 3.2 计数器追踪（两条 loop 都需要）

`TASK_NUDGE_THRESHOLD = 10`，镜像 Claude Code `TODO_REMINDER_CONFIG.TURNS_SINCE_WRITE`。

**重置条件**：任意 Task V2 工具（`TaskCreate`/`TaskUpdate`/`TaskList`/`TaskGet`）被调用即重置，不区分读写（与 CC 实际行为一致）。

```python
# 在 _run_conversation_loop 和 _run_conversation_loop_stream 中都加：
used_task_tool = any(b.get("name") in TASK_V2_TOOLS for b in tool_use_blocks)
if used_task_tool:
    rounds_without_task = 0
elif has_tool_calls:
    rounds_without_task += 1
```

### 3.3 `_build_task_reminder_block()` 内联构造 TaskService

Agent 没有 `self._task_service`，需内联构造：

```python
def _build_task_reminder_block(self) -> TextBlock | None:
    """构建 task_reminder TextBlock，若无 pending 任务则返回 None。

    镜像 CC attachments.ts task_reminder attachment。
    """
    from bourbon.tasks.service import TaskService
    from bourbon.tasks.store import TaskStore

    storage_dir = Path(self.config.tasks.storage_dir).expanduser()
    service = TaskService(TaskStore(storage_dir))

    # task_list_id 同 task_tools.py 的 _resolve_task_list_id 逻辑
    task_list_id = getattr(
        getattr(self.config, "tasks", None), "default_list_id", None
    ) or "default"

    tasks = service.list_tasks(task_list_id)
    pending = [t for t in tasks if t.status.value != "completed"]
    if not pending:
        return None   # 无 pending 任务时跳过，镜像 CC brief mode 跳过逻辑

    lines = "\n".join(
        f"- [{t.status.value}] {t.subject}"
        + (f" (blocked by: {', '.join(t.blocked_by)})" if t.blocked_by else "")
        for t in pending
    )
    text = (
        f"<task_reminder>\n"
        f"You have {len(pending)} pending task(s). "
        f"Please update their status with TaskUpdate, "
        f"or use TaskCreate if new work is needed.\n\n{lines}\n"
        f"</task_reminder>"
    )
    return TextBlock(text=text)
```

**与 Claude Code 对齐：**

| Claude Code | bourbon |
|-------------|---------|
| `TODO_REMINDER_CONFIG.TURNS_SINCE_WRITE = 10` | `TASK_NUDGE_THRESHOLD = 10` |
| `task_reminder` attachment 在 tool_result 同轮注入 | `TextBlock` 附加到 tool_turn_msg.content |
| 跳过 brief mode / ant users | 无 pending 任务时返回 None |
| 任意 Task 工具使用重置计数 | 同上 |
| 两条 loop 路径都有 | `_run_conversation_loop` + `_run_conversation_loop_stream` |

---

## 变更文件清单

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `src/bourbon/tools/__init__.py` | 修改 | `Tool.is_concurrency_safe` 类型扩展为 `Callable\|bool`；`__post_init__` 归一化；新增 `concurrent_safe_for()` 方法；`register_tool` 参数类型扩展 |
| `src/bourbon/tools/execution_queue.py` | **新建** | `ToolExecutionQueue` + `TrackedTool` + `ToolStatus`；带 `threading.Lock` 的线程安全实现 |
| `src/bourbon/tools/base.py` | 修改 | `bash` 标注 `is_concurrency_safe=_is_readonly_bash`；`read`/`glob`/`grep`/`search` 标注 `True` |
| `src/bourbon/tools/agent_tool.py` | 修改 | AgentTool 标注 `is_concurrency_safe=lambda _: True` |
| `src/bourbon/agent.py` | 修改 | `_execute_tools` 改用队列；`_run_conversation_loop` 和 `_run_conversation_loop_stream` 增加 nudge 计数；新增 `_build_task_reminder_block()` |
| `src/bourbon/subagent/types.py` | 修改 | 新增 `SubagentMode` 枚举 |
| `src/bourbon/subagent/tools.py` | 修改 | `AGENT_TYPE_CONFIGS` 新增 "teammate"；`ToolFilter.is_allowed()` 接受 `subagent_mode` 参数 |
| `src/bourbon/subagent/manager.py` | 修改 | `spawn()` 根据 `agent_type`/`run_in_background` 决定 `SubagentMode` |
| `tests/test_tool_execution_queue.py` | **新建** | 队列并发逻辑（concurrent batch、serial 阻塞等待、混合场景、线程安全） |
| `tests/test_subagent_tool_visibility.py` | **新建** | teammate/async 工具过滤（双路径） |
| `tests/test_task_nudge.py` | **新建** | nudge 阈值触发、重置、无 pending 时跳过、附加到 tool_turn_msg |

---

## 设计原则对照

| 维度 | Claude Code | bourbon 本次对齐 |
|------|-------------|----------------|
| `isConcurrencySafe` | interface 方法，动态 | `is_concurrency_safe: Callable\|bool` 字段 + `concurrent_safe_for()` 方法 |
| 执行队列 | 异步流式 `StreamingToolExecutor` | 同步 `ToolExecutionQueue` + ThreadPoolExecutor + Lock |
| serial 工具等待 | 保持 queued，done_callback 唤醒 | 同上（v2 修正） |
| Subagent 工具可见性 | allowlist + 硬注入 | `SubagentMode` + 定义层过滤 + 执行层 denial 双路径 |
| Task nudge 注入 | attachment 附在 tool_result 同轮 | TextBlock 附加到 tool_turn_msg.content（同轮） |
| Task nudge 重置 | 任意 Task 工具 | 同上 |
| Task nudge 覆盖路径 | 单一 loop | streaming + non-streaming 两条路径 |

---

*设计文档作者：Claude Sonnet 4.6*
*v2：整合 code review 修正（2026-04-14）*
*基于 Claude Code `main` 分支源码分析*
