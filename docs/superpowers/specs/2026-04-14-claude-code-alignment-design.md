# Bourbon ↔ Claude Code 对齐设计：并发工具执行 + 任务管理

**日期**：2026-04-14  
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

### 1.1 `Tool.is_concurrency_safe` 方法

在 `Tool` dataclass（`src/bourbon/tools/__init__.py`）上新增 `_concurrent_fn` callable 字段，对外暴露为 `is_concurrency_safe(input) -> bool` 方法。

**默认值**：`lambda _: False`（fail-closed，与 Claude Code 一致）

```python
@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: ToolHandler
    risk_level: RiskLevel = RiskLevel.LOW
    risk_patterns: list[str] | None = None
    required_capabilities: list[str] | None = None
    aliases: list[str] = field(default_factory=list)
    always_load: bool = True
    # 新增：并发安全标记，默认 False（fail-closed）
    _concurrent_fn: Callable[[dict], bool] = field(
        default=lambda _: False, repr=False
    )

    def is_concurrency_safe(self, tool_input: dict) -> bool:
        """判断此工具调用是否可与其他工具并行执行。

        镜像 Claude Code Tool.isConcurrencySafe(input)。
        默认 False（fail-closed）：未明确标注的工具都串行执行。
        """
        try:
            return bool(self._concurrent_fn(tool_input))
        except Exception:
            return False
```

**`register_tool` 装饰器**新增 `concurrent` 参数：

```python
def register_tool(
    name: str,
    description: str,
    input_schema: dict[str, Any],
    risk_level: RiskLevel = RiskLevel.LOW,
    concurrent: Callable[[dict], bool] | bool = False,  # 新增
    ...
) -> Callable:
    ...
    # bool 简写支持：concurrent=True → lambda _: True
    if isinstance(concurrent, bool):
        concurrent_fn = lambda _: concurrent
    else:
        concurrent_fn = concurrent
```

**各工具的标注**（镜像 Claude Code）：

| 工具 | concurrent 值 | 说明 |
|------|--------------|------|
| `agent` (AgentTool) | `lambda _: True` | 始终可并行，镜像 CC |
| `read` | `lambda _: True` | 只读，天然安全 |
| `glob` / `grep` / `search` | `lambda _: True` | 只读 |
| `bash` | `lambda inp: _is_readonly_bash(inp)` | 动态判断，镜像 CC BashTool |
| `write` / `edit` | `False`（默认） | 写操作，串行 |
| Task 工具 | `False`（默认） | 状态变更，串行 |
| skill | `False`（默认） | 串行 |

`_is_readonly_bash` 判断逻辑：检测常见只读命令前缀（`ls`、`cat`、`grep`、`find`、`echo` 等），命中则返回 `True`。

### 1.2 `ToolExecutionQueue` 类

新建文件 `src/bourbon/tools/execution_queue.py`，镜像 Claude Code `StreamingToolExecutor`。

**核心数据结构：**

```python
class ToolStatus(Enum):
    QUEUED = "queued"
    EXECUTING = "executing"
    COMPLETED = "completed"

@dataclass
class TrackedTool:
    block: dict           # 原始 tool_use block
    tool: Tool
    concurrent: bool      # is_concurrency_safe 的结果（入队时计算一次）
    status: ToolStatus = ToolStatus.QUEUED
    result: dict | None = None
    future: Future | None = None
```

**队列逻辑（完全镜像 Claude Code）：**

```python
class ToolExecutionQueue:
    MAX_CONCURRENT_WORKERS = 10  # 镜像 CC AsyncExecutor 默认值

    def _can_execute(self, concurrent: bool) -> bool:
        """镜像 StreamingToolExecutor.canExecuteTool()"""
        executing = [t for t in self._tools if t.status == ToolStatus.EXECUTING]
        return (
            len(executing) == 0
            or (concurrent and all(t.concurrent for t in executing))
        )

    def _process_queue(self) -> None:
        """镜像 StreamingToolExecutor.processQueue()"""
        for tool in self._tools:
            if tool.status != ToolStatus.QUEUED:
                continue
            if self._can_execute(tool.concurrent):
                self._start_tool(tool)
            elif not tool.concurrent:
                # 非并发工具阻塞后续，等待完成后递归继续
                if tool.future:
                    tool.future.result()
                tool.status = ToolStatus.COMPLETED
                self._process_queue()
                return
```

**并发执行**：concurrent 工具提交到 `ThreadPoolExecutor`（10 workers），完成后通过 `done_callback` 触发 `_process_queue`。串行工具在当前线程阻塞执行。

**`execute_all()` 返回有序结果**：等待所有 future 完成，按原始 `tool_use_blocks` 顺序返回 `tool_result` 列表。

### 1.3 `_execute_tools` 改造

`Agent._execute_tools` 改造为使用 `ToolExecutionQueue`。

**改造边界**：
- denial 检查、permission 检查、`_suspend_tool_round` 仍在入队前处理（与现在一致）
- 通过所有检查的工具才进入队列
- `on_tool_start` / `on_tool_end` 回调在队列内部调用

```python
def _execute_tools(self, tool_use_blocks, *, source_assistant_uuid):
    queue = ToolExecutionQueue(
        execute_fn=self._execute_single_tool,
        on_tool_start=self.on_tool_start,
        on_tool_end=self.on_tool_end,
    )

    for index, block in enumerate(tool_use_blocks):
        tool_name = block.get("name", "")
        tool_input = block.get("input", {})

        # denial / permission 检查不变（仍串行、仍可中断）
        denial = self._subagent_tool_denial(tool_name)
        if denial is not None:
            queue.add_result(block, denial, is_error=True)
            continue

        permission = self._permission_decision_for_tool(tool_name, tool_input)
        if permission.action == PermissionAction.ASK:
            self._suspend_tool_round(...)
            return queue.get_completed_results()

        tool = self._registry.get(tool_name)
        queue.add(block, tool)

    return queue.execute_all()
```

---

## 特性二：Subagent 工具可见性

### 2.1 `SubagentMode` 枚举

在 `src/bourbon/subagent/types.py` 新增：

```python
class SubagentMode(Enum):
    NORMAL = "normal"
    # in-process teammate：强制注入 Task V2 工具
    # 镜像 CC inProcessRunner.ts:982-995
    TEAMMATE = "teammate"
    # 纯执行型 async subagent：剥离 Task 工具
    # 镜像 CC ASYNC_AGENT_ALLOWED_TOOLS 排除 Task V2
    ASYNC = "async"
```

### 2.2 `Agent._tool_definitions()` 过滤

```python
TASK_V2_TOOLS = frozenset({"TaskCreate", "TaskUpdate", "TaskList", "TaskGet"})

def _tool_definitions(self) -> list[dict]:
    tools = self._registry.definitions()

    if self.subagent_mode == SubagentMode.TEAMMATE:
        # 强制保证 Task V2 工具可见
        present = {t["name"] for t in tools}
        missing = TASK_V2_TOOLS - present
        if missing:
            tools = tools + [
                self._registry.get(name).to_definition()
                for name in missing
                if self._registry.get(name)
            ]

    elif self.subagent_mode == SubagentMode.ASYNC:
        # 剥离 Task 工具
        tools = [t for t in tools if t["name"] not in TASK_V2_TOOLS]

    return tools
```

### 2.3 `spawn()` 传入 mode

在 `SubagentManager.spawn()` 中，根据调用参数决定 mode：

```python
def spawn(self, ..., agent_type: str, run_in_background: bool) -> ...:
    if agent_type == "teammate":
        mode = SubagentMode.TEAMMATE
    elif run_in_background:
        mode = SubagentMode.ASYNC
    else:
        mode = SubagentMode.NORMAL

    run = SubagentRun(..., subagent_mode=mode)
    ...
```

**与 Claude Code 对齐关系：**

| Claude Code | bourbon |
|-------------|---------|
| `inProcessRunner.ts:982` 硬注入 Task V2 | `SubagentMode.TEAMMATE` 确保工具存在 |
| `ASYNC_AGENT_ALLOWED_TOOLS` 白名单排除 Task V2 | `SubagentMode.ASYNC` 剥离 Task 工具 |
| 主线程/sync subagent 跟随 session 开关 | `SubagentMode.NORMAL` 继承父 agent |

---

## 特性三：Task Nudge 机制

### 3.1 计数器追踪

在 `Agent._run_conversation_loop()` 中新增计数器：

```python
TASK_NUDGE_THRESHOLD = 10  # 镜像 CC TODO_REMINDER_CONFIG.TURNS_SINCE_WRITE

def _run_conversation_loop(self) -> str:
    tool_round = 0
    rounds_without_task = 0   # 新增

    while tool_round < self._max_tool_rounds:
        # ... LLM call ...

        # 检查本轮是否有 task 操作
        used_task_tool = any(
            b.get("name") in TASK_V2_TOOLS
            for b in tool_use_blocks
        )
        if used_task_tool:
            rounds_without_task = 0
        elif has_tool_calls:
            rounds_without_task += 1

        # 超阈值注入 nudge（仅当有 pending 任务时）
        if rounds_without_task >= TASK_NUDGE_THRESHOLD:
            self._inject_task_reminder()
            rounds_without_task = 0  # 重置，避免每轮都注入

        # ... 工具执行、结果追加 ...
```

### 3.2 Nudge 注入

```python
def _inject_task_reminder(self) -> None:
    """注入 task_reminder，镜像 CC attachments.ts task_reminder attachment。"""
    if not hasattr(self, '_task_service') or self._task_service is None:
        return

    tasks = self._task_service.list_tasks()
    pending = [t for t in tasks if t.status.value != "completed"]
    if not pending:
        return   # 无 pending 任务时不提醒（镜像 CC 的 brief mode 跳过逻辑）

    lines = "\n".join(
        f"- [{t.status.value}] {t.subject}"
        + (f" (blocked by: {', '.join(t.blocked_by)})" if t.blocked_by else "")
        for t in pending
    )
    reminder = (
        f"You have {len(pending)} pending task(s). "
        "Please update their status with TaskUpdate, "
        "or use TaskCreate if new work is needed.\n\n"
        f"{lines}"
    )
    self.session.add_message(TranscriptMessage(
        role=MessageRole.USER,
        content=[TextBlock(text=f"<task_reminder>\n{reminder}\n</task_reminder>")],
    ))
```

**与 Claude Code 对齐：**

| Claude Code | bourbon |
|-------------|---------|
| `TODO_REMINDER_CONFIG.TURNS_SINCE_WRITE = 10` | `TASK_NUDGE_THRESHOLD = 10` |
| `task_reminder` attachment 注入 context | `<task_reminder>` block 注入 session |
| 跳过 brief mode / ant users | 跳过无 pending 任务的情况 |
| 注入后重置计数 | 同上 |

---

## 变更文件清单

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `src/bourbon/tools/__init__.py` | 修改 | `Tool` 增加 `_concurrent_fn` 字段和 `is_concurrency_safe()` 方法；`register_tool` 增加 `concurrent` 参数 |
| `src/bourbon/tools/execution_queue.py` | **新建** | `ToolExecutionQueue` + `TrackedTool` + `ToolStatus` |
| `src/bourbon/tools/base.py` | 修改 | `bash`/`read`/`glob`/`grep`/`search` 标注 `concurrent` |
| `src/bourbon/tools/agent_tool.py` | 修改 | AgentTool 标注 `concurrent=lambda _: True` |
| `src/bourbon/agent.py` | 修改 | `_execute_tools` 改用队列；`_run_conversation_loop` 增加 task nudge 计数；新增 `_inject_task_reminder()` |
| `src/bourbon/subagent/types.py` | 修改 | 新增 `SubagentMode` 枚举 |
| `src/bourbon/subagent/manager.py` | 修改 | `spawn()` 根据 `agent_type`/`run_in_background` 决定 `SubagentMode` |
| `tests/test_tool_execution_queue.py` | **新建** | 队列并发逻辑单测（concurrent batch、串行阻塞、混合场景） |
| `tests/test_subagent_tool_visibility.py` | **新建** | teammate/async 工具过滤验证 |
| `tests/test_task_nudge.py` | **新建** | nudge 阈值触发、重置、无 pending 时跳过 |

---

## 设计原则对照

| 维度 | Claude Code | bourbon 本次对齐 |
|------|-------------|----------------|
| `isConcurrencySafe` | interface 方法覆写 | dataclass callable 字段 + 方法 |
| 执行队列 | 异步流式 `StreamingToolExecutor` | 同步 `ToolExecutionQueue` + ThreadPoolExecutor |
| Subagent 工具可见性 | allowlist 常量 + 硬注入 | `SubagentMode` 枚举 + `_tool_definitions` 过滤 |
| Task nudge 阈值 | `TODO_REMINDER_CONFIG.TURNS_SINCE_WRITE = 10` | `TASK_NUDGE_THRESHOLD = 10` |
| Nudge 注入方式 | attachment 渲染 | session message 注入 |

---

*设计文档作者：Claude Sonnet 4.6*  
*基于 Claude Code `main` 分支源码分析*
