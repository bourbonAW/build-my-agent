"""Tests for bourbon.memory.store — sanitize_project_key, file CRUD, index, search."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
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
from bourbon.memory.store import MemoryStore, _record_to_filename, sanitize_project_key


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

    # File should exist with expected name (kind_slug_id8.md)
    expected_file = tmp_path / _record_to_filename(record)
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


def test_store_persists_cue_metadata_frontmatter(tmp_path: Path) -> None:
    from bourbon.memory.cues.models import (
        CueGenerationStatus,
        CueKind,
        CueSource,
        MemoryConcept,
        MemoryCueMetadata,
        RetrievalCue,
    )

    store = MemoryStore(memory_dir=tmp_path)
    metadata = MemoryCueMetadata(
        schema_version="cue.v1",
        generator_version="record-cue-v1",
        concepts=[MemoryConcept.ARCHITECTURE_DECISION],
        retrieval_cues=[
            RetrievalCue(
                text="why cue metadata",
                kind=CueKind.DECISION_QUESTION,
                source=CueSource.LLM,
                confidence=0.8,
            ),
            RetrievalCue(
                text="src/bourbon/memory/store.py",
                kind=CueKind.FILE_OR_SYMBOL,
                source=CueSource.RUNTIME,
                confidence=1.0,
            ),
        ],
        files=["src/bourbon/memory/store.py"],
        symbols=[],
        generation_status=CueGenerationStatus.GENERATED,
    )
    record = _make_record(
        id="mem_cue00001",
        name="Cue metadata",
        content="Store cue metadata in frontmatter.",
    )
    record.cue_metadata = metadata

    store.write_record(record)
    raw_text = (tmp_path / _record_to_filename(record)).read_text(encoding="utf-8")
    loaded = store.read_record(record.id)

    assert "cue_metadata:" in raw_text
    assert "why cue metadata" in raw_text
    assert loaded is not None
    assert loaded.cue_metadata == metadata


def test_store_round_trips_cue_text_containing_yaml_delimiter(tmp_path: Path) -> None:
    from bourbon.memory.cues.models import (
        CueGenerationStatus,
        CueKind,
        CueSource,
        MemoryConcept,
        MemoryCueMetadata,
        RetrievalCue,
    )

    store = MemoryStore(memory_dir=tmp_path)
    metadata = MemoryCueMetadata(
        schema_version="cue.v1",
        generator_version="record-cue-v1",
        concepts=[MemoryConcept.PROJECT_CONTEXT],
        retrieval_cues=[
            RetrievalCue(
                text="why --- metadata marker",
                kind=CueKind.USER_PHRASE,
                source=CueSource.USER,
                confidence=1.0,
            )
        ],
        files=[],
        symbols=[],
        generation_status=CueGenerationStatus.GENERATED,
    )
    record = _make_record(id="mem_delim001", name="Delimiter cue")
    record.cue_metadata = metadata

    store.write_record(record)
    loaded = store.read_record(record.id)

    assert loaded is not None
    assert loaded.cue_metadata == metadata


def test_store_reads_old_record_without_cue_metadata(tmp_path: Path) -> None:
    store = MemoryStore(memory_dir=tmp_path)
    record = _make_record(id="mem_old00001", name="Old record")

    store.write_record(record)
    loaded = store.read_record(record.id)

    assert loaded is not None
    assert loaded.cue_metadata is None


def test_update_cue_metadata_rewrites_existing_record_without_changing_status(
    tmp_path: Path,
) -> None:
    from bourbon.memory.cues.models import (
        CueGenerationStatus,
        CueKind,
        CueSource,
        MemoryConcept,
        MemoryCueMetadata,
        RetrievalCue,
    )

    original_store = MemoryStore(memory_dir=tmp_path)
    record = _make_record(
        id="mem_cueupdate",
        name="Cue update",
        status=MemStatus.STALE,
        content="Keep this content unchanged.",
    )
    original_path = original_store.write_record(record)
    custom_path = tmp_path / "custom_existing_memory_file.md"
    original_path.rename(custom_path)

    metadata = MemoryCueMetadata(
        schema_version="cue.v1",
        generator_version="record-cue-v1",
        concepts=[MemoryConcept.PROJECT_CONTEXT],
        retrieval_cues=[
            RetrievalCue(
                text="how cue updates work",
                kind=CueKind.DECISION_QUESTION,
                source=CueSource.BACKFILL,
                confidence=0.9,
            )
        ],
        files=["src/bourbon/memory/store.py"],
        symbols=["MemoryStore.update_cue_metadata"],
        generation_status=CueGenerationStatus.GENERATED,
    )
    store = MemoryStore(memory_dir=tmp_path)

    updated = store.update_cue_metadata(record.id, metadata)

    assert updated.id == record.id
    assert updated.status == record.status
    assert updated.content == record.content
    assert updated.created_at == record.created_at
    assert updated.updated_at > record.updated_at
    assert updated.cue_metadata == metadata
    assert custom_path.exists()
    assert not original_path.exists()

    loaded = store.read_record(record.id)
    assert loaded is not None
    assert loaded.cue_metadata == metadata
    assert loaded.status == MemStatus.STALE


def test_store_ignores_malformed_cue_metadata_without_losing_record(tmp_path: Path) -> None:
    store = MemoryStore(memory_dir=tmp_path)
    record = _make_record(id="mem_badcue1", name="Bad cue")
    store.write_record(record)
    path = tmp_path / _record_to_filename(record)
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        "created_by: user\n",
        "created_by: user\ncue_metadata:\n  schema_version: cue.v1\n"
        "  retrieval_cues: not-a-list\n",
    )
    path.write_text(text, encoding="utf-8")

    loaded = store.read_record(record.id)

    assert loaded is not None
    assert loaded.id == "mem_badcue1"
    assert loaded.cue_metadata is None


def test_store_ignores_malformed_nested_cue_metadata_without_losing_record(
    tmp_path: Path,
) -> None:
    store = MemoryStore(memory_dir=tmp_path)
    record = _make_record(id="mem_badcue2", name="Bad nested cue")
    store.write_record(record)
    path = tmp_path / _record_to_filename(record)
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        "created_by: user\n",
        "created_by: user\ncue_metadata:\n  schema_version: cue.v1\n"
        "  generator_version: record-cue-v1\n"
        "  generation_status: generated\n"
        "  concepts:\n"
        "    - project_context\n"
        "  domain_concepts: not-a-list\n"
        "  retrieval_cues:\n"
        "    - text: valid cue\n"
        "      kind: user_phrase\n"
        "      source: user\n"
        "      confidence: 1.0\n",
    )
    path.write_text(text, encoding="utf-8")

    loaded = store.read_record(record.id)
    listed = store.list_records()

    assert loaded is not None
    assert loaded.id == "mem_badcue2"
    assert loaded.cue_metadata is None
    assert [item.id for item in listed] == ["mem_badcue2"]


def test_store_ignores_invalid_domain_concept_source_without_losing_record(
    tmp_path: Path,
) -> None:
    store = MemoryStore(memory_dir=tmp_path)
    record = _make_record(id="mem_badcue3", name="Invalid domain source")
    store.write_record(record)
    path = tmp_path / _record_to_filename(record)
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        "created_by: user\n",
        "created_by: user\ncue_metadata:\n"
        "  schema_version: cue.v1\n"
        "  generator_version: record-cue-v1\n"
        "  generation_status: generated\n"
        "  concepts:\n"
        "    - project_context\n"
        "  domain_concepts:\n"
        "    - namespace: investment\n"
        "      value: risk_model\n"
        "      source: not-valid\n"
        "      schema_version: cue.v1\n"
        "  retrieval_cues:\n"
        "    - text: valid cue\n"
        "      kind: user_phrase\n"
        "      source: user\n"
        "      confidence: 1.0\n",
    )
    path.write_text(text, encoding="utf-8")

    loaded = store.read_record(record.id)

    assert loaded is not None
    assert loaded.cue_metadata is None


def test_store_ignores_malformed_yaml_frontmatter(tmp_path: Path) -> None:
    path = tmp_path / "project_bad_mem_bad00001.md"
    path.write_text("---\nid: [unterminated\n---\n\nBody remains readable.\n", encoding="utf-8")
    store = MemoryStore(memory_dir=tmp_path)

    assert store.list_records() == []
    assert store.search("Body remains readable") == []


def test_read_record_returns_none_for_known_file_with_malformed_yaml(tmp_path: Path) -> None:
    store = MemoryStore(memory_dir=tmp_path)
    record = _make_record(id="mem_malformed", name="Malformed yaml")
    store.write_record(record)
    path = tmp_path / _record_to_filename(record)
    path.write_text("---\nid: [unterminated\n---\n\nBody remains readable.\n", encoding="utf-8")

    assert store.read_record(record.id) is None


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
    assert _record_to_filename(record) in text


def test_update_index_deduplicates(tmp_path: Path) -> None:
    store = MemoryStore(memory_dir=tmp_path)
    record = _make_record(id="mem_dedup001", name="Dedup entry", description="Should not duplicate")
    store.write_record(record)
    store.update_index(record)
    store.update_index(record)  # second call

    text = (tmp_path / "MEMORY.md").read_text()
    # The filename reference should appear exactly once
    assert text.count(_record_to_filename(record)) == 1


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


def test_update_status_rewrites_frontmatter_and_returns_updated_record(tmp_path: Path) -> None:
    store = MemoryStore(memory_dir=tmp_path)
    active = _make_record(id="mem_keep0001", name="Keep active")
    record = _make_record(id="mem_prom0001", name="Promote me")
    stale = _make_record(id="mem_stal0001", name="Stale item", status=MemStatus.STALE)
    rejected = _make_record(id="mem_rej0001", name="Rejected item", status=MemStatus.REJECTED)

    for item in (active, record, stale, rejected):
        store.write_record(item)
        store.update_index(item)

    updated = store.update_status("mem_prom0001", MemStatus.PROMOTED)

    assert updated.status == MemStatus.PROMOTED
    assert updated.updated_at >= record.updated_at
    index_text = (tmp_path / "MEMORY.md").read_text()
    assert "Keep active" in index_text
    assert "Promote me" not in index_text
    assert "Stale item" not in index_text
    assert "Rejected item" not in index_text
    assert "status: promoted" in (tmp_path / _record_to_filename(updated)).read_text()


def test_rebuild_index_orders_by_updated_at_desc_and_truncates_to_200(tmp_path: Path) -> None:
    store = MemoryStore(memory_dir=tmp_path)
    base_time = datetime(2026, 4, 20, 12, 0, 0, tzinfo=UTC)

    for i in range(205):
        record = _make_record(
            id=f"mem_ord{i:05d}",
            name=f"Ordered {i}",
            description=f"Ordered entry {i}",
        )
        record = replace(record, updated_at=base_time + timedelta(seconds=i))
        store.write_record(record)

    rebuilt = store._rebuild_index()

    assert rebuilt is True
    lines = (tmp_path / "MEMORY.md").read_text().strip().splitlines()
    assert len(lines) == 200
    assert lines[0].startswith("- [Ordered 204]")
    assert lines[-1].startswith("- [Ordered 5]")


def test_rebuild_index_excludes_promoted_stale_and_rejected(tmp_path: Path) -> None:
    store = MemoryStore(memory_dir=tmp_path)
    active = _make_record(id="mem_act0001", name="Active only")
    promoted = _make_record(id="mem_prm0001", name="Promoted", status=MemStatus.PROMOTED)
    stale = _make_record(id="mem_stl0001", name="Stale", status=MemStatus.STALE)
    rejected = _make_record(id="mem_rej0001", name="Rejected", status=MemStatus.REJECTED)

    for record in (active, promoted, stale, rejected):
        store.write_record(record)

    rebuilt = store._rebuild_index()

    assert rebuilt is False
    text = (tmp_path / "MEMORY.md").read_text()
    assert "Active only" in text
    assert "Promoted" not in text
    assert "Stale" not in text
    assert "Rejected" not in text


# --- Task 6: Grep-Based Search ---


def test_grep_search_finds_matching_content(tmp_path: Path) -> None:
    store = MemoryStore(memory_dir=tmp_path)
    record = _make_record(
        id="mem_srch0001",
        name="WAL mode rule",
        description="Use WAL for SQLite",
        content="Always use WAL mode for SQLite stores to allow concurrent reads.",
    )
    store.write_record(record)

    results = store.search("WAL mode")
    assert len(results) >= 1
    assert results[0].id == "mem_srch0001"
    assert "WAL" in results[0].snippet


def test_grep_search_filters_by_kind(tmp_path: Path) -> None:
    store = MemoryStore(memory_dir=tmp_path)
    for i, kind in enumerate([MemoryKind.PROJECT, MemoryKind.USER]):
        store.write_record(
            _make_record(
                id=f"mem_kind000{i}",
                name=f"Kind test {i}",
                description=f"Test {kind}",
                kind=kind,
                content="Searchable content here.",
            )
        )

    results = store.search("Searchable", kind=["project"])
    assert len(results) == 1
    assert results[0].kind == MemoryKind.PROJECT


def test_grep_search_matches_multi_word_queries_by_token(tmp_path: Path) -> None:
    store = MemoryStore(memory_dir=tmp_path)
    store.write_record(
        _make_record(
            id="mem_terms0001",
            name="DB mocking rule",
            description="Avoid DB mocks",
            content="Never mock the database in integration tests.",
        )
    )

    results = store.search("mock database")
    assert len(results) == 1
    assert results[0].id == "mem_terms0001"


def test_grep_search_empty_dir_returns_empty(tmp_path: Path) -> None:
    store = MemoryStore(memory_dir=tmp_path / "nonexistent")
    results = store.search("anything")
    assert results == []


def test_grep_search_respects_status_filter(tmp_path: Path) -> None:
    store = MemoryStore(memory_dir=tmp_path)
    store.write_record(
        _make_record(
            id="mem_stat0001",
            name="Rejected item",
            description="Was rejected",
            status=MemStatus.REJECTED,
            content="Rejected searchable content.",
        )
    )

    # Default: only active
    results = store.search("Rejected searchable", status=["active"])
    assert len(results) == 0

    # Explicit rejected
    results = store.search("Rejected searchable", status=["rejected"])
    assert len(results) == 1


def test_grep_search_no_matches(tmp_path: Path) -> None:
    store = MemoryStore(memory_dir=tmp_path)
    store.write_record(_make_record(id="mem_nomatch", name="No match", content="Something else."))
    results = store.search("xyznonexistent")
    assert results == []


def test_python_grep_fallback(tmp_path: Path) -> None:
    """Test the Python fallback grep directly."""
    store = MemoryStore(memory_dir=tmp_path)
    store.write_record(
        _make_record(
            id="mem_pygr0001",
            name="Python grep test",
            description="Fallback test",
            content="Fallback grep content here.",
        )
    )

    # Call _python_grep directly
    matches = store._python_grep("Fallback grep")
    assert len(matches) == 1
    assert any("Fallback grep" in line for line in matches[0][1])


def test_two_records_same_name_and_kind_do_not_collide(tmp_path: Path) -> None:
    """Two records with identical kind+name must not overwrite each other."""
    store = MemoryStore(memory_dir=tmp_path)
    record1 = _make_record(id="mem_aaa11111", name="WAL rule", kind=MemoryKind.PROJECT)
    record2 = _make_record(id="mem_bbb22222", name="WAL rule", kind=MemoryKind.PROJECT)
    store.write_record(record1)
    store.write_record(record2)
    retrieved1 = store.read_record("mem_aaa11111")
    retrieved2 = store.read_record("mem_bbb22222")
    assert retrieved1 is not None, "first record was lost"
    assert retrieved2 is not None, "second record was lost"
    assert retrieved1.id == "mem_aaa11111", "first record was silently overwritten by second"
    assert retrieved2.id == "mem_bbb22222", "second record id mismatch"
