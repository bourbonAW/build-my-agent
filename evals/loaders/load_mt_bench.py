"""Loader for lmsys/mt_bench_human_judgments benchmark cases."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pyarrow.parquet as pq
from huggingface_hub import dataset_info as hf_dataset_info
from huggingface_hub import hf_hub_download

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evals.loaders.common import write_yaml_with_header

_DATASET_ID = "lmsys/mt_bench_human_judgments"
_PARQUET_FILE = "data/human-00000-of-00001-25f4910818759289.parquet"
_CATEGORIES = [
    (81, 90, "writing"),
    (91, 100, "roleplay"),
    (101, 110, "reasoning"),
    (111, 120, "math"),
    (121, 130, "coding"),
    (131, 140, "extraction"),
    (141, 150, "stem"),
    (151, 160, "humanities"),
]
_RUBRIC_TEMPLATE = """\
The output is a JSON string with a "text" field containing the agent's response.
Extract the "text" field and score the response from 1 to 10.

Scoring criteria:
- 9-10: Fully addresses the task, accurate, well-structured, no significant errors
- 7-8: Addresses the task with minor gaps or imprecisions
- 5-6: Partially addresses the task with notable omissions or errors
- 1-4: Fails to address the task, significantly wrong, or refuses without reason

Respond with only a single integer."""


def _category_for_id(question_id: int) -> str:
    """Return the MT-Bench category for a question ID."""
    for lower, upper, name in _CATEGORIES:
        if lower <= question_id <= upper:
            return name
    return "other"


def _extract_first_user_prompt(conversation: list[dict]) -> str:
    """Extract the first user message from a conversation transcript."""
    for turn in conversation:
        if turn.get("role") == "user":
            return str(turn.get("content", ""))
    raise ValueError("conversation does not contain a user prompt")


def transform_mt_bench(records: list[dict]) -> list[dict]:
    """Transform MT-Bench judgment records into promptfoo cases."""
    seen: set[int] = set()
    unique_records: list[dict] = []
    for record in records:
        if record.get("turn") != 1:
            continue
        question_id = record["question_id"]
        if question_id in seen:
            continue
        seen.add(question_id)
        unique_records.append(record)

    unique_records.sort(key=lambda record: record["question_id"])
    cases: list[dict] = []
    for record in unique_records:
        question_id = record["question_id"]
        category = _category_for_id(question_id)
        prompt = _extract_first_user_prompt(record["conversation_a"])
        cases.append(
            {
                "description": f"MT-Bench #{question_id} ({category})",
                "vars": {"prompt": prompt},
                "assert": [
                    {
                        "type": "llm-rubric",
                        "metric": "mt_bench_score",
                        "value": _RUBRIC_TEMPLATE,
                        "threshold": 7,
                    }
                ],
                "metadata": {
                    "category": "benchmark-mt-bench",
                    "subcategory": category,
                    "question_id": question_id,
                },
            }
        )
    return cases


def main() -> None:
    parser = argparse.ArgumentParser(description="Load MT-Bench questions")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    parquet_path = hf_hub_download(_DATASET_ID, repo_type="dataset", filename=_PARQUET_FILE)
    records = pq.read_table(parquet_path).to_pylist()
    revision = hf_dataset_info(_DATASET_ID).sha or "unknown"
    cases = transform_mt_bench(records)
    print(f"Extracted {len(cases)} unique first-turn questions")
    write_yaml_with_header(
        cases=cases,
        output_path=args.output,
        command=f"python evals/loaders/load_mt_bench.py --output {args.output}",
        dataset_id=_DATASET_ID,
        dataset_revision=str(revision),
    )


if __name__ == "__main__":
    main()
