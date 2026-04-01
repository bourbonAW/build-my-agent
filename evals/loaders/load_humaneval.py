"""Loader for openai/openai-humaneval benchmark cases."""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

from huggingface_hub import dataset_info as hf_dataset_info

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evals.loaders.common import write_yaml_with_header

_DATASET_ID = "openai/openai_humaneval"
_RUBRIC_TEMPLATE = """\
The output is a JSON string. Extract the "text" field.
The response should contain a Python function implementation AND
the raw output from running test assertions via bash.

Evaluate based on the ACTUAL execution output, not the agent's verbal summary:
- 9-10: Function implemented AND bash output shows clean execution
  (no AssertionError, no Traceback, output confirms success)
- 5-8: Function present but execution output is unclear or missing
- 1-4: No bash execution output, or output shows AssertionError/Traceback

Do NOT trust the agent's summary; look for the raw bash output.
Respond with only a single integer."""


def transform_humaneval(tasks: list[dict], sample: int, seed: int) -> list[dict]:
    """Transform HumanEval records into promptfoo cases."""
    rng = random.Random(seed)
    sampled = rng.sample(tasks, min(sample, len(tasks)))
    cases: list[dict] = []

    for task in sampled:
        test_code = f"{task['test']}\ncheck({task['entry_point']})\n"
        prompt = (
            "Complete the following Python function, then run the provided test assertions "
            "using your bash tool. Include the complete raw bash output in your response; "
            "do not paraphrase or summarize the execution result.\n\n"
            f"{task['prompt']}\n\n"
            "Test assertions to run (write to a file and execute with python3):\n"
            f"{test_code}"
            'print("All tests passed")'
        )
        cases.append(
            {
                "description": f"HumanEval {task['task_id']}",
                "vars": {"prompt": prompt},
                "assert": [
                    {
                        "type": "llm-rubric",
                        "metric": "humaneval_execution",
                        "value": _RUBRIC_TEMPLATE,
                        "threshold": 8,
                    }
                ],
                "metadata": {
                    "category": "benchmark-humaneval",
                    "task_id": task["task_id"],
                },
            }
        )

    return cases


def main() -> None:
    parser = argparse.ArgumentParser(description="Load HumanEval subset")
    parser.add_argument("--sample", type=int, default=50)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    from datasets import load_dataset

    dataset = load_dataset(_DATASET_ID, split="test")
    revision = hf_dataset_info(_DATASET_ID).sha or "unknown"
    tasks = list(dataset)
    cases = transform_humaneval(tasks, sample=args.sample, seed=args.seed)
    command = (
        "python evals/loaders/load_humaneval.py "
        f"--sample {args.sample} --seed {args.seed} --output {args.output}"
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
