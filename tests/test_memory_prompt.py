import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

from bourbon.memory.files import render_merged_user_md_for_prompt, upsert_managed_block
from bourbon.memory.models import MemoryKind, MemoryScope
from bourbon.memory.models import MemoryStatus as MemStatus
from bourbon.memory.prompt import MEMORY_ANCHOR_ORDER, memory_anchors_section
from bourbon.prompt.dynamic import DYNAMIC_SECTIONS
from bourbon.prompt.types import PromptContext
from tests.test_memory_store import _make_record


def test_memory_anchor_order() -> None:
    assert MEMORY_ANCHOR_ORDER == 15


def test_memory_anchors_section_registered() -> None:
    assert any(section.name == "memory_anchors" for section in DYNAMIC_SECTIONS)


def test_memory_anchors_section_no_manager() -> None:
    ctx = PromptContext(workdir=Path("/tmp/test"))
    result = asyncio.run(memory_anchors_section(ctx))
    assert result == ""


def test_memory_anchors_section_with_agents_md(tmp_path: Path) -> None:
    agents_md = tmp_path / "AGENTS.md"
    agents_md.write_text("# Rules\n\nAlways use TDD.\n")

    mock_manager = MagicMock()
    mock_manager.get_memory_dir.return_value = tmp_path / "memory"
    mock_manager.config.memory_md_token_limit = 1200
    mock_manager.config.user_md_token_limit = 600

    ctx = PromptContext(workdir=tmp_path, memory_manager=mock_manager)
    result = asyncio.run(memory_anchors_section(ctx))
    assert "Always use TDD" in result


def test_memory_anchors_section_includes_memory_md(tmp_path: Path) -> None:
    mem_dir = tmp_path / "memory"
    mem_dir.mkdir()
    memory_md = mem_dir / "MEMORY.md"
    memory_md.write_text("- [Rule 1](project_rule-1.md) - Important rule\n")

    mock_manager = MagicMock()
    mock_manager.get_memory_dir.return_value = mem_dir
    mock_manager.config.memory_md_token_limit = 1200
    mock_manager.config.user_md_token_limit = 600

    ctx = PromptContext(workdir=tmp_path, memory_manager=mock_manager)
    result = asyncio.run(memory_anchors_section(ctx))
    assert "Important rule" in result


def test_promoted_managed_blocks_render_before_handwritten_user_md_content(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    global_user_md = tmp_path / ".bourbon" / "USER.md"
    global_user_md.parent.mkdir()
    global_user_md.write_text("## Handwritten\n\nGlobal handwritten.\n")

    promoted = _make_record(
        id="mem_user0001",
        kind=MemoryKind.USER,
        scope=MemoryScope.USER,
        status=MemStatus.PROMOTED,
        content="Always use uv.",
    )
    upsert_managed_block(global_user_md, promoted)

    project_user_md = tmp_path / "project" / "USER.md"
    project_user_md.parent.mkdir()
    project_user_md.write_text("## Project\n\nProject handwritten.\n")

    mock_manager = MagicMock()
    mock_manager.get_memory_dir.return_value = tmp_path / "memory"
    mock_manager.config.memory_md_token_limit = 1200
    mock_manager.config.user_md_token_limit = 600

    ctx = PromptContext(workdir=project_user_md.parent, memory_manager=mock_manager)
    result = asyncio.run(memory_anchors_section(ctx))

    assert result.index("Always use uv.") < result.index("Global handwritten.")
    assert result.index("Always use uv.") < result.index("Project handwritten.")


def test_budget_overflow_prefers_newer_promotions_using_promoted_at_descending(
    tmp_path: Path,
) -> None:
    global_file = tmp_path / "USER.md"
    older = _make_record(
        id="mem_old000001",
        name="Old",
        kind=MemoryKind.USER,
        scope=MemoryScope.USER,
        status=MemStatus.PROMOTED,
        content="Older preference should drop first.",
    )
    newer = _make_record(
        id="mem_new000001",
        name="New",
        kind=MemoryKind.USER,
        scope=MemoryScope.USER,
        status=MemStatus.PROMOTED,
        content="Newer preference should survive.",
    )
    older.updated_at = datetime(2026, 4, 20, tzinfo=UTC)
    newer.updated_at = older.updated_at + timedelta(days=1)

    upsert_managed_block(global_file, older)
    upsert_managed_block(global_file, newer)

    rendered = render_merged_user_md_for_prompt(global_file, None, token_limit=30)

    assert "Newer preference should survive." in rendered
    assert "Older preference should drop first." not in rendered
