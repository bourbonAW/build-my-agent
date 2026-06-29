"""Validate a judge on judge_dev or the held-out judge_test split."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import cast

from flywheel.report import write_judge_report
from flywheel.validate import LabeledCase, validate

from scripts.common import (
    DEFAULT_ROOT,
    Split,
    ensure_disjoint_splits,
    items_for_split,
    load_dataset_items,
    load_score_records,
    one_score_per_case,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default="bourbon")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--dataset-json", type=Path, default=None)
    parser.add_argument("--dataset", default=None)
    parser.add_argument("--split", default="judge_test", choices=("judge_dev", "judge_test"))
    parser.add_argument("--judge-version", default=None)
    parser.add_argument("--threshold", type=float, default=0.70)
    parser.add_argument("--min-class-support", type=int, default=5)
    args = parser.parse_args()

    split = cast(Split, args.split)
    items = load_dataset_items(args.dataset_json, args.dataset)
    ensure_disjoint_splits(items)
    target_items = items_for_split(items, split)
    if not target_items:
        raise SystemExit(f"dataset has no {split} items")

    scores, judge_version = load_score_records(
        args.root,
        args.project,
        split,
        judge_version=args.judge_version,
    )
    by_case = one_score_per_case(scores, {item.case_id for item in target_items})

    labeled: list[LabeledCase] = []
    for item in target_items:
        if item.human_label is None:
            raise ValueError(f"{split} item {item.case_id!r} missing human_label")
        labeled.append(LabeledCase(item.case_id, item.human_label, by_case[item.case_id].label))

    first = scores[0]
    report = validate(
        labeled,
        judge_version=judge_version,
        model=first.model,
        prompt_version=first.prompt_version,
        threshold=args.threshold,
        min_class_support=args.min_class_support,
    )
    if split == "judge_test":
        path = write_judge_report(args.root, args.project, report)
        payload = asdict(report) | {"passes": report.passes(), "path": str(path)}
    else:
        payload = asdict(report) | {"passes": report.passes()}
    print(json.dumps(payload, indent=2))
    if not report.passes():
        raise SystemExit(1)


if __name__ == "__main__":
    main()
