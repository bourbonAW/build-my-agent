"""Baseline vs candidate regression (Engine §7): better | no_change | worse."""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from typing import Literal, get_args

from .identity import Label, validate_judge_version
from .metrics import pass_rate

RegressionResult = Literal["better", "no_change", "worse"]


def _sign_test_significant(fixed_n: int, broken_n: int, alpha: float = 0.05) -> bool:
    """Exact two-sided binomial sign test (McNemar exact) on discordant pairs."""
    disc = fixed_n + broken_n
    if disc == 0:
        return False
    k = min(fixed_n, broken_n)
    tail_numerator = sum(int(math.comb(disc, i)) for i in range(k + 1))
    tail: float = tail_numerator / float(2**disc)
    doubled_tail = 2.0 * tail
    p_value: float = 1.0 if doubled_tail > 1.0 else doubled_tail
    return bool(p_value < alpha)


@dataclass(frozen=True)
class CaseScore:
    case_id: str
    label: Label
    failure_label: str | None = None

    def __post_init__(self) -> None:
        if self.label not in get_args(Label):
            raise ValueError(f"invalid label {self.label!r}; expected one of {get_args(Label)}")


@dataclass(frozen=True)
class RegressionReport:
    result: RegressionResult
    judge_version: str
    baseline_rate: float
    candidate_rate: float
    candidate_rate_low: float
    candidate_rate_high: float
    candidate_non_pass_count: int
    delta: float
    delta_low: float
    delta_high: float
    fixed: list[str]
    newly_broken: list[str]
    per_label: list[dict[str, object]]


def _labels_by_case(scores: list[CaseScore]) -> dict[str, Label]:
    return {s.case_id: s.label for s in scores}


def _fail_counts(scores: list[CaseScore]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for score in scores:
        if score.label != "pass":
            label = score.failure_label or "unlabeled"
            counts[label] = counts.get(label, 0) + 1
    return counts


def aggregate_repeats(scores: list[CaseScore]) -> list[CaseScore]:
    """Collapse repeated scorings of one case by conservative majority vote."""
    by_case: dict[str, list[CaseScore]] = {}
    for score in scores:
        by_case.setdefault(score.case_id, []).append(score)

    out: list[CaseScore] = []
    priority: dict[Label, int] = {"fail": 0, "uncertain": 1, "skip": 2, "pass": 3}
    for case_id, runs in by_case.items():
        if len(runs) == 1:
            out.append(runs[0])
            continue

        passes = sum(1 for run in runs if run.label == "pass")
        if passes * 2 > len(runs):
            out.append(CaseScore(case_id, "pass"))
            continue

        non_pass = Counter(run.label for run in runs if run.label != "pass")
        label = max(non_pass, key=lambda candidate: (non_pass[candidate], -priority[candidate]))
        failure_labels = Counter(
            run.failure_label for run in runs if run.label != "pass" and run.failure_label
        )
        failure_label = failure_labels.most_common(1)[0][0] if failure_labels else None
        out.append(CaseScore(case_id, label, failure_label))
    return sorted(out, key=lambda score: score.case_id)


def check_repeat_budgets(
    baseline: list[CaseScore],
    candidate: list[CaseScore],
    *,
    min_repeats: int = 3,
) -> None:
    """Ensure repeated scorings are fair before aggregation discards counts."""
    baseline_counts = Counter(score.case_id for score in baseline)
    candidate_counts = Counter(score.case_id for score in candidate)
    if set(baseline_counts) != set(candidate_counts):
        raise ValueError("baseline and candidate cover different case ids before aggregation")
    for case_id in baseline_counts:
        if baseline_counts[case_id] != candidate_counts[case_id]:
            raise ValueError(
                f"unequal repeat budget for {case_id!r}: baseline {baseline_counts[case_id]}x "
                f"vs candidate {candidate_counts[case_id]}x"
            )
        if baseline_counts[case_id] != 1 and baseline_counts[case_id] < min_repeats:
            raise ValueError(
                f"case {case_id!r} sampled {baseline_counts[case_id]}x: "
                f"repeat once or >= {min_repeats}x (Engine §7)"
            )


def compare(
    baseline: list[CaseScore],
    candidate: list[CaseScore],
    *,
    regression_case_ids: set[str],
    baseline_judge_version: str,
    candidate_judge_version: str,
) -> RegressionReport:
    validate_judge_version(baseline_judge_version)
    validate_judge_version(candidate_judge_version)
    if baseline_judge_version != candidate_judge_version:
        raise ValueError(
            "same-judge gate: baseline and candidate must use one judge_version "
            f"({baseline_judge_version!r} != {candidate_judge_version!r}); re-score first"
        )

    base_ids = [score.case_id for score in baseline]
    cand_ids = [score.case_id for score in candidate]
    if not base_ids or not cand_ids:
        raise ValueError("regression set must not be empty")
    if len(set(base_ids)) != len(base_ids) or len(set(cand_ids)) != len(cand_ids):
        raise ValueError(
            "duplicate case_id within baseline or candidate scores; aggregate repeats first "
            "(see aggregate_repeats)"
        )
    if set(base_ids) != set(cand_ids):
        raise ValueError(
            "same-population gate: baseline and candidate must cover the same regression "
            "case set (compare on identical case_ids, not different populations); "
            "re-run the missing cases first"
        )
    if set(base_ids) != regression_case_ids:
        missing = regression_case_ids - set(base_ids)
        extra = set(base_ids) - regression_case_ids
        raise ValueError(
            "regression set is incomplete: baseline/candidate must cover exactly the "
            f"declared regression split (missing={missing}, extra={extra}); re-run the "
            "missing cases — a silently dropped case must not pass the gate"
        )

    baseline_by_case = _labels_by_case(baseline)
    candidate_by_case = _labels_by_case(candidate)
    fixed = sorted(
        case_id
        for case_id in baseline_by_case
        if baseline_by_case[case_id] != "pass" and candidate_by_case[case_id] == "pass"
    )
    newly_broken = sorted(
        case_id
        for case_id in baseline_by_case
        if baseline_by_case[case_id] == "pass" and candidate_by_case[case_id] != "pass"
    )

    baseline_labels: list[str] = [score.label for score in baseline]
    candidate_labels: list[str] = [score.label for score in candidate]
    baseline_rate = pass_rate(baseline_labels).point
    candidate_ci = pass_rate(candidate_labels)
    candidate_rate = candidate_ci.point
    candidate_non_pass = sum(1 for label in candidate_labels if label != "pass")
    delta = candidate_rate - baseline_rate

    n = len(base_ids)
    discordant = len(fixed) + len(newly_broken)
    if discordant == 0:
        bound = min(3.0 / n, 1.0)
        delta_low, delta_high = -bound, bound
    else:
        p_ci = pass_rate(["pass"] * len(fixed) + ["fail"] * len(newly_broken))
        delta_low = (2 * p_ci.low - 1) * discordant / n
        delta_high = (2 * p_ci.high - 1) * discordant / n

    if _sign_test_significant(len(fixed), len(newly_broken)):
        result: RegressionResult = "better" if delta > 0 else "worse"
    else:
        result = "no_change"

    baseline_fails = _fail_counts(baseline)
    candidate_fails = _fail_counts(candidate)
    per_label = [
        {
            "label": label,
            "baseline": baseline_fails.get(label, 0),
            "candidate": candidate_fails.get(label, 0),
        }
        for label in sorted(set(baseline_fails) | set(candidate_fails))
    ]

    return RegressionReport(
        result=result,
        judge_version=baseline_judge_version,
        baseline_rate=baseline_rate,
        candidate_rate=candidate_rate,
        candidate_rate_low=candidate_ci.low,
        candidate_rate_high=candidate_ci.high,
        candidate_non_pass_count=candidate_non_pass,
        delta=delta,
        delta_low=delta_low,
        delta_high=delta_high,
        fixed=fixed,
        newly_broken=newly_broken,
        per_label=per_label,
    )
