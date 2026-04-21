"""Memory file store — file CRUD, MEMORY.md index, grep search."""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from bourbon.memory.models import (
    MemoryKind,
    MemoryRecord,
    MemoryScope,
    MemorySearchResult,
    MemorySource,
    MemoryStatus,
    SourceRef,
)

_index_lock = threading.Lock()


def sanitize_project_key(canonical_path: Path) -> str:
    """Derive a filesystem-safe project key from canonical path.

    Algorithm:
    1. Convert path to string
    2. Slugify: replace /, \\, space with -, remove non-ASCII, lowercase
    3. Truncate slug to 64 chars
    4. Append SHA256[:8] of original path
    """
    path_str = str(canonical_path)
    # Slugify
    slug = path_str.replace("/", "-").replace("\\", "-").replace(" ", "-")
    slug = re.sub(r"[^a-z0-9\-]", "", slug.lower())
    slug = re.sub(r"-+", "-", slug).strip("-")
    slug = slug[:64]
    # Hash suffix
    hash_suffix = hashlib.sha256(path_str.encode()).hexdigest()[:8]
    return f"{slug}-{hash_suffix}"


def _slugify_name(name: str) -> str:
    """Convert name to filename-safe slug."""
    slug = name.lower().replace(" ", "-")
    slug = re.sub(r"[^a-z0-9\-]", "", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug[:50]


def _record_to_filename(record: MemoryRecord) -> str:
    """Derive filename from kind and name."""
    slug = _slugify_name(record.name)
    return f"{record.kind}_{slug}.md"


def _record_to_frontmatter(record: MemoryRecord) -> dict[str, Any]:
    """Convert record metadata to YAML frontmatter dict."""
    fm: dict[str, Any] = {
        "id": record.id,
        "name": record.name,
        "description": record.description,
        "kind": str(record.kind),
        "scope": str(record.scope),
        "confidence": record.confidence,
        "source": str(record.source),
        "status": str(record.status),
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
        "created_by": record.created_by,
    }
    if record.source_ref:
        ref_dict: dict[str, Any] = {"kind": record.source_ref.kind}
        for f in (
            "project_name",
            "session_id",
            "message_uuid",
            "start_message_uuid",
            "end_message_uuid",
            "file_path",
            "tool_call_id",
        ):
            val = getattr(record.source_ref, f)
            if val is not None:
                ref_dict[f] = val
        fm["source_ref"] = ref_dict
    return fm


def _frontmatter_to_record(fm: dict[str, Any], body: str) -> MemoryRecord:
    """Parse frontmatter dict + body into MemoryRecord."""
    source_ref = None
    if "source_ref" in fm:
        ref_data = fm["source_ref"]
        source_ref = SourceRef(
            kind=ref_data["kind"],
            project_name=ref_data.get("project_name"),
            session_id=ref_data.get("session_id"),
            message_uuid=ref_data.get("message_uuid"),
            start_message_uuid=ref_data.get("start_message_uuid"),
            end_message_uuid=ref_data.get("end_message_uuid"),
            file_path=ref_data.get("file_path"),
            tool_call_id=ref_data.get("tool_call_id"),
        )

    created_at = fm["created_at"]
    if isinstance(created_at, str):
        created_at = __import__("datetime").datetime.fromisoformat(created_at)
    updated_at = fm["updated_at"]
    if isinstance(updated_at, str):
        updated_at = __import__("datetime").datetime.fromisoformat(updated_at)

    return MemoryRecord(
        id=fm["id"],
        name=fm["name"],
        description=fm["description"],
        kind=MemoryKind(fm["kind"]),
        scope=MemoryScope(fm["scope"]),
        confidence=float(fm["confidence"]),
        source=MemorySource(fm["source"]),
        status=MemoryStatus(fm["status"]),
        created_at=created_at,
        updated_at=updated_at,
        created_by=fm["created_by"],
        content=body.strip(),
        source_ref=source_ref,
    )


class MemoryStore:
    """File-based memory storage with atomic writes and grep search."""

    def __init__(self, memory_dir: Path) -> None:
        self.memory_dir = memory_dir
        self._id_to_filename: dict[str, str] = {}
        self._scan_existing()

    def _scan_existing(self) -> None:
        """Build id->filename index from existing files."""
        if not self.memory_dir.exists():
            return
        for f in self.memory_dir.glob("*.md"):
            if f.name == "MEMORY.md":
                continue
            try:
                fm, _ = self._parse_file(f)
                if "id" in fm:
                    self._id_to_filename[fm["id"]] = f.name
            except Exception:
                continue

    def _parse_file(self, path: Path) -> tuple[dict[str, Any], str]:
        """Parse a memory file into (frontmatter_dict, body_str)."""
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---"):
            return {}, text
        parts = text.split("---", 2)
        if len(parts) < 3:
            return {}, text
        fm = yaml.safe_load(parts[1]) or {}
        body = parts[2]
        return fm, body

    def _atomic_write(self, path: Path, content: str) -> None:
        """Write content to path using atomic rename."""
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
        """Write a memory record to disk using atomic rename."""
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        filename = _record_to_filename(record)
        target = self.memory_dir / filename

        fm = _record_to_frontmatter(record)
        content = (
            f"---\n{yaml.dump(fm, default_flow_style=False, allow_unicode=True)}---\n\n"
            f"{record.content}\n"
        )

        self._atomic_write(target, content)
        self._id_to_filename[record.id] = filename
        return target

    def read_record(self, memory_id: str) -> MemoryRecord | None:
        """Read a memory record by id."""
        filename = self._id_to_filename.get(memory_id)
        if not filename:
            # Fallback: scan files
            self._scan_existing()
            filename = self._id_to_filename.get(memory_id)
        if not filename:
            return None

        path = self.memory_dir / filename
        if not path.exists():
            return None

        fm, body = self._parse_file(path)
        return _frontmatter_to_record(fm, body)

    def list_records(self, *, status: list[str] | None = None) -> list[MemoryRecord]:
        """List all memory records, optionally filtered by status."""
        records: list[MemoryRecord] = []
        if not self.memory_dir.exists():
            return records
        for f in sorted(self.memory_dir.glob("*.md")):
            if f.name == "MEMORY.md":
                continue
            try:
                fm, body = self._parse_file(f)
                if "id" not in fm:
                    continue
                record = _frontmatter_to_record(fm, body)
                if status and record.status not in status:
                    continue
                records.append(record)
            except Exception:
                continue
        return records

    # --- Task 5: MEMORY.md Index ---

    def update_index(self, record: MemoryRecord) -> bool:
        """Update MEMORY.md index with record entry.

        Returns True if index is at capacity (>=200 lines) and entry was NOT added.
        """
        index_path = self.memory_dir / "MEMORY.md"
        filename = _record_to_filename(record)
        entry_line = f"- [{record.name}]({filename}) — {record.description}"

        with _index_lock:
            existing_lines: list[str] = []
            if index_path.exists():
                existing_lines = index_path.read_text(encoding="utf-8").strip().split("\n")
                existing_lines = [line for line in existing_lines if line.strip()]

            # Deduplicate: remove existing entry with same filename
            new_lines = [line for line in existing_lines if f"]({filename})" not in line]

            # Capacity check
            if len(new_lines) >= 200:
                content = "\n".join(new_lines) + "\n"
                self._atomic_write(index_path, content)
                return True

            new_lines.append(entry_line)
            content = "\n".join(new_lines) + "\n"
            self._atomic_write(index_path, content)
            return False

    # --- Task 6: Grep-Based Search ---

    def search(
        self,
        query: str,
        *,
        kind: list[str] | None = None,
        status: list[str] | None = None,
        limit: int = 8,
    ) -> list[MemorySearchResult]:
        """Search memory files using grep.

        Args:
            query: Search string
            kind: Filter by memory kind
            status: Filter by status (default: ["active"])
            limit: Max results to return
        """
        if status is None:
            status = ["active"]

        if not self.memory_dir.exists():
            return []

        matching_files = self._grep_files(query)

        results: list[MemorySearchResult] = []
        for filepath, matched_lines in matching_files:
            try:
                fm, body = self._parse_file(filepath)
                if "id" not in fm:
                    continue

                record = _frontmatter_to_record(fm, body)

                # Apply filters
                if record.status not in status:
                    continue
                if kind and record.kind not in kind:
                    continue

                snippet = "\n".join(matched_lines[:3])
                results.append(
                    MemorySearchResult(
                        id=record.id,
                        name=record.name,
                        kind=record.kind,
                        scope=record.scope,
                        snippet=snippet,
                        confidence=record.confidence,
                        status=record.status,
                        source_ref=record.source_ref,
                        why_matched=f"grep: {query}",
                    )
                )

                if len(results) >= limit:
                    break
            except Exception:
                continue

        return results

    def _grep_files(self, query: str) -> list[tuple[Path, list[str]]]:
        """Run grep/ripgrep on memory directory, return (file, matched_lines) pairs."""
        if not self.memory_dir.exists():
            return []

        try:
            result = subprocess.run(
                [
                    "rg",
                    "--no-heading",
                    "--with-filename",
                    "-C",
                    "1",
                    "--type",
                    "md",
                    query,
                    str(self.memory_dir),
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode not in (0, 1):  # 1 means no matches
                return self._python_grep(query)
            if not result.stdout.strip():
                return []

            # Parse grouped output
            files_with_matches: dict[Path, list[str]] = {}
            for line in result.stdout.strip().split("\n"):
                if not line or line == "--":
                    continue
                # rg format: /path/file.md:linenum:content or /path/file.md-linenum-content
                for sep in (":", "-"):
                    parts = line.split(sep, 2)
                    if len(parts) >= 3:
                        fp = Path(parts[0])
                        if fp.suffix == ".md" and fp.name != "MEMORY.md":
                            files_with_matches.setdefault(fp, []).append(parts[2])
                        break

            return list(files_with_matches.items())
        except (FileNotFoundError, subprocess.TimeoutExpired):
            # Fallback to Python grep if rg not available
            return self._python_grep(query)

    def _python_grep(self, query: str) -> list[tuple[Path, list[str]]]:
        """Fallback grep using Python when ripgrep is not available."""
        results: list[tuple[Path, list[str]]] = []
        if not self.memory_dir.exists():
            return results
        query_lower = query.lower()
        for f in sorted(self.memory_dir.glob("*.md")):
            if f.name == "MEMORY.md":
                continue
            try:
                text = f.read_text(encoding="utf-8")
                if query_lower in text.lower():
                    lines = [line for line in text.split("\n") if query_lower in line.lower()]
                    results.append((f, lines[:5]))
            except Exception:
                continue
        return results
