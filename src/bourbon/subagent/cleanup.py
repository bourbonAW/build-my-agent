"""Resource cleanup for subagent runtime jobs."""

from __future__ import annotations

import atexit
import contextlib
import weakref

from bourbon.subagent.types import RunStatus, SubagentRun


class ResourceManager:
    """Tracks subagent runs and cleans up running resources on shutdown."""

    def __init__(self, *, register_atexit: bool = True):
        self._runs: weakref.WeakValueDictionary[str, SubagentRun] = (
            weakref.WeakValueDictionary()
        )
        if register_atexit:
            atexit.register(self.cleanup_all)

    def register(self, run: SubagentRun) -> None:
        """Register a runtime job for cleanup tracking."""
        self._runs[run.run_id] = run

    def cleanup_all(self) -> None:
        """Cleanup all currently running runtime jobs."""
        for run in list(self._runs.values()):
            if run.status == RunStatus.RUNNING:
                self.cleanup_run(run)

    def cleanup_run(self, run: SubagentRun) -> None:
        """Cleanup one runtime job."""
        if run.abort_controller is not None:
            run.abort_controller.abort()

        subagent = getattr(run, "_subagent", None)
        if subagent is not None:
            with contextlib.suppress(Exception):
                subagent.shutdown_mcp_sync()

        run.status = RunStatus.KILLED
