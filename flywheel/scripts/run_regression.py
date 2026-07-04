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
from flywheel.report import write_regression_markdown, write_regression_report

from scripts.common import (
    DEFAULT_ROOT,
    Case,
    ScoreRecord,
    active_cases,
    load_dataset_items,
    load_run_metadata,
    load_score_records,
)


def _case_scores(items: dict[str, Case], records: list[ScoreRecord]) -> list[CaseScore]:
    scores: list[CaseScore] = []
    for record in records:
        item = items.get(record.case_id)
        if item is None:
            scores.append(CaseScore(record.case_id, record.label))
            continue
        failure_label = item.failure_category if record.label != "pass" else None
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
    parser.add_argument("--cases-path", type=Path, default=None)
    parser.add_argument("--baseline-run", required=True)
    parser.add_argument("--candidate-run", required=True)
    parser.add_argument("--judge-version", default=None)
    parser.add_argument("--candidate-pr-url", default=None)
    args = parser.parse_args()

    items = load_dataset_items(args.cases_path, args.root, args.project)
    regression_items = active_cases(items)
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

    baseline_scores = _case_scores(item_by_id, baseline_records)
    candidate_scores = _case_scores(item_by_id, candidate_records)
    check_repeat_budgets(baseline_scores, candidate_scores)
    baseline_aggregated = aggregate_repeats(baseline_scores)
    candidate_aggregated = aggregate_repeats(candidate_scores)

    report = compare(
        baseline_aggregated,
        candidate_aggregated,
        regression_case_ids={item.case_id for item in regression_items},
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
