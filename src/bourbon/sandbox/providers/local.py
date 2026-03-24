"""Local sandbox provider."""

from __future__ import annotations

import subprocess
import time

from bourbon.sandbox.runtime import (
    ResourceUsage,
    SandboxContext,
    SandboxProvider,
    SandboxResult,
)


class LocalProvider(SandboxProvider):
    """Execute commands locally without OS-level isolation."""

    def execute(self, command: str, context: SandboxContext) -> SandboxResult:
        started_at = time.monotonic()
        try:
            completed = subprocess.run(
                command,
                shell=True,
                cwd=context.workdir,
                capture_output=True,
                text=True,
                timeout=context.timeout,
                env=context.env_vars,
            )
        except subprocess.TimeoutExpired as exc:
            elapsed = time.monotonic() - started_at
            stderr = f"Command timed out after {context.timeout} seconds."
            if exc.stderr:
                stderr = f"{stderr}\n{exc.stderr}"
            return SandboxResult(
                stdout=self._truncate_output(exc.output or "", context.max_output),
                stderr=stderr,
                exit_code=-1,
                timed_out=True,
                resource_usage=ResourceUsage(
                    cpu_time=elapsed,
                    memory_peak="0M",
                    files_written=[],
                ),
            )

        elapsed = time.monotonic() - started_at
        stdout = completed.stdout
        return SandboxResult(
            stdout=self._truncate_output(stdout, context.max_output),
            stderr=completed.stderr,
            exit_code=completed.returncode,
            timed_out=False,
            resource_usage=ResourceUsage(
                cpu_time=elapsed,
                memory_peak="0M",
                files_written=[],
            ),
        )

    def get_isolation_level(self) -> str:
        return "local (no OS isolation)"

    @staticmethod
    def _truncate_output(output: str, max_output: int) -> str:
        if max_output <= 0 or len(output) <= max_output:
            return output
        marker = "..."
        if max_output <= len(marker):
            return marker[:max_output]
        return f"{output[: max_output - len(marker)]}{marker}"
