"""Minimal memory file store."""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from bourbon.memory.cues import normalize_cues
from bourbon.memory.models import MemoryRecord, MemorySearchResult, validate_memory_target

_index_lock = threading.Lock()


def sanitize_project_key(canonical_path: Path) -> str:
    """Derive a filesystem-safe project key from canonical path."""
    path_str = str(canonical_path)
    slug = path_str.replace("/", "-").replace("\\", "-").replace(" ", "-")
    slug = re.sub(r"[^a-z0-9\-]", "", slug.lower())
    slug = re.sub(r"-+", "-", slug).strip("-")[:64]
    hash_suffix = hashlib.sha256(path_str.encode()).hexdigest()[:8]
    return f"{slug}-{hash_suffix}"


def _record_to_filename(record: MemoryRecord) -> str:
    """Return the record filename."""
    return f"{record.id}.md"


def _record_preview(record: MemoryRecord, *, limit: int = 100) -> str:
    """Return display text derived from content."""
    first_line = next((line.strip() for line in record.content.splitlines() if line.strip()), "")
    preview = first_line or record.content.strip()
    return preview[:limit].rstrip()


def _record_to_frontmatter(record: MemoryRecord) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "id": record.id,
        "target": record.target,
        "created_at": record.created_at.isoformat(),
    }
    if record.cues:
        raw["cues"] = list(record.cues)
    return raw


def _record_to_file_content(record: MemoryRecord) -> str:
    frontmatter = yaml.dump(_record_to_frontmatter(record), default_flow_style=False)
    return f"---\n{frontmatter}---\n\n{record.content.rstrip()}\n"


def _frontmatter_to_record(fm: dict[str, Any], body: str) -> MemoryRecord:
    created_at = fm["created_at"]
    if isinstance(created_at, str):
        created_at = datetime.fromisoformat(created_at)
    cues = fm.get("cues", [])
    if not isinstance(cues, list):
        cues = []
    return MemoryRecord(
        id=str(fm["id"]),
        target=validate_memory_target(str(fm["target"])),
        content=body.strip(),
        created_at=created_at,
        cues=normalize_cues(cues),
    )


class MemoryStore:
    """File-based memory storage with atomic writes and simple search."""

    def __init__(self, memory_dir: Path) -> None:
        self.memory_dir = memory_dir
        self._id_to_filename: dict[str, str] = {}
        self._scan_existing()

    def _scan_existing(self) -> None:
        if not self.memory_dir.exists():
            return
        for path in self.memory_dir.glob("*.md"):
            if path.name == "MEMORY.md":
                continue
            try:
                fm, _ = self._parse_file(path)
                if "id" in fm:
                    self._id_to_filename[str(fm["id"])] = path.name
            except Exception:
                continue

    def _parse_file(self, path: Path) -> tuple[dict[str, Any], str]:
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            return {}, text
        end_marker = text.find("\n---\n", 4)
        if end_marker == -1:
            return {}, text
        raw_frontmatter = text[4:end_marker]
        body = text[end_marker + len("\n---\n") :]
        loaded = yaml.safe_load(raw_frontmatter) or {}
        return loaded if isinstance(loaded, dict) else {}, body

    def _atomic_write(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            os.write(fd, content.encode("utf-8"))
            os.close(fd)
            fd = -1
            os.replace(tmp_path, path)
        except Exception:
            if fd >= 0:
                with contextlib.suppress(OSError):
                    os.close(fd)
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

    def write_record(self, record: MemoryRecord) -> Path:
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        filename = _record_to_filename(record)
        target = self.memory_dir / filename
        self._atomic_write(target, _record_to_file_content(record))
        self._id_to_filename[record.id] = filename
        self.rebuild_index()
        return target

    def delete_record(self, memory_id: str) -> None:
        filename = self._id_to_filename.get(memory_id)
        if filename is None:
            self._scan_existing()
            filename = self._id_to_filename.get(memory_id)
        if filename is None:
            raise KeyError(f"Unknown memory id: {memory_id}")
        path = self.memory_dir / filename
        if path.exists():
            path.unlink()
        self._id_to_filename.pop(memory_id, None)
        self.rebuild_index()

    def read_record(self, memory_id: str) -> MemoryRecord | None:
        filename = self._id_to_filename.get(memory_id)
        if filename is None:
            self._scan_existing()
            filename = self._id_to_filename.get(memory_id)
        if filename is None:
            return None
        path = self.memory_dir / filename
        if not path.exists():
            return None
        fm, body = self._parse_file(path)
        if "id" not in fm:
            return None
        return _frontmatter_to_record(fm, body)

    def list_records(self) -> list[MemoryRecord]:
        records: list[MemoryRecord] = []
        if not self.memory_dir.exists():
            return records
        for path in sorted(self.memory_dir.glob("*.md")):
            if path.name == "MEMORY.md":
                continue
            try:
                fm, body = self._parse_file(path)
                if "id" not in fm:
                    continue
                records.append(_frontmatter_to_record(fm, body))
            except Exception:
                continue
        return sorted(records, key=lambda record: record.created_at, reverse=True)

    def rebuild_index(self) -> bool:
        records = self.list_records()[:200]
        lines = [
            f"- [{record.target}] {_record_preview(record)} "
            f"([{_record_to_filename(record)}]({_record_to_filename(record)}))"
            for record in records
        ]
        content = "\n".join(lines)
        if content:
            content += "\n"
        with _index_lock:
            self._atomic_write(self.memory_dir / "MEMORY.md", content)
        return len(records) >= 200

    def search(
        self,
        query: str,
        *,
        target: str | None = None,
        limit: int = 8,
    ) -> list[MemorySearchResult]:
        normalized_query = query.casefold()
        results: list[MemorySearchResult] = []
        for record in self.list_records():
            if target is not None and record.target != target:
                continue
            content_match = normalized_query in record.content.casefold()
            matched_cue = next(
                (cue for cue in record.cues if normalized_query in cue.casefold()),
                None,
            )
            if not content_match and matched_cue is None:
                continue
            reason = (
                f"matched cue: {matched_cue}"
                if matched_cue is not None
                else f"matched content: {query}"
            )
            results.append(
                MemorySearchResult(
                    id=record.id,
                    target=record.target,
                    snippet=_record_preview(record),
                    why_matched=reason,
                )
            )
            if len(results) >= limit:
                break
        return results
