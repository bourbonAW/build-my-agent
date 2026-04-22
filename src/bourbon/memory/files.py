"""Helpers for reading prompt anchor files and merging USER.md content."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from bourbon.memory.models import MemoryRecord
from bourbon.memory.store import _record_to_filename

_PREAMBLE_KEY = "__preamble__"
_MANAGED_SECTION_START = '<!-- bourbon-managed:start section="preferences" -->'
_MANAGED_SECTION_END = '<!-- bourbon-managed:end section="preferences" -->'
_MANAGED_HEADER = "\n".join(
    [
        "## Bourbon Managed Preferences",
        "",
        "> Managed by Bourbon. Marker lines must be preserved. Manual edits inside a block may be overwritten the next time Bourbon upserts that same memory.",
    ]
)
_BLOCK_RE = re.compile(
    r'<!-- bourbon-memory:start id="(?P<id>[^"]+)" -->\n'
    r"(?P<body>.*?)\n"
    r'<!-- bourbon-memory:end id="(?P=id)" -->',
    re.DOTALL,
)
_STATUS_RE = re.compile(r"^- status: .*$", re.MULTILINE)
_PROMOTED_AT_RE = re.compile(r"^- promoted_at: (?P<value>.+)$", re.MULTILINE)
_LOGGER = logging.getLogger(__name__)


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


def _merge_user_md_text(global_text: str, project_text: str) -> str:
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


def merge_user_md(global_path: Path | None, project_path: Path | None) -> str:
    """Merge global and project USER.md with project-local headings taking priority."""
    return _merge_user_md_text(_read_text(global_path), _read_text(project_path))


def _extract_managed_section(text: str, path: Path | None = None) -> tuple[str, str]:
    start_index = text.find(_MANAGED_SECTION_START)
    end_index = text.find(_MANAGED_SECTION_END)

    if start_index == -1:
        if end_index != -1:
            _LOGGER.warning(
                "Found bourbon managed section end without start in %s; ignoring orphan marker",
                path or "<memory>",
            )
            text = text.replace(_MANAGED_SECTION_END, "", 1)
        return text, ""

    if end_index != -1 and end_index < start_index:
        _LOGGER.warning(
            "Found bourbon managed section end without start in %s; ignoring orphan marker",
            path or "<memory>",
        )
        text = text[:end_index] + text[end_index + len(_MANAGED_SECTION_END) :]
        start_index = text.find(_MANAGED_SECTION_START)

    after_start = start_index + len(_MANAGED_SECTION_START)
    end_index = text.find(_MANAGED_SECTION_END, after_start)
    if end_index == -1:
        _LOGGER.warning(
            "Found bourbon managed section start without end in %s; closing at EOF",
            path or "<memory>",
        )
        return text[:start_index].rstrip(), text[after_start:].strip()

    handwritten = (text[:start_index] + text[end_index + len(_MANAGED_SECTION_END) :]).strip()
    managed = text[after_start:end_index].strip()
    return handwritten, managed


def _build_managed_section(blocks: list[str]) -> str:
    body_parts = [_MANAGED_HEADER]
    if blocks:
        body_parts.append("\n\n".join(blocks))
    body = "\n\n".join(part for part in body_parts if part).strip()
    return f"{_MANAGED_SECTION_START}\n{body}\n{_MANAGED_SECTION_END}"


def _extract_blocks(managed_text: str) -> list[tuple[str, str]]:
    return [(match.group("id"), match.group(0).strip()) for match in _BLOCK_RE.finditer(managed_text)]


def _render_managed_body(content: str, source_path: Path) -> str:
    if _estimate_tokens(content) <= 150:
        return content.strip()
    truncated = _truncate_to_tokens(content.strip(), 150).strip()
    return f"{truncated}\n\nSource: {source_path}"


def _format_block(record: MemoryRecord, note: str, source_path: Path) -> str:
    metadata = [
        f"- status: {record.status}",
        f"- kind: {record.kind}",
        f"- promoted_at: {record.updated_at.isoformat()}",
    ]
    if note:
        metadata.append(f"- note: {note}")
    body = _render_managed_body(record.content, source_path)
    title = f"### User Preference: {record.id}"
    return "\n".join(
        [
            f'<!-- bourbon-memory:start id="{record.id}" -->',
            title,
            "",
            *metadata,
            "",
            body,
            f'<!-- bourbon-memory:end id="{record.id}" -->',
        ]
    ).strip()


def upsert_managed_block(
    user_md_path: Path,
    record: MemoryRecord,
    note: str = "",
    source_path: Path | None = None,
) -> None:
    """Insert or replace a bourbon-managed block in USER.md."""
    text = _read_text(user_md_path)
    handwritten, managed = _extract_managed_section(text, user_md_path)
    blocks = _extract_blocks(managed)
    source_path = source_path or Path(_record_to_filename(record))
    rendered_block = _format_block(record, note=note, source_path=source_path)

    updated_blocks: list[str] = []
    replaced = False
    for memory_id, block in blocks:
        if memory_id == record.id:
            updated_blocks.append(rendered_block)
            replaced = True
            continue
        updated_blocks.append(block)
    if not replaced:
        updated_blocks.append(rendered_block)

    sections = [part for part in [handwritten, _build_managed_section(updated_blocks)] if part]
    user_md_path.parent.mkdir(parents=True, exist_ok=True)
    user_md_path.write_text("\n\n".join(sections).strip() + "\n", encoding="utf-8")


def update_managed_block_status(
    user_md_path: Path,
    memory_id: str,
    status: str,
) -> None:
    """Update status field inside an existing managed block."""
    text = _read_text(user_md_path)
    handwritten, managed = _extract_managed_section(text, user_md_path)
    updated_blocks: list[str] = []

    for block_id, block in _extract_blocks(managed):
        if block_id == memory_id:
            block = _STATUS_RE.sub(f"- status: {status}", block, count=1)
        updated_blocks.append(block)

    sections = [part for part in [handwritten, _build_managed_section(updated_blocks)] if part]
    user_md_path.parent.mkdir(parents=True, exist_ok=True)
    user_md_path.write_text("\n\n".join(sections).strip() + "\n", encoding="utf-8")


def _parse_promoted_at(block: str) -> str:
    match = _PROMOTED_AT_RE.search(block)
    return match.group("value") if match else ""


def _is_promoted_block(block: str) -> bool:
    return "- status: promoted" in block


def _block_prompt_content(block: str) -> str:
    lines = block.splitlines()
    content_lines: list[str] = []
    in_body = False

    for line in lines:
        if line.startswith("<!-- bourbon-memory:"):
            continue
        if not in_body:
            if not line.strip():
                if any(
                    candidate.startswith(("- status:", "- kind:", "- promoted_at:", "- note:"))
                    for candidate in lines[max(0, len(content_lines)) :]
                ):
                    continue
            if line.startswith("### "):
                continue
            if line.startswith(("- status:", "- kind:", "- promoted_at:", "- note:")):
                continue
            if not line.strip():
                in_body = True
                continue
        if in_body or line.strip():
            content_lines.append(line)

    return "\n".join(content_lines).strip()


def _render_promoted_blocks(blocks: list[str], token_limit: int) -> str:
    if token_limit <= 0 or not blocks:
        return ""

    rendered_blocks: list[str] = []
    heading = "## Bourbon Managed Preferences"
    used_tokens = _estimate_tokens(heading)
    for block in blocks:
        prompt_block = _block_prompt_content(block)
        if not prompt_block:
            continue
        block_tokens = _estimate_tokens(prompt_block)
        if not rendered_blocks and block_tokens > token_limit:
            return _truncate_to_tokens(prompt_block, token_limit)
        if used_tokens + block_tokens > token_limit:
            break
        rendered_blocks.append(prompt_block)
        used_tokens += block_tokens

    if not rendered_blocks:
        return ""
    return heading + "\n\n" + "\n\n".join(rendered_blocks).strip() + "\n"


def render_merged_user_md_for_prompt(
    global_path: Path | None,
    project_path: Path | None,
    token_limit: int,
) -> str:
    """Render USER.md for prompt injection with managed-first budgeting."""
    global_text = _read_text(global_path)
    project_text = _read_text(project_path)
    global_handwritten, managed = _extract_managed_section(global_text, global_path)

    promoted_blocks = sorted(
        [block for _, block in _extract_blocks(managed) if _is_promoted_block(block)],
        key=_parse_promoted_at,
        reverse=True,
    )
    managed_budget = min(300, token_limit // 2) if promoted_blocks else 0
    managed_content = _render_promoted_blocks(promoted_blocks, managed_budget)
    remaining_budget = max(0, token_limit - _estimate_tokens(managed_content))
    handwritten_content = _truncate_to_tokens(
        _merge_user_md_text(global_handwritten, project_text),
        remaining_budget,
    )

    if managed_content and handwritten_content:
        return f"{managed_content}\n\n{handwritten_content}".strip() + "\n"
    return managed_content or handwritten_content
