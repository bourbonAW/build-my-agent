"""Docker container sandbox provider."""

from __future__ import annotations

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


class DockerProvider(SandboxProvider):
    """Sandbox isolation via Docker containers.

    Provides: overlay rootfs, cgroup memory limits, --cap-drop=ALL,
    --user nobody, --security-opt no-new-privileges.
    """

    def __init__(self, config: dict | None = None) -> None:
        cfg = config or {}
        self._image: str = cfg.get("image", "python:3.11-slim")
        self._pull_policy: str = cfg.get("pull_policy", "if-not-present")
        self._user: str = cfg.get("user", "nobody")

    @classmethod
    def is_available(cls) -> bool:
        """True if docker binary exists and daemon is reachable."""
        if shutil.which("docker") is None:
            return False
        try:
            subprocess.run(
                ["docker", "info"],
                capture_output=True,
                timeout=5,
                check=True,
            )
            return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def execute(self, command: str, context: SandboxContext) -> SandboxResult:
        self._ensure_image()

        policy = FilesystemPolicy.from_context(context)
        proxy = None
        proxy_addr: str | None = None

        if context.network_enabled and context.allow_domains:
            from bourbon.sandbox.credential_proxy import CredentialProxy
            proxy = CredentialProxy(
                credential_mgr=None,
                allow_domains=context.allow_domains,
            )
            proxy_addr = proxy.start()

        try:
            args = self._build_docker_args(command, policy, context, proxy_addr)

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
                target=self._drain, args=(process.stdout, stdout_buf), daemon=True
            )
            stderr_thread = Thread(
                target=self._drain, args=(process.stderr, stderr_buf), daemon=True
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
                msg = f"Command timed out after {context.timeout} seconds."
                if stderr_text:
                    msg = f"{msg}\n{stderr_text}"
                return SandboxResult(
                    stdout=stdout_buf.render(),
                    stderr=msg,
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
            result.violations = self._parse_violations(result, context.max_memory)
            return result

        finally:
            if proxy is not None:
                proxy.stop()

    def get_isolation_level(self) -> str:
        return f"docker (container isolation, image={self._image})"

    def _ensure_image(self) -> None:
        """Pull image according to pull_policy."""
        if self._pull_policy == "never":
            return
        if self._pull_policy == "always":
            subprocess.run(["docker", "pull", self._image], check=True, capture_output=True)
            return
        # if-not-present: check if image exists locally
        result = subprocess.run(
            ["docker", "image", "inspect", self._image],
            capture_output=True,
        )
        if result.returncode != 0:
            subprocess.run(["docker", "pull", self._image], check=True, capture_output=True)

    def _build_docker_args(
        self,
        command: str,
        policy: FilesystemPolicy,
        context: SandboxContext,
        proxy_addr: str | None = None,
    ) -> list[str]:
        args = ["docker", "run", "--rm"]

        # Security hardening
        args += ["--cap-drop=ALL"]
        args += ["--security-opt", "no-new-privileges"]
        args += ["--user", self._user]

        # Resource limits
        args += ["--memory", context.max_memory]
        args += ["--cpus", "1"]

        # Network
        if not context.network_enabled:
            args += ["--network", "none"]
        elif proxy_addr:
            args += ["--network", "bridge"]
            args += ["-e", f"http_proxy=http://{proxy_addr}"]
            args += ["-e", f"https_proxy=http://{proxy_addr}"]
            args += ["-e", f"HTTP_PROXY=http://{proxy_addr}"]
            args += ["-e", f"HTTPS_PROXY=http://{proxy_addr}"]
        else:
            # network_enabled=True without proxy: direct bridge access
            args += ["--network", "bridge"]

        # Filesystem mounts
        for rule in policy.rules:
            if rule.mode == MountMode.READ_WRITE:
                args += ["-v", f"{rule.path}:{rule.path}:rw"]
            elif rule.mode == MountMode.READ_ONLY:
                args += ["-v", f"{rule.path}:{rule.path}:ro"]
            # DENY: not mounted — container rootfs has no such path

        # Working directory
        args += ["-w", str(context.workdir)]

        # Environment
        for key, value in context.env_vars.items():
            args += ["-e", f"{key}={value}"]

        # Image + command
        args += [self._image]
        args += ["bash", "-c", command]

        return args

    def _parse_violations(
        self, result: SandboxResult, max_memory: str
    ) -> list[Violation]:
        violations: list[Violation] = []
        stderr_lower = result.stderr.lower()

        # OOM kill: exit code 137 (128 + SIGKILL) when not a timeout
        if result.exit_code == 137 and not result.timed_out:
            violations.append(
                Violation(
                    type="oom_killed",
                    detail=f"process exceeded memory limit ({max_memory})",
                )
            )

        # Network denied
        if "network is unreachable" in stderr_lower or "errno 101" in stderr_lower:
            violations.append(
                Violation(
                    type="net_denied",
                    detail="container network disabled (--network=none)",
                )
            )

        # Capability denied
        if "operation not permitted" in stderr_lower and result.exit_code != 0:
            violations.append(
                Violation(
                    type="cap_denied",
                    detail="operation denied by capability restrictions (--cap-drop=ALL)",
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
