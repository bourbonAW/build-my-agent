# Flywheel 06 — L3 Analysis Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the L3 analysis engine: multi-signal failure clustering, root-cause attribution producing `FailureIssue` records, `ImprovementProposal` generation that records every consumed case (not just cited examples), `candidate_hypothesis_id` identity, target-file conflict detection, and coding-agent handoff Markdown generation.

**Architecture:** `flywheel/engine/{analyzer,proposer,handoff,writer}.py`. The analyzer consumes only redacted evidence (via plan 03 `EvidenceReader`), never raw. Clustering is deterministic/multi-signal in MVP (no LLM dependency in unit tests). Proposals capture `consumed_case_ids` for holdout integrity (plan 07). Synchronous.

**Tech Stack:** Python 3.13, pydantic v2, pytest.

## Global Constraints

(See `2026-06-23-flywheel-00-index.md`.) Most relevant here:
- L3 never receives raw payloads — evidence comes from plan 03 `EvidenceReader` (redacted only).
- `consumed_case_ids` records **every case visible to the proposer**, not only cited examples (Engine §13). Plan 07 excludes these from holdout.
- `candidate_hypothesis_id` default identity = `proposal_id + candidate_fingerprint`; re-runs (retry/judge migration/baseline re-score) do **not** create a new hypothesis; a material fingerprint change does.
- `target_files` conflict detection is a human gate in MVP; `target_symbols`/`prompt_sections` are optional refinements.
- Human gates: proposal generation produces a `draft` proposal; approval is a separate human action (plan 02 lifecycle + plan 08 UI).

---

## File Structure

- Create: `flywheel/engine/analyzer.py` — multi-signal clustering + root-cause attribution → `FailureIssue`
- Create: `flywheel/engine/proposer.py` — `ImprovementProposal` generation, `candidate_hypothesis_id`, conflict detection
- Create: `flywheel/engine/handoff.py` — coding-agent handoff Markdown
- Create: `flywheel/engine/writer.py` — persists issues/proposals/handoffs to State Store
- Test: mirrors under `flywheel/tests/engine/`

**Interfaces consumed:** `FailureIssueModel`, `ImprovementProposalModel`, `ProposedChangeModel`, `HandoffModel` (plan 02 schemas); `JsonRecordStore` (plan 02); `EvidenceReader` (plan 03).

---

## Task 1: Multi-signal failure clustering

**Files:**
- Create: `flywheel/engine/analyzer.py`
- Test: `flywheel/tests/engine/test_analyzer_cluster.py`

**Interfaces:**
- Produces:
  - `@dataclass class FailureObservation` with `case_id`, `trace_id`, `taxonomy_labels: list[str]`, `tool_name: str | None`, `tool_error: str | None`, `dataset_split: str`, `critique: str`, `harness_fingerprint: str`, `redaction_state: str`, `open_codes: list[str]`, `case_intent: str`, `repeated_trace_features: list[str]`.
  - `@dataclass class FailureCluster` with `cluster_id: str`, `members: list[FailureObservation]`, `shared_labels: list[str]`, `dominant_tool: str | None`.
  - `cluster_failures(observations: list[FailureObservation]) -> list[FailureCluster]` — Engine §13 "do not cluster only by top-level label": clusters by composite key (sorted taxonomy labels + normalized open codes + tool_name + tool_error bucket + case intent + dataset split + critique bucket + harness fingerprint + repeated trace features + redaction state), excludes `redaction_state == "blocked"` observations, assigns stable `cluster_id` (`clu_` + short hash of the key). Deterministic.

- [ ] **Step 1: Write the failing test**

```python
# flywheel/tests/engine/test_analyzer_cluster.py
from engine.analyzer import FailureObservation, cluster_failures


def _obs(case_id, labels, tool, err, redaction="redacted", *,
         intent="edit_file", harness="fp1"):
    return FailureObservation(
        case_id=case_id, trace_id=f"t_{case_id}", taxonomy_labels=labels,
        tool_name=tool, tool_error=err, dataset_split="regression_holdout",
        critique="missing offset", harness_fingerprint=harness, redaction_state=redaction,
        open_codes=["missing offset explanation"], case_intent=intent,
        repeated_trace_features=["read_file:error"],
    )


def test_clusters_by_composite_signal_not_only_label():
    obs = [
        _obs("c1", ["tool_argument_error"], "read_file", "bad offset"),
        _obs("c2", ["tool_argument_error"], "read_file", "bad offset"),
        _obs("c3", ["tool_argument_error"], "web_fetch", "timeout"),
    ]
    clusters = cluster_failures(obs)
    # same label but different tool/error -> different clusters
    assert len(clusters) == 2
    sizes = sorted(len(c.members) for c in clusters)
    assert sizes == [1, 2]


def test_same_label_tool_splits_by_intent():
    obs = [
        _obs("c1", ["tool_argument_error"], "read_file", "bad offset", intent="edit_file"),
        _obs("c2", ["tool_argument_error"], "read_file", "bad offset", intent="summarize_file"),
    ]
    assert len(cluster_failures(obs)) == 2


def test_same_label_tool_splits_by_harness_fingerprint():
    obs = [
        _obs("c1", ["tool_argument_error"], "read_file", "bad offset", harness="fp_old"),
        _obs("c2", ["tool_argument_error"], "read_file", "bad offset", harness="fp_new"),
    ]
    assert len(cluster_failures(obs)) == 2


def test_blocked_evidence_excluded():
    obs = [
        _obs("c1", ["tool_argument_error"], "read_file", "bad offset"),
        _obs("c2", ["tool_argument_error"], "read_file", "bad offset", redaction="blocked"),
    ]
    clusters = cluster_failures(obs)
    members = [m for c in clusters for m in c.members]
    assert all(m.redaction_state != "blocked" for m in members)
    assert len(members) == 1


def test_cluster_id_is_deterministic():
    obs = [_obs("c1", ["x"], "t", "e"), _obs("c2", ["x"], "t", "e")]
    a = cluster_failures(obs)[0].cluster_id
    b = cluster_failures(obs)[0].cluster_id
    assert a == b and a.startswith("clu_")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd flywheel && pytest tests/engine/test_analyzer_cluster.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.analyzer'`.

- [ ] **Step 3: Write minimal implementation**

```python
# flywheel/engine/analyzer.py
"""Multi-signal failure clustering and root-cause attribution (Engine §13)."""
from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass, field


@dataclass
class FailureObservation:
    case_id: str
    trace_id: str
    taxonomy_labels: list[str]
    tool_name: str | None
    tool_error: str | None
    dataset_split: str
    critique: str
    harness_fingerprint: str
    redaction_state: str
    open_codes: list[str] = field(default_factory=list)
    case_intent: str = ""
    repeated_trace_features: list[str] = field(default_factory=list)


@dataclass
class FailureCluster:
    cluster_id: str
    members: list[FailureObservation]
    shared_labels: list[str]
    dominant_tool: str | None


def _composite_key(obs: FailureObservation) -> str:
    labels = ",".join(sorted(obs.taxonomy_labels))
    open_codes = ",".join(sorted(_bucket_text(c) for c in obs.open_codes))
    critique_bucket = _bucket_text(obs.critique)
    features = ",".join(sorted(obs.repeated_trace_features))
    error_bucket = _bucket_text(obs.tool_error or "")
    return "|".join([
        labels, open_codes, obs.tool_name or "", error_bucket,
        obs.case_intent, obs.dataset_split, critique_bucket,
        obs.harness_fingerprint, features, obs.redaction_state,
    ])


def _bucket_text(text: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    # deterministic shallow similarity bucket: first meaningful tokens are enough
    # to avoid over-merging unrelated critiques in MVP.
    return " ".join(normalized.split()[:4])


def cluster_failures(observations: list[FailureObservation]) -> list[FailureCluster]:
    buckets: dict[str, list[FailureObservation]] = {}
    for obs in observations:
        if obs.redaction_state == "blocked":
            continue  # blocked evidence excluded from analysis (Engine §10)
        buckets.setdefault(_composite_key(obs), []).append(obs)
    clusters: list[FailureCluster] = []
    for key, members in buckets.items():
        cluster_id = "clu_" + hashlib.sha256(key.encode()).hexdigest()[:10]
        shared = sorted(set.intersection(
            *(set(m.taxonomy_labels) for m in members)) if members else set())
        tool_counts = Counter(m.tool_name for m in members if m.tool_name)
        dominant = tool_counts.most_common(1)[0][0] if tool_counts else None
        clusters.append(FailureCluster(cluster_id=cluster_id, members=members,
                                       shared_labels=shared, dominant_tool=dominant))
    return clusters
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd flywheel && pytest tests/engine/test_analyzer_cluster.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add flywheel/engine/analyzer.py flywheel/tests/engine/test_analyzer_cluster.py
git commit -m "feat(engine): multi-signal failure clustering"
```

---

## Task 2: Root-cause attribution → FailureIssue

**Files:**
- Modify: `flywheel/engine/analyzer.py` (append `attribute_root_cause`)
- Test: `flywheel/tests/engine/test_analyzer_issue.py`

**Interfaces:**
- Consumes: `FailureCluster`.
- Produces:
  - `@dataclass class FailureIssue` with `issue_id`, `title`, `taxonomy_labels: list[str]`, `affected_case_ids: list[str]`, `evidence_trace_ids: list[str]`, `root_cause_hypothesis: str`, `confidence: float`, `counterexample_case_ids: list[str]`.
  - `attribute_root_cause(cluster: FailureCluster, *, counterexamples: list[str] | None = None) -> FailureIssue` — builds an issue from a cluster: title from shared labels + dominant tool; `confidence = min(1.0, len(members)/5)` (more evidence → higher confidence, capped); `root_cause_hypothesis` templated from the dominant tool/error and shared labels. `issue_id = "iss_" + cluster_id[4:]`.

- [ ] **Step 1: Write the failing test**

```python
# flywheel/tests/engine/test_analyzer_issue.py
from engine.analyzer import FailureObservation, cluster_failures, attribute_root_cause


def _obs(case_id):
    return FailureObservation(
        case_id=case_id, trace_id=f"t_{case_id}",
        taxonomy_labels=["tool_argument_error"], tool_name="read_file",
        tool_error="bad offset", dataset_split="regression_holdout",
        critique="missing offset", harness_fingerprint="fp1", redaction_state="redacted",
    )


def test_issue_from_cluster():
    cluster = cluster_failures([_obs("c1"), _obs("c2")])[0]
    issue = attribute_root_cause(cluster, counterexamples=["c9"])
    assert issue.issue_id.startswith("iss_")
    assert set(issue.affected_case_ids) == {"c1", "c2"}
    assert "read_file" in issue.title or "tool_argument_error" in issue.title
    assert 0.0 < issue.confidence <= 1.0
    assert issue.counterexample_case_ids == ["c9"]


def test_confidence_scales_with_evidence():
    small = attribute_root_cause(cluster_failures([_obs("c1")])[0])
    big = attribute_root_cause(cluster_failures([_obs(f"c{i}") for i in range(6)])[0])
    assert big.confidence > small.confidence
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd flywheel && pytest tests/engine/test_analyzer_issue.py -v`
Expected: FAIL with `ImportError: cannot import name 'attribute_root_cause'`.

- [ ] **Step 3: Append implementation to `analyzer.py`**

```python
# flywheel/engine/analyzer.py  (append)
@dataclass
class FailureIssue:
    issue_id: str
    title: str
    taxonomy_labels: list[str]
    affected_case_ids: list[str]
    evidence_trace_ids: list[str]
    root_cause_hypothesis: str
    confidence: float
    counterexample_case_ids: list[str]


def attribute_root_cause(cluster: FailureCluster, *,
                         counterexamples: list[str] | None = None) -> FailureIssue:
    labels = cluster.shared_labels or sorted(
        {l for m in cluster.members for l in m.taxonomy_labels})
    tool = cluster.dominant_tool
    title_bits = [b for b in (tool, *labels) if b]
    title = " / ".join(title_bits) or "uncategorized failure"
    errors = sorted({m.tool_error for m in cluster.members if m.tool_error})
    hypothesis = (
        f"Failures share labels {labels}"
        + (f" on tool '{tool}'" if tool else "")
        + (f" with errors {errors}" if errors else "")
        + "; likely a systematic harness defect rather than isolated noise."
    )
    return FailureIssue(
        issue_id="iss_" + cluster.cluster_id[4:],
        title=title,
        taxonomy_labels=labels,
        affected_case_ids=[m.case_id for m in cluster.members],
        evidence_trace_ids=[m.trace_id for m in cluster.members],
        root_cause_hypothesis=hypothesis,
        confidence=min(1.0, len(cluster.members) / 5),
        counterexample_case_ids=counterexamples or [],
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd flywheel && pytest tests/engine/test_analyzer_issue.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add flywheel/engine/analyzer.py flywheel/tests/engine/test_analyzer_issue.py
git commit -m "feat(engine): root-cause attribution producing FailureIssue"
```

---

## Task 3: ImprovementProposal generation + candidate_hypothesis_id + conflict detection

**Files:**
- Create: `flywheel/engine/proposer.py`
- Test: `flywheel/tests/engine/test_proposer.py`

**Interfaces:**
- Consumes: `FailureIssue` (`engine.analyzer`); `ProposedChangeModel`, `ImprovementProposalModel` (plan 02 schemas).
- Produces:
  - `candidate_hypothesis_id(proposal_id: str, candidate_fingerprint: str) -> str` — Engine §13 default identity `f"{proposal_id}::{candidate_fingerprint}"`.
  - `@dataclass class ProposalDraft` mirroring `ImprovementProposalModel` fields needed at draft time.
  - `class Proposer`:
    - `generate(*, project, proposal_id, baseline_fingerprint, baseline_generation, source_eval_run_id, taxonomy_version, issues: list[FailureIssue], changes: list[ProposedChangeModel], consumed_case_ids: list[str], consumed_trace_ids: list[str], candidate_fingerprint: str, proposer_id: str, expected_metric_delta: dict[str, float], rollback_plan: str) -> ImprovementProposalModel` — builds the proposal with `consumed_case_ids` = the **union of every case visible** and `consumed_trace_ids` = every trace visible to the proposer. Both lists are passed in explicitly. Case ids must be a superset of issue affected cases, and trace ids must cover issue evidence trace ids (Engine §13 evidence lineage invariant). `target_files` = sorted unique `change.target_file`, `candidate_hypothesis_id` computed, `state="draft"`. Raises `ValueError` if any issue's affected case or evidence trace is missing from the consumed lists.
    - `detect_conflicts(a: ImprovementProposalModel, b: ImprovementProposalModel) -> list[str]` — returns the intersection of `target_files` (Engine §13: overlapping target files cannot publish concurrently). Empty list = no conflict.

- [ ] **Step 1: Write the failing test**

```python
# flywheel/tests/engine/test_proposer.py
import pytest
from api.schemas import ProposedChangeModel
from engine.analyzer import FailureIssue
from engine.proposer import Proposer, candidate_hypothesis_id


def _issue():
    return FailureIssue(issue_id="iss_1", title="t", taxonomy_labels=["x"],
        affected_case_ids=["c1", "c2"], evidence_trace_ids=["t1"],
        root_cause_hypothesis="h", confidence=0.6, counterexample_case_ids=[])


def _change(target="src/prompt.md"):
    return ProposedChangeModel(change_type="prompt", target_file=target,
        description="d", rationale="r", evidence_trace_ids=["t1"],
        evidence_case_ids=["c1"], suggested_diff="diff", risk_level="medium")


def test_hypothesis_id_identity():
    assert candidate_hypothesis_id("p1", "fpA") == "p1::fpA"


def test_generate_collects_consumed_and_target_files():
    p = Proposer().generate(
        project="bourbon", proposal_id="p1", baseline_fingerprint="fp0",
        baseline_generation=1, source_eval_run_id="run1", taxonomy_version="tax1",
        issues=[_issue()], changes=[_change("src/a.md"), _change("src/b.md")],
        consumed_case_ids=["c1", "c2", "c3"], consumed_trace_ids=["t1", "t2"],
        candidate_fingerprint="fpA", proposer_id="engine",
        expected_metric_delta={"pass_rate": 0.05}, rollback_plan="revert",
    )
    assert p.target_files == ["src/a.md", "src/b.md"]
    assert p.consumed_case_ids == ["c1", "c2", "c3"]
    assert p.consumed_trace_ids == ["t1", "t2"]
    assert p.candidate_hypothesis_id == "p1::fpA"
    assert p.state == "draft"


def test_generate_rejects_consumed_missing_affected_case():
    with pytest.raises(ValueError, match="consumed"):
        Proposer().generate(
            project="bourbon", proposal_id="p1", baseline_fingerprint="fp0",
            baseline_generation=1, source_eval_run_id="run1", taxonomy_version="tax1",
            issues=[_issue()], changes=[_change()],
            consumed_case_ids=["c1"],  # missing c2
            consumed_trace_ids=["t1"], candidate_fingerprint="fpA", proposer_id="engine",
            expected_metric_delta={}, rollback_plan="revert")


def test_generate_rejects_consumed_missing_evidence_trace():
    with pytest.raises(ValueError, match="trace"):
        Proposer().generate(
            project="bourbon", proposal_id="p1", baseline_fingerprint="fp0",
            baseline_generation=1, source_eval_run_id="run1", taxonomy_version="tax1",
            issues=[_issue()], changes=[_change()],
            consumed_case_ids=["c1", "c2"], consumed_trace_ids=[],
            candidate_fingerprint="fpA", proposer_id="engine",
            expected_metric_delta={}, rollback_plan="revert")


def test_detect_conflicts_on_overlapping_files():
    pr = Proposer()
    a = pr.generate(project="bourbon", proposal_id="p1", baseline_fingerprint="fp0",
        baseline_generation=1, source_eval_run_id="r", taxonomy_version="t",
        issues=[_issue()], changes=[_change("src/shared.md")],
        consumed_case_ids=["c1", "c2"], consumed_trace_ids=["t1"],
        candidate_fingerprint="fpA", proposer_id="e", expected_metric_delta={},
        rollback_plan="x")
    b = pr.generate(project="bourbon", proposal_id="p2", baseline_fingerprint="fp0",
        baseline_generation=1, source_eval_run_id="r", taxonomy_version="t",
        issues=[_issue()], changes=[_change("src/shared.md")],
        consumed_case_ids=["c1", "c2"], consumed_trace_ids=["t1"],
        candidate_fingerprint="fpB", proposer_id="e", expected_metric_delta={},
        rollback_plan="x")
    assert pr.detect_conflicts(a, b) == ["src/shared.md"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd flywheel && pytest tests/engine/test_proposer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.proposer'`.

- [ ] **Step 3: Write minimal implementation**

```python
# flywheel/engine/proposer.py
"""ImprovementProposal generation, hypothesis identity, conflict detection (Engine §13)."""
from __future__ import annotations

from api.schemas import ImprovementProposalModel, ProposedChangeModel
from engine.analyzer import FailureIssue


def candidate_hypothesis_id(proposal_id: str, candidate_fingerprint: str) -> str:
    # Engine §13: default identity = proposal_id + candidate_fingerprint
    return f"{proposal_id}::{candidate_fingerprint}"


class Proposer:
    def generate(self, *, project: str, proposal_id: str, baseline_fingerprint: str,
                 baseline_generation: int, source_eval_run_id: str,
                 taxonomy_version: str, issues: list[FailureIssue],
                 changes: list[ProposedChangeModel], consumed_case_ids: list[str],
                 consumed_trace_ids: list[str], candidate_fingerprint: str, proposer_id: str,
                 expected_metric_delta: dict[str, float],
                 rollback_plan: str) -> ImprovementProposalModel:
        consumed = set(consumed_case_ids)
        affected = {c for issue in issues for c in issue.affected_case_ids}
        missing = affected - consumed
        if missing:
            raise ValueError(
                f"consumed_case_ids must include every visible case; missing {sorted(missing)}")
        consumed_traces = set(consumed_trace_ids)
        evidence_traces = {t for issue in issues for t in issue.evidence_trace_ids}
        missing_traces = evidence_traces - consumed_traces
        if missing_traces:
            raise ValueError(
                f"consumed_trace_ids must include every visible evidence trace; "
                f"missing {sorted(missing_traces)}")
        target_files = sorted({c.target_file for c in changes})
        return ImprovementProposalModel(
            project=project, id=proposal_id,
            baseline_fingerprint=baseline_fingerprint,
            baseline_generation=baseline_generation,
            candidate_hypothesis_id=candidate_hypothesis_id(proposal_id, candidate_fingerprint),
            source_eval_run_id=source_eval_run_id, taxonomy_version=taxonomy_version,
            failure_issues=[i.issue_id for i in issues],
            proposed_changes=changes, target_files=target_files,
            consumed_case_ids=list(consumed_case_ids),
            consumed_trace_ids=list(consumed_trace_ids),
            proposer_id=proposer_id, expected_metric_delta=expected_metric_delta,
            rollback_plan=rollback_plan, state="draft",
        )

    def detect_conflicts(self, a: ImprovementProposalModel,
                         b: ImprovementProposalModel) -> list[str]:
        return sorted(set(a.target_files) & set(b.target_files))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd flywheel && pytest tests/engine/test_proposer.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add flywheel/engine/proposer.py flywheel/tests/engine/test_proposer.py
git commit -m "feat(engine): proposal generation, hypothesis identity, conflict detection"
```

---

## Task 4: Coding-agent handoff Markdown

**Files:**
- Create: `flywheel/engine/handoff.py`
- Test: `flywheel/tests/engine/test_handoff.py`

**Interfaces:**
- Consumes: `ImprovementProposalModel` (plan 02 schemas).
- Produces:
  - `generate_handoff_markdown(proposal: ImprovementProposalModel) -> str` — produces a Markdown handoff doc containing: title with proposal id, baseline fingerprint/generation, the rollback plan, a per-change section (target file, change type, risk, rationale, suggested diff in a fenced block), the expected metric delta, and an explicit "DO NOT touch holdout cases" note listing `consumed_case_ids`. Deterministic.

- [ ] **Step 1: Write the failing test**

```python
# flywheel/tests/engine/test_handoff.py
from api.schemas import ImprovementProposalModel, ProposedChangeModel
from engine.handoff import generate_handoff_markdown


def _proposal():
    return ImprovementProposalModel(
        project="bourbon", id="p1", baseline_fingerprint="fp0", baseline_generation=1,
        candidate_hypothesis_id="p1::fpA", source_eval_run_id="run1",
        taxonomy_version="tax1", failure_issues=["iss_1"],
        proposed_changes=[ProposedChangeModel(change_type="prompt",
            target_file="src/prompt.md", description="clarify offset",
            rationale="agents misread offset", evidence_trace_ids=["t1"],
            evidence_case_ids=["c1"], suggested_diff="- old\n+ new", risk_level="medium")],
        target_files=["src/prompt.md"], consumed_case_ids=["c1", "c2"],
        consumed_trace_ids=[], proposer_id="engine",
        expected_metric_delta={"pass_rate": 0.05}, rollback_plan="git revert <sha>")


def test_handoff_contains_key_sections():
    md = generate_handoff_markdown(_proposal())
    assert "# Handoff: p1" in md
    assert "fp0" in md and "generation 1" in md.lower()
    assert "src/prompt.md" in md
    assert "- old\n+ new" in md
    assert "git revert <sha>" in md
    assert "pass_rate" in md
    assert "c1" in md and "c2" in md  # consumed cases warning


def test_handoff_is_deterministic():
    assert generate_handoff_markdown(_proposal()) == generate_handoff_markdown(_proposal())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd flywheel && pytest tests/engine/test_handoff.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.handoff'`.

- [ ] **Step 3: Write minimal implementation**

```python
# flywheel/engine/handoff.py
"""Coding-agent handoff Markdown generation (Engine §13)."""
from __future__ import annotations

from api.schemas import ImprovementProposalModel


def generate_handoff_markdown(proposal: ImprovementProposalModel) -> str:
    lines: list[str] = []
    lines.append(f"# Handoff: {proposal.id}")
    lines.append("")
    lines.append(f"- Baseline fingerprint: `{proposal.baseline_fingerprint}`")
    lines.append(f"- Baseline generation: {proposal.baseline_generation}")
    lines.append(f"- Source eval run: `{proposal.source_eval_run_id}`")
    lines.append(f"- Taxonomy version: `{proposal.taxonomy_version}`")
    lines.append(f"- Linked issues: {', '.join(proposal.failure_issues)}")
    lines.append("")
    lines.append("## Proposed Changes")
    for i, change in enumerate(proposal.proposed_changes, start=1):
        lines.append("")
        lines.append(f"### {i}. `{change.target_file}` ({change.change_type}, "
                     f"risk: {change.risk_level})")
        lines.append(f"**Description:** {change.description}")
        lines.append(f"**Rationale:** {change.rationale}")
        lines.append("")
        lines.append("```diff")
        lines.append(change.suggested_diff)
        lines.append("```")
    lines.append("")
    lines.append("## Expected Metric Delta")
    for metric, delta in sorted(proposal.expected_metric_delta.items()):
        lines.append(f"- {metric}: {delta:+.4f}")
    lines.append("")
    lines.append("## Rollback Plan")
    lines.append(proposal.rollback_plan)
    lines.append("")
    lines.append("## DO NOT touch holdout cases")
    lines.append("These cases were consumed during analysis and must be excluded "
                 "from regression holdout:")
    lines.append(", ".join(proposal.consumed_case_ids))
    lines.append("")
    return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd flywheel && pytest tests/engine/test_handoff.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add flywheel/engine/handoff.py flywheel/tests/engine/test_handoff.py
git commit -m "feat(engine): coding-agent handoff Markdown generation"
```

---

## Task 5: Writer — persist issues, proposals, handoffs

**Files:**
- Create: `flywheel/engine/writer.py`
- Test: `flywheel/tests/engine/test_writer.py`

**Interfaces:**
- Consumes: `JsonRecordStore` (plan 02), `FailureIssue` (`engine.analyzer`), `ImprovementProposalModel`, `HandoffModel` (plan 02 schemas).
- Produces:
  - `class EngineWriter(store: JsonRecordStore)`:
    - `store_issue(project: str, issue: FailureIssue) -> dict` (collection `"issues"`).
    - `store_proposal(proposal: ImprovementProposalModel) -> dict` (collection `"proposals"`).
    - `store_handoff(project: str, proposal_id: str, markdown: str) -> dict` (collection `"handoffs"`, id = `f"{proposal_id}:handoff"`).

- [ ] **Step 1: Write the failing test**

```python
# flywheel/tests/engine/test_writer.py
from api.store import JsonRecordStore
from api.schemas import ImprovementProposalModel
from engine.analyzer import FailureIssue
from engine.writer import EngineWriter


def test_store_issue_and_proposal_and_handoff(tmp_path):
    w = EngineWriter(JsonRecordStore(root=tmp_path))
    issue = FailureIssue(issue_id="iss_1", title="t", taxonomy_labels=["x"],
        affected_case_ids=["c1"], evidence_trace_ids=["t1"],
        root_cause_hypothesis="h", confidence=0.6, counterexample_case_ids=[])
    assert w.store_issue("bourbon", issue)["title"] == "t"

    proposal = ImprovementProposalModel(project="bourbon", id="p1",
        baseline_fingerprint="fp0", baseline_generation=1,
        candidate_hypothesis_id="p1::fpA", source_eval_run_id="run1",
        taxonomy_version="tax1", failure_issues=["iss_1"], proposed_changes=[],
        target_files=[], consumed_case_ids=["c1"], consumed_trace_ids=[],
        proposer_id="engine", expected_metric_delta={}, rollback_plan="x")
    assert w.store_proposal(proposal)["id"] == "p1"

    h = w.store_handoff("bourbon", "p1", "# Handoff: p1")
    assert h["markdown"].startswith("# Handoff")
    assert h["id"] == "p1:handoff"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd flywheel && pytest tests/engine/test_writer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.writer'`.

- [ ] **Step 3: Write minimal implementation**

```python
# flywheel/engine/writer.py
"""Persist engine outputs (issues, proposals, handoffs) to the State Store."""
from __future__ import annotations

from dataclasses import asdict

from api.schemas import ImprovementProposalModel
from api.store import JsonRecordStore
from engine.analyzer import FailureIssue


class EngineWriter:
    def __init__(self, store: JsonRecordStore):
        self._store = store

    def store_issue(self, project: str, issue: FailureIssue) -> dict:
        row = {"project": project, **asdict(issue)}
        return self._store.put("issues", issue.issue_id, row)

    def store_proposal(self, proposal: ImprovementProposalModel) -> dict:
        return self._store.put("proposals", proposal.id, proposal.model_dump())

    def store_handoff(self, project: str, proposal_id: str, markdown: str) -> dict:
        handoff_id = f"{proposal_id}:handoff"
        return self._store.put("handoffs", handoff_id, {
            "project": project, "proposal_id": proposal_id, "markdown": markdown,
        })
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd flywheel && pytest tests/engine/test_writer.py -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Run full suite + lint + types, then commit**

```bash
cd flywheel && pytest -q && ruff check api engine sdk tests && mypy api engine sdk
git add flywheel/engine/writer.py flywheel/tests/engine/test_writer.py
git commit -m "feat(engine): writer persists issues, proposals, handoffs"
```

---

## Task 6: Analysis orchestration through EvidenceReader

**Files:**
- Create: `flywheel/engine/orchestrator.py`
- Test: `flywheel/tests/engine/test_analysis_orchestrator.py`

**Interfaces:**
- Consumes: `EvidenceReader.fetch_redacted_failed_evidence()` (plan 03), `RedactionAnalytics` (plan 03), `JudgeService` (plan 05), `cluster_failures`, `attribute_root_cause`, `Proposer`, `EngineWriter`, `ProposedChangeModel`, `JsonRecordStore`.
- Produces:
  - `class AnalysisEngine(store, reader, writer, proposer, redaction_analytics)`:
    - `trigger_analysis(project: str, eval_run_id: str) -> dict` — validates the run has `dataset_id`, `dataset_version`, `taxonomy_version`, `judge_version`, `harness_fingerprint`, `baseline_generation`, and `baseline_fingerprint`; validates the referenced judge exists with `status == "validated"` before automated proposal generation; derives failed cases from synced annotations plus dataset cases; fetches evidence only through `EvidenceReader.fetch_redacted_failed_evidence()`.
    - If all failed evidence is missing/blocked, or missing/blocked evidence materially reduces coverage, update the run state to `needs_more_data`, persist a redaction report with `missing_trace_ids`, and return `{"state": "needs_more_data", ...}`. Never bypass redaction.
    - Otherwise build `FailureObservation`s from redacted payload summaries + annotation/dataset metadata, cluster, store `FailureIssue`s, generate one draft `ImprovementProposal`, store it, set run state to `under_review`, and return stored issue/proposal ids.

- [ ] **Step 1: Write the failing test**

```python
# flywheel/tests/engine/test_analysis_orchestrator.py
from api.redaction import RedactionAnalytics, RedactionResult
from api.schemas import ProposedChangeModel
from api.store import JsonRecordStore
from engine.orchestrator import AnalysisEngine
from engine.proposer import Proposer
from engine.writer import EngineWriter


class FakeReader:
    def __init__(self, *, missing=False):
        self.missing = missing
        self.requested = []

    def fetch_redacted_failed_evidence(self, trace_ids):
        self.requested = list(trace_ids)
        if self.missing:
            return [], [], list(trace_ids)
        return (
            [{"trace_id": "t1", "tool_name": "read_file", "tool_error": "bad offset",
              "repeated_trace_features": ["read_file:error"]}],
            [RedactionResult(state="redacted", payload={}, policy_version="v1",
                             redacted_field_count=0, coverage=1.0)],
            [],
        )


def _store(tmp_path):
    store = JsonRecordStore(root=tmp_path)
    store.put("runs", "run1", {"project": "bourbon", "id": "run1",
        "state": "auto_analysis_ready", "dataset_id": "ds1", "dataset_version": "v1",
        "taxonomy_version": "tax1", "judge_version": "jv1",
        "harness_fingerprint": "fp0", "baseline_fingerprint": "fp0",
        "baseline_generation": 1})
    store.put("judges", "bourbon:jv1", {"project": "bourbon", "id": "bourbon:jv1",
        "judge_version": "jv1", "status": "validated", "task_family": "tool_use"})
    store.put("dataset_cases", "ds1:v1:c1", {"project": "bourbon",
        "dataset_id": "ds1", "dataset_version": "v1", "case_id": "c1",
        "task_family": "tool_use", "source_trace_ids": ["t1"],
        "intent_summary": "edit file", "split": "regression_holdout"})
    store.put("annotations", "ann1", {"project": "bourbon", "id": "ann1",
        "eval_run_id": "run1", "case_id": "c1", "sample_id": "s0",
        "label": "fail", "source": "human", "failure_labels": ["tool_argument_error"],
        "confidence": 0.9, "critique": "missing offset"})
    return store


def test_trigger_analysis_fetches_redacted_evidence_and_stores_outputs(tmp_path):
    store = _store(tmp_path)
    reader = FakeReader()
    engine = AnalysisEngine(store, reader, EngineWriter(store), Proposer(),
                            RedactionAnalytics(store))
    out = engine.trigger_analysis(project="bourbon", eval_run_id="run1")
    assert reader.requested == ["t1"]
    assert out["state"] == "under_review"
    assert len(out["issue_ids"]) == 1
    assert len(out["proposal_ids"]) == 1
    proposal = store.get("proposals", out["proposal_ids"][0])
    assert proposal["consumed_case_ids"] == ["c1"]
    assert proposal["consumed_trace_ids"] == ["t1"]


def test_missing_evidence_marks_run_needs_more_data(tmp_path):
    store = _store(tmp_path)
    engine = AnalysisEngine(store, FakeReader(missing=True), EngineWriter(store),
                            Proposer(), RedactionAnalytics(store))
    out = engine.trigger_analysis(project="bourbon", eval_run_id="run1")
    assert out["state"] == "needs_more_data"
    assert store.get("runs", "run1")["state"] == "needs_more_data"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd flywheel && pytest tests/engine/test_analysis_orchestrator.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.orchestrator'`.

- [ ] **Step 3: Write minimal implementation**

```python
# flywheel/engine/orchestrator.py
"""Analysis orchestration: redacted evidence -> issues -> proposal draft."""
from __future__ import annotations

import uuid

from api.schemas import ProposedChangeModel
from api.store import JsonRecordStore
from engine.analyzer import FailureObservation, attribute_root_cause, cluster_failures
from engine.proposer import Proposer
from engine.writer import EngineWriter


class AnalysisEngine:
    def __init__(self, store: JsonRecordStore, reader, writer: EngineWriter,
                 proposer: Proposer, redaction_analytics):
        self._store = store
        self._reader = reader
        self._writer = writer
        self._proposer = proposer
        self._redaction_analytics = redaction_analytics

    def trigger_analysis(self, *, project: str, eval_run_id: str) -> dict:
        run = self._store.get("runs", eval_run_id)
        if run is None or run.get("project") != project:
            raise ValueError(f"unknown run {eval_run_id}")
        required = ("dataset_id", "dataset_version", "taxonomy_version", "judge_version",
                    "harness_fingerprint", "baseline_fingerprint", "baseline_generation")
        missing_fields = [f for f in required if not run.get(f)]
        if missing_fields:
            raise ValueError(f"run missing analysis fields: {missing_fields}")
        judge = self._store.get("judges", f"{project}:{run['judge_version']}")
        if judge is None or judge.get("status") != "validated":
            raise ValueError("automated analysis requires a validated judge")

        annotations = [a for a in self._store.list("annotations", project=project)
                       if a.get("eval_run_id") == eval_run_id and a.get("label") == "fail"]
        cases = {c["case_id"]: c for c in self._store.list("dataset_cases", project=project)
                 if c.get("dataset_id") == run["dataset_id"]
                 and c.get("dataset_version") == run["dataset_version"]}
        trace_ids = sorted({t for a in annotations for t in
                            cases.get(a["case_id"], {}).get("source_trace_ids", [])})
        payloads, redaction_results, missing_trace_ids = \
            self._reader.fetch_redacted_failed_evidence(trace_ids)
        report = self._redaction_analytics.record(project=project,
            eval_run_id=eval_run_id, results=redaction_results,
            missing_trace_ids=missing_trace_ids)
        blocked_count = report["blocked_evidence_count"]
        if missing_trace_ids or blocked_count or not payloads:
            run["state"] = "needs_more_data"
            self._store.put("runs", eval_run_id, run)
            return {"state": "needs_more_data", "missing_trace_ids": missing_trace_ids,
                    "blocked_evidence_count": blocked_count}

        payload_by_trace = {p.get("trace_id"): p for p in payloads}
        observations: list[FailureObservation] = []
        for annotation in annotations:
            case = cases[annotation["case_id"]]
            for trace_id in case.get("source_trace_ids", []):
                payload = payload_by_trace.get(trace_id, {})
                observations.append(FailureObservation(
                    case_id=annotation["case_id"], trace_id=trace_id,
                    taxonomy_labels=annotation.get("failure_labels", []),
                    tool_name=payload.get("tool_name"),
                    tool_error=payload.get("tool_error"),
                    dataset_split=case.get("split", ""),
                    critique=annotation.get("critique") or "",
                    harness_fingerprint=run["harness_fingerprint"],
                    redaction_state="redacted",
                    open_codes=annotation.get("open_codes", []),
                    case_intent=case.get("intent_summary", ""),
                    repeated_trace_features=payload.get("repeated_trace_features", []),
                ))
        clusters = cluster_failures(observations)
        issues = [attribute_root_cause(c) for c in clusters]
        issue_rows = [self._writer.store_issue(project, issue) for issue in issues]

        proposal_id = f"prop_{uuid.uuid4().hex[:12]}"
        changes = [ProposedChangeModel(change_type="prompt", target_file="prompts/flywheel.md",
            description="Address clustered failure modes", rationale="Derived from redacted evidence",
            evidence_trace_ids=trace_ids, evidence_case_ids=[a["case_id"] for a in annotations],
            suggested_diff="", risk_level="medium")]
        proposal = self._proposer.generate(project=project, proposal_id=proposal_id,
            baseline_fingerprint=run["baseline_fingerprint"],
            baseline_generation=run["baseline_generation"],
            source_eval_run_id=eval_run_id, taxonomy_version=run["taxonomy_version"],
            issues=issues, changes=changes,
            consumed_case_ids=sorted({a["case_id"] for a in annotations}),
            consumed_trace_ids=trace_ids,
            candidate_fingerprint=f"{run['harness_fingerprint']}::draft",
            proposer_id="analysis_engine", expected_metric_delta={}, rollback_plan="revert proposal")
        proposal_row = self._writer.store_proposal(proposal)
        run["state"] = "under_review"
        self._store.put("runs", eval_run_id, run)
        return {"state": "under_review", "issue_ids": [r["id"] for r in issue_rows],
                "proposal_ids": [proposal_row["id"]]}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd flywheel && pytest tests/engine/test_analysis_orchestrator.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add flywheel/engine/orchestrator.py flywheel/tests/engine/test_analysis_orchestrator.py
git commit -m "feat(engine): analysis orchestration over redacted evidence"
```

---

## Task 7: Wire run analysis, issue, proposal, and handoff API routes

**Files:**
- Modify: `flywheel/api/server.py`
- Test: `flywheel/tests/api/test_analysis_routes.py`, `flywheel/tests/api/test_issue_proposal_routes.py`

**Interfaces:**
- Consumes: `AnalysisEngine`, `EngineWriter`, `generate_handoff_markdown`, `IdempotencyStore`, `AuditLog`, `assert_transition`, `BaselineService`.
- Produces the plan-06 endpoints assigned in `2026-06-23-flywheel-00-index.md`:
  - `POST /api/runs/{run_id}/sync-labels`
  - `POST /api/runs/{run_id}/analysis`
  - `GET /api/issues`
  - `GET /api/issues/{issue_id}`
  - `GET /api/proposals/{proposal_id}`
  - `POST /api/proposals/{proposal_id}/handoff`
  - `POST /api/proposals/{proposal_id}/implementation-link`
  - `POST /api/proposals/{proposal_id}/rebase`
- Mutations require `Idempotency-Key` and return the updated object plus `audit_event_id`. `sync-labels` is repeatable: late Langfuse labels can update the run and mark analysis stale. In MVP, sync copies already-imported `annotations` from State Store; a later integration may pull from Langfuse directly.
- Role checks: `sync-labels` accepts `dataset_curator` or `harness_owner`; `analysis`, handoff, implementation link, and rebase require `harness_owner`.

- [ ] **Step 1: Write the failing route tests**

```python
# flywheel/tests/api/test_analysis_routes.py
from pathlib import Path
from fastapi.testclient import TestClient
from api.auth import Principal
from api.server import create_app


class FakeAnalysisEngine:
    def trigger_analysis(self, *, project, eval_run_id):
        return {"state": "under_review", "issue_ids": ["iss_1"], "proposal_ids": ["p1"]}


def test_sync_labels_is_idempotent_and_audited(tmp_path: Path):
    principal = Principal(actor_id="alice", roles=frozenset({"harness_owner"}))
    app = create_app(root=tmp_path, principal_resolver=lambda request: principal)
    app.state.store.put("runs", "run1", {"project": "bourbon", "id": "run1",
        "state": "waiting_for_labels"})
    app.state.store.put("annotations", "ann1", {"project": "bourbon", "id": "ann1",
        "eval_run_id": "run1", "label": "fail"})
    client = TestClient(app)
    r1 = client.post("/api/runs/run1/sync-labels", json={"project": "bourbon"},
                     headers={"Idempotency-Key": "sync-1"})
    r2 = client.post("/api/runs/run1/sync-labels", json={"project": "bourbon"},
                     headers={"Idempotency-Key": "sync-1"})
    assert r1.status_code == 200
    assert r1.json() == r2.json()
    assert r1.json()["run"]["state"] == "labels_synced"
    assert "audit_event_id" in r1.json()


def test_analysis_route_calls_engine(tmp_path: Path):
    principal = Principal(actor_id="alice", roles=frozenset({"harness_owner"}))
    app = create_app(root=tmp_path, principal_resolver=lambda request: principal)
    app.state.analysis_engine = FakeAnalysisEngine()
    client = TestClient(app)
    r = client.post("/api/runs/run1/analysis", json={"project": "bourbon"},
                    headers={"Idempotency-Key": "analysis-1"})
    assert r.status_code == 200
    assert r.json()["analysis"]["proposal_ids"] == ["p1"]
```

```python
# flywheel/tests/api/test_issue_proposal_routes.py
from pathlib import Path
from fastapi.testclient import TestClient
from api.auth import Principal
from api.server import create_app


def _client(tmp_path: Path):
    principal = Principal(actor_id="alice", roles=frozenset({"harness_owner"}))
    app = create_app(root=tmp_path, principal_resolver=lambda request: principal)
    return TestClient(app), app


def test_issue_and_proposal_reads(tmp_path):
    client, app = _client(tmp_path)
    app.state.store.put("issues", "iss_1", {"project": "bourbon", "id": "iss_1",
        "title": "bad offset"})
    app.state.store.put("proposals", "p1", {"project": "bourbon", "id": "p1",
        "state": "draft"})
    assert client.get("/api/issues", params={"project": "bourbon"}).json()["issues"][0]["id"] == "iss_1"
    assert client.get("/api/issues/iss_1").json()["issue"]["title"] == "bad offset"
    assert client.get("/api/proposals/p1").json()["proposal"]["id"] == "p1"


def test_handoff_and_implementation_link_are_audited(tmp_path):
    client, app = _client(tmp_path)
    app.state.store.put("proposals", "p1", {"project": "bourbon", "id": "p1",
        "baseline_fingerprint": "fp0", "baseline_generation": 1,
        "candidate_hypothesis_id": "p1::pending", "source_eval_run_id": "run1",
        "taxonomy_version": "tax1", "failure_issues": [], "proposed_changes": [],
        "target_files": [], "consumed_case_ids": [], "consumed_trace_ids": [],
        "proposer_id": "engine", "expected_metric_delta": {}, "rollback_plan": "x",
        "state": "draft"})
    r = client.post("/api/proposals/p1/handoff", json={"project": "bourbon"},
                    headers={"Idempotency-Key": "handoff-1"})
    assert r.status_code == 200
    assert "audit_event_id" in r.json()
    r2 = client.post("/api/proposals/p1/implementation-link",
                     json={"project": "bourbon", "pr_url": "https://example/pr/1"},
                     headers={"Idempotency-Key": "link-1"})
    assert r2.status_code == 200
    assert r2.json()["handoff"]["pr_url"] == "https://example/pr/1"


def test_rebase_stale_proposal_to_current_baseline(tmp_path):
    client, app = _client(tmp_path)
    app.state.store.put("baselines", "bourbon:gen2", {"project": "bourbon",
        "generation": 2, "fingerprint": "fp2", "produced_by_proposal_id": "p0",
        "previous_generation": 1, "published_at": "now", "status": "current"})
    app.state.store.put("proposals", "p1", {"project": "bourbon", "id": "p1",
        "state": "baseline_stale", "baseline_generation": 1,
        "baseline_fingerprint": "fp1"})
    r = client.post("/api/proposals/p1/rebase", json={"project": "bourbon"},
                    headers={"Idempotency-Key": "rebase-1"})
    assert r.status_code == 200
    assert r.json()["proposal"]["state"] == "under_review"
    assert r.json()["proposal"]["baseline_generation"] == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd flywheel
pytest tests/api/test_analysis_routes.py tests/api/test_issue_proposal_routes.py -v
```

Expected: FAIL because the plan-06 routes are still 501 stubs or absent.

- [ ] **Step 3: Wire services/routes in `server.py`**

Add services:

```python
    from api.redaction import DEFAULT_POLICY, RedactionAnalytics, RedactionService
    from engine.handoff import generate_handoff_markdown
    from engine.orchestrator import AnalysisEngine
    from engine.proposer import Proposer
    from engine.reader import EvidenceReader
    from engine.writer import EngineWriter

    writer = EngineWriter(store)
    reader = EvidenceReader(langfuse_url=settings.langfuse_url,
                            langfuse_secret=settings.langfuse_secret,
                            redactor=RedactionService(DEFAULT_POLICY))
    analysis_engine = AnalysisEngine(store, reader, writer, Proposer(),
                                     RedactionAnalytics(store))
    app.state.analysis_engine = analysis_engine
```

Add route-local request models/imports before the route snippets:

```python
    from pydantic import BaseModel
    from api.schemas import ImprovementProposalModel

    class ProjectBody(BaseModel):
        project: str

    class ImplementationLinkBody(BaseModel):
        project: str
        pr_url: str | None = None
        diff_url: str | None = None
```

Use the same `_idempotent()` helper style as plans 04/05. Add route snippets:

```python
    @app.post("/api/runs/{run_id}/sync-labels")
    def sync_labels(run_id: str, body: ProjectBody, request: Request):
        principal = principal_resolver(request)
        if "harness_owner" not in principal.roles and "dataset_curator" not in principal.roles:
            require_role(principal, "harness_owner")
        def compute():
            run = store.get("runs", run_id)
            if run is None:
                raise HTTPException(status_code=404, detail="run not found")
            before = dict(run)
            labels = [a for a in store.list("annotations", project=body.project)
                      if a.get("eval_run_id") == run_id]
            run["label_count"] = len(labels)
            run["state"] = "labels_synced"
            store.put("runs", run_id, run)
            aid = audit.record(project=body.project, actor=principal.actor_id,
                               action="sync_labels", target_type="run",
                               target_id=run_id, before=before, after=run)
            return {"run": run, "audit_event_id": aid}
        return _idempotent(request, compute)

    @app.post("/api/runs/{run_id}/analysis")
    def trigger_analysis(run_id: str, body: ProjectBody, request: Request):
        principal = principal_resolver(request)
        require_role(principal, "harness_owner")
        def compute():
            result = app.state.analysis_engine.trigger_analysis(
                project=body.project, eval_run_id=run_id)
            aid = audit.record(project=body.project, actor=principal.actor_id,
                               action="trigger_analysis", target_type="run",
                               target_id=run_id, before=None, after=result)
            return {"analysis": result, "audit_event_id": aid}
        return _idempotent(request, compute)

    @app.get("/api/issues")
    def list_issues(project: str):
        return {"issues": store.list("issues", project=project)}

    @app.get("/api/issues/{issue_id}")
    def get_issue(issue_id: str):
        issue = store.get("issues", issue_id)
        if issue is None:
            raise HTTPException(status_code=404, detail="issue not found")
        return {"issue": issue}

    @app.get("/api/proposals/{proposal_id}")
    def get_proposal(proposal_id: str):
        proposal = store.get("proposals", proposal_id)
        if proposal is None:
            raise HTTPException(status_code=404, detail="proposal not found")
        return {"proposal": proposal}

    @app.post("/api/proposals/{proposal_id}/handoff")
    def create_handoff(proposal_id: str, body: ProjectBody, request: Request):
        principal = principal_resolver(request)
        require_role(principal, "harness_owner")
        def compute():
            proposal = ImprovementProposalModel(**store.get("proposals", proposal_id))
            markdown = generate_handoff_markdown(proposal)
            handoff = writer.store_handoff(body.project, proposal_id, markdown)
            aid = audit.record(project=body.project, actor=principal.actor_id,
                               action="create_handoff", target_type="handoff",
                               target_id=handoff["id"], before=None, after=handoff)
            return {"handoff": handoff, "audit_event_id": aid}
        return _idempotent(request, compute)

    @app.post("/api/proposals/{proposal_id}/implementation-link")
    def link_implementation(proposal_id: str, body: ImplementationLinkBody, request: Request):
        principal = principal_resolver(request)
        require_role(principal, "harness_owner")
        def compute():
            handoff_id = f"{proposal_id}:handoff"
            handoff = store.get("handoffs", handoff_id) or {
                "project": body.project, "proposal_id": proposal_id, "markdown": ""}
            before = dict(handoff)
            handoff["pr_url"] = body.pr_url
            handoff["diff_url"] = body.diff_url
            handoff = store.put("handoffs", handoff_id, handoff)
            aid = audit.record(project=body.project, actor=principal.actor_id,
                               action="link_implementation", target_type="handoff",
                               target_id=handoff_id, before=before, after=handoff)
            return {"handoff": handoff, "audit_event_id": aid}
        return _idempotent(request, compute)

    @app.post("/api/proposals/{proposal_id}/rebase")
    def rebase_proposal(proposal_id: str, body: ProjectBody, request: Request):
        principal = principal_resolver(request)
        require_role(principal, "harness_owner")
        def compute():
            from api.lifecycle import assert_transition
            proposal = store.get("proposals", proposal_id)
            if proposal is None:
                raise HTTPException(status_code=404, detail="proposal not found")
            current = baselines.current(body.project)
            if current is None:
                raise HTTPException(status_code=409, detail="no current baseline")
            assert_transition(proposal["state"], "under_review")
            before = dict(proposal)
            proposal["baseline_generation"] = current.generation
            proposal["baseline_fingerprint"] = current.fingerprint
            proposal["state"] = "under_review"
            proposal = store.put("proposals", proposal_id, proposal)
            aid = audit.record(project=body.project, actor=principal.actor_id,
                               action="rebase_proposal", target_type="proposal",
                               target_id=proposal_id, before=before, after=proposal)
            return {"proposal": proposal, "audit_event_id": aid}
        return _idempotent(request, compute)
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
cd flywheel
pytest tests/api/test_analysis_routes.py tests/api/test_issue_proposal_routes.py -v
```

Expected: PASS.

- [ ] **Step 5: Run full suite + lint + types, then commit**

```bash
cd flywheel && pytest -q && ruff check api engine sdk tests && mypy api engine sdk
git add flywheel/api/server.py flywheel/engine/orchestrator.py flywheel/tests/api/test_analysis_routes.py flywheel/tests/api/test_issue_proposal_routes.py flywheel/tests/engine/test_analysis_orchestrator.py
git commit -m "feat(api): analysis, issue, proposal, and handoff routes"
```

---

## Self-Review

- **Spec coverage (Engine §13 analyzer/proposer/handoff):** `cluster_failures` implements the multi-signal clustering requirement (not only top-level label; excludes blocked evidence; includes open codes, tool/error, case intent, split, critique bucket, harness fingerprint, repeated trace features, and redaction state); `attribute_root_cause` produces `FailureIssue` with evidence, counterexamples, affected labels, and confidence; `Proposer.generate` enforces the `consumed_case_ids ⊇ affected cases` and `consumed_trace_ids ⊇ evidence traces` invariants and computes `candidate_hypothesis_id`; `detect_conflicts` implements the §13 target-file conflict (human gate in MVP); `generate_handoff_markdown` produces the §13 coding-agent handoff with the holdout-exclusion warning; `EngineWriter` persists all three; `AnalysisEngine` enforces the mandatory redaction boundary by consuming only `EvidenceReader.fetch_redacted_failed_evidence()` and returning `needs_more_data` when missing/blocked evidence reduces coverage. API route wiring covers every plan-06 endpoint assigned by the index.
- **Placeholder scan:** clustering/attribution are deterministic heuristics per the MVP stance — fully implemented, no LLM call required for tests, no TODO.
- **Type consistency:** `FailureIssue` is the analyzer dataclass; `ImprovementProposalModel`/`ProposedChangeModel`/`HandoffModel` are the plan-02 pydantic models used unchanged. `candidate_hypothesis_id` format `proposal_id::candidate_fingerprint` matches plan 07's holdout-ledger keying. `consumed_case_ids` is the field plan 07 subtracts from the holdout, and `consumed_trace_ids` preserves proposal evidence lineage. `state="draft"` matches plan 02 `ProposalState`.
