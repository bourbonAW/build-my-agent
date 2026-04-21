"""Tests for bourbon.memory.store — sanitize_project_key, file CRUD, index, search."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from bourbon.memory.models import (
    MemoryKind,
    MemoryRecord,
    MemoryScope,
    MemorySource,
    SourceRef,
)
from bourbon.memory.models import (
    MemoryStatus as MemStatus,
)
from bourbon.memory.store import MemoryStore, sanitize_project_key


def test_sanitize_simple_path():
    key = sanitize_project_key(Path("/home/user/projects/bourbon"))
    # Should be slug + 8-char hash suffix
    assert key.startswith("home-user-projects-bourbon-")
    assert len(key.split("-")[-1]) == 8  # sha256 hex prefix


def test_sanitize_truncates_long_slug():
    long_path = Path("/" + "a" * 200)
    key = sanitize_project_key(long_path)
    # slug (before hash) should be <= 64 chars, total = slug + "-" + 8
    slug_part = key.rsplit("-", 1)[0]
    assert len(slug_part) <= 64


def test_sanitize_removes_non_ascii():
    key = sanitize_project_key(Path("/home/用户/project"))
    assert "用" not in key
    assert "户" not in key


def test_sanitize_same_path_same_key():
    p = Path("/home/user/myrepo")
    assert sanitize_project_key(p) == sanitize_project_key(p)


def test_sanitize_different_paths_different_keys():
    k1 = sanitize_project_key(Path("/home/user/repo1"))
    k2 = sanitize_project_key(Path("/home/user/repo2"))
    assert k1 != k2


# --- Task 4: File CRUD ---


def _make_record(
    *,
    id: str = "mem_test1234",
    name: str = "Test rule",
    description: str = "A test memory record",
    kind: MemoryKind = MemoryKind.PROJECT,
    scope: MemoryScope = MemoryScope.PROJECT,
    confidence: float = 1.0,
    source: MemorySource = MemorySource.USER,
    status: MemStatus = MemStatus.ACTIVE,
    content: str = "Always use WAL mode.",
    source_ref: SourceRef | None = None,
) -> MemoryRecord:
    if source_ref is None:
        source_ref = SourceRef(kind="manual")
    return MemoryRecord(
        id=id,
        name=name,
        description=description,
        kind=kind,
        scope=scope,
        confidence=confidence,
        source=source,
        status=status,
        created_at=datetime(2026, 4, 20, tzinfo=UTC),
        updated_at=datetime(2026, 4, 20, tzinfo=UTC),
        created_by="user",
        content=content,
        source_ref=source_ref,
    )


def test_write_and_read_memory_file(tmp_path: Path) -> None:
    store = MemoryStore(memory_dir=tmp_path)
    record = _make_record()
    store.write_record(record)

    # File should exist with expected name
    expected_file = tmp_path / "project_test-rule.md"
    assert expected_file.exists()

    # Read it back
    loaded = store.read_record("mem_test1234")
    assert loaded is not None
    assert loaded.id == "mem_test1234"
    assert loaded.content == "Always use WAL mode."
    assert loaded.kind == MemoryKind.PROJECT


def test_write_atomic_does_not_corrupt_on_existing(tmp_path: Path) -> None:
    store = MemoryStore(memory_dir=tmp_path)
    record = _make_record(id="mem_dup00001", name="Dup test", content="Original content.")
    store.write_record(record)

    # Update content
    record2 = _make_record(
        id="mem_dup00001",
        name="Dup test",
        description="Duplicate updated",
        confidence=0.9,
        content="Updated content.",
    )
    store.write_record(record2)
    loaded = store.read_record("mem_dup00001")
    assert loaded is not None
    assert loaded.content == "Updated content."


def test_read_nonexistent_returns_none(tmp_path: Path) -> None:
    store = MemoryStore(memory_dir=tmp_path)
    assert store.read_record("mem_notexist") is None


def test_list_records_all(tmp_path: Path) -> None:
    store = MemoryStore(memory_dir=tmp_path)
    store.write_record(_make_record(id="mem_a", name="Rec A"))
    store.write_record(_make_record(id="mem_b", name="Rec B"))
    records = store.list_records()
    assert len(records) == 2


def test_list_records_status_filter(tmp_path: Path) -> None:
    store = MemoryStore(memory_dir=tmp_path)
    store.write_record(_make_record(id="mem_act", name="Active", status=MemStatus.ACTIVE))
    store.write_record(_make_record(id="mem_stl", name="Stale", status=MemStatus.STALE))
    active = store.list_records(status=["active"])
    assert len(active) == 1
    assert active[0].id == "mem_act"


def test_list_records_empty_dir(tmp_path: Path) -> None:
    store = MemoryStore(memory_dir=tmp_path / "nonexistent")
    assert store.list_records() == []


# --- Task 5: MEMORY.md Index Maintenance ---


def test_update_index_adds_entry(tmp_path: Path) -> None:
    store = MemoryStore(memory_dir=tmp_path)
    record = _make_record(id="mem_idx00001", name="Index test", description="Testing index update")
    store.write_record(record)
    store.update_index(record)

    index_path = tmp_path / "MEMORY.md"
    assert index_path.exists()
    text = index_path.read_text()
    assert "Index test" in text
    assert "project_index-test.md" in text


def test_update_index_deduplicates(tmp_path: Path) -> None:
    store = MemoryStore(memory_dir=tmp_path)
    record = _make_record(id="mem_dedup001", name="Dedup entry", description="Should not duplicate")
    store.write_record(record)
    store.update_index(record)
    store.update_index(record)  # second call

    text = (tmp_path / "MEMORY.md").read_text()
    # The filename reference should appear exactly once
    assert text.count("project_dedup-entry.md") == 1


def test_update_index_capacity_200_lines(tmp_path: Path) -> None:
    store = MemoryStore(memory_dir=tmp_path)
    # Write 200 records to fill index
    for i in range(200):
        record = _make_record(
            id=f"mem_cap{i:05d}",
            name=f"Cap entry {i}",
            description=f"Entry number {i}",
            content=f"Content {i}.",
        )
        store.write_record(record)
        store.update_index(record)

    # 201st should return at_capacity=True
    extra = _make_record(
        id="mem_cap00200",
        name="Over capacity",
        description="Should not be indexed",
        content="Over cap.",
    )
    store.write_record(extra)
    at_capacity = store.update_index(extra)
    assert at_capacity is True

    lines = (tmp_path / "MEMORY.md").read_text().strip().split("\n")
    assert len(lines) <= 200
