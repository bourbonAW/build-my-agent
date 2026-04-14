# Bourbon ↔ Claude Code 对齐设计：并发工具执行 + 任务管理

**日期**：2026-04-14（v3，已整合第二轮 code review 修正）
**范围**：三个特性的对齐实现
1. 并发工具执行（`ToolExecutionQueue` + `concurrent_safe_for`）
2. Subagent 工具可见性（`SubagentMode` 区分 teammate / async）
3. Task Nudge 机制（10 轮阈值注入 `task_reminder`）

---

## 背景

Claude Code 采用 **LLM-centric** 设计哲学：LLM 是唯一的 orchestrator，系统模块只提供原子性辅助。bourbon 作为对齐 Claude Code 设计的学习项目，本次需要补齐三个关键机制：

- **并发工具执行**：Claude Code 的 `StreamingToolExecutor` 允许多个 `isConcurrencySafe=true` 的工具在同一轮内并行执行。bourbon 目前是串行 for loop。
- **Subagent 工具可见性**：Claude Code 区分 in-process teammate（强制注入 Task V2 工具）和普通 async subagent（剥离 Task 工具）。
- **Task Nudge**：Claude Code 在 LLM 超过 10 轮未操作任务时注入 `task_reminder`。

---

## 特性一：并发工具执行

### 1.1 `Tool` dataclass 扩展（保持向后兼容）

**现状**：`Tool` 已有 `is_concurrency_safe: bool = False` 字段，测试直接断言 `tool.is_concurrency_safe is True/False`，不能改为 callable。

**做法**：保留 `is_concurrency_safe: bool` 不变，**新增** `_concurrency_fn: Callable[[dict], bool] | None` 私有字段，新增公开方法 `concurrent_safe_for(input) -> bool`：

```python
@dataclass
class Tool:
    name: str
    # ... 所有现有字段不变 ...
    is_concurrency_safe: bool = False           # 保持不变，向后兼容
    # 新增：动态判断的 callable（优先于 bool 字段）
    _concurrency_fn: Callable[[dict], bool] | None = field(default=None, repr=False)

    def concurrent_safe_for(self, tool_input: dict) -> bool:
        """判断此次调用是否可与其他工具并行。

        镜像 Claude Code Tool.isConcurrencySafe(input)。
        优先使用 _concurrency_fn（支持动态判断），其次回退到 is_concurrency_safe bool。
        """
        if self._concurrency_fn is not None:
            try:
                return bool(self._concurrency_fn(tool_input))
            except Exception:
                return False
        return self.is_concurrency_safe
```

**`register_tool` 装饰器**新增 `concurrency_fn` 参数（不与现有 `is_concurrency_safe: bool` 冲突）：

```python
def register_tool(
    name: str,
    ...,
    is_concurrency_safe: bool = False,           # 保持不变
    concurrency_fn: Callable[[dict], bool] | None = None,  # 新增
) -> Callable:
    ...
    Tool(..., is_concurrency_safe=is_concurrency_safe, _concurrency_fn=concurrency_fn)
```

**各工具标注**：

| 工具 | is_concurrency_safe | concurrency_fn | 说明 |
|------|---------------------|----------------|------|
| `agent` (AgentTool) | `True` | 无 | 始终可并行 |
| `read` | `True` | 无 | 只读 |
| `glob` / `grep` / `search` | `True` | 无 | 只读 |
| `bash` | `False` | `_is_readonly_bash` | 动态判断 |
| `write` / `edit` / Task 工具 | `False` | 无 | 串行 |

**`_is_readonly_bash(input: dict) -> bool`**：保守白名单，仅以下命令前缀视为安全（无重定向、无管道到写命令）：`ls`、`cat`、`grep`、`find`（不含 `-delete`/`-exec rm`）、`echo`（不含 `>`）、`pwd`、`wc`、`head`、`tail`、`stat`、`diff`、`sort`、`uniq`。其余一律返回 `False`。

### 1.2 `ToolExecutionQueue` 类

新建 `src/bourbon/tools/execution_queue.py`。

**结果顺序保证**：每个 `TrackedTool` 持有 `original_index`，`execute_all()` 按原始索引排序返回。

```python
@dataclass
class TrackedTool:
    block: dict
    tool: Tool
    concurrent: bool
    original_index: int                    # 对应 tool_use_blocks 的原始位置
    status: ToolStatus = ToolStatus.QUEUED
    result: dict | None = None             # 完整 tool_result dict
    future: Future | None = None
```

**execute_fn 协议**：`execute_fn(block: dict) -> str`（调用 `_execute_regular_tool` 的返回值）。`ToolExecutionQueue` 内部负责包装成 `tool_result` dict：

```python
def _run_tool(self, tool: TrackedTool) -> None:
    raw_output = self._execute_fn(tool.block)   # str
    tool.result = {
        "type": "tool_result",
        "tool_use_id": tool.block.get("id", ""),
        "content": str(raw_output)[:50000],
    }
    with self._lock:
        tool.status = ToolStatus.COMPLETED
```

**队列逻辑（核心，镜像 StreamingToolExecutor）：**

```python
class ToolExecutionQueue:
    MAX_CONCURRENT_WORKERS = 10

    def __init__(self, execute_fn: Callable[[dict], str], ...):
        self._tools: list[TrackedTool] = []
        self._lock = threading.Lock()
        self._thread_pool = ThreadPoolExecutor(
            max_workers=self.MAX_CONCURRENT_WORKERS,
            thread_name_prefix="tool_queue_"
        )
        self._execute_fn = execute_fn

    def add(self, block: dict, tool: Tool, index: int) -> None:
        concurrent = tool.concurrent_safe_for(block.get("input", {}))
        tracked = TrackedTool(block=block, tool=tool, concurrent=concurrent,
                              original_index=index)
        with self._lock:
            self._tools.append(tracked)

    def execute_all(self) -> list[dict]:
        """执行所有工具，按 original_index 排序返回结果。"""
        self._process_queue()
        self._wait_all()
        with self._lock:
            sorted_tools = sorted(self._tools, key=lambda t: t.original_index)
            return [t.result for t in sorted_tools]

    def _can_execute(self, concurrent: bool) -> bool:
        """调用前须持有 _lock。镜像 StreamingToolExecutor.canExecuteTool()"""
        executing = [t for t in self._tools if t.status == ToolStatus.EXECUTING]
        return (
            len(executing) == 0
            or (concurrent and all(t.concurrent for t in executing))
        )

    def _process_queue(self) -> None:
        with self._lock:
            for tool in self._tools:
                if tool.status != ToolStatus.QUEUED:
                    continue
                if self._can_execute(tool.concurrent):
                    self._start_tool_locked(tool)
                elif not tool.concurrent:
                    # 串行工具被 concurrent 工具阻塞：保持 QUEUED
                    # done_callback 完成后会再次触发 _process_queue
                    break

    def _start_tool_locked(self, tool: TrackedTool) -> None:
        """须在 _lock 内调用。"""
        tool.status = ToolStatus.EXECUTING
        tool.future = self._thread_pool.submit(self._run_tool, tool)
        if tool.concurrent:
            tool.future.add_done_callback(lambda _: self._on_tool_done(tool))

    def _run_tool(self, tool: TrackedTool) -> None:
        raw_output = self._execute_fn(tool.block)
        tool.result = {
            "type": "tool_result",
            "tool_use_id": tool.block.get("id", ""),
            "content": str(raw_output)[:50000],
        }
        with self._lock:
            tool.status = ToolStatus.COMPLETED

    def _on_tool_done(self, tool: TrackedTool) -> None:
        self._process_queue()

    def _wait_all(self) -> None:
        """等待所有 future 完成；处理 concurrent 完成后解锁的串行工具。"""
        while True:
            with self._lock:
                pending = [t for t in self._tools
                           if t.future is not None and t.status != ToolStatus.COMPLETED]
            if not pending:
                break
            for t in pending:
                t.future.result()
            self._process_queue()

    def shutdown(self) -> None:
        self._thread_pool.shutdown(wait=True)
```

### 1.3 `_execute_tools` 改造（保持结果顺序）

denial / compress / permission-deny 的结果通过 `original_index` 对应的 slot 保序，不再先 append 再 extend。

```python
def _execute_tools(self, tool_use_blocks, *, source_assistant_uuid):
    n = len(tool_use_blocks)
    results = [None] * n    # 按原始索引预分配 slot
    manual_compact = False

    queue = ToolExecutionQueue(
        execute_fn=lambda block: self._execute_regular_tool(
            block.get("name", ""), block.get("input", {}), skip_policy_check=True
        ),
    )

    for index, block in enumerate(tool_use_blocks):
        tool_name = block.get("name", "")
        tool_input = block.get("input", {})
        tool_id = block.get("id", "")

        # denial
        denial = self._subagent_tool_denial(tool_name)
        if denial is not None:
            results[index] = {"type": "tool_result", "tool_use_id": tool_id,
                              "content": str(denial)[:50000], "is_error": True}
            continue

        # compress
        if tool_name == "compress":
            manual_compact = True
            results[index] = {"type": "tool_result", "tool_use_id": tool_id,
                              "content": "Compressing context..."}
            continue

        # permission
        permission = self._permission_decision_for_tool(tool_name, tool_input)
        if permission.action == PermissionAction.DENY:
            results[index] = {"type": "tool_result", "tool_use_id": tool_id,
                              "content": f"Denied: {permission.reason}"}
            continue
        if permission.action == PermissionAction.ASK:
            # suspend：把已确认的 results（去 None）和剩余 blocks 交给 suspend 逻辑
            completed = [r for r in results if r is not None]
            self._suspend_tool_round(
                source_assistant_uuid=source_assistant_uuid,
                tool_use_blocks=tool_use_blocks,
                completed_results=completed,
                next_tool_index=index,
                request=build_permission_request(...),
            )
            if self.on_tool_end:
                self.on_tool_end(tool_name, "Requires permission")
            return completed

        # 入队
        tool = get_tool_with_metadata(tool_name)
        if tool:
            queue.add(block, tool, index)
        else:
            results[index] = {"type": "tool_result", "tool_use_id": tool_id,
                              "content": f"Unknown tool: {tool_name}", "is_error": True}

    # 执行队列，结果已按 original_index 排序
    for queued_result in queue.execute_all():
        # 找到对应 slot（通过 tool_use_id 匹配）
        for i, block in enumerate(tool_use_blocks):
            if block.get("id") == queued_result.get("tool_use_id"):
                results[i] = queued_result
                break

    if manual_compact:
        self._manual_compact()

    return [r for r in results if r is not None]
```

---

## 特性二：Subagent 工具可见性

### 2.1 `SubagentMode` 枚举

在 `src/bourbon/subagent/types.py` 新增：

```python
class SubagentMode(Enum):
    NORMAL = "normal"
    TEAMMATE = "teammate"
    ASYNC = "async"
```

### 2.2 `Agent` 初始化新增 `subagent_mode`

在 `Agent.__init__` 中新增：

```python
self.subagent_mode: SubagentMode = SubagentMode.NORMAL
```

在子 agent 创建路径（`_create_subagent` 或等效位置）中：

```python
child_agent.subagent_mode = mode   # 由 spawn() 传入
```

### 2.3 `AGENT_TYPE_CONFIGS` 新增 "teammate"

在 `src/bourbon/subagent/tools.py`：

```python
"teammate": AgentDefinition(
    agent_type="teammate",
    description="In-process teammate for task claiming and parallel execution",
    allowed_tools=None,
    max_turns=100,
),
```

### 2.4 `ToolFilter` 扩展（保留全局禁用逻辑）

`ALL_AGENT_DISALLOWED_TOOLS`（`Agent`、`TodoWrite`、`compress`）在任何 SubagentMode 下都必须优先拒绝：

```python
class ToolFilter:
    def is_allowed(self, tool_name: str, agent_def: AgentDefinition,
                   subagent_mode: SubagentMode | None = None) -> bool:
        # 全局禁用（优先级最高，任何 mode 下都不例外）
        if tool_name in ALL_AGENT_DISALLOWED_TOOLS:
            return False

        if tool_name in agent_def.disallowed_tools:
            return False

        # SubagentMode 覆盖（在 allowed_tools 白名单检查之前）
        if subagent_mode == SubagentMode.ASYNC and tool_name in TASK_V2_TOOLS:
            return False
        if subagent_mode == SubagentMode.TEAMMATE and tool_name in TASK_V2_TOOLS:
            return True   # 绕过 allowed_tools 白名单，强制允许

        if agent_def.allowed_tools is not None:
            return tool_name in agent_def.allowed_tools
        return True
```

`_subagent_tool_denial()` 调用 `ToolFilter.is_allowed()` 时传入 `self.subagent_mode`。

### 2.5 `_tool_definitions()` 同步过滤

现有 `_tool_definitions()` 已调用 `filter_engine.filter_tools(tool_defs, agent_def)`，扩展为传入 subagent_mode：

```python
filtered_tools = filter_engine.filter_tools(tool_defs, agent_def,
                                            subagent_mode=self.subagent_mode)
```

**TEAMMATE 额外注入**：`filter_tools` 内对 TEAMMATE mode 确保 Task V2 工具在结果中出现（从全量 `definitions()` 补充）。这样无需 `tool.to_definition()`。

### 2.6 `agent_tool.py` schema enum 更新

在 `src/bourbon/tools/agent_tool.py` 的 input_schema 中新增 "teammate"：

```python
"enum": ["default", "coder", "explore", "plan", "quick_task", "teammate"],
```

### 2.7 `spawn()` 决定 mode

```python
def spawn(self, ..., agent_type: str, run_in_background: bool):
    if agent_type == "teammate":
        mode = SubagentMode.TEAMMATE
    elif run_in_background:
        mode = SubagentMode.ASYNC
    else:
        mode = SubagentMode.NORMAL
```

---

## 特性三：Task Nudge 机制

### 3.1 注入位置：附加到 tool_turn_msg.content

不能注入为独立 USER message（破坏 tool_use → tool_result 配对协议）。正确做法：构建 `tool_turn_msg` 后，将 reminder TextBlock 附加到同一条 user message 的 content：

```python
tool_results = self._execute_tools(tool_use_blocks, ...)
tool_turn_msg = self._build_tool_results_transcript_message(tool_results, assistant_msg.uuid)

if rounds_without_task >= TASK_NUDGE_THRESHOLD:
    reminder = self._build_task_reminder_block()
    if reminder is not None:
        tool_turn_msg.content.append(reminder)
        rounds_without_task = 0

self.session.add_message(tool_turn_msg)
```

### 3.2 计数器（两条 loop 路径都加）

`_run_conversation_loop` 和 `_run_conversation_loop_stream` 各自维护 `rounds_without_task` 局部变量：

```python
TASK_NUDGE_THRESHOLD = 10  # 镜像 CC TODO_REMINDER_CONFIG.TURNS_SINCE_WRITE

# 每轮检查
used_task_tool = any(b.get("name") in TASK_V2_TOOLS for b in tool_use_blocks)
if used_task_tool:
    rounds_without_task = 0
elif has_tool_calls:
    rounds_without_task += 1
```

**重置条件**：任意 Task V2 工具调用（TaskCreate/Update/List/Get）均重置，不区分读写。

### 3.3 `_build_task_reminder_block()`

```python
TASK_V2_TOOLS = frozenset({"TaskCreate", "TaskUpdate", "TaskList", "TaskGet"})

def _build_task_reminder_block(self) -> TextBlock | None:
    """构建 task_reminder，无 pending 任务时返回 None。

    镜像 CC attachments.ts task_reminder attachment。
    """
    from bourbon.tasks.service import TaskService
    from bourbon.tasks.store import TaskStore

    storage_dir = Path(self.config.tasks.storage_dir).expanduser()
    service = TaskService(TaskStore(storage_dir))

    # task_list_id 解析与 task_tools._resolve_task_list_id 保持一致
    # （优先 config.tasks.default_list_id，否则 "default"）
    tasks_cfg = getattr(self.config, "tasks", None)
    task_list_id = str(getattr(tasks_cfg, "default_list_id", None) or "default")

    tasks = service.list_tasks(task_list_id)
    # TaskRecord.status 是 str（非 Enum），直接比较字符串
    pending = [t for t in tasks if t.status != "completed"]
    if not pending:
        return None

    lines = "\n".join(
        f"- [{t.status}] {t.subject}"
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

---

## 变更文件清单

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `src/bourbon/tools/__init__.py` | 修改 | `Tool` 新增 `_concurrency_fn` 字段和 `concurrent_safe_for()` 方法；`register_tool` 新增 `concurrency_fn` 参数（不改 `is_concurrency_safe: bool`） |
| `src/bourbon/tools/execution_queue.py` | **新建** | `ToolExecutionQueue`（带 Lock + original_index 排序 + execute_fn 返回 str 内部包装 dict） |
| `src/bourbon/tools/base.py` | 修改 | `bash` 标注 `concurrency_fn=_is_readonly_bash`；`read`/`glob`/`grep`/`search` 标注 `is_concurrency_safe=True` |
| `src/bourbon/tools/agent_tool.py` | 修改 | AgentTool 标注 `is_concurrency_safe=True`；schema enum 新增 "teammate" |
| `src/bourbon/agent.py` | 修改 | `__init__` 新增 `self.subagent_mode = SubagentMode.NORMAL`；`_execute_tools` 改用 `ToolExecutionQueue` + 索引 slot 保序；`_run_conversation_loop` 和 `_run_conversation_loop_stream` 增加 nudge 计数；新增 `_build_task_reminder_block()` |
| `src/bourbon/subagent/types.py` | 修改 | 新增 `SubagentMode` 枚举 |
| `src/bourbon/subagent/tools.py` | 修改 | `AGENT_TYPE_CONFIGS` 新增 "teammate"；`ToolFilter.is_allowed()` 接受 `subagent_mode` 参数，保留 `ALL_AGENT_DISALLOWED_TOOLS` 最高优先级；`filter_tools()` 同步传递 mode |
| `src/bourbon/subagent/manager.py` | 修改 | `spawn()` 根据 `agent_type`/`run_in_background` 决定 `SubagentMode`；子 agent 创建时写入 `child_agent.subagent_mode` |
| `tests/test_tool_execution_queue.py` | **新建** | 队列并发 + serial 阻塞等待 + 顺序保证 + 线程安全 |
| `tests/test_subagent_tool_visibility.py` | **新建** | teammate/async 工具过滤双路径（definitions + denial） |
| `tests/test_task_nudge.py` | **新建** | nudge 阈值 + 重置 + 无 pending 跳过 + 附加到 tool_turn_msg |

---

## 设计原则对照

| 维度 | Claude Code | bourbon v3 |
|------|-------------|------------|
| `isConcurrencySafe` | interface 方法，动态 | `concurrent_safe_for(input)` 方法，`_concurrency_fn` 优先，bool 回退 |
| 现有 bool 字段 | 无对应 | `is_concurrency_safe: bool` 保持不变（向后兼容） |
| 执行队列 | 异步流式 `StreamingToolExecutor` | 同步 `ToolExecutionQueue` + ThreadPoolExecutor + Lock |
| 结果顺序 | streaming 按 id 追踪 | `original_index` slot + execute_all() 排序 |
| Subagent 工具可见性 | allowlist + 硬注入 | `SubagentMode` + `ToolFilter` 双路径（全局禁用优先） |
| Task nudge 注入 | attachment 附 tool_result 同轮 | TextBlock 附加到 tool_turn_msg.content |
| task_list_id 解析 | env/teamName/session 链 | 等价简化：config.tasks.default_list_id or "default" |
| TaskRecord.status | — | `str`（非 Enum），直接字符串比较 |

---

*设计文档作者：Claude Sonnet 4.6*
*v3：整合第二轮 code review 修正（2026-04-14）*
*基于 Claude Code `main` 分支源码分析*
