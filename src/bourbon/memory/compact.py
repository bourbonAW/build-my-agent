"""Deterministic pre-compact memory extraction helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from bourbon.memory.models import MemoryKind, SourceRef

_REMEMBER_KEYWORDS = re.compile(
    r"\b(remember|always|never|以后|记住|从现在起|每次)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class FlushCandidate:
    """A compact-time candidate for memory persistence."""

    content: str
    source_ref: SourceRef
    kind: MemoryKind
    confidence: float


def extract_flush_candidates(
    messages: list[dict[str, Any]],
    *,
    session_id: str,
) -> list[FlushCandidate]:
    """Extract deterministic flush candidates from compactable messages."""
    candidates: list[FlushCandidate] = []

    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        uuid = msg.get("uuid", "")

        if isinstance(content, list):
            content = " ".join(
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and block.get("text")
            )

        if role == "user" and _REMEMBER_KEYWORDS.search(content):
            candidates.append(
                FlushCandidate(
                    content=content[:500],
                    source_ref=SourceRef(
                        kind="transcript",
                        session_id=session_id,
                        message_uuid=uuid,
                    ),
                    kind=MemoryKind.PROJECT,
                    confidence=0.6,
                )
            )

        for tool_result in msg.get("tool_results", []):
            if not tool_result.get("is_error"):
                continue
            candidates.append(
                FlushCandidate(
                    content=(
                        f"Error in {tool_result.get('tool_name', 'unknown')}: "
                        f"{str(tool_result.get('output', ''))[:300]}"
                    ),
                    source_ref=SourceRef(
                        kind="transcript",
                        session_id=session_id,
                        message_uuid=uuid,
                    ),
                    kind=MemoryKind.REFERENCE,
                    confidence=0.4,
                )
            )

    return candidates


def write_daily_log(
    log_dir: Path,
    *,
    session_start: datetime,
    session_id: str,
    entries: list[str],
) -> Path:
    """Append session entries to a date-based daily log."""
    date_str = session_start.strftime("%Y-%m-%d")
    log_path = (
        log_dir
        / session_start.strftime("%Y")
        / session_start.strftime("%m")
        / f"{date_str}.md"
    )
    log_path.parent.mkdir(parents=True, exist_ok=True)

    time_str = session_start.strftime("%H:%M")
    section = f"\n## Session {session_id} ({time_str})\n\n"
    section += "".join(f"- {entry}\n" for entry in entries)

    if log_path.exists():
        existing = log_path.read_text(encoding="utf-8")
        log_path.write_text(existing + section, encoding="utf-8")
    else:
        log_path.write_text(f"# Daily Log: {date_str}\n{section}", encoding="utf-8")

    return log_path
