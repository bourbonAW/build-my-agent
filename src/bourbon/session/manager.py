"""Session and SessionManager - orchestrate chain, storage, and context."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from .chain import MessageChain
from .context import ContextManager
from .storage import TranscriptStore
from .types import (
    CompactResult,
    CompactTrigger,
    SessionMetadata,
    SessionSummary,
    TranscriptMessage,
)


class Session:
    """A single conversation session.

    Orchestrates MessageChain (in-memory), TranscriptStore (persistence),
    and ContextManager (token tracking / compact).
    """

    def __init__(
        self,
        metadata: SessionMetadata,
        store: TranscriptStore,
        project_name: str,
        token_threshold: int = 100000,
        keep_tool_results: int = 3,
        compact_preserve_count: int = 3,
    ):
        self.metadata = metadata
        self.store = store
        self.project_name = project_name

        self.chain = MessageChain()
        self.context_manager = ContextManager(
            chain=self.chain,
            token_threshold=token_threshold,
            keep_tool_results=keep_tool_results,
            compact_preserve_count=compact_preserve_count,
        )
        self._compact_preserve_count = compact_preserve_count

    @property
    def session_id(self) -> UUID:
        return self.metadata.uuid

    def add_message(self, message: TranscriptMessage) -> None:
        """Add a message to the session.

        Finding 5b fix: Overwrite session_id to current session's UUID,
        since TranscriptMessage defaults to random uuid4().

        Order: chain.append() THEN append_to_transcript().
        This ordering means crash-before-persist loses the message (acceptable),
        while crash-after-persist allows correct rebuild (no orphans).
        """
        message.session_id = self.metadata.uuid
        self.chain.append(message)
        self.store.append_to_transcript(
            self.project_name, self.metadata.uuid, [message]
        )
        self.metadata.message_count += 1
        if message.usage:
            self.metadata.total_tokens_used += message.usage.total_tokens
        self.metadata.last_activity = datetime.now()

    def get_messages_for_llm(self) -> list[dict]:
        """Get messages formatted for LLM API."""
        return self.chain.get_llm_messages()

    def save(self) -> None:
        """Persist session metadata only."""
        self.store.save_metadata(
            self.project_name, self.metadata.uuid, self.metadata
        )

    def maybe_compact(
        self,
        trigger: CompactTrigger = CompactTrigger.AUTO_THRESHOLD,
    ) -> CompactResult | None:
        """Check if compact is needed and execute if so.

        Finding 2 fix: accepts trigger param, allows /compact to pass MANUAL.
        """
        if (
            trigger == CompactTrigger.AUTO_THRESHOLD
            and not self.context_manager.should_compact()
        ):
            return None

        summary = self.context_manager.generate_summary()
        result = self.chain.compact(
            preserve_count=self._compact_preserve_count,
            summary=summary,
            trigger=trigger,
        )

        if result.success:
            # Persist boundary message to transcript
            boundary_msg = self.chain.get(result.boundary_uuid)
            if boundary_msg:
                self.store.append_to_transcript(
                    self.project_name,
                    self.metadata.uuid,
                    [boundary_msg],
                )
            # Persist parent_uuid overrides to compact manifest
            self.store.save_compact_manifest(
                self.project_name,
                self.metadata.uuid,
                result.parent_uuid_overrides,
            )
            self.save()

        return result

    def load_and_rebuild(self) -> None:
        """Rebuild active chain from transcript + manifest."""
        transcript = self.store.load_transcript(
            self.project_name, self.metadata.uuid
        )
        overrides = self.store.load_compact_manifest(
            self.project_name, self.metadata.uuid
        )
        self.chain.rebuild_from_transcript(
            transcript, parent_uuid_overrides=overrides
        )


class SessionManager:
    """Manages session lifecycle: create, resume, list, delete."""

    def __init__(
        self,
        store: TranscriptStore,
        project_name: str,
        project_dir: str = "",
        token_threshold: int = 100000,
        keep_tool_results: int = 3,
        compact_preserve_count: int = 3,
    ):
        self.store = store
        self.project_name = project_name
        self.project_dir = project_dir
        self.token_threshold = token_threshold
        self.keep_tool_results = keep_tool_results
        self.compact_preserve_count = compact_preserve_count

    def create_session(
        self,
        session_id: UUID | None = None,
        parent_uuid: UUID | None = None,
        description: str = "",
    ) -> Session:
        """Create a new session."""
        now = datetime.now()
        sid = session_id or uuid4()

        metadata = SessionMetadata(
            uuid=sid,
            parent_uuid=parent_uuid,
            project_dir=self.project_dir,
            created_at=now,
            last_activity=now,
            description=description,
        )

        session = Session(
            metadata=metadata,
            store=self.store,
            project_name=self.project_name,
            token_threshold=self.token_threshold,
            keep_tool_results=self.keep_tool_results,
            compact_preserve_count=self.compact_preserve_count,
        )
        session.save()
        return session

    def resume_session(self, session_id: UUID) -> Session | None:
        """Resume an existing session by loading transcript and rebuilding chain."""
        metadata = self.store.load_metadata(self.project_name, session_id)
        if metadata is None:
            return None

        session = Session(
            metadata=metadata,
            store=self.store,
            project_name=self.project_name,
            token_threshold=self.token_threshold,
            keep_tool_results=self.keep_tool_results,
            compact_preserve_count=self.compact_preserve_count,
        )
        session.load_and_rebuild()
        return session

    def resume_latest(self) -> Session | None:
        """Resume the most recent active session."""
        sessions = self.store.list_sessions(self.project_name)
        for summary in sessions:
            if summary.is_resumable:
                return self.resume_session(summary.uuid)
        return None

    def list_sessions(self) -> list[SessionSummary]:
        """List all sessions."""
        return self.store.list_sessions(self.project_name)

    def delete_session(self, session_id: UUID) -> bool:
        """Delete a session and all its data."""
        return self.store.delete_session(self.project_name, session_id)
