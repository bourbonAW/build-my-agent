"""Small cue helpers for minimal memory search."""

from __future__ import annotations

import re
from collections.abc import Iterable

MAX_CUES = 12
_MAX_CUE_LENGTH = 80
_BACKTICK_RE = re.compile(r"`([^`]{1,120})`")
_QUOTE_RE = re.compile(r'"([^"]{1,120})"')
_PATH_RE = re.compile(r"(?<!\w)[\w./@+-]+\.[A-Za-z0-9]{1,8}(?!\w)")
_SENTENCE_RE = re.compile(r"[^.!?。！？\n]+")
_SEPARATOR_RE = re.compile(r"\s+(?:for|in|on|about|with|when|where|because)\s+")
_LEADING_CONTEXT_PATTERNS = (
    re.compile(r"^users?\s+(?:prefer|prefers|preferred|like|likes|want|wants|use|uses|need|needs)\s+"),
    re.compile(r"^prefer\s+"),
    re.compile(r"^use\s+"),
    re.compile(r"^(?:is|are|was|were)\s+"),
    re.compile(r"^we\s+decided\s+(?:that\s+)?"),
    re.compile(r"^decided\s+(?:that\s+)?"),
    re.compile(r"^remember\s+(?:that\s+)?"),
    re.compile(r"^always\s+(?:run|use|keep|write|prefer|choose|call)\s+"),
    re.compile(r"^always\s+"),
    re.compile(r"^never\s+(?:run|use|keep|write|prefer|choose|call)?\s*"),
)
_QUERY_PREFIX_RE = re.compile(
    r"^(?:where|what|which|how|why|when)\s+"
    r"(?:(?:is|are|was|were|did|do|does|should|must)\s+)?"
)
_TRAILING_CLAUSE_RE = re.compile(
    r"\s+(?:are|is|was|were|will be|should be|must be)\s+"
)
_MODAL_CLAUSE_RE = re.compile(r"\s+(?:must|should|needs? to|has to)\s+")
_LEADING_VERB_RE = re.compile(
    r"^(?:emit|use|run|keep|write|prefer|choose|call|store|rebuild|delete|create)\s+"
    r"(?:an?\s+|the\s+)?"
)
_QUERY_SUFFIX_WORDS = {
    "decision",
    "memory",
    "policy",
    "preference",
    "requirement",
}
_GENERIC_TOPIC_SUFFIXES = {
    "component",
    "components",
    "event",
    "events",
    "panel",
    "panels",
    "screen",
    "screens",
    "setting",
    "settings",
}
_LOW_VALUE_WORDS = {
    "a",
    "after",
    "an",
    "and",
    "for",
    "in",
    "of",
    "on",
    "or",
    "the",
    "to",
    "when",
    "where",
    "with",
}


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


def _normalize_phrase_text(value: str) -> str:
    text = value.casefold()
    text = text.replace("`", " ").replace('"', " ").replace("'", " ")
    text = re.sub(r"[^a-z0-9_./@+-]+", " ", text)
    return _clean_term(text).strip(" .:/-")


def _strip_leading_context(value: str) -> str:
    text = value
    for pattern in _LEADING_CONTEXT_PATTERNS:
        updated = pattern.sub("", text, count=1)
        if updated != text:
            return updated.strip()
    return text


def _trim_query_suffix(value: str) -> str:
    tokens = value.split()
    while len(tokens) > 2 and tokens[-1] in _QUERY_SUFFIX_WORDS:
        tokens.pop()
    return " ".join(tokens)


def _is_useful_phrase(value: str) -> bool:
    tokens = value.split()
    if tokens and all(token in _LOW_VALUE_WORDS for token in tokens):
        return False
    if len(tokens) >= 2:
        return True
    return bool(tokens and any(char in tokens[0] for char in ("_", "-", ".", "/")))


def _add_phrase(phrases: list[str], value: str) -> None:
    phrase = _normalize_phrase_text(value)
    if _is_useful_phrase(phrase):
        phrases.append(phrase)


def _has_content_token(value: str) -> bool:
    tokens = _normalize_phrase_text(value).split()
    return any(token not in _LOW_VALUE_WORDS for token in tokens)


def _topic_label(value: str) -> str:
    tokens = _normalize_phrase_text(value).split()
    while len(tokens) > 1 and tokens[-1] in _GENERIC_TOPIC_SUFFIXES:
        tokens.pop()
    return " ".join(tokens[:4])


def _source_label(value: str) -> str:
    first_token = next(iter(_normalize_phrase_text(value).split()), "")
    if not first_token:
        return ""
    return re.split(r"[_./+-]+", first_token)[0]


def _phrase_variants(text: str, *, for_query: bool) -> list[str]:
    phrases: list[str] = []
    if ":" in text:
        left, right = text.split(":", 1)
        phrases.extend(_phrase_variants(left, for_query=for_query))
        phrases.extend(_phrase_variants(right, for_query=for_query))
        return phrases

    base = _normalize_phrase_text(text)
    if not base:
        return phrases
    if for_query:
        base = _QUERY_PREFIX_RE.sub("", base, count=1).strip()
        base = _trim_query_suffix(base)
    is_preference = bool(
        re.match(
            r"^(?:users?\s+)?(?:prefer|prefers|preferred|like|likes|want|wants|use|uses|need|needs)\s+",
            base,
        )
    )
    is_decision = bool(re.match(r"^(?:we\s+)?decided\s+(?:that\s+)?", base))
    base = _strip_leading_context(base)
    if not base:
        return phrases

    if ":" in base:
        left, right = base.split(":", 1)
        _add_phrase(phrases, left)
        base = right.strip() or left

    clause_parts = _TRAILING_CLAUSE_RE.split(base, maxsplit=1)
    if len(clause_parts) == 2:
        _add_phrase(phrases, clause_parts[0])
        if is_decision:
            _add_phrase(phrases, f"{_topic_label(clause_parts[0])} decision")
        base = clause_parts[0]

    modal_parts = _MODAL_CLAUSE_RE.split(base, maxsplit=1)
    if len(modal_parts) == 2:
        _add_phrase(phrases, modal_parts[0])
        requirement = _LEADING_VERB_RE.sub("", modal_parts[1], count=1)
        _add_phrase(phrases, requirement)
        requirement_topic = _topic_label(requirement)
        source_topic = _source_label(modal_parts[0])
        _add_phrase(phrases, f"{requirement_topic} requirement")
        if source_topic and requirement_topic:
            _add_phrase(phrases, f"{source_topic} {requirement_topic}")
        base = modal_parts[0]

    separators = _SEPARATOR_RE.split(base)
    if len(separators) > 1:
        for part in separators:
            _add_phrase(phrases, part)
        preference_topic = _topic_label(separators[-1])
        if is_preference and _has_content_token(preference_topic):
            _add_phrase(phrases, f"{preference_topic} preference")
    else:
        _add_phrase(phrases, base)
        preference_topic = _topic_label(base)
        if is_preference and _has_content_token(preference_topic):
            _add_phrase(phrases, f"{preference_topic} preference")
    return phrases


def _extract_plain_phrases(text: str, *, for_query: bool = False) -> list[str]:
    phrases: list[str] = []
    plain_text = _PATH_RE.sub(" ", _QUOTE_RE.sub(" ", _BACKTICK_RE.sub(" ", text)))
    for match in _SENTENCE_RE.finditer(plain_text):
        sentence = match.group(0).strip()
        if not sentence:
            continue
        phrases.extend(_phrase_variants(sentence, for_query=for_query))
        if len(phrases) >= MAX_CUES:
            break
    return phrases


def generate_cues(content: str) -> tuple[str, ...]:
    """Generate write-time cues from explicit hints and simple retrieval phrases."""
    return normalize_cues((*_extract_terms(content), *_extract_plain_phrases(content)))


def expand_query_terms(query: str) -> tuple[str, ...]:
    """Return the normalized query plus explicit and derived retrieval terms."""
    base = _clean_term(query)
    if not base:
        return ()
    explicit_terms = _extract_terms(query)
    if explicit_terms:
        return normalize_cues((base, *explicit_terms))
    return normalize_cues((base, *_extract_plain_phrases(query, for_query=True)))
