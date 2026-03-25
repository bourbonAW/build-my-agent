"""Tests for the local sandbox provider."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from bourbon.sandbox import SandboxManager
from bourbon.sandbox.providers import SandboxProviderNotFound, select_provider
from bourbon.sandbox.providers.local import LocalProvider
from bourbon.sandbox.runtime import ResourceUsage, SandboxContext, SandboxResult, Violation


class TestSandboxRuntime:
    def test_runtime_dataclasses(self) -> None:
        resource_usage = ResourceUsage()
        context = SandboxContext(
            workdir=Path("/tmp/work"),
            writable_paths=["/tmp/work"],
            readonly_paths=["/tmp/ro"],
            deny_paths=["/tmp/deny"],
            network_enabled=False,
            allow_domains=["example.com"],
            timeout=5,
            max_memory="256M",
            max_output=100,
            env_vars={"CUSTOM": "value"},
        )
        result = SandboxResult(
            stdout="out",
            stderr="err",
            exit_code=0,
            timed_out=False,
            resource_usage=resource_usage,
        )

        assert resource_usage.cpu_time == 0.0
        assert resource_usage.memory_peak == "0M"
        assert resource_usage.files_written == []
        assert context.workdir == Path("/tmp/work")
        assert context.writable_paths == ["/tmp/work"]
        assert context.max_memory == "256M"
        assert result.stdout == "out"


class TestSelectProvider:
    def test_select_local_provider(self) -> None:
        provider = select_provider("local")

        assert isinstance(provider, LocalProvider)

    def test_select_auto_provider_returns_local_provider(self) -> None:
        provider = select_provider("auto")

        assert isinstance(provider, LocalProvider)

    def test_unknown_provider_raises(self) -> None:
        with pytest.raises(SandboxProviderNotFound, match="missing"):
            select_provider("missing")


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


class TestProviderAvailability:
    def test_local_provider_always_available(self) -> None:
        assert LocalProvider.is_available() is True

    def test_sandbox_provider_default_available(self) -> None:
        from bourbon.sandbox.runtime import SandboxProvider
        assert SandboxProvider.is_available() is True


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


class TestLocalProvider:
    def test_simple_command(self, tmp_path: Path) -> None:
        provider = LocalProvider()
        context = SandboxContext(
            workdir=tmp_path,
            writable_paths=[],
            readonly_paths=[],
            deny_paths=[],
            network_enabled=False,
            allow_domains=[],
            timeout=5,
            max_memory="0M",
            max_output=0,
            env_vars={},
        )

        result = provider.execute("echo hello", context)

        assert result.exit_code == 0
        assert result.timed_out is False
        assert result.stdout.strip() == "hello"
        assert result.stderr == ""
        assert result.resource_usage.cpu_time >= 0
        assert result.resource_usage.memory_peak == "0M"
        assert result.resource_usage.files_written == []

    def test_timeout(self, tmp_path: Path) -> None:
        provider = LocalProvider()
        context = SandboxContext(
            workdir=tmp_path,
            writable_paths=[],
            readonly_paths=[],
            deny_paths=[],
            network_enabled=False,
            allow_domains=[],
            timeout=1,
            max_memory="0M",
            max_output=0,
            env_vars={},
        )

        result = provider.execute("sleep 2", context)

        assert result.timed_out is True
        assert result.exit_code == -1
        assert "command timed out after" in result.stderr.lower()
        assert result.resource_usage.cpu_time >= 0

    def test_env_passthrough_visible(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        provider = LocalProvider()
        monkeypatch.setenv("ANTHROPIC_API_KEY", "secret")
        context = SandboxContext(
            workdir=tmp_path,
            writable_paths=[],
            readonly_paths=[],
            deny_paths=[],
            network_enabled=False,
            allow_domains=[],
            timeout=5,
            max_memory="0M",
            max_output=0,
            env_vars={"PATH": os.environ.get("PATH", ""), "CUSTOM_FLAG": "enabled"},
        )

        result = provider.execute("env", context)

        assert result.exit_code == 0
        assert "CUSTOM_FLAG=enabled" in result.stdout
        assert "ANTHROPIC_API_KEY" not in result.stdout

    def test_output_truncation(self, tmp_path: Path) -> None:
        provider = LocalProvider()
        context = SandboxContext(
            workdir=tmp_path,
            writable_paths=[],
            readonly_paths=[],
            deny_paths=[],
            network_enabled=False,
            allow_domains=[],
            timeout=5,
            max_memory="0M",
            max_output=10,
            env_vars={"PATH": os.environ.get("PATH", "")},
        )

        result = provider.execute("python -c 'print(\"x\" * 100)'", context)

        assert result.stdout.endswith("...")
        assert len(result.stdout) == 10

    def test_stderr_truncation(self, tmp_path: Path) -> None:
        provider = LocalProvider()
        context = SandboxContext(
            workdir=tmp_path,
            writable_paths=[],
            readonly_paths=[],
            deny_paths=[],
            network_enabled=False,
            allow_domains=[],
            timeout=5,
            max_memory="0M",
            max_output=10,
            env_vars={"PATH": os.environ.get("PATH", "")},
        )

        result = provider.execute(
            "python -c 'import sys; sys.stderr.write(\"y\" * 100)'",
            context,
        )

        assert result.stderr.endswith("...")
        assert len(result.stderr) == 10

    def test_isolation_level(self) -> None:
        provider = LocalProvider()

        assert provider.get_isolation_level() == "local (no OS isolation)"

    def test_failed_command(self, tmp_path: Path) -> None:
        provider = LocalProvider()
        context = SandboxContext(
            workdir=tmp_path,
            writable_paths=[],
            readonly_paths=[],
            deny_paths=[],
            network_enabled=False,
            allow_domains=[],
            timeout=5,
            max_memory="0M",
            max_output=0,
            env_vars={"PATH": os.environ.get("PATH", "")},
        )

        result = provider.execute("python -c 'import sys; sys.exit(3)'", context)

        assert result.exit_code == 3
        assert result.timed_out is False
        assert result.resource_usage.cpu_time >= 0
