"""Sandbox runtime contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


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


class SandboxProvider(ABC):
    """Sandbox execution backend."""

    @abstractmethod
    def execute(self, command: str, context: SandboxContext) -> SandboxResult:
        """Execute a command under the provider."""

    @abstractmethod
    def get_isolation_level(self) -> str:
        """Return a human-readable description of the isolation level."""
