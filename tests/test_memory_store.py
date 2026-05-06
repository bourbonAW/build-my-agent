"""Tests for minimal memory store."""

from __future__ import annotations

from datetime import UTC, datetime

from bourbon.memory.models import MemoryRecord
from bourbon.memory.store import MemoryStore, _record_preview, _record_to_filename


def _record(
    memory_id: str = "mem_abc12345",
    *,
    target: str = "project",
    content: str = "Prefer append-only memory records.",
    cues: tuple[str, ...] = ("append-only",),
) -> MemoryRecord:
    return MemoryRecord(
        id=memory_id,
        target=target,  # type: ignore[arg-type]
        content=content,
        created_at=datetime(2026, 5, 6, 8, 0, tzinfo=UTC),
        cues=cues,
    )


def test_record_filename_is_id_only() -> None:
    assert _record_to_filename(_record()) == "mem_abc12345.md"


def test_record_preview_uses_first_line() -> None:
    assert _record_preview(_record(content="First line.\nSecond line.")) == "First line."


def test_store_round_trips_minimal_frontmatter(tmp_path) -> None:
    store = MemoryStore(tmp_path)
    record = _record(target="user", content="User prefers dark mode.", cues=("dark mode",))

    path = store.write_record(record)
    loaded = store.read_record(record.id)

    assert path.name == "mem_abc12345.md"
    assert loaded == record
    raw = path.read_text(encoding="utf-8")
    assert "target: user" in raw
    assert "created_at:" in raw
    assert "cues:" in raw
    assert "kind:" not in raw
    assert "scope:" not in raw
    assert "status:" not in raw
    assert "created_by:" not in raw
    assert "cue_" + "metadata:" not in raw


def test_store_rebuilds_index_after_write_and_delete(tmp_path) -> None:
    store = MemoryStore(tmp_path)
    first = _record("mem_first111", target="user", content="User prefers dark mode.")
    second = _record("mem_second22", target="project", content="Prefer append-only memory records.")

    store.write_record(first)
    store.write_record(second)

    index = (tmp_path / "MEMORY.md").read_text(encoding="utf-8")
    assert "- [user] User prefers dark mode." in index
    assert "- [project] Prefer append-only memory records." in index

    store.delete_record(first.id)

    index = (tmp_path / "MEMORY.md").read_text(encoding="utf-8")
    assert "User prefers dark mode." not in index
    assert "Prefer append-only memory records." in index


def test_search_matches_content_and_cues_with_target_filter(tmp_path) -> None:
    store = MemoryStore(tmp_path)
    store.write_record(_record("mem_user1111", target="user", content="User likes compact output."))
    store.write_record(
        _record(
            "mem_project1",
            target="project",
            content="Theme settings live in the UI package.",
            cues=("dark mode",),
        )
    )

    cue_results = store.search("dark mode")
    target_results = store.search("compact", target="project")

    assert [result.id for result in cue_results] == ["mem_project1"]
    assert cue_results[0].why_matched == "matched cue: dark mode"
    assert target_results == []
