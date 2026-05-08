# Bourbon Memory Local Semantic Index Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a local FastEmbed-backed semantic search channel to Bourbon memory while keeping Markdown memory records as the source of truth.

**Architecture:** Add a lazy FastEmbed provider, a rebuildable SQLite `MemorySearchIndex`, and a `MemoryRetriever` that fuses exact content/cue matches, FTS lexical matches, and dense vector candidates. The existing `memory_search` tool schema remains unchanged and semantic failures fall back to current content/cue search.

**Tech Stack:** Python 3.12, sqlite3/FTS5, FastEmbed, dataclasses, pytest, Ruff, Mypy.

---

## File Structure

- Create `src/bourbon/memory/embeddings.py`: embedding provider protocol, lazy `FastEmbedProvider`, vector packing/unpacking, cosine similarity.
- Create `src/bourbon/memory/search_index.py`: derived SQLite index, schema management, FTS search, vector upsert/delete/rebuild/search.
- Create `src/bourbon/memory/retriever.py`: hybrid retrieval over `MemoryStore` and `MemorySearchIndex`.
- Modify `src/bourbon/config.py`: add nested `MemorySemanticConfig` and TOML round trip support.
- Modify `src/bourbon/memory/manager.py`: initialize search index/retriever and use hybrid search with fallback.
- Modify `pyproject.toml`: add FastEmbed dependency.
- Modify `evals/memory_retrieval_provider.py`: add `hybrid_semantic` deterministic eval path using fixture vectors, not real model downloads.
- Modify `evals/fixtures/memory_retrieval/retrieval-smoke.json`: add Chinese/English mixed semantic cases.
- Add tests:
  - `tests/test_memory_embeddings.py`
  - `tests/test_memory_search_index.py`
  - `tests/test_memory_retriever.py`
  - update `tests/test_memory_config.py`
  - update `tests/test_memory_manager.py`
  - update `tests/test_memory_retrieval_provider.py`

## Task 1: Configuration And Embedding Provider Boundary

**Files:**
- Modify: `src/bourbon/config.py`
- Create: `src/bourbon/memory/embeddings.py`
- Modify: `pyproject.toml`
- Test: `tests/test_memory_config.py`
- Test: `tests/test_memory_embeddings.py`

- [x] **Step 1: Write failing config tests**

Add to `tests/test_memory_config.py`:

```python
def test_memory_semantic_config_defaults() -> None:
    cfg = MemoryConfig()

    assert cfg.semantic.enabled is True
    assert cfg.semantic.provider == "fastembed"
    assert cfg.semantic.model == "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    assert cfg.semantic.top_k == 16
    assert cfg.semantic.min_similarity == 0.25


def test_config_from_dict_memory_semantic_fields() -> None:
    cfg = Config.from_dict(
        {
            "memory": {
                "semantic": {
                    "enabled": False,
                    "provider": "fastembed",
                    "model": "custom/model",
                    "top_k": 4,
                    "min_similarity": 0.4,
                }
            }
        }
    )

    assert cfg.memory.semantic.enabled is False
    assert cfg.memory.semantic.provider == "fastembed"
    assert cfg.memory.semantic.model == "custom/model"
    assert cfg.memory.semantic.top_k == 4
    assert cfg.memory.semantic.min_similarity == 0.4
```

Update `test_config_to_dict_memory_minimal_fields()` expected memory dict to include:

```python
"semantic": {
    "enabled": True,
    "provider": "fastembed",
    "model": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    "top_k": 16,
    "min_similarity": 0.25,
},
```

- [x] **Step 2: Write failing embedding helper tests**

Create `tests/test_memory_embeddings.py`:

```python
from __future__ import annotations

import math
import struct

import pytest

from bourbon.memory.embeddings import (
    EmbeddingUnavailableError,
    FastEmbedProvider,
    cosine_similarity,
    pack_vector,
    unpack_vector,
)


def test_pack_vector_round_trips_float32_values() -> None:
    raw = (0.25, -0.5, 1.0)
    blob = pack_vector(raw)

    assert isinstance(blob, bytes)
    assert len(blob) == 12
    assert unpack_vector(blob, 3) == pytest.approx(raw)


def test_unpack_vector_rejects_dimension_mismatch() -> None:
    blob = struct.pack("<2f", 1.0, 2.0)

    with pytest.raises(ValueError, match="Vector blob has 2 dimensions; expected 3"):
        unpack_vector(blob, 3)


def test_cosine_similarity() -> None:
    assert cosine_similarity((1.0, 0.0), (1.0, 0.0)) == pytest.approx(1.0)
    assert cosine_similarity((1.0, 0.0), (0.0, 1.0)) == pytest.approx(0.0)
    assert math.isclose(cosine_similarity((0.0, 0.0), (1.0, 0.0)), 0.0)


def test_fastembed_provider_import_is_lazy(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_import(name: str):
        raise ImportError(name)

    provider = FastEmbedProvider(model="local/model")
    monkeypatch.setattr(provider, "_load_model", fail_import)

    with pytest.raises(EmbeddingUnavailableError):
        provider.embed_query("hello")
```

- [x] **Step 3: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/test_memory_config.py tests/test_memory_embeddings.py -q
```

Expected: FAIL because semantic config and `bourbon.memory.embeddings` do not exist.

- [x] **Step 4: Implement config and embedding helpers**

Implement `MemorySemanticConfig`, `MemoryConfig.from_dict()`, `MemoryConfig.to_dict()`, and update `Config.from_dict()` / `Config.to_dict()`.

Create `src/bourbon/memory/embeddings.py` with:

```python
class EmbeddingUnavailable(RuntimeError):
    ...


class EmbeddingProvider(Protocol):
    name: str
    model: str
    dimensions: int | None

    def embed_passages(self, texts: list[str]) -> list[tuple[float, ...]]:
        ...

    def embed_query(self, text: str) -> tuple[float, ...]:
        ...
```

`FastEmbedProvider` must lazily import `fastembed.TextEmbedding`, cache the model object, set dimensions after the first embedding, and convert returned vectors to tuples of floats.

Vector helpers:

```python
pack_vector(vector: Sequence[float]) -> bytes
unpack_vector(blob: bytes, dimensions: int) -> tuple[float, ...]
cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float
```

Add FastEmbed to the `semantic` optional dependency group, not the base install:

```toml
[project.optional-dependencies]
semantic = [
    "fastembed>=0.6.0",
]
```

- [x] **Step 5: Run focused tests**

Run:

```bash
uv run pytest tests/test_memory_config.py tests/test_memory_embeddings.py -q
uv run ruff check src/bourbon/config.py src/bourbon/memory/embeddings.py tests/test_memory_config.py tests/test_memory_embeddings.py
```

Expected: PASS.

- [x] **Step 6: Commit**

```bash
git add pyproject.toml src/bourbon/config.py src/bourbon/memory/embeddings.py tests/test_memory_config.py tests/test_memory_embeddings.py
git commit -m "feat(memory): add semantic embedding provider boundary"
```

## Task 2: SQLite Search Index

**Files:**
- Create: `src/bourbon/memory/search_index.py`
- Test: `tests/test_memory_search_index.py`

- [x] **Step 1: Write failing index tests**

Create `tests/test_memory_search_index.py` with fake provider classes that return fixed vectors. Test:

- `upsert()` creates `search_index.sqlite` and stores search text/vector.
- `search_fts()` returns lexical candidates filtered by target.
- `search_vector()` returns cosine-ranked candidates above `min_similarity`.
- `delete()` removes all rows for one memory id.
- `rebuild()` clears stale rows and indexes current records.

- [x] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/test_memory_search_index.py -q
```

Expected: FAIL because `bourbon.memory.search_index` does not exist.

- [x] **Step 3: Implement `MemorySearchIndex`**

Create:

```python
@dataclass(frozen=True)
class IndexCandidate:
    memory_id: str
    channel: Literal["fts", "semantic"]
    score: float
    reason: str


class MemorySearchIndex:
    def __init__(self, index_path: Path, provider: EmbeddingProvider, *, top_k: int, min_similarity: float) -> None:
        ...

    def upsert(self, record: MemoryRecord) -> None:
        ...

    def delete(self, memory_id: str) -> None:
        ...

    def rebuild(self, records: Iterable[MemoryRecord]) -> None:
        ...

    def search_fts(self, query: str, *, target: str | None, limit: int) -> list[IndexCandidate]:
        ...

    def search_vector(self, query: str, *, target: str | None, limit: int) -> list[IndexCandidate]:
        ...
```

Use WAL, `PRAGMA busy_timeout=5000`, schema version metadata, `pack_vector()`/`unpack_vector()`, and `render_search_text(record)`.

- [x] **Step 4: Run focused tests**

Run:

```bash
uv run pytest tests/test_memory_search_index.py -q
uv run ruff check src/bourbon/memory/search_index.py tests/test_memory_search_index.py
```

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add src/bourbon/memory/search_index.py tests/test_memory_search_index.py
git commit -m "feat(memory): add sqlite semantic search index"
```

## Task 3: Hybrid Retriever And Manager Integration

**Files:**
- Create: `src/bourbon/memory/retriever.py`
- Modify: `src/bourbon/memory/manager.py`
- Test: `tests/test_memory_retriever.py`
- Test: `tests/test_memory_manager.py`

- [x] **Step 1: Write failing retriever tests**

Create `tests/test_memory_retriever.py` to verify:

- exact cue/content matches outrank semantic-only matches,
- semantic-only mixed Chinese/English query can retrieve the expected memory with a fake provider,
- target filtering applies to exact and semantic channels,
- index failure falls back to exact store search.

- [x] **Step 2: Write failing manager integration test**

Add to `tests/test_memory_manager.py`:

```python
def test_search_uses_semantic_retriever_when_available(tmp_path: Path, audit: FakeAudit) -> None:
    manager = MemoryManager(
        config=MemoryConfig(storage_dir=str(tmp_path)),
        project_key="proj",
        workdir=tmp_path,
        audit=audit,  # type: ignore[arg-type]
    )
    record = manager.write(
        MemoryRecordDraft(target="user", content="User prefers dark mode for UI components."),
        actor=MemoryActor(kind="user", session_id="ses_1"),
    )

    results = manager.search("用户喜欢什么界面主题？", target="user")

    assert results[0].id == record.id
```

Use monkeypatch or provider injection if real FastEmbed should not load in the unit test.

- [x] **Step 3: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/test_memory_retriever.py tests/test_memory_manager.py -q
```

Expected: FAIL because `MemoryRetriever` is missing and manager still uses only store search.

- [x] **Step 4: Implement retriever and manager integration**

`MemoryRetriever.search()` should:

- expand exact terms using existing manager-provided terms,
- collect exact store results,
- collect FTS candidates,
- collect vector candidates,
- merge by memory id,
- apply target hard filter,
- return `MemorySearchResult` up to limit.

`MemoryManager` should:

- create `MemorySearchIndex` and `MemoryRetriever` when semantic config is enabled and provider is available,
- call `index.upsert(record)` after store write, swallowing semantic index failures,
- call `index.delete(memory_id)` after store delete, swallowing semantic index failures,
- use retriever in search when available,
- fall back to the existing term loop when unavailable or failing.

- [x] **Step 5: Run focused tests**

Run:

```bash
uv run pytest tests/test_memory_retriever.py tests/test_memory_manager.py tests/test_memory_store.py -q
uv run ruff check src/bourbon/memory/retriever.py src/bourbon/memory/manager.py tests/test_memory_retriever.py tests/test_memory_manager.py
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/bourbon/memory/retriever.py src/bourbon/memory/manager.py tests/test_memory_retriever.py tests/test_memory_manager.py
git commit -m "feat(memory): use hybrid semantic retriever"
```

## Task 4: Retrieval Eval Variant

**Files:**
- Modify: `evals/memory_retrieval_provider.py`
- Modify: `evals/fixtures/memory_retrieval/retrieval-smoke.json`
- Modify: `tests/test_memory_retrieval_provider.py`

- [x] **Step 1: Write failing eval test**

Add a test proving `hybrid_semantic` improves a mixed Chinese/English query fixture that `expanded_query_plus_cues` misses.

- [x] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/test_memory_retrieval_provider.py -q
```

Expected: FAIL because provider output lacks `hybrid_semantic`.

- [x] **Step 3: Add deterministic eval semantic scoring**

Do not load FastEmbed in eval tests. Add fixture-local `semantic_terms` or `semantic_neighbors` so the provider can deterministically simulate semantic recall for mixed-language cases. The eval must measure retrieval pipeline behavior, not model download behavior.

- [x] **Step 4: Run eval tests and smoke**

Run:

```bash
uv run pytest tests/test_memory_retrieval_provider.py -q
uv run python -c "import json; from evals.memory_retrieval_provider import call_api; out = call_api('', {}, {'vars': {'fixture': 'memory_retrieval/retrieval-smoke.json'}})['output']; print(json.loads(out)['metrics'])"
```

Expected: PASS and printed metrics include `hybrid_semantic`.

- [ ] **Step 5: Commit**

```bash
git add evals/memory_retrieval_provider.py evals/fixtures/memory_retrieval/retrieval-smoke.json tests/test_memory_retrieval_provider.py
git commit -m "test(memory): add hybrid semantic retrieval eval"
```

## Task 5: Verification And Documentation Sync

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify any docs that describe current memory search behavior.

- [x] **Step 1: Update docs**

Document that memory search is now hybrid:

```text
Markdown records are source of truth. search_index.sqlite is a rebuildable local semantic index using FastEmbed when available. Search falls back to content/cue matching when semantic indexing is unavailable.
```

- [x] **Step 2: Run focused memory tests**

Run:

```bash
uv run pytest tests/test_memory*.py -q
```

Expected: PASS.

- [x] **Step 3: Run static checks**

Run:

```bash
uv run ruff check src/bourbon/memory src/bourbon/config.py evals/memory_retrieval_provider.py tests/test_memory*.py
uv run mypy src/bourbon/memory src/bourbon/config.py
```

Expected: PASS.

- [x] **Step 4: Run full test suite**

Run:

```bash
uv run pytest -q
```

Expected: PASS.

- [ ] **Step 5: Commit final docs or cleanup**

If documentation or cleanup changed after prior commits:

```bash
git add README.md AGENTS.md docs/superpowers/specs/2026-05-07-bourbon-memory-local-semantic-index-design.md docs/superpowers/plans/2026-05-07-bourbon-memory-local-semantic-index.md
git commit -m "docs(memory): describe local semantic search index"
```

## Self-Review

- Spec coverage: config, provider, SQLite index, lifecycle, fallback, fusion, eval, and docs each have a task.
- Placeholder scan: no placeholder markers remain.
- Type consistency: provider, index, and retriever names are stable across tasks.
