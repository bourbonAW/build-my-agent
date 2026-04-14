# Bourbon ↔ Claude Code 对齐设计：并发工具执行 + 任务管理

**日期**：2026-04-14（v5，已整合第四轮 code review 修正）
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

`register_tool` 新增 `concurrency_fn` 参数，不改 `is_concurrency_safe: bool`。

**各工具标注**：

| 工具 | is_concurrency_safe | concurrency_fn |
|------|---------------------|----------------|
| `agent` / `read` / `glob` / `grep` / `search` | `True` | 无 |
| `bash` | `False` | `_is_readonly_bash`（两阶段） |
| 其余 | `False` | 无 |

**`_is_readonly_bash(input: dict) -> bool`** — 两阶段，均通过才返回 `True`：

1. **Shell 控制符检测（优先）**：命令字符串含以下任一字符/序列时立即返回 `False`（`shell=True` 下均可组合副作用）：
   `;`、`|`、`&&`、`||`、`>`、`>>`、`<`、`$()`、反引号（`` ` ``）、换行（`\n`）、单独 `&`（后台执行）。

2. **前缀白名单**：通过第一阶段后，检查命令以下列前缀开头：`ls`、`cat`、`grep`、`find`（不含 `-delete`/`-exec`）、`echo`、`pwd`、`wc`、`head`、`tail`、`stat`、`diff`、`sort`、`uniq`。否则返回 `False`。

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
        with self._lock:
            for tool in self._tools:
                if tool.status != ToolStatus.QUEUED:
                    continue
                if self._can_execute(tool.concurrent):
                    self._start_tool_locked(tool)
                elif not tool.concurrent:
                    break   # 串行工具被阻塞：保持 QUEUED，等 done_callback 唤醒

    def _start_tool_locked(self, tool: TrackedTool) -> None:
        # 须在 _lock 内调用
        tool.status = ToolStatus.EXECUTING
        tool.future = self._thread_pool.submit(self._run_tool, tool)
        if tool.concurrent:
            tool.future.add_done_callback(lambda _: self._on_tool_done(tool))

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
def _execute_tools(self, tool_use_blocks, *, source_assistant_uuid):
    n = len(tool_use_blocks)
    results = [None] * n    # 按原始索引预分配 slot
    manual_compact = False

    queue = ToolExecutionQueue(
        execute_fn=lambda block: self._execute_regular_tool(
            block.get("name", ""), block.get("input", {}), skip_policy_check=True
        ),
        on_tool_start=self.on_tool_start,
        on_tool_end=self.on_tool_end,
    )

    def _fill_queue_results():
        """将 queue 结果按 tool_use_id 填入 results slots。"""
        for r in queue.execute_all():
            uid = r.get("tool_use_id")
            for j, b in enumerate(tool_use_blocks):
                if b.get("id") == uid and results[j] is None:
                    results[j] = r
                    break

    for index, block in enumerate(tool_use_blocks):
        tool_name = block.get("name", "")
        tool_input = block.get("input", {})
        tool_id = block.get("id", "")

        # on_tool_start 对所有路径统一调用
        if self.on_tool_start:
            self.on_tool_start(tool_name, tool_input)

        # denial
        denial = self._subagent_tool_denial(tool_name)
        if denial is not None:
            results[index] = {"type": "tool_result", "tool_use_id": tool_id,
                              "content": str(denial)[:50000], "is_error": True}
            if self.on_tool_end:
                self.on_tool_end(tool_name, str(denial))
            continue

        # compress
        if tool_name == "compress":
            manual_compact = True
            results[index] = {"type": "tool_result", "tool_use_id": tool_id,
                              "content": "Compressing context..."}
            if self.on_tool_end:
                self.on_tool_end(tool_name, "Compressing context...")
            continue

        # permission
        permission = self._permission_decision_for_tool(tool_name, tool_input)
        if permission.action == PermissionAction.DENY:
            msg = f"Denied: {permission.reason}"
            results[index] = {"type": "tool_result", "tool_use_id": tool_id,
                              "content": msg}
            if self.on_tool_end:
                self.on_tool_end(tool_name, msg)
            continue
        if permission.action == PermissionAction.ASK:
            # suspend 前先 flush 队列，保证已入队工具结果完整
            _fill_queue_results()
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

        # 入队（callbacks 由 queue 内部在 worker thread 中调用，故这里不再重复 start/end）
        # 注意：on_tool_start 已在循环顶部调用过，queue 内部不再重复 start
        tool_obj = get_tool_with_metadata(tool_name)
        if tool_obj:
            # 把 callbacks 交给 queue 处理，避免重复调用
            # 传 None 给 queue，因为 start 已调用，end 由 queue 负责
            queue.add(block, tool_obj, index)
        else:
            msg = f"Unknown tool: {tool_name}"
            results[index] = {"type": "tool_result", "tool_use_id": tool_id,
                              "content": msg, "is_error": True}
            if self.on_tool_end:
                self.on_tool_end(tool_name, msg)

    # 执行队列
    _fill_queue_results()

    if manual_compact:
        self._manual_compact()

    return [r for r in results if r is not None]
```

**注意**：`on_tool_start` 在循环顶部统一调用（所有路径），`on_tool_end` 在各路径显式调用。对入队工具，`on_tool_start` 已在主线程调用，queue 内部 `_run_tool` 只调用 `on_tool_end`（队列创建时传 `on_tool_end=self.on_tool_end`，`on_tool_start=None`）。

---

## 特性二：Subagent 工具可见性

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

`_create_subagent()` 从 run 读取，设置到子 agent（不修改 config）：

```python
def _create_subagent(self, run, agent_def, agent_factory):
    ...
    subagent = Agent(config=self.config, ...)   # config 不改
    subagent.subagent_mode = run.subagent_mode
    if run.parent_task_list_id:
        subagent.task_list_id_override = run.parent_task_list_id
    ...
```

### 2.4 `ToolFilter` + 调用点更新

**`ToolFilter.is_allowed()`** 接受 `subagent_mode`，保留 `ALL_AGENT_DISALLOWED_TOOLS` 最高优先：

```python
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

`ToolFilter.filter_tools()` 也需同步接受并向下传递 `subagent_mode`。

### 2.5 `AGENT_TYPE_CONFIGS` + schema enum

```python
# subagent/tools.py
"teammate": AgentDefinition(
    agent_type="teammate",
    description="In-process teammate for task claiming and parallel execution",
    allowed_tools=None,
    max_turns=100,
),

# tools/agent_tool.py input_schema
"enum": ["default", "coder", "explore", "plan", "quick_task", "teammate"],
```

---

## 特性三：Task Nudge 机制

### 3.1 注入位置

附加到 `tool_turn_msg.content`，不注入独立 USER message：

```python
tool_results = self._execute_tools(tool_use_blocks, ...)
tool_turn_msg = self._build_tool_results_transcript_message(tool_results, ...)

if rounds_without_task >= TASK_NUDGE_THRESHOLD:
    reminder = self._build_task_reminder_block()
    if reminder is not None:
        tool_turn_msg.content.append(reminder)
        rounds_without_task = 0

self.session.add_message(tool_turn_msg)
```

两条 loop 路径（`_run_conversation_loop` 和 `_run_conversation_loop_stream`）都加。

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

task_list_id 与 `_resolve_task_list_id` 完全对齐（override → session_id → config → "default"）：

```python
def _build_task_reminder_block(self) -> TextBlock | None:
    from bourbon.tasks.service import TaskService
    from bourbon.tasks.store import TaskStore

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
| `src/bourbon/tools/execution_queue.py` | **新建** | 双 Lock（状态 + callback 串行化）；callback 异常隔离；finally shutdown |
| `src/bourbon/tools/base.py` | 修改 | bash 两阶段 `_is_readonly_bash`（含 `\n`/`&` 控制符）；read/glob/grep/search `is_concurrency_safe=True` |
| `src/bourbon/tools/agent_tool.py` | 修改 | `is_concurrency_safe=True`；schema enum 新增 "teammate" |
| `src/bourbon/tools/task_tools.py` | 修改 | `_resolve_task_list_id` 新增 `task_list_id_override` 最高优先检查 |
| `src/bourbon/agent.py` | 修改 | `__init__` 新增 `subagent_mode`/`task_list_id_override`；`_execute_tools` 重构（callbacks 对称 + flush on suspend）；两条 loop 增 nudge；新增 `_build_task_reminder_block()` |
| `src/bourbon/subagent/types.py` | 修改 | 新增 `SubagentMode`；`SubagentRun` 新增 `subagent_mode`/`parent_task_list_id` |
| `src/bourbon/subagent/tools.py` | 修改 | `AGENT_TYPE_CONFIGS` 新增 "teammate"；`ToolFilter` 接受 `subagent_mode`，`filter_tools` 传递 mode |
| `src/bourbon/subagent/manager.py` | 修改 | `spawn()` 计算 mode/parent_task_list_id 写入 run；`_create_subagent()` 设置 `subagent.subagent_mode`/`task_list_id_override` |
| `tests/test_tool_execution_queue.py` | **新建** | 并发 + serial 阻塞 + 顺序 + callback 串行化 + 异常隔离 + shutdown |
| `tests/test_subagent_tool_visibility.py` | **新建** | teammate/async 双路径 + task_list_id 继承 |
| `tests/test_task_nudge.py` | **新建** | 阈值 + 重置 + 无 pending 跳过 + session_id 路由 |

---

## 设计原则对照

| 维度 | Claude Code | bourbon v5 |
|------|-------------|------------|
| `isConcurrencySafe` | interface 方法 | `concurrent_safe_for()` + `_concurrency_fn` 优先 |
| bool 向后兼容 | — | `is_concurrency_safe: bool` 不变 |
| Callback 线程安全 | 单线程 async | `_callback_lock` 串行化，隔离异常 |
| Suspend 保序 | streaming id 追踪 | suspend 前 flush 队列 |
| Teammate task list | parent session | `task_list_id_override` 最高优先，不修改 config |
| SubagentMode 传递 | run 对象 | `SubagentRun.subagent_mode`，`_create_subagent()` 写入 agent |
| SubagentMode 执行层 | allowlist | `ToolFilter` 双路径均传 `subagent_mode` |
| Bash 安全判断 | `isReadOnly` | 两阶段：控制符（含 `\n`/`&`）+ 前缀白名单 |

---

*设计文档作者：Claude Sonnet 4.6*
*v5：整合第四轮 code review 修正（2026-04-14）*
*基于 Claude Code `main` 分支源码分析*
