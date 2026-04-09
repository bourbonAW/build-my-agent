# User Confirmation Redesign Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace Bourbon's current `pending_confirmation` flow with a true suspend/resume permission runtime that supports `allow once`, `allow for session`, and `reject` across all tools.

**Architecture:** Introduce a dedicated `bourbon.permissions` runtime for permission requests, session-scoped approval matching, and request presentation. Refactor `Agent` to suspend an in-flight tool round instead of turning approval into a new chat turn, then update the REPL to render and resolve permission requests through a dedicated resume API.

**Tech Stack:** Python 3.12+, dataclasses, pytest, prompt-toolkit, Rich, existing Bourbon session/audit/access-control layers

---

## Preconditions

The repository's full test suite needs optional extras that are not installed by default in a clean environment.

- `tests/test_benchmark_loaders.py` imports `yaml`
- `tests/tools/test_web.py` imports `aiohttp`

Before broad verification, install the full local dev/test dependency set:

```bash
uv pip install -e ".[dev,stage-b,loaders]"
```

For fast iteration during implementation, use targeted `uv run --extra dev pytest ...` commands first, then run the broader verification command in Task 5.

Relevant design reference:

- `docs/plans/2026-04-09-user-confirmation-redesign-design.md`

Non-goal for this MVP:

- Do not redesign classifier/hooks/headless approval.
- Do not persist session approval rules.
- Do not keep the legacy "high-risk operation failed" follow-up prompt. Return normal tool errors instead and let the model decide the next move.

---

### Task 1: Create Permission Runtime Primitives

**Files:**
- Create: `src/bourbon/permissions/__init__.py`
- Create: `src/bourbon/permissions/runtime.py`
- Test: `tests/test_permissions_runtime.py`

**Step 1: Write the failing runtime tests**

```python
from bourbon.permissions.runtime import (
    PermissionAction,
    PermissionChoice,
    PermissionDecision,
    PermissionRequest,
    SessionPermissionStore,
    SuspendedToolRound,
)


def test_permission_request_defaults_to_three_claude_style_choices():
    request = PermissionRequest(
        request_id="req-1",
        tool_use_id="tool-1",
        tool_name="Bash",
        tool_input={"command": "pip install flask"},
        title="Bash command",
        description="Install a package",
        reason="exec: need_approval (command.need_approval: pip install *)",
        match_candidate={"kind": "command_prefix", "value": "pip install"},
    )

    assert request.options == (
        PermissionChoice.ALLOW_ONCE,
        PermissionChoice.ALLOW_SESSION,
        PermissionChoice.REJECT,
    )


def test_session_permission_store_is_process_local_and_empty_by_default():
    store = SessionPermissionStore()

    assert store.has_match("Bash", {"command": "pip install flask"}) is False


def test_suspended_tool_round_tracks_progress_and_active_request():
    request = PermissionRequest(
        request_id="req-1",
        tool_use_id="tool-2",
        tool_name="Write",
        tool_input={"path": "notes/todo.md", "content": "hello"},
        title="Write file",
        description="Create notes/todo.md",
        reason="file_write: need_approval (default)",
        match_candidate={"kind": "parent_dir", "value": "notes"},
    )
    round_state = SuspendedToolRound(
        source_assistant_uuid=None,
        tool_use_blocks=[{"id": "tool-1"}, {"id": "tool-2"}],
        completed_results=[{"tool_use_id": "tool-1", "content": "ok"}],
        next_tool_index=1,
        active_request=request,
    )

    assert round_state.next_tool_index == 1
    assert round_state.active_request.tool_use_id == "tool-2"
```

**Step 2: Run the tests to verify they fail**

Run:

```bash
uv run --extra dev pytest tests/test_permissions_runtime.py -v
```

Expected:

- FAIL with `ModuleNotFoundError: No module named 'bourbon.permissions'`

**Step 3: Write the minimal runtime module**

```python
# src/bourbon/permissions/runtime.py
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class PermissionAction(StrEnum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


class PermissionChoice(StrEnum):
    ALLOW_ONCE = "allow_once"
    ALLOW_SESSION = "allow_session"
    REJECT = "reject"


@dataclass(frozen=True)
class PermissionDecision:
    action: PermissionAction
    reason: str
    title: str = ""
    description: str = ""
    match_candidate: dict[str, Any] | None = None


@dataclass(frozen=True)
class PermissionRequest:
    request_id: str
    tool_use_id: str
    tool_name: str
    tool_input: dict[str, Any]
    title: str
    description: str
    reason: str
    match_candidate: dict[str, Any] | None = None
    options: tuple[PermissionChoice, PermissionChoice, PermissionChoice] = (
        PermissionChoice.ALLOW_ONCE,
        PermissionChoice.ALLOW_SESSION,
        PermissionChoice.REJECT,
    )


@dataclass
class SuspendedToolRound:
    source_assistant_uuid: Any
    tool_use_blocks: list[dict[str, Any]]
    completed_results: list[dict[str, Any]]
    next_tool_index: int
    active_request: PermissionRequest


class SessionPermissionStore:
    def __init__(self) -> None:
        self._rules: list[dict[str, Any]] = []

    def add(self, candidate: dict[str, Any]) -> None:
        self._rules.append(candidate)

    def has_match(self, tool_name: str, tool_input: dict[str, Any]) -> bool:
        return any(rule.get("tool_name") == tool_name for rule in self._rules)
```

```python
# src/bourbon/permissions/__init__.py
from bourbon.permissions.runtime import (
    PermissionAction,
    PermissionChoice,
    PermissionDecision,
    PermissionRequest,
    SessionPermissionStore,
    SuspendedToolRound,
)

__all__ = [
    "PermissionAction",
    "PermissionChoice",
    "PermissionDecision",
    "PermissionRequest",
    "SessionPermissionStore",
    "SuspendedToolRound",
]
```

**Step 4: Run the tests to verify they pass**

Run:

```bash
uv run --extra dev pytest tests/test_permissions_runtime.py -v
```

Expected:

- PASS

**Step 5: Commit**

```bash
git add src/bourbon/permissions/__init__.py src/bourbon/permissions/runtime.py tests/test_permissions_runtime.py
git commit -m "feat: add permission runtime primitives"
```

---

### Task 2: Implement Session Approval Matching and Request Presentation

**Files:**
- Create: `src/bourbon/permissions/matching.py`
- Create: `src/bourbon/permissions/presentation.py`
- Modify: `src/bourbon/permissions/runtime.py`
- Test: `tests/test_permissions_matching.py`

**Step 1: Write the failing matching and presentation tests**

```python
from pathlib import Path

from bourbon.permissions.matching import build_match_candidate, session_rule_matches
from bourbon.permissions.presentation import build_permission_request
from bourbon.permissions.runtime import PermissionDecision, PermissionAction


def test_bash_session_rule_matches_normalized_command_prefix(tmp_path: Path):
    candidate = build_match_candidate("Bash", {"command": "pip install flask"}, tmp_path)

    assert candidate["kind"] == "command_prefix"
    assert session_rule_matches(candidate, "Bash", {"command": "pip install requests"}, tmp_path)
    assert not session_rule_matches(candidate, "Bash", {"command": "uv run pytest"}, tmp_path)


def test_write_new_file_matches_parent_directory(tmp_path: Path):
    candidate = build_match_candidate(
        "Write",
        {"path": "notes/today.md", "content": "hello"},
        tmp_path,
    )

    assert candidate["kind"] == "parent_dir"
    assert session_rule_matches(
        candidate,
        "Write",
        {"path": "notes/tomorrow.md", "content": "world"},
        tmp_path,
    )


def test_edit_matches_exact_file_path(tmp_path: Path):
    candidate = build_match_candidate(
        "Edit",
        {"path": "src/app.py", "old_text": "a", "new_text": "b"},
        tmp_path,
    )

    assert candidate["kind"] == "exact_file"
    assert session_rule_matches(
        candidate,
        "Edit",
        {"path": "src/app.py", "old_text": "x", "new_text": "y"},
        tmp_path,
    )
    assert not session_rule_matches(
        candidate,
        "Edit",
        {"path": "src/other.py", "old_text": "x", "new_text": "y"},
        tmp_path,
    )


def test_build_permission_request_uses_tool_specific_summary(tmp_path: Path):
    decision = PermissionDecision(
        action=PermissionAction.ASK,
        reason="exec: need_approval (command.need_approval: pip install *)",
    )

    request = build_permission_request(
        tool_name="Bash",
        tool_input={"command": "pip install flask"},
        tool_use_id="tool-1",
        decision=decision,
        workdir=tmp_path,
    )

    assert request.title == "Bash command"
    assert "pip install flask" in request.description
    assert request.match_candidate["kind"] == "command_prefix"
```

**Step 2: Run the tests to verify they fail**

Run:

```bash
uv run --extra dev pytest tests/test_permissions_matching.py -v
```

Expected:

- FAIL with missing `matching.py` / `presentation.py`

**Step 3: Implement match-candidate builders and request presentation**

```python
# src/bourbon/permissions/matching.py
from __future__ import annotations

from pathlib import Path


def _normalize_path(path: str, workdir: Path) -> str:
    raw = Path(path)
    resolved = raw.resolve() if raw.is_absolute() else (workdir / raw).resolve()
    return str(resolved)


def _normalized_command_prefix(command: str) -> str:
    tokens = command.strip().split()
    return " ".join(tokens[:2]) if len(tokens) >= 2 else command.strip()


def build_match_candidate(tool_name: str, tool_input: dict, workdir: Path) -> dict:
    if tool_name == "Bash":
        return {
            "tool_name": tool_name,
            "kind": "command_prefix",
            "value": _normalized_command_prefix(tool_input.get("command", "")),
        }

    if tool_name == "Write":
        resolved = Path(_normalize_path(tool_input["path"], workdir))
        kind = "exact_file" if resolved.exists() else "parent_dir"
        value = str(resolved if kind == "exact_file" else resolved.parent)
        return {"tool_name": tool_name, "kind": kind, "value": value}

    if tool_name == "Edit":
        return {
            "tool_name": tool_name,
            "kind": "exact_file",
            "value": _normalize_path(tool_input["path"], workdir),
        }

    key_fields = sorted((k, repr(v)) for k, v in tool_input.items() if k in {"path", "command", "url"})
    return {
        "tool_name": tool_name,
        "kind": "fallback",
        "value": tuple(key_fields),
    }


def session_rule_matches(candidate: dict, tool_name: str, tool_input: dict, workdir: Path) -> bool:
    fresh = build_match_candidate(tool_name, tool_input, workdir)
    return candidate == fresh
```

```python
# src/bourbon/permissions/presentation.py
from __future__ import annotations

import uuid
from pathlib import Path

from bourbon.permissions.matching import build_match_candidate
from bourbon.permissions.runtime import PermissionDecision, PermissionRequest


def build_permission_request(
    *,
    tool_name: str,
    tool_input: dict,
    tool_use_id: str,
    decision: PermissionDecision,
    workdir: Path,
) -> PermissionRequest:
    if tool_name == "Bash":
        title = "Bash command"
        description = tool_input.get("command", "")
    elif tool_name == "Write":
        title = "Write file"
        description = f"{tool_input.get('path')} ({len(tool_input.get('content', ''))} chars)"
    elif tool_name == "Edit":
        title = "Edit file"
        description = tool_input.get("path", "")
    else:
        title = f"{tool_name} request"
        description = repr(tool_input)

    return PermissionRequest(
        request_id=f"perm-{uuid.uuid4().hex[:8]}",
        tool_use_id=tool_use_id,
        tool_name=tool_name,
        tool_input=tool_input,
        title=title,
        description=description,
        reason=decision.reason,
        match_candidate=build_match_candidate(tool_name, tool_input, workdir),
    )
```

**Step 4: Update `SessionPermissionStore` to use real matching**

```python
# in src/bourbon/permissions/runtime.py
from pathlib import Path

from bourbon.permissions.matching import session_rule_matches


class SessionPermissionStore:
    def __init__(self) -> None:
        self._rules: list[dict[str, Any]] = []

    def add(self, candidate: dict[str, Any]) -> None:
        self._rules.append(candidate)

    def has_match(self, tool_name: str, tool_input: dict[str, Any], workdir: Path) -> bool:
        return any(
            session_rule_matches(rule, tool_name, tool_input, workdir)
            for rule in self._rules
        )
```

**Step 5: Run the tests to verify they pass**

Run:

```bash
uv run --extra dev pytest tests/test_permissions_runtime.py tests/test_permissions_matching.py -v
```

Expected:

- PASS

**Step 6: Commit**

```bash
git add src/bourbon/permissions/runtime.py src/bourbon/permissions/matching.py src/bourbon/permissions/presentation.py tests/test_permissions_matching.py
git commit -m "feat: add session approval matching and request summaries"
```

---

### Task 3: Refactor Agent to Suspend and Resume Tool Rounds

**Files:**
- Modify: `src/bourbon/agent.py`
- Modify: `src/bourbon/permissions/__init__.py`
- Test: `tests/test_agent_permission_runtime.py`
- Modify: `tests/test_agent_security_integration.py`

**Step 1: Write the failing agent-runtime tests**

```python
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from bourbon.access_control.policy import CapabilityDecision, PolicyAction, PolicyDecision
from bourbon.agent import Agent
from bourbon.permissions.runtime import PermissionChoice


def make_approval_decision():
    return PolicyDecision(
        action=PolicyAction.NEED_APPROVAL,
        reason="exec: need_approval (command.need_approval: pip install *)",
        decisions=[
            CapabilityDecision(
                capability="exec",
                action=PolicyAction.NEED_APPROVAL,
                matched_rule="command.need_approval: pip install *",
            )
        ],
    )


def test_execute_tools_suspends_round_instead_of_reentering_chat(monkeypatch):
    agent = make_agent_stub()
    agent.access_controller.evaluate.return_value = make_approval_decision()
    monkeypatch.setattr("bourbon.agent.get_registry", lambda: MagicMock())

    results = agent._execute_tools(
        [
            {"type": "tool_use", "id": "tool-1", "name": "Read", "input": {"path": "README.md"}},
            {"type": "tool_use", "id": "tool-2", "name": "Bash", "input": {"command": "pip install flask"}},
        ],
        source_assistant_uuid=uuid4(),
    )

    assert agent.active_permission_request is not None
    assert agent.suspended_tool_round is not None
    assert agent.suspended_tool_round.next_tool_index == 1
    assert results[0]["tool_use_id"] == "tool-1"


def test_resume_permission_request_allow_session_stores_rule_and_executes(monkeypatch):
    agent = make_agent_stub()
    registry = MagicMock()
    registry.call.return_value = "installed"
    monkeypatch.setattr("bourbon.agent.get_registry", lambda: registry)
    # build suspended state here

    output = agent.resume_permission_request(PermissionChoice.ALLOW_SESSION)

    assert "installed" in output
    assert agent.session_permissions._rules
    assert agent.active_permission_request is None


def test_resume_permission_request_reject_returns_error_tool_result(monkeypatch):
    agent = make_agent_stub()
    # build suspended state here

    output = agent.resume_permission_request(PermissionChoice.REJECT)

    assert "Mock" in output
    tool_result_blocks = [
        block for block in agent.session.chain.messages[-1].content
        if getattr(block, "type", None) == "tool_result"
    ]
    assert any(block.is_error for block in tool_result_blocks)
```

**Step 2: Run the tests to verify they fail**

Run:

```bash
uv run --extra dev pytest tests/test_agent_permission_runtime.py -v
```

Expected:

- FAIL because `Agent` does not yet expose `active_permission_request`, `suspended_tool_round`, or `resume_permission_request()`

**Step 3: Add the new agent runtime state**

In `src/bourbon/agent.py`, replace the old single-slot confirmation state:

```python
self.session_permissions = SessionPermissionStore()
self.suspended_tool_round: SuspendedToolRound | None = None
self.active_permission_request: PermissionRequest | None = None
```

Delete:

- `PendingConfirmation`
- `self.pending_confirmation`
- `_handle_confirmation_response()`
- `_format_confirmation_prompt()`
- `_is_approval_response()`

Also delete the legacy post-error confirmation path that calls `_generate_options()` for failed high-risk tools.

**Step 4: Add permission helpers inside `Agent`**

Implement these helpers in `src/bourbon/agent.py`:

```python
def _permission_decision_for_tool(self, tool_name: str, tool_input: dict) -> PermissionDecision:
    decision = self.access_controller.evaluate(tool_name, tool_input)
    self._record_policy_decision(tool_name=tool_name, tool_input=tool_input, decision=decision)

    if decision.action == PolicyAction.DENY:
        return PermissionDecision(action=PermissionAction.DENY, reason=decision.reason)

    if decision.action == PolicyAction.NEED_APPROVAL:
        if self.session_permissions.has_match(tool_name, tool_input, self.workdir):
            return PermissionDecision(action=PermissionAction.ALLOW, reason="session rule matched")
        return PermissionDecision(action=PermissionAction.ASK, reason=decision.reason)

    return PermissionDecision(action=PermissionAction.ALLOW, reason=decision.reason)
```

```python
def _suspend_tool_round(
    self,
    *,
    source_assistant_uuid,
    tool_use_blocks: list[dict],
    completed_results: list[dict],
    next_tool_index: int,
    request: PermissionRequest,
) -> None:
    self.active_permission_request = request
    self.suspended_tool_round = SuspendedToolRound(
        source_assistant_uuid=source_assistant_uuid,
        tool_use_blocks=tool_use_blocks,
        completed_results=completed_results,
        next_tool_index=next_tool_index,
        active_request=request,
    )
```

**Step 5: Change `_execute_tools()` to support suspension**

Change the signature:

```python
def _execute_tools(
    self,
    tool_use_blocks: list[dict],
    *,
    source_assistant_uuid,
) -> list[dict]:
```

Core behavior:

- Evaluate permission before executing each non-special tool
- On `deny`, append a normal tool result error and continue
- On `ask`, build a `PermissionRequest`, suspend the round, and return only the results already completed in this round
- On `allow`, execute normally

Use `build_permission_request(...)` from `bourbon.permissions.presentation`.

**Step 6: Add `resume_permission_request()`**

Implement:

```python
def resume_permission_request(self, choice: PermissionChoice) -> str:
    suspended = self.suspended_tool_round
    if suspended is None:
        return "Error: No suspended permission request."

    request = suspended.active_request
    self.active_permission_request = None

    if choice == PermissionChoice.ALLOW_SESSION and request.match_candidate:
        self.session_permissions.add(request.match_candidate)

    if choice == PermissionChoice.REJECT:
        resumed_results = suspended.completed_results + [
            {
                "type": "tool_result",
                "tool_use_id": request.tool_use_id,
                "content": f"Rejected by user: {request.reason}",
                "is_error": True,
            }
        ]
    else:
        resumed_results = list(suspended.completed_results)
        resumed_results.append(
            {
                "type": "tool_result",
                "tool_use_id": request.tool_use_id,
                "content": self._execute_regular_tool(request.tool_name, request.tool_input),
            }
        )

    remaining = suspended.tool_use_blocks[suspended.next_tool_index + 1 :]
    if remaining:
        resumed_results.extend(
            self._execute_tools(remaining, source_assistant_uuid=suspended.source_assistant_uuid)
        )
        if self.active_permission_request:
            return ""

    tool_turn_msg = self._build_tool_results_transcript_message(
        resumed_results,
        suspended.source_assistant_uuid,
    )
    self.session.add_message(tool_turn_msg)
    self.session.save()
    self.suspended_tool_round = None
    return self._run_conversation_loop()
```

**Step 7: Update the existing security tests**

In `tests/test_agent_security_integration.py`:

- Replace assertions against `pending_confirmation`
- Add `session_permissions`, `suspended_tool_round`, and `active_permission_request` to `make_agent_stub()`
- Update approval test to call `agent.resume_permission_request(PermissionChoice.ALLOW_ONCE)`

**Step 8: Run the tests to verify they pass**

Run:

```bash
uv run --extra dev pytest tests/test_agent_permission_runtime.py tests/test_agent_security_integration.py -v
```

Expected:

- PASS

**Step 9: Commit**

```bash
git add src/bourbon/agent.py src/bourbon/permissions/__init__.py tests/test_agent_permission_runtime.py tests/test_agent_security_integration.py
git commit -m "feat: suspend and resume tool rounds for permission requests"
```

---

### Task 4: Update REPL to Use the Dedicated Permission Resume API

**Files:**
- Modify: `src/bourbon/repl.py`
- Create: `tests/test_repl_permission_requests.py`
- Modify: `tests/test_repl_streaming.py`

**Step 1: Write the failing REPL tests**

```python
from unittest.mock import MagicMock

from bourbon.permissions.runtime import PermissionChoice, PermissionRequest
from bourbon.repl import REPL


def test_handle_permission_request_calls_resume_api_not_process_input():
    repl = object.__new__(REPL)
    repl.console = MagicMock()
    repl.style = None
    repl.agent = MagicMock()
    repl.session = MagicMock()
    repl._process_input = MagicMock()

    repl.agent.active_permission_request = PermissionRequest(
        request_id="req-1",
        tool_use_id="tool-1",
        tool_name="Bash",
        tool_input={"command": "pip install flask"},
        title="Bash command",
        description="pip install flask",
        reason="exec: need_approval (command.need_approval: pip install *)",
        match_candidate={"kind": "command_prefix", "value": "pip install"},
    )
    repl.session.prompt.return_value = "2"
    repl.agent.resume_permission_request.return_value = "done"

    repl._handle_permission_request()

    repl.agent.resume_permission_request.assert_called_once_with(PermissionChoice.ALLOW_SESSION)
    repl._process_input.assert_not_called()


def test_handle_permission_request_retries_on_invalid_choice():
    repl = object.__new__(REPL)
    repl.console = MagicMock()
    repl.style = None
    repl.agent = MagicMock()
    repl.session = MagicMock()
    repl.agent.active_permission_request = PermissionRequest(
        request_id="req-1",
        tool_use_id="tool-1",
        tool_name="Write",
        tool_input={"path": "notes/today.md", "content": "hello"},
        title="Write file",
        description="notes/today.md",
        reason="file_write: need_approval (default)",
        match_candidate={"kind": "parent_dir", "value": "notes"},
    )
    repl.session.prompt.side_effect = ["x", "1"]
    repl.agent.resume_permission_request.return_value = "done"

    repl._handle_permission_request()

    assert repl.agent.resume_permission_request.call_count == 1
    repl.console.print.assert_any_call("[red]Invalid choice. Please try again.[/red]")
```

**Step 2: Run the tests to verify they fail**

Run:

```bash
uv run --extra dev pytest tests/test_repl_permission_requests.py -v
```

Expected:

- FAIL because `_handle_permission_request()` does not exist

**Step 3: Replace the REPL confirmation flow**

In `src/bourbon/repl.py`:

- Rename `_handle_pending_confirmation()` to `_handle_permission_request()`
- Read `self.agent.active_permission_request`
- Render the structured request
- Map keys:
  - `1` -> `PermissionChoice.ALLOW_ONCE`
  - `2` -> `PermissionChoice.ALLOW_SESSION`
  - `3` -> `PermissionChoice.REJECT`

Implementation sketch:

```python
def _handle_permission_request(self) -> None:
    request = self.agent.active_permission_request
    if not request:
        return

    self.console.print()
    self.console.print(f"[bold yellow]{request.title}[/bold yellow]")
    self.console.print(f"[bold]Tool:[/bold] {request.tool_name}")
    self.console.print(f"[bold]Reason:[/bold] {request.reason}")
    self.console.print(f"[bold]Summary:[/bold] {request.description}")
    self.console.print()
    self.console.print("  [bold][1][/bold] Allow once")
    self.console.print("  [bold][2][/bold] Allow for session")
    self.console.print("  [bold][3][/bold] Reject")

    while True:
        choice = self.session.prompt("Enter your choice: ", style=self.style).strip()
        if choice == "1":
            response = self.agent.resume_permission_request(PermissionChoice.ALLOW_ONCE)
            break
        if choice == "2":
            response = self.agent.resume_permission_request(PermissionChoice.ALLOW_SESSION)
            break
        if choice == "3":
            response = self.agent.resume_permission_request(PermissionChoice.REJECT)
            break
        self.console.print("[red]Invalid choice. Please try again.[/red]")

    if response:
        self._print_response(response)
```

**Step 4: Update the streaming tests**

In `tests/test_repl_streaming.py`:

- Replace `repl._handle_pending_confirmation` mocks with `repl._handle_permission_request`
- Replace `agent.pending_confirmation` with `agent.active_permission_request`

**Step 5: Run the tests to verify they pass**

Run:

```bash
uv run --extra dev pytest tests/test_repl_permission_requests.py tests/test_repl_streaming.py -v
```

Expected:

- PASS

**Step 6: Commit**

```bash
git add src/bourbon/repl.py tests/test_repl_permission_requests.py tests/test_repl_streaming.py
git commit -m "feat: route repl confirmations through permission resume api"
```

---

### Task 5: Remove Legacy Confirmation Paths and Run Final Verification

**Files:**
- Modify: `src/bourbon/agent.py`
- Modify: `src/bourbon/repl.py`
- Modify: `tests/test_agent_security_integration.py`
- Modify: `tests/test_repl_streaming.py`
- Modify: `tests/test_policy.py`

**Step 1: Write one regression test for removing the legacy high-risk retry prompt**

```python
def test_failed_high_risk_command_returns_plain_error_without_followup_prompt(monkeypatch):
    agent = make_agent_stub()
    agent.access_controller.evaluate.return_value = allow_decision()
    registry = MagicMock()
    registry.call.return_value = "Error: command failed"
    monkeypatch.setattr("bourbon.agent.get_registry", lambda: registry)
    monkeypatch.setattr(
        "bourbon.agent.get_tool_with_metadata",
        lambda name: SimpleNamespace(
            is_destructive=True,
            is_high_risk_operation=lambda tool_input: True,
        ),
    )

    output = agent._execute_regular_tool("Bash", {"command": "pip install broken"})

    assert output == "Error: command failed"
    assert agent.active_permission_request is None
    assert agent.suspended_tool_round is None
```

**Step 2: Run the regression test to verify it fails**

Run:

```bash
uv run --extra dev pytest tests/test_agent_security_integration.py::test_failed_high_risk_command_returns_plain_error_without_followup_prompt -v
```

Expected:

- FAIL because the old post-error follow-up logic still exists

**Step 3: Delete the old retry prompt plumbing**

Remove from `src/bourbon/agent.py`:

- `_generate_options()`
- old branches that assign prompt state after a high-risk tool returns an error string

Remove from `src/bourbon/repl.py`:

- any remaining formatting or handling that assumes the old `PendingConfirmation` layout

**Step 4: Run the focused regression suite**

Run:

```bash
uv run --extra dev pytest \
  tests/test_permissions_runtime.py \
  tests/test_permissions_matching.py \
  tests/test_agent_permission_runtime.py \
  tests/test_agent_security_integration.py \
  tests/test_repl_permission_requests.py \
  tests/test_repl_streaming.py \
  tests/test_policy.py -q
```

Expected:

- PASS

**Step 5: Run the broad verification suite**

First ensure extras are installed:

```bash
uv pip install -e ".[dev,stage-b,loaders]"
```

Then run:

```bash
uv run pytest -q
```

Expected:

- PASS, or if unrelated pre-existing failures exist, capture them explicitly before merging

**Step 6: Commit**

```bash
git add src/bourbon/agent.py src/bourbon/repl.py tests/test_agent_security_integration.py tests/test_repl_streaming.py tests/test_policy.py
git commit -m "refactor: remove legacy confirmation flow"
```

---

## Final Review Checklist

- `pending_confirmation` no longer exists
- approval choices are exactly `allow once / allow for session / reject`
- session approvals are in-memory only
- REPL does not recurse back through `_process_input()` to approve a tool
- tool rounds resume in place after approval
- rejected approvals become `tool_result(is_error=True)`
- deny/audit/sandbox behavior still works

---

## Handoff

Plan complete and saved to `docs/plans/2026-04-09-user-confirmation-redesign-implementation.md`.

Two execution options:

**1. Subagent-Driven (this session)** - I dispatch fresh subagent per task, review between tasks, fast iteration

**2. Parallel Session (separate)** - Open new session with `superpowers:executing-plans`, batch execution with checkpoints

Which approach?
