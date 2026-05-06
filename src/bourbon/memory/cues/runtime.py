"""Runtime evidence extraction for memory cue generation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from bourbon.memory.models import SourceRef

READ_TOOLS = {
    "read",
    "Read",
    "rg_search",
    "grep",
    "Grep",
    "glob",
    "Glob",
    "ast_grep_search",
    "AstGrep",
    "csv_analyze",
    "CsvAnalyze",
    "json_query",
    "JsonQuery",
    "pdf_to_text",
    "PdfRead",
    "docx_to_markdown",
    "DocxRead",
}
WRITE_TOOLS = {
    "write",
    "Write",
    "write_file",
    "edit",
    "Edit",
    "edit_file",
    "str_replace",
    "StrReplace",
}
SEARCH_TOOLS = {"rg_search", "grep", "Grep", "glob", "Glob", "ast_grep_search", "AstGrep"}


@dataclass(frozen=True)
class CueRuntimeContext:
    """Runtime evidence available when record-side cues are generated."""

    workdir: Path
    current_files: list[str] = field(default_factory=list)
    touched_files: list[str] = field(default_factory=list)
    modified_files: list[str] = field(default_factory=list)
    symbols: list[str] = field(default_factory=list)
    source_ref: SourceRef | None = None
    recent_tool_names: list[str] = field(default_factory=list)
    task_subject: str | None = None
    session_id: str | None = None

    def fingerprint(self) -> str:
        """Return a deterministic fingerprint excluding session identity."""
        source_ref_file = self.source_ref.file_path if self.source_ref else ""
        payload = {
            "current_files": sorted(self.current_files),
            "touched_files": sorted(self.touched_files),
            "modified_files": sorted(self.modified_files),
            "symbols": sorted(self.symbols),
            "recent_tool_names": self.recent_tool_names[-5:],
            "task_subject": self.task_subject or "",
            "source_ref_file": source_ref_file or "",
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()[:16]


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        normalized = item.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def extract_paths_from_tool_input(tool_input: dict[str, Any]) -> list[str]:
    """Extract explicit file/path inputs without treating glob patterns as files."""
    candidates: list[str] = []
    for key in ("file_path", "filepath", "path"):
        value = tool_input.get(key)
        if isinstance(value, str) and "*" not in value and "?" not in value:
            candidates.append(value)
    for key in ("files", "file_paths"):
        value = tool_input.get(key)
        if isinstance(value, list):
            candidates.extend(str(item) for item in value if "*" not in str(item))
    return _dedupe(candidates)


def _iter_tool_uses(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tool_uses: list[dict[str, Any]] = []
    for message in messages:
        content = message.get("content", [])
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                tool_uses.append(block)
    return tool_uses


def build_runtime_context_from_messages(
    messages: list[dict[str, Any]],
    *,
    workdir: Path,
    source_ref: SourceRef | None = None,
    session_id: str | None = None,
    task_subject: str | None = None,
) -> CueRuntimeContext:
    """Build runtime cue context from recent LLM-format message dictionaries."""
    tool_uses = _iter_tool_uses(messages)[-20:]
    touched: list[str] = []
    modified: list[str] = []
    read_or_edit: list[str] = []
    recent_tool_names: list[str] = []

    for tool in tool_uses:
        name = str(tool.get("name", ""))
        recent_tool_names.append(name)
        tool_input = tool.get("input", {})
        if not isinstance(tool_input, dict):
            continue
        paths = extract_paths_from_tool_input(tool_input)
        if name in READ_TOOLS or name in WRITE_TOOLS or name in SEARCH_TOOLS:
            touched.extend(paths)
        if (name in READ_TOOLS and name not in SEARCH_TOOLS) or name in WRITE_TOOLS:
            read_or_edit.extend(paths)
        if name in WRITE_TOOLS:
            modified.extend(paths)

    current_files = _dedupe(list(reversed(read_or_edit)))[:3]
    current_files = sorted(current_files)
    return CueRuntimeContext(
        workdir=workdir,
        current_files=current_files,
        touched_files=sorted(_dedupe(touched)),
        modified_files=sorted(_dedupe(modified)),
        symbols=[],
        source_ref=source_ref,
        recent_tool_names=recent_tool_names[-10:],
        task_subject=task_subject,
        session_id=session_id,
    )
