"""Sandbox runtime coordination for Bourbon."""

from __future__ import annotations

import os
from pathlib import Path

from bourbon.audit import AuditLogger
from bourbon.audit.events import AuditEvent
from bourbon.sandbox.credential import CredentialManager
from bourbon.sandbox.providers import SandboxProviderNotFound, select_provider
from bourbon.sandbox.providers.local import LocalProvider
from bourbon.sandbox.runtime import ResourceUsage, SandboxContext, SandboxResult

__all__ = [
    "CredentialManager",
    "SandboxManager",
    "SandboxProviderNotFound",
]

_NETWORK_PATTERNS = (
    "curl ",
    "wget ",
    "http://",
    "https://",
    "pip install ",
    "pip3 install ",
    "git clone ",
    "git pull ",
    "git push ",
)


class SandboxManager:
    """Coordinates provider selection, context building, and execution."""

    def __init__(self, config: dict, workdir: Path, audit: AuditLogger) -> None:
        self.enabled = config.get("enabled", True)
        self.workdir = workdir
        self.audit = audit
        self.provider = None
        if self.enabled:
            provider_name = config.get("provider", "auto")
            docker_cfg = config.get("docker", {})
            self.provider = select_provider(provider_name, docker_config=docker_cfg)

        self.credential_mgr = CredentialManager()
        self._fs = config.get("filesystem", {})
        self._net = config.get("network", {})
        self._res = config.get("resources", {})
        self._cred = config.get("credentials", {})

    def execute(self, command: str, tool_name: str = "bash") -> SandboxResult:
        """Execute a command using the configured provider.

        Args:
            command: Shell command to execute.
            tool_name: The tool that triggered execution (used in audit events).
                       Defaults to "bash"; pass the real tool name when a second
                       sandboxed tool (e.g. "code_execute") is added.
        """
        if not self.enabled or self.provider is None:
            raise RuntimeError("SandboxManager.execute() called but sandbox is disabled")

        passthrough = self._cred.get("passthrough_vars", ["PATH", "HOME", "LANG"])
        clean_env = self._cred.get("clean_env", True)
        env_vars = (
            self.credential_mgr.clean_env(passthrough_vars=passthrough)
            if clean_env
            else {key: value for key, value in os.environ.items() if key in passthrough}
        )

        context = SandboxContext(
            workdir=self.workdir,
            writable_paths=self._resolve_paths(self._fs.get("writable", [str(self.workdir)])),
            readonly_paths=self._resolve_paths(self._fs.get("readonly", [])),
            deny_paths=self._resolve_paths(self._fs.get("deny", [])),
            network_enabled=self._net.get("enabled", False),
            allow_domains=list(self._net.get("allow_domains", [])),
            timeout=self._res.get("timeout", 120),
            max_memory=self._res.get("max_memory", "512M"),
            max_output=self._res.get("max_output", 50000),
            env_vars=env_vars,
        )

        if (
            not context.network_enabled
            and isinstance(self.provider, LocalProvider)
            and self._contains_network_activity(command)
        ):
            self.audit.record(
                AuditEvent.sandbox_violation(
                    tool_name=tool_name,
                    tool_input_summary=command[:200],
                    reason="network access disabled by sandbox policy",
                )
            )
            return SandboxResult(
                stdout="",
                stderr="Network access disabled by sandbox policy.",
                exit_code=1,
                timed_out=False,
                resource_usage=ResourceUsage(
                    cpu_time=0.0,
                    memory_peak="0M",
                    files_written=[],
                ),
            )

        result = self.provider.execute(command, context)
        for v in result.violations:
            self.audit.record(
                AuditEvent.sandbox_violation(
                    tool_name=tool_name,
                    tool_input_summary=command[:200],
                    reason=f"{v.type}: {v.detail}",
                )
            )
        self.audit.record(
            AuditEvent.sandbox_exec(
                tool_name=tool_name,
                tool_input_summary=command[:200],
                provider=self.provider.get_isolation_level(),
                exit_code=result.exit_code,
                timed_out=result.timed_out,
                resource_usage={
                    "cpu_time": result.resource_usage.cpu_time,
                    "memory_peak": result.resource_usage.memory_peak,
                    "files_written": result.resource_usage.files_written,
                },
            )
        )
        return result

    def _resolve_paths(self, paths: list[str]) -> list[str]:
        return [path.replace("{workdir}", str(self.workdir)) for path in paths]

    @staticmethod
    def _contains_network_activity(command: str) -> bool:
        # NOTE: This is a best-effort keyword scan, NOT real OS-level network isolation.
        # LocalProvider cannot block TCP at the kernel level; it only intercepts known
        # patterns (curl, wget, pip install, etc.).  Code that makes HTTP calls through
        # Python's urllib or requests without these keywords will bypass this check.
        # Phase 2 providers (Bubblewrap / Seatbelt) will enforce real network isolation.
        return any(pattern in command for pattern in _NETWORK_PATTERNS)
