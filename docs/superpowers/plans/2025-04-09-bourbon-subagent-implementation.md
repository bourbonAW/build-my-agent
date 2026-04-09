# Bourbon Subagent System Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the Bourbon Subagent System enabling parallel task execution, code exploration, and focused work through specialized sub-agents.

**Architecture:** A `SubagentManager` orchestrates task lifecycle, with `TaskRegistry` for state management, `AgentTypeRegistry` for tool filtering, and `AbortController` for cancellation. Supports both synchronous (blocking) and asynchronous (background) execution modes.

**Tech Stack:** Python 3.11+, ThreadPoolExecutor for async, existing Bourbon Agent/Session/Tools infrastructure.

**Reference:** [Design Spec](../specs/2025-04-09-bourbon-subagent-design.md)

---

## File Structure

```
src/bourbon/subagent/
├── __init__.py              # Public API exports
├── types.py                 # AgentDefinition, SubagentTask, ErrorCode enums
├── cancel.py                # AbortController hierarchy
├── registry.py              # TaskRegistry in-memory storage
├── tools.py                 # Tool filtering logic
├── errors.py                # Exception classes
├── result.py                # Result finalization
├── notify.py                # Notification service
├── partial_result.py        # Partial result extraction
├── cleanup.py               # Resource cleanup
├── session_adapter.py       # Subagent session isolation
├── executor.py              # AsyncExecutor thread pool
└── manager.py               # SubagentManager (main API)

src/bourbon/tools/
└── agent_tool.py            # Agent tool registration

src/bourbon/commands/
└── task_commands.py         # /task CLI commands

tests/test_subagent/
├── test_types.py
├── test_cancel.py
├── test_registry.py
├── test_tools.py
├── test_errors.py
├── test_manager.py
└── test_integration.py
```

---

## Chunk 1: Core Types and Error Handling

### Task 1: Create Error Codes and Exceptions

**Files:**
- Create: `src/bourbon/subagent/errors.py`
- Create: `src/bourbon/subagent/__init__.py`
- Test: `tests/test_subagent/test_errors.py`

- [ ] **Step 1: Write failing test for error codes**

```python
# tests/test_subagent/test_errors.py
import pytest
from bourbon.subagent.errors import SubagentErrorCode, TaskError, TaskCancelledError


def test_error_code_values():
    assert SubagentErrorCode.USER_ABORT.value == "user_abort"
    assert SubagentErrorCode.MAX_TURNS_EXCEEDED.value == "max_turns_exceeded"
    assert SubagentErrorCode.LLM_ERROR.value == "llm_error"


def test_task_error_has_code():
    error = TaskError(SubagentErrorCode.LLM_ERROR, "API failed")
    assert error.code == SubagentErrorCode.LLM_ERROR
    assert str(error) == "API failed"


def test_task_cancelled_error():
    error = TaskCancelledError("User stopped task")
    assert error.code == SubagentErrorCode.USER_ABORT
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/hf/github_project/build-my-agent
python -m pytest tests/test_subagent/test_errors.py -v
```

Expected: FAIL - Module not found

- [ ] **Step 3: Implement error codes and exceptions**

```python
# src/bourbon/subagent/errors.py
from enum import Enum


class SubagentErrorCode(Enum):
    """Standardized error codes for subagent failures."""
    USER_ABORT = "user_abort"
    MAX_TURNS_EXCEEDED = "max_turns_exceeded"
    LLM_ERROR = "llm_error"
    LLM_RETRY_EXHAUSTED = "llm_retry_exhausted"
    TOOL_PERMISSION_DENIED = "tool_permission_denied"
    TOOL_NOT_FOUND = "tool_not_found"
    SESSION_ERROR = "session_error"
    UNKNOWN_ERROR = "unknown_error"


class TaskError(Exception):
    """Base exception for subagent task failures."""
    
    def __init__(self, code: SubagentErrorCode, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class TaskCancelledError(TaskError):
    """Task was cancelled by user or parent."""
    
    def __init__(self, message: str = "Task was cancelled"):
        super().__init__(SubagentErrorCode.USER_ABORT, message)


class MaxTurnsExceededError(TaskError):
    """Task exceeded maximum number of turns."""
    
    def __init__(self, max_turns: int):
        super().__init__(
            SubagentErrorCode.MAX_TURNS_EXCEEDED,
            f"Task exceeded maximum turns ({max_turns})"
        )
        self.max_turns = max_turns
```

- [ ] **Step 4: Create subagent package init**

```python
# src/bourbon/subagent/__init__.py
"""Bourbon Subagent System - Parallel task execution and specialized agents."""

from .errors import (
    SubagentErrorCode,
    TaskError,
    TaskCancelledError,
    MaxTurnsExceededError,
)

__all__ = [
    "SubagentErrorCode",
    "TaskError",
    "TaskCancelledError",
    "MaxTurnsExceededError",
]
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
python -m pytest tests/test_subagent/test_errors.py -v
```

Expected: 3 tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/bourbon/subagent/__init__.py src/bourbon/subagent/errors.py tests/test_subagent/test_errors.py
git commit -m "feat(subagent): add error codes and exception classes

- Add SubagentErrorCode enum for standardized error handling
- Add TaskError, TaskCancelledError, MaxTurnsExceededError exceptions
- Create subagent package structure"
```

---

### Task 2: Create Core Types (AgentDefinition, SubagentTask)

**Files:**
- Create: `src/bourbon/subagent/types.py`
- Test: `tests/test_subagent/test_types.py`

- [ ] **Step 1: Write failing test for types**

```python
# tests/test_subagent/test_types.py
import pytest
from datetime import datetime
from bourbon.subagent.types import TaskStatus, AgentDefinition, SubagentTask


def test_task_status_enum():
    assert TaskStatus.PENDING.value == "pending"
    assert TaskStatus.RUNNING.value == "running"
    assert TaskStatus.COMPLETED.value == "completed"
    assert TaskStatus.FAILED.value == "failed"
    assert TaskStatus.KILLED.value == "killed"


def test_agent_definition_creation():
    agent_def = AgentDefinition(
        agent_type="coder",
        description="Code specialist",
        max_turns=100,
    )
    assert agent_def.agent_type == "coder"
    assert agent_def.max_turns == 100
    assert agent_def.allowed_tools is None  # All tools allowed


def test_agent_definition_with_allowed_tools():
    agent_def = AgentDefinition(
        agent_type="explore",
        description="Read-only explorer",
        allowed_tools=["Read", "Grep"],
    )
    assert agent_def.allowed_tools == ["Read", "Grep"]


def test_subagent_task_creation():
    task = SubagentTask(
        description="Test task",
        prompt="Do something",
        agent_type="default",
    )
    assert task.description == "Test task"
    assert task.status == TaskStatus.PENDING
    assert task.is_async is False
    assert task.tool_call_count == 0


def test_subagent_task_to_dict():
    task = SubagentTask(
        description="A very long description that should be truncated",
        prompt="Do something",
        agent_type="coder",
        status=TaskStatus.RUNNING,
    )
    d = task.to_dict()
    assert d["task_id"] == task.task_id
    assert d["agent_type"] == "coder"
    assert d["status"] == "running"
    assert "..." in d["description"]  # Should be truncated
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_subagent/test_types.py -v
```

Expected: FAIL - ImportError

- [ ] **Step 3: Implement core types**

```python
# src/bourbon/subagent/types.py
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from uuid import uuid4


class TaskStatus(Enum):
    """Task lifecycle states."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    KILLED = "killed"


@dataclass
class AgentDefinition:
    """Configuration for an agent type."""
    agent_type: str
    description: str
    allowed_tools: list[str] | None = None
    disallowed_tools: list[str] = field(default_factory=list)
    max_turns: int = 50
    model: str | None = None
    system_prompt_suffix: str | None = None
    permission_mode: str = "default"


@dataclass
class SubagentTask:
    """Runtime task instance."""
    # Identity
    task_id: str = field(default_factory=lambda: str(uuid4())[:8])
    
    # Configuration
    description: str = ""
    prompt: str = ""
    agent_type: str = "default"
    model: str | None = None
    max_turns: int = 50
    
    # State
    status: TaskStatus = field(default=TaskStatus.PENDING)
    created_at: datetime = field(default_factory=datetime.now)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    
    # Execution
    is_async: bool = False
    abort_controller: Any | None = None
    
    # Results
    result: str | None = None
    error: str | None = None
    
    # Progress
    tool_call_count: int = 0
    total_tokens: int = 0
    current_activity: str | None = None
    
    def to_dict(self) -> dict:
        """Convert to dictionary for CLI display."""
        desc = self.description
        if len(desc) > 50:
            desc = desc[:50] + "..."
        
        return {
            "task_id": self.task_id,
            "description": desc,
            "agent_type": self.agent_type,
            "status": self.status.value,
            "is_async": self.is_async,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "tool_calls": self.tool_call_count,
        }
```

- [ ] **Step 4: Update __init__.py exports**

Add to `src/bourbon/subagent/__init__.py`:

```python
from .types import (
    TaskStatus,
    AgentDefinition,
    SubagentTask,
)

__all__ = [
    # errors
    "SubagentErrorCode",
    "TaskError",
    "TaskCancelledError",
    "MaxTurnsExceededError",
    # types
    "TaskStatus",
    "AgentDefinition",
    "SubagentTask",
]
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
python -m pytest tests/test_subagent/test_types.py -v
```

Expected: 6 tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/bourbon/subagent/types.py tests/test_subagent/test_types.py src/bourbon/subagent/__init__.py
git commit -m "feat(subagent): add core types (AgentDefinition, SubagentTask)

- Add TaskStatus enum for task lifecycle states
- Add AgentDefinition for agent type configuration
- Add SubagentTask runtime task instance
- Include to_dict() for CLI display"
```

---

## Chunk 2: AbortController and Cancellation

### Task 3: Implement Hierarchical AbortController

**Files:**
- Create: `src/bourbon/subagent/cancel.py`
- Test: `tests/test_subagent/test_cancel.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_subagent/test_cancel.py
import threading
import time
import pytest
from bourbon.subagent.cancel import AbortController


def test_abort_controller_initial_state():
    controller = AbortController()
    assert controller.is_aborted() is False


def test_abort_controller_abort():
    controller = AbortController()
    controller.abort()
    assert controller.is_aborted() is True


def test_abort_controller_parent_child():
    parent = AbortController()
    child = AbortController(parent=parent)
    
    parent.abort()
    assert child.is_aborted() is True


def test_abort_controller_child_does_not_affect_parent():
    parent = AbortController()
    child = AbortController(parent=parent)
    
    child.abort()
    assert parent.is_aborted() is False
    assert child.is_aborted() is True


def test_abort_controller_grandchild():
    grandparent = AbortController()
    parent = AbortController(parent=grandparent)
    child = AbortController(parent=parent)
    
    grandparent.abort()
    assert parent.is_aborted() is True
    assert child.is_aborted() is True


def test_abort_controller_wait():
    controller = AbortController()
    
    def abort_after_delay():
        time.sleep(0.1)
        controller.abort()
    
    thread = threading.Thread(target=abort_after_delay)
    thread.start()
    
    result = controller.wait(timeout=1.0)
    assert result is True
    assert controller.is_aborted() is True


def test_abort_controller_wait_timeout():
    controller = AbortController()
    result = controller.wait(timeout=0.01)
    assert result is False
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_subagent/test_cancel.py -v
```

Expected: FAIL - ImportError

- [ ] **Step 3: Implement AbortController**

```python
# src/bourbon/subagent/cancel.py
import threading
from typing import Optional


class AbortController:
    """Hierarchical cancellation controller.
    
    Supports parent-child relationships where aborting a parent
    automatically aborts all children.
    """
    
    def __init__(self, parent: Optional['AbortController'] = None):
        self._event = threading.Event()
        self._parent = parent
        self._children: list['AbortController'] = []
        
        if parent:
            parent._add_child(self)
    
    def _add_child(self, child: 'AbortController') -> None:
        """Register a child controller."""
        self._children.append(child)
    
    def abort(self) -> None:
        """Trigger abort and cascade to all children."""
        self._event.set()
        for child in self._children:
            child.abort()
    
    def is_aborted(self) -> bool:
        """Check if this or any parent is aborted."""
        if self._event.is_set():
            return True
        if self._parent:
            return self._parent.is_aborted()
        return False
    
    def wait(self, timeout: Optional[float] = None) -> bool:
        """Wait for abort signal.
        
        Returns:
            True if abort was triggered, False if timeout
        """
        return self._event.wait(timeout)
```

- [ ] **Step 4: Update __init__.py**

Add to `src/bourbon/subagent/__init__.py`:

```python
from .cancel import AbortController

__all__ = [
    # ... existing exports ...
    "AbortController",
]
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
python -m pytest tests/test_subagent/test_cancel.py -v
```

Expected: 7 tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/bourbon/subagent/cancel.py tests/test_subagent/test_cancel.py src/bourbon/subagent/__init__.py
git commit -m "feat(subagent): add hierarchical AbortController

- Support parent-child cancellation hierarchy
- Cascade abort from parent to all children
- Thread-safe Event-based signaling
- wait() with timeout support"
```

---

## Chunk 3: Tool Filtering

### Task 4: Implement Tool Filtering System

**Files:**
- Create: `src/bourbon/subagent/tools.py`
- Modify: `src/bourbon/tools/__init__.py` (if needed)
- Test: `tests/test_subagent/test_tools.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_subagent/test_tools.py
import pytest
from bourbon.subagent.tools import (
    ALL_AGENT_DISALLOWED_TOOLS,
    AGENT_TYPE_CONFIGS,
    ToolFilter,
)
from bourbon.subagent.types import AgentDefinition


def test_global_disallowed_tools():
    assert "Agent" in ALL_AGENT_DISALLOWED_TOOLS
    assert "TodoWrite" in ALL_AGENT_DISALLOWED_TOOLS


def test_agent_type_configs_exist():
    assert "default" in AGENT_TYPE_CONFIGS
    assert "coder" in AGENT_TYPE_CONFIGS
    assert "explore" in AGENT_TYPE_CONFIGS
    assert "plan" in AGENT_TYPE_CONFIGS
    assert "quick_task" in AGENT_TYPE_CONFIGS


def test_explore_agent_restricted_tools():
    explore_def = AGENT_TYPE_CONFIGS["explore"]
    assert explore_def.allowed_tools == ["Read", "Glob", "Grep", "WebSearch", "WebFetch"]


def test_tool_filter_init():
    filter_engine = ToolFilter()
    assert filter_engine is not None


def test_tool_filter_allows_readonly_tools():
    filter_engine = ToolFilter()
    explore_def = AGENT_TYPE_CONFIGS["explore"]
    
    assert filter_engine.is_allowed("Read", explore_def) is True
    assert filter_engine.is_allowed("Grep", explore_def) is True


def test_tool_filter_blocks_write_for_explore():
    filter_engine = ToolFilter()
    explore_def = AGENT_TYPE_CONFIGS["explore"]
    
    assert filter_engine.is_allowed("Write", explore_def) is False
    assert filter_engine.is_allowed("Edit", explore_def) is False


def test_tool_filter_blocks_agent_tool():
    filter_engine = ToolFilter()
    coder_def = AGENT_TYPE_CONFIGS["coder"]
    
    # Even coder cannot use Agent tool (no recursion)
    assert filter_engine.is_allowed("Agent", coder_def) is False


def test_tool_filter_allows_all_for_coder():
    filter_engine = ToolFilter()
    coder_def = AGENT_TYPE_CONFIGS["coder"]
    
    assert filter_engine.is_allowed("Read", coder_def) is True
    assert filter_engine.is_allowed("Write", coder_def) is True
    assert filter_engine.is_allowed("Bash", coder_def) is True


def test_tool_filter_custom_disallowed():
    custom_def = AgentDefinition(
        agent_type="custom",
        description="Test",
        disallowed_tools=["Bash", "WebSearch"],
    )
    filter_engine = ToolFilter()
    
    assert filter_engine.is_allowed("Read", custom_def) is True
    assert filter_engine.is_allowed("Bash", custom_def) is False
    assert filter_engine.is_allowed("WebSearch", custom_def) is False
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_subagent/test_tools.py -v
```

Expected: FAIL - ImportError

- [ ] **Step 3: Implement tool filtering**

```python
# src/bourbon/subagent/tools.py
from .types import AgentDefinition


# Tools all subagents are forbidden from using
ALL_AGENT_DISALLOWED_TOOLS = {
    "Agent",           # No recursion
    "TodoWrite",       # Don't pollute parent todo list
    "TaskStop",        # Can't control other tasks
    "compress",        # Manual compression disabled
}


# Pre-configured agent types
AGENT_TYPE_CONFIGS: dict[str, AgentDefinition] = {
    "default": AgentDefinition(
        agent_type="default",
        description="General purpose agent for most tasks",
        max_turns=50,
    ),
    
    "coder": AgentDefinition(
        agent_type="coder",
        description="Code refactoring and implementation specialist",
        allowed_tools=None,  # All non-disallowed tools
        max_turns=100,
        system_prompt_suffix="Focus on code quality and test coverage.",
    ),
    
    "explore": AgentDefinition(
        agent_type="explore",
        description="Read-only codebase exploration",
        allowed_tools=["Read", "Glob", "Grep", "WebSearch", "WebFetch"],
        max_turns=30,
        system_prompt_suffix="You are in READ-ONLY mode. Do not modify files.",
    ),
    
    "plan": AgentDefinition(
        agent_type="plan",
        description="Architecture and design planning",
        allowed_tools=["Read", "Glob", "Grep", "WebSearch"],
        max_turns=30,
        permission_mode="plan",
    ),
    
    "quick_task": AgentDefinition(
        agent_type="quick_task",
        description="Fast execution for simple, bounded tasks",
        max_turns=20,
    ),
}


class ToolFilter:
    """Filters available tools based on agent type configuration."""
    
    def is_allowed(self, tool_name: str, agent_def: AgentDefinition) -> bool:
        """Check if a tool is allowed for the given agent type.
        
        Logic:
        1. Check global disallowed list
        2. Check agent's disallowed list
        3. Check agent's allowed list (if specified)
        """
        # Check global disallowed
        if tool_name in ALL_AGENT_DISALLOWED_TOOLS:
            return False
        
        # Check agent's disallowed list
        if tool_name in agent_def.disallowed_tools:
            return False
        
        # Check agent's allowed list (if specified)
        if agent_def.allowed_tools is not None:
            return tool_name in agent_def.allowed_tools
        
        # No restrictions specified - allow
        return True
    
    def filter_tools(
        self,
        tools: list[dict],
        agent_def: AgentDefinition,
    ) -> list[dict]:
        """Filter a list of tool definitions."""
        return [
            tool for tool in tools
            if self.is_allowed(tool["name"], agent_def)
        ]
```

- [ ] **Step 4: Update __init__.py**

Add to `src/bourbon/subagent/__init__.py`:

```python
from .tools import (
    ALL_AGENT_DISALLOWED_TOOLS,
    AGENT_TYPE_CONFIGS,
    ToolFilter,
)

__all__ = [
    # ... existing exports ...
    "ALL_AGENT_DISALLOWED_TOOLS",
    "AGENT_TYPE_CONFIGS",
    "ToolFilter",
]
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
python -m pytest tests/test_subagent/test_tools.py -v
```

Expected: 10 tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/bourbon/subagent/tools.py tests/test_subagent/test_tools.py src/bourbon/subagent/__init__.py
git commit -m "feat(subagent): add tool filtering system

- Add ALL_AGENT_DISALLOWED_TOOLS (Agent, TodoWrite, etc.)
- Add AGENT_TYPE_CONFIGS for 5 agent types (default/coder/explore/plan/quick_task)
- Add ToolFilter class for permission checking
- Support allowed_tools whitelist and disallowed_tools blacklist"
```

---

## Chunk 4: Task Registry

### Task 5: Implement TaskRegistry

**Files:**
- Create: `src/bourbon/subagent/registry.py`
- Test: `tests/test_subagent/test_registry.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_subagent/test_registry.py
import pytest
from datetime import datetime
from bourbon.subagent.registry import TaskRegistry
from bourbon.subagent.types import SubagentTask, TaskStatus


def test_registry_empty():
    registry = TaskRegistry()
    assert registry.list_all() == []
    assert registry.get("nonexistent") is None


def test_registry_register_task():
    registry = TaskRegistry()
    task = SubagentTask(description="Test", prompt="Do it")
    
    registry.register(task)
    
    assert registry.get(task.task_id) == task


def test_registry_list_all():
    registry = TaskRegistry()
    task1 = SubagentTask(description="Task 1", prompt="Do 1")
    task2 = SubagentTask(description="Task 2", prompt="Do 2")
    
    registry.register(task1)
    registry.register(task2)
    
    tasks = registry.list_all()
    assert len(tasks) == 2
    assert task1 in tasks
    assert task2 in tasks


def test_registry_list_by_status():
    registry = TaskRegistry()
    task1 = SubagentTask(description="Running", prompt="Run")
    task1.status = TaskStatus.RUNNING
    task2 = SubagentTask(description="Pending", prompt="Wait")
    task2.status = TaskStatus.PENDING
    
    registry.register(task1)
    registry.register(task2)
    
    running = registry.list_all(status=TaskStatus.RUNNING)
    assert len(running) == 1
    assert running[0].description == "Running"


def test_registry_update_status():
    registry = TaskRegistry()
    task = SubagentTask(description="Test", prompt="Do it")
    registry.register(task)
    
    registry.update_status(task.task_id, TaskStatus.RUNNING)
    
    updated = registry.get(task.task_id)
    assert updated.status == TaskStatus.RUNNING


def test_registry_complete():
    registry = TaskRegistry()
    task = SubagentTask(description="Test", prompt="Do it")
    registry.register(task)
    
    registry.complete(task.task_id, "Result content")
    
    updated = registry.get(task.task_id)
    assert updated.status == TaskStatus.COMPLETED
    assert updated.result == "Result content"
    assert updated.completed_at is not None


def test_registry_fail():
    registry = TaskRegistry()
    task = SubagentTask(description="Test", prompt="Do it")
    registry.register(task)
    
    registry.fail(task.task_id, "Something went wrong")
    
    updated = registry.get(task.task_id)
    assert updated.status == TaskStatus.FAILED
    assert updated.error == "Something went wrong"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_subagent/test_registry.py -v
```

Expected: FAIL - ImportError

- [ ] **Step 3: Implement TaskRegistry**

```python
# src/bourbon/subagent/registry.py
from typing import Optional
from .types import SubagentTask, TaskStatus


class TaskRegistry:
    """In-memory registry of subagent tasks.
    
    Stores task state and provides query/filter capabilities.
    """
    
    def __init__(self):
        self._tasks: dict[str, SubagentTask] = {}
    
    def register(self, task: SubagentTask) -> None:
        """Register a new task."""
        self._tasks[task.task_id] = task
    
    def get(self, task_id: str) -> Optional[SubagentTask]:
        """Get task by ID."""
        return self._tasks.get(task_id)
    
    def list_all(
        self,
        status: Optional[TaskStatus] = None,
        agent_type: Optional[str] = None,
    ) -> list[SubagentTask]:
        """List tasks with optional filtering."""
        tasks = list(self._tasks.values())
        
        if status:
            tasks = [t for t in tasks if t.status == status]
        
        if agent_type:
            tasks = [t for t in tasks if t.agent_type == agent_type]
        
        return tasks
    
    def update_status(self, task_id: str, status: TaskStatus) -> bool:
        """Update task status."""
        task = self._tasks.get(task_id)
        if not task:
            return False
        
        task.status = status
        if status == TaskStatus.RUNNING and not task.started_at:
            from datetime import datetime
            task.started_at = datetime.now()
        
        return True
    
    def complete(self, task_id: str, result: str) -> bool:
        """Mark task as completed with result."""
        task = self._tasks.get(task_id)
        if not task:
            return False
        
        task.status = TaskStatus.COMPLETED
        task.result = result
        from datetime import datetime
        task.completed_at = datetime.now()
        
        return True
    
    def fail(self, task_id: str, error: str) -> bool:
        """Mark task as failed with error."""
        task = self._tasks.get(task_id)
        if not task:
            return False
        
        task.status = TaskStatus.FAILED
        task.error = error
        from datetime import datetime
        task.completed_at = datetime.now()
        
        return True
```

- [ ] **Step 4: Update __init__.py**

Add to `src/bourbon/subagent/__init__.py`:

```python
from .registry import TaskRegistry

__all__ = [
    # ... existing exports ...
    "TaskRegistry",
]
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
python -m pytest tests/test_subagent/test_registry.py -v
```

Expected: 8 tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/bourbon/subagent/registry.py tests/test_subagent/test_registry.py src/bourbon/subagent/__init__.py
git commit -m "feat(subagent): add TaskRegistry for task state management

- In-memory task storage with dict-based lookup
- Support filtering by status and agent_type
- Methods: register, get, list_all, update_status, complete, fail
- Auto-set started_at and completed_at timestamps"
```

---

## Next Chunks Preview

**Chunk 5:** Result finalization, partial result extraction, notification service
**Chunk 6:** Session adapter, executor, cleanup
**Chunk 7:** SubagentManager (core orchestration)
**Chunk 8:** Agent tool registration
**Chunk 9:** CLI commands (/task list, output, stop)
**Chunk 10:** Integration tests and documentation

Plan saved to `docs/superpowers/plans/2025-04-09-bourbon-subagent-implementation.md`

Ready to execute or continue with remaining chunks?


---

## Chunk 5: Result Handling

### Task 6: Implement Result Finalization

**Files:**
- Create: `src/bourbon/subagent/result.py`
- Test: `tests/test_subagent/test_result.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_subagent/test_result.py
from datetime import datetime
import pytest
from bourbon.subagent.result import AgentToolResult, finalize_agent_tool
from bourbon.subagent.types import SubagentTask, TaskStatus


def test_agent_tool_result_creation():
    result = AgentToolResult(
        task_id="abc123",
        agent_type="coder",
        content="Task completed successfully",
        total_duration_ms=5000,
        total_tokens=1000,
        total_tool_calls=5,
    )
    assert result.task_id == "abc123"
    assert result.agent_type == "coder"
    assert result.total_tool_calls == 5


def test_agent_tool_result_to_notification():
    result = AgentToolResult(
        task_id="abc123",
        agent_type="coder",
        content="Refactoring complete.\n\nUpdated 3 files.",
        total_duration_ms=12500,
        total_tokens=2450,
        total_tool_calls=8,
    )
    
    notification = result.to_notification()
    
    assert "abc123" in notification
    assert "12.5s" in notification
    assert "2450" in notification
    assert "/task output abc123" in notification


def test_finalize_agent_tool_basic():
    task = SubagentTask(
        task_id="test123",
        description="Test task",
        prompt="Do something",
        agent_type="default",
    )
    task.tool_call_count = 5
    task.total_tokens = 1000
    
    messages = []  # Simplified - would contain actual messages
    start_time = datetime.now().timestamp() * 1000 - 5000  # 5 seconds ago
    
    result = finalize_agent_tool(
        task=task,
        messages=messages,
        final_content="Task done",
        start_time_ms=start_time,
    )
    
    assert result.task_id == "test123"
    assert result.content == "Task done"
    assert result.total_duration_ms >= 5000
    assert result.total_tool_calls == 5
    assert result.total_tokens == 1000
```

- [ ] **Step 2-6: Implement and test (similar pattern)**

```python
# src/bourbon/subagent/result.py
from dataclasses import dataclass
from typing import Any


@dataclass
class AgentToolResult:
    """Final result of a subagent task."""
    task_id: str
    agent_type: str
    content: str
    total_duration_ms: int
    total_tokens: int
    total_tool_calls: int
    usage: dict | None = None
    
    def to_notification(self) -> str:
        """Convert to user notification message."""
        return f"""[Task {self.task_id}] Completed

Description: {self.description if hasattr(self, 'description') else self.task_id}
Status: ✅ Completed
Duration: {self.total_duration_ms / 1000:.1f}s
Tokens: {self.total_tokens}
Tool Calls: {self.total_tool_calls}

Result:
{self.content[:500]}{'...' if len(self.content) > 500 else ''}

Use `/task output {self.task_id}` for full details.
"""


def finalize_agent_tool(
    task: Any,  # SubagentTask
    messages: list[dict],
    final_content: str,
    start_time_ms: float,
) -> AgentToolResult:
    """Finalize a task and create result object."""
    from datetime import datetime
    
    duration_ms = int(datetime.now().timestamp() * 1000 - start_time_ms)
    
    return AgentToolResult(
        task_id=task.task_id,
        agent_type=task.agent_type,
        content=final_content,
        total_duration_ms=duration_ms,
        total_tokens=task.total_tokens,
        total_tool_calls=task.tool_call_count,
        usage={
            "input_tokens": task.total_tokens // 2,  # Approximation
            "output_tokens": task.total_tokens // 2,
        },
    )
```

---

### Task 7: Implement Partial Result Extraction

**Files:**
- Create: `src/bourbon/subagent/partial_result.py`
- Test: `tests/test_subagent/test_partial_result.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_subagent/test_partial_result.py
import pytest
from bourbon.subagent.partial_result import extract_partial_result
from bourbon.subagent.types import TextBlock, ToolUseBlock, TranscriptMessage, MessageRole


def test_extract_partial_from_assistant_message():
    messages = [
        TranscriptMessage(
            role=MessageRole.USER,
            content=[TextBlock(text="Hello")],
        ),
        TranscriptMessage(
            role=MessageRole.ASSISTANT,
            content=[TextBlock(text="Working on it...")],
        ),
    ]
    
    result = extract_partial_result(messages)
    assert result == "Working on it..."


def test_extract_partial_skips_empty_messages():
    messages = [
        TranscriptMessage(
            role=MessageRole.ASSISTANT,
            content=[ToolUseBlock(id="1", name="Read", input={})],
        ),
        TranscriptMessage(
            role=MessageRole.ASSISTANT,
            content=[TextBlock(text="Final result")],
        ),
    ]
    
    result = extract_partial_result(messages)
    assert result == "Final result"


def test_extract_partial_truncates_long_content():
    long_text = "x" * 3000
    messages = [
        TranscriptMessage(
            role=MessageRole.ASSISTANT,
            content=[TextBlock(text=long_text)],
        ),
    ]
    
    result = extract_partial_result(messages)
    assert len(result) < 2500
    assert result.endswith("... (truncated)")


def test_extract_partial_no_content():
    messages = [
        TranscriptMessage(
            role=MessageRole.USER,
            content=[TextBlock(text="Hello")],
        ),
    ]
    
    result = extract_partial_result(messages)
    assert "No partial result" in result
```

- [ ] **Step 2-6: Implement and test**

```python
# src/bourbon/subagent/partial_result.py
from .types import TranscriptMessage, MessageRole, TextBlock


def extract_partial_result(messages: list[TranscriptMessage]) -> str:
    """Extract partial result from incomplete task.
    
    Searches from most recent message backwards to find
    the last assistant message with text content.
    """
    for msg in reversed(messages):
        if msg.role != MessageRole.ASSISTANT:
            continue
        
        # Extract text blocks
        text_parts = []
        for block in msg.content:
            if isinstance(block, TextBlock) and block.text.strip():
                text_parts.append(block.text)
        
        if text_parts:
            result = "\n".join(text_parts)
            # Truncate if too long
            if len(result) > 2000:
                return result[:2000] + "\n... (truncated)"
            return result
    
    return "(No partial result available)"
```

---

## Chunk 6: Supporting Infrastructure

### Task 8: Implement Session Adapter

**Files:**
- Create: `src/bourbon/subagent/session_adapter.py`
- Test: `tests/test_subagent/test_session_adapter.py`

```python
# src/bourbon/subagent/session_adapter.py
from pathlib import Path
from uuid import uuid4

from bourbon.session.manager import SessionManager
from bourbon.session.storage import TranscriptStore
from bourbon.session.types import SessionMetadata

from .types import AgentDefinition


class SubagentSessionAdapter:
    """Creates isolated session environment for subagent.
    
    Subagents have their own:
    - Independent MessageChain (no parent history pollution)
    - Shared TranscriptStore (for persistence)
    - Independent ContextManager (separate token tracking)
    """
    
    def __init__(
        self,
        parent_store: TranscriptStore,
        project_name: str,
        project_dir: str,
        task_id: str,
    ):
        self.parent_store = parent_store
        self.project_name = f"{project_name}/subagents"
        self.project_dir = project_dir
        self.task_id = task_id
    
    def create_session(self):
        """Create isolated subagent session."""
        from bourbon.session.manager import Session
        from bourbon.session.types import SessionMetadata
        from datetime import datetime
        from uuid import uuid4
        
        metadata = SessionMetadata(
            uuid=uuid4(),
            parent_uuid=None,
            project_dir=self.project_dir,
            created_at=datetime.now(),
            last_activity=datetime.now(),
            description=f"Subagent task {self.task_id}",
        )
        
        return Session(
            metadata=metadata,
            store=self.parent_store,
            project_name=self.project_name,
        )
```

---

### Task 9: Implement AsyncExecutor

**Files:**
- Create: `src/bourbon/subagent/executor.py`
- Test: `tests/test_subagent/test_executor.py`

```python
# src/bourbon/subagent/executor.py
from concurrent.futures import ThreadPoolExecutor, Future
from typing import Callable, Any


class AsyncExecutor:
    """Manages thread pool for background task execution."""
    
    def __init__(self, max_workers: int = 10):
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="subagent_",
        )
        self._futures: dict[str, Future] = {}
    
    def submit(
        self,
        task_id: str,
        fn: Callable,
        *args,
        **kwargs,
    ) -> Future:
        """Submit task to thread pool."""
        future = self._executor.submit(fn, *args, **kwargs)
        self._futures[task_id] = future
        
        # Clean up when done
        future.add_done_callback(
            lambda f: self._futures.pop(task_id, None)
        )
        
        return future
    
    def get_future(self, task_id: str) -> Future | None:
        """Get future for running task."""
        return self._futures.get(task_id)
    
    def shutdown(self, wait: bool = True):
        """Shutdown thread pool."""
        self._executor.shutdown(wait=wait)
```

---

### Task 10: Implement Cleanup

**Files:**
- Create: `src/bourbon/subagent/cleanup.py`

```python
# src/bourbon/subagent/cleanup.py
import atexit
import weakref
from typing import Set

from .types import SubagentTask, TaskStatus


class ResourceManager:
    """Ensures proper cleanup of subagent resources."""
    
    def __init__(self):
        self._tasks: weakref.WeakSet[SubagentTask] = weakref.WeakSet()
        atexit.register(self._cleanup_all)
    
    def register(self, task: SubagentTask):
        """Register task for cleanup tracking."""
        self._tasks.add(task)
    
    def _cleanup_all(self):
        """Cleanup all running tasks on exit."""
        for task in list(self._tasks):
            if task.status == TaskStatus.RUNNING:
                self._cleanup_task(task)
    
    def _cleanup_task(self, task: SubagentTask):
        """Cleanup single task resources."""
        # Signal abort
        if task.abort_controller:
            task.abort_controller.abort()
        
        # Shutdown MCP if needed
        if hasattr(task, '_subagent'):
            try:
                task._subagent.shutdown_mcp_sync()
            except Exception:
                pass
        
        # Mark as killed
        task.status = TaskStatus.KILLED
```

---

## Chunk 7: Core Manager

### Task 11: Implement SubagentManager

**Files:**
- Create: `src/bourbon/subagent/manager.py`
- Test: `tests/test_subagent/test_manager.py`

This is the main orchestration component. Implementation follows design spec Section 4.1.

Key methods to implement:
- `spawn()` - main entry point
- `_spawn_sync()` - blocking execution
- `_spawn_async()` - background execution
- `_create_subagent()` - Agent instance creation
- `_run_subagent()` - execution loop
- `_finalize()` - result extraction
- `get_task()`, `list_tasks()`, `kill_task()`, `get_output()`

See design spec for full implementation details.

---

## Chunk 8: Tool Registration

### Task 12: Implement Agent Tool

**Files:**
- Create: `src/bourbon/tools/agent_tool.py`
- Test: `tests/test_subagent/test_agent_tool.py`

```python
# src/bourbon/tools/agent_tool.py
from bourbon.tools import RiskLevel, ToolContext, register_tool


def get_manager(ctx: ToolContext):
    """Get SubagentManager from context."""
    return ctx.agent.subagent_manager


@register_tool(
    name="Agent",
    description="Start a subagent for focused task execution.",
    input_schema={
        "type": "object",
        "properties": {
            "description": {"type": "string", "description": "Short task description"},
            "prompt": {"type": "string", "description": "Complete instructions"},
            "subagent_type": {
                "type": "string",
                "enum": ["default", "coder", "explore", "plan", "quick_task"],
                "default": "default",
            },
            "model": {"type": "string"},
            "max_turns": {"type": "integer", "default": 50},
            "run_in_background": {"type": "boolean", "default": False},
        },
        "required": ["description", "prompt"],
    },
    risk_level=RiskLevel.MEDIUM,
    required_capabilities=["subagent"],
)
def agent_tool(
    description: str,
    prompt: str,
    subagent_type: str = "default",
    model: str | None = None,
    max_turns: int = 50,
    run_in_background: bool = False,
    *,
    ctx: ToolContext,
) -> str:
    """Agent tool handler."""
    manager = get_manager(ctx)
    
    result = manager.spawn(
        description=description,
        prompt=prompt,
        agent_type=subagent_type,
        model=model,
        max_turns=max_turns,
        run_in_background=run_in_background,
    )
    
    if run_in_background:
        task_id = result
        return f"Started background task: {task_id}\nUse `/task output {task_id}` to check status."
    else:
        agent_result = result
        return (
            f"Subagent completed in {agent_result.total_duration_ms / 1000:.1f}s\n"
            f"Tokens: {agent_result.total_tokens}, Tool calls: {agent_result.total_tool_calls}\n\n"
            f"Result:\n{agent_result.content}"
        )
```

---

## Chunk 9: CLI Commands

### Task 13: Implement Task Commands

**Files:**
- Create: `src/bourbon/commands/task_commands.py`
- Modify: `src/bourbon/agent.py` - add command handling

```python
# src/bourbon/commands/task_commands.py
from bourbon.tools.base import run_bash


def task_list(*, ctx) -> str:
    """List all tasks."""
    manager = ctx.agent.subagent_manager
    tasks = manager.list_tasks()
    
    if not tasks:
        return "No tasks found."
    
    lines = ["┌────────┬──────────┬──────────────────────────────┬───────────┐"]
    lines.append("│ Task   │ Type     │ Description                  │ Status    │")
    lines.append("├────────┼──────────┼──────────────────────────────┼───────────┤")
    
    for t in tasks:
        desc = t.description[:28] + ".." if len(t.description) > 30 else t.description
        lines.append(
            f"│ {t.task_id:6} │ {t.agent_type:8} │ {desc:28} │ {t.status.value:9} │"
        )
    
    lines.append("└────────┴──────────┴──────────────────────────────┴───────────┘")
    return "\n".join(lines)


def task_output(task_id: str, *, ctx) -> str:
    """Get task output."""
    manager = ctx.agent.subagent_manager
    output = manager.get_output(task_id)
    
    if output is None:
        return f"Task {task_id} not found."
    
    return output


def task_stop(task_id: str, *, ctx) -> str:
    """Stop a running task."""
    manager = ctx.agent.subagent_manager
    success = manager.kill_task(task_id)
    
    return f"Task {task_id} stopped." if success else f"Could not stop task {task_id}."
```

---

## Chunk 10: Integration and Finalization

### Task 14: Integrate with Agent Class

**Files:**
- Modify: `src/bourbon/agent.py`

Add to Agent.__init__:
```python
from bourbon.subagent.manager import SubagentManager

# Initialize subagent manager
self.subagent_manager = SubagentManager(
    config=config,
    workdir=self.workdir,
    parent_agent=self,
)
```

Add command handling to step():
```python
def step(self, user_input: str) -> str:
    # Handle task commands
    if user_input.startswith("/task "):
        return self._handle_task_command(user_input[6:])
    # ... rest of method
```

---

### Task 15: Integration Tests

**Files:**
- Create: `tests/test_subagent/test_integration.py`

Test end-to-end scenarios:
- Sync subagent execution
- Async subagent execution
- Task listing
- Task cancellation
- Error handling

---

### Task 16: Documentation

**Files:**
- Modify: `docs/superpowers/specs/2025-04-09-bourbon-subagent-design.md` - mark as implemented
- Create: `docs/superpowers/guides/subagent-usage.md` - user guide

---

## Summary

This plan implements the complete Bourbon Subagent System across 16 tasks in 10 chunks.

**Key Design Principles:**
- DRY: Reuse existing Bourbon components (Session, ToolRegistry, etc.)
- YAGNI: Focus on core features, defer enhancements
- TDD: Write tests before implementation
- Frequent commits: Each task ends with a commit

**Dependencies:**
- All chunks depend on Chunk 1 (core types)
- Chunk 7 (Manager) depends on Chunks 1-6
- Chunk 8 (Tool) depends on Chunk 7
- Chunk 9 (CLI) depends on Chunk 7
- Chunk 10 (Integration) depends on all previous

Ready to execute?
