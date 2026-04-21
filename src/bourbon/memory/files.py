"""Helpers for reading prompt anchor files and merging USER.md content."""

from __future__ import annotations

from pathlib import Path

_PREAMBLE_KEY = "__preamble__"


def _estimate_tokens(text: str) -> int:
    """Estimate token count with a simple character heuristic."""
    return len(text) // 4


def _truncate_to_tokens(text: str, token_limit: int) -> str:
    """Truncate text to an approximate token budget."""
    if token_limit <= 0:
        return ""

    if _estimate_tokens(text) <= token_limit:
        return text

    char_limit = token_limit * 4
    truncated = text[:char_limit]
    last_newline = truncated.rfind("\n")
    if last_newline > char_limit // 2:
        truncated = truncated[:last_newline]
    return truncated.rstrip() + "\n\n[... truncated to token limit ...]"


def read_file_anchor(path: Path, token_limit: int) -> str:
    """Read an anchor file if it exists, returning an empty string on failure."""
    if not path.exists():
        return ""

    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""

    return _truncate_to_tokens(text, token_limit)


def _parse_sections(text: str) -> list[tuple[str, str]]:
    """Parse markdown text into sections keyed by normalized heading."""
    sections: list[tuple[str, str]] = []
    current_key = _PREAMBLE_KEY
    current_lines: list[str] = []

    for line in text.splitlines():
        if line.startswith("#"):
            if current_lines:
                sections.append((current_key, "\n".join(current_lines).strip()))
            current_key = line.lstrip("#").strip().lower()
            current_lines = [line]
            continue
        current_lines.append(line)

    if current_lines:
        sections.append((current_key, "\n".join(current_lines).strip()))

    return [(key, content) for key, content in sections if content]


def _read_text(path: Path | None) -> str:
    if path is None or not path.exists():
        return ""

    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _only_preamble(sections: list[tuple[str, str]]) -> bool:
    return all(key == _PREAMBLE_KEY for key, _ in sections)


def merge_user_md(global_path: Path | None, project_path: Path | None) -> str:
    """Merge global and project USER.md with project-local headings taking priority."""
    global_text = _read_text(global_path)
    project_text = _read_text(project_path)

    if not global_text and not project_text:
        return ""
    if not global_text:
        return project_text
    if not project_text:
        return global_text

    global_sections = _parse_sections(global_text)
    project_sections = _parse_sections(project_text)

    if _only_preamble(global_sections) and _only_preamble(project_sections):
        return project_text

    global_map = dict(global_sections)
    project_map = dict(project_sections)
    merged_parts: list[str] = []

    preamble = project_map.get(_PREAMBLE_KEY) or global_map.get(_PREAMBLE_KEY)
    if preamble:
        merged_parts.append(preamble)

    seen_keys: set[str] = set()
    for key, content in global_sections:
        if key == _PREAMBLE_KEY:
            continue
        merged_parts.append(project_map.get(key, content))
        seen_keys.add(key)

    for key, content in project_sections:
        if key in {_PREAMBLE_KEY, *seen_keys}:
            continue
        merged_parts.append(content)

    return "\n\n".join(part for part in merged_parts if part).strip() + "\n"
