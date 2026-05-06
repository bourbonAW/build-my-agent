"""Record-side cue generation."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from bourbon.memory.cues.models import (
    CueGenerationStatus,
    CueKind,
    CueQualityFlag,
    CueSource,
    MemoryConcept,
    MemoryCueMetadata,
    RetrievalCue,
)
from bourbon.memory.cues.runtime import CueRuntimeContext

if TYPE_CHECKING:
    from bourbon.memory.cues.models import QueryCue
    from bourbon.memory.cues.query import QueryCueCache
    from bourbon.memory.models import MemoryRecordDraft

GENERATOR_VERSION = "record-cue-v1"
SCHEMA_VERSION = "cue.v1"


class CueEngine:
    """Generate deterministic record-side cues from runtime evidence and heuristics."""

    def __init__(self, *, query_cache: QueryCueCache | None = None) -> None:
        from bourbon.memory.cues.query import QueryCueCache

        self._query_cache = query_cache or QueryCueCache()

    def interpret_query(
        self,
        query: str,
        *,
        runtime_context: CueRuntimeContext,
    ) -> QueryCue:
        """Interpret a user query into a deterministic fallback query cue."""
        from bourbon.memory.cues.models import RecallNeed
        from bourbon.memory.cues.query import build_fallback_query_cue, should_interpret_query

        cached = self._query_cache.get(query, runtime_context)
        if cached is not None:
            return cached

        recall_need = (
            RecallNeed.WEAK
            if should_interpret_query(query, runtime_context)
            else RecallNeed.NONE
        )
        cue = build_fallback_query_cue(
            query,
            runtime_context,
            recall_need=recall_need,
        )
        self._query_cache.set(query, runtime_context, cue)
        return cue

    def generate_for_record(
        self,
        draft: MemoryRecordDraft,
        *,
        runtime_context: CueRuntimeContext,
    ) -> MemoryCueMetadata:
        content = draft.content.strip()
        if not content:
            return MemoryCueMetadata(
                schema_version=SCHEMA_VERSION,
                generator_version=GENERATOR_VERSION,
                concepts=[MemoryConcept.PROJECT_CONTEXT],
                retrieval_cues=[
                    RetrievalCue(
                        text="Untitled memory",
                        kind=CueKind.USER_PHRASE,
                        source=CueSource.USER,
                        confidence=1.0,
                    )
                ],
                files=[],
                symbols=[],
                generation_status=CueGenerationStatus.FAILED,
                generated_at=datetime.now(UTC),
                quality_flags=[CueQualityFlag.LLM_GENERATION_FAILED],
            )

        files = self._runtime_files(runtime_context)
        runtime_cues = self._runtime_file_cues(files)
        content_cues = self._content_cues(draft)
        cues = self._select_cues(runtime_cues=runtime_cues, content_cues=content_cues)

        return MemoryCueMetadata(
            schema_version=SCHEMA_VERSION,
            generator_version=GENERATOR_VERSION,
            concepts=self._concepts_for_draft(draft),
            retrieval_cues=cues,
            files=files,
            symbols=sorted(set(runtime_context.symbols)),
            generation_status=CueGenerationStatus.GENERATED,
            generated_at=datetime.now(UTC),
            quality_flags=[],
        )

    def generate_for_records(
        self,
        drafts: list[MemoryRecordDraft],
        *,
        runtime_contexts: list[CueRuntimeContext],
    ) -> list[MemoryCueMetadata]:
        if len(drafts) != len(runtime_contexts):
            raise ValueError("drafts and runtime_contexts must have the same length")
        return [
            self.generate_for_record(draft, runtime_context=runtime_context)
            for draft, runtime_context in zip(drafts, runtime_contexts, strict=True)
        ]

    def _runtime_files(self, runtime_context: CueRuntimeContext) -> list[str]:
        files: list[str] = []
        if runtime_context.source_ref and runtime_context.source_ref.file_path:
            files.append(runtime_context.source_ref.file_path)
        files.extend(runtime_context.current_files)
        files.extend(runtime_context.touched_files)
        files.extend(runtime_context.modified_files)
        return self._dedupe_strings(files)

    def _runtime_file_cues(self, files: list[str]) -> list[RetrievalCue]:
        return [
            RetrievalCue(
                text=file_path[-80:].strip(),
                kind=CueKind.FILE_OR_SYMBOL,
                source=CueSource.RUNTIME,
                confidence=1.0,
            )
            for file_path in files
        ]

    def _content_cues(self, draft: MemoryRecordDraft) -> list[RetrievalCue]:
        cues: list[RetrievalCue] = []
        name = draft.name.strip() if draft.name else ""
        description = draft.description.strip() if draft.description else ""
        if name:
            cues.append(
                RetrievalCue(
                    text=name[:80],
                    kind=CueKind.USER_PHRASE,
                    source=CueSource.USER,
                    confidence=1.0,
                )
            )
        if description and description != name:
            cues.append(
                RetrievalCue(
                    text=description[:80],
                    kind=CueKind.TASK_PHRASE,
                    source=CueSource.USER,
                    confidence=0.9,
                )
            )

        first_line = draft.content.strip().splitlines()[0].strip()
        if first_line:
            cues.append(
                RetrievalCue(
                    text=first_line[:80],
                    kind=CueKind.USER_PHRASE,
                    source=CueSource.USER,
                    confidence=0.85,
                )
            )
        return cues

    def _select_cues(
        self,
        *,
        runtime_cues: list[RetrievalCue],
        content_cues: list[RetrievalCue],
    ) -> list[RetrievalCue]:
        selected = self._dedupe_cues(runtime_cues[:4])
        for cue in content_cues:
            if len(selected) >= 8:
                break
            selected.append(cue)
        remaining_runtime = runtime_cues[4:]
        for cue in remaining_runtime:
            if len(selected) >= 8:
                break
            selected.append(cue)
        return self._dedupe_cues(selected)[:8]

    def _dedupe_strings(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            normalized = value.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            result.append(normalized)
        return result

    def _concepts_for_draft(self, draft: MemoryRecordDraft) -> list[MemoryConcept]:
        content_lower = draft.content.lower()
        if str(draft.kind) == "user":
            return [MemoryConcept.USER_PREFERENCE]
        if str(draft.kind) == "feedback":
            if any(token in content_lower for token in ("always", "must", "never", "prefer")):
                return [MemoryConcept.BEHAVIOR_RULE]
            return [MemoryConcept.RISK_OR_LESSON]
        if any(
            token in content_lower
            for token in ("decided", "decision", "trade-off", "tradeoff")
        ):
            return [MemoryConcept.ARCHITECTURE_DECISION]
        if any(token in content_lower for token in ("run", "steps", "test", "workflow")):
            return [MemoryConcept.WORKFLOW]
        return [MemoryConcept.PROJECT_CONTEXT]

    def _dedupe_cues(self, cues: list[RetrievalCue]) -> list[RetrievalCue]:
        seen: set[tuple[str, CueKind]] = set()
        result: list[RetrievalCue] = []
        for cue in cues:
            key = (cue.text.lower(), cue.kind)
            if key in seen:
                continue
            seen.add(key)
            result.append(cue)
        return result
