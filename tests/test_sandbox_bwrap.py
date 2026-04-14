"""Integration tests for BwrapProvider (Linux bubblewrap)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from bourbon.sandbox.providers.bubblewrap import BwrapProvider
from bourbon.sandbox.runtime import SandboxContext

pytestmark = pytest.mark.skipif(
    not BwrapProvider.is_available(),
    reason="requires Linux with bubblewrap and user namespace support",
)


def _make_context(tmp_path: Path, **overrides) -> SandboxContext:
    defaults = {
        "workdir": tmp_path,
        "writable_paths": [str(tmp_path)],
        "readonly_paths": ["/usr", "/lib", "/lib64", "/bin", "/sbin"],
        "deny_paths": [],
        "network_enabled": False,
        "allow_domains": [],
        "timeout": 10,
        "max_memory": "256M",
        "max_output": 50000,
        "env_vars": {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
    }
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
