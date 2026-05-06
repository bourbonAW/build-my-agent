# Bourbon Memory Retrieval Handoff Phase 5 Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce the retrieval/ranking handoff spec that consumes `MemoryCueMetadata` and `QueryCue` without binding Bourbon prematurely to embedding-first retrieval.

**Architecture:** This phase is design-only. It defines the next retrieval layer as a separate component below `MemoryManager.search()` and above `MemoryStore`, with local FTS/BM25 plus cue-aware fusion as the recommended first implementation path.

**Tech Stack:** Markdown design spec, existing memory/cue docs, Phase 4 eval thresholds.

---

## Implementation Status

**Phase:** Phase 5

**Status:** Completed

**Started:** 2026-05-06

**Completed:** 2026-05-06

**Verification:** Passed

**Task Progress:**

- [x] Task 1: Write retrieval/ranking handoff spec
- [x] Task 2: Decide backend sequencing
- [x] Task 3: Define eval gates and rollout boundary
- [x] Task 4: Status update

**Completion Notes:**

- 2026-05-06: Added `docs/superpowers/specs/2026-05-06-bourbon-memory-retrieval-ranking-handoff-design.md`.
- 2026-05-06: Recommended backend sequence: local FTS/BM25 first, cue-aware fusion second, embedding/HyDE-derived semantic text later.
- 2026-05-06: Verified the spec has no placeholder markers via `rg -n "TBD|TODO|PLACEHOLDER|待定" docs/superpowers/specs/2026-05-06-bourbon-memory-retrieval-ranking-handoff-design.md`.

---

## Notes

- Phase 5 does not implement retrieval code.
- Phase 5 intentionally keeps CueEngine as a representation layer, not a ranker.
