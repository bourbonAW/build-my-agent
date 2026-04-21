"""Tests for bourbon.memory.models."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from bourbon.memory.models import (
    MemoryActor,
    MemoryKind,
    MemoryRecord,
    MemoryRecordDraft,
    MemoryScope,
    MemorySearchResult,
    MemorySource,
    MemoryStatusInfo,
    RecentWriteSummary,
    SourceRef,
    actor_to_created_by,
)
from bourbon.memory.models import (
    MemoryStatus as MemStatus,
)

# --- Enums ---


def test_memory_kind_values():
    assert {e.value for e in MemoryKind} == {"user", "feedback", "project", "reference"}


def test_memory_scope_values():
    assert {e.value for e in MemoryScope} == {"user", "project", "session"}


def test_memory_source_values():
    assert {e.value for e in MemorySource} == {
        "user",
        "agent",
        "subagent",
        "compaction",
        "manual",
    }


def test_memory_status_values():
    assert {e.value for e in MemStatus} == {"active", "stale", "rejected"}


# --- MemoryActor ---


def test_actor_user():
    actor = MemoryActor(kind="user")
    assert actor_to_created_by(actor) == "user"


def test_actor_agent():
    actor = MemoryActor(kind="agent", session_id="ses_abc123")
    assert actor_to_created_by(actor) == "agent:ses_abc123"


def test_actor_subagent():
    actor = MemoryActor(kind="subagent", run_id="run_xyz", agent_type="explore")
    assert actor_to_created_by(actor) == "subagent:run_xyz"


def test_actor_system():
    actor = MemoryActor(kind="system")
    assert actor_to_created_by(actor) == "system:system"


# --- SourceRef ---


def test_source_ref_transcript_valid():
    ref = SourceRef(
        kind="transcript", project_name="proj", session_id="ses_1", message_uuid="msg_1"
    )
    assert ref.kind == "transcript"


def test_source_ref_transcript_missing_session():
    with pytest.raises(ValueError, match="session_id"):
        SourceRef(kind="transcript", project_name="proj", message_uuid="msg_1")


def test_source_ref_file_valid():
    ref = SourceRef(kind="file", file_path="/path/to/file.md")
    assert ref.file_path == "/path/to/file.md"


def test_source_ref_file_missing_path():
    with pytest.raises(ValueError, match="file_path"):
        SourceRef(kind="file")


def test_source_ref_range_requires_both_start_end():
    with pytest.raises(ValueError, match="start_message_uuid.*end_message_uuid"):
        SourceRef(
            kind="transcript_range",
            project_name="proj",
            session_id="ses_1",
            start_message_uuid="msg_1",
        )


def test_source_ref_range_valid():
    ref = SourceRef(
        kind="transcript_range",
        project_name="proj",
        session_id="ses_1",
        start_message_uuid="msg_1",
        end_message_uuid="msg_5",
    )
    assert ref.start_message_uuid == "msg_1"


def test_source_ref_message_uuid_and_range_mutually_exclusive():
    with pytest.raises(ValueError, match="mutually exclusive"):
        SourceRef(
            kind="transcript",
            project_name="proj",
            session_id="ses_1",
            message_uuid="msg_1",
            start_message_uuid="msg_2",
            end_message_uuid="msg_3",
        )


# --- MemoryRecordDraft ---


def test_memory_record_draft_minimal():
    draft = MemoryRecordDraft(
        kind=MemoryKind.PROJECT,
        scope=MemoryScope.PROJECT,
        content="Always use WAL mode.",
        source=MemorySource.USER,
        confidence=1.0,
    )
    assert draft.kind == "project"
    assert draft.name is None  # auto-derived later


# --- MemoryRecord ---


def test_memory_record_has_all_fields():
    ref = SourceRef(kind="manual")
    record = MemoryRecord(
        id="mem_abc12345",
        name="WAL mode rule",
        description="Always use WAL mode for SQLite",
        kind=MemoryKind.PROJECT,
        scope=MemoryScope.PROJECT,
        confidence=1.0,
        source=MemorySource.USER,
        status=MemStatus.ACTIVE,
        created_at=datetime(2026, 4, 20, tzinfo=UTC),
        updated_at=datetime(2026, 4, 20, tzinfo=UTC),
        created_by="user",
        content="Always use WAL mode for SQLite stores.",
        source_ref=ref,
    )
    assert record.id.startswith("mem_")
    assert record.status == "active"


# --- MemorySearchResult ---


def test_memory_search_result():
    result = MemorySearchResult(
        id="mem_abc12345",
        name="test",
        kind=MemoryKind.PROJECT,
        scope=MemoryScope.PROJECT,
        snippet="Always use WAL",
        confidence=1.0,
        status=MemStatus.ACTIVE,
        source_ref=SourceRef(kind="manual"),
        why_matched="keyword: WAL",
    )
    assert result.snippet == "Always use WAL"


# --- MemoryStatusInfo ---


def test_memory_status_info():
    info = MemoryStatusInfo(
        readable_scopes=["project", "session"],
        writable_scopes=["project"],
        prompt_anchor_tokens=800,
        recent_writes=[],
        index_at_capacity=False,
        memory_file_count=5,
    )
    assert info.memory_file_count == 5


def test_recent_write_summary():
    rws = RecentWriteSummary(
        id="mem_xyz",
        name="Test",
        kind=MemoryKind.USER,
        created_at=datetime(2026, 4, 20, tzinfo=UTC),
    )
    assert rws.id == "mem_xyz"
