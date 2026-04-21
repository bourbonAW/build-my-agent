from pathlib import Path

from bourbon.memory.files import merge_user_md, read_file_anchor


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
