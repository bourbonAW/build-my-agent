"""Bubblewrap sandbox provider for Linux namespace isolation."""

from __future__ import annotations

import os
import shutil
import subprocess
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

# Minimal system paths required for bash and basic commands to function.
# These are always mounted read-only regardless of user configuration.
_SYSTEM_RO_BINDS = [
    "/usr",
    "/lib",
    "/lib64",
    "/bin",
    "/sbin",
]


class BwrapProvider(SandboxProvider):
    """Linux namespace isolation via bubblewrap."""

    @classmethod
    def is_available(cls) -> bool:
        """True if bwrap binary exists and can actually execute (user namespaces work)."""
        if shutil.which("bwrap") is None:
            return False
        try:
            result = subprocess.run(
                ["bwrap", "--ro-bind", "/", "/", "--", "true"],
                capture_output=True,
                timeout=5,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return False

    def execute(self, command: str, context: SandboxContext) -> SandboxResult:
        policy = FilesystemPolicy.from_context(context)
        args = self._build_args(command, policy, context)

        started_at = time.monotonic()
        process = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
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

    def get_isolation_level(self) -> str:
        return "bubblewrap (Linux namespace)"

    def _build_args(
        self, command: str, policy: FilesystemPolicy, context: SandboxContext
    ) -> list[str]:
        args = ["bwrap"]

        # System paths (always read-only)
        for sys_path in _SYSTEM_RO_BINDS:
            if os.path.exists(sys_path):
                args += ["--ro-bind", sys_path, sys_path]
        args += ["--proc", "/proc"]
        args += ["--dev", "/dev"]

        # Collect mounted paths to detect deny-as-subpath-of-mount
        mounted: list[str] = []

        # User-configured filesystem rules
        for rule in policy.rules:
            if rule.mode == MountMode.READ_WRITE:
                args += ["--bind", rule.path, rule.path]
                mounted.append(rule.path)
            elif rule.mode == MountMode.READ_ONLY:
                # Skip if already covered by _SYSTEM_RO_BINDS
                covered_by_system = any(
                    rule.path == path or rule.path.startswith(path + "/")
                    for path in _SYSTEM_RO_BINDS
                )
                if not covered_by_system and os.path.exists(rule.path):
                    args += ["--ro-bind", rule.path, rule.path]
                mounted.append(rule.path)

        # Deny rules: if deny path is a subpath of a mounted path, use --tmpfs
        for rule in policy.rules:
            deny_covers_mount = any(
                rule.path.startswith(m + "/") or rule.path.startswith(m + os.sep)
                for m in mounted
            )
            if rule.mode == MountMode.DENY and deny_covers_mount:
                args += ["--tmpfs", rule.path]

        # Network isolation
        if not context.network_enabled:
            args += ["--unshare-net"]

        # Process isolation
        args += ["--unshare-pid"]
        args += ["--new-session"]
        args += ["--die-with-parent"]

        # Clean environment
        args += ["--clearenv"]
        for key, value in context.env_vars.items():
            args += ["--setenv", key, value]

        # Working directory + command
        args += ["--chdir", str(context.workdir)]
        args += ["--", "bash", "-c", command]

        return args

    def _parse_violations(self, result: SandboxResult) -> list[Violation]:
        """Best-effort violation detection from stderr."""
        violations: list[Violation] = []
        if "Network is unreachable" in result.stderr:
            violations.append(
                Violation(
                    type="net_denied",
                    detail="network isolated by namespace (--unshare-net)",
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
