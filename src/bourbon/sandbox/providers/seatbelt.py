"""Seatbelt sandbox provider for macOS sandbox-exec isolation."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from threading import Thread
from typing import BinaryIO

from bourbon.sandbox.policy import FilesystemPolicy, MountMode
from bourbon.sandbox.runtime import (
    BoundedOutput,
    ResourceUsage,
    SandboxContext,
    SandboxProvider,
    SandboxResult,
    Violation,
)


class SeatbeltProvider(SandboxProvider):
    """macOS sandbox-exec isolation via SBPL profiles."""

    @classmethod
    def is_available(cls) -> bool:
        return sys.platform == "darwin"

    def execute(self, command: str, context: SandboxContext) -> SandboxResult:
        policy = FilesystemPolicy.from_context(context)
        profile = self._build_profile(policy, context)

        fd, profile_path = tempfile.mkstemp(suffix=".sb")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(profile)

            args = ["sandbox-exec", "-f", profile_path, "bash", "-c", command]

            started_at = time.monotonic()
            process = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=context.workdir,
                env=context.env_vars,
            )
            assert process.stdout is not None
            assert process.stderr is not None

            stdout_buf = BoundedOutput(context.max_output)
            stderr_buf = BoundedOutput(context.max_output)
            stdout_thread = Thread(
                target=self._drain,
                args=(process.stdout, stdout_buf),
                daemon=True,
            )
            stderr_thread = Thread(
                target=self._drain,
                args=(process.stderr, stderr_buf),
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
                stderr_text = stderr_buf.render()
                timeout_msg = f"Command timed out after {context.timeout} seconds."
                if stderr_text:
                    timeout_msg = f"{timeout_msg}\n{stderr_text}"
                return SandboxResult(
                    stdout=stdout_buf.render(),
                    stderr=timeout_msg,
                    exit_code=-1,
                    timed_out=True,
                    resource_usage=ResourceUsage(cpu_time=elapsed),
                )

            stdout_thread.join()
            stderr_thread.join()
            elapsed = time.monotonic() - started_at

            result = SandboxResult(
                stdout=stdout_buf.render(),
                stderr=stderr_buf.render(),
                exit_code=exit_code,
                timed_out=False,
                resource_usage=ResourceUsage(cpu_time=elapsed),
            )
            result.violations = self._parse_violations(result)
            return result
        finally:
            os.unlink(profile_path)

    def get_isolation_level(self) -> str:
        return "seatbelt (macOS sandbox-exec)"

    def _build_profile(
        self, policy: FilesystemPolicy, context: SandboxContext
    ) -> str:
        """Convert FilesystemPolicy to SBPL profile text.

        In seatbelt, when multiple rules match the same path,
        the last-added rule wins. So we write allow rules first,
        then deny rules — deny at the end overrides allow.
        """
        lines = [
            "(version 1)",
            "(deny default)",
            "",
            "; === base system permissions ===",
            "(allow process-exec)",
            "(allow process-fork)",
            "(allow sysctl-read)",
            "(allow mach-lookup)",
            "(allow ipc-posix-shm-read*)",
            "(allow ipc-posix-shm-write*)",
            "(allow signal (target self))",
            "",
            "; macOS process startup may read dyld/system metadata outside configured paths.",
            "; Explicit deny rules below still override this broad read allowance.",
            "(allow file-read*)",
            "",
            "; === /dev access ===",
            '(allow file-read* file-write* (subpath "/dev"))',
            "",
            "; === filesystem rules (allow first, deny last to override) ===",
        ]

        # Allow rules first
        for rule in policy.rules:
            if rule.mode == MountMode.READ_WRITE:
                lines.append(
                    f'(allow file-read* file-write* (subpath "{rule.path}"))'
                )
            elif rule.mode == MountMode.READ_ONLY:
                lines.append(f'(allow file-read* (subpath "{rule.path}"))')

        # Deny rules last (higher priority)
        for rule in policy.rules:
            if rule.mode == MountMode.DENY:
                lines.append(
                    f'(deny file-read* file-write* (subpath "{rule.path}"))'
                )

        # Network
        lines.append("")
        if context.network_enabled:
            lines.append("(allow network*)")
        else:
            lines.append("(deny network*)")

        return "\n".join(lines)

    def _parse_violations(self, result: SandboxResult) -> list[Violation]:
        """Best-effort violation detection from stderr."""
        violations: list[Violation] = []
        if "Operation not permitted" in result.stderr:
            violations.append(
                Violation(
                    type="path_denied",
                    detail="filesystem access denied by seatbelt profile",
                )
            )
        stderr_lower = result.stderr.lower()
        if (
            "network" in stderr_lower or "connect" in stderr_lower
        ) and "denied" in stderr_lower:
            violations.append(
                Violation(
                    type="net_denied",
                    detail="network access denied by seatbelt profile",
                )
            )
        return violations

    @staticmethod
    def _drain(stream: BinaryIO, buffer: BoundedOutput) -> None:
        try:
            while chunk := stream.read(4096):
                buffer.append(chunk)
        finally:
            stream.close()
