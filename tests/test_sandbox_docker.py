"""Integration tests for DockerProvider (requires Docker daemon)."""

from __future__ import annotations

import os
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
        # Make tmp_path world-writable so nobody user can write to it
        tmp_path.chmod(0o777)
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

        # os.setuid(0) raises PermissionError when CAP_SETUID is absent
        result = provider.execute(
            "python3 -c \"import os; os.setuid(0)\"",
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
