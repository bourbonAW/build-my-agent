# Bourbon Subagent System Design

**Date:** 2026-04-09  
**Author:** AI Agent  
**Status:** Draft  
**Related:** [Claude Code Subagent Architecture](../../wiki/subagent-architecture-overview.md)

---

## Executive Summary

This document describes the design of Bourbon's Subagent System, enabling the creation and management of specialized sub-agents for parallel task execution, code exploration, and focused work. The design is heavily inspired by Claude Code's subagent architecture while adapting it to Bourbon's Python-based, CLI-first environment.

### Key Design Decisions

| Aspect | Decision | Rationale |
|--------|----------|-----------|
| Execution Model | Thread-based async | Python GIL makes true parallelism difficult; threads provide sufficient concurrency for I/O-bound subagents |
| Context Strategy | Independent sessions | Subagents receive only the provided prompt, not parent session history |
| Tool Permissions | Agent-type based filtering | Different agent types (coder/explore/plan) have different tool access |
| Notification | REPL command-based | Extend the existing REPL command handler instead of introducing a second command subsystem |
| Recursion | Disabled | Subagents cannot create subagents to prevent infinite nesting |

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Bourbon Subagent Architecture                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                        Agent (Main Session)                          │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────────┐  │   │
│  │  │   Session   │  │    LLM      │  │      SubagentManager        │  │   │
│  │  │   Manager   │◄─┤   Client    │◄─┤  ┌─────────────────────┐    │  │   │
│  │  └─────────────┘  └─────────────┘  │  │ SubagentRegistry    │    │  │   │
│  │                                    │  │  ┌─────┐┌─────┐     │    │  │   │
│  │  ┌─────────────┐  ┌─────────────┐  │  │  │Run1 ││Run2 │ ... │    │  │   │
│  │  │  Tool Reg   │  │   Skills    │  │  │  └─────┘└─────┘     │    │  │   │
│  │  └─────────────┘  └─────────────┘  │  └─────────────────────┘    │  │   │
│  │                                    │  ┌─────────────────────┐    │  │   │
│  │                                    │  │ AgentTypeRegistry   │    │  │   │
│  │                                    │  │  (coder/explore/...)│    │  │   │
│  │                                    │  └─────────────────────┘    │  │   │
│  │                                    │  ┌─────────────────────┐    │  │   │
│  │                                    │  │ ToolFilterEngine    │    │  │   │
│  │                                    │  │  (Permission Ctrl)  │    │  │   │
│  │                                    │  └─────────────────────┘    │  │   │
│  │                                    └─────────────────────────────┘  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                        │
│                    ┌───────────────┼───────────────┐                        │
│                    ▼               ▼               ▼                        │
│            ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                │
│            │  Sync Exec  │  │ Async Exec  │  │ Notification│                │
│            │  (Blocking) │  │ (Thread)    │  │   Service   │                │
│            └─────────────┘  └─────────────┘  └─────────────┘                │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | File Location | Responsibility |
|-----------|---------------|----------------|
| `SubagentManager` | `src/bourbon/subagent/manager.py` | Lifecycle management for runtime jobs |
| `SubagentRegistry` | `src/bourbon/subagent/registry.py` | In-memory runtime job state storage |
| `AgentTypeRegistry` | `src/bourbon/subagent/types.py` | Agent definition configs (coder/explore/plan) |
| `ToolFilterEngine` | `src/bourbon/subagent/tools.py` | Dynamic tool filtering per agent type |
| `AbortController` | `src/bourbon/subagent/cancel.py` | Hierarchical cancellation signaling |
| `AgentTool` | `src/bourbon/tools/agent_tool.py` | Tool registration and handler |
| `REPL` integration | `src/bourbon/repl.py` | Runtime-job commands such as `/runs`, `/run-show`, and `/run-stop` |

### Terminology Boundary

- `TodoWrite` is the legacy in-memory checklist for one agent.
- `TaskCreate` / `TaskUpdate` / `TaskList` / `TaskGet` are reserved for persistent workflow task management.
- The subagent registry tracks runtime jobs only. It is execution state, not workflow task state.
- `/tasks` remains reserved for workflow tasks, so runtime-job UX should use `/runs`, `/run-show`, and `/run-stop`.

---

## Data Models

### Runtime Job State Machine

```
                    ┌─────────────┐
         ┌─────────►│   PENDING   │◄────────┐
         │          │  (Created)  │         │
         │          └──────┬──────┘         │
         │                 │ register       │ retry
         │                 ▼                │
    kill  │          ┌─────────────┐         │
         │     ┌───►│   RUNNING   │─────────┘
         │     │    │  (Active)   │◄───┐
         │     │    └──────┬──────┘    │
         │  kill      complete      fail │
         │     │           │           │
         │     │           ▼           │
         │     └────┤  COMPLETED ├─────┘
         │          │   (Done)    │
         │          └─────────────┘
         │
         └────────────►┌─────────────┐
                       │   KILLED    │
                       │  (Aborted)  │
                       └─────────────┘

         fail ─────────►┌─────────────┐
                       │   FAILED    │
                       │  (Error)    │
                       └─────────────┘
```

### Core Types

```python
# src/bourbon/subagent/types.py

class RunStatus(Enum):
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
    allowed_tools: list[str] | None = None      # None = all except disallowed
    disallowed_tools: list[str] = field(default_factory=list)
    max_turns: int = 50
    model: str | None = None
    system_prompt_suffix: str | None = None


@dataclass
class SubagentRun:
    """Runtime job instance."""
    run_id: str
    description: str
    prompt: str
    agent_type: str
    status: RunStatus
    is_async: bool
    
    # Execution
    abort_controller: AbortController | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    
    # Results
    result: str | None = None
    error: str | None = None
    tool_call_count: int = 0
    total_tokens: int = 0
    
    def to_dict(self) -> dict: ...
```

Subagents should not introduce a second permission mode abstraction unless the parent `Agent` permission runtime is first generalized to support it.

---

## Tool Permission Matrix

### Global Disallowed Tools (All Subagents)

```python
ALL_AGENT_DISALLOWED_TOOLS = {
    "Agent",           # No recursion - subagents cannot spawn subagents
    "TodoWrite",       # Prevent polluting parent agent's todo list
    "compress",        # Manual compression disabled
}
```

### Agent Type Configurations

```python
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


AGENT_TYPE_CONFIGS = {
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
        allowed_tools=["Read", "Glob", "Grep", "AstGrep", "WebFetch"],
        max_turns=30,
        system_prompt_suffix="You are in READ-ONLY mode. Do not modify files.",
    ),
    
    "plan": AgentDefinition(
        agent_type="plan",
        description="Architecture and design planning",
        allowed_tools=["Read", "Glob", "Grep", "AstGrep", "WebFetch"],
        max_turns=30,
        system_prompt_suffix="Focus on architecture, tradeoffs, and implementation planning.",
    ),
    
    "quick_task": AgentDefinition(
        agent_type="quick_task",
        description="Fast execution for simple, bounded tasks",
        max_turns=20,
    ),
}
```

---

## Execution Flows

### Synchronous Execution (Foreground)

```
┌─────────────────────────────────────────────────────────────────┐
│                    Synchronous Subagent Flow                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. Agent Tool Call                                             │
│     Agent(description="Fix bug", prompt="...",                  │
│          run_in_background=False)                               │
│                          │                                      │
│                          ▼                                      │
│  2. Create Subagent Context                                     │
│     • Initialize empty session (no parent history)              │
│     • Filter tools by agent_type                                │
│     • Set max_turns limit                                       │
│                          │                                      │
│                          ▼                                      │
│  3. Execute Agent Loop                                          │
│     subagent.step(prompt)                                       │
│           │                                                     │
│           ├──► LLM.chat() with filtered tools                   │
│           │    Check cancellation signal each round             │
│           │                                                     │
│           ├──► Execute tool calls                               │
│           │    Verify tool permissions                          │
│           │                                                     │
│           └──► Loop until completion or max_turns               │
│                          │                                      │
│                          ▼                                      │
│  4. Finalize                                                    │
│     • Extract result text                                       │
│     • Calculate statistics                                      │
│     • Return AgentToolResult                                    │
│                          │                                      │
│                          ▼                                      │
│  5. Return to Parent                                            │
│     Result displayed directly in conversation                   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Asynchronous Execution (Background)

```
┌─────────────────────────────────────────────────────────────────┐
│                   Asynchronous Subagent Flow                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. Agent Tool Call                                             │
│     Agent(description="Long task", prompt="...",                │
│          run_in_background=True)                                │
│                          │                                      │
│                          ▼                                      │
│  2. Register Runtime Job                                        │
│     • Generate run_id                                           │
│     • Create RunState (PENDING)                                 │
│     • Setup AbortController                                     │
│     • Return run_id immediately                                 │
│                          │                                      │
│                          ▼                                      │
│  3. Execute in Thread Pool                                      │
│     Thread(target=_async_lifecycle)                             │
│           │                                                     │
│           ├──► Transition to RUNNING                            │
│           │                                                     │
│           ├──► Run agent loop (same as sync)                    │
│           │    Periodically save checkpoint                     │
│           │                                                     │
│           └──► Handle completion/error/abort                    │
│                          │                                      │
│                          ▼                                      │
│  4. Finalize & Notify                                           │
│     • Save result to disk                                       │
│     • Update RunState status                                    │
│     • Insert notification into parent session                   │
│                          │                                      │
│                          ▼                                      │
│  5. User Notification                                           │
│     "[Run a7f3b2] Completed. Use `/run-show a7f3b2`"            │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## REPL Interface

### REPL Commands

```bash
/runs                           # List runtime jobs
/run-show <run_id>             # Get full runtime job output
/run-stop <run_id>             # Stop a running runtime job
```

### Output Format

```
$ /runs

┌────────┬──────────┬────────────────────────────────┬───────────┐
│ Run    │ Type     │ Description                    │ Status    │
├────────┼──────────┼────────────────────────────────┼───────────┤
│ a7f3b2 │ coder    │ Refactor auth module           │ running   │
│ c9e1d4 │ explore  │ Analyze codebase structure     │ completed │
│ b2a8f9 │ default  │ Fix bug in parser              │ failed    │
└────────┴──────────┴────────────────────────────────┴───────────┘

$ /run-show a7f3b2
Subagent completed in 12.5s
Tokens: 2450, Tool calls: 8

Result:
Successfully refactored auth module:
- Extracted AuthService class
- Added unit tests
- Updated imports in 3 files
```

---

## Error Handling

### Error Types and Strategies

| Error Type | Detection | Handling | User Impact |
|------------|-----------|----------|-------------|
| `USER_ABORT` | `AbortController.is_aborted()` | Stop immediately, save partial result | Run status: KILLED |
| `MAX_TURNS_EXCEEDED` | `turn >= max_turns` | Stop loop, return collected results | Run status: COMPLETED with warning |
| `LLM_ERROR` | Exception from LLM.chat() | Retry 3x with backoff, then fail | Run status: FAILED |
| `TOOL_ERROR` | Tool returns "Error:" prefix | Return error to LLM for handling | Continue execution |
| `PERMISSION_DENIED` | AccessController denies | Reuse the parent agent's existing permission flow | Run status: FAILED or suspended for approval |

### Partial Result Extraction

When a task is killed or fails, extract partial results:

```python
def extract_partial_result(messages: list[TranscriptMessage]) -> str:
    """Extract the last assistant message with content."""
    for msg in reversed(messages):
        if msg.role == MessageRole.ASSISTANT:
            text = extract_text_content(msg)
            if text.strip():
                return text[:2000]  # Truncate if too long
    return "(No partial result available)"
```

---

## Cancellation Mechanism

### Hierarchical AbortController

```python
class AbortController:
    """Supports parent-child cancellation hierarchy."""
    
    def __init__(self, parent: 'AbortController' | None = None):
        self._event = threading.Event()
        self._parent = parent
        self._children: list[AbortController] = []
        if parent:
            parent._add_child(self)
    
    def abort(self):
        """Cascade abort to all children."""
        self._event.set()
        for child in self._children:
            child.abort()
    
    def is_aborted(self) -> bool:
        """Check self or any parent is aborted."""
        if self._event.is_set():
            return True
        return self._parent.is_aborted() if self._parent else False
```

### Usage in Agent Loop

```python
for turn in range(max_turns):
    # Check cancellation at start of each turn
    if abort_controller.is_aborted():
        raise RunCancellationError("Task was cancelled")
    
    response = llm.chat(...)
    # ... process response
```

---

## File Structure

```
src/bourbon/subagent/
├── __init__.py           # Public API exports
├── manager.py            # SubagentManager
├── registry.py           # SubagentRegistry (runtime jobs)
├── types.py              # Data models (AgentDefinition, SubagentRun)
├── tools.py              # Tool filtering logic
├── cancel.py             # AbortController
├── executor.py           # Async execution utilities
├── result.py             # Result finalization
├── notify.py             # Notification service
├── partial_result.py     # Partial result extraction
├── cleanup.py            # Resource cleanup
└── session_adapter.py    # Subagent session isolation

src/bourbon/tools/
└── agent_tool.py         # Agent tool registration

tests/test_subagent/
├── test_manager.py
├── test_registry.py
├── test_tools.py
├── test_cancel.py
└── test_integration.py
```

---

## Implementation Phases

### Phase 1: Core Infrastructure
- [ ] Create `SubagentManager` and `SubagentRegistry`
- [ ] Implement `AgentDefinition` configs
- [ ] Add tool filtering logic
- [ ] Create `AbortController`

### Phase 2: Synchronous Execution
- [ ] Implement `_spawn_sync()`
- [ ] Create subagent session isolation
- [ ] Add result finalization
- [ ] Write unit tests

### Phase 3: Asynchronous Execution
- [ ] Implement `_spawn_async()` with thread pool
- [ ] Add progress tracking
- [ ] Implement notification service
- [ ] Add checkpoint saving

### Phase 4: REPL Integration
- [ ] Implement `/runs` / `/run-show` / `/run-stop` commands in `src/bourbon/repl.py`
- [ ] Add runtime-job list display
- [ ] Implement output retrieval
- [ ] Add stop functionality

### Phase 5: Polish
- [ ] Error handling edge cases
- [ ] Resource cleanup
- [ ] Documentation
- [ ] Integration tests

---

## Configuration

Subagent settings must be added to `Config` before use. The first implementation should introduce a dedicated `SubagentConfig` dataclass in `src/bourbon/config.py` and persist only fields that are actually consumed by code, for example:

```toml
[subagent]
max_concurrent_tasks = 10
default_max_turns = 50
default_timeout_seconds = 600
enable_checkpointing = true
```

Avoid documenting storage or timeout knobs that are not yet wired through `Config.from_dict()` and `Config.to_dict()`.

## Integration with Existing Systems

### Access Control Integration

Subagents reuse the parent's `AccessController` for permission evaluation and follow the same permission-request behavior already implemented in `Agent`:

```python
class SubagentContext:
    def __init__(self, parent_agent: Agent, agent_def: AgentDefinition):
        # Share parent's access controller
        self.access_controller = parent_agent.access_controller
    
    def check_tool_permission(self, tool_name: str, tool_input: dict) -> PolicyDecision:
        # Use parent's policy evaluation
        return self.access_controller.evaluate(tool_name, tool_input)
```

Tool calls within subagents are logged through the parent's audit system:
- Tool name and input summary
- Subagent run_id (for traceability)
- Policy decision (allow/deny/need_approval)

### Audit Logging Integration

```python
def log_subagent_tool_call(
    run_id: str,
    tool_name: str,
    tool_input: dict,
    decision: PolicyDecision,
    parent_audit: AuditLogger,
):
    """Log subagent tool calls with parent audit logger."""
    parent_audit.record(
        AuditEvent.tool_call(
            run_id=run_id,
            tool_name=tool_name,
            tool_input_summary=str(tool_input)[:200],
            decision=decision.action.value,
            reason=decision.reason,
        )
    )
```

### Sandbox Integration

Destructive operations in subagents respect the parent's sandbox configuration:

```python
class SubagentManager:
    def _execute_destructive_tool(
        self,
        tool_name: str,
        tool_input: dict,
        task: SubagentRun,
    ) -> str:
        if self.parent_agent.sandbox.enabled:
            return self.parent_agent.sandbox.execute(
                tool_input.get("command", ""),
                tool_name=tool_name,
            )
        # Fall back to regular execution
        return self._execute_regular_tool(tool_name, tool_input)
```

### Session Storage Integration

Subagent transcripts should be stored through the existing `SessionManager.create_session()` flow with a dedicated project-name suffix such as `<project>/subagents`. This keeps metadata persistence and transcript rebuild behavior aligned with the current session system.

If a dedicated task-output file is later needed, add it after the session-backed version is working.

## Security Considerations

1. **No Recursion**: Subagents cannot spawn subagents (enforced by tool filtering)
2. **Tool Filtering**: Each agent type has strictly controlled tool access
3. **Path Safety**: Subagents inherit parent's workdir sandboxing
4. **Resource Limits**: max_turns prevents infinite execution
5. **Cancellation**: Users can kill runaway runtime jobs via `/run-stop`
6. **Audit Trail**: All subagent tool calls logged through parent's audit system
7. **Result Isolation**: Subagent transcripts use a dedicated session namespace separate from the parent session

---

## Future Enhancements

- **Fork Mode**: Support context inheritance for special scenarios
- **Process Isolation**: Use multiprocessing for true parallelism
- **Task Dependencies**: Support DAG-style task dependencies
- **Result Caching**: Cache subagent results for identical prompts
- **Custom Agent Types**: User-defined agent configurations

---

## References

- [Claude Code Subagent Architecture](../../wiki/subagent-architecture-overview.md)
- [Claude Code Code Reference](../../wiki/claude-code-subagent-code-reference.md)
- [Subagent Implementation Guide](../../wiki/subagent-implementation-guide.md)
- [Subagent Concurrency Control](../../wiki/subagent-concurrency-control.md)
- [Subagent Result Handling](../../wiki/subagent-result-handling.md)
