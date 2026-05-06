"""Tests for memory prompt anchor file helpers."""

from __future__ import annotations

from pathlib import Path

from bourbon.memory.files import merge_user_md, read_file_anchor, render_merged_user_md_for_prompt


def test_read_file_anchor_returns_empty_for_missing_file(tmp_path: Path) -> None:
    assert read_file_anchor(tmp_path / "missing.md", token_limit=100) == ""


def test_read_file_anchor_truncates_to_token_budget(tmp_path: Path) -> None:
    path = tmp_path / "MEMORY.md"
    path.write_text("x" * 1000, encoding="utf-8")

    text = read_file_anchor(path, token_limit=10)

    assert "[... truncated to token limit ...]" in text


def test_merge_user_md_prefers_project_preamble(tmp_path: Path) -> None:
    global_path = tmp_path / "global_USER.md"
    project_path = tmp_path / "USER.md"
    global_path.write_text("Global preference\n", encoding="utf-8")
    project_path.write_text("Project preference\n", encoding="utf-8")

    assert merge_user_md(global_path, project_path) == "Project preference\n"


def test_render_merged_user_md_for_prompt_uses_merge_and_budget(tmp_path: Path) -> None:
    global_path = tmp_path / "global_USER.md"
    project_path = tmp_path / "USER.md"
    global_path.write_text("# Style\n\nUse concise answers.\n", encoding="utf-8")
    project_path.write_text("# Style\n\nUse Chinese for this repo.\n", encoding="utf-8")

    rendered = render_merged_user_md_for_prompt(global_path, project_path, token_limit=100)

    assert "Use Chinese for this repo." in rendered
    assert "Use concise answers." not in rendered
