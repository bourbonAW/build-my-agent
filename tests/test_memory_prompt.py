import asyncio
from pathlib import Path
from unittest.mock import MagicMock

from bourbon.memory.prompt import MEMORY_ANCHOR_ORDER, memory_anchors_section
from bourbon.prompt.dynamic import DYNAMIC_SECTIONS
from bourbon.prompt.types import PromptContext


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
