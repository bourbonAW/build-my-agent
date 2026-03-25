"""Tests for SandboxManager."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from bourbon.audit.events import EventType
from bourbon.sandbox import SandboxManager
from bourbon.sandbox.runtime import ResourceUsage, SandboxContext, SandboxResult


class RecordingProvider:
    """Minimal provider stub that records execution context."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, SandboxContext]] = []

    def execute(self, command: str, context: SandboxContext) -> SandboxResult:
        self.calls.append((command, context))
        return SandboxResult(
            stdout="hello\n",
            stderr="",
            exit_code=0,
            timed_out=False,
            resource_usage=ResourceUsage(cpu_time=0.1, memory_peak="1M"),
        )

    def get_isolation_level(self) -> str:
        return "recording"


@pytest.fixture
def mock_audit() -> MagicMock:
    return MagicMock()


class TestSandboxManagerDisabled:
    def test_execute_raises_when_disabled(self, mock_audit: MagicMock) -> None:
        mgr = SandboxManager(config={"enabled": False}, workdir=Path("/tmp"), audit=mock_audit)

        assert mgr.enabled is False
        assert mgr.provider is None

        with pytest.raises(RuntimeError, match="sandbox is disabled"):
            mgr.execute("ls")


class TestSandboxManagerEnabled:
    def test_execute_calls_provider(
        self,
        mock_audit: MagicMock,
        tmp_path: Path,
    ) -> None:
        mgr = SandboxManager(
            config={"enabled": True, "provider": "local"},
            workdir=tmp_path,
            audit=mock_audit,
        )
        provider = RecordingProvider()
        mgr.provider = provider

        result = mgr.execute("echo hello")

        assert isinstance(result, SandboxResult)
        assert provider.calls[0][0] == "echo hello"

    def test_execute_records_audit_event(
        self,
        mock_audit: MagicMock,
        tmp_path: Path,
    ) -> None:
        mgr = SandboxManager(
            config={"enabled": True, "provider": "local"},
            workdir=tmp_path,
            audit=mock_audit,
        )
        mgr.provider = RecordingProvider()

        mgr.execute("echo hello")

        mock_audit.record.assert_called_once()
        event = mock_audit.record.call_args.args[0]
        assert event.event_type == EventType.SANDBOX_EXEC
        assert event.extra["provider"] == "recording"
        assert event.extra["exit_code"] == 0

    def test_workdir_placeholder_resolved_in_paths(
        self,
        mock_audit: MagicMock,
        tmp_path: Path,
    ) -> None:
        mgr = SandboxManager(
            config={
                "enabled": True,
                "provider": "local",
                "filesystem": {"writable": ["{workdir}/src"]},
            },
            workdir=tmp_path,
            audit=mock_audit,
        )
        provider = RecordingProvider()
        mgr.provider = provider

        mgr.execute("echo test")

        assert provider.calls[0][1].writable_paths == [f"{tmp_path}/src"]

    def test_execute_cleans_environment_before_provider(
        self,
        mock_audit: MagicMock,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("PATH", os.environ.get("PATH", ""))
        monkeypatch.setenv("CUSTOM_FLAG", "enabled")
        monkeypatch.setenv("OPENAI_API_KEY", "secret")

        mgr = SandboxManager(
            config={
                "enabled": True,
                "provider": "local",
                "credentials": {
                    "passthrough_vars": ["PATH", "CUSTOM_FLAG", "OPENAI_API_KEY"],
                },
            },
            workdir=tmp_path,
            audit=mock_audit,
        )
        provider = RecordingProvider()
        mgr.provider = provider

        mgr.execute("echo hello")

        env_vars = provider.calls[0][1].env_vars
        assert env_vars["CUSTOM_FLAG"] == "enabled"
        assert "PATH" in env_vars
        assert "OPENAI_API_KEY" not in env_vars

    def test_execute_tool_name_is_reflected_in_audit_event(
        self,
        mock_audit: MagicMock,
        tmp_path: Path,
    ) -> None:
        mgr = SandboxManager(
            config={"enabled": True, "provider": "local"},
            workdir=tmp_path,
            audit=mock_audit,
        )
        mgr.provider = RecordingProvider()

        mgr.execute("echo hello", tool_name="code_execute")

        mock_audit.record.assert_called_once()
        event = mock_audit.record.call_args.args[0]
        assert event.tool_name == "code_execute"

    def test_execute_blocks_network_commands_when_network_disabled(
        self,
        mock_audit: MagicMock,
        tmp_path: Path,
    ) -> None:
        # Network keyword scan only triggers for LocalProvider (real providers
        # use OS-level isolation and don't need the keyword heuristic).
        from bourbon.sandbox.providers.local import LocalProvider

        mgr = SandboxManager(
            config={
                "enabled": True,
                "provider": "local",
                "network": {"enabled": False, "allow_domains": []},
                "credentials": {"clean_env": False, "passthrough_vars": ["PATH"]},
            },
            workdir=tmp_path,
            audit=mock_audit,
        )
        assert isinstance(mgr.provider, LocalProvider)

        result = mgr.execute("curl https://example.com")

        assert result.exit_code != 0
        assert result.stdout == ""
        assert "network" in result.stderr.lower()
        mock_audit.record.assert_called_once()
