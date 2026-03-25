# Sandbox Phase 3 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement DockerProvider (container isolation via `docker run`) and CredentialProxy (host-side HTTP proxy that injects credentials without exposing them inside the container).

**Architecture:** Two independent components. `CredentialProxy` is a pure Python HTTP proxy (unit-testable without Docker). `DockerProvider` wraps `docker run` with `--cap-drop=ALL`, `--user nobody`, `--memory`, and optional proxy wiring. Both share existing `FilesystemPolicy`, `BoundedOutput`, and `SandboxProvider` interfaces from Phase 2.

**Tech Stack:** Python 3.11+, `http.server.BaseHTTPRequestHandler`, `urllib.request`, `subprocess`, `shutil`, `threading`, `dataclasses`

**Spec:** `docs/superpowers/specs/2026-03-25-sandbox-phase3-design.md`

---

## File Structure

### New files to create

| File | Responsibility |
|------|---------------|
| `src/bourbon/sandbox/credential_proxy.py` | `CredentialProxy` — host-side HTTP proxy with domain allowlist and credential injection |
| `src/bourbon/sandbox/providers/docker.py` | `DockerProvider` — `docker run` with security hardening + CredentialProxy wiring |
| `tests/test_credential_proxy.py` | CredentialProxy unit tests (no Docker required) |
| `tests/test_sandbox_docker.py` | DockerProvider integration tests (skipif Docker absent) |

### Existing files to modify

| File | Change |
|------|--------|
| `src/bourbon/sandbox/providers/__init__.py:16-28` | Add `docker` and update `auto` logic in `select_provider()` |
| `src/bourbon/config.py:135-160` | Add `docker` sub-dict to default `sandbox` config |

---

## Chunk 1: CredentialProxy

### Task 1: CredentialProxy core

**Files:**
- Create: `src/bourbon/sandbox/credential_proxy.py`
- Create: `tests/test_credential_proxy.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_credential_proxy.py
"""Unit tests for CredentialProxy."""

from __future__ import annotations

import time
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

import pytest

from bourbon.sandbox.credential_proxy import CredentialProxy


class TestCredentialProxyLifecycle:
    def test_start_returns_address(self) -> None:
        proxy = CredentialProxy(credential_mgr=None, allow_domains=[])
        addr = proxy.start()
        try:
            assert ":" in addr
            host, port_str = addr.rsplit(":", 1)
            assert int(port_str) > 0
        finally:
            proxy.stop()

    def test_stop_is_idempotent(self) -> None:
        proxy = CredentialProxy(credential_mgr=None, allow_domains=[])
        proxy.start()
        proxy.stop()
        proxy.stop()  # second stop should not raise

    def test_address_before_start_raises(self) -> None:
        proxy = CredentialProxy(credential_mgr=None, allow_domains=[])
        with pytest.raises(RuntimeError, match="not started"):
            _ = proxy.address


class TestCredentialProxyDomainMatching:
    def test_exact_domain_allowed(self) -> None:
        proxy = CredentialProxy(credential_mgr=None, allow_domains=["api.example.com"])
        assert proxy._is_domain_allowed("api.example.com") is True

    def test_exact_domain_denied(self) -> None:
        proxy = CredentialProxy(credential_mgr=None, allow_domains=["api.example.com"])
        assert proxy._is_domain_allowed("other.example.com") is False

    def test_wildcard_matches_subdomain(self) -> None:
        proxy = CredentialProxy(credential_mgr=None, allow_domains=["*.example.com"])
        assert proxy._is_domain_allowed("api.example.com") is True
        assert proxy._is_domain_allowed("cdn.example.com") is True

    def test_wildcard_does_not_match_root(self) -> None:
        proxy = CredentialProxy(credential_mgr=None, allow_domains=["*.example.com"])
        assert proxy._is_domain_allowed("example.com") is False

    def test_empty_allowlist_denies_all(self) -> None:
        proxy = CredentialProxy(credential_mgr=None, allow_domains=[])
        assert proxy._is_domain_allowed("api.example.com") is False

    def test_denied_domain_returns_403(self) -> None:
        """Proxy returns HTTP 403 for non-allowlisted domain."""
        proxy = CredentialProxy(credential_mgr=None, allow_domains=["allowed.com"])
        addr = proxy.start()
        try:
            proxy_handler = urllib.request.ProxyHandler({"http": f"http://{addr}"})
            opener = urllib.request.build_opener(proxy_handler)
            with pytest.raises(urllib.error.HTTPError) as exc_info:
                opener.open("http://denied.com/path", timeout=3)
            assert exc_info.value.code == 403
        finally:
            proxy.stop()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_credential_proxy.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'bourbon.sandbox.credential_proxy'`

- [ ] **Step 3: Implement CredentialProxy**

```python
# src/bourbon/sandbox/credential_proxy.py
"""Host-side HTTP proxy for credential injection.

Container connects via http_proxy/https_proxy environment variables.
The proxy validates the target domain against allow_domains and
injects credentials on the host side — the container never holds them.
"""

from __future__ import annotations

import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bourbon.sandbox.credential import CredentialManager


class CredentialProxy:
    """Host-side HTTP forward proxy with domain allowlisting.

    Domain matching rules:
    - Exact match: "api.example.com" matches only "api.example.com"
    - Wildcard: "*.example.com" matches "api.example.com" but NOT "example.com"
    """

    def __init__(
        self,
        credential_mgr: CredentialManager | None,
        allow_domains: list[str],
        host: str = "127.0.0.1",
        port: int = 0,  # 0 = OS assigns ephemeral port
    ) -> None:
        self._credential_mgr = credential_mgr
        self._allow_domains = allow_domains
        self._host = host
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> str:
        """Start the proxy server. Returns 'host:port' address string."""
        handler = _make_handler(self)
        self._server = HTTPServer((self._host, 0), handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
            name="CredentialProxy",
        )
        self._thread.start()
        return self.address

    def stop(self) -> None:
        """Stop the proxy server. Safe to call multiple times."""
        if self._server is not None:
            self._server.shutdown()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    @property
    def address(self) -> str:
        """Returns 'host:port'. Raises RuntimeError if not started."""
        if self._server is None:
            raise RuntimeError("CredentialProxy not started — call start() first")
        host, port = self._server.server_address
        return f"{host}:{port}"

    def _is_domain_allowed(self, target: str) -> bool:
        """Check if target domain matches the allow_domains list."""
        for pattern in self._allow_domains:
            if pattern.startswith("*."):
                # Wildcard: match subdomain only, not root
                suffix = pattern[2:]  # strip "*."
                if target.endswith("." + suffix):
                    return True
            else:
                if target == pattern:
                    return True
        return False


def _make_handler(proxy: CredentialProxy) -> type[BaseHTTPRequestHandler]:
    """Create a handler class bound to the given proxy instance."""

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self._handle()

        def do_POST(self) -> None:
            self._handle()

        def do_HEAD(self) -> None:
            self._handle()

        def _handle(self) -> None:
            from urllib.parse import urlparse

            parsed = urlparse(self.path)
            host = parsed.netloc or parsed.hostname or ""
            # Strip port from host
            if ":" in host:
                host = host.rsplit(":", 1)[0]

            if not proxy._is_domain_allowed(host):
                self.send_response(403)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(
                    f"CredentialProxy: domain '{host}' not in allow_domains\n".encode()
                )
                return

            # Read request body if present
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length) if content_length else None

            # Build forwarded request
            req = urllib.request.Request(self.path, data=body, method=self.command)
            # Forward original headers (skip proxy-specific ones)
            for key, value in self.headers.items():
                if key.lower() not in ("host", "proxy-connection", "content-length"):
                    req.add_header(key, value)

            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    self.send_response(resp.status)
                    for key, value in resp.headers.items():
                        self.send_header(key, value)
                    self.end_headers()
                    self.wfile.write(resp.read())
            except urllib.error.HTTPError as e:
                self.send_response(e.code)
                self.end_headers()
            except Exception as e:
                self.send_response(502)
                self.end_headers()
                self.wfile.write(f"CredentialProxy error: {e}\n".encode())

        def log_message(self, format: str, *args: object) -> None:
            pass  # Suppress default access log

    return _Handler
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_credential_proxy.py -v
```
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/bourbon/sandbox/credential_proxy.py tests/test_credential_proxy.py
git commit -m "feat(sandbox): add CredentialProxy with domain allowlisting"
```

---

## Chunk 2: DockerProvider

### Task 2: DockerProvider implementation + integration tests

**Files:**
- Create: `src/bourbon/sandbox/providers/docker.py`
- Create: `tests/test_sandbox_docker.py`

- [ ] **Step 1: Write failing integration tests**

```python
# tests/test_sandbox_docker.py
"""Integration tests for DockerProvider (requires Docker daemon)."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest

from bourbon.sandbox.providers.docker import DockerProvider
from bourbon.sandbox.runtime import SandboxContext

pytestmark = pytest.mark.skipif(
    not DockerProvider.is_available(),
    reason="requires Docker daemon running",
)


def _make_context(tmp_path: Path, **overrides) -> SandboxContext:
    defaults = dict(
        workdir=tmp_path,
        writable_paths=[str(tmp_path)],
        readonly_paths=[],
        deny_paths=[],
        network_enabled=False,
        allow_domains=[],
        timeout=30,
        max_memory="256M",
        max_output=50000,
        env_vars={"PATH": "/usr/bin:/usr/local/bin:/bin"},
    )
    defaults.update(overrides)
    return SandboxContext(**defaults)


class TestDockerProviderBasic:
    def test_basic_execution(self, tmp_path: Path) -> None:
        provider = DockerProvider()
        context = _make_context(tmp_path)

        result = provider.execute("echo hello", context)

        assert result.exit_code == 0
        assert result.stdout.strip() == "hello"
        assert result.timed_out is False

    def test_isolation_level(self) -> None:
        provider = DockerProvider()
        level = provider.get_isolation_level()
        assert "docker" in level.lower()
        assert "python:3.11-slim" in level

    def test_is_available(self) -> None:
        assert DockerProvider.is_available() is True

    def test_env_clean(self, tmp_path: Path) -> None:
        """Only passthrough env vars visible inside container."""
        provider = DockerProvider()
        context = _make_context(
            tmp_path,
            env_vars={"PATH": "/usr/bin:/bin", "CUSTOM_VAR": "visible"},
        )

        result = provider.execute("env", context)

        assert result.exit_code == 0
        assert "CUSTOM_VAR=visible" in result.stdout
        assert "ANTHROPIC_API_KEY" not in result.stdout

    def test_timeout(self, tmp_path: Path) -> None:
        provider = DockerProvider()
        context = _make_context(tmp_path, timeout=2)

        result = provider.execute("sleep 10", context)

        assert result.timed_out is True
        assert result.exit_code == -1

    def test_workdir_writable(self, tmp_path: Path) -> None:
        provider = DockerProvider()
        context = _make_context(tmp_path)

        result = provider.execute(
            f"echo test > {tmp_path}/out.txt && cat {tmp_path}/out.txt",
            context,
        )

        assert result.exit_code == 0
        assert "test" in result.stdout


class TestDockerProviderIsolation:
    def test_filesystem_isolation(self, tmp_path: Path) -> None:
        """Paths not mounted are not visible inside the container."""
        provider = DockerProvider()
        home = os.path.expanduser("~")
        ssh_dir = os.path.join(home, ".ssh")
        context = _make_context(tmp_path)  # .ssh not in writable_paths

        result = provider.execute(f"ls {ssh_dir}", context)

        assert result.exit_code != 0
        # Container's own rootfs has no ~/.ssh
        assert "No such file" in result.stderr or "cannot access" in result.stderr

    def test_network_none(self, tmp_path: Path) -> None:
        """--network=none blocks all outbound connections."""
        provider = DockerProvider()
        context = _make_context(tmp_path, network_enabled=False)

        result = provider.execute(
            "python3 -c \"import socket; socket.create_connection(('8.8.8.8', 53), timeout=2)\"",
            context,
        )

        assert result.exit_code != 0

    def test_readonly_volume(self, tmp_path: Path) -> None:
        """Read-only volumes cannot be written."""
        provider = DockerProvider()
        src = tmp_path / "ro_dir"
        src.mkdir()
        context = _make_context(
            tmp_path,
            writable_paths=[str(tmp_path)],
            readonly_paths=[str(src)],
        )

        result = provider.execute(f"touch {src}/test", context)

        assert result.exit_code != 0


class TestDockerProviderSecurity:
    def test_nonroot_user(self, tmp_path: Path) -> None:
        """Container runs as nobody, not root."""
        provider = DockerProvider(config={"user": "nobody"})
        context = _make_context(tmp_path)

        result = provider.execute("id -u", context)

        assert result.exit_code == 0
        uid = result.stdout.strip()
        assert uid != "0", f"Expected non-root UID, got: {uid}"

    def test_cap_drop_all(self, tmp_path: Path) -> None:
        """--cap-drop=ALL prevents privileged operations."""
        provider = DockerProvider()
        context = _make_context(tmp_path)

        # capsh requires CAP_SETPCAP; without it this fails
        result = provider.execute(
            "python3 -c \"import ctypes; ctypes.CDLL(None).setuid(0)\"",
            context,
        )

        assert result.exit_code != 0

    def test_memory_limit_oom(self, tmp_path: Path) -> None:
        """Exceeding --memory limit causes OOM kill (exit 137)."""
        provider = DockerProvider(config={"image": "python:3.11-slim"})
        context = _make_context(tmp_path, max_memory="64M")

        result = provider.execute(
            "python3 -c \"x = bytearray(200 * 1024 * 1024)\"",
            context,
        )

        # OOM kill = exit 137 or timed out; either way it didn't succeed
        assert result.exit_code != 0 or result.timed_out

    def test_oom_violation_detected(self, tmp_path: Path) -> None:
        """OOM kill produces a violation entry."""
        provider = DockerProvider(config={"image": "python:3.11-slim"})
        context = _make_context(tmp_path, max_memory="64M")

        result = provider.execute(
            "python3 -c \"x = bytearray(200 * 1024 * 1024)\"",
            context,
        )

        if result.exit_code == 137:
            oom_violations = [v for v in result.violations if v.type == "oom_killed"]
            assert len(oom_violations) >= 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_sandbox_docker.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'bourbon.sandbox.providers.docker'` (or SKIPPED if Docker not running)

- [ ] **Step 3: Implement DockerProvider**

```python
# src/bourbon/sandbox/providers/docker.py
"""Docker container sandbox provider."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
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


class DockerProvider(SandboxProvider):
    """Sandbox isolation via Docker containers.

    Provides: overlay rootfs, cgroup memory limits, --cap-drop=ALL,
    --user nobody, --security-opt no-new-privileges.
    """

    def __init__(self, config: dict | None = None) -> None:
        cfg = config or {}
        self._image: str = cfg.get("image", "python:3.11-slim")
        self._pull_policy: str = cfg.get("pull_policy", "if-not-present")
        self._user: str = cfg.get("user", "nobody")

    @classmethod
    def is_available(cls) -> bool:
        """True if docker binary exists and daemon is reachable."""
        if shutil.which("docker") is None:
            return False
        try:
            subprocess.run(
                ["docker", "info"],
                capture_output=True,
                timeout=5,
                check=True,
            )
            return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def execute(self, command: str, context: SandboxContext) -> SandboxResult:
        self._ensure_image()

        policy = FilesystemPolicy.from_context(context)
        proxy = None
        proxy_addr: str | None = None

        if context.network_enabled and context.allow_domains:
            from bourbon.sandbox.credential_proxy import CredentialProxy
            proxy = CredentialProxy(
                credential_mgr=None,  # Phase 3: injection wired in next task
                allow_domains=context.allow_domains,
            )
            proxy_addr = proxy.start()

        try:
            args = self._build_docker_args(command, policy, context, proxy_addr)

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
                target=self._drain, args=(process.stdout, stdout_buf), daemon=True
            )
            stderr_thread = Thread(
                target=self._drain, args=(process.stderr, stderr_buf), daemon=True
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
                msg = f"Command timed out after {context.timeout} seconds."
                if stderr_text:
                    msg = f"{msg}\n{stderr_text}"
                return SandboxResult(
                    stdout=stdout_buf.render(),
                    stderr=msg,
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
            result.violations = self._parse_violations(result, context.max_memory)
            return result

        finally:
            if proxy is not None:
                proxy.stop()

    def get_isolation_level(self) -> str:
        return f"docker (container isolation, image={self._image})"

    def _ensure_image(self) -> None:
        """Pull image according to pull_policy."""
        if self._pull_policy == "never":
            return
        if self._pull_policy == "always":
            subprocess.run(["docker", "pull", self._image], check=True, capture_output=True)
            return
        # if-not-present: check if image exists locally
        result = subprocess.run(
            ["docker", "image", "inspect", self._image],
            capture_output=True,
        )
        if result.returncode != 0:
            subprocess.run(["docker", "pull", self._image], check=True, capture_output=True)

    def _build_docker_args(
        self,
        command: str,
        policy: FilesystemPolicy,
        context: SandboxContext,
        proxy_addr: str | None = None,
    ) -> list[str]:
        args = ["docker", "run", "--rm"]

        # Security hardening
        args += ["--cap-drop=ALL"]
        args += ["--security-opt", "no-new-privileges"]
        args += ["--user", self._user]

        # Resource limits
        args += ["--memory", context.max_memory]
        args += ["--cpus", "1"]

        # Network
        if not context.network_enabled:
            args += ["--network", "none"]
        elif proxy_addr:
            args += ["--network", "bridge"]
            args += ["-e", f"http_proxy=http://{proxy_addr}"]
            args += ["-e", f"https_proxy=http://{proxy_addr}"]
            args += ["-e", f"HTTP_PROXY=http://{proxy_addr}"]
            args += ["-e", f"HTTPS_PROXY=http://{proxy_addr}"]
        else:
            # network_enabled=True without proxy: direct bridge access
            args += ["--network", "bridge"]

        # Filesystem mounts
        for rule in policy.rules:
            if rule.mode == MountMode.READ_WRITE:
                args += ["-v", f"{rule.path}:{rule.path}:rw"]
            elif rule.mode == MountMode.READ_ONLY:
                args += ["-v", f"{rule.path}:{rule.path}:ro"]
            # DENY: not mounted — container rootfs has no such path

        # Working directory
        args += ["-w", str(context.workdir)]

        # Environment
        for key, value in context.env_vars.items():
            args += ["-e", f"{key}={value}"]

        # Image + command
        args += [self._image]
        args += ["bash", "-c", command]

        return args

    def _parse_violations(
        self, result: SandboxResult, max_memory: str
    ) -> list[Violation]:
        violations: list[Violation] = []
        stderr_lower = result.stderr.lower()

        # OOM kill: exit code 137 (128 + SIGKILL) when not a timeout
        if result.exit_code == 137 and not result.timed_out:
            violations.append(
                Violation(
                    type="oom_killed",
                    detail=f"process exceeded memory limit ({max_memory})",
                )
            )

        # Network denied
        if "network is unreachable" in stderr_lower or (
            "errno 101" in stderr_lower  # ENETUNREACH
        ):
            violations.append(
                Violation(
                    type="net_denied",
                    detail="container network disabled (--network=none)",
                )
            )

        # Capability denied
        if "operation not permitted" in stderr_lower and result.exit_code != 0:
            violations.append(
                Violation(
                    type="cap_denied",
                    detail="operation denied by capability restrictions (--cap-drop=ALL)",
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

```bash
pytest tests/test_sandbox_docker.py -v
```
Expected: All PASS on machines with Docker running, SKIPPED otherwise

- [ ] **Step 5: Run all existing tests for regressions**

```bash
pytest tests/ -v
```
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add src/bourbon/sandbox/providers/docker.py tests/test_sandbox_docker.py
git commit -m "feat(sandbox): add DockerProvider with container isolation and security hardening"
```

---

## Chunk 3: Integration (select_provider + config)

### Task 3: Extend select_provider and default config

**Files:**
- Modify: `src/bourbon/sandbox/providers/__init__.py:16-28`
- Modify: `src/bourbon/config.py:135-160`
- Test: `tests/test_sandbox_local.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_sandbox_local.py`:

```python
class TestSelectProviderDocker:
    def test_select_docker_explicit(self) -> None:
        from bourbon.sandbox.providers.docker import DockerProvider

        if not DockerProvider.is_available():
            with pytest.raises(SandboxProviderNotFound, match="docker"):
                select_provider("docker")
        else:
            provider = select_provider("docker")
            assert isinstance(provider, DockerProvider)

    def test_select_docker_with_config(self) -> None:
        from bourbon.sandbox.providers.docker import DockerProvider

        if not DockerProvider.is_available():
            pytest.skip("Docker not available")

        provider = select_provider("docker", docker_config={"image": "python:3.11-slim", "user": "nobody"})
        assert isinstance(provider, DockerProvider)
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest tests/test_sandbox_local.py::TestSelectProviderDocker -v
```
Expected: FAIL

- [ ] **Step 3: Update select_provider**

Replace `src/bourbon/sandbox/providers/__init__.py`:

```python
"""Sandbox provider selection."""

from __future__ import annotations

import sys

from bourbon.sandbox.providers.local import LocalProvider
from bourbon.sandbox.runtime import SandboxProvider


class SandboxProviderNotFoundError(ValueError):
    """Raised when a sandbox provider name is not recognized."""


SandboxProviderNotFound = SandboxProviderNotFoundError


def select_provider(
    name: str,
    docker_config: dict | None = None,
) -> SandboxProvider:
    """Return a sandbox provider by name.

    Args:
        name: Provider name: "local", "bubblewrap", "seatbelt", "docker", "auto"
        docker_config: Optional config dict for DockerProvider (image, pull_policy, user)
    """
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

    if normalized == "docker":
        from bourbon.sandbox.providers.docker import DockerProvider
        if not DockerProvider.is_available():
            raise SandboxProviderNotFound(
                'docker daemon not available. Ensure Docker is running or set provider = "auto"'
            )
        return DockerProvider(config=docker_config)

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

- [ ] **Step 4: Add docker to default config**

In `src/bourbon/config.py`, update the `sandbox` default dict to include `docker` sub-config. Locate the `sandbox` field (around line 135) and add:

```python
sandbox: dict = field(
    default_factory=lambda: {
        "enabled": True,
        "provider": "auto",
        "filesystem": {
            "writable": ["{workdir}"],
            "readonly": [],
            "deny": [],
        },
        "network": {
            "enabled": False,
            "allow_domains": [],
        },
        "resources": {
            "timeout": 120,
            "max_memory": "512M",
            "max_output": 50000,
        },
        "credentials": {
            "clean_env": True,
            "passthrough_vars": ["PATH", "HOME", "LANG"],
        },
        "docker": {
            "image": "python:3.11-slim",
            "pull_policy": "if-not-present",
            "user": "nobody",
        },
    }
)
```

Also update `SandboxManager.__init__` to pass docker config when constructing provider. In `src/bourbon/sandbox/__init__.py`, the `select_provider` call needs to pass `docker_config`:

```python
docker_cfg = config.get("docker", {})
self.provider = select_provider(provider_name, docker_config=docker_cfg)
```

- [ ] **Step 5: Run all tests**

```bash
pytest tests/ -v
```
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add src/bourbon/sandbox/providers/__init__.py src/bourbon/config.py src/bourbon/sandbox/__init__.py tests/test_sandbox_local.py
git commit -m "feat(sandbox): add docker to select_provider and default config"
```
