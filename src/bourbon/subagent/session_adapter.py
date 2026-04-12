"""Session adapter for isolated subagent conversations."""

from __future__ import annotations

from bourbon.session.manager import Session, SessionManager
from bourbon.session.storage import TranscriptStore


class SubagentSessionAdapter:
    """Creates an isolated session environment for one subagent run."""

    def __init__(
        self,
        parent_store: TranscriptStore,
        project_name: str,
        project_dir: str,
        run_id: str,
    ):
        self.parent_store = parent_store
        self.project_name = f"{project_name}/subagents"
        self.project_dir = project_dir
        self.run_id = run_id

    def create_session(self) -> Session:
        """Create a subagent session through the canonical SessionManager path."""
        manager = SessionManager(
            store=self.parent_store,
            project_name=self.project_name,
            project_dir=self.project_dir,
        )
        return manager.create_session(description=f"Subagent run {self.run_id}")
