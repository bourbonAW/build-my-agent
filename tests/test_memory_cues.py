"""Tests for minimal memory cue helpers."""

from __future__ import annotations

from bourbon.memory.cues import MAX_CUES, expand_query_terms, generate_cues, normalize_cues


def test_normalize_cues_trims_deduplicates_and_limits() -> None:
    values = [" dark mode ", "", "dark mode", "ui", *[f"term-{index}" for index in range(20)]]

    cues = normalize_cues(values)

    assert cues[0:2] == ("dark mode", "ui")
    assert len(cues) == MAX_CUES
    assert "" not in cues


def test_generate_cues_extracts_backticks_quotes_and_paths() -> None:
    content = 'Use `dark mode` for "settings panels" in src/ui/theme.py.'

    cues = generate_cues(content)

    assert cues == ("dark mode", "settings panels", "src/ui/theme.py")


def test_generate_cues_returns_empty_tuple_for_plain_content() -> None:
    assert generate_cues("User prefers concise replies.") == ()


def test_expand_query_terms_returns_normalized_query_and_extracted_terms() -> None:
    terms = expand_query_terms('Find `dark mode` memory in src/ui/theme.py')

    assert terms == (
        "Find `dark mode` memory in src/ui/theme.py",
        "dark mode",
        "src/ui/theme.py",
    )
