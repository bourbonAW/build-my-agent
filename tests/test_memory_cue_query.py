"""Tests for query-side memory cue interpretation."""

from __future__ import annotations

from pathlib import Path

from bourbon.memory.cues.engine import CueEngine
from bourbon.memory.cues.models import (
    CueKind,
    CueQualityFlag,
    CueSource,
    QueryCue,
    RecallNeed,
    TimeHint,
)
from bourbon.memory.cues.query import (
    INTERPRETER_VERSION,
    QUERY_SCHEMA_VERSION,
    QueryCueCache,
    build_fallback_query_cue,
    should_interpret_query,
)
from bourbon.memory.cues.runtime import CueRuntimeContext
from bourbon.memory.models import SourceRef


def _runtime(**overrides: object) -> CueRuntimeContext:
    values = {"workdir": Path("/repo")}
    values.update(overrides)
    return CueRuntimeContext(**values)


def test_should_interpret_query_skips_non_semantic_fast_path_inputs() -> None:
    runtime = _runtime()

    assert not should_interpret_query("", runtime)
    assert not should_interpret_query("cache", runtime)
    assert not should_interpret_query("src/bourbon/memory/store.py", runtime)
    assert not should_interpret_query("tests/test_memory.py::test_search", runtime)
    assert not should_interpret_query("def search(query): return query", runtime)
    assert not should_interpret_query("uv run pytest tests/test_memory.py -q", runtime)


def test_should_interpret_query_accepts_semantic_and_recall_queries() -> None:
    runtime = _runtime()

    assert should_interpret_query("what did we decide about memory prompt anchors", runtime)
    assert should_interpret_query("remember sandbox policy", runtime)
    assert should_interpret_query("上次 讨论 的 memory cue 方案", runtime)


def test_build_fallback_query_cue_preserves_query_and_runtime_hints() -> None:
    runtime = _runtime(
        current_files=["src/bourbon/memory/manager.py"],
        touched_files=["src/bourbon/memory/manager.py", " docs/memory.md "],
        modified_files=["tests/test_memory_manager.py"],
        symbols=[" MemoryManager ", "CueEngine", "MemoryManager"],
        source_ref=SourceRef(kind="file", file_path="src/bourbon/memory/models.py"),
    )

    cue = build_fallback_query_cue(
        "  what did we decide about memory cue fallback?  ",
        runtime,
    )

    assert isinstance(cue, QueryCue)
    assert cue.schema_version == QUERY_SCHEMA_VERSION
    assert cue.interpreter_version == INTERPRETER_VERSION
    assert cue.recall_need == RecallNeed.WEAK
    assert cue.concepts == []
    assert cue.cue_phrases[0].text == "what did we decide about memory cue fallback?"
    assert cue.cue_phrases[0].kind == CueKind.USER_PHRASE
    assert cue.cue_phrases[0].source == CueSource.USER
    assert cue.cue_phrases[0].confidence == 1.0
    assert cue.file_hints == [
        "src/bourbon/memory/models.py",
        "src/bourbon/memory/manager.py",
        "docs/memory.md",
        "tests/test_memory_manager.py",
    ]
    assert cue.symbol_hints == ["MemoryManager", "CueEngine"]
    assert cue.kind_hints == []
    assert cue.scope_hint is None
    assert cue.uncertainty == 1.0
    assert cue.time_hint == TimeHint.NONE
    assert cue.fallback_used is True
    assert cue.quality_flags == [CueQualityFlag.FALLBACK_USED]


def test_build_fallback_query_cue_accepts_explicit_recall_need() -> None:
    cue = build_fallback_query_cue(
        "src/bourbon/memory/store.py",
        _runtime(),
        recall_need=RecallNeed.NONE,
    )

    assert cue.recall_need == RecallNeed.NONE
    assert cue.fallback_used is True


def test_query_cue_cache_keys_on_normalized_query_runtime_and_versions() -> None:
    runtime = _runtime(current_files=["src/a.py"])
    changed_runtime = _runtime(current_files=["src/b.py"])
    cache = QueryCueCache(max_size=2)
    cue = build_fallback_query_cue("Remember memory anchors", runtime)

    cache.set("  Remember   MEMORY anchors  ", runtime, cue)

    assert cache.get("remember memory anchors", runtime) == cue
    assert cache.get("remember memory anchors", changed_runtime) is None
    assert (
        cache.get(
            "remember memory anchors",
            runtime,
            interpreter_version="query-cue-v2",
        )
        is None
    )
    assert (
        cache.get(
            "remember memory anchors",
            runtime,
            schema_version="cue.v2",
        )
        is None
    )


def test_query_cue_cache_evicts_least_recently_used_entry() -> None:
    runtime = _runtime()
    cache = QueryCueCache(max_size=2)
    first = build_fallback_query_cue("first memory query", runtime)
    second = build_fallback_query_cue("second memory query", runtime)
    third = build_fallback_query_cue("third memory query", runtime)

    cache.set("first memory query", runtime, first)
    cache.set("second memory query", runtime, second)
    assert cache.get("first memory query", runtime) == first
    cache.set("third memory query", runtime, third)

    assert cache.get("first memory query", runtime) == first
    assert cache.get("second memory query", runtime) is None
    assert cache.get("third memory query", runtime) == third


def test_cue_engine_interpret_query_uses_deterministic_fallback_and_cache() -> None:
    runtime = _runtime(current_files=["src/bourbon/memory/cues/query.py"])
    engine = CueEngine(query_cache=QueryCueCache(max_size=4))

    first = engine.interpret_query(
        "what did we decide about query cue caching",
        runtime_context=runtime,
    )
    second = engine.interpret_query(
        " what   did we decide about QUERY cue caching ",
        runtime_context=runtime,
    )
    skipped = engine.interpret_query(
        "uv run pytest tests/test_memory_cue_query.py -q",
        runtime_context=runtime,
    )

    assert first is second
    assert first.recall_need == RecallNeed.WEAK
    assert first.fallback_used is True
    assert first.quality_flags == [CueQualityFlag.FALLBACK_USED]
    assert first.file_hints == ["src/bourbon/memory/cues/query.py"]
    assert skipped.recall_need == RecallNeed.NONE
