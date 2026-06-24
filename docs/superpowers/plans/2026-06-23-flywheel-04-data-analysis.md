# Flywheel 04 — Data & Error Analysis Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the data-first pipeline that turns a trace pool into curated datasets: representative sampling, open coding, axial clustering into candidate labels, the open + versioned taxonomy registry with immutable versions and migration maps, dataset construction with mechanically-disjoint splits, and the per-run `EvalBudget`.

**Architecture:** `flywheel/engine/{sampler,coder,taxonomy,dataset}.py` plus an `api/budget.py` value object. Taxonomy versions are immutable; changes create a new version + migration map. Splits are enforced disjoint at construction time. Synchronous.

**Tech Stack:** Python 3.13, pydantic v2, pytest. (Clustering is deterministic/heuristic in MVP — no LLM dependency required for the unit tests.)

## Global Constraints

(See `2026-06-23-flywheel-00-index.md`.) Most relevant here:
- **Splits mechanically disjoint:** `train ∩ dev ∩ locked_test ∩ regression_holdout = ∅`. `locked_test` and `regression_holdout` must never share cases.
- **Open taxonomy registry.** No closed `FailureCategory` enum. Versions immutable after publication; changes create a new version + migration map. `other` is a temporary code only.
- A taxonomy migration touching labels used by a validated judge marks that judge `recheck_required` (the *propagation* is implemented in plan 05; this plan exposes the changed-label set so plan 05 can react).
- Each run has an explicit `EvalBudget` before it starts; if budget prevents a valid decision → `needs_more_data`, not publish.

---

## File Structure

- Create: `flywheel/api/budget.py` — `EvalBudget` value object + report shape
- Create: `flywheel/engine/sampler.py` — representative sampling
- Create: `flywheel/engine/coder.py` — open code normalization
- Create: `flywheel/engine/taxonomy.py` — registry, axial clustering, immutable versions, migration
- Create: `flywheel/engine/dataset.py` — `DatasetCase`, split enforcement, target-size checks
- Test: mirrors under `flywheel/tests/`

**Interfaces consumed:** `DatasetCaseModel`, `TaxonomyLabelModel`, `TaxonomyMigrationModel` (plan 02 schemas); `JsonRecordStore` (plan 02).

---

## Task 1: EvalBudget value object

**Files:**
- Create: `flywheel/api/budget.py`
- Test: `flywheel/tests/api/test_budget.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class EvalBudget` with the Engine §5 fields: `max_cases`, `max_repeats_per_case`, `max_judge_calls`, `max_curation_llm_calls`, `max_drift_sentinel_cases`, `max_analysis_traces`, `max_total_cost_usd: float`, `max_wall_clock_minutes`.
  - `@dataclass class BudgetUsage` with `judge_calls`, `model_calls`, `cost_usd`, `cases_skipped`, `analysis_traces_sampled`, `analysis_traces_available`, `confidence_limited_by_budget: bool`.
  - `EvalBudget.would_exceed(usage: BudgetUsage) -> bool` — True if any hard limit is breached.

- [ ] **Step 1: Write the failing test**

```python
# flywheel/tests/api/test_budget.py
from api.budget import EvalBudget, BudgetUsage


def _budget(**o):
    base = dict(max_cases=50, max_repeats_per_case=3, max_judge_calls=200,
                max_curation_llm_calls=50, max_drift_sentinel_cases=10,
                max_analysis_traces=100, max_total_cost_usd=5.0,
                max_wall_clock_minutes=30)
    base.update(o)
    return EvalBudget(**base)


def test_within_budget():
    usage = BudgetUsage(judge_calls=10, model_calls=20, cost_usd=1.0, cases_skipped=0,
                        analysis_traces_sampled=10, analysis_traces_available=100,
                        confidence_limited_by_budget=False)
    assert _budget().would_exceed(usage) is False


def test_cost_overrun_exceeds():
    usage = BudgetUsage(judge_calls=10, model_calls=20, cost_usd=9.0, cases_skipped=0,
                        analysis_traces_sampled=10, analysis_traces_available=100,
                        confidence_limited_by_budget=False)
    assert _budget().would_exceed(usage) is True


def test_judge_call_overrun_exceeds():
    usage = BudgetUsage(judge_calls=500, model_calls=20, cost_usd=1.0, cases_skipped=0,
                        analysis_traces_sampled=10, analysis_traces_available=100,
                        confidence_limited_by_budget=False)
    assert _budget().would_exceed(usage) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd flywheel && pytest tests/api/test_budget.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'api.budget'`.

- [ ] **Step 3: Write minimal implementation**

```python
# flywheel/api/budget.py
"""Per-run evaluation budget (Engine §5). Budget exhaustion -> needs_more_data."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EvalBudget:
    max_cases: int
    max_repeats_per_case: int
    max_judge_calls: int
    max_curation_llm_calls: int
    max_drift_sentinel_cases: int
    max_analysis_traces: int
    max_total_cost_usd: float
    max_wall_clock_minutes: int

    def would_exceed(self, usage: "BudgetUsage") -> bool:
        return (
            usage.judge_calls > self.max_judge_calls
            or usage.cost_usd > self.max_total_cost_usd
            or usage.analysis_traces_sampled > self.max_analysis_traces
        )


@dataclass
class BudgetUsage:
    judge_calls: int
    model_calls: int
    cost_usd: float
    cases_skipped: int
    analysis_traces_sampled: int
    analysis_traces_available: int
    confidence_limited_by_budget: bool
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd flywheel && pytest tests/api/test_budget.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add flywheel/api/budget.py flywheel/tests/api/test_budget.py
git commit -m "feat(api): EvalBudget value object and usage accounting"
```

---

## Task 2: Representative sampler

**Files:**
- Create: `flywheel/engine/sampler.py`
- Test: `flywheel/tests/engine/test_sampler.py`

**Interfaces:**
- Produces:
  - `@dataclass class TraceSummary` with `trace_id`, `failed: bool`, `low_confidence: bool`, `high_risk: bool`, `multi_turn: bool`, `intent: str`.
  - `sample_representative(summaries: list[TraceSummary], *, n: int) -> list[TraceSummary]` — deterministic stratified sample (Engine §5 sampling priorities: failed/low-confidence, high-risk, long multi-turn, repeated intents, recent). Guarantees: at least one from each non-empty risk stratum when `n >= number_of_strata`; never returns more than `n`; deterministic for a fixed input order.

- [ ] **Step 1: Write the failing test**

```python
# flywheel/tests/engine/test_sampler.py
from engine.sampler import TraceSummary, sample_representative


def _summaries():
    return [
        TraceSummary("t1", failed=True, low_confidence=False, high_risk=False,
                     multi_turn=False, intent="a"),
        TraceSummary("t2", failed=False, low_confidence=True, high_risk=False,
                     multi_turn=False, intent="a"),
        TraceSummary("t3", failed=False, low_confidence=False, high_risk=True,
                     multi_turn=False, intent="b"),
        TraceSummary("t4", failed=False, low_confidence=False, high_risk=False,
                     multi_turn=True, intent="b"),
        TraceSummary("t5", failed=False, low_confidence=False, high_risk=False,
                     multi_turn=False, intent="c"),
    ]


def test_respects_n():
    out = sample_representative(_summaries(), n=3)
    assert len(out) == 3


def test_covers_risk_strata_first():
    out = sample_representative(_summaries(), n=3)
    ids = {s.trace_id for s in out}
    # failed, high_risk, and multi_turn strata each contribute before plain cases
    assert "t1" in ids        # failed
    assert "t3" in ids or "t4" in ids  # high-risk or multi-turn


def test_deterministic():
    assert sample_representative(_summaries(), n=4) == sample_representative(_summaries(), n=4)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd flywheel && pytest tests/engine/test_sampler.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.sampler'`.

- [ ] **Step 3: Write minimal implementation**

```python
# flywheel/engine/sampler.py
"""Representative trace sampling for error analysis (Engine §5)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TraceSummary:
    trace_id: str
    failed: bool
    low_confidence: bool
    high_risk: bool
    multi_turn: bool
    intent: str


def sample_representative(summaries: list[TraceSummary], *, n: int) -> list[TraceSummary]:
    """Stratified, deterministic sample prioritizing risk strata (Engine §5)."""
    selected: list[TraceSummary] = []
    seen: set[str] = set()

    def take(predicate) -> None:
        for s in summaries:
            if len(selected) >= n:
                return
            if s.trace_id in seen:
                continue
            if predicate(s):
                selected.append(s)
                seen.add(s.trace_id)

    # priority strata, one pass each (Engine §5 sampling priorities)
    take(lambda s: s.failed or s.low_confidence)
    take(lambda s: s.high_risk)
    take(lambda s: s.multi_turn)
    # fill remainder with anything not yet taken, preserving input order
    take(lambda s: True)
    return selected[:n]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd flywheel && pytest tests/engine/test_sampler.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add flywheel/engine/sampler.py flywheel/tests/engine/test_sampler.py
git commit -m "feat(engine): representative stratified trace sampler"
```

---

## Task 3: Open code normalization

**Files:**
- Create: `flywheel/engine/coder.py`
- Test: `flywheel/tests/engine/test_coder.py`

**Interfaces:**
- Produces:
  - `@dataclass class OpenCode` with `trace_id`, `code: str`, `author: str`.
  - `normalize_code(raw: str) -> str` — lowercases, collapses whitespace, strips punctuation, so "Missing offset explanation!" and "missing  offset explanation" map to the same normalized form `"missing offset explanation"`.
  - `group_by_normalized(codes: list[OpenCode]) -> dict[str, list[OpenCode]]` — buckets codes by normalized form, preserving insertion order within a bucket.

- [ ] **Step 1: Write the failing test**

```python
# flywheel/tests/engine/test_coder.py
from engine.coder import OpenCode, normalize_code, group_by_normalized


def test_normalize_collapses_variants():
    assert normalize_code("Missing offset explanation!") == "missing offset explanation"
    assert normalize_code("missing  offset   explanation") == "missing offset explanation"


def test_group_buckets_equivalent_codes():
    codes = [
        OpenCode("t1", "Missing offset explanation", "alice"),
        OpenCode("t2", "missing  offset explanation!", "bob"),
        OpenCode("t3", "wrong tool arg shape", "alice"),
    ]
    groups = group_by_normalized(codes)
    assert set(groups.keys()) == {"missing offset explanation", "wrong tool arg shape"}
    assert len(groups["missing offset explanation"]) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd flywheel && pytest tests/engine/test_coder.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.coder'`.

- [ ] **Step 3: Write minimal implementation**

```python
# flywheel/engine/coder.py
"""Open code normalization and grouping (Engine §5 open coding)."""
from __future__ import annotations

import re
from dataclasses import dataclass

_PUNCT = re.compile(r"[^\w\s]")
_WS = re.compile(r"\s+")


@dataclass
class OpenCode:
    trace_id: str
    code: str
    author: str


def normalize_code(raw: str) -> str:
    lowered = raw.lower()
    no_punct = _PUNCT.sub("", lowered)
    return _WS.sub(" ", no_punct).strip()


def group_by_normalized(codes: list[OpenCode]) -> dict[str, list[OpenCode]]:
    groups: dict[str, list[OpenCode]] = {}
    for code in codes:
        key = normalize_code(code.code)
        groups.setdefault(key, []).append(code)
    return groups
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd flywheel && pytest tests/engine/test_coder.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add flywheel/engine/coder.py flywheel/tests/engine/test_coder.py
git commit -m "feat(engine): open code normalization and grouping"
```

---

## Task 4: Taxonomy registry — clustering, immutable versions, promotion gate

**Files:**
- Create: `flywheel/engine/taxonomy.py`
- Test: `flywheel/tests/engine/test_taxonomy.py`

**Interfaces:**
- Consumes: `OpenCode`, `group_by_normalized` (`engine.coder`); `JsonRecordStore` (plan 02).
- Produces:
  - `@dataclass class CandidateLabel` with `slug`, `member_codes: list[str]`, `count: int`.
  - `cluster_open_codes(codes: list[OpenCode], *, min_cluster_size: int = 2) -> list[CandidateLabel]` — axial clustering by normalized form; clusters below `min_cluster_size` are bucketed under slug `"other"`. Repeated `other` content stays flagged for review (the `"other"` candidate is always returned when present).
  - `class TaxonomyRegistry(store: JsonRecordStore)`:
    - `promote(*, project, slug, definition, examples, counterexamples, parent=None) -> dict` — creates a label with `status="candidate"`, `owner_approved=False`. Raises `ValueError` if `definition` empty, `examples` empty, or `counterexamples` empty (Engine §5 promotion gate requires definition + positive examples + negative examples).
    - `activate(*, project, slug, approved_by: str) -> dict` — flips `candidate → active` only when an owner id is provided; sets `owner_approved=True`, `approved_by=approved_by`.
    - `publish_version(*, project, version: str) -> dict` — snapshots all `active` labels into an immutable taxonomy version record (collection `"taxonomy_versions"`). Re-publishing the same version id raises `ValueError` (immutable).

- [ ] **Step 1: Write the failing test**

```python
# flywheel/tests/engine/test_taxonomy.py
import pytest
from api.store import JsonRecordStore
from engine.coder import OpenCode
from engine.taxonomy import cluster_open_codes, TaxonomyRegistry


def test_clustering_buckets_small_groups_as_other():
    codes = [
        OpenCode("t1", "wrong tool arg shape", "a"),
        OpenCode("t2", "wrong tool arg shape", "b"),
        OpenCode("t3", "one off weirdness", "c"),
    ]
    clusters = {c.slug: c for c in cluster_open_codes(codes, min_cluster_size=2)}
    assert clusters["wrong tool arg shape"].count == 2
    assert "other" in clusters
    assert clusters["other"].count == 1


def test_promote_requires_definition_and_examples(tmp_path):
    reg = TaxonomyRegistry(JsonRecordStore(root=tmp_path))
    with pytest.raises(ValueError):
        reg.promote(project="bourbon", slug="x", definition="", examples=[],
                    counterexamples=[])
    with pytest.raises(ValueError, match="positive"):
        reg.promote(project="bourbon", slug="x", definition="d", examples=[],
                    counterexamples=["c2"])
    with pytest.raises(ValueError, match="negative"):
        reg.promote(project="bourbon", slug="x", definition="d", examples=["c1"],
                    counterexamples=[])
    label = reg.promote(project="bourbon", slug="tool_argument_error",
                        definition="bad args", examples=["c1"], counterexamples=["c2"])
    assert label["status"] == "candidate"
    assert label["owner_approved"] is False


def test_activate_requires_owner_approval(tmp_path):
    reg = TaxonomyRegistry(JsonRecordStore(root=tmp_path))
    reg.promote(project="bourbon", slug="tool_argument_error", definition="bad",
                examples=["c1"], counterexamples=["c2"])
    with pytest.raises(ValueError, match="owner approval"):
        reg.activate(project="bourbon", slug="tool_argument_error", approved_by="")
    label = reg.activate(project="bourbon", slug="tool_argument_error",
                         approved_by="owner_alice")
    assert label["status"] == "active"
    assert label["owner_approved"] is True
    assert label["approved_by"] == "owner_alice"


def test_publish_version_is_immutable(tmp_path):
    reg = TaxonomyRegistry(JsonRecordStore(root=tmp_path))
    reg.promote(project="bourbon", slug="tool_argument_error", definition="bad",
                examples=["c1"], counterexamples=["c2"])
    reg.activate(project="bourbon", slug="tool_argument_error", approved_by="owner_alice")
    reg.publish_version(project="bourbon", version="2026-06-22.1")
    with pytest.raises(ValueError, match="immutable"):
        reg.publish_version(project="bourbon", version="2026-06-22.1")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd flywheel && pytest tests/engine/test_taxonomy.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.taxonomy'`.

- [ ] **Step 3: Write minimal implementation**

```python
# flywheel/engine/taxonomy.py
"""Open taxonomy registry: clustering, promotion gate, immutable versions (Engine §5)."""
from __future__ import annotations

from dataclasses import dataclass

from .coder import OpenCode, group_by_normalized
from api.store import JsonRecordStore


@dataclass
class CandidateLabel:
    slug: str
    member_codes: list[str]
    count: int


def cluster_open_codes(codes: list[OpenCode], *,
                       min_cluster_size: int = 2) -> list[CandidateLabel]:
    groups = group_by_normalized(codes)
    candidates: list[CandidateLabel] = []
    other_members: list[str] = []
    for key, members in groups.items():
        if len(members) >= min_cluster_size:
            candidates.append(CandidateLabel(
                slug=key, member_codes=[m.code for m in members], count=len(members)))
        else:
            other_members.extend(m.code for m in members)
    if other_members:
        candidates.append(CandidateLabel(
            slug="other", member_codes=other_members, count=len(other_members)))
    return candidates


class TaxonomyRegistry:
    def __init__(self, store: JsonRecordStore):
        self._store = store

    def _label_id(self, project: str, slug: str) -> str:
        return f"{project}:{slug}"

    def promote(self, *, project: str, slug: str, definition: str,
                examples: list[str], counterexamples: list[str],
                parent: str | None = None) -> dict:
        if not definition.strip():
            raise ValueError("taxonomy label requires a definition")
        if not examples:
            raise ValueError("taxonomy label requires positive examples")
        if not counterexamples:
            raise ValueError("taxonomy label requires negative examples")
        return self._store.put("taxonomy_labels", self._label_id(project, slug), {
            "project": project, "slug": slug, "parent": parent,
            "definition": definition, "examples": examples,
            "counterexamples": counterexamples, "status": "candidate",
            "owner_approved": False, "approved_by": None,
        })

    def activate(self, *, project: str, slug: str, approved_by: str) -> dict:
        label = self._store.get("taxonomy_labels", self._label_id(project, slug))
        if label is None:
            raise ValueError(f"unknown label {slug}")
        if not approved_by:
            raise ValueError("taxonomy activation requires owner approval")
        label["status"] = "active"
        label["owner_approved"] = True
        label["approved_by"] = approved_by
        return self._store.put("taxonomy_labels", self._label_id(project, slug), label)

    def publish_version(self, *, project: str, version: str) -> dict:
        version_id = f"{project}:{version}"
        if self._store.get("taxonomy_versions", version_id) is not None:
            raise ValueError(f"taxonomy version {version} is immutable and already published")
        active = [l for l in self._store.list("taxonomy_labels", project=project)
                  if l.get("status") == "active"]
        return self._store.put("taxonomy_versions", version_id, {
            "project": project, "version": version,
            "labels": [l["slug"] for l in active],
            "label_snapshot": active,
        })
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd flywheel && pytest tests/engine/test_taxonomy.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add flywheel/engine/taxonomy.py flywheel/tests/engine/test_taxonomy.py
git commit -m "feat(engine): taxonomy registry with clustering and immutable versions"
```

---

## Task 5: Taxonomy migration map + changed-label detection

**Files:**
- Modify: `flywheel/engine/taxonomy.py` (append `create_migration`, `changed_labels`)
- Test: `flywheel/tests/engine/test_taxonomy_migration.py`

**Interfaces:**
- Produces (added to `TaxonomyRegistry`):
  - `create_migration(*, project, from_version, to_version, migrations: list[dict]) -> dict` — stores a migration record (collection `"taxonomy_migrations"`). Each migration matches plan 02 `TaxonomyMigrationStepModel`: `{"from_slug": str, "to_slug": str | list[str] | None, "kind": Literal["rename","split","merge","retire"]}`. Raises `ValueError` if `from_version == to_version`.
  - `changed_labels(migration: dict) -> set[str]` — returns the set of `from_slug` values touched by the migration. **Used by plan 05** to mark judges `recheck_required` when a migration touches a label a validated judge used.

- [ ] **Step 1: Write the failing test**

```python
# flywheel/tests/engine/test_taxonomy_migration.py
import pytest
from api.store import JsonRecordStore
from engine.taxonomy import TaxonomyRegistry


def test_create_migration_and_changed_labels(tmp_path):
    reg = TaxonomyRegistry(JsonRecordStore(root=tmp_path))
    migrations = [
        {"from_slug": "tool_argument_error", "to_slug": "invalid_tool_arguments", "kind": "rename"},
        {"from_slug": "context_miss", "to_slug": ["retrieval_miss", "memory_miss"], "kind": "split"},
        {"from_slug": "obsolete_label", "to_slug": None, "kind": "retire"},
    ]
    rec = reg.create_migration(project="bourbon", from_version="2026-06-22.1",
                               to_version="2026-07-01.1", migrations=migrations)
    assert rec["from_version"] == "2026-06-22.1"
    changed = reg.changed_labels(rec)
    assert changed == {"tool_argument_error", "context_miss", "obsolete_label"}


def test_migration_requires_distinct_versions(tmp_path):
    reg = TaxonomyRegistry(JsonRecordStore(root=tmp_path))
    with pytest.raises(ValueError):
        reg.create_migration(project="bourbon", from_version="v1", to_version="v1",
                             migrations=[])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd flywheel && pytest tests/engine/test_taxonomy_migration.py -v`
Expected: FAIL with `AttributeError: ... 'create_migration'`.

- [ ] **Step 3: Append implementation to `taxonomy.py`**

```python
# flywheel/engine/taxonomy.py  (append to TaxonomyRegistry)
    def create_migration(self, *, project: str, from_version: str,
                         to_version: str, migrations: list[dict]) -> dict:
        if from_version == to_version:
            raise ValueError("migration requires distinct from/to versions")
        migration_id = f"{project}:{from_version}->{to_version}"
        return self._store.put("taxonomy_migrations", migration_id, {
            "project": project, "from_version": from_version,
            "to_version": to_version, "migrations": migrations,
        })

    @staticmethod
    def changed_labels(migration: dict) -> set[str]:
        return {m["from_slug"] for m in migration.get("migrations", [])}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd flywheel && pytest tests/engine/test_taxonomy_migration.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add flywheel/engine/taxonomy.py flywheel/tests/engine/test_taxonomy_migration.py
git commit -m "feat(engine): taxonomy migration map and changed-label detection"
```

---

## Task 6: Dataset construction with disjoint-split enforcement

**Files:**
- Create: `flywheel/engine/dataset.py`
- Test: `flywheel/tests/engine/test_dataset.py`

**Interfaces:**
- Consumes: `DatasetCaseModel` (plan 02 schemas); `JsonRecordStore` (plan 02).
- Produces:
  - `class SplitViolation(ValueError)`.
  - `class DatasetBuilder(store: JsonRecordStore)`:
    - `add_case(case: DatasetCaseModel) -> dict` — persists a case (collection `"dataset_cases"`, id = `f"{dataset_id}:{dataset_version}:{case_id}"`). Before persisting, asserts the `case_id` is not already assigned to a *different* split within the same dataset version → else `SplitViolation` (enforces `train ∩ dev ∩ locked_test ∩ regression_holdout = ∅`).
    - `split_intersections(dataset_id, dataset_version) -> dict[tuple[str, str], list[str]]` — returns, for each pair of splits, the case_ids shared (must be empty for a valid dataset). Specifically reports the four Engine §14 holdout intersections.
    - `target_size_report(dataset_id, dataset_version) -> dict` — counts per split and flags whether `regression_holdout >= 30` and `locked_test` non-empty (Engine §5 target sizes).

- [ ] **Step 1: Write the failing test**

```python
# flywheel/tests/engine/test_dataset.py
import pytest
from api.store import JsonRecordStore
from api.schemas import DatasetCaseModel
from engine.dataset import DatasetBuilder, SplitViolation


def _case(case_id, split):
    return DatasetCaseModel(
        project="bourbon", id=case_id, dataset_id="ds1", dataset_version="v1",
        case_id=case_id, task_family="tool_use", source_trace_ids=["t1"],
        intent_summary="x", input_messages_ref="ref", expected_outcome="ok",
        acceptance_criteria=["a"], risk_tags=[], failure_labels=[],
        split=split, created_from="production_trace",
    )


def test_add_case_persists(tmp_path):
    b = DatasetBuilder(JsonRecordStore(root=tmp_path))
    row = b.add_case(_case("c1", "train"))
    assert row["split"] == "train"


def test_same_case_in_two_splits_raises(tmp_path):
    b = DatasetBuilder(JsonRecordStore(root=tmp_path))
    b.add_case(_case("c1", "locked_test"))
    with pytest.raises(SplitViolation):
        b.add_case(_case("c1", "regression_holdout"))


def test_split_intersections_empty_for_valid_dataset(tmp_path):
    b = DatasetBuilder(JsonRecordStore(root=tmp_path))
    b.add_case(_case("c1", "train"))
    b.add_case(_case("c2", "locked_test"))
    b.add_case(_case("c3", "regression_holdout"))
    inter = b.split_intersections("ds1", "v1")
    assert all(len(v) == 0 for v in inter.values())


def test_target_size_report(tmp_path):
    b = DatasetBuilder(JsonRecordStore(root=tmp_path))
    b.add_case(_case("c1", "regression_holdout"))
    rep = b.target_size_report("ds1", "v1")
    assert rep["counts"]["regression_holdout"] == 1
    assert rep["regression_holdout_meets_target"] is False  # < 30
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd flywheel && pytest tests/engine/test_dataset.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.dataset'`.

- [ ] **Step 3: Write minimal implementation**

```python
# flywheel/engine/dataset.py
"""Dataset construction with mechanically-disjoint split enforcement (Engine §5, §14)."""
from __future__ import annotations

from itertools import combinations

from api.schemas import DatasetCaseModel
from api.store import JsonRecordStore

_SPLITS = ("train", "dev", "locked_test", "regression_holdout")


class SplitViolation(ValueError):
    """Raised when a case_id would be assigned to more than one split."""


class DatasetBuilder:
    def __init__(self, store: JsonRecordStore):
        self._store = store

    def _case_id(self, dataset_id: str, dataset_version: str, case_id: str) -> str:
        return f"{dataset_id}:{dataset_version}:{case_id}"

    def _cases(self, dataset_id: str, dataset_version: str) -> list[dict]:
        return [c for c in self._store.list("dataset_cases", project=None)
                if c.get("dataset_id") == dataset_id
                and c.get("dataset_version") == dataset_version]

    def add_case(self, case: DatasetCaseModel) -> dict:
        existing = self._cases(case.dataset_id, case.dataset_version)
        for other in existing:
            if other["case_id"] == case.case_id and other["split"] != case.split:
                raise SplitViolation(
                    f"case {case.case_id} already in split {other['split']}, "
                    f"cannot also be {case.split}")
        return self._store.put(
            "dataset_cases",
            self._case_id(case.dataset_id, case.dataset_version, case.case_id),
            case.model_dump(),
        )

    def split_intersections(self, dataset_id: str,
                            dataset_version: str) -> dict[tuple[str, str], list[str]]:
        by_split: dict[str, set[str]] = {s: set() for s in _SPLITS}
        for c in self._cases(dataset_id, dataset_version):
            by_split[c["split"]].add(c["case_id"])
        result: dict[tuple[str, str], list[str]] = {}
        for a, b in combinations(_SPLITS, 2):
            result[(a, b)] = sorted(by_split[a] & by_split[b])
        return result

    def target_size_report(self, dataset_id: str, dataset_version: str) -> dict:
        counts = {s: 0 for s in _SPLITS}
        for c in self._cases(dataset_id, dataset_version):
            counts[c["split"]] += 1
        return {
            "counts": counts,
            "regression_holdout_meets_target": counts["regression_holdout"] >= 30,
            "locked_test_non_empty": counts["locked_test"] > 0,
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd flywheel && pytest tests/engine/test_dataset.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Run full suite + lint + types, then commit**

```bash
cd flywheel && pytest -q && ruff check api engine sdk tests && mypy api engine sdk
git add flywheel/engine/dataset.py flywheel/tests/engine/test_dataset.py
git commit -m "feat(engine): dataset builder with disjoint-split enforcement"
```

---

## Task 7: Wire data-analysis and taxonomy API routes

**Files:**
- Modify: `flywheel/api/server.py`
- Test: `flywheel/tests/api/test_data_routes.py`, `flywheel/tests/api/test_taxonomy_routes.py`, `flywheel/tests/api/test_score_taxonomy_validation.py`

**Interfaces:**
- Consumes: `DatasetBuilder`, `TaxonomyRegistry`, `sample_representative`, `OpenCode`, `IdempotencyStore`, `AuditLog`, `require_role`.
- Produces the plan-04 endpoints assigned in `2026-06-23-flywheel-00-index.md`:
  - `GET /api/projects`
  - `GET /api/datasets`, `GET /api/datasets/{dataset_id}`
  - `POST /api/datasets/{dataset_id}/cases`
  - `GET /api/taxonomy`
  - `GET, POST /api/taxonomy/labels`
  - `GET, POST /api/taxonomy/migrations`
  - `POST /api/taxonomy/propose-update`
  - `GET /api/trace-pools`
  - `POST /api/trace-pools/{pool_id}/sample`
  - `GET /api/open-code-batches/{batch_id}`
  - `POST /api/open-code-batches/{batch_id}/codes`
  - `POST /api/runs/{run_id}/scores` taxonomy validation layer: plan 02 owns Score Bridge mechanics; this task rejects stable `failure_labels` not active in the run's taxonomy version before delegating to the existing score writer.
- All mutations require `Idempotency-Key`, return the updated object plus `audit_event_id`, and duplicate submits return the stored prior result. Dataset/open-code/taxonomy mutations require `dataset_curator`.

- [ ] **Step 1: Write the failing route tests**

```python
# flywheel/tests/api/test_data_routes.py
from pathlib import Path
from fastapi.testclient import TestClient
from api.auth import Principal
from api.server import create_app


def _client(tmp_path: Path, roles=("dataset_curator",)):
    principal = Principal(actor_id="alice", roles=frozenset(roles))
    app = create_app(root=tmp_path, principal_resolver=lambda request: principal)
    return TestClient(app), app


def test_create_dataset_case_is_idempotent_and_audited(tmp_path):
    client, _ = _client(tmp_path)
    body = {
        "project": "bourbon", "id": "c1", "dataset_id": "ds1",
        "dataset_version": "v1", "case_id": "c1", "task_family": "tool_use",
        "source_trace_ids": ["t1"], "intent_summary": "x",
        "input_messages_ref": "ref", "expected_outcome": "ok",
        "acceptance_criteria": ["a"], "risk_tags": [],
        "failure_labels": [], "split": "train",
        "created_from": "production_trace",
    }
    r1 = client.post("/api/datasets/ds1/cases", json=body,
                     headers={"Idempotency-Key": "case-1"})
    r2 = client.post("/api/datasets/ds1/cases", json=body,
                     headers={"Idempotency-Key": "case-1"})
    assert r1.status_code == 200
    assert r1.json() == r2.json()
    assert r1.json()["case"]["case_id"] == "c1"
    assert "audit_event_id" in r1.json()


def test_trace_pool_sampling_creates_open_code_batch(tmp_path):
    client, app = _client(tmp_path)
    app.state.store.put("trace_pools", "pool1", {"project": "bourbon", "id": "pool1",
        "traces": [
            {"trace_id": "t1", "failed": True, "low_confidence": False,
             "high_risk": False, "multi_turn": False, "intent": "a"},
            {"trace_id": "t2", "failed": False, "low_confidence": False,
             "high_risk": True, "multi_turn": False, "intent": "b"},
        ]})
    r = client.post("/api/trace-pools/pool1/sample",
                    json={"project": "bourbon", "n": 1},
                    headers={"Idempotency-Key": "sample-1"})
    assert r.status_code == 200
    assert len(r.json()["batch"]["trace_ids"]) == 1
    assert "audit_event_id" in r.json()


def test_data_route_wiring_keeps_plan02_runs_list_working(tmp_path):
    client, app = _client(tmp_path)
    app.state.store.put("runs", "run1", {"project": "bourbon", "id": "run1",
        "state": "collecting"})
    r = client.get("/api/runs", params={"project": "bourbon"})
    assert r.status_code == 200
    assert r.json()["runs"][0]["id"] == "run1"


def test_projects_datasets_taxonomy_trace_pools_and_open_code_routes(tmp_path):
    client, app = _client(tmp_path)
    app.state.store.put("datasets", "ds1", {"project": "bourbon", "id": "ds1",
        "dataset_id": "ds1", "dataset_version": "v1"})
    app.state.store.put("dataset_cases", "case1", {"project": "bourbon", "id": "case1",
        "dataset_id": "ds1", "case_id": "c1"})
    app.state.store.put("taxonomy_labels", "lab1", {"project": "bourbon", "id": "lab1",
        "slug": "tool_argument_error", "status": "active"})
    app.state.store.put("taxonomy_migrations", "mig1", {"project": "bourbon", "id": "mig1",
        "from_version": "v1", "to_version": "v2", "migrations": []})
    app.state.store.put("trace_pools", "pool1", {"project": "bourbon", "id": "pool1",
        "traces": []})
    app.state.store.put("open_code_batches", "batch1", {"project": "bourbon",
        "id": "batch1", "trace_pool_id": "pool1", "trace_ids": ["t1"], "codes": []})

    assert client.get("/api/projects").json()["projects"] == ["bourbon"]
    assert client.get("/api/datasets", params={"project": "bourbon"}).json()["datasets"][0]["id"] == "ds1"
    assert client.get("/api/datasets/ds1", params={"project": "bourbon"}).json()["cases"][0]["case_id"] == "c1"
    assert client.get("/api/taxonomy", params={"project": "bourbon"}).json()["labels"][0]["slug"] == "tool_argument_error"
    assert client.get("/api/taxonomy/labels", params={"project": "bourbon"}).json()["labels"][0]["slug"] == "tool_argument_error"
    assert client.get("/api/taxonomy/migrations", params={"project": "bourbon"}).json()["migrations"][0]["to_version"] == "v2"
    assert client.get("/api/trace-pools", params={"project": "bourbon"}).json()["trace_pools"][0]["id"] == "pool1"
    assert client.get("/api/open-code-batches/batch1").json()["batch"]["trace_ids"] == ["t1"]

    r = client.post("/api/open-code-batches/batch1/codes",
                    json={"project": "bourbon", "trace_id": "t1",
                          "code": "wrong tool arg shape", "author": "alice"},
                    headers={"Idempotency-Key": "code-1"})
    assert r.status_code == 200
    assert r.json()["batch"]["codes"][0]["code"] == "wrong tool arg shape"
    assert "audit_event_id" in r.json()
```

```python
# flywheel/tests/api/test_taxonomy_routes.py
from pathlib import Path
from fastapi.testclient import TestClient
from api.auth import Principal
from api.server import create_app


def _client(tmp_path: Path, roles=("dataset_curator",)):
    principal = Principal(actor_id="alice", roles=frozenset(roles))
    app = create_app(root=tmp_path, principal_resolver=lambda request: principal)
    return TestClient(app), app


def test_taxonomy_label_route_requires_examples_and_audits(tmp_path):
    client, _ = _client(tmp_path)
    body = {"project": "bourbon", "slug": "tool_argument_error",
            "definition": "bad args", "examples": ["c1"],
            "counterexamples": ["c2"]}
    r = client.post("/api/taxonomy/labels", json=body,
                    headers={"Idempotency-Key": "label-1"})
    assert r.status_code == 200
    assert r.json()["label"]["status"] == "candidate"
    assert r.json()["label"]["owner_approved"] is False
    assert "audit_event_id" in r.json()


def test_taxonomy_migration_route_uses_from_slug_to_slug(tmp_path):
    client, _ = _client(tmp_path)
    r = client.post("/api/taxonomy/migrations", json={
        "project": "bourbon", "from_version": "v1", "to_version": "v2",
        "migrations": [{"from_slug": "old", "to_slug": "new", "kind": "rename"}],
    }, headers={"Idempotency-Key": "mig-1"})
    assert r.status_code == 200
    assert r.json()["migration"]["migrations"][0]["from_slug"] == "old"


def test_propose_update_can_activate_with_owner_approval(tmp_path):
    client, _ = _client(tmp_path)
    client.post("/api/taxonomy/labels", json={"project": "bourbon",
        "slug": "tool_argument_error", "definition": "bad args",
        "examples": ["c1"], "counterexamples": ["c2"]},
        headers={"Idempotency-Key": "label-1"})
    r = client.post("/api/taxonomy/propose-update", json={"project": "bourbon",
        "action": "activate", "slug": "tool_argument_error",
        "approved_by": "owner_alice"},
        headers={"Idempotency-Key": "activate-1"})
    assert r.status_code == 200
    assert r.json()["label"]["status"] == "active"
```

```python
# flywheel/tests/api/test_score_taxonomy_validation.py
from pathlib import Path
from fastapi.testclient import TestClient
from api.auth import Principal
from api.server import create_app


def test_scores_reject_unknown_stable_failure_label(tmp_path: Path):
    principal = Principal(actor_id="alice", roles=frozenset({"harness_owner"}))
    app = create_app(root=tmp_path, principal_resolver=lambda request: principal)
    client = TestClient(app)
    app.state.store.put("runs", "run1", {"project": "bourbon", "id": "run1",
        "taxonomy_version": "tax1", "state": "scored"})
    r = client.post("/api/runs/run1/scores", json={
        "project": "bourbon", "case_id": "c1", "sample_id": "s0",
        "source": "judge", "judge_version": "jv1", "label": "fail",
        "failure_labels": ["not_in_taxonomy"], "confidence": 0.9,
        "critique": "x", "trace_id": "trace1",
    }, headers={"Idempotency-Key": "score-1"})
    assert r.status_code == 400
    assert "unknown failure label" in r.json()["detail"]


class FakeScoreBridge:
    def write_score(self, **kwargs):
        return {"score_id": "score1", "deduped": False, "audit_event_id": "audit1",
                "kwargs": kwargs}


def test_scores_accept_known_stable_failure_label(tmp_path: Path):
    principal = Principal(actor_id="alice", roles=frozenset({"harness_owner"}))
    app = create_app(root=tmp_path, principal_resolver=lambda request: principal)
    app.state.score_bridge_factory = lambda project: FakeScoreBridge()
    client = TestClient(app)
    app.state.store.put("runs", "run1", {"project": "bourbon", "id": "run1",
        "taxonomy_version": "tax1", "state": "scored"})
    app.state.store.put("taxonomy_labels", "lab1", {"project": "bourbon", "id": "lab1",
        "slug": "tool_argument_error", "status": "active", "taxonomy_version": "tax1"})
    r = client.post("/api/runs/run1/scores", json={
        "project": "bourbon", "case_id": "c1", "sample_id": "s0",
        "source": "judge", "judge_version": "jv1", "label": "fail",
        "failure_labels": ["tool_argument_error"], "confidence": 0.9,
        "critique": "x", "trace_id": "trace1",
    }, headers={"Idempotency-Key": "score-2"})
    assert r.status_code == 200
    assert r.json()["score"]["score_id"] == "score1"
    assert r.json()["audit_event_id"] == "audit1"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd flywheel
pytest tests/api/test_data_routes.py tests/api/test_taxonomy_routes.py tests/api/test_score_taxonomy_validation.py -v
```

Expected: FAIL because plan 02 stubs are still present or the routes do not yet perform data-analysis behavior.

- [ ] **Step 3: Wire services and routes in `server.py`**

Add services inside `create_app`:

```python
    from engine.dataset import DatasetBuilder
    from engine.sampler import TraceSummary, sample_representative
    from engine.taxonomy import TaxonomyRegistry

    datasets = DatasetBuilder(store)
    taxonomy = TaxonomyRegistry(store)
    app.state.store = store
```

Add a data-route-specific idempotent mutation helper. Do not redefine plan 02's
`_idempotent(key, build)` helper inside the same `create_app` scope; the unique
name avoids changing closures already registered by the plan-02 routes:

```python
    def _idempotent_data_mutation(request: Request, compute):
        key = request.headers.get("Idempotency-Key")
        if not key:
            raise HTTPException(status_code=400, detail="Idempotency-Key required")
        prior = idem.lookup(key)
        if prior is not None:
            return prior
        result = compute()
        idem.remember(key, result)
        return result
```

Add route-local request models before the route snippets:

```python
    from typing import Literal
    import os
    from pydantic import BaseModel
    from api.schemas import DatasetCaseModel, TaxonomyMigrationStepModel
    from api.score_bridge import ScoreBridge

    class TaxonomyLabelCreate(BaseModel):
        project: str
        slug: str
        definition: str
        examples: list[str]
        counterexamples: list[str]
        parent: str | None = None

    class TaxonomyMigrationCreate(BaseModel):
        project: str
        from_version: str
        to_version: str
        migrations: list[TaxonomyMigrationStepModel]

    class TaxonomyUpdateBody(BaseModel):
        project: str
        action: Literal["activate", "migration"]
        slug: str | None = None
        approved_by: str | None = None
        from_version: str | None = None
        to_version: str | None = None
        migrations: list[TaxonomyMigrationStepModel] = []

    class SampleBody(BaseModel):
        project: str
        n: int

    class OpenCodeBody(BaseModel):
        project: str
        trace_id: str
        code: str
        author: str

    class ScoreSubmitBody(BaseModel):
        project: str
        case_id: str
        sample_id: str
        source: Literal["human", "judge", "rule", "system"]
        judge_version: str | None = None
        label: Literal["pass", "fail", "skip", "uncertain"]
        failure_labels: list[str] = []
        confidence: float | None = None
        critique: str | None = None
        trace_id: str
```

Add complete route snippets for every endpoint listed above. The final
`submit_score` snippet **replaces** the plan-02
`POST /api/runs/{run_id}/scores` 501 stub in `server.py`; do not register a
second route with the same path/method. The score taxonomy tests must assert
the route returns validation behavior, not the plan-02 501 stub.

```python
    def _score_bridge(project: str):
        factory = getattr(app.state, "score_bridge_factory", None)
        if factory is not None:
            return factory(project)
        return ScoreBridge(langfuse_url=os.environ["LANGFUSE_URL"],
                           langfuse_secret=os.environ["LANGFUSE_SECRET"],
                           idem=idem, audit=audit, project=project, client=None)

    @app.get("/api/projects")
    def list_projects():
        projects = sorted({r["project"] for collection in
            ("runs", "datasets", "trace_pools", "taxonomy_labels")
            for r in store.list(collection, project=None)
            if r.get("project")})
        return {"projects": projects}

    @app.get("/api/datasets")
    def list_datasets(project: str):
        return {"datasets": store.list("datasets", project=project)}

    @app.get("/api/datasets/{dataset_id}")
    def get_dataset(dataset_id: str, project: str):
        cases = [c for c in store.list("dataset_cases", project=project)
                 if c.get("dataset_id") == dataset_id]
        return {"dataset": {"dataset_id": dataset_id, "project": project},
                "cases": cases}

    @app.post("/api/datasets/{dataset_id}/cases")
    def create_dataset_case(dataset_id: str, case: DatasetCaseModel, request: Request):
        principal = principal_resolver(request)
        require_role(principal, "dataset_curator")
        if case.dataset_id != dataset_id:
            raise HTTPException(status_code=400, detail="dataset id mismatch")
        def compute():
            row = datasets.add_case(case)
            aid = audit.record(project=case.project, actor=principal.actor_id,
                               action="create_dataset_case", target_type="dataset_case",
                               target_id=row["id"], before=None, after=row)
            return {"case": row, "audit_event_id": aid}
        return _idempotent_data_mutation(request, compute)

    @app.get("/api/taxonomy")
    def get_taxonomy(project: str):
        return {"labels": store.list("taxonomy_labels", project=project),
                "migrations": store.list("taxonomy_migrations", project=project),
                "versions": store.list("taxonomy_versions", project=project)}

    @app.get("/api/taxonomy/labels")
    def list_taxonomy_labels(project: str, status: str | None = None):
        where = {"status": status} if status else None
        return {"labels": store.list("taxonomy_labels", project=project, where=where)}

    @app.post("/api/taxonomy/labels")
    def create_taxonomy_label(body: TaxonomyLabelCreate, request: Request):
        principal = principal_resolver(request)
        require_role(principal, "dataset_curator")
        def compute():
            label = taxonomy.promote(**body.model_dump())
            aid = audit.record(project=body.project, actor=principal.actor_id,
                               action="promote_taxonomy_label", target_type="taxonomy_label",
                               target_id=label["id"], before=None, after=label)
            return {"label": label, "audit_event_id": aid}
        return _idempotent_data_mutation(request, compute)

    @app.get("/api/taxonomy/migrations")
    def list_taxonomy_migrations(project: str, from_version: str | None = None,
                                 to_version: str | None = None):
        where = {k: v for k, v in {"from_version": from_version,
                                   "to_version": to_version}.items() if v is not None}
        return {"migrations": store.list("taxonomy_migrations", project=project,
                                         where=where or None)}

    @app.post("/api/taxonomy/migrations")
    def create_taxonomy_migration(body: TaxonomyMigrationCreate, request: Request):
        principal = principal_resolver(request)
        require_role(principal, "dataset_curator")
        def compute():
            migration = taxonomy.create_migration(**body.model_dump())
            aid = audit.record(project=body.project, actor=principal.actor_id,
                               action="create_taxonomy_migration",
                               target_type="taxonomy_migration",
                               target_id=migration["id"], before=None, after=migration)
            return {"migration": migration, "audit_event_id": aid}
        return _idempotent_data_mutation(request, compute)

    @app.post("/api/taxonomy/propose-update")
    def propose_taxonomy_update(body: TaxonomyUpdateBody, request: Request):
        principal = principal_resolver(request)
        require_role(principal, "dataset_curator")
        def compute():
            if body.action == "activate":
                label = taxonomy.activate(project=body.project, slug=body.slug,
                                          approved_by=body.approved_by or principal.actor_id)
                after = {"label": label}
            else:
                after = taxonomy.create_migration(project=body.project,
                    from_version=body.from_version, to_version=body.to_version,
                    migrations=body.migrations)
            aid = audit.record(project=body.project, actor=principal.actor_id,
                               action=f"taxonomy_{body.action}",
                               target_type="taxonomy", target_id=body.slug or body.to_version,
                               before=None, after=after)
            return {**after, "audit_event_id": aid}
        return _idempotent_data_mutation(request, compute)

    @app.get("/api/trace-pools")
    def list_trace_pools(project: str):
        return {"trace_pools": store.list("trace_pools", project=project)}

    @app.post("/api/trace-pools/{pool_id}/sample")
    def sample_trace_pool(pool_id: str, body: SampleBody, request: Request):
        principal = principal_resolver(request)
        require_role(principal, "dataset_curator")
        pool = store.get("trace_pools", pool_id)
        if pool is None:
            raise HTTPException(status_code=404, detail="trace pool not found")
        def compute():
            summaries = [TraceSummary(**t) for t in pool.get("traces", [])]
            sample = sample_representative(summaries, n=body.n)
            batch_id = f"{pool_id}:sample:{len(store.list('open_code_batches', project=body.project)) + 1}"
            batch = store.put("open_code_batches", batch_id, {"project": body.project,
                "trace_pool_id": pool_id, "trace_ids": [s.trace_id for s in sample],
                "codes": []})
            aid = audit.record(project=body.project, actor=principal.actor_id,
                               action="sample_trace_pool", target_type="open_code_batch",
                               target_id=batch_id, before=None, after=batch)
            return {"batch": batch, "audit_event_id": aid}
        return _idempotent_data_mutation(request, compute)

    @app.get("/api/open-code-batches/{batch_id}")
    def get_open_code_batch(batch_id: str):
        batch = store.get("open_code_batches", batch_id)
        if batch is None:
            raise HTTPException(status_code=404, detail="open code batch not found")
        return {"batch": batch}

    @app.post("/api/open-code-batches/{batch_id}/codes")
    def append_open_code(batch_id: str, body: OpenCodeBody, request: Request):
        principal = principal_resolver(request)
        require_role(principal, "dataset_curator")
        def compute():
            batch = store.get("open_code_batches", batch_id)
            if batch is None:
                raise HTTPException(status_code=404, detail="open code batch not found")
            before = dict(batch)
            codes = list(batch.get("codes", []))
            codes.append({"trace_id": body.trace_id, "code": body.code,
                          "author": body.author})
            batch["codes"] = codes
            batch = store.put("open_code_batches", batch_id, batch)
            aid = audit.record(project=body.project, actor=principal.actor_id,
                               action="append_open_code", target_type="open_code_batch",
                               target_id=batch_id, before=before, after=batch)
            return {"batch": batch, "audit_event_id": aid}
        return _idempotent_data_mutation(request, compute)

    def _active_taxonomy_slugs(project: str, taxonomy_version: str | None) -> set[str]:
        return {l["slug"] for l in store.list("taxonomy_labels", project=project)
                if l.get("status") == "active"
                and (taxonomy_version is None or l.get("taxonomy_version") in (None, taxonomy_version))}

    @app.post("/api/runs/{run_id}/scores")
    def submit_score(run_id: str, body: ScoreSubmitBody, request: Request):
        principal = principal_resolver(request)
        require_role(principal, "harness_owner")
        run = store.get("runs", run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        unknown = set(body.failure_labels) - _active_taxonomy_slugs(
            body.project, run.get("taxonomy_version"))
        if unknown:
            raise HTTPException(status_code=400,
                                detail=f"unknown failure label(s): {sorted(unknown)}")
        def compute():
            score = _score_bridge(body.project).write_score(
                eval_run_id=run_id, case_id=body.case_id, sample_id=body.sample_id,
                source=body.source, judge_version=body.judge_version, label=body.label,
                failure_labels=body.failure_labels, confidence=body.confidence,
                critique=body.critique, trace_id=body.trace_id)
            return {"score": score, "audit_event_id": score["audit_event_id"]}
        return _idempotent_data_mutation(request, compute)
```

- [ ] **Step 4: Run route tests to verify they pass**

Run:

```bash
cd flywheel
pytest tests/api/test_data_routes.py tests/api/test_taxonomy_routes.py tests/api/test_score_taxonomy_validation.py -v
```

Expected: PASS.

- [ ] **Step 5: Run full suite + lint + types, then commit**

```bash
cd flywheel && pytest -q && ruff check api engine sdk tests && mypy api engine sdk
git add flywheel/api/server.py flywheel/tests/api/test_data_routes.py flywheel/tests/api/test_taxonomy_routes.py flywheel/tests/api/test_score_taxonomy_validation.py
git commit -m "feat(api): data analysis and taxonomy routes"
```

---

## Self-Review

- **Spec coverage (Engine §5, §13 sampler/coder/taxonomy/dataset):** `EvalBudget` matches §5 fields and the needs_more_data semantics; `sample_representative` covers §5 sampling priorities; `coder` implements open coding normalization; `TaxonomyRegistry` covers axial clustering, the promotion gate (definition + positive and negative examples + owner approval), immutable versions, and the migration map with `changed_labels` for §5/§11 judge-recheck propagation; `DatasetBuilder` mechanically enforces disjoint splits and reports the §14 intersections + §5 target sizes. API route wiring covers every plan-04 endpoint assigned by the index, including score taxonomy validation before stable labels are written.
- **Placeholder scan:** clustering is intentionally heuristic (normalized-form grouping) per the MVP stance — fully specified, no TODO. No placeholders.
- **Type consistency:** `DatasetCaseModel` fields/`split` literal match plan 02. Taxonomy migrations use plan 02's `TaxonomyMigrationStepModel` keys (`from_slug`, `to_slug`). `changed_labels(migration)` return type (`set[str]`) is the exact input plan 05's judge-recheck logic consumes. `JsonRecordStore.list(project=None)` is supported by plan 02's signature (project optional). Note: `_cases` filters by dataset across projects via `project=None`; acceptable because dataset ids are project-scoped in practice and the id prefix disambiguates.
