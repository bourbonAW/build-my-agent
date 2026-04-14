# Bourbon ↔ Claude Code 对齐设计：并发工具执行 + 任务管理

**日期**：2026-04-14（v4，已整合第三轮 code review 修正）
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

**现状**：`Tool` 已有 `is_concurrency_safe: bool = False`，测试直接断言 bool 值，不能改为 callable。

**做法**：保留 `is_concurrency_safe: bool` 不变，**新增** `_concurrency_fn` 私有字段，新增 `concurrent_safe_for(input) -> bool` 方法：

```python
@dataclass
class Tool:
    # 所有现有字段不变
    is_concurrency_safe: bool = False
    _concurrency_fn: Callable[[dict], bool] | None = field(default=None, repr=False)

    def concurrent_safe_for(self, tool_input: dict) -> bool:
        """动态判断此次调用是否可并行。_concurrency_fn 优先，否则回退到 bool 字段。"""
        if self._concurrency_fn is not None:
            try:
                return bool(self._concurrency_fn(tool_input))
            except Exception:
                return False
        return self.is_concurrency_safe
```

**`register_tool`** 新增 `concurrency_fn` 参数，不修改现有 `is_concurrency_safe: bool`。

**各工具标注**：

| 工具 | is_concurrency_safe | concurrency_fn |
|------|---------------------|----------------|
| `agent` | `True` | 无 |
| `read` / `glob` / `grep` / `search` | `True` | 无 |
| `bash` | `False` | `_is_readonly_bash`（见下文） |
| `write` / `edit` / Task 工具 | `False` | 无 |

**`_is_readonly_bash(input: dict) -> bool`**：

两阶段判断，两者均通过才返回 `True`：

1. **Shell 控制符检测（优先）**：命令字符串含 `;`、`|`、`&&`、`||`、`>`、`>>`、`<`、`$()`、反引号，直接返回 `False`（shell=True 下这些可组合任意副作用）。
2. **前缀白名单**：通过第一阶段后，检查命令以安全前缀开头：`ls`、`cat`、`grep`、`find`（不含 `-delete`/`-exec`）、`echo`、`pwd`、`wc`、`head`、`tail`、`stat`、`diff`、`sort`、`uniq`。

### 1.2 `ToolExecutionQueue` 类

新建 `src/bourbon/tools/execution_queue.py`。

**设计要点**：
- `execute_fn(block: dict) -> str`（返回字符串），queue 内部包装为完整 `tool_result` dict
- `original_index` 保证结果顺序与 `tool_use_blocks` 一致
- `on_tool_start` / `on_tool_end` 回调在队列内部调用，保持 REPL 活动显示
- `threading.Lock` 保护 `_tools` 读写
- `execute_all()` 结束时自动 `shutdown()` 线程池（no leak）

```python
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
        self._lock = threading.Lock()
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
        """执行所有工具，按 original_index 排序返回结果，最后关闭线程池。"""
        try:
            self._process_queue()
            self._wait_all()
            with self._lock:
                return [t.result for t in sorted(self._tools, key=lambda t: t.original_index)]
        finally:
            self._thread_pool.shutdown(wait=True)

    def _can_execute(self, concurrent: bool) -> bool:
        """须在 _lock 内调用。镜像 StreamingToolExecutor.canExecuteTool()"""
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
                    # done_callback 唤醒后再执行
                    break

    def _start_tool_locked(self, tool: TrackedTool) -> None:
        """须在 _lock 内调用。"""
        tool.status = ToolStatus.EXECUTING
        tool.future = self._thread_pool.submit(self._run_tool, tool)
        if tool.concurrent:
            tool.future.add_done_callback(lambda _: self._on_tool_done(tool))

    def _run_tool(self, tool: TrackedTool) -> None:
        name = tool.block.get("name", "")
        inp = tool.block.get("input", {})
        if self._on_tool_start:
            self._on_tool_start(name, inp)
        raw_output = self._execute_fn(tool.block)
        tool.result = {
            "type": "tool_result",
            "tool_use_id": tool.block.get("id", ""),
            "content": str(raw_output)[:50000],
        }
        if self._on_tool_end:
            self._on_tool_end(name, raw_output)
        with self._lock:
            tool.status = ToolStatus.COMPLETED

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

**关键约束**：当 permission=ASK 触发 suspend 时，必须先 flush 队列中已入队的工具，再把完整结果传给 `_suspend_tool_round`，否则 resume 时这些工具的 `tool_result` 永久丢失。

```python
def _execute_tools(self, tool_use_blocks, *, source_assistant_uuid):
    n = len(tool_use_blocks)
    results = [None] * n        # 按原始索引预分配 slot
    manual_compact = False

    queue = ToolExecutionQueue(
        execute_fn=lambda block: self._execute_regular_tool(
            block.get("name", ""), block.get("input", {}), skip_policy_check=True
        ),
        on_tool_start=self.on_tool_start,
        on_tool_end=self.on_tool_end,
    )

    suspend_index = None
    suspend_request = None

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
            # 先 flush 已入队的工具，保证 suspend 时 results 完整
            for i, r in enumerate(queue.execute_all()):
                tool_id_q = tool_use_blocks[i].get("id") if i < n else None
                # 找到对应 slot 填入
                for j, b in enumerate(tool_use_blocks):
                    if b.get("id") == r.get("tool_use_id") and results[j] is None:
                        results[j] = r
                        break
            completed = [r for r in results if r is not None]
            self._suspend_tool_round(
                source_assistant_uuid=source_assistant_uuid,
                tool_use_blocks=tool_use_blocks,
                completed_results=completed,
                next_tool_index=index,
                request=build_permission_request(
                    tool_name=tool_name, tool_input=tool_input,
                    tool_use_id=tool_id, decision=permission, workdir=self.workdir,
                ),
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

    # 执行队列，结果按 original_index 排序
    for r in queue.execute_all():
        for j, b in enumerate(tool_use_blocks):
            if b.get("id") == r.get("tool_use_id") and results[j] is None:
                results[j] = r
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

### 2.2 `SubagentRun` 携带 `subagent_mode`

在 `SubagentRun` dataclass（`src/bourbon/subagent/types.py`）新增字段：

```python
@dataclass
class SubagentRun:
    # ... 现有字段 ...
    subagent_mode: SubagentMode = SubagentMode.NORMAL  # 新增
```

`spawn()` 计算 mode 并写入 run：

```python
def spawn(self, ..., agent_type: str, run_in_background: bool):
    if agent_type == "teammate":
        mode = SubagentMode.TEAMMATE
    elif run_in_background:
        mode = SubagentMode.ASYNC
    else:
        mode = SubagentMode.NORMAL

    run = SubagentRun(..., subagent_mode=mode)
```

`_create_subagent()` 从 `run` 取 mode 写入子 agent：

```python
def _create_subagent(self, run: SubagentRun, agent_def, agent_factory):
    ...
    subagent = Agent(...)
    subagent.subagent_mode = run.subagent_mode   # 新增
    subagent._subagent_agent_def = agent_def
    subagent._subagent_tool_filter = ToolFilter()
    ...
```

`Agent.__init__` 新增默认值：

```python
self.subagent_mode: SubagentMode = SubagentMode.NORMAL
```

### 2.3 Teammate 任务列表隔离问题

**问题**：`_resolve_task_list_id` 优先用 `agent.session.session_id`。subagent 有独立 session，teammate 将看到一个空的子 session 任务列表，无法访问父 agent 的工作任务。

**解决**：`spawn()` 在创建 `SubagentRun` 时，将父 agent 的 task_list_id 带入 run，`_create_subagent()` 将其写入子 agent 的 config：

```python
# spawn() 中
parent_task_list_id = None
if mode == SubagentMode.TEAMMATE:
    parent_session = getattr(self.parent_agent, "session", None)
    parent_task_list_id = getattr(parent_session, "session_id", None)

run = SubagentRun(..., subagent_mode=mode, parent_task_list_id=parent_task_list_id)
```

```python
# _create_subagent() 中，TEAMMATE 模式
if run.subagent_mode == SubagentMode.TEAMMATE and run.parent_task_list_id:
    subagent.config.tasks.default_list_id = run.parent_task_list_id
```

这样 teammate 的 Task 工具调用 `_resolve_task_list_id` 时，会命中 `config.tasks.default_list_id`，指向父 agent 的任务列表。

### 2.4 `AGENT_TYPE_CONFIGS` 新增 "teammate"

```python
"teammate": AgentDefinition(
    agent_type="teammate",
    description="In-process teammate for task claiming and parallel execution",
    allowed_tools=None,
    max_turns=100,
),
```

### 2.5 `ToolFilter` 扩展（保留全局禁用优先级）

```python
TASK_V2_TOOLS = frozenset({"TaskCreate", "TaskUpdate", "TaskList", "TaskGet"})

class ToolFilter:
    def is_allowed(self, tool_name: str, agent_def: AgentDefinition,
                   subagent_mode: SubagentMode | None = None) -> bool:
        # 全局禁用（最高优先，任何 mode 下均不例外）
        if tool_name in ALL_AGENT_DISALLOWED_TOOLS:
            return False
        if tool_name in agent_def.disallowed_tools:
            return False

        # SubagentMode 覆盖（在 allowed_tools 白名单之前）
        if subagent_mode == SubagentMode.ASYNC and tool_name in TASK_V2_TOOLS:
            return False
        if subagent_mode == SubagentMode.TEAMMATE and tool_name in TASK_V2_TOOLS:
            return True  # 绕过白名单，强制允许

        if agent_def.allowed_tools is not None:
            return tool_name in agent_def.allowed_tools
        return True
```

### 2.6 `agent_tool.py` schema enum 新增 "teammate"

```python
"enum": ["default", "coder", "explore", "plan", "quick_task", "teammate"],
```

---

## 特性三：Task Nudge 机制

### 3.1 注入位置：附加到 tool_turn_msg.content

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

两条 loop 路径（`_run_conversation_loop` 和 `_run_conversation_loop_stream`）都加此逻辑。

### 3.2 计数器

```python
TASK_NUDGE_THRESHOLD = 10

used_task_tool = any(b.get("name") in TASK_V2_TOOLS for b in tool_use_blocks)
if used_task_tool:
    rounds_without_task = 0
elif has_tool_calls:
    rounds_without_task += 1
```

### 3.3 `_build_task_reminder_block()`

**task_list_id 使用 `session.session_id`**，与 `_resolve_task_list_id` 的优先顺序完全对齐：

```python
def _build_task_reminder_block(self) -> TextBlock | None:
    from bourbon.tasks.service import TaskService
    from bourbon.tasks.store import TaskStore

    storage_dir = Path(self.config.tasks.storage_dir).expanduser()
    service = TaskService(TaskStore(storage_dir))

    # 与 _resolve_task_list_id 优先顺序对齐：session_id > config.default_list_id > "default"
    session_id = getattr(getattr(self, "session", None), "session_id", None)
    tasks_cfg = getattr(self.config, "tasks", None)
    default_list_id = getattr(tasks_cfg, "default_list_id", None)
    task_list_id = str(session_id or default_list_id or "default")

    tasks = service.list_tasks(task_list_id)
    # TaskRecord.status 是 str（非 Enum）
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
| `src/bourbon/tools/__init__.py` | 修改 | `Tool` 新增 `_concurrency_fn` + `concurrent_safe_for()`；`register_tool` 新增 `concurrency_fn` |
| `src/bourbon/tools/execution_queue.py` | **新建** | `ToolExecutionQueue`：Lock + original_index 排序 + callbacks + finally shutdown |
| `src/bourbon/tools/base.py` | 修改 | `bash` 标注 `concurrency_fn=_is_readonly_bash`（两阶段：控制符检测 + 前缀白名单）；`read`/`glob`/`grep`/`search` 标注 `is_concurrency_safe=True` |
| `src/bourbon/tools/agent_tool.py` | 修改 | AgentTool `is_concurrency_safe=True`；schema enum 新增 "teammate" |
| `src/bourbon/agent.py` | 修改 | `__init__` 新增 `subagent_mode`；`_execute_tools` 改用队列（suspend 前先 flush）；两条 loop 增加 nudge 计数；新增 `_build_task_reminder_block()` |
| `src/bourbon/subagent/types.py` | 修改 | 新增 `SubagentMode`；`SubagentRun` 新增 `subagent_mode` 和 `parent_task_list_id` 字段 |
| `src/bourbon/subagent/tools.py` | 修改 | `AGENT_TYPE_CONFIGS` 新增 "teammate"；`ToolFilter.is_allowed()` 接受 `subagent_mode`，保留 `ALL_AGENT_DISALLOWED_TOOLS` 最高优先 |
| `src/bourbon/subagent/manager.py` | 修改 | `spawn()` 计算 mode 写入 `run.subagent_mode`，TEAMMATE 时记录 `parent_task_list_id`；`_create_subagent()` 从 run 读取 mode 写入 `subagent.subagent_mode` 和 config |
| `tests/test_tool_execution_queue.py` | **新建** | 并发 batch + serial 阻塞等待 + 顺序保证 + callback 调用 + 线程池 shutdown |
| `tests/test_subagent_tool_visibility.py` | **新建** | teammate/async 工具过滤双路径 + task_list_id 继承 |
| `tests/test_task_nudge.py` | **新建** | nudge 阈值 + 重置 + 无 pending 跳过 + session_id 路由 |

---

## 设计原则对照

| 维度 | Claude Code | bourbon v4 |
|------|-------------|------------|
| `isConcurrencySafe` | interface 方法 | `concurrent_safe_for()` + `_concurrency_fn` |
| bool 字段向后兼容 | — | `is_concurrency_safe: bool` 不变 |
| 执行队列 | 异步流式 | 同步 + ThreadPoolExecutor + Lock + finally shutdown |
| suspend 保序 | streaming id 追踪 | suspend 前 flush 队列 |
| SubagentMode 传递 | run 对象携带 | `SubagentRun.subagent_mode` |
| Teammate task list | parent session | `parent_task_list_id` → `config.tasks.default_list_id` |
| Task nudge task_list_id | session-based | `session.session_id > config > "default"` |
| 全局禁用工具 | 常量集合 | `ALL_AGENT_DISALLOWED_TOOLS` 最高优先（任何 mode） |
| bash 并发安全判断 | `isReadOnly` | 两阶段：控制符检测 + 前缀白名单 |

---

*设计文档作者：Claude Sonnet 4.6*
*v4：整合第三轮 code review 修正（2026-04-14）*
*基于 Claude Code `main` 分支源码分析*
