"""Compare baseline and candidate regression runs and write Flywheel reports."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from flywheel.regression import (
    CaseScore,
    aggregate_repeats,
    check_repeat_budgets,
    compare,
)
from flywheel.report import read_json, write_regression_markdown, write_regression_report

from scripts.common import (
    DEFAULT_ROOT,
    DatasetItem,
    ScoreRecord,
    ensure_disjoint_splits,
    items_for_split,
    load_dataset_items,
    load_run_metadata,
    load_score_records,
    require_failure_labels,
    split_sets,
)


def _judge_report_path(root: Path, project: str, judge_version: str) -> Path:
    from flywheel.report import _safe_segment

    return (
        Path(root)
        / _safe_segment(project)
        / "reports"
        / "judge"
        / f"{_safe_segment(judge_version)}.json"
    )


def _require_passing_judge(root: Path, project: str, judge_version: str) -> None:
    path = _judge_report_path(root, project, judge_version)
    if not path.exists():
        raise FileNotFoundError(f"missing JudgeReport for {judge_version!r}: {path}")
    report = read_json(path)
    if report.get("passes") is not True:
        raise ValueError(f"judge {judge_version!r} is not validated; refusing regression compare")


def _case_scores(items: dict[str, DatasetItem], records: list[ScoreRecord]) -> list[CaseScore]:
    scores: list[CaseScore] = []
    for record in records:
        item = items.get(record.case_id)
        if item is None:
            scores.append(CaseScore(record.case_id, record.label))
            continue
        failure_label = item.failure_label if record.label != "pass" else None
        scores.append(CaseScore(record.case_id, record.label, failure_label))
    return scores


def _representative_trace_urls(
    records: list[ScoreRecord],
    aggregated: list[CaseScore],
) -> dict[str, str]:
    majority = {score.case_id: score.label for score in aggregated}
    urls: dict[str, str] = {}
    for record in sorted(records, key=lambda item: item.sample_id):
        if record.case_id in urls:
            continue
        if record.label == majority.get(record.case_id) and record.trace_url:
            urls[record.case_id] = record.trace_url
    return urls


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default="bourbon")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--dataset-json", type=Path, default=None)
    parser.add_argument("--dataset", default=None)
    parser.add_argument("--baseline-run", required=True)
    parser.add_argument("--candidate-run", required=True)
    parser.add_argument("--judge-version", default=None)
    parser.add_argument("--candidate-pr-url", default=None)
    args = parser.parse_args()

    items = load_dataset_items(args.dataset_json, args.dataset)
    ensure_disjoint_splits(items)
    regression_items = items_for_split(items, "regression")
    require_failure_labels(regression_items)
    item_by_id = {item.case_id: item for item in regression_items}

    baseline_records, baseline_judge_version = load_score_records(
        args.root, args.project, args.baseline_run
    )
    candidate_records, candidate_judge_version = load_score_records(
        args.root, args.project, args.candidate_run
    )
    if args.judge_version is not None and args.judge_version not in {
        baseline_judge_version,
        candidate_judge_version,
    }:
        raise ValueError(
            f"--judge-version {args.judge_version!r} does not match score metadata "
            f"{baseline_judge_version!r}/{candidate_judge_version!r}"
        )
    _require_passing_judge(args.root, args.project, baseline_judge_version)

    baseline_scores = _case_scores(item_by_id, baseline_records)
    candidate_scores = _case_scores(item_by_id, candidate_records)
    check_repeat_budgets(baseline_scores, candidate_scores)
    baseline_aggregated = aggregate_repeats(baseline_scores)
    candidate_aggregated = aggregate_repeats(candidate_scores)

    splits = split_sets(items)
    validation_ids = splits["judge_train"] | splits["judge_dev"] | splits["judge_test"]
    report = compare(
        baseline_aggregated,
        candidate_aggregated,
        regression_case_ids=splits["regression"],
        validation_case_ids=validation_ids,
        baseline_judge_version=baseline_judge_version,
        candidate_judge_version=candidate_judge_version,
    )

    baseline_meta = load_run_metadata(args.root, args.project, args.baseline_run)
    candidate_meta = load_run_metadata(args.root, args.project, args.candidate_run)
    baseline_harness = str(baseline_meta.get("harness", args.baseline_run))
    candidate_harness = str(candidate_meta.get("harness", args.candidate_run))
    trace_urls = _representative_trace_urls(candidate_records, candidate_aggregated)

    json_path = write_regression_report(
        args.root,
        args.project,
        args.candidate_run,
        report,
        baseline_harness=baseline_harness,
        candidate_harness=candidate_harness,
        trace_urls=trace_urls,
        candidate_pr_url=args.candidate_pr_url,
    )
    md_path = write_regression_markdown(
        args.root,
        args.project,
        args.candidate_run,
        report,
        baseline_harness=baseline_harness,
        candidate_harness=candidate_harness,
        trace_urls=trace_urls,
        candidate_pr_url=args.candidate_pr_url,
    )
    print(
        json.dumps(
            {
                "runId": args.candidate_run,
                "result": report.result,
                "json": str(json_path),
                "markdown": str(md_path),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
