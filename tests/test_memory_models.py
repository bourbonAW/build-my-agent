"""Tests for minimal Bourbon memory models."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from bourbon.memory.models import (
    MEMORY_TARGETS,
    MemoryActor,
    MemoryRecord,
    MemoryRecordDraft,
    MemorySearchResult,
    MemorySystemInfo,
    RecentWriteSummary,
    validate_memory_target,
)


def test_memory_targets_are_user_and_project_only() -> None:
    assert MEMORY_TARGETS == ("user", "project")
    assert validate_memory_target("user") == "user"
    assert validate_memory_target("project") == "project"
    with pytest.raises(ValueError, match="Invalid memory target"):
        validate_memory_target("session")


def test_memory_actor_identifies_runtime_writer() -> None:
    actor = MemoryActor(
        kind="subagent",
        session_id="ses_1",
        run_id="run_1",
        agent_type="explorer",
    )

    assert actor.kind == "subagent"
    assert actor.session_id == "ses_1"
    assert actor.run_id == "run_1"
    assert actor.agent_type == "explorer"


def test_memory_record_draft_only_requires_target_and_content() -> None:
    draft = MemoryRecordDraft(target="project", content="Prefer append-only memory records.")

    assert draft.target == "project"
    assert draft.content == "Prefer append-only memory records."


def test_memory_record_has_minimal_fields() -> None:
    created_at = datetime(2026, 5, 6, 8, 30, tzinfo=UTC)
    record = MemoryRecord(
        id="mem_abc12345",
        target="user",
        content="User prefers dark mode for UI components.",
        created_at=created_at,
        cues=("dark mode", "ui preference"),
    )

    assert record.__dict__ == {
        "id": "mem_abc12345",
        "target": "user",
        "content": "User prefers dark mode for UI components.",
        "created_at": created_at,
        "cues": ("dark mode", "ui preference"),
    }


def test_memory_search_result_is_target_based() -> None:
    result = MemorySearchResult(
        id="mem_abc12345",
        target="project",
        snippet="Prefer append-only memory records.",
        why_matched="matched content: append-only",
    )

    assert result.target == "project"
    assert result.why_matched == "matched content: append-only"


def test_memory_system_info_uses_targets_not_status() -> None:
    info = MemorySystemInfo(
        readable_targets=("user", "project"),
        writable_targets=("project",),
        recent_writes=(
            RecentWriteSummary(
                id="mem_abc12345",
                target="project",
                preview="Prefer append-only memory records.",
                created_at=datetime(2026, 5, 6, tzinfo=UTC),
            ),
        ),
        index_at_capacity=False,
        memory_file_count=1,
    )

    assert info.readable_targets == ("user", "project")
    assert info.writable_targets == ("project",)
    assert info.recent_writes[0].preview == "Prefer append-only memory records."
