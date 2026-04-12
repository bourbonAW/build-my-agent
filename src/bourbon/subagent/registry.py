"""In-memory runtime-job registry for subagents."""

from __future__ import annotations

from datetime import datetime

from bourbon.subagent.types import RunStatus, SubagentRun


class RunRegistry:
    """Stores subagent runtime-job state for lookup and status updates."""

    def __init__(self):
        self._runs: dict[str, SubagentRun] = {}

    def register(self, run: SubagentRun) -> None:
        """Register a runtime job."""
        self._runs[run.run_id] = run

    def get(self, run_id: str) -> SubagentRun | None:
        """Return a runtime job by ID."""
        return self._runs.get(run_id)

    def get_run(self, run_id: str) -> SubagentRun | None:
        """Return a runtime job by ID using run-specific naming."""
        return self.get(run_id)

    def list_all(
        self,
        *,
        status: RunStatus | None = None,
        agent_type: str | None = None,
    ) -> list[SubagentRun]:
        """List runtime jobs with optional filtering."""
        runs = list(self._runs.values())

        if status is not None:
            runs = [run for run in runs if run.status == status]
        if agent_type is not None:
            runs = [run for run in runs if run.agent_type == agent_type]

        return runs

    def list_runs(
        self,
        *,
        status: RunStatus | None = None,
        agent_type: str | None = None,
    ) -> list[SubagentRun]:
        """List runtime jobs using run-specific naming."""
        return self.list_all(status=status, agent_type=agent_type)

    def update_status(self, run_id: str, status: RunStatus) -> bool:
        """Update runtime-job status."""
        run = self._runs.get(run_id)
        if run is None:
            return False

        run.status = status
        if status == RunStatus.RUNNING and run.started_at is None:
            run.started_at = datetime.now()
        return True

    def complete(self, run_id: str, result: str) -> bool:
        """Mark a runtime job as completed."""
        run = self._runs.get(run_id)
        if run is None:
            return False

        run.status = RunStatus.COMPLETED
        run.result = result
        run.completed_at = datetime.now()
        return True

    def fail(self, run_id: str, error: str) -> bool:
        """Mark a runtime job as failed."""
        run = self._runs.get(run_id)
        if run is None:
            return False

        run.status = RunStatus.FAILED
        run.error = error
        run.completed_at = datetime.now()
        return True
