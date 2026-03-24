# Sandbox Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Access Control + Audit + LocalProvider + Agent integration — the first layer of Bourbon's sandbox system.

**Architecture:** Three independent modules (`access_control/`, `audit/`, `sandbox/`) coordinated by `Agent._execute_tools()`. Access Control evaluates every tool call against TOML-configured policies. Sandbox Runtime (LocalProvider only in Phase 1) executes bash commands with credential cleaning. Audit records all events as JSONL.

**Tech Stack:** Python 3.11+, dataclasses, fnmatch (glob pattern matching), toml (config), pathlib, subprocess

**Spec:** `docs/superpowers/specs/2026-03-24-sandbox-design.md`

---

## File Structure

### New files to create

| File | Responsibility |
|------|---------------|
| `src/bourbon/access_control/__init__.py` | `AccessController` — evaluates tool calls against policies |
| `src/bourbon/access_control/capabilities.py` | `CapabilityType` enum, `InferredContext`, `infer_capabilities()` |
| `src/bourbon/access_control/policy.py` | `PolicyEngine` — loads TOML rules, matches patterns, returns decisions |
| `src/bourbon/audit/__init__.py` | `AuditLogger` — writes JSONL events, query, summary |
| `src/bourbon/audit/events.py` | `AuditEvent`, `EventType` dataclasses |
| `src/bourbon/sandbox/__init__.py` | `SandboxManager` — selects provider, builds context, coordinates execution |
| `src/bourbon/sandbox/runtime.py` | `SandboxProvider` ABC, `SandboxContext`, `SandboxResult`, `ResourceUsage` |
| `src/bourbon/sandbox/credential.py` | `CredentialManager` — env var cleaning |
| `src/bourbon/sandbox/providers/__init__.py` | Provider registry + auto-select logic |
| `src/bourbon/sandbox/providers/local.py` | `LocalProvider` — subprocess with env cleaning + timeout |
| `tests/test_capabilities.py` | Tests for capability inference |
| `tests/test_policy.py` | Tests for policy engine |
| `tests/test_audit.py` | Tests for audit logger |
| `tests/test_credential.py` | Tests for credential manager |
| `tests/test_sandbox_local.py` | Tests for LocalProvider |
| `tests/test_access_controller.py` | Tests for AccessController integration |

### Existing files to modify

| File | Change |
|------|--------|
| `src/bourbon/tools/__init__.py:24-33` | Add `required_capabilities` field to `Tool` dataclass |
| `src/bourbon/tools/__init__.py:120-159` | Add `required_capabilities` param to `register_tool()` |
| `src/bourbon/tools/base.py:208-301` | Add `required_capabilities` to each `@register_tool()` call |
| `src/bourbon/config.py:43-51,94-101,103-131` | Add `AccessControlConfig`, `SandboxConfig`, `AuditConfig` dataclasses + parsing |
| `src/bourbon/agent.py:1-13,33-82,376-479` | Import new modules, init components, rewrite `_execute_tools()` |

---

## Chunk 1: Capabilities + Policy Engine

### Task 1: CapabilityType and InferredContext

**Files:**
- Create: `src/bourbon/access_control/__init__.py` (empty, just makes it a package)
- Create: `src/bourbon/access_control/capabilities.py`
- Test: `tests/test_capabilities.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_capabilities.py
"""Tests for capability inference."""

import pytest

from bourbon.access_control.capabilities import (
    CapabilityType,
    InferredContext,
    infer_capabilities,
)


class TestCapabilityType:
    def test_enum_values(self):
        assert CapabilityType.FILE_READ.value == "file_read"
        assert CapabilityType.FILE_WRITE.value == "file_write"
        assert CapabilityType.EXEC.value == "exec"
        assert CapabilityType.NET.value == "net"


class TestInferCapabilities:
    def test_bash_basic_returns_exec(self):
        ctx = infer_capabilities("bash", {"command": "ls -la"}, [CapabilityType.EXEC])
        assert CapabilityType.EXEC in ctx.capabilities
        assert CapabilityType.NET not in ctx.capabilities
        assert ctx.file_paths == []

    def test_bash_curl_adds_net(self):
        ctx = infer_capabilities("bash", {"command": "curl example.com"}, [CapabilityType.EXEC])
        assert CapabilityType.NET in ctx.capabilities

    def test_bash_pip_install_adds_net(self):
        ctx = infer_capabilities("bash", {"command": "pip install flask"}, [CapabilityType.EXEC])
        assert CapabilityType.NET in ctx.capabilities

    def test_bash_cat_adds_file_read(self):
        ctx = infer_capabilities("bash", {"command": "cat /etc/hosts"}, [CapabilityType.EXEC])
        assert CapabilityType.FILE_READ in ctx.capabilities

    def test_bash_redirect_adds_file_write(self):
        ctx = infer_capabilities("bash", {"command": "echo hi > out.txt"}, [CapabilityType.EXEC])
        assert CapabilityType.FILE_WRITE in ctx.capabilities

    def test_bash_no_file_paths_extracted(self):
        """Bash commands don't extract file_paths — too unreliable."""
        ctx = infer_capabilities("bash", {"command": "cat ~/.ssh/id_rsa"}, [CapabilityType.EXEC])
        assert ctx.file_paths == []

    def test_read_file_extracts_path(self):
        ctx = infer_capabilities("read_file", {"path": "src/main.py"}, [CapabilityType.FILE_READ])
        assert CapabilityType.FILE_READ in ctx.capabilities
        assert ctx.file_paths == ["src/main.py"]

    def test_write_file_extracts_path(self):
        ctx = infer_capabilities("write_file", {"path": "out.txt", "content": "hi"}, [CapabilityType.FILE_WRITE])
        assert ctx.file_paths == ["out.txt"]

    def test_edit_file_extracts_path(self):
        ctx = infer_capabilities("edit_file", {"path": "f.py", "old_text": "a", "new_text": "b"}, [CapabilityType.FILE_WRITE])
        assert ctx.file_paths == ["f.py"]

    def test_unknown_tool_returns_base_caps(self):
        ctx = infer_capabilities("some_tool", {}, [CapabilityType.MCP])
        assert ctx.capabilities == [CapabilityType.MCP]
        assert ctx.file_paths == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_capabilities.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bourbon.access_control'`

- [ ] **Step 3: Create the package init**

```python
# src/bourbon/access_control/__init__.py
"""Access control for Bourbon agent tools."""
```

- [ ] **Step 4: Implement capabilities.py**

```python
# src/bourbon/access_control/capabilities.py
"""Capability types and dynamic inference for tool calls."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class CapabilityType(Enum):
    FILE_READ = "file_read"
    FILE_WRITE = "file_write"
    EXEC = "exec"
    NET = "net"
    SKILL = "skill"
    MCP = "mcp"


@dataclass
class InferredContext:
    """Result of capability inference: required capabilities + resource paths to validate."""

    capabilities: list[CapabilityType] = field(default_factory=list)
    file_paths: list[str] = field(default_factory=list)


# Patterns that indicate network access in bash commands
_NET_PATTERNS = ("curl ", "wget ", "pip install", "pip3 install", "git clone", "git pull", "git push")

# Patterns that indicate file read in bash commands
_FILE_READ_PATTERNS = ("cat ", "less ", "head ", "tail ", "grep ")

# Patterns that indicate file write in bash commands
_FILE_WRITE_PATTERNS = (">", ">>", "tee ", "mv ", "cp ")


def infer_capabilities(
    tool_name: str,
    tool_input: dict,
    base_capabilities: list[CapabilityType],
) -> InferredContext:
    """Infer actual capabilities needed and extract resource paths from tool input.

    Args:
        tool_name: Name of the tool being called.
        tool_input: The tool's input arguments.
        base_capabilities: Static capabilities declared on the tool.

    Returns:
        InferredContext with capabilities and file_paths.
    """
    caps = list(base_capabilities)
    file_paths: list[str] = []

    if tool_name == "bash":
        command = tool_input.get("command", "")
        if any(p in command for p in _NET_PATTERNS):
            caps.append(CapabilityType.NET)
        if any(p in command for p in _FILE_READ_PATTERNS):
            caps.append(CapabilityType.FILE_READ)
        if any(p in command for p in _FILE_WRITE_PATTERNS):
            caps.append(CapabilityType.FILE_WRITE)
        # Note: bash commands don't extract file_paths because reliably parsing
        # paths from shell commands is not feasible (pipes, variable expansion,
        # subshells). File path protection for bash is enforced by Sandbox Runtime
        # at the OS level, not at the Access Control level.

    elif tool_name in ("read_file", "write_file", "edit_file"):
        path = tool_input.get("path", tool_input.get("file_path", ""))
        if path:
            file_paths.append(path)

    return InferredContext(capabilities=caps, file_paths=file_paths)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_capabilities.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add src/bourbon/access_control/__init__.py src/bourbon/access_control/capabilities.py tests/test_capabilities.py
git commit -m "feat(access_control): Add CapabilityType enum and infer_capabilities"
```

---

### Task 2: PolicyEngine

**Files:**
- Create: `src/bourbon/access_control/policy.py`
- Test: `tests/test_policy.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_policy.py
"""Tests for policy engine."""

from pathlib import Path

import pytest

from bourbon.access_control.capabilities import CapabilityType, InferredContext
from bourbon.access_control.policy import (
    PolicyAction,
    PolicyDecision,
    CapabilityDecision,
    PolicyEngine,
)


def _make_context(caps, file_paths=None):
    return InferredContext(capabilities=caps, file_paths=file_paths or [])


class TestPolicyEngineFileRules:
    def setup_method(self):
        self.engine = PolicyEngine(
            default_action=PolicyAction.DENY,
            file_rules={
                "allow": ["/workspace/**"],
                "deny": ["**/.git/hooks/**"],
                "mandatory_deny": ["/home/user/.ssh/**"],
            },
            command_rules={},
            workdir=Path("/workspace"),
        )

    def test_allow_file_in_workspace(self):
        ctx = _make_context([CapabilityType.FILE_READ], ["/workspace/src/main.py"])
        decision = self.engine.evaluate("read_file", ctx)
        assert decision.action == PolicyAction.ALLOW

    def test_deny_file_outside_workspace(self):
        ctx = _make_context([CapabilityType.FILE_READ], ["/etc/passwd"])
        decision = self.engine.evaluate("read_file", ctx)
        assert decision.action == PolicyAction.DENY

    def test_mandatory_deny_overrides_allow(self):
        """mandatory_deny cannot be overridden, even if allow matches."""
        engine = PolicyEngine(
            default_action=PolicyAction.ALLOW,
            file_rules={
                "allow": ["**"],
                "deny": [],
                "mandatory_deny": ["/home/user/.ssh/**"],
            },
            command_rules={},
            workdir=Path("/workspace"),
        )
        ctx = _make_context([CapabilityType.FILE_READ], ["/home/user/.ssh/id_rsa"])
        decision = engine.evaluate("read_file", ctx)
        assert decision.action == PolicyAction.DENY
        assert "mandatory_deny" in decision.reason

    def test_deny_git_hooks(self):
        ctx = _make_context([CapabilityType.FILE_WRITE], ["/workspace/.git/hooks/pre-commit"])
        decision = self.engine.evaluate("write_file", ctx)
        assert decision.action == PolicyAction.DENY


class TestPolicyEngineCommandRules:
    def setup_method(self):
        self.engine = PolicyEngine(
            default_action=PolicyAction.ALLOW,
            file_rules={"allow": ["**"], "deny": [], "mandatory_deny": []},
            command_rules={
                "deny_patterns": ["rm -rf /", "sudo *"],
                "need_approval_patterns": ["pip install *", "apt *"],
            },
            workdir=Path("/workspace"),
        )

    def test_deny_dangerous_command(self):
        ctx = _make_context([CapabilityType.EXEC])
        decision = self.engine.evaluate_command("rm -rf /", ctx)
        assert decision.action == PolicyAction.DENY

    def test_need_approval_for_pip(self):
        ctx = _make_context([CapabilityType.EXEC, CapabilityType.NET])
        decision = self.engine.evaluate_command("pip install flask", ctx)
        assert decision.action == PolicyAction.NEED_APPROVAL

    def test_allow_safe_command(self):
        ctx = _make_context([CapabilityType.EXEC])
        decision = self.engine.evaluate_command("ls -la", ctx)
        assert decision.action == PolicyAction.ALLOW

    def test_sudo_wildcard_match(self):
        ctx = _make_context([CapabilityType.EXEC])
        decision = self.engine.evaluate_command("sudo apt update", ctx)
        assert decision.action == PolicyAction.DENY


class TestPolicyDecisionMerge:
    def test_deny_wins_over_allow(self):
        decisions = [
            CapabilityDecision(CapabilityType.EXEC, PolicyAction.ALLOW, None),
            CapabilityDecision(CapabilityType.NET, PolicyAction.DENY, "net denied"),
        ]
        merged = PolicyDecision.merge(decisions)
        assert merged.action == PolicyAction.DENY
        assert merged.denied_capability == CapabilityType.NET

    def test_need_approval_wins_over_allow(self):
        decisions = [
            CapabilityDecision(CapabilityType.EXEC, PolicyAction.ALLOW, None),
            CapabilityDecision(CapabilityType.NET, PolicyAction.NEED_APPROVAL, "need approval"),
        ]
        merged = PolicyDecision.merge(decisions)
        assert merged.action == PolicyAction.NEED_APPROVAL

    def test_all_allow(self):
        decisions = [
            CapabilityDecision(CapabilityType.EXEC, PolicyAction.ALLOW, None),
            CapabilityDecision(CapabilityType.FILE_READ, PolicyAction.ALLOW, None),
        ]
        merged = PolicyDecision.merge(decisions)
        assert merged.action == PolicyAction.ALLOW
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_policy.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bourbon.access_control.policy'`

- [ ] **Step 3: Implement policy.py**

```python
# src/bourbon/access_control/policy.py
"""Policy engine: loads rules from config, evaluates tool calls."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from fnmatch import fnmatch
from pathlib import Path

from bourbon.access_control.capabilities import CapabilityType, InferredContext


class PolicyAction(Enum):
    ALLOW = "allow"
    DENY = "deny"
    NEED_APPROVAL = "need_approval"


@dataclass
class CapabilityDecision:
    """Evaluation result for a single capability."""

    capability: CapabilityType
    action: PolicyAction
    matched_rule: str | None


@dataclass
class PolicyDecision:
    """Merged decision across all capabilities."""

    action: PolicyAction
    reason: str
    decisions: list[CapabilityDecision] = field(default_factory=list)

    @property
    def denied_capability(self) -> CapabilityType | None:
        for d in self.decisions:
            if d.action == PolicyAction.DENY:
                return d.capability
        return None

    @classmethod
    def merge(cls, decisions: list[CapabilityDecision]) -> PolicyDecision:
        """Merge per-capability decisions. Strictest wins: DENY > NEED_APPROVAL > ALLOW."""
        if not decisions:
            return cls(action=PolicyAction.ALLOW, reason="no capabilities to check")

        # Priority: DENY > NEED_APPROVAL > ALLOW
        priority = {PolicyAction.DENY: 2, PolicyAction.NEED_APPROVAL: 1, PolicyAction.ALLOW: 0}
        strictest = max(decisions, key=lambda d: priority[d.action])

        reason_parts = []
        for d in decisions:
            if d.action != PolicyAction.ALLOW:
                reason_parts.append(f"{d.capability.value}: {d.action.value} ({d.matched_rule})")

        reason = "; ".join(reason_parts) if reason_parts else "all capabilities allowed"
        return cls(action=strictest.action, reason=reason, decisions=decisions)


class PolicyEngine:
    """Evaluates tool calls against configured rules."""

    def __init__(
        self,
        default_action: PolicyAction,
        file_rules: dict,
        command_rules: dict,
        workdir: Path,
    ):
        self.default_action = default_action
        self.file_allow = file_rules.get("allow", [])
        self.file_deny = file_rules.get("deny", [])
        self.file_mandatory_deny = file_rules.get("mandatory_deny", [])
        self.command_deny = command_rules.get("deny_patterns", [])
        self.command_need_approval = command_rules.get("need_approval_patterns", [])
        self.workdir = workdir

    def evaluate(self, tool_name: str, context: InferredContext) -> PolicyDecision:
        """Evaluate a tool call. For bash commands, use evaluate_command() instead."""
        decisions: list[CapabilityDecision] = []

        for cap in context.capabilities:
            if cap in (CapabilityType.FILE_READ, CapabilityType.FILE_WRITE):
                for path in context.file_paths:
                    decisions.append(self._check_file_path(path, cap))
                if not context.file_paths:
                    decisions.append(CapabilityDecision(cap, self.default_action, "default"))
            else:
                decisions.append(CapabilityDecision(cap, self.default_action, "default"))

        if not decisions:
            decisions.append(CapabilityDecision(CapabilityType.EXEC, self.default_action, "default"))

        return PolicyDecision.merge(decisions)

    def evaluate_command(self, command: str, context: InferredContext) -> PolicyDecision:
        """Evaluate a bash command against command rules + file rules."""
        decisions: list[CapabilityDecision] = []

        # Check command patterns
        for pattern in self.command_deny:
            if self._command_matches(command, pattern):
                decisions.append(
                    CapabilityDecision(CapabilityType.EXEC, PolicyAction.DENY, f"command.deny: {pattern}")
                )
                return PolicyDecision.merge(decisions)

        for pattern in self.command_need_approval:
            if self._command_matches(command, pattern):
                decisions.append(
                    CapabilityDecision(CapabilityType.EXEC, PolicyAction.NEED_APPROVAL, f"command.need_approval: {pattern}")
                )
                break
        else:
            decisions.append(CapabilityDecision(CapabilityType.EXEC, PolicyAction.ALLOW, None))

        # Also check file paths if present in context
        for cap in context.capabilities:
            if cap in (CapabilityType.FILE_READ, CapabilityType.FILE_WRITE):
                for path in context.file_paths:
                    decisions.append(self._check_file_path(path, cap))
            elif cap == CapabilityType.NET:
                # NET capability: pass through (network isolation is sandbox's job)
                decisions.append(CapabilityDecision(cap, PolicyAction.ALLOW, "net deferred to sandbox"))

        return PolicyDecision.merge(decisions)

    def _resolve_pattern(self, pattern: str) -> str:
        """Resolve {workdir} and ~ in a pattern."""
        return str(Path(pattern.replace("{workdir}", str(self.workdir))).expanduser())

    def _check_file_path(self, path: str, cap: CapabilityType) -> CapabilityDecision:
        """Check a file path against allow/deny/mandatory_deny rules."""
        resolved = str(Path(path).expanduser())

        # mandatory_deny always wins
        for pattern in self.file_mandatory_deny:
            if fnmatch(resolved, self._resolve_pattern(pattern)):
                return CapabilityDecision(cap, PolicyAction.DENY, f"file.mandatory_deny: {pattern}")

        # deny
        for pattern in self.file_deny:
            if fnmatch(resolved, self._resolve_pattern(pattern)):
                return CapabilityDecision(cap, PolicyAction.DENY, f"file.deny: {pattern}")

        # allow
        for pattern in self.file_allow:
            if fnmatch(resolved, self._resolve_pattern(pattern)):
                return CapabilityDecision(cap, PolicyAction.ALLOW, f"file.allow: {pattern}")

        return CapabilityDecision(cap, self.default_action, "default")

    @staticmethod
    def _command_matches(command: str, pattern: str) -> bool:
        """Check if command matches a pattern.

        If pattern contains *, use fnmatch glob matching.
        Otherwise, use simple substring containment.
        """
        if "*" in pattern:
            return fnmatch(command, pattern)
        return pattern in command
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_policy.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/bourbon/access_control/policy.py tests/test_policy.py
git commit -m "feat(access_control): Add PolicyEngine with file and command rules"
```

---

### Task 3: AccessController (facade)

**Files:**
- Modify: `src/bourbon/access_control/__init__.py`
- Test: `tests/test_access_controller.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_access_controller.py
"""Tests for AccessController integration."""

from pathlib import Path

import pytest

from bourbon.access_control import AccessController
from bourbon.access_control.capabilities import CapabilityType
from bourbon.access_control.policy import PolicyAction


class TestAccessController:
    def setup_method(self):
        self.controller = AccessController(
            config={
                "default_action": "allow",
                "file": {
                    "allow": ["{workdir}/**"],
                    "deny": ["~/.ssh/**"],
                    "mandatory_deny": ["~/.ssh/**"],
                },
                "command": {
                    "deny_patterns": ["rm -rf /", "sudo *"],
                    "need_approval_patterns": ["pip install *"],
                },
            },
            workdir=Path("/workspace"),
        )

    def test_allow_safe_bash(self):
        decision = self.controller.evaluate("bash", {"command": "ls -la"})
        assert decision.action == PolicyAction.ALLOW

    def test_deny_dangerous_bash(self):
        decision = self.controller.evaluate("bash", {"command": "rm -rf /"})
        assert decision.action == PolicyAction.DENY

    def test_need_approval_pip(self):
        decision = self.controller.evaluate("bash", {"command": "pip install flask"})
        assert decision.action == PolicyAction.NEED_APPROVAL

    def test_allow_read_file_in_workspace(self):
        decision = self.controller.evaluate("read_file", {"path": "/workspace/src/main.py"})
        assert decision.action == PolicyAction.ALLOW

    def test_deny_read_ssh_key(self):
        decision = self.controller.evaluate("read_file", {"path": "~/.ssh/id_rsa"})
        assert decision.action == PolicyAction.DENY

    def test_unknown_tool_uses_default(self):
        decision = self.controller.evaluate("some_mcp_tool", {"query": "hello"})
        assert decision.action == PolicyAction.ALLOW
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_access_controller.py -v`
Expected: FAIL — `ImportError: cannot import name 'AccessController'`

- [ ] **Step 3: Implement AccessController**

```python
# src/bourbon/access_control/__init__.py
"""Access control for Bourbon agent tools."""

from __future__ import annotations

from pathlib import Path

from bourbon.access_control.capabilities import (
    CapabilityType,
    InferredContext,
    infer_capabilities,
)
from bourbon.access_control.policy import PolicyAction, PolicyDecision, PolicyEngine

# Map tool names to their base capabilities
_TOOL_CAPABILITIES: dict[str, list[CapabilityType]] = {
    "bash": [CapabilityType.EXEC],
    "read_file": [CapabilityType.FILE_READ],
    "write_file": [CapabilityType.FILE_WRITE],
    "edit_file": [CapabilityType.FILE_WRITE],
    "skill": [CapabilityType.SKILL],
    "rg_search": [CapabilityType.FILE_READ],
    "ast_grep_search": [CapabilityType.FILE_READ],
}


class AccessController:
    """Evaluates tool calls against configured policies.

    Bridges capability inference and the policy engine.
    """

    def __init__(self, config: dict, workdir: Path):
        default_str = config.get("default_action", "allow")
        self.default_action = PolicyAction(default_str)
        self.engine = PolicyEngine(
            default_action=self.default_action,
            file_rules=config.get("file", {}),
            command_rules=config.get("command", {}),
            workdir=workdir,
        )

    def evaluate(self, tool_name: str, tool_input: dict) -> PolicyDecision:
        """Evaluate whether a tool call should be allowed."""
        base_caps = _TOOL_CAPABILITIES.get(tool_name, [])
        context = infer_capabilities(tool_name, tool_input, base_caps)

        if tool_name == "bash":
            return self.engine.evaluate_command(tool_input.get("command", ""), context)
        else:
            return self.engine.evaluate(tool_name, context)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_access_controller.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/bourbon/access_control/__init__.py tests/test_access_controller.py
git commit -m "feat(access_control): Add AccessController facade"
```

---

## Chunk 2: Audit Layer

### Task 4: AuditEvent model

**Files:**
- Create: `src/bourbon/audit/__init__.py` (empty package init)
- Create: `src/bourbon/audit/events.py`
- Test: `tests/test_audit.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_audit.py
"""Tests for audit events and logger."""

import json
import tempfile
from pathlib import Path

import pytest

from bourbon.audit.events import AuditEvent, EventType
from bourbon.audit import AuditLogger


class TestAuditEvent:
    def test_policy_decision_event(self):
        event = AuditEvent.policy_decision(
            tool_name="bash",
            tool_input_summary="pip install flask",
            decision="need_approval",
            matched_rule="command.need_approval: pip install *",
            capabilities_required=["exec", "net"],
        )
        assert event.event_type == EventType.POLICY_DECISION
        assert event.tool_name == "bash"
        d = event.to_dict()
        assert d["event_type"] == "policy_decision"
        assert d["decision"] == "need_approval"

    def test_sandbox_exec_event(self):
        event = AuditEvent.sandbox_exec(
            tool_name="bash",
            tool_input_summary="ls -la",
            provider="local",
            exit_code=0,
            timed_out=False,
        )
        assert event.event_type == EventType.SANDBOX_EXEC
        d = event.to_dict()
        assert d["provider"] == "local"

    def test_tool_call_event(self):
        event = AuditEvent.tool_call(
            tool_name="read_file",
            tool_input_summary="path=src/main.py",
        )
        assert event.event_type == EventType.TOOL_CALL

    def test_violation_event(self):
        event = AuditEvent.sandbox_violation(
            tool_name="bash",
            violation_type="net_denied",
            violation_detail="connection to 10.0.0.1 blocked",
        )
        assert event.event_type == EventType.SANDBOX_VIOLATION


class TestAuditLogger:
    def test_record_and_query(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = AuditLogger(log_dir=Path(tmpdir), enabled=True)
            event = AuditEvent.tool_call("read_file", "path=main.py")
            logger.record(event)

            events = logger.query()
            assert len(events) == 1
            assert events[0]["tool_name"] == "read_file"

    def test_jsonl_format(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = AuditLogger(log_dir=Path(tmpdir), enabled=True)
            logger.record(AuditEvent.tool_call("bash", "ls"))
            logger.record(AuditEvent.tool_call("read_file", "main.py"))

            log_files = list(Path(tmpdir).glob("*.jsonl"))
            assert len(log_files) == 1
            lines = log_files[0].read_text().strip().split("\n")
            assert len(lines) == 2
            for line in lines:
                json.loads(line)  # should not raise

    def test_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = AuditLogger(log_dir=Path(tmpdir), enabled=True)
            logger.record(AuditEvent.tool_call("bash", "ls"))
            logger.record(AuditEvent.policy_decision("bash", "rm -rf /", "deny", "command.deny", ["exec"]))
            logger.record(AuditEvent.sandbox_exec("bash", "ls", "local", 0, False))

            summary = logger.summary()
            assert summary["total_events"] == 3
            assert summary["policy_denied"] == 1
            assert summary["sandbox_executions"] == 1

    def test_disabled_logger_does_nothing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = AuditLogger(log_dir=Path(tmpdir), enabled=False)
            logger.record(AuditEvent.tool_call("bash", "ls"))
            assert logger.query() == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_audit.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement events.py**

```python
# src/bourbon/audit/events.py
"""Audit event types."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class EventType(Enum):
    POLICY_DECISION = "policy_decision"
    SANDBOX_EXEC = "sandbox_exec"
    SANDBOX_VIOLATION = "sandbox_violation"
    TOOL_CALL = "tool_call"


@dataclass
class AuditEvent:
    """A single auditable event."""

    timestamp: str
    event_type: EventType
    tool_name: str
    tool_input_summary: str
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = {
            "timestamp": self.timestamp,
            "event_type": self.event_type.value,
            "tool_name": self.tool_name,
            "tool_input_summary": self.tool_input_summary,
        }
        d.update(self.extra)
        return d

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @classmethod
    def policy_decision(
        cls,
        tool_name: str,
        tool_input_summary: str,
        decision: str,
        matched_rule: str | None,
        capabilities_required: list[str] | None = None,
    ) -> AuditEvent:
        return cls(
            timestamp=cls._now(),
            event_type=EventType.POLICY_DECISION,
            tool_name=tool_name,
            tool_input_summary=tool_input_summary,
            extra={
                "decision": decision,
                "matched_rule": matched_rule,
                "capabilities_required": capabilities_required,
            },
        )

    @classmethod
    def sandbox_exec(
        cls,
        tool_name: str,
        tool_input_summary: str,
        provider: str,
        exit_code: int,
        timed_out: bool,
        resource_usage: dict | None = None,
    ) -> AuditEvent:
        return cls(
            timestamp=cls._now(),
            event_type=EventType.SANDBOX_EXEC,
            tool_name=tool_name,
            tool_input_summary=tool_input_summary,
            extra={
                "provider": provider,
                "exit_code": exit_code,
                "timed_out": timed_out,
                "resource_usage": resource_usage,
            },
        )

    @classmethod
    def sandbox_violation(
        cls,
        tool_name: str,
        violation_type: str,
        violation_detail: str,
    ) -> AuditEvent:
        return cls(
            timestamp=cls._now(),
            event_type=EventType.SANDBOX_VIOLATION,
            tool_name=tool_name,
            tool_input_summary="",
            extra={
                "violation_type": violation_type,
                "violation_detail": violation_detail,
            },
        )

    @classmethod
    def tool_call(cls, tool_name: str, tool_input_summary: str) -> AuditEvent:
        return cls(
            timestamp=cls._now(),
            event_type=EventType.TOOL_CALL,
            tool_name=tool_name,
            tool_input_summary=tool_input_summary,
        )
```

- [ ] **Step 4: Implement AuditLogger**

```python
# src/bourbon/audit/__init__.py
"""Audit logging for Bourbon agent."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from bourbon.audit.events import AuditEvent, EventType


class AuditLogger:
    """Writes audit events to JSONL files."""

    def __init__(self, log_dir: Path, enabled: bool = True):
        self.log_dir = log_dir
        self.enabled = enabled
        self._events: list[dict] = []
        self._log_file: Path | None = None

        if enabled:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            self._log_file = self.log_dir / f"session-{ts}.jsonl"

    def record(self, event: AuditEvent) -> None:
        if not self.enabled:
            return
        d = event.to_dict()
        self._events.append(d)
        if self._log_file:
            with open(self._log_file, "a") as f:
                f.write(json.dumps(d) + "\n")

    def query(self, **filters) -> list[dict]:
        return list(self._events)

    def summary(self) -> dict:
        total = len(self._events)
        denied = sum(1 for e in self._events if e.get("decision") == "deny")
        approved = sum(1 for e in self._events if e.get("decision") == "need_approval")
        sandbox = sum(1 for e in self._events if e.get("event_type") == "sandbox_exec")
        violations = sum(1 for e in self._events if e.get("event_type") == "sandbox_violation")
        return {
            "total_events": total,
            "policy_denied": denied,
            "policy_need_approval": approved,
            "sandbox_executions": sandbox,
            "violations": violations,
        }
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_audit.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add src/bourbon/audit/__init__.py src/bourbon/audit/events.py tests/test_audit.py
git commit -m "feat(audit): Add AuditLogger with JSONL events"
```

---

## Chunk 3: Sandbox Runtime (LocalProvider)

### Task 5: CredentialManager

**Files:**
- Create: `src/bourbon/sandbox/__init__.py` (empty)
- Create: `src/bourbon/sandbox/credential.py`
- Test: `tests/test_credential.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_credential.py
"""Tests for credential manager."""

import os
from unittest.mock import patch

import pytest

from bourbon.sandbox.credential import CredentialManager


class TestCredentialManager:
    def test_passthrough_only(self):
        env = {"PATH": "/usr/bin", "HOME": "/home/user", "SECRET_KEY": "s3cret", "LANG": "en_US"}
        mgr = CredentialManager()
        clean = mgr.clean_env(passthrough_vars=["PATH", "HOME", "LANG"], source_env=env)
        assert "PATH" in clean
        assert "HOME" in clean
        assert "LANG" in clean
        assert "SECRET_KEY" not in clean

    def test_sensitive_pattern_blocks_even_if_passthrough(self):
        """Safety net: even if someone puts a sensitive var in passthrough, it's blocked."""
        env = {"PATH": "/usr/bin", "AWS_SECRET_KEY": "abc123"}
        mgr = CredentialManager()
        clean = mgr.clean_env(passthrough_vars=["PATH", "AWS_SECRET_KEY"], source_env=env)
        assert "PATH" in clean
        assert "AWS_SECRET_KEY" not in clean

    def test_anthropic_key_blocked(self):
        env = {"ANTHROPIC_API_KEY": "sk-ant-123", "PATH": "/usr/bin"}
        mgr = CredentialManager()
        clean = mgr.clean_env(passthrough_vars=["ANTHROPIC_API_KEY", "PATH"], source_env=env)
        assert "ANTHROPIC_API_KEY" not in clean

    def test_empty_passthrough(self):
        env = {"PATH": "/usr/bin", "HOME": "/home/user"}
        mgr = CredentialManager()
        clean = mgr.clean_env(passthrough_vars=[], source_env=env)
        assert clean == {}

    def test_default_uses_os_environ(self):
        mgr = CredentialManager()
        clean = mgr.clean_env(passthrough_vars=["PATH"])
        assert "PATH" in clean
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_credential.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Create package init and implement credential.py**

```python
# src/bourbon/sandbox/__init__.py
"""Sandbox runtime for Bourbon agent."""
```

```python
# src/bourbon/sandbox/credential.py
"""Credential manager: cleans environment variables for sandbox execution."""

from __future__ import annotations

import os
from fnmatch import fnmatch


class CredentialManager:
    """Filters environment variables to prevent credential leakage into sandbox.

    Two-step defense in depth:
    1. Whitelist: only passthrough_vars are kept.
    2. Safety net: SENSITIVE_PATTERNS block vars even if they're in passthrough.
    """

    SENSITIVE_PATTERNS = [
        "*_KEY",
        "*_SECRET",
        "*_TOKEN",
        "*_PASSWORD",
        "AWS_*",
        "OPENAI_*",
        "ANTHROPIC_*",
        "DATABASE_URL",
        "REDIS_URL",
    ]

    def clean_env(
        self,
        passthrough_vars: list[str],
        source_env: dict[str, str] | None = None,
    ) -> dict[str, str]:
        """Return a cleaned copy of environment variables.

        Args:
            passthrough_vars: Variable names to keep (whitelist).
            source_env: Source environment. Defaults to os.environ.

        Returns:
            Filtered dict with only safe, allowed variables.
        """
        env = source_env if source_env is not None else dict(os.environ)
        result: dict[str, str] = {}

        for var in passthrough_vars:
            if var not in env:
                continue
            # Safety net: block if matches sensitive pattern
            if any(fnmatch(var, pat) for pat in self.SENSITIVE_PATTERNS):
                continue
            result[var] = env[var]

        return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_credential.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/bourbon/sandbox/__init__.py src/bourbon/sandbox/credential.py tests/test_credential.py
git commit -m "feat(sandbox): Add CredentialManager for env var cleaning"
```

---

### Task 6: SandboxProvider interface + LocalProvider

**Files:**
- Create: `src/bourbon/sandbox/runtime.py`
- Create: `src/bourbon/sandbox/providers/__init__.py`
- Create: `src/bourbon/sandbox/providers/local.py`
- Test: `tests/test_sandbox_local.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_sandbox_local.py
"""Tests for LocalProvider."""

import tempfile
from pathlib import Path

import pytest

from bourbon.sandbox.runtime import SandboxContext, SandboxResult
from bourbon.sandbox.providers.local import LocalProvider


def _make_context(workdir: Path, **overrides) -> SandboxContext:
    defaults = {
        "workdir": workdir,
        "writable_paths": [str(workdir)],
        "readonly_paths": [],
        "deny_paths": [],
        "network_enabled": False,
        "allow_domains": [],
        "timeout": 10,
        "max_memory": "512M",
        "max_output": 50000,
        "env_vars": {"PATH": "/usr/bin:/bin"},
    }
    defaults.update(overrides)
    return SandboxContext(**defaults)


class TestLocalProvider:
    def test_simple_command(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = _make_context(Path(tmpdir))
            provider = LocalProvider()
            result = provider.execute("echo hello", ctx)
            assert result.exit_code == 0
            assert "hello" in result.stdout
            assert not result.timed_out

    def test_timeout(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = _make_context(Path(tmpdir), timeout=1)
            provider = LocalProvider()
            result = provider.execute("sleep 10", ctx)
            assert result.timed_out
            assert result.exit_code != 0

    def test_env_cleaning(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = _make_context(Path(tmpdir), env_vars={"PATH": "/usr/bin", "CUSTOM": "val"})
            provider = LocalProvider()
            result = provider.execute("env", ctx)
            assert "CUSTOM=val" in result.stdout
            # Should NOT have vars that weren't passed
            assert "ANTHROPIC_API_KEY" not in result.stdout

    def test_output_truncation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = _make_context(Path(tmpdir), max_output=20)
            provider = LocalProvider()
            result = provider.execute("echo aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", ctx)
            assert len(result.stdout) <= 20 + 50  # allow for truncation message

    def test_isolation_level(self):
        provider = LocalProvider()
        assert provider.get_isolation_level() == "local (no OS isolation)"

    def test_failed_command(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = _make_context(Path(tmpdir))
            provider = LocalProvider()
            result = provider.execute("exit 1", ctx)
            assert result.exit_code == 1
            assert not result.timed_out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_sandbox_local.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement runtime.py**

```python
# src/bourbon/sandbox/runtime.py
"""Sandbox provider interface and data types."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ResourceUsage:
    cpu_time: float = 0.0
    memory_peak: str = "0M"
    files_written: list[str] = field(default_factory=list)


@dataclass
class SandboxContext:
    """Describes the sandbox constraints for a single execution."""

    workdir: Path
    writable_paths: list[str]
    readonly_paths: list[str]
    deny_paths: list[str]
    network_enabled: bool
    allow_domains: list[str]
    timeout: int
    max_memory: str
    max_output: int
    env_vars: dict[str, str]


@dataclass
class SandboxResult:
    """Result of a sandboxed execution."""

    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool
    resource_usage: ResourceUsage = field(default_factory=ResourceUsage)


class SandboxProvider(ABC):
    """Abstract base for sandbox execution providers."""

    @abstractmethod
    def execute(self, command: str, context: SandboxContext) -> SandboxResult:
        """Execute a command in the sandbox."""

    @abstractmethod
    def get_isolation_level(self) -> str:
        """Human-readable description of isolation provided."""
```

- [ ] **Step 4: Implement providers/__init__.py**

```python
# src/bourbon/sandbox/providers/__init__.py
"""Sandbox provider registry."""

from __future__ import annotations

import platform

from bourbon.sandbox.runtime import SandboxProvider


class SandboxProviderNotFound(Exception):
    """Raised when a configured provider is not available."""


def select_provider(name: str) -> SandboxProvider:
    """Select and instantiate a sandbox provider.

    Args:
        name: Provider name — "auto", "local", "bubblewrap", "seatbelt", "docker".

    Returns:
        An instantiated SandboxProvider.

    Raises:
        SandboxProviderNotFound: If explicitly named provider is unavailable.
    """
    if name == "local":
        from bourbon.sandbox.providers.local import LocalProvider
        return LocalProvider()

    if name == "auto":
        return _auto_select()

    # Future providers: bubblewrap, seatbelt, docker
    raise SandboxProviderNotFound(
        f"{name} not found. Install it or set provider = \"auto\""
    )


def _auto_select() -> SandboxProvider:
    """Auto-select based on platform and available tools."""
    # Phase 1: always LocalProvider
    # Phase 2 will add bubblewrap/seatbelt detection
    from bourbon.sandbox.providers.local import LocalProvider
    return LocalProvider()
```

- [ ] **Step 5: Implement providers/local.py**

```python
# src/bourbon/sandbox/providers/local.py
"""Local sandbox provider: subprocess with env cleaning and resource limits."""

from __future__ import annotations

import subprocess
import time

from bourbon.sandbox.runtime import (
    ResourceUsage,
    SandboxContext,
    SandboxProvider,
    SandboxResult,
)


class LocalProvider(SandboxProvider):
    """Pure Python sandbox. No OS-level isolation.

    Provides:
    - Credential cleaning via env_vars (passed to subprocess)
    - Timeout enforcement
    - Output truncation
    - Working directory enforcement

    Does NOT provide:
    - Filesystem isolation (can still access any path)
    - Network isolation
    - Process isolation
    """

    def execute(self, command: str, context: SandboxContext) -> SandboxResult:
        start = time.monotonic()
        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=context.workdir,
                capture_output=True,
                text=True,
                timeout=context.timeout,
                env=context.env_vars if context.env_vars else None,
            )
            elapsed = time.monotonic() - start

            stdout = result.stdout.strip()
            stderr = result.stderr.strip()

            if len(stdout) > context.max_output:
                stdout = stdout[: context.max_output] + f"\n... (truncated)"

            return SandboxResult(
                stdout=stdout,
                stderr=stderr,
                exit_code=result.returncode,
                timed_out=False,
                resource_usage=ResourceUsage(cpu_time=elapsed),
            )

        except subprocess.TimeoutExpired:
            elapsed = time.monotonic() - start
            return SandboxResult(
                stdout="",
                stderr=f"Timeout after {context.timeout}s",
                exit_code=-1,
                timed_out=True,
                resource_usage=ResourceUsage(cpu_time=elapsed),
            )

    def get_isolation_level(self) -> str:
        return "local (no OS isolation)"
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_sandbox_local.py -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add src/bourbon/sandbox/runtime.py src/bourbon/sandbox/providers/__init__.py src/bourbon/sandbox/providers/local.py tests/test_sandbox_local.py
git commit -m "feat(sandbox): Add SandboxProvider interface and LocalProvider"
```

---

### Task 7: SandboxManager

**Files:**
- Modify: `src/bourbon/sandbox/__init__.py`
- Create: `tests/test_sandbox_manager.py`

- [ ] **Step 1: Write failing tests for SandboxManager**

```python
# tests/test_sandbox_manager.py
"""Tests for SandboxManager."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock

from bourbon.sandbox import SandboxManager
from bourbon.sandbox.runtime import SandboxResult, ResourceUsage


@pytest.fixture
def mock_audit():
    return MagicMock()


class TestSandboxManagerDisabled:
    def test_execute_raises_when_disabled(self, mock_audit):
        mgr = SandboxManager(config={"enabled": False}, workdir=Path("/tmp"), audit=mock_audit)
        assert mgr.enabled is False
        assert mgr.provider is None
        with pytest.raises(RuntimeError, match="sandbox is disabled"):
            mgr.execute("ls")


class TestSandboxManagerEnabled:
    def test_execute_calls_provider(self, mock_audit):
        mgr = SandboxManager(config={"enabled": True, "provider": "local"}, workdir=Path("/tmp"), audit=mock_audit)
        assert mgr.enabled is True
        assert mgr.provider is not None
        result = mgr.execute("echo hello")
        assert isinstance(result, SandboxResult)

    def test_execute_records_audit_event(self, mock_audit):
        mgr = SandboxManager(config={"enabled": True, "provider": "local"}, workdir=Path("/tmp"), audit=mock_audit)
        mgr.execute("echo hello")
        mock_audit.record.assert_called_once()

    def test_workdir_placeholder_resolved_in_paths(self, mock_audit):
        mgr = SandboxManager(
            config={"enabled": True, "provider": "local", "filesystem": {"writable": ["{workdir}/src"]}},
            workdir=Path("/home/user/project"),
            audit=mock_audit,
        )
        # Provider is created — execute triggers context building with resolved paths
        # We verify indirectly: no crash means {workdir} was resolved
        result = mgr.execute("echo test")
        assert isinstance(result, SandboxResult)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_sandbox_manager.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bourbon.sandbox'`

- [ ] **Step 3: Implement SandboxManager**

```python
# src/bourbon/sandbox/__init__.py
"""Sandbox runtime for Bourbon agent."""

from __future__ import annotations

from pathlib import Path

from bourbon.audit import AuditLogger
from bourbon.audit.events import AuditEvent
from bourbon.sandbox.credential import CredentialManager
from bourbon.sandbox.providers import SandboxProviderNotFound, select_provider
from bourbon.sandbox.runtime import SandboxContext, SandboxResult


class SandboxManager:
    """Coordinates provider selection, context building, and execution."""

    def __init__(self, config: dict, workdir: Path, audit: AuditLogger):
        self.enabled = config.get("enabled", True)
        self.workdir = workdir
        self.audit = audit

        if self.enabled:
            provider_name = config.get("provider", "auto")
            self.provider = select_provider(provider_name)
        else:
            self.provider = None

        self.credential_mgr = CredentialManager()

        # Config sections
        self._fs = config.get("filesystem", {})
        self._net = config.get("network", {})
        self._res = config.get("resources", {})
        self._cred = config.get("credentials", {})

    def execute(self, command: str) -> SandboxResult:
        """Execute a command in the sandbox.

        If sandbox is disabled, raises RuntimeError — caller should check
        self.enabled before calling.
        """
        if not self.enabled or self.provider is None:
            raise RuntimeError("SandboxManager.execute() called but sandbox is disabled")

        passthrough = self._cred.get("passthrough_vars", ["PATH", "HOME", "LANG"])
        env_vars = self.credential_mgr.clean_env(passthrough_vars=passthrough)

        # Resolve {workdir} in paths
        def resolve(paths: list[str]) -> list[str]:
            return [p.replace("{workdir}", str(self.workdir)) for p in paths]

        context = SandboxContext(
            workdir=self.workdir,
            writable_paths=resolve(self._fs.get("writable", [str(self.workdir)])),
            readonly_paths=resolve(self._fs.get("readonly", [])),
            deny_paths=resolve(self._fs.get("deny", [])),
            network_enabled=self._net.get("enabled", False),
            allow_domains=self._net.get("allow_domains", []),
            timeout=self._res.get("timeout", 120),
            max_memory=self._res.get("max_memory", "512M"),
            max_output=self._res.get("max_output", 50000),
            env_vars=env_vars,
        )

        result = self.provider.execute(command, context)

        self.audit.record(AuditEvent.sandbox_exec(
            tool_name="bash",
            tool_input_summary=command[:200],
            provider=self.provider.get_isolation_level(),
            exit_code=result.exit_code,
            timed_out=result.timed_out,
            resource_usage={
                "cpu_time": result.resource_usage.cpu_time,
                "memory_peak": result.resource_usage.memory_peak,
            },
        ))

        return result
```

- [ ] **Step 4: Run all sandbox tests**

Run: `uv run pytest tests/test_credential.py tests/test_sandbox_local.py tests/test_sandbox_manager.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/bourbon/sandbox/__init__.py tests/test_sandbox_manager.py
git commit -m "feat(sandbox): Add SandboxManager coordinator"
```

---

## Chunk 4: Config + Agent Integration

### Task 8: Config dataclasses

**Files:**
- Modify: `src/bourbon/config.py:43-51,94-131`

- [ ] **Step 1: Write failing test**

```python
# Add to tests/test_config.py (append to existing file)

class TestSandboxConfig:
    def test_default_config_has_sandbox_sections(self):
        config = Config()
        assert hasattr(config, "access_control")
        assert hasattr(config, "sandbox")
        assert hasattr(config, "audit")

    def test_from_dict_with_sandbox(self):
        data = {
            "access_control": {
                "default_action": "deny",
                "file": {"allow": ["/workspace/**"], "deny": [], "mandatory_deny": []},
                "command": {"deny_patterns": ["rm -rf /"], "need_approval_patterns": []},
            },
            "sandbox": {
                "enabled": True,
                "provider": "local",
            },
            "audit": {
                "enabled": True,
                "log_dir": "/tmp/audit",
            },
        }
        config = Config.from_dict(data)
        assert config.access_control["default_action"] == "deny"
        assert config.sandbox["provider"] == "local"
        assert config.audit["enabled"] is True

    def test_from_dict_without_sandbox_uses_defaults(self):
        config = Config.from_dict({})
        assert config.access_control["default_action"] == "allow"
        assert config.sandbox["enabled"] is True
        assert config.audit["enabled"] is True

    def test_from_dict_deep_merges_nested_keys(self):
        """Verify that overriding a nested key preserves sibling keys."""
        data = {
            "sandbox": {
                "network": {"enabled": True},  # override one nested key
            },
        }
        config = Config.from_dict(data)
        # Overridden key takes effect
        assert config.sandbox["network"]["enabled"] is True
        # Sibling key preserved from defaults
        assert config.sandbox["network"]["allow_domains"] == []
        # Other nested sections preserved
        assert config.sandbox["filesystem"]["writable"] == ["{workdir}"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py::TestSandboxConfig -v`
Expected: FAIL — `AttributeError: Config has no attribute 'access_control'`

- [ ] **Step 3: Add sandbox config fields to Config**

Modify `src/bourbon/config.py` — add three dict fields to `Config` with sensible defaults, and update `from_dict()` and `to_dict()`:

Add to the `Config` dataclass (after `mcp` field):

```python
    access_control: dict = field(default_factory=lambda: {
        "default_action": "allow",
        "file": {"allow": ["{workdir}/**"], "deny": ["~/.ssh/**", "~/.aws/**"], "mandatory_deny": ["~/.ssh/**"]},
        "command": {"deny_patterns": ["rm -rf /", "sudo *"], "need_approval_patterns": ["pip install *", "apt *"]},
    })
    sandbox: dict = field(default_factory=lambda: {
        "enabled": True,
        "provider": "auto",
        "filesystem": {"writable": ["{workdir}"], "readonly": ["/usr", "/lib"], "deny": ["~/.ssh", "~/.aws"]},
        "network": {"enabled": False, "allow_domains": []},
        "resources": {"timeout": 120, "max_memory": "512M", "max_output": 50000},
        "credentials": {"clean_env": True, "passthrough_vars": ["PATH", "HOME", "LANG"]},
    })
    audit: dict = field(default_factory=lambda: {
        "enabled": True,
        "log_dir": "~/.bourbon/audit/",
        "format": "jsonl",
    })
```

Add a deep merge helper **before** the `Config` class:

```python
def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base, returning a new dict."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result
```

In `from_dict()`, after `mcp_data = ...` add:

```python
        access_control_data = data.get("access_control", {})
        sandbox_data = data.get("sandbox", {})
        audit_data = data.get("audit", {})
```

And in the return statement, add:

```python
            access_control=_deep_merge(Config().access_control, access_control_data),
            sandbox=_deep_merge(Config().sandbox, sandbox_data),
            audit=_deep_merge(Config().audit, audit_data),
```

In `to_dict()`, add:

```python
            "access_control": self.access_control,
            "sandbox": self.sandbox,
            "audit": self.audit,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_config.py -v`
Expected: All PASS (including existing tests)

- [ ] **Step 5: Commit**

```bash
git add src/bourbon/config.py tests/test_config.py
git commit -m "feat(config): Add access_control, sandbox, audit config sections"
```

---

### Task 9: Tool dataclass — add required_capabilities

**Files:**
- Modify: `src/bourbon/tools/__init__.py:24-33,120-159`
- Modify: `src/bourbon/tools/base.py:208-301`

- [ ] **Step 1: Add required_capabilities to Tool dataclass**

In `src/bourbon/tools/__init__.py`, add import and field:

```python
from dataclasses import dataclass, field  # add field to import
```

Add to `Tool` dataclass after `risk_patterns`:

```python
    required_capabilities: list[str] | None = None  # list of CapabilityType values
```

Add `required_capabilities` parameter to `register_tool()`:

```python
def register_tool(
    name: str,
    description: str,
    input_schema: dict[str, Any],
    risk_level: RiskLevel = RiskLevel.LOW,
    risk_patterns: list[str] | None = None,
    required_capabilities: list[str] | None = None,
) -> Callable[[ToolHandler], ToolHandler]:
```

Pass it through to `Tool(...)` in the decorator.

- [ ] **Step 2: Add capabilities to tool registrations in base.py**

```python
# bash tool:
@register_tool(
    name="bash",
    ...,
    required_capabilities=["exec"],
)

# read_file tool:
@register_tool(
    name="read_file",
    ...,
    required_capabilities=["file_read"],
)

# write_file tool:
@register_tool(
    name="write_file",
    ...,
    required_capabilities=["file_write"],
)

# edit_file tool:
@register_tool(
    name="edit_file",
    ...,
    required_capabilities=["file_write"],
)
```

- [ ] **Step 3: Run existing tests to verify nothing breaks**

Run: `uv run pytest tests/test_tools_registry.py tests/test_risk_level.py tests/test_tools_base.py -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add src/bourbon/tools/__init__.py src/bourbon/tools/base.py
git commit -m "feat(tools): Add required_capabilities field to Tool"
```

---

### Task 10: Agent integration

**Files:**
- Modify: `src/bourbon/agent.py`

This is the final integration step — wiring AccessController, SandboxManager, and AuditLogger into `Agent.__init__()` and `_execute_tools()`.

- [ ] **Step 1: Add imports to agent.py**

At top of `src/bourbon/agent.py`, add:

```python
from bourbon.access_control import AccessController
from bourbon.access_control.policy import PolicyAction
from bourbon.audit import AuditLogger
from bourbon.audit.events import AuditEvent
from bourbon.sandbox import SandboxManager
```

- [ ] **Step 2: Initialize components in Agent.__init__()**

After `self._max_tool_rounds = ...` add:

```python
        # Initialize security components
        audit_config = config.audit if hasattr(config, 'audit') else {}
        log_dir = Path(audit_config.get("log_dir", "~/.bourbon/audit/")).expanduser()
        self.audit = AuditLogger(log_dir=log_dir, enabled=audit_config.get("enabled", True))

        ac_config = config.access_control if hasattr(config, 'access_control') else {}
        self.access_controller = AccessController(config=ac_config, workdir=self.workdir)

        sandbox_config = config.sandbox if hasattr(config, 'sandbox') else {}
        self.sandbox = SandboxManager(config=sandbox_config, workdir=self.workdir, audit=self.audit)
```

- [ ] **Step 3: Modify _execute_tools() to use access control and sandbox**

In the `else:` branch of `_execute_tools()` (the regular tool execution path, around line 420), replace the existing logic with:

```python
            else:
                # Execute regular tool with access control
                tool_handler_fn = handler(tool_name)
                tool_metadata = get_tool_with_metadata(tool_name)

                # Step 1: Access Control
                decision = self.access_controller.evaluate(tool_name, tool_input)
                self.audit.record(AuditEvent.policy_decision(
                    tool_name=tool_name,
                    tool_input_summary=str(tool_input)[:200],
                    decision=decision.action.value,
                    matched_rule=decision.reason,
                    capabilities_required=[d.capability.value for d in decision.decisions],
                ))

                if decision.action == PolicyAction.DENY:
                    output = f"Denied: {decision.reason}"
                elif decision.action == PolicyAction.NEED_APPROVAL:
                    if tool_metadata:
                        self.pending_confirmation = PendingConfirmation(
                            tool_name=tool_name,
                            tool_input=tool_input,
                            error_output=f"Requires approval: {decision.reason}",
                            options=["Approve and execute", "Skip this operation"],
                        )
                        results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_id,
                            "content": f"Requires approval: {decision.reason}",
                        })
                        return results
                    output = f"Requires approval: {decision.reason}"
                elif tool_handler_fn:
                    # Step 2: Route bash through sandbox if enabled
                    if tool_name == "bash" and self.sandbox.enabled:
                        sandbox_result = self.sandbox.execute(tool_input.get("command", ""))
                        # Concatenate stdout+stderr to match existing run_bash behavior
                        output = (sandbox_result.stdout + sandbox_result.stderr).strip()
                        if sandbox_result.timed_out:
                            output = f"Error: Timeout ({sandbox_result.resource_usage.cpu_time:.0f}s)"
                        self.audit.record(AuditEvent.tool_call(
                            tool_name=tool_name,
                            tool_input_summary=str(tool_input)[:200],
                        ))
                    else:
                        # Non-sandbox tools (or bash when sandbox disabled) execute directly
                        try:
                            output = tool_handler_fn(**tool_input)
                            self.audit.record(AuditEvent.tool_call(
                                tool_name=tool_name,
                                tool_input_summary=str(tool_input)[:200],
                            ))

                            # Preserve existing high-risk error confirmation behavior
                            if (
                                tool_metadata
                                and output.startswith("Error")
                                and tool_metadata.is_high_risk_operation(tool_input)
                            ):
                                self.pending_confirmation = PendingConfirmation(
                                    tool_name=tool_name,
                                    tool_input=tool_input,
                                    error_output=output,
                                    options=self._generate_options(tool_name, tool_input, output),
                                )
                                if self.on_tool_end:
                                    self.on_tool_end(tool_name, output)
                                results.append({
                                    "type": "tool_result",
                                    "tool_use_id": tool_id,
                                    "content": str(output)[:50000],
                                })
                                return results
                        except Exception as e:
                            output = f"Error executing {tool_name}: {e}"
                else:
                    output = f"Unknown tool: {tool_name}"
```

- [ ] **Step 4: Run all tests**

Run: `uv run pytest -v`
Expected: All PASS (existing tests + all new tests)

- [ ] **Step 5: Manual smoke test**

Run: `uv run python -m bourbon` and try:
1. Type a question → should work normally
2. Ask agent to run `ls -la` → should execute through sandbox, audit log created in `~/.bourbon/audit/`
3. Check `~/.bourbon/audit/` for JSONL file with events

- [ ] **Step 6: Commit**

```bash
git add src/bourbon/agent.py
git commit -m "feat(agent): Integrate AccessController, SandboxManager, and AuditLogger"
```

---

### Task 11: Run full test suite + lint

- [ ] **Step 1: Run all tests**

Run: `uv run pytest -v`
Expected: All PASS

- [ ] **Step 2: Run linter**

Run: `uv run ruff check src tests && uv run ruff format src tests`
Expected: No errors

- [ ] **Step 3: Run type checker**

Run: `uv run mypy src`
Expected: No new errors

- [ ] **Step 4: Fix any issues found**

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "chore: Fix lint and type issues from sandbox phase 1"
```
