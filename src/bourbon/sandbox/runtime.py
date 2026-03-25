"""Sandbox runtime contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


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


@dataclass(slots=True)
class Violation:
    """A sandbox violation detected during execution."""

    type: str    # "path_denied" / "net_denied" / "exec_denied" / "oom_killed" / "cap_denied"
    detail: str  # Human-readable description


@dataclass(slots=True)
class ResourceUsage:
    """Resource usage reported by a sandbox execution."""

    cpu_time: float = 0.0
    memory_peak: str = "0M"
    files_written: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SandboxContext:
    """Execution context for a sandbox provider."""

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


@dataclass(slots=True)
class SandboxResult:
    """Result of a sandbox execution."""

    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool
    resource_usage: ResourceUsage
    violations: list[Violation] = field(default_factory=list)


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
