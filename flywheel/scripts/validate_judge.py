"""Validate a judge against every currently human-labeled case (continuous metric,
not a pass/fail gate — see docs/superpowers/specs/2026-07-02-flywheel-local-case-store-design.md §2)."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from flywheel.report import write_judge_report
from flywheel.validate import LabeledCase, validate

from scripts.common import (
    DEFAULT_ROOT,
    labeled_cases,
    load_dataset_items,
    load_score_records,
    one_score_per_case,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default="bourbon")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--cases-path", type=Path, default=None)
    parser.add_argument("--judge-version", default=None)
    parser.add_argument("--threshold", type=float, default=0.70)
    parser.add_argument("--min-class-support", type=int, default=5)
    args = parser.parse_args()

    items = load_dataset_items(args.cases_path, args.root, args.project)
    target_items = labeled_cases(items)
    if not target_items:
        raise SystemExit("no labeled cases to validate the judge against")

    scores, judge_version = load_score_records(
        args.root, args.project, "frozen", judge_version=args.judge_version,
    )
    by_case = one_score_per_case(scores, {item.case_id for item in target_items})

    labeled: list[LabeledCase] = [
        LabeledCase(item.case_id, item.label, by_case[item.case_id].label)  # type: ignore[arg-type]
        for item in target_items
    ]

    first = scores[0]
    report = validate(
        labeled,
        judge_version=judge_version,
        model=first.model,
        prompt_version=first.prompt_version,
        threshold=args.threshold,
        min_class_support=args.min_class_support,
    )
    path = write_judge_report(args.root, args.project, report)
    payload = asdict(report) | {"passes": report.passes(), "path": str(path)}
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
