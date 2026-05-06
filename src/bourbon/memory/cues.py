"""Small cue helpers for minimal memory search."""

from __future__ import annotations

import re
from collections.abc import Iterable

MAX_CUES = 12
_MAX_CUE_LENGTH = 80
_BACKTICK_RE = re.compile(r"`([^`]{1,120})`")
_QUOTE_RE = re.compile(r'"([^"]{1,120})"')
_PATH_RE = re.compile(r"(?<!\w)[\w./@+-]+\.[A-Za-z0-9]{1,8}(?!\w)")


def _clean_term(value: object) -> str:
    text = " ".join(str(value).strip().split())
    return text[:_MAX_CUE_LENGTH].rstrip()


def normalize_cues(values: Iterable[object], *, limit: int = MAX_CUES) -> tuple[str, ...]:
    """Normalize cue strings while preserving first-seen order."""
    cues: list[str] = []
    seen: set[str] = set()
    for value in values:
        cue = _clean_term(value)
        key = cue.casefold()
        if not cue or key in seen:
            continue
        cues.append(cue)
        seen.add(key)
        if len(cues) >= limit:
            break
    return tuple(cues)


def _extract_terms(text: str) -> list[str]:
    terms: list[str] = []
    terms.extend(match.group(1) for match in _BACKTICK_RE.finditer(text))
    terms.extend(match.group(1) for match in _QUOTE_RE.finditer(text))
    terms.extend(match.group(0) for match in _PATH_RE.finditer(text))
    return terms


def generate_cues(content: str) -> tuple[str, ...]:
    """Generate write-time cues from explicit textual hints only."""
    return normalize_cues(_extract_terms(content))


def expand_query_terms(query: str) -> tuple[str, ...]:
    """Return the normalized query plus explicit terms extracted from it."""
    base = _clean_term(query)
    if not base:
        return ()
    return normalize_cues((base, *_extract_terms(query)))
