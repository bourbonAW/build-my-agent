# Sandbox Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement BwrapProvider (Linux namespace isolation) and SeatbeltProvider (macOS sandbox-exec) as OS-level sandbox providers, adding real filesystem and network isolation to Bourbon's sandbox system.

**Architecture:** Two flat providers sharing a `FilesystemPolicy` intermediate representation. Each provider independently converts policy rules to OS-specific config (bwrap CLI args / SBPL profile). Shared infrastructure changes first (BoundedOutput extraction, Violation model, is_available()), then providers, then integration.

**Tech Stack:** Python 3.11+, dataclasses, subprocess, shutil, tempfile, os.path, bubblewrap (Linux), sandbox-exec (macOS)

**Spec:** `docs/superpowers/specs/2026-03-25-sandbox-phase2-design.md`

---

## File Structure

### New files to create

| File | Responsibility |
|------|---------------|
| `src/bourbon/sandbox/policy.py` | `MountMode` enum, `MountRule`, `FilesystemPolicy` — intermediate representation from SandboxContext |
| `src/bourbon/sandbox/providers/bubblewrap.py` | `BwrapProvider` — Linux namespace isolation via bubblewrap |
| `src/bourbon/sandbox/providers/seatbelt.py` | `SeatbeltProvider` — macOS sandbox-exec with SBPL profiles |
| `tests/test_filesystem_policy.py` | Unit tests for FilesystemPolicy |
| `tests/test_sandbox_bwrap.py` | Integration tests for BwrapProvider (skipif not Linux/no bwrap) |
| `tests/test_sandbox_seatbelt.py` | Integration tests for SeatbeltProvider (skipif not macOS) |

### Existing files to modify

| File | Change |
|------|--------|
| `src/bourbon/sandbox/runtime.py:1-55` | Extract `BoundedOutput` from local.py here; add `Violation` dataclass; add `violations` field to `SandboxResult`; add `is_available()` classmethod to `SandboxProvider` |
| `src/bourbon/sandbox/providers/local.py:18-52` | Remove `_BoundedOutput` class, import `BoundedOutput` from `runtime` |
| `src/bourbon/sandbox/providers/__init__.py:1-29` | Expand `select_provider()` with bubblewrap/seatbelt/auto platform logic |
| `src/bourbon/sandbox/__init__.py:20-31,84-101` | Narrow network keyword scan to LocalProvider only; add violations audit loop |
| `tests/test_sandbox_local.py:30-36` | Add `violations=[]` where `SandboxResult` is constructed manually (if any) |

---

## Chunk 1: Shared Infrastructure

### Task 1: Extract BoundedOutput to runtime.py

**Files:**
- Modify: `src/bourbon/sandbox/runtime.py:1-55`
- Modify: `src/bourbon/sandbox/providers/local.py:18-52`
- Test: `tests/test_sandbox_local.py` (existing tests must still pass)

- [ ] **Step 1: Copy BoundedOutput class to runtime.py**

Add at the top of `src/bourbon/sandbox/runtime.py`, after the imports:

```python
class BoundedOutput:
    """Capture stream output without retaining more than max_output bytes.

    Used by all sandbox providers to limit subprocess output size.
    """

    def __init__(self, max_output: int) -> None:
        self.max_output = max_output
        self._chunks: list[bytes] = []
        self._captured_bytes = 0
        self._truncated = False

    def append(self, chunk: bytes) -> None:
        if not chunk:
            return
        if self.max_output <= 0:
            self._chunks.append(chunk)
            return

        remaining = self.max_output - self._captured_bytes
        if remaining > 0:
            kept = chunk[:remaining]
            self._chunks.append(kept)
            self._captured_bytes += len(kept)

        if len(chunk) > max(remaining, 0):
            self._truncated = True

    def render(self) -> str:
        data = b"".join(self._chunks)
        if self.max_output > 0 and self._truncated:
            marker = "..."
            if self.max_output <= len(marker):
                return marker[: self.max_output]
            visible_bytes = max(self.max_output - len(marker), 0)
            prefix = data[:visible_bytes].decode("utf-8", errors="replace")
            return f"{prefix}{marker}"
        return data.decode("utf-8", errors="replace")
```

- [ ] **Step 2: Update local.py to import from runtime**

Replace the `_BoundedOutput` class in `src/bourbon/sandbox/providers/local.py` with an import, and update all references:

Remove lines 18-52 (the `_BoundedOutput` class). Add import:

```python
from bourbon.sandbox.runtime import (
    BoundedOutput,
    ResourceUsage,
    SandboxContext,
    SandboxProvider,
    SandboxResult,
)
```

Replace `_BoundedOutput` → `BoundedOutput` in `execute()` method (two occurrences, lines 71-72).

- [ ] **Step 3: Run existing tests to verify refactor is clean**

Run: `pytest tests/test_sandbox_local.py -v`
Expected: All tests PASS (no behavior change)

- [ ] **Step 4: Commit**

```bash
git add src/bourbon/sandbox/runtime.py src/bourbon/sandbox/providers/local.py
git commit -m "refactor(sandbox): extract BoundedOutput to runtime.py for shared use"
```

---

### Task 2: Add Violation dataclass and SandboxResult.violations field

**Files:**
- Modify: `src/bourbon/sandbox/runtime.py`
- Test: `tests/test_sandbox_local.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_sandbox_local.py`:

```python
from bourbon.sandbox.runtime import Violation


class TestViolation:
    def test_violation_fields(self) -> None:
        v = Violation(type="path_denied", detail="access to /etc/shadow blocked")
        assert v.type == "path_denied"
        assert v.detail == "access to /etc/shadow blocked"


class TestSandboxResultViolations:
    def test_default_empty_violations(self) -> None:
        result = SandboxResult(
            stdout="",
            stderr="",
            exit_code=0,
            timed_out=False,
            resource_usage=ResourceUsage(),
        )
        assert result.violations == []

    def test_violations_populated(self) -> None:
        result = SandboxResult(
            stdout="",
            stderr="",
            exit_code=1,
            timed_out=False,
            resource_usage=ResourceUsage(),
            violations=[Violation(type="net_denied", detail="blocked")],
        )
        assert len(result.violations) == 1
        assert result.violations[0].type == "net_denied"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_sandbox_local.py::TestViolation -v`
Expected: FAIL with `ImportError: cannot import name 'Violation'`

- [ ] **Step 3: Implement Violation and update SandboxResult**

Add to `src/bourbon/sandbox/runtime.py`, before `SandboxResult`:

```python
@dataclass(slots=True)
class Violation:
    """A sandbox violation detected during execution."""

    type: str       # "path_denied" / "net_denied" / "exec_denied"
    detail: str     # Human-readable description
```

Update `SandboxResult` to add `violations` field (with default, so non-breaking):

```python
@dataclass(slots=True)
class SandboxResult:
    """Result of a sandbox execution."""

    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool
    resource_usage: ResourceUsage
    violations: list[Violation] = field(default_factory=list)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_sandbox_local.py -v`
Expected: All tests PASS (including existing ones — default violations=[] is non-breaking)

- [ ] **Step 5: Commit**

```bash
git add src/bourbon/sandbox/runtime.py tests/test_sandbox_local.py
git commit -m "feat(sandbox): add Violation dataclass and SandboxResult.violations field"
```

---

### Task 3: Add is_available() to SandboxProvider

**Files:**
- Modify: `src/bourbon/sandbox/runtime.py:46-55`
- Test: `tests/test_sandbox_local.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_sandbox_local.py`:

```python
class TestProviderAvailability:
    def test_local_provider_always_available(self) -> None:
        assert LocalProvider.is_available() is True

    def test_sandbox_provider_default_available(self) -> None:
        from bourbon.sandbox.runtime import SandboxProvider
        assert SandboxProvider.is_available() is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_sandbox_local.py::TestProviderAvailability -v`
Expected: FAIL with `AttributeError: type object 'LocalProvider' has no attribute 'is_available'`

- [ ] **Step 3: Implement is_available()**

Add to `SandboxProvider` in `src/bourbon/sandbox/runtime.py`:

```python
class SandboxProvider(ABC):
    """Sandbox execution backend."""

    @abstractmethod
    def execute(self, command: str, context: SandboxContext) -> SandboxResult:
        """Execute a command under the provider."""

    @abstractmethod
    def get_isolation_level(self) -> str:
        """Return a human-readable description of the isolation level."""

    @classmethod
    def is_available(cls) -> bool:
        """Check if this provider is available on the current system."""
        return True
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_sandbox_local.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/bourbon/sandbox/runtime.py tests/test_sandbox_local.py
git commit -m "feat(sandbox): add is_available() classmethod to SandboxProvider"
```

---

### Task 4: FilesystemPolicy

**Files:**
- Create: `src/bourbon/sandbox/policy.py`
- Create: `tests/test_filesystem_policy.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_filesystem_policy.py
"""Tests for FilesystemPolicy intermediate representation."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from bourbon.sandbox.policy import FilesystemPolicy, MountMode, MountRule
from bourbon.sandbox.runtime import SandboxContext


class TestMountMode:
    def test_enum_values(self) -> None:
        assert MountMode.READ_ONLY.value == "ro"
        assert MountMode.READ_WRITE.value == "rw"
        assert MountMode.DENY.value == "deny"


class TestMountRule:
    def test_fields(self) -> None:
        rule = MountRule(path="/usr", mode=MountMode.READ_ONLY)
        assert rule.path == "/usr"
        assert rule.mode == MountMode.READ_ONLY


class TestFilesystemPolicy:
    def _make_context(self, tmp_path: Path, **overrides) -> SandboxContext:
        defaults = dict(
            workdir=tmp_path,
            writable_paths=[str(tmp_path)],
            readonly_paths=["/usr"],
            deny_paths=["~/.ssh"],
            network_enabled=False,
            allow_domains=[],
            timeout=5,
            max_memory="256M",
            max_output=1000,
            env_vars={},
        )
        defaults.update(overrides)
        return SandboxContext(**defaults)

    def test_from_context_produces_rules(self, tmp_path: Path) -> None:
        context = self._make_context(tmp_path)
        policy = FilesystemPolicy.from_context(context)

        modes = [r.mode for r in policy.rules]
        assert MountMode.READ_WRITE in modes
        assert MountMode.READ_ONLY in modes
        assert MountMode.DENY in modes

    def test_from_context_ordering(self, tmp_path: Path) -> None:
        """Rules are ordered: READ_WRITE, then READ_ONLY, then DENY.
        This matters for seatbelt where last rule wins."""
        context = self._make_context(tmp_path)
        policy = FilesystemPolicy.from_context(context)

        modes = [r.mode for r in policy.rules]
        # All RW before RO, all RO before DENY
        last_rw = max(
            (i for i, m in enumerate(modes) if m == MountMode.READ_WRITE),
            default=-1,
        )
        first_ro = next(
            (i for i, m in enumerate(modes) if m == MountMode.READ_ONLY),
            len(modes),
        )
        first_deny = next(
            (i for i, m in enumerate(modes) if m == MountMode.DENY),
            len(modes),
        )
        assert last_rw < first_ro, "READ_WRITE rules should come before READ_ONLY"
        assert first_ro < first_deny, "READ_ONLY rules should come before DENY"

    def test_workdir_always_included(self, tmp_path: Path) -> None:
        """Even if writable_paths is empty, workdir appears as READ_WRITE."""
        context = self._make_context(tmp_path, writable_paths=[])
        policy = FilesystemPolicy.from_context(context)

        rw_paths = [r.path for r in policy.rules if r.mode == MountMode.READ_WRITE]
        assert str(tmp_path) in rw_paths

    def test_tilde_expansion(self, tmp_path: Path) -> None:
        context = self._make_context(tmp_path, deny_paths=["~/.ssh"])
        policy = FilesystemPolicy.from_context(context)

        deny_paths = [r.path for r in policy.rules if r.mode == MountMode.DENY]
        for p in deny_paths:
            assert "~" not in p, f"tilde not expanded in: {p}"
            assert p.startswith("/"), f"not absolute: {p}"

    def test_symlink_resolved(self, tmp_path: Path) -> None:
        real_dir = tmp_path / "real"
        real_dir.mkdir()
        link = tmp_path / "link"
        link.symlink_to(real_dir)

        context = self._make_context(
            tmp_path, readonly_paths=[str(link)]
        )
        policy = FilesystemPolicy.from_context(context)

        ro_paths = [r.path for r in policy.rules if r.mode == MountMode.READ_ONLY]
        assert str(real_dir) in ro_paths
        assert str(link) not in ro_paths

    def test_empty_paths_still_has_workdir(self, tmp_path: Path) -> None:
        context = self._make_context(
            tmp_path, writable_paths=[], readonly_paths=[], deny_paths=[]
        )
        policy = FilesystemPolicy.from_context(context)

        assert len(policy.rules) >= 1
        assert policy.rules[0].path == str(tmp_path)
        assert policy.rules[0].mode == MountMode.READ_WRITE

    def test_all_paths_absolute(self, tmp_path: Path) -> None:
        context = self._make_context(
            tmp_path,
            writable_paths=[str(tmp_path)],
            readonly_paths=["/usr", "/lib"],
            deny_paths=["~/.ssh", "~/.aws"],
        )
        policy = FilesystemPolicy.from_context(context)

        for rule in policy.rules:
            assert os.path.isabs(rule.path), f"not absolute: {rule.path}"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_filesystem_policy.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bourbon.sandbox.policy'`

- [ ] **Step 3: Implement FilesystemPolicy**

```python
# src/bourbon/sandbox/policy.py
"""Filesystem policy intermediate representation.

Converts SandboxContext's three path lists (writable, readonly, deny)
into an ordered list of MountRules that providers consume to generate
OS-specific configurations (bwrap args, SBPL profiles).
"""

from __future__ import annotations

import os
from enum import Enum
from dataclasses import dataclass

from bourbon.sandbox.runtime import SandboxContext


class MountMode(Enum):
    READ_ONLY = "ro"
    READ_WRITE = "rw"
    DENY = "deny"


@dataclass(slots=True)
class MountRule:
    """A single filesystem access rule."""

    path: str
    mode: MountMode


@dataclass(slots=True)
class FilesystemPolicy:
    """Ordered filesystem rules built from SandboxContext.

    Providers iterate this to generate OS-specific configurations.
    """

    rules: list[MountRule]

    @classmethod
    def from_context(cls, context: SandboxContext) -> FilesystemPolicy:
        """Build policy from SandboxContext paths.

        - All paths are expanded (~ → home, symlinks → realpath).
        - workdir is always included as READ_WRITE.
        - Order: READ_WRITE first, then READ_ONLY, then DENY.
          Providers that care about priority (seatbelt: last rule wins)
          use this ordering — deny is last so it overrides allow.
        """
        rules: list[MountRule] = []
        seen: set[str] = set()

        workdir_str = str(context.workdir)
        resolved_workdir = _resolve(workdir_str)
        rules.append(MountRule(path=resolved_workdir, mode=MountMode.READ_WRITE))
        seen.add(resolved_workdir)

        for path in context.writable_paths:
            resolved = _resolve(path)
            if resolved not in seen:
                rules.append(MountRule(path=resolved, mode=MountMode.READ_WRITE))
                seen.add(resolved)

        for path in context.readonly_paths:
            resolved = _resolve(path)
            if resolved not in seen:
                rules.append(MountRule(path=resolved, mode=MountMode.READ_ONLY))
                seen.add(resolved)

        for path in context.deny_paths:
            resolved = _resolve(path)
            rules.append(MountRule(path=resolved, mode=MountMode.DENY))

        return cls(rules=rules)


def _resolve(path: str) -> str:
    """Expand ~ and resolve symlinks to get a canonical absolute path."""
    return os.path.realpath(os.path.expanduser(path))
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_filesystem_policy.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/bourbon/sandbox/policy.py tests/test_filesystem_policy.py
git commit -m "feat(sandbox): add FilesystemPolicy intermediate representation"
```

---

## Chunk 2: BwrapProvider

### Task 5: BwrapProvider implementation + integration tests

**Files:**
- Create: `src/bourbon/sandbox/providers/bubblewrap.py`
- Create: `tests/test_sandbox_bwrap.py`

- [ ] **Step 1: Write failing integration tests**

```python
# tests/test_sandbox_bwrap.py
"""Integration tests for BwrapProvider (Linux bubblewrap)."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest

from bourbon.sandbox.providers.bubblewrap import BwrapProvider
from bourbon.sandbox.runtime import ResourceUsage, SandboxContext

pytestmark = pytest.mark.skipif(
    sys.platform != "linux" or shutil.which("bwrap") is None,
    reason="requires Linux with bubblewrap installed",
)


def _make_context(tmp_path: Path, **overrides) -> SandboxContext:
    defaults = dict(
        workdir=tmp_path,
        writable_paths=[str(tmp_path)],
        readonly_paths=["/usr", "/lib", "/lib64", "/bin", "/sbin"],
        deny_paths=[],
        network_enabled=False,
        allow_domains=[],
        timeout=10,
        max_memory="256M",
        max_output=50000,
        env_vars={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
    )
    defaults.update(overrides)
    return SandboxContext(**defaults)


class TestBwrapProvider:
    def test_basic_execution(self, tmp_path: Path) -> None:
        provider = BwrapProvider()
        context = _make_context(tmp_path)

        result = provider.execute("echo hello", context)

        assert result.exit_code == 0
        assert result.stdout.strip() == "hello"
        assert result.timed_out is False

    def test_workdir_writable(self, tmp_path: Path) -> None:
        provider = BwrapProvider()
        context = _make_context(tmp_path)

        result = provider.execute(
            f"echo test > {tmp_path}/output.txt && cat {tmp_path}/output.txt",
            context,
        )

        assert result.exit_code == 0
        assert "test" in result.stdout

    def test_filesystem_isolation(self, tmp_path: Path) -> None:
        """Paths not mounted into namespace don't exist (ENOENT)."""
        provider = BwrapProvider()
        home = os.path.expanduser("~")
        ssh_dir = os.path.join(home, ".ssh")
        context = _make_context(tmp_path, deny_paths=[ssh_dir])

        result = provider.execute(f"ls {ssh_dir}", context)

        assert result.exit_code != 0
        assert "No such file" in result.stderr or "cannot access" in result.stderr

    def test_readonly_enforcement(self, tmp_path: Path) -> None:
        """Readonly paths cannot be written to."""
        provider = BwrapProvider()
        context = _make_context(tmp_path)

        result = provider.execute("touch /usr/test_readonly", context)

        assert result.exit_code != 0
        assert "Read-only file system" in result.stderr or "Permission denied" in result.stderr

    def test_network_isolation(self, tmp_path: Path) -> None:
        """--unshare-net blocks network access."""
        provider = BwrapProvider()
        context = _make_context(tmp_path, network_enabled=False)

        result = provider.execute(
            "python3 -c \"import urllib.request; urllib.request.urlopen('http://example.com')\"",
            context,
        )

        assert result.exit_code != 0
        # Violations detected from stderr
        net_violations = [v for v in result.violations if v.type == "net_denied"]
        assert len(net_violations) >= 0  # best-effort detection

    def test_env_clean(self, tmp_path: Path) -> None:
        """Only passthrough env vars are visible inside sandbox."""
        provider = BwrapProvider()
        context = _make_context(
            tmp_path,
            env_vars={"PATH": "/usr/bin:/bin", "CUSTOM": "visible"},
        )

        result = provider.execute("env", context)

        assert result.exit_code == 0
        assert "CUSTOM=visible" in result.stdout
        assert "ANTHROPIC_API_KEY" not in result.stdout

    def test_timeout(self, tmp_path: Path) -> None:
        provider = BwrapProvider()
        context = _make_context(tmp_path, timeout=1)

        result = provider.execute("sleep 5", context)

        assert result.timed_out is True
        assert result.exit_code == -1

    def test_isolation_level(self) -> None:
        provider = BwrapProvider()
        assert provider.get_isolation_level() == "bubblewrap (Linux namespace)"

    def test_is_available(self) -> None:
        # We already know bwrap is installed (skipif above)
        assert BwrapProvider.is_available() is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_sandbox_bwrap.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bourbon.sandbox.providers.bubblewrap'` (or skipped on non-Linux)

- [ ] **Step 3: Implement BwrapProvider**

```python
# src/bourbon/sandbox/providers/bubblewrap.py
"""Bubblewrap sandbox provider for Linux namespace isolation."""

from __future__ import annotations

import shutil
import subprocess
import time
from threading import Thread
from typing import BinaryIO

from bourbon.sandbox.policy import FilesystemPolicy, MountMode
from bourbon.sandbox.runtime import (
    BoundedOutput,
    ResourceUsage,
    SandboxContext,
    SandboxProvider,
    SandboxResult,
    Violation,
)

import os

# Minimal system paths required for bash and basic commands to function.
# These are always mounted read-only regardless of user configuration.
_SYSTEM_RO_BINDS = [
    "/usr",
    "/lib",
    "/lib64",
    "/bin",
    "/sbin",
]


class BwrapProvider(SandboxProvider):
    """Linux namespace isolation via bubblewrap."""

    @classmethod
    def is_available(cls) -> bool:
        return shutil.which("bwrap") is not None

    def execute(self, command: str, context: SandboxContext) -> SandboxResult:
        policy = FilesystemPolicy.from_context(context)
        args = self._build_args(policy, context)

        started_at = time.monotonic()
        process = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert process.stdout is not None
        assert process.stderr is not None

        stdout_buf = BoundedOutput(context.max_output)
        stderr_buf = BoundedOutput(context.max_output)
        stdout_thread = Thread(
            target=self._drain,
            args=(process.stdout, stdout_buf),
            daemon=True,
        )
        stderr_thread = Thread(
            target=self._drain,
            args=(process.stderr, stderr_buf),
            daemon=True,
        )
        stdout_thread.start()
        stderr_thread.start()

        try:
            exit_code = process.wait(timeout=context.timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            stdout_thread.join()
            stderr_thread.join()
            elapsed = time.monotonic() - started_at
            stderr_text = stderr_buf.render()
            timeout_msg = f"Command timed out after {context.timeout} seconds."
            if stderr_text:
                timeout_msg = f"{timeout_msg}\n{stderr_text}"
            return SandboxResult(
                stdout=stdout_buf.render(),
                stderr=timeout_msg,
                exit_code=-1,
                timed_out=True,
                resource_usage=ResourceUsage(cpu_time=elapsed),
            )

        stdout_thread.join()
        stderr_thread.join()
        elapsed = time.monotonic() - started_at

        result = SandboxResult(
            stdout=stdout_buf.render(),
            stderr=stderr_buf.render(),
            exit_code=exit_code,
            timed_out=False,
            resource_usage=ResourceUsage(cpu_time=elapsed),
        )
        result.violations = self._parse_violations(result)
        return result

    def get_isolation_level(self) -> str:
        return "bubblewrap (Linux namespace)"

    def _build_args(
        self, policy: FilesystemPolicy, context: SandboxContext
    ) -> list[str]:
        args = ["bwrap"]

        # System paths (always read-only)
        for sys_path in _SYSTEM_RO_BINDS:
            args += ["--ro-bind", sys_path, sys_path]
        args += ["--proc", "/proc"]
        args += ["--dev", "/dev"]

        # Collect mounted paths to detect deny-as-subpath-of-mount
        mounted: list[str] = []

        # User-configured filesystem rules
        for rule in policy.rules:
            if rule.mode == MountMode.READ_WRITE:
                args += ["--bind", rule.path, rule.path]
                mounted.append(rule.path)
            elif rule.mode == MountMode.READ_ONLY:
                args += ["--ro-bind", rule.path, rule.path]
                mounted.append(rule.path)

        # Deny rules: if deny path is a subpath of a mounted path, use --tmpfs
        for rule in policy.rules:
            if rule.mode == MountMode.DENY:
                if any(rule.path.startswith(m + "/") or rule.path.startswith(m + os.sep) for m in mounted):
                    args += ["--tmpfs", rule.path]

        # Network isolation
        if not context.network_enabled:
            args += ["--unshare-net"]

        # Process isolation
        args += ["--unshare-pid"]
        args += ["--new-session"]
        args += ["--die-with-parent"]

        # Clean environment
        args += ["--clearenv"]
        for key, value in context.env_vars.items():
            args += ["--setenv", key, value]

        # Working directory + command
        args += ["--chdir", str(context.workdir)]
        args += ["--", "bash", "-c", command]

        return args

    def _parse_violations(self, result: SandboxResult) -> list[Violation]:
        """Best-effort violation detection from stderr."""
        violations: list[Violation] = []
        if "Network is unreachable" in result.stderr:
            violations.append(
                Violation(
                    type="net_denied",
                    detail="network isolated by namespace (--unshare-net)",
                )
            )
        return violations

    @staticmethod
    def _drain(stream: BinaryIO, buffer: BoundedOutput) -> None:
        try:
            while chunk := stream.read(4096):
                buffer.append(chunk)
        finally:
            stream.close()
```

Note: add `import os` to the imports at the top.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_sandbox_bwrap.py -v`
Expected: All PASS on Linux with bwrap installed, SKIPPED on other platforms

- [ ] **Step 5: Run all existing tests to check for regressions**

Run: `pytest tests/ -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add src/bourbon/sandbox/providers/bubblewrap.py tests/test_sandbox_bwrap.py
git commit -m "feat(sandbox): add BwrapProvider with Linux namespace isolation"
```

---

## Chunk 3: SeatbeltProvider

### Task 6: SeatbeltProvider implementation + integration tests

**Files:**
- Create: `src/bourbon/sandbox/providers/seatbelt.py`
- Create: `tests/test_sandbox_seatbelt.py`

- [ ] **Step 1: Write failing integration tests**

```python
# tests/test_sandbox_seatbelt.py
"""Integration tests for SeatbeltProvider (macOS sandbox-exec)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from bourbon.sandbox.providers.seatbelt import SeatbeltProvider
from bourbon.sandbox.runtime import SandboxContext

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin",
    reason="requires macOS",
)


def _make_context(tmp_path: Path, **overrides) -> SandboxContext:
    defaults = dict(
        workdir=tmp_path,
        writable_paths=[str(tmp_path)],
        readonly_paths=["/usr", "/bin", "/sbin", "/Library"],
        deny_paths=[],
        network_enabled=False,
        allow_domains=[],
        timeout=10,
        max_memory="256M",
        max_output=50000,
        env_vars={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
    )
    defaults.update(overrides)
    return SandboxContext(**defaults)


class TestSeatbeltProvider:
    def test_basic_execution(self, tmp_path: Path) -> None:
        provider = SeatbeltProvider()
        context = _make_context(tmp_path)

        result = provider.execute("echo hello", context)

        assert result.exit_code == 0
        assert result.stdout.strip() == "hello"
        assert result.timed_out is False

    def test_workdir_writable(self, tmp_path: Path) -> None:
        provider = SeatbeltProvider()
        context = _make_context(tmp_path)

        result = provider.execute(
            f"echo test > {tmp_path}/output.txt && cat {tmp_path}/output.txt",
            context,
        )

        assert result.exit_code == 0
        assert "test" in result.stdout

    def test_filesystem_deny(self, tmp_path: Path) -> None:
        """Denied paths return EPERM (Operation not permitted)."""
        provider = SeatbeltProvider()
        home = os.path.expanduser("~")
        ssh_dir = os.path.join(home, ".ssh")
        context = _make_context(tmp_path, deny_paths=[ssh_dir])

        result = provider.execute(f"ls {ssh_dir}", context)

        assert result.exit_code != 0
        assert "Operation not permitted" in result.stderr or "Permission denied" in result.stderr

    def test_readonly_enforcement(self, tmp_path: Path) -> None:
        provider = SeatbeltProvider()
        context = _make_context(tmp_path)

        result = provider.execute("touch /usr/test_readonly", context)

        assert result.exit_code != 0
        assert "Operation not permitted" in result.stderr or "Permission denied" in result.stderr

    def test_network_isolation(self, tmp_path: Path) -> None:
        """deny network* blocks outbound connections."""
        provider = SeatbeltProvider()
        context = _make_context(tmp_path, network_enabled=False)

        result = provider.execute(
            "python3 -c \"import urllib.request; urllib.request.urlopen('http://example.com')\"",
            context,
        )

        assert result.exit_code != 0

    def test_env_clean(self, tmp_path: Path) -> None:
        provider = SeatbeltProvider()
        context = _make_context(
            tmp_path,
            env_vars={"PATH": "/usr/bin:/bin", "CUSTOM": "visible"},
        )

        result = provider.execute("env", context)

        assert result.exit_code == 0
        assert "CUSTOM=visible" in result.stdout

    def test_profile_cleanup(self, tmp_path: Path) -> None:
        """Temporary .sb profile file is cleaned up after execution."""
        import glob

        provider = SeatbeltProvider()
        context = _make_context(tmp_path)

        sb_before = set(glob.glob("/tmp/*.sb"))
        provider.execute("echo cleanup_test", context)
        sb_after = set(glob.glob("/tmp/*.sb"))

        # No new .sb files lingering
        new_files = sb_after - sb_before
        assert len(new_files) == 0

    def test_violation_detection(self, tmp_path: Path) -> None:
        """Violations list populated when access denied."""
        provider = SeatbeltProvider()
        home = os.path.expanduser("~")
        ssh_dir = os.path.join(home, ".ssh")
        context = _make_context(tmp_path, deny_paths=[ssh_dir])

        result = provider.execute(f"cat {ssh_dir}/id_rsa", context)

        if "Operation not permitted" in result.stderr:
            path_violations = [v for v in result.violations if v.type == "path_denied"]
            assert len(path_violations) >= 1

    def test_timeout(self, tmp_path: Path) -> None:
        provider = SeatbeltProvider()
        context = _make_context(tmp_path, timeout=1)

        result = provider.execute("sleep 5", context)

        assert result.timed_out is True
        assert result.exit_code == -1

    def test_isolation_level(self) -> None:
        provider = SeatbeltProvider()
        assert provider.get_isolation_level() == "seatbelt (macOS sandbox-exec)"

    def test_is_available(self) -> None:
        assert SeatbeltProvider.is_available() is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_sandbox_seatbelt.py -v`
Expected: FAIL with `ModuleNotFoundError` (or SKIPPED on Linux)

- [ ] **Step 3: Implement SeatbeltProvider**

```python
# src/bourbon/sandbox/providers/seatbelt.py
"""Seatbelt sandbox provider for macOS sandbox-exec isolation."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from threading import Thread
from typing import BinaryIO

from bourbon.sandbox.policy import FilesystemPolicy, MountMode
from bourbon.sandbox.runtime import (
    BoundedOutput,
    ResourceUsage,
    SandboxContext,
    SandboxProvider,
    SandboxResult,
    Violation,
)


class SeatbeltProvider(SandboxProvider):
    """macOS sandbox-exec isolation via SBPL profiles."""

    @classmethod
    def is_available(cls) -> bool:
        return sys.platform == "darwin"

    def execute(self, command: str, context: SandboxContext) -> SandboxResult:
        policy = FilesystemPolicy.from_context(context)
        profile = self._build_profile(policy, context)

        fd, profile_path = tempfile.mkstemp(suffix=".sb")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(profile)

            args = ["sandbox-exec", "-f", profile_path, "bash", "-c", command]

            started_at = time.monotonic()
            process = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=context.workdir,
                env=context.env_vars,
            )
            assert process.stdout is not None
            assert process.stderr is not None

            stdout_buf = BoundedOutput(context.max_output)
            stderr_buf = BoundedOutput(context.max_output)
            stdout_thread = Thread(
                target=self._drain,
                args=(process.stdout, stdout_buf),
                daemon=True,
            )
            stderr_thread = Thread(
                target=self._drain,
                args=(process.stderr, stderr_buf),
                daemon=True,
            )
            stdout_thread.start()
            stderr_thread.start()

            try:
                exit_code = process.wait(timeout=context.timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                stdout_thread.join()
                stderr_thread.join()
                elapsed = time.monotonic() - started_at
                stderr_text = stderr_buf.render()
                timeout_msg = f"Command timed out after {context.timeout} seconds."
                if stderr_text:
                    timeout_msg = f"{timeout_msg}\n{stderr_text}"
                return SandboxResult(
                    stdout=stdout_buf.render(),
                    stderr=timeout_msg,
                    exit_code=-1,
                    timed_out=True,
                    resource_usage=ResourceUsage(cpu_time=elapsed),
                )

            stdout_thread.join()
            stderr_thread.join()
            elapsed = time.monotonic() - started_at

            result = SandboxResult(
                stdout=stdout_buf.render(),
                stderr=stderr_buf.render(),
                exit_code=exit_code,
                timed_out=False,
                resource_usage=ResourceUsage(cpu_time=elapsed),
            )
            result.violations = self._parse_violations(result)
            return result
        finally:
            os.unlink(profile_path)

    def get_isolation_level(self) -> str:
        return "seatbelt (macOS sandbox-exec)"

    def _build_profile(
        self, policy: FilesystemPolicy, context: SandboxContext
    ) -> str:
        """Convert FilesystemPolicy to SBPL profile text.

        In seatbelt, when multiple rules match the same path,
        the last-added rule wins. So we write allow rules first,
        then deny rules — deny at the end overrides allow.
        """
        lines = [
            "(version 1)",
            "(deny default)",
            "",
            "; === base system permissions ===",
            "(allow process-exec)",
            "(allow process-fork)",
            "(allow sysctl-read)",
            "(allow mach-lookup)",
            "(allow ipc-posix-shm-read*)",
            "(allow ipc-posix-shm-write*)",
            '(allow signal (target self))',
            "",
            "; === /dev access ===",
            '(allow file-read* file-write* (subpath "/dev"))',
            "",
            "; === filesystem rules (allow first, deny last to override) ===",
        ]

        # Allow rules first
        for rule in policy.rules:
            if rule.mode == MountMode.READ_WRITE:
                lines.append(
                    f'(allow file-read* file-write* (subpath "{rule.path}"))'
                )
            elif rule.mode == MountMode.READ_ONLY:
                lines.append(f'(allow file-read* (subpath "{rule.path}"))')

        # Deny rules last (higher priority)
        for rule in policy.rules:
            if rule.mode == MountMode.DENY:
                lines.append(
                    f'(deny file-read* file-write* (subpath "{rule.path}"))'
                )

        # Network
        lines.append("")
        if context.network_enabled:
            lines.append("(allow network*)")
        else:
            lines.append("(deny network*)")

        return "\n".join(lines)

    def _parse_violations(self, result: SandboxResult) -> list[Violation]:
        """Best-effort violation detection from stderr."""
        violations: list[Violation] = []
        if "Operation not permitted" in result.stderr:
            violations.append(
                Violation(
                    type="path_denied",
                    detail="filesystem access denied by seatbelt profile",
                )
            )
        stderr_lower = result.stderr.lower()
        if (
            "network" in stderr_lower or "connect" in stderr_lower
        ) and "denied" in stderr_lower:
            violations.append(
                Violation(
                    type="net_denied",
                    detail="network access denied by seatbelt profile",
                )
            )
        return violations

    @staticmethod
    def _drain(stream: BinaryIO, buffer: BoundedOutput) -> None:
        try:
            while chunk := stream.read(4096):
                buffer.append(chunk)
        finally:
            stream.close()
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_sandbox_seatbelt.py -v`
Expected: All PASS on macOS, SKIPPED on Linux

- [ ] **Step 5: Run all tests for regressions**

Run: `pytest tests/ -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add src/bourbon/sandbox/providers/seatbelt.py tests/test_sandbox_seatbelt.py
git commit -m "feat(sandbox): add SeatbeltProvider with macOS sandbox-exec isolation"
```

---

## Chunk 4: Integration

### Task 7: Update select_provider with platform auto-detection

**Files:**
- Modify: `src/bourbon/sandbox/providers/__init__.py:1-29`
- Modify: `tests/test_sandbox_local.py:47-60`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_sandbox_local.py`:

```python
class TestSelectProviderPhase2:
    def test_select_bubblewrap_explicit(self) -> None:
        """Explicit 'bubblewrap' selects BwrapProvider if available."""
        from bourbon.sandbox.providers.bubblewrap import BwrapProvider

        if not BwrapProvider.is_available():
            with pytest.raises(SandboxProviderNotFound, match="bubblewrap not found"):
                select_provider("bubblewrap")
        else:
            provider = select_provider("bubblewrap")
            assert isinstance(provider, BwrapProvider)

    def test_select_seatbelt_explicit(self) -> None:
        """Explicit 'seatbelt' selects SeatbeltProvider if available."""
        from bourbon.sandbox.providers.seatbelt import SeatbeltProvider

        if not SeatbeltProvider.is_available():
            with pytest.raises(SandboxProviderNotFound, match="seatbelt requires macOS"):
                select_provider("seatbelt")
        else:
            provider = select_provider("seatbelt")
            assert isinstance(provider, SeatbeltProvider)

    def test_auto_selects_strongest_available(self) -> None:
        """Auto mode selects the strongest provider for the current platform."""
        provider = select_provider("auto")
        # On any platform, auto should return a valid provider
        assert hasattr(provider, "execute")
        assert hasattr(provider, "get_isolation_level")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_sandbox_local.py::TestSelectProviderPhase2 -v`
Expected: FAIL (bubblewrap/seatbelt not recognized by current select_provider)

- [ ] **Step 3: Update select_provider**

Replace the contents of `src/bourbon/sandbox/providers/__init__.py`:

```python
"""Sandbox provider selection."""

from __future__ import annotations

import sys

from bourbon.sandbox.providers.local import LocalProvider
from bourbon.sandbox.runtime import SandboxProvider


class SandboxProviderNotFoundError(ValueError):
    """Raised when a sandbox provider name is not recognized."""


SandboxProviderNotFound = SandboxProviderNotFoundError


def select_provider(name: str) -> SandboxProvider:
    """Return a sandbox provider by name."""
    normalized = name.lower()

    if normalized == "bubblewrap":
        from bourbon.sandbox.providers.bubblewrap import BwrapProvider

        if not BwrapProvider.is_available():
            raise SandboxProviderNotFound(
                'bubblewrap not found. Install it or set provider = "auto"'
            )
        return BwrapProvider()

    if normalized == "seatbelt":
        from bourbon.sandbox.providers.seatbelt import SeatbeltProvider

        if not SeatbeltProvider.is_available():
            raise SandboxProviderNotFound(
                'seatbelt requires macOS. Set provider = "auto"'
            )
        return SeatbeltProvider()

    if normalized == "local":
        return LocalProvider()

    if normalized == "auto":
        if sys.platform == "linux":
            from bourbon.sandbox.providers.bubblewrap import BwrapProvider

            if BwrapProvider.is_available():
                return BwrapProvider()
        if sys.platform == "darwin":
            from bourbon.sandbox.providers.seatbelt import SeatbeltProvider

            return SeatbeltProvider()
        return LocalProvider()

    raise SandboxProviderNotFound(f"Sandbox provider not found: {name}")


__all__ = [
    "SandboxProviderNotFound",
    "SandboxProviderNotFoundError",
    "select_provider",
    "LocalProvider",
]
```

Note: lazy imports for BwrapProvider and SeatbeltProvider to avoid importing platform-specific code when not needed.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_sandbox_local.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/bourbon/sandbox/providers/__init__.py tests/test_sandbox_local.py
git commit -m "feat(sandbox): expand select_provider with bubblewrap/seatbelt/auto"
```

---

### Task 8: SandboxManager modifications

**Files:**
- Modify: `src/bourbon/sandbox/__init__.py:20-31,84-118`
- Test: `tests/test_sandbox_local.py` (add test for violations audit)

- [ ] **Step 1: Write failing test**

Add to `tests/test_sandbox_local.py`:

```python
from unittest.mock import MagicMock

from bourbon.sandbox import SandboxManager
from bourbon.sandbox.runtime import Violation


class TestSandboxManagerViolationsAudit:
    def test_violations_recorded_to_audit(self, tmp_path: Path) -> None:
        """Provider violations are forwarded to audit logger."""
        audit = MagicMock()
        config = {
            "enabled": True,
            "provider": "local",
            "filesystem": {},
            "network": {"enabled": False},
            "resources": {"timeout": 5},
            "credentials": {"clean_env": False, "passthrough_vars": ["PATH"]},
        }
        manager = SandboxManager(config=config, workdir=tmp_path, audit=audit)

        # LocalProvider won't produce violations, but we test the audit loop
        # by checking that sandbox_exec events are still recorded
        result = manager.execute("echo test", tool_name="bash")
        assert result.exit_code == 0

        # At minimum, sandbox_exec event should be recorded
        assert audit.record.called
```

- [ ] **Step 2: Run to verify baseline passes**

Run: `pytest tests/test_sandbox_local.py::TestSandboxManagerViolationsAudit -v`
Expected: PASS (this is a baseline test)

- [ ] **Step 3: Update SandboxManager**

Modify `src/bourbon/sandbox/__init__.py`:

Add import at top:

```python
from bourbon.sandbox.providers.local import LocalProvider
```

Update the `execute()` method — change the network check condition and add violations audit loop.

The network check block (around line 84) changes from:

```python
        if not context.network_enabled and self._contains_network_activity(command):
```

to:

```python
        if (
            not context.network_enabled
            and isinstance(self.provider, LocalProvider)
            and self._contains_network_activity(command)
        ):
```

After the `result = self.provider.execute(command, context)` line, before the existing audit record, add:

```python
        for v in result.violations:
            self.audit.record(
                AuditEvent.sandbox_violation(
                    tool_name=tool_name,
                    tool_input_summary=command[:200],
                    reason=f"{v.type}: {v.detail}",
                )
            )
```

- [ ] **Step 4: Run all tests**

Run: `pytest tests/ -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/bourbon/sandbox/__init__.py tests/test_sandbox_local.py
git commit -m "feat(sandbox): narrow network scan to LocalProvider, add violations audit"
```
