# Bourbon Memory Local Semantic Index Design

**Date:** 2026-05-07
**Status:** Approved for implementation
**Scope:** Add a local dense semantic retrieval channel to the minimal Bourbon memory model without changing the authoritative memory record schema.

## Context

Bourbon memory has just been reduced to a minimal file-first model:

```python
MemoryRecord(id, target, content, created_at, cues)
```

The current search path uses content substring matching plus lightweight cue matching. That keeps the model maintainable, but it still misses paraphrases and mixed Chinese/English queries such as:

```text
record: User prefers dark mode for UI components.
query: 用户喜欢什么界面主题？
```

The next step is to add a dense semantic retrieval channel. This must not undo the recent cleanup by storing embedding metadata on records, restoring cue engine schemas, or replacing inspectable file-first memory with an opaque vector database.

## Goals

- Improve recall for paraphrase and Chinese/English mixed queries.
- Keep Markdown memory files as the only source of truth.
- Store dense vectors only in a rebuildable local derived index.
- Keep exact content/cue matches explainable and stronger than semantic matches.
- Use a real local embedding model, not a hash or fake embedding provider.
- Keep `memory_write` and `memory_search` user-facing schemas stable.
- Degrade safely to current content/cue search if semantic indexing is unavailable.

## Non-Goals

- No embedding fields on `MemoryRecord`.
- No external vector service such as Chroma, Qdrant, Redis, or Neo4j.
- No SQLite vector extension in the MVP.
- No LLM-generated query cue object.
- No automatic memory extraction or background daemon.
- No recency boost in the first ranking version.
- No claim that vector similarity is authoritative provenance.

## Core Decision

Use a local SQLite derived index with:

- a small records table,
- an FTS5 lexical table,
- a vector table storing `float32` vectors as BLOBs,
- Python exact cosine scan for dense candidates,
- a local FastEmbed embedding provider.

The default model is optimized for Chinese/English mixed memory:

```toml
[memory.semantic]
enabled = true
provider = "fastembed"
model = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
top_k = 16
min_similarity = 0.25
```

FastEmbed is the only runtime provider in the MVP. Tests may use injected fake providers, but production code must not include a hash embedding fallback.

## Architecture

```text
MemoryManager
  ├─ MemoryStore          # authoritative Markdown records + MEMORY.md
  ├─ MemorySearchIndex    # derived SQLite FTS + dense vector index
  └─ MemoryRetriever      # hybrid candidate generation and fusion
```

`MemoryStore` continues to own reads, writes, deletes, and `MEMORY.md` rendering. It does not know about embedding models.

`MemorySearchIndex` lives at:

```text
~/.bourbon/projects/{project}/memory/search_index.sqlite
```

The file can be deleted and rebuilt from `MemoryStore.list_records()`.

`MemoryRetriever` is the search path. It combines:

- exact content/cue matches,
- SQLite FTS lexical candidates,
- dense vector candidates.

It returns the existing `MemorySearchResult` shape.

## Embedding Provider

The provider interface stays small:

```python
class EmbeddingProvider:
    name: str
    model: str
    dimensions: int

    def embed_passages(self, texts: list[str]) -> list[tuple[float, ...]]:
        ...

    def embed_query(self, text: str) -> tuple[float, ...]:
        ...
```

`embed_passages()` and `embed_query()` are separate so later models that require query/passsage prefixes can be supported without changing the retriever.

`FastEmbedProvider` imports FastEmbed lazily. If the package is missing, the model cannot be loaded, or model download fails, semantic indexing is disabled for that operation and search falls back to content/cue search.

## Search Text

Dense vectors are generated from derived text:

```text
{record.content}

cues:
{cue1}
{cue2}
...
```

This text is not a new record field. It is stored in SQLite only to support index inspection, hashing, FTS, and rebuild checks.

Search text version starts as:

```text
memory-search-text-v1
```

Changing the render format requires index rebuild.

## SQLite Schema

```sql
CREATE TABLE memory_index_meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE memory_index_records (
  memory_id TEXT PRIMARY KEY,
  target TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  created_at TEXT NOT NULL,
  search_text TEXT NOT NULL
);

CREATE VIRTUAL TABLE memory_fts USING fts5(
  memory_id UNINDEXED,
  search_text,
  tokenize='unicode61'
);

CREATE TABLE memory_vectors (
  memory_id TEXT PRIMARY KEY,
  provider TEXT NOT NULL,
  model TEXT NOT NULL,
  dimensions INTEGER NOT NULL,
  vector BLOB NOT NULL
);
```

Index metadata records:

```text
schema_version = "memory-search-index-v1"
search_text_version = "memory-search-text-v1"
embedding_provider = "fastembed"
embedding_model = configured model
embedding_dimensions = detected dimension
```

If schema, search text version, provider, model, or dimensions differ from the configured runtime, the index is rebuilt.

## Lifecycle

Write:

```text
MemoryManager.write()
  -> generate_cues(content)
  -> MemoryStore.write_record(record)
  -> MemorySearchIndex.upsert(record)
```

Delete:

```text
MemoryManager.delete()
  -> MemoryStore.delete_record(memory_id)
  -> MemorySearchIndex.delete(memory_id)
```

Search:

```text
MemoryManager.search(query, target, limit)
  -> expand_query_terms(query)
  -> MemoryRetriever.search(...)
  -> MemorySearchResult[]
```

If the index is missing, stale, corrupt, or unreadable, Bourbon attempts one rebuild from Markdown records. If rebuild fails, search uses the current content/cue scan path.

## Ranking

The first ranker is intentionally simple:

```text
score =
  exact_score
  + fts_score
  + semantic_score
```

Initial behavior:

- exact content/cue candidates are strongest,
- FTS lexical candidates are medium strength,
- semantic candidates are medium-low unless similarity is high,
- semantic candidates below `min_similarity` are ignored,
- no recency boost.

Vector similarity cannot bypass `target` filtering.

`why_matched` stays compact:

```text
matched cue: dark mode
matched content: pytest
matched semantic: 0.72
matched content + semantic
```

## Configuration

Add nested memory semantic config:

```python
@dataclass
class MemorySemanticConfig:
    enabled: bool = True
    provider: str = "fastembed"
    model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    top_k: int = 16
    min_similarity: float = 0.25
```

Existing minimal memory config remains intact. `Config.from_dict()` and `Config.to_dict()` must support the nested `[memory.semantic]` TOML shape.

## Dependency Boundary

FastEmbed is the local dense embedding dependency. It belongs in a `semantic` optional dependency group, not the base install. It should be imported only inside the provider implementation so the memory package remains importable even when semantic dependencies are unavailable.

No code path should download a model during unit tests.

## Evaluation

Extend memory retrieval eval variants:

```text
content_only
content_plus_cues
expanded_query_plus_cues
hybrid_semantic
```

Add Chinese/English mixed cases:

```text
record: User prefers dark mode for UI components.
query: 用户喜欢什么界面主题？

record: Prefer append-only memory records.
query: memory 记录应该能不能原地修改？
```

Acceptance gates:

```text
hybrid_semantic recall_at_3 > expanded_query_plus_cues
target leakage = 0
index deletion triggers rebuild
semantic unavailable falls back to content/cue search
```

## Failure Policy

Semantic indexing is a quality improvement, not a correctness dependency.

Failures that must fall back:

- FastEmbed package missing,
- model load/download failure,
- embedding call failure,
- SQLite corruption,
- FTS syntax failure,
- vector dimension mismatch.

Fallback behavior:

- return content/cue search results,
- keep `memory_search` successful,
- do not mutate memory records,
- log debug information if logging is enabled.

## Risks

| Risk | Mitigation |
|---|---|
| Embedding dependency makes base install heavier | Keep provider lazy and make failure non-fatal |
| Vector result feels like a black box | Keep exact/cue explanations and compact semantic scores |
| Chinese segmentation hurts FTS | Dense channel handles Chinese/English semantic recall |
| Model version changes produce stale vectors | Store provider/model/dimensions in index meta and rebuild |
| Index diverges from Markdown | Treat SQLite as derived; rebuild from `MemoryStore.list_records()` |

## Future Work

- Add `sqlite-vec` backend only after exact scan becomes too slow.
- Add a second provider for `sentence-transformers` if FastEmbed model coverage is insufficient.
- Add MMR only after semantic results become redundant.
- Add retrieval telemetry after the basic path is stable.
