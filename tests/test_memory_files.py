import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

from bourbon.memory.files import (
    merge_user_md,
    read_file_anchor,
    render_merged_user_md_for_prompt,
    update_managed_block_status,
    upsert_managed_block,
)
from bourbon.memory.models import MemoryKind, MemoryScope
from bourbon.memory.models import MemoryStatus as MemStatus
from tests.test_memory_store import _make_record


def test_merge_user_md_project_local_wins(tmp_path: Path) -> None:
    global_file = tmp_path / "global" / "USER.md"
    global_file.parent.mkdir()
    global_file.write_text("## Code Style\n\nUse tabs.\n\n## Language\n\nEnglish.\n")

    project_file = tmp_path / "project" / "USER.md"
    project_file.parent.mkdir()
    project_file.write_text("## Code Style\n\nUse spaces.\n")

    merged = merge_user_md(global_path=global_file, project_path=project_file)
    assert "Use spaces" in merged
    assert "English" in merged
    assert "Use tabs" not in merged


def test_merge_user_md_preamble_only_files(tmp_path: Path) -> None:
    global_file = tmp_path / "global.md"
    global_file.write_text("Global prefs here.\n")

    project_file = tmp_path / "project.md"
    project_file.write_text("Project-specific prefs.\n")

    merged = merge_user_md(global_path=global_file, project_path=project_file)
    assert "Project-specific prefs" in merged
    assert "Global prefs" not in merged


def test_merge_user_md_global_only(tmp_path: Path) -> None:
    global_file = tmp_path / "global.md"
    global_file.write_text("## Prefs\n\nMy prefs.\n")

    merged = merge_user_md(global_path=global_file, project_path=None)
    assert "My prefs" in merged


def test_merge_user_md_neither_exists(tmp_path: Path) -> None:
    merged = merge_user_md(
        global_path=tmp_path / "nonexistent.md",
        project_path=tmp_path / "also_nonexistent.md",
    )
    assert merged == ""


def test_read_file_anchor_exists(tmp_path: Path) -> None:
    anchor = tmp_path / "AGENTS.md"
    anchor.write_text("# Project Rules\n\nDo TDD.\n")

    content = read_file_anchor(anchor, token_limit=5000)
    assert "Do TDD" in content


def test_read_file_anchor_missing(tmp_path: Path) -> None:
    content = read_file_anchor(tmp_path / "missing.md", token_limit=5000)
    assert content == ""


def test_read_file_anchor_truncates(tmp_path: Path) -> None:
    anchor = tmp_path / "LARGE.md"
    anchor.write_text("x " * 10000)

    content = read_file_anchor(anchor, token_limit=100)
    assert len(content) < 1000


def test_upsert_managed_block_creates_file_and_section(tmp_path: Path) -> None:
    user_md = tmp_path / "USER.md"
    record = _make_record(
        id="mem_user0001",
        kind=MemoryKind.USER,
        scope=MemoryScope.USER,
        status=MemStatus.PROMOTED,
    )

    upsert_managed_block(user_md, record, note="stable preference")

    text = user_md.read_text()
    assert 'bourbon-managed:start section="preferences"' in text
    assert 'bourbon-memory:start id="mem_user0001"' in text
    assert "- status: promoted" in text
    assert "- note: stable preference" in text


def test_update_managed_block_status_marks_stale_without_deleting_block(tmp_path: Path) -> None:
    user_md = tmp_path / "USER.md"
    record = _make_record(
        id="mem_user0002",
        kind=MemoryKind.USER,
        scope=MemoryScope.USER,
        status=MemStatus.PROMOTED,
    )
    upsert_managed_block(user_md, record)

    update_managed_block_status(user_md, "mem_user0002", "stale")

    text = user_md.read_text()
    assert "- status: stale" in text
    assert 'bourbon-memory:end id="mem_user0002"' in text


def test_update_managed_block_status_is_noop_when_file_missing(tmp_path: Path) -> None:
    user_md = tmp_path / "USER.md"

    update_managed_block_status(user_md, "mem_missing0001", "stale")

    assert not user_md.exists()


def test_update_managed_block_status_is_noop_when_memory_id_missing(tmp_path: Path) -> None:
    user_md = tmp_path / "USER.md"
    record = _make_record(
        id="mem_user0005",
        kind=MemoryKind.USER,
        scope=MemoryScope.USER,
        status=MemStatus.PROMOTED,
    )
    upsert_managed_block(user_md, record)
    original_text = user_md.read_text()

    update_managed_block_status(user_md, "mem_unknown0001", "stale")

    assert user_md.read_text() == original_text


def test_upsert_managed_block_truncates_long_body_and_adds_source_backlink(tmp_path: Path) -> None:
    user_md = tmp_path / "USER.md"
    source_file = tmp_path / "memory" / "user_preference-mem_long0001.md"
    long_text = "token " * 220
    record = _make_record(
        id="mem_long0001",
        kind=MemoryKind.USER,
        scope=MemoryScope.USER,
        status=MemStatus.PROMOTED,
        content=long_text,
    )
    record.source_ref = None

    upsert_managed_block(user_md, record, source_path=source_file)

    text = user_md.read_text()
    managed_body = text.split("- note:", 1)[-1] if "- note:" in text else text
    assert "Source:" in text
    assert str(source_file) in text
    assert len(managed_body.split()) < len(long_text.split())


def test_upsert_managed_block_recovers_missing_end_marker_at_eof(tmp_path: Path, caplog) -> None:
    user_md = tmp_path / "USER.md"
    user_md.write_text(
        "\n".join(
            [
                "Intro",
                '<!-- bourbon-managed:start section="preferences" -->',
                "## Bourbon Managed Preferences",
            ]
        )
    )
    record = _make_record(
        id="mem_user0003",
        kind=MemoryKind.USER,
        scope=MemoryScope.USER,
        status=MemStatus.PROMOTED,
    )

    with caplog.at_level(logging.WARNING):
        upsert_managed_block(user_md, record)

    text = user_md.read_text()
    assert 'bourbon-memory:start id="mem_user0003"' in text
    assert text.rstrip().endswith('<!-- bourbon-managed:end section="preferences" -->')
    assert "managed section start without end" in caplog.text


def test_upsert_managed_block_ignores_orphan_end_marker(tmp_path: Path, caplog) -> None:
    user_md = tmp_path / "USER.md"
    user_md.write_text(
        "\n".join(
            [
                "Intro",
                '<!-- bourbon-managed:end section="preferences" -->',
                "More notes",
            ]
        )
    )
    record = _make_record(
        id="mem_user0004",
        kind=MemoryKind.USER,
        scope=MemoryScope.USER,
        status=MemStatus.PROMOTED,
    )

    with caplog.at_level(logging.WARNING):
        upsert_managed_block(user_md, record)

    text = user_md.read_text()
    assert text.count('bourbon-managed:end section="preferences"') == 1
    assert 'bourbon-memory:start id="mem_user0004"' in text
    assert "managed section end without start" in caplog.text


def test_render_merged_user_md_for_prompt_prefers_newer_promotions_on_budget_overflow(
    tmp_path: Path,
) -> None:
    global_file = tmp_path / "global.md"
    newer = _make_record(
        id="mem_newer0001",
        name="Newer",
        kind=MemoryKind.USER,
        scope=MemoryScope.USER,
        status=MemStatus.PROMOTED,
        content="Prefer uv for installs.",
    )
    older = _make_record(
        id="mem_older0001",
        name="Older",
        kind=MemoryKind.USER,
        scope=MemoryScope.USER,
        status=MemStatus.PROMOTED,
        content="Prefer pip for installs.",
    )
    older.updated_at = datetime(2026, 4, 20, tzinfo=UTC)
    newer.updated_at = older.updated_at + timedelta(days=1)

    upsert_managed_block(global_file, older)
    upsert_managed_block(global_file, newer)

    rendered = render_merged_user_md_for_prompt(global_file, None, token_limit=30)

    assert "Prefer uv for installs." in rendered
    assert "Prefer pip for installs." not in rendered


def test_render_merged_user_md_for_prompt_orders_promotions_by_timestamp_with_offsets(
    tmp_path: Path,
) -> None:
    global_file = tmp_path / "global.md"
    later_utc = _make_record(
        id="mem_offset0001",
        name="Later UTC",
        kind=MemoryKind.USER,
        scope=MemoryScope.USER,
        status=MemStatus.PROMOTED,
        content="Later absolute time.",
    )
    earlier_lexical = _make_record(
        id="mem_offset0002",
        name="Earlier UTC",
        kind=MemoryKind.USER,
        scope=MemoryScope.USER,
        status=MemStatus.PROMOTED,
        content="Earlier absolute time.",
    )
    later_utc.updated_at = datetime.fromisoformat("2026-04-22T10:00:00+00:00")
    earlier_lexical.updated_at = datetime.fromisoformat("2026-04-22T12:30:00+03:00")

    upsert_managed_block(global_file, earlier_lexical)
    upsert_managed_block(global_file, later_utc)

    rendered = render_merged_user_md_for_prompt(global_file, None, token_limit=50)

    assert rendered.index("Later absolute time.") < rendered.index("Earlier absolute time.")


def test_render_merged_user_md_for_prompt_preserves_blank_lines_in_managed_body(tmp_path: Path) -> None:
    global_file = tmp_path / "global.md"
    record = _make_record(
        id="mem_para00001",
        kind=MemoryKind.USER,
        scope=MemoryScope.USER,
        status=MemStatus.PROMOTED,
        content="First paragraph.\n\nSecond paragraph.",
    )

    upsert_managed_block(global_file, record)

    rendered = render_merged_user_md_for_prompt(global_file, None, token_limit=100)

    assert "First paragraph.\n\nSecond paragraph." in rendered
