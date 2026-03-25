"""Local sandbox provider."""

from __future__ import annotations

import subprocess
import time
from threading import Thread
from typing import BinaryIO

from bourbon.sandbox.runtime import (
    BoundedOutput,
    ResourceUsage,
    SandboxContext,
    SandboxProvider,
    SandboxResult,
)


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

        stdout_buffer = BoundedOutput(context.max_output)
        stderr_buffer = BoundedOutput(context.max_output)
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
    def _drain_stream(stream: BinaryIO, buffer: BoundedOutput) -> None:
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
