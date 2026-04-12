# Bourbon Task/Todo Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align Bourbon's work-tracking model with Claude Code's split between lightweight in-memory todos and persistent workflow tasks, while keeping runtime subagent jobs separate from workflow task management.

**Architecture:** Keep `src/bourbon/todos.py` as Bourbon's Todo V1 layer, but fix the current behavior and tool-contract mismatches first. Introduce a new file-backed `src/bourbon/tasks/` package for Task V2 workflow management with `TaskCreate`/`TaskUpdate`/`TaskList`/`TaskGet` tools and REPL support. Reserve runtime background/subagent state for `subagent` job management and move its user-facing commands away from `/tasks` so the workflow task vocabulary stays clean.

**Tech Stack:** Python 3.11+, existing Bourbon Agent/REPL/ToolRegistry/Session systems, JSON storage under `~/.bourbon/tasks/`, POSIX file locking helper, pytest.

**References:**
- `wiki/claude-code-task-todo-architecture.md`
- `docs/specs/2026-03-19-bourbon-design.md`
- `docs/superpowers/specs/2026-04-09-bourbon-subagent-design.md`

---

## Gap Summary

1. Bourbon currently matches only part of Claude Code's Todo V1:
   - `content/status/activeForm`
   - max 20 items
   - only one `in_progress`
2. Bourbon does **not** yet match Claude Todo V1 semantics in two important ways:
   - `TodoWrite` is not a first-class registered tool
   - all-completed todo lists are not cleared automatically
3. Bourbon has **no** Claude-style Task V2 equivalent yet:
   - no persistent task files
   - no task IDs
   - no owner field
   - no `blocks/blockedBy`
   - no create/update/list/get tool family
4. Bourbon's current subagent design uses `/task-*` for runtime jobs, but Claude's architecture uses `Task` for workflow management and a different runtime `TaskState` concept. Those names should not be merged.

## Scope Boundaries

This plan intentionally covers three tightly related but distinct layers:

1. **Todo V1 compatibility**
   - fast, in-memory, single-agent checklist
   - `TodoWrite`
2. **Task V2 workflow management**
   - persistent, file-backed, owner/dependency aware tasks
   - `TaskCreate` / `TaskUpdate` / `TaskList` / `TaskGet`
3. **Runtime jobs**
   - background bash, subagents, monitors
   - belongs under `subagent` or a future `runs`/`jobs` surface

Out of scope for this plan:

- mailbox notifications for assigned tasks
- task lifecycle hooks
- remote teammate coordination
- verification-agent nudges
- replacing the subagent runtime registry with the workflow task store

---

## File Structure

```
src/bourbon/
├── todos.py                      # Legacy Todo V1 semantics
├── config.py                     # Add workflow-task storage config
├── agent.py                      # Inject agent into ToolContext; remove TodoWrite special path
├── repl.py                       # /todos and /tasks workflow commands
├── prompt/sections.py            # Prompt guidance for TodoWrite vs Task* tools
├── tools/
│   ├── __init__.py               # ToolContext.agent + lazy imports
│   ├── todo_tool.py              # Register TodoWrite as a real tool
│   └── task_tools.py             # TaskCreate/TaskUpdate/TaskList/TaskGet
└── tasks/
    ├── __init__.py               # Public task API exports
    ├── types.py                  # TaskRecord + status definitions
    ├── list_id.py                # Resolve task list scope from session/agent
    ├── locking.py                # .lock helper for cross-process safety
    ├── store.py                  # JSON persistence + .highwatermark
    └── service.py                # Business rules (dependencies, owner, cleanup)

tests/
├── test_todos.py
├── test_todo_tool.py
├── test_tasks_types.py
├── test_tasks_store.py
├── test_tasks_service.py
├── test_task_tools.py
├── test_repl_tasks.py
└── test_task_todo_integration.py

docs/
├── specs/2026-03-19-bourbon-design.md
└── superpowers/
    ├── specs/2026-04-09-bourbon-subagent-design.md
    ├── plans/2026-04-09-bourbon-subagent-implementation.md
    └── guides/task-v2-usage.md
```

---

## Chunk 1: Fix Todo V1 Semantics

### Task 1: Align `TodoManager` with Claude Todo V1 Behavior

**Files:**
- Modify: `src/bourbon/todos.py`
- Modify: `tests/test_todos.py`

- [ ] **Step 1: Write failing tests for missing V1 semantics**

```python
def test_all_completed_items_clear_the_list():
    manager = TodoManager()
    result = manager.update(
        [
            {"content": "Done", "status": "completed"},
        ]
    )
    assert manager.items == []
    assert result == "No todos."


def test_active_form_only_required_for_in_progress():
    manager = TodoManager()
    manager.update(
        [
            {"content": "Queued", "status": "pending"},
            {"content": "Done", "status": "completed"},
        ]
    )
    assert len(manager.items) == 2


def test_in_progress_item_still_requires_active_form():
    manager = TodoManager()
    with pytest.raises(ValueError, match="activeForm required for in_progress"):
        manager.update(
            [
                {"content": "Running", "status": "in_progress"},
            ]
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_todos.py -v`
Expected: FAIL because `TodoManager.update()` still requires `activeForm` for all statuses and does not clear all-completed lists.

- [ ] **Step 3: Implement the minimal behavior change**

```python
class TodoManager:
    def update(self, items: list[dict]) -> str:
        validated: list[TodoItem] = []
        in_progress_count = 0

        for i, item in enumerate(items):
            content = str(item.get("content", "")).strip()
            status = str(item.get("status", "pending")).lower()
            active_form = str(item.get("activeForm", "")).strip()

            if not content:
                raise ValueError(f"Item {i}: content required")
            if status not in self.VALID_STATUSES:
                raise ValueError(f"Item {i}: invalid status '{status}'")
            if status == "in_progress" and not active_form:
                raise ValueError(f"Item {i}: activeForm required for in_progress")

            if status == "in_progress":
                in_progress_count += 1

            validated.append(
                TodoItem(content=content, status=status, active_form=active_form)
            )

        if len(validated) > self.MAX_TODOS:
            raise ValueError(f"Max {self.MAX_TODOS} todos")
        if in_progress_count > 1:
            raise ValueError("Only one in_progress allowed")

        all_done = validated and all(item.status == "completed" for item in validated)
        self.items = [] if all_done else validated
        return self.render()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_todos.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/bourbon/todos.py tests/test_todos.py
git commit -m "fix(todos): align todo manager with legacy Claude semantics"
```

---

## Chunk 2: Make `TodoWrite` a First-Class Tool

### Task 2: Register `TodoWrite` and Remove the Hidden Special Case

**Files:**
- Create: `src/bourbon/tools/todo_tool.py`
- Modify: `src/bourbon/tools/__init__.py`
- Modify: `src/bourbon/agent.py`
- Create: `tests/test_todo_tool.py`

- [ ] **Step 1: Write failing tests for tool registration and execution**

```python
from pathlib import Path
from types import SimpleNamespace

from bourbon.todos import TodoManager
from bourbon.tools import ToolContext, definitions, get_registry


def test_todowrite_appears_in_tool_definitions():
    tool_names = {tool["name"] for tool in definitions()}
    assert "TodoWrite" in tool_names


def test_todowrite_updates_agent_todos():
    agent = SimpleNamespace(todos=TodoManager())
    ctx = ToolContext(workdir=Path("."), agent=agent)

    output = get_registry().call(
        "TodoWrite",
        {
            "items": [
                {"content": "Task 1", "status": "in_progress", "activeForm": "working"},
            ]
        },
        ctx,
    )

    assert "[>] Task 1 <- working" in output
    assert agent.todos.has_open_items() is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_todo_tool.py -v`
Expected: FAIL because `TodoWrite` is not registered and `ToolContext` has no `agent`.

- [ ] **Step 3: Extend `ToolContext` and register the tool**

```python
@dataclass
class ToolContext:
    workdir: Path
    skill_manager: Any | None = None
    on_tools_discovered: Callable[[set[str]], None] | None = None
    agent: Any | None = None


@register_tool(
    name="TodoWrite",
    description="Replace the current in-memory todo list for this agent.",
    input_schema={
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string"},
                        "status": {"type": "string"},
                        "activeForm": {"type": "string"},
                    },
                    "required": ["content", "status"],
                },
            },
        },
        "required": ["items"],
    },
    risk_level=RiskLevel.LOW,
)
def todo_write_handler(items: list[dict], *, ctx: ToolContext) -> str:
    if ctx.agent is None or getattr(ctx.agent, "todos", None) is None:
        return "Error: TodoWrite requires an agent with an attached TodoManager"
    return ctx.agent.todos.update(items)
```

- [ ] **Step 4: Route `TodoWrite` through the registry like other normal tools**

In `src/bourbon/agent.py`, remove the dedicated `elif tool_name == "TodoWrite"` branch and let `TodoWrite` flow through `_execute_regular_tool()` using the injected `agent=self` context from `_make_tool_context()`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_todo_tool.py -v`
Expected: PASS

- [ ] **Step 6: Run targeted agent integration tests**

Run: `uv run pytest tests/test_prompt_agent_integration.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/bourbon/tools/todo_tool.py src/bourbon/tools/__init__.py src/bourbon/agent.py tests/test_todo_tool.py
git commit -m "feat(tools): register TodoWrite as a first-class tool"
```

---

## Chunk 3: Introduce Task V2 Storage and Types

### Task 3: Build Persistent Workflow Task Models and Storage

**Files:**
- Create: `src/bourbon/tasks/__init__.py`
- Create: `src/bourbon/tasks/types.py`
- Create: `src/bourbon/tasks/list_id.py`
- Create: `src/bourbon/tasks/locking.py`
- Create: `src/bourbon/tasks/store.py`
- Modify: `src/bourbon/config.py`
- Create: `tests/test_tasks_types.py`
- Create: `tests/test_tasks_store.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Write failing tests for task persistence**

```python
def test_task_record_serializes_dependencies():
    task = TaskRecord(
        id="1",
        subject="Write tests",
        description="Add missing coverage",
        blocked_by=["2"],
        blocks=["3"],
        owner="main-agent",
    )
    assert task.to_dict()["blockedBy"] == ["2"]
    assert task.to_dict()["blocks"] == ["3"]


def test_store_allocates_incrementing_ids(tmp_path):
    store = TaskStore(base_dir=tmp_path)
    first = store.create(
        "session-1",
        TaskRecord(id="", subject="A", description="desc"),
    )
    second = store.create(
        "session-1",
        TaskRecord(id="", subject="B", description="desc"),
    )
    assert first == "1"
    assert second == "2"


def test_config_roundtrip_includes_task_settings():
    config = Config.from_dict({"tasks": {"storage_dir": "~/.bourbon/tasks", "enabled": True}})
    assert config.tasks.enabled is True
    assert config.to_dict()["tasks"]["storage_dir"] == "~/.bourbon/tasks"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tasks_types.py tests/test_tasks_store.py tests/test_config.py -v`
Expected: FAIL with import errors and missing `tasks` config.

- [ ] **Step 3: Implement task datatypes and config**

```python
@dataclass(slots=True)
class TaskRecord:
    id: str
    subject: str
    description: str
    status: str = "pending"
    active_form: str | None = None
    owner: str | None = None
    blocks: list[str] = field(default_factory=list)
    blocked_by: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "subject": self.subject,
            "description": self.description,
            "status": self.status,
            "activeForm": self.active_form,
            "owner": self.owner,
            "blocks": self.blocks,
            "blockedBy": self.blocked_by,
            "metadata": self.metadata,
        }
```

- [ ] **Step 4: Implement file-backed storage**

Use a layout compatible with the Claude document:

```text
~/.bourbon/tasks/<task_list_id>/
├── 1.json
├── 2.json
├── .highwatermark
└── .lock
```

`TaskStore` responsibilities:

- create task list directory on demand
- allocate numeric string IDs under lock
- write individual task JSON files
- list tasks by reading `*.json`
- update existing tasks atomically under the same lock
- delete tasks when `status == "deleted"`

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_tasks_types.py tests/test_tasks_store.py tests/test_config.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/bourbon/tasks/__init__.py src/bourbon/tasks/types.py src/bourbon/tasks/list_id.py src/bourbon/tasks/locking.py src/bourbon/tasks/store.py src/bourbon/config.py tests/test_tasks_types.py tests/test_tasks_store.py tests/test_config.py
git commit -m "feat(tasks): add file-backed task storage and config"
```

---

## Chunk 4: Add Task V2 Service Rules and Tools

### Task 4: Implement Workflow Task Operations

**Files:**
- Create: `src/bourbon/tasks/service.py`
- Create: `src/bourbon/tools/task_tools.py`
- Modify: `src/bourbon/tools/__init__.py`
- Create: `tests/test_tasks_service.py`
- Create: `tests/test_task_tools.py`

- [ ] **Step 1: Write failing tests for create/update/list/get behavior**

```python
def test_update_task_adds_bidirectional_block_edges(tmp_path):
    service = TaskService(TaskStore(base_dir=tmp_path))
    a = service.create_task("session-1", subject="A", description="desc")
    b = service.create_task("session-1", subject="B", description="desc")

    service.update_task("session-1", a.id, add_blocks=[b.id])
    a_after = service.get_task("session-1", a.id)
    b_after = service.get_task("session-1", b.id)

    assert b.id in a_after.blocks
    assert a.id in b_after.blocked_by


def test_list_tasks_hides_completed_blockers(tmp_path):
    service = TaskService(TaskStore(base_dir=tmp_path))
    blocker = service.create_task("session-1", subject="Tests", description="desc")
    target = service.create_task("session-1", subject="Deploy", description="desc")
    service.update_task("session-1", target.id, add_blocked_by=[blocker.id])
    service.update_task("session-1", blocker.id, status="completed")

    listed = service.list_tasks("session-1")
    deploy = next(task for task in listed if task.id == target.id)
    assert deploy.blocked_by == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_tasks_service.py tests/test_task_tools.py -v`
Expected: FAIL with import errors.

- [ ] **Step 3: Implement service rules**

`TaskService` should provide:

- `create_task(task_list_id, subject, description, active_form=None, metadata=None)`
- `update_task(task_list_id, task_id, ...)`
- `get_task(task_list_id, task_id)`
- `list_tasks(task_list_id)`
- `claim_task(task_list_id, task_id, owner)`

Important rules:

- `add_blocks` updates both `blocks` and the peer's `blocked_by`
- `add_blocked_by` updates both `blocked_by` and the peer's `blocks`
- completed tasks should not show up as active blockers in `list_tasks()`
- `status="deleted"` should physically remove the JSON file
- ownership should be stored, but task assignment notifications remain out of scope

- [ ] **Step 4: Register Claude-style task tools**

```python
@register_tool(name="TaskCreate", ...)
def task_create_handler(..., *, ctx: ToolContext) -> str: ...


@register_tool(name="TaskUpdate", ...)
def task_update_handler(..., *, ctx: ToolContext) -> str: ...


@register_tool(name="TaskList", ...)
def task_list_handler(*, ctx: ToolContext) -> str: ...


@register_tool(name="TaskGet", ...)
def task_get_handler(task_id: str, *, ctx: ToolContext) -> str: ...
```

Resolve `task_list_id` from the current agent session by default:

```python
def get_task_list_id(ctx: ToolContext) -> str:
    if ctx.agent is not None and getattr(ctx.agent, "session", None) is not None:
        return str(ctx.agent.session.session_id)
    return "default"
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_tasks_service.py tests/test_task_tools.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/bourbon/tasks/service.py src/bourbon/tools/task_tools.py src/bourbon/tools/__init__.py tests/test_tasks_service.py tests/test_task_tools.py
git commit -m "feat(tasks): add workflow task service and tools"
```

---

## Chunk 5: Migrate REPL and Prompt Surfaces

### Task 5: Give Workflow Tasks and Legacy Todos Separate User-Facing Commands

**Files:**
- Modify: `src/bourbon/repl.py`
- Modify: `src/bourbon/prompt/sections.py`
- Modify: `tests/test_prompt_sections.py`
- Create: `tests/test_repl_tasks.py`

- [ ] **Step 1: Write failing tests for command routing**

```python
def test_tasks_command_shows_workflow_tasks(...):
    ...
    assert "/tasks" in REPL.COMMANDS
    assert "/todos" in REPL.COMMANDS


def test_task_guidelines_mentions_both_todo_and_tasks():
    assert "TodoWrite" in TASK_GUIDELINES.content
    assert "TaskCreate" in TASK_GUIDELINES.content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_repl_tasks.py tests/test_prompt_sections.py -v`
Expected: FAIL because `/todos` does not exist and prompt text does not mention Task V2.

- [ ] **Step 3: Update REPL command semantics**

Target REPL surface:

```text
/todos   -> legacy in-memory Todo V1
/tasks   -> persistent workflow Task V2 list
/task <id> or /task-show <id> -> detailed workflow task output
```

Do **not** use `/tasks` for subagent runtime jobs.

- [ ] **Step 4: Update prompt guidance**

Replace the single Todo-only instruction with guidance like:

```python
TASK_GUIDELINES = PromptSection(
    ...,
    content=(
        "When working on a short, single-agent, in-memory checklist, use TodoWrite.\n\n"
        "When work needs persistence, ownership, or dependency tracking, use TaskCreate, "
        "TaskUpdate, TaskList, and TaskGet.\n\n"
        ...
    ),
)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_repl_tasks.py tests/test_prompt_sections.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/bourbon/repl.py src/bourbon/prompt/sections.py tests/test_prompt_sections.py tests/test_repl_tasks.py
git commit -m "feat(repl): split workflow tasks from legacy todos"
```

---

## Chunk 6: Protect the Subagent Boundary and Add End-to-End Coverage

### Task 6: Keep Runtime Jobs Separate from Workflow Tasks

**Files:**
- Modify: `docs/specs/2026-03-19-bourbon-design.md`
- Modify: `docs/superpowers/specs/2026-04-09-bourbon-subagent-design.md`
- Modify: `docs/superpowers/plans/2026-04-09-bourbon-subagent-implementation.md`
- Create: `tests/test_task_todo_integration.py`
- Create: `docs/superpowers/guides/task-v2-usage.md`

- [ ] **Step 1: Write failing integration tests**

```python
def test_todowrite_is_not_persistent_but_taskcreate_is(...):
    ...


def test_completed_workflow_tasks_do_not_clear_runtime_job_state(...):
    ...
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_task_todo_integration.py -v`
Expected: FAIL until both Todo V1 and Task V2 layers exist together.

- [ ] **Step 3: Update docs and naming**

Documentation rules after this task:

- `TodoWrite` = legacy in-memory checklist
- `Task*` = persistent workflow task management
- `subagent` registry = runtime jobs
- future subagent REPL commands should move to `/runs`, `/run-show`, `/run-stop` or equivalent

Update the subagent design/implementation docs so they stop reserving `/task-*` for runtime jobs.

- [ ] **Step 4: Write a user guide**

Create `docs/superpowers/guides/task-v2-usage.md` with:

- when to use todos vs tasks
- how persistence works
- how ownership/dependencies work
- why runtime jobs are not workflow tasks

- [ ] **Step 5: Run the full focused test suite**

Run:

```bash
uv run pytest tests/test_todos.py tests/test_todo_tool.py tests/test_tasks_types.py tests/test_tasks_store.py tests/test_tasks_service.py tests/test_task_tools.py tests/test_repl_tasks.py tests/test_task_todo_integration.py -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add docs/specs/2026-03-19-bourbon-design.md docs/superpowers/specs/2026-04-09-bourbon-subagent-design.md docs/superpowers/plans/2026-04-09-bourbon-subagent-implementation.md docs/superpowers/guides/task-v2-usage.md tests/test_task_todo_integration.py
git commit -m "docs(tasks): separate workflow tasks from runtime subagent jobs"
```

---

## Execution Notes

1. Land Chunk 1 and Chunk 2 before touching Task V2. That fixes the current broken `TodoWrite` contract and reduces ambiguity in prompt behavior.
2. Land Chunk 3 and Chunk 4 together in one short branch if possible. File-backed storage without tools is hard to validate from the agent surface.
3. Land Chunk 5 before resuming subagent implementation work. Otherwise `/tasks` naming will continue to drift.
4. Land Chunk 6 before exposing workflow tasks to subagents. The user model must be unambiguous first.

## Success Criteria

- `TodoWrite` is a real registered tool and no longer relies on a hidden special-case path.
- all-completed todo lists collapse to `No todos.` just like Claude Todo V1.
- Bourbon gains a persistent Task V2 layer with `TaskCreate`, `TaskUpdate`, `TaskList`, and `TaskGet`.
- `/todos` and `/tasks` refer to different concepts and stay that way.
- runtime subagent/background jobs no longer compete with workflow task naming.
