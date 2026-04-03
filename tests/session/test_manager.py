"""Tests for Session and SessionManager."""

import pytest
from pathlib import Path
from uuid import uuid4

from bourbon.session.manager import Session, SessionManager
from bourbon.session.storage import TranscriptStore
from bourbon.session.types import (
    CompactTrigger,
    MessageRole,
    TextBlock,
    ToolResultBlock,
    TranscriptMessage,
)


@pytest.fixture
def store(tmp_path):
    return TranscriptStore(base_dir=tmp_path)


@pytest.fixture
def manager(store):
    return SessionManager(
        store=store,
        project_name="test_project",
        project_dir="/tmp/test",
        token_threshold=100000,
        compact_preserve_count=3,
    )


class TestSession:
    def test_add_message_persists(self, store):
        mgr = SessionManager(store=store, project_name="p", project_dir="/tmp")
        session = mgr.create_session()

        msg = TranscriptMessage(
            role=MessageRole.USER,
            content=[TextBlock(text="Hello")],
        )
        session.add_message(msg)

        # Verify persisted
        transcript = store.load_transcript("p", session.session_id)
        assert len(transcript) == 1
        assert transcript[0].uuid == msg.uuid
        assert transcript[0].session_id == session.session_id

    def test_add_message_overwrites_session_id(self, store):
        """Finding 5b: session_id must be overwritten to current session."""
        mgr = SessionManager(store=store, project_name="p", project_dir="/tmp")
        session = mgr.create_session()

        msg = TranscriptMessage(
            role=MessageRole.USER,
            content=[TextBlock(text="test")],
            session_id=uuid4(),  # Wrong session_id
        )
        session.add_message(msg)

        assert msg.session_id == session.session_id

    def test_add_message_increments_count(self, store):
        mgr = SessionManager(store=store, project_name="p", project_dir="/tmp")
        session = mgr.create_session()

        session.add_message(
            TranscriptMessage(role=MessageRole.USER, content=[TextBlock(text="1")])
        )
        session.add_message(
            TranscriptMessage(
                role=MessageRole.ASSISTANT, content=[TextBlock(text="2")]
            )
        )

        assert session.metadata.message_count == 2

    def test_get_messages_for_llm(self, store):
        mgr = SessionManager(store=store, project_name="p", project_dir="/tmp")
        session = mgr.create_session()

        session.add_message(
            TranscriptMessage(role=MessageRole.USER, content=[TextBlock(text="hi")])
        )
        session.add_message(
            TranscriptMessage(
                role=MessageRole.ASSISTANT, content=[TextBlock(text="hello")]
            )
        )

        llm_msgs = session.get_messages_for_llm()
        assert len(llm_msgs) == 2
        assert llm_msgs[0]["role"] == "user"
        assert llm_msgs[1]["role"] == "assistant"

    def test_maybe_compact_manual(self, store):
        mgr = SessionManager(
            store=store,
            project_name="p",
            project_dir="/tmp",
            compact_preserve_count=2,
        )
        session = mgr.create_session()

        for i in range(5):
            session.add_message(
                TranscriptMessage(
                    role=MessageRole.USER, content=[TextBlock(text=f"msg {i}")]
                )
            )

        result = session.maybe_compact(trigger=CompactTrigger.MANUAL)

        assert result is not None
        assert result.success is True
        assert result.archived_count == 3

        # Verify manifest saved
        manifest = store.load_compact_manifest("p", session.session_id)
        assert len(manifest) > 0

    def test_maybe_compact_auto_skips_below_threshold(self, store):
        mgr = SessionManager(
            store=store,
            project_name="p",
            project_dir="/tmp",
            token_threshold=1000000,  # Very high threshold
        )
        session = mgr.create_session()

        session.add_message(
            TranscriptMessage(role=MessageRole.USER, content=[TextBlock(text="short")])
        )

        result = session.maybe_compact()
        assert result is None

    def test_save_and_reload_metadata(self, store):
        mgr = SessionManager(store=store, project_name="p", project_dir="/tmp")
        session = mgr.create_session(description="test session")

        session.add_message(
            TranscriptMessage(role=MessageRole.USER, content=[TextBlock(text="hi")])
        )
        session.save()

        loaded = store.load_metadata("p", session.session_id)
        assert loaded is not None
        assert loaded.description == "test session"
        assert loaded.message_count == 1


class TestSessionManager:
    def test_create_session(self, manager):
        session = manager.create_session(description="new session")
        assert session.metadata.description == "new session"
        assert session.chain.message_count == 0

    def test_resume_session(self, manager):
        session = manager.create_session()

        session.add_message(
            TranscriptMessage(role=MessageRole.USER, content=[TextBlock(text="hi")])
        )
        session.add_message(
            TranscriptMessage(
                role=MessageRole.ASSISTANT, content=[TextBlock(text="hello")]
            )
        )
        session.save()

        # Resume
        resumed = manager.resume_session(session.session_id)
        assert resumed is not None
        assert resumed.chain.message_count == 2
        assert resumed.metadata.message_count == 2

        llm_msgs = resumed.get_messages_for_llm()
        assert len(llm_msgs) == 2

    def test_resume_nonexistent(self, manager):
        assert manager.resume_session(uuid4()) is None

    def test_resume_latest(self, manager):
        s1 = manager.create_session(description="first")
        s1.add_message(
            TranscriptMessage(role=MessageRole.USER, content=[TextBlock(text="1")])
        )
        s1.save()

        s2 = manager.create_session(description="second")
        s2.add_message(
            TranscriptMessage(role=MessageRole.USER, content=[TextBlock(text="2")])
        )
        s2.save()

        latest = manager.resume_latest()
        assert latest is not None
        # Should be the most recent one
        assert latest.session_id == s2.session_id

    def test_list_sessions(self, manager):
        manager.create_session(description="a")
        manager.create_session(description="b")

        sessions = manager.list_sessions()
        assert len(sessions) == 2

    def test_delete_session(self, manager):
        session = manager.create_session()
        session.add_message(
            TranscriptMessage(role=MessageRole.USER, content=[TextBlock(text="hi")])
        )
        session.save()

        assert manager.delete_session(session.session_id) is True
        assert manager.resume_session(session.session_id) is None

    def test_resume_after_compact(self, manager):
        """Test that resume correctly rebuilds chain after compact."""
        mgr = SessionManager(
            store=manager.store,
            project_name=manager.project_name,
            project_dir="/tmp",
            compact_preserve_count=2,
        )
        session = mgr.create_session()

        for i in range(5):
            session.add_message(
                TranscriptMessage(
                    role=MessageRole.USER, content=[TextBlock(text=f"msg {i}")]
                )
            )
        session.save()

        # Compact
        result = session.maybe_compact(trigger=CompactTrigger.MANUAL)
        assert result.success

        # Resume from scratch
        resumed = mgr.resume_session(session.session_id)
        assert resumed is not None

        # Should have boundary + 2 preserved = 3 messages
        active = resumed.chain.build_active_chain()
        assert len(active) == 3
        assert active[0].is_compact_boundary is True

        # LLM messages should only have the 2 preserved (boundary filtered)
        llm_msgs = resumed.get_messages_for_llm()
        assert len(llm_msgs) == 2
