"""Query-side cue interpretation fast path."""

from __future__ import annotations

import re
from collections import OrderedDict
from dataclasses import dataclass
from typing import TYPE_CHECKING

from bourbon.memory.cues.models import (
    CueKind,
    CueQualityFlag,
    CueSource,
    RetrievalCue,
)
from bourbon.memory.cues.runtime import CueRuntimeContext

if TYPE_CHECKING:
    from bourbon.memory.cues.models import QueryCue, RecallNeed

QUERY_SCHEMA_VERSION = "cue.v1"
INTERPRETER_VERSION = "query-cue-v1"
MAX_QUERY_CUE_TEXT_LENGTH = 80

_ENGLISH_MEMORY_RECALL_MARKERS = (
    "last time",
    "previously",
    "earlier",
    "remember",
    "memory",
    "before",
    "we discussed",
    "we decided",
)
_CJK_MEMORY_RECALL_MARKERS = (
    "上次",
    "之前",
    "记得",
    "当时",
    "以前讨论",
    "以前",
)
_PATH_EXTENSION_RE = re.compile(r"^[\w@+., -]+\.[A-Za-z0-9]{1,8}(?:::[A-Za-z_]\w*)?$")
_CODE_LEADING_RE = re.compile(
    r"^\s*(?:def|class|import|from|return|if|for|while|try|except|with|async\s+def)\b"
)
_ASSIGNMENT_RE = re.compile(r"\b[A-Za-z_]\w*\s*=\s*[^=]")
_CALL_RE = re.compile(r"\b[A-Za-z_]\w*\([^)]*\)")
_COMMAND_STARTS = {
    "coverage",
    "docker",
    "git",
    "make",
    "mypy",
    "npm",
    "npx",
    "pnpm",
    "poetry",
    "pytest",
    "python",
    "ruff",
    "tox",
    "uv",
    "uvx",
    "yarn",
}


@dataclass(frozen=True)
class _QueryCueCacheKey:
    normalized_query: str
    runtime_fingerprint: str
    schema_version: str
    interpreter_version: str


class QueryCueCache:
    """Small LRU cache for deterministic query cue interpretation."""

    def __init__(self, max_size: int = 128) -> None:
        if max_size < 1:
            raise ValueError("max_size must be at least 1")
        self.max_size = max_size
        self._items: OrderedDict[_QueryCueCacheKey, QueryCue] = OrderedDict()

    def get(
        self,
        query: str,
        runtime_context: CueRuntimeContext,
        *,
        schema_version: str = QUERY_SCHEMA_VERSION,
        interpreter_version: str = INTERPRETER_VERSION,
    ) -> QueryCue | None:
        key = self._key(
            query,
            runtime_context,
            schema_version=schema_version,
            interpreter_version=interpreter_version,
        )
        cue = self._items.get(key)
        if cue is None:
            return None
        self._items.move_to_end(key)
        return cue

    def set(
        self,
        query: str,
        runtime_context: CueRuntimeContext,
        cue: QueryCue,
        *,
        schema_version: str = QUERY_SCHEMA_VERSION,
        interpreter_version: str = INTERPRETER_VERSION,
    ) -> None:
        key = self._key(
            query,
            runtime_context,
            schema_version=schema_version,
            interpreter_version=interpreter_version,
        )
        self._items[key] = cue
        self._items.move_to_end(key)
        while len(self._items) > self.max_size:
            self._items.popitem(last=False)

    def clear(self) -> None:
        self._items.clear()

    def __len__(self) -> int:
        return len(self._items)

    def _key(
        self,
        query: str,
        runtime_context: CueRuntimeContext,
        *,
        schema_version: str,
        interpreter_version: str,
    ) -> _QueryCueCacheKey:
        return _QueryCueCacheKey(
            normalized_query=_normalize_query_key(query),
            runtime_fingerprint=runtime_context.fingerprint(),
            schema_version=schema_version,
            interpreter_version=interpreter_version,
        )


def should_interpret_query(query: str, runtime_context: CueRuntimeContext) -> bool:
    """Return whether a query is worth semantic interpretation beyond fast path."""
    del runtime_context
    normalized = _normalize_query_text(query)
    if not normalized:
        return False

    has_marker = _has_memory_recall_marker(normalized)
    if len(normalized.split()) < 3 and not has_marker:
        return False
    if _looks_like_file_path(normalized):
        return False
    if _looks_like_code_snippet(normalized):
        return False
    return has_marker or not _only_contains_command_or_test_invocation(normalized)


def build_fallback_query_cue(
    query: str,
    runtime_context: CueRuntimeContext,
    *,
    recall_need: RecallNeed | None = None,
) -> QueryCue:
    """Build a deterministic QueryCue without any live model interpretation."""
    from bourbon.memory.cues.models import QueryCue, RecallNeed, TimeHint

    normalized = _normalize_query_text(query)
    if recall_need is None:
        recall_need = (
            RecallNeed.WEAK
            if should_interpret_query(query, runtime_context)
            else RecallNeed.NONE
        )

    cue_phrases = []
    if normalized:
        cue_phrases.append(
            RetrievalCue(
                text=_truncate_cue_text(normalized),
                kind=CueKind.USER_PHRASE,
                source=CueSource.USER,
                confidence=1.0,
            )
        )

    return QueryCue(
        schema_version=QUERY_SCHEMA_VERSION,
        interpreter_version=INTERPRETER_VERSION,
        recall_need=recall_need,
        concepts=[],
        cue_phrases=cue_phrases,
        file_hints=_runtime_files(runtime_context),
        symbol_hints=_dedupe_strings(runtime_context.symbols),
        kind_hints=[],
        scope_hint=None,
        uncertainty=1.0,
        domain_concepts=[],
        time_hint=TimeHint.NONE,
        time_range=None,
        fallback_used=True,
        quality_flags=[CueQualityFlag.FALLBACK_USED],
    )


def _normalize_query_text(query: str) -> str:
    return " ".join(query.strip().split())


def _normalize_query_key(query: str) -> str:
    return _normalize_query_text(query).casefold()


def _has_memory_recall_marker(query: str) -> bool:
    normalized = query.casefold()
    if any(marker in normalized for marker in _CJK_MEMORY_RECALL_MARKERS):
        return True
    return any(
        re.search(rf"(?<![\w-]){re.escape(marker)}(?![\w-])", normalized)
        for marker in _ENGLISH_MEMORY_RECALL_MARKERS
    )


def _looks_like_file_path(query: str) -> bool:
    if any(char.isspace() for char in query):
        return False
    if "/" in query or "\\" in query:
        return True
    return bool(_PATH_EXTENSION_RE.fullmatch(query))


def _looks_like_code_snippet(query: str) -> bool:
    if "```" in query:
        return True
    if _CODE_LEADING_RE.search(query):
        return True
    code_chars = sum(query.count(char) for char in ("{", "}", "(", ")", ";"))
    if "\n" in query and code_chars:
        return True
    if _ASSIGNMENT_RE.search(query):
        return True
    return bool(_CALL_RE.search(query) and not query.endswith("?") and len(query.split()) <= 5)


def _only_contains_command_or_test_invocation(query: str) -> bool:
    tokens = query.split()
    if not tokens:
        return False
    command = tokens[0].casefold()
    if command not in _COMMAND_STARTS:
        return False
    if command in {"npm", "pnpm", "yarn"} and len(tokens) > 1:
        return tokens[1] in {"run", "test", "exec", "x"}
    return True


def _runtime_files(runtime_context: CueRuntimeContext) -> list[str]:
    files: list[str] = []
    if runtime_context.source_ref and runtime_context.source_ref.file_path:
        files.append(runtime_context.source_ref.file_path)
    files.extend(runtime_context.current_files)
    files.extend(runtime_context.touched_files)
    files.extend(runtime_context.modified_files)
    return _dedupe_strings(files)


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _truncate_cue_text(text: str) -> str:
    if len(text) <= MAX_QUERY_CUE_TEXT_LENGTH:
        return text
    return text[:MAX_QUERY_CUE_TEXT_LENGTH].rstrip()
