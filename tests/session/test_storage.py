"""Tests for TranscriptStore."""

from datetime import datetime
from uuid import uuid4

import pytest

from bourbon.session.storage import TranscriptStore
from bourbon.session.types import (
    CompactMetadata,
    CompactTrigger,
    MessageRole,
    SessionMetadata,
    TextBlock,
    TokenUsage,
    ToolResultBlock,
    ToolUseBlock,
    TranscriptMessage,
)


@pytest.fixture
def store(tmp_path):
    return TranscriptStore(base_dir=tmp_path)


@pytest.fixture
def session_id():
    return uuid4()


class TestTranscriptAppendAndLoad:
    def test_append_and_load_single_message(self, store, session_id):
        msg = TranscriptMessage(
            role=MessageRole.USER,
            session_id=session_id,
            content=[TextBlock(text="Hello")],
        )
        store.append_to_transcript("test_project", session_id, [msg])

        loaded = store.load_transcript("test_project", session_id)
        assert len(loaded) == 1
        assert loaded[0].uuid == msg.uuid
        assert loaded[0].role == MessageRole.USER
        assert loaded[0].content[0].text == "Hello"

    def test_append_is_additive(self, store, session_id):
        msg1 = TranscriptMessage(
            role=MessageRole.USER,
            session_id=session_id,
            content=[TextBlock(text="first")],
        )
        msg2 = TranscriptMessage(
            role=MessageRole.ASSISTANT,
            session_id=session_id,
            content=[TextBlock(text="second")],
        )

        store.append_to_transcript("test_project", session_id, [msg1])
        store.append_to_transcript("test_project", session_id, [msg2])

        loaded = store.load_transcript("test_project", session_id)
        assert len(loaded) == 2
        assert loaded[0].uuid == msg1.uuid
        assert loaded[1].uuid == msg2.uuid

    def test_load_nonexistent_returns_empty(self, store):
        loaded = store.load_transcript("nope", uuid4())
        assert loaded == []

    def test_roundtrip_with_tool_blocks(self, store, session_id):
        msg = TranscriptMessage(
            role=MessageRole.ASSISTANT,
            session_id=session_id,
            content=[
                TextBlock(text="Let me check"),
                ToolUseBlock(id="t1", name="read", input={"path": "x.py"}),
            ],
        )
        store.append_to_transcript("p", session_id, [msg])

        loaded = store.load_transcript("p", session_id)
        assert len(loaded[0].content) == 2
        assert isinstance(loaded[0].content[0], TextBlock)
        assert isinstance(loaded[0].content[1], ToolUseBlock)
        assert loaded[0].content[1].name == "read"

    def test_roundtrip_with_tool_result(self, store, session_id):
        msg = TranscriptMessage(
            role=MessageRole.USER,
            session_id=session_id,
            content=[
                ToolResultBlock(tool_use_id="t1", content="file content", is_error=False),
            ],
            source_tool_uuid=uuid4(),
        )
        store.append_to_transcript("p", session_id, [msg])

        loaded = store.load_transcript("p", session_id)
        assert isinstance(loaded[0].content[0], ToolResultBlock)
        assert loaded[0].source_tool_uuid == msg.source_tool_uuid

    def test_roundtrip_with_usage(self, store, session_id):
        msg = TranscriptMessage(
            role=MessageRole.ASSISTANT,
            session_id=session_id,
            content=[TextBlock(text="hi")],
            usage=TokenUsage(input_tokens=100, output_tokens=50, total_tokens=150),
        )
        store.append_to_transcript("p", session_id, [msg])

        loaded = store.load_transcript("p", session_id)
        assert loaded[0].usage is not None
        assert loaded[0].usage.input_tokens == 100

    def test_roundtrip_with_compact_metadata(self, store, session_id):
        first_uuid = uuid4()
        last_uuid = uuid4()
        msg = TranscriptMessage(
            role=MessageRole.SYSTEM,
            session_id=session_id,
            content=[TextBlock(text="[Compressed]")],
            is_compact_boundary=True,
            compact_metadata=CompactMetadata(
                trigger=CompactTrigger.AUTO_THRESHOLD,
                pre_compact_token_count=10,
                post_compact_token_count=3,
                first_archived_uuid=first_uuid,
                last_archived_uuid=last_uuid,
                summary="test compact",
            ),
        )
        store.append_to_transcript("p", session_id, [msg])

        loaded = store.load_transcript("p", session_id)
        assert loaded[0].is_compact_boundary is True
        assert loaded[0].compact_metadata is not None
        assert loaded[0].compact_metadata.trigger == CompactTrigger.AUTO_THRESHOLD
        assert loaded[0].compact_metadata.first_archived_uuid == first_uuid

    def test_roundtrip_preserves_parent_uuids(self, store, session_id):
        parent_uuid = uuid4()
        logical_parent = uuid4()
        msg = TranscriptMessage(
            role=MessageRole.USER,
            session_id=session_id,
            content=[TextBlock(text="hi")],
            parent_uuid=parent_uuid,
            logical_parent_uuid=logical_parent,
        )
        store.append_to_transcript("p", session_id, [msg])

        loaded = store.load_transcript("p", session_id)
        assert loaded[0].parent_uuid == parent_uuid
        assert loaded[0].logical_parent_uuid == logical_parent


class TestMetadata:
    def test_save_and_load_metadata(self, store, session_id):
        now = datetime.now()
        meta = SessionMetadata(
            uuid=session_id,
            parent_uuid=None,
            project_dir="/tmp/test",
            created_at=now,
            last_activity=now,
            message_count=5,
            total_tokens_used=1000,
            description="test session",
        )
        store.save_metadata("p", session_id, meta)

        loaded = store.load_metadata("p", session_id)
        assert loaded is not None
        assert loaded.uuid == session_id
        assert loaded.message_count == 5
        assert loaded.description == "test session"

    def test_load_nonexistent_metadata(self, store):
        assert store.load_metadata("p", uuid4()) is None


class TestCompactManifest:
    def test_save_and_load_manifest(self, store, session_id):
        overrides = {
            str(uuid4()): None,
            str(uuid4()): str(uuid4()),
        }
        store.save_compact_manifest("p", session_id, overrides)

        loaded = store.load_compact_manifest("p", session_id)
        assert loaded == overrides

    def test_load_nonexistent_manifest(self, store):
        assert store.load_compact_manifest("p", uuid4()) == {}

    def test_manifest_overwrites_previous(self, store, session_id):
        overrides1 = {str(uuid4()): None}
        overrides2 = {str(uuid4()): str(uuid4())}

        store.save_compact_manifest("p", session_id, overrides1)
        store.save_compact_manifest("p", session_id, overrides2)

        loaded = store.load_compact_manifest("p", session_id)
        assert loaded == overrides2


class TestSessionListing:
    def test_list_sessions(self, store):
        sid1, sid2 = uuid4(), uuid4()
        now = datetime.now()

        for sid in [sid1, sid2]:
            store.save_metadata(
                "p",
                sid,
                SessionMetadata(
                    uuid=sid,
                    parent_uuid=None,
                    project_dir="/tmp",
                    created_at=now,
                    last_activity=now,
                    message_count=1,
                    description=f"session {sid}",
                ),
            )

        sessions = store.list_sessions("p")
        assert len(sessions) == 2

    def test_list_nonexistent_project(self, store):
        assert store.list_sessions("nonexistent") == []

    def test_delete_session(self, store, session_id):
        msg = TranscriptMessage(
            role=MessageRole.USER,
            session_id=session_id,
            content=[TextBlock(text="hi")],
        )
        store.append_to_transcript("p", session_id, [msg])
        store.save_metadata(
            "p",
            session_id,
            SessionMetadata(
                uuid=session_id,
                parent_uuid=None,
                project_dir="/tmp",
                created_at=datetime.now(),
                last_activity=datetime.now(),
            ),
        )
        store.save_compact_manifest("p", session_id, {str(uuid4()): None})

        assert store.delete_session("p", session_id) is True
        assert store.load_transcript("p", session_id) == []
        assert store.load_metadata("p", session_id) is None
        assert store.load_compact_manifest("p", session_id) == {}
