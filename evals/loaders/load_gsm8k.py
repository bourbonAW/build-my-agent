"""Loader for openai/gsm8k benchmark cases."""

from __future__ import annotations

import argparse
import random
import re
import sys
from pathlib import Path

from huggingface_hub import dataset_info as hf_dataset_info

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evals.loaders.common import write_yaml_with_header

_DATASET_ID = "openai/gsm8k"
_JS_ASSERTION = """\
const parsed = JSON.parse(output);
const data = typeof parsed.output === 'string' ? JSON.parse(parsed.output) : parsed;
const match = data.text.match(/####\\s*(\\d+\\.?\\d*)/);
const extracted = match ? match[1] : null;
if (extracted === null) return false;
return extracted === String(context.vars.expected_answer);
"""


def _extract_answer_number(answer: str) -> str | None:
    """Extract the final answer after the #### delimiter."""
    match = re.search(r"####\s*(\d+\.?\d*)", answer)
    return match.group(1) if match else None


def _estimate_steps(answer: str) -> int:
    """Estimate difficulty from the number of annotated intermediate calculations."""
    return len(re.findall(r"<<", answer))


def transform_gsm8k(tasks: list[dict], sample: int, seed: int) -> list[dict]:
    """Transform GSM8K records into promptfoo cases."""
    valid_tasks = [task for task in tasks if _extract_answer_number(task["answer"]) is not None]
    rng = random.Random(seed)
    sampled = rng.sample(valid_tasks, min(sample, len(valid_tasks)))
    cases: list[dict] = []

    for index, task in enumerate(sampled):
        expected = _extract_answer_number(task["answer"])
        steps = _estimate_steps(task["answer"])
        difficulty = "easy" if steps <= 3 else ("medium" if steps <= 6 else "hard")
        cases.append(
            {
                "description": f"GSM8K #{index}: {task['question'][:60].rstrip()}",
                "vars": {
                    "prompt": (
                        f"{task['question']}\n\n"
                        'Solve step by step. End your answer with "#### <number>" '
                        "on its own line (the number only, no units)."
                    ),
                    "expected_answer": expected,
                },
                "assert": [{"type": "javascript", "value": _JS_ASSERTION}],
                "metadata": {
                    "category": "benchmark-gsm8k",
                    "difficulty": difficulty,
                },
            }
        )

    return cases


def main() -> None:
    parser = argparse.ArgumentParser(description="Load GSM8K subset")
    parser.add_argument("--sample", type=int, default=50)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--stratify-by-steps", action="store_true")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    from datasets import load_dataset

    dataset = load_dataset(_DATASET_ID, "main", split="test")
    revision = hf_dataset_info(_DATASET_ID).sha or "unknown"
    tasks = list(dataset)

    if args.stratify_by_steps:
        rng = random.Random(args.seed)
        easy = [task for task in tasks if _estimate_steps(task["answer"]) <= 3]
        medium = [task for task in tasks if 4 <= _estimate_steps(task["answer"]) <= 6]
        hard = [task for task in tasks if _estimate_steps(task["answer"]) >= 7]
        per_tier = args.sample // 3
        remainder = args.sample - per_tier * 3
        pool = (
            rng.sample(easy, min(per_tier + remainder, len(easy)))
            + rng.sample(medium, min(per_tier, len(medium)))
            + rng.sample(hard, min(per_tier, len(hard)))
        )
        rng.shuffle(pool)
        cases = transform_gsm8k(pool, sample=len(pool), seed=args.seed)
    else:
        cases = transform_gsm8k(tasks, sample=args.sample, seed=args.seed)

    command = (
        "python evals/loaders/load_gsm8k.py "
        f"--sample {args.sample} --seed {args.seed} --output {args.output}"
        + (" --stratify-by-steps" if args.stratify_by_steps else "")
    )
    write_yaml_with_header(
        cases=cases,
        output_path=args.output,
        command=command,
        dataset_id=_DATASET_ID,
        dataset_revision=str(revision),
    )


if __name__ == "__main__":
    main()
