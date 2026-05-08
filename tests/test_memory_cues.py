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

    assert cues[:3] == ("dark mode", "settings panels", "src/ui/theme.py")


def test_generate_cues_derives_search_phrases_from_plain_preference() -> None:
    cues = generate_cues("User prefers dark mode for UI components.")

    assert "dark mode" in cues
    assert "ui components" in cues
    assert "ui preference" in cues


def test_generate_cues_derives_rule_and_decision_phrases() -> None:
    rule_cues = generate_cues("Always run focused tests first.")
    decision_cues = generate_cues(
        "We decided append-only memory records are easier to maintain."
    )

    assert "focused tests first" in rule_cues
    assert "append-only memory records" in decision_cues
    assert "append-only memory records decision" in decision_cues


def test_generate_cues_derives_requirement_phrase_from_modal_rule() -> None:
    cues = generate_cues("memory_write must emit an audit event.")

    assert "audit event" in cues
    assert "audit requirement" in cues
    assert "memory audit" in cues


def test_generate_cues_preserves_label_phrases() -> None:
    cues = generate_cues("Index rebuild: MEMORY index updates after write and delete.")

    assert "index rebuild" in cues


def test_expand_query_terms_returns_normalized_query_and_extracted_terms() -> None:
    terms = expand_query_terms('Find `dark mode` memory in src/ui/theme.py')

    assert terms == (
        "Find `dark mode` memory in src/ui/theme.py",
        "dark mode",
        "src/ui/theme.py",
    )


def test_expand_query_terms_derives_retrieval_phrases_from_plain_query() -> None:
    terms = expand_query_terms("where is dark mode preference")

    assert terms[0] == "where is dark mode preference"
    assert "dark mode" in terms
