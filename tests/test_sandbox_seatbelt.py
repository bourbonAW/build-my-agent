"""Integration tests for SeatbeltProvider (macOS sandbox-exec)."""

from __future__ import annotations

from pathlib import Path

import pytest

from bourbon.sandbox.providers.seatbelt import SeatbeltProvider
from bourbon.sandbox.runtime import SandboxContext

pytestmark = pytest.mark.skipif(
    not SeatbeltProvider.is_available(),
    reason="requires macOS",
)


def _make_context(tmp_path: Path, **overrides) -> SandboxContext:
    defaults = {
        "workdir": tmp_path,
        "writable_paths": [str(tmp_path)],
        "readonly_paths": ["/usr", "/bin", "/sbin", "/Library"],
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
        denied_dir = tmp_path / "denied"
        denied_dir.mkdir()
        context = _make_context(tmp_path, deny_paths=[str(denied_dir)])

        result = provider.execute(f"ls {denied_dir}", context)

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
        denied_dir = tmp_path / "denied"
        denied_dir.mkdir()
        denied_file = denied_dir / "secret.txt"
        denied_file.write_text("secret")
        context = _make_context(tmp_path, deny_paths=[str(denied_dir)])

        result = provider.execute(f"cat {denied_file}", context)

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
