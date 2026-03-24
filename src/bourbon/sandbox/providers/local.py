"""Local sandbox provider."""

from __future__ import annotations

import subprocess
import time
from threading import Thread
from typing import BinaryIO

from bourbon.sandbox.runtime import (
    ResourceUsage,
    SandboxContext,
    SandboxProvider,
    SandboxResult,
)


class _BoundedOutput:
    """Capture stream output without retaining more than max_output bytes."""

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


class LocalProvider(SandboxProvider):
    """Execute commands locally without OS-level isolation."""

    def execute(self, command: str, context: SandboxContext) -> SandboxResult:
        started_at = time.monotonic()
        process = subprocess.Popen(
            command,
            shell=True,
            cwd=context.workdir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=context.env_vars,
        )
        assert process.stdout is not None
        assert process.stderr is not None

        stdout_buffer = _BoundedOutput(context.max_output)
        stderr_buffer = _BoundedOutput(context.max_output)
        stdout_thread = Thread(
            target=self._drain_stream,
            args=(process.stdout, stdout_buffer),
            daemon=True,
        )
        stderr_thread = Thread(
            target=self._drain_stream,
            args=(process.stderr, stderr_buffer),
            daemon=True,
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
            stderr = self._with_timeout_message(
                stderr_buffer.render(),
                timeout=context.timeout,
            )
            return SandboxResult(
                stdout=stdout_buffer.render(),
                stderr=stderr,
                exit_code=-1,
                timed_out=True,
                resource_usage=ResourceUsage(
                    cpu_time=elapsed,
                    memory_peak="0M",
                    files_written=[],
                ),
            )

        stdout_thread.join()
        stderr_thread.join()
        elapsed = time.monotonic() - started_at
        return SandboxResult(
            stdout=stdout_buffer.render(),
            stderr=stderr_buffer.render(),
            exit_code=exit_code,
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
    def _drain_stream(stream: BinaryIO, buffer: _BoundedOutput) -> None:
        try:
            while chunk := stream.read(4096):
                buffer.append(chunk)
        finally:
            stream.close()

    @staticmethod
    def _with_timeout_message(stderr_output: str, *, timeout: int) -> str:
        message = f"Command timed out after {timeout} seconds."
        if stderr_output:
            return f"{message}\n{stderr_output}"
        return message
