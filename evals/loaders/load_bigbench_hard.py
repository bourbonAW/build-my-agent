"""Loader for lighteval/big_bench_hard benchmark cases."""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path

from huggingface_hub import dataset_info as hf_dataset_info
from huggingface_hub import hf_hub_download

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evals.loaders.common import write_yaml_with_header

_DATASET_ID = "lighteval/big_bench_hard"
_BBH_SUBTASKS = [
    "causal_judgement",
    "date_understanding",
    "formal_fallacies",
    "geometric_shapes",
    "hyperbaton",
    "logical_deduction_five_objects",
    "movie_recommendation",
    "navigate",
    "reasoning_about_colored_objects",
    "snarks",
]
_JS_ASSERTION = """\
const parsed = JSON.parse(output);
const data = typeof parsed.output === 'string' ? JSON.parse(parsed.output) : parsed;
const match = data.text.match(/^Answer:\\s*(\\([A-Z]\\))\\s*$/m);
if (!match) return false;
return match[1] === context.vars.expected_option;
"""


def _normalize_expected_option(input_text: str, target: str) -> str:
    """Convert textual targets from the dataset into canonical option labels."""
    normalized_target = target.strip()
    if re.fullmatch(r"\([A-Z]\)", normalized_target):
        return normalized_target

    labeled_options: list[tuple[str, str]] = []
    bullet_options: list[str] = []
    for line in input_text.splitlines():
        stripped = line.strip()
        labeled_match = re.match(r"^\(([A-Z])\)\s*(.+)$", stripped)
        if labeled_match:
            labeled_options.append((f"({labeled_match.group(1)})", labeled_match.group(2).strip()))
            continue
        bullet_match = re.match(r"^-\s+(.+)$", stripped)
        if bullet_match:
            bullet_options.append(bullet_match.group(1).strip())

    for label, text in labeled_options:
        if text.casefold() == normalized_target.casefold():
            return label

    for index, text in enumerate(bullet_options):
        if text.casefold() == normalized_target.casefold():
            return f"({chr(ord('A') + index)})"

    return normalized_target


def transform_bbh_task(records: list[dict], task_name: str, per_task: int, seed: int) -> list[dict]:
    """Transform a BIG-bench Hard subtask into promptfoo cases."""
    rng = random.Random(seed)
    sampled = rng.sample(records, min(per_task, len(records)))
    cases: list[dict] = []

    for index, record in enumerate(sampled):
        cases.append(
            {
                "description": f"BBH {task_name} #{index}",
                "vars": {
                    "prompt": (
                        f"{record['input']}\n\n"
                        'End your response with "Answer: (X)" on its own line.'
                    ),
                    "expected_option": _normalize_expected_option(
                        record["input"], record["target"]
                    ),
                },
                "assert": [{"type": "javascript", "value": _JS_ASSERTION}],
                "metadata": {
                    "category": "benchmark-bigbench-hard",
                    "subcategory": task_name,
                },
            }
        )

    return cases


def main() -> None:
    parser = argparse.ArgumentParser(description="Load BIG-bench Hard subset")
    parser.add_argument("--tasks", nargs="+", default=_BBH_SUBTASKS)
    parser.add_argument("--per-task", type=int, default=10)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    revision = hf_dataset_info(_DATASET_ID).sha or "unknown"
    all_cases: list[dict] = []
    for task_name in args.tasks:
        path = hf_hub_download(_DATASET_ID, repo_type="dataset", filename=f"data/{task_name}.json")
        with Path(path).open(encoding="utf-8") as handle:
            payload = json.load(handle)
        records = payload["examples"]
        cases = transform_bbh_task(
            records,
            task_name=task_name,
            per_task=args.per_task,
            seed=args.seed,
        )
        all_cases.extend(cases)
        print(f"  {task_name}: {len(cases)} tasks")

    command = (
        "python evals/loaders/load_bigbench_hard.py "
        f"--tasks {' '.join(args.tasks)} "
        f"--per-task {args.per_task} --seed {args.seed} --output {args.output}"
    )
    write_yaml_with_header(
        cases=all_cases,
        output_path=args.output,
        command=command,
        dataset_id=_DATASET_ID,
        dataset_revision=str(revision),
    )


if __name__ == "__main__":
    main()
