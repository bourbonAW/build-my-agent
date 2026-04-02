"""Loader for GAIA Level 1 benchmark cases."""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

import pyarrow.parquet as pq
from huggingface_hub import dataset_info as hf_dataset_info
from huggingface_hub import hf_hub_download

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evals.loaders.common import write_yaml_with_header

_DATASET_ID = "gaia-benchmark/GAIA"
_PARQUET_FILE = "2023/validation/metadata.level1.parquet"
_WEB_KEYWORDS = (
    "search",
    "look up",
    "find online",
    "google",
    "web",
    "browse",
    "current price",
    "latest",
    "today",
    "real-time",
)
_JS_ASSERTION = """\
const parsed = JSON.parse(output);
const data = typeof parsed.output === 'string' ? JSON.parse(parsed.output) : parsed;
const text = data.text.toLowerCase();
const ans = context.vars.expected_answer.toLowerCase();
return text.includes(ans);
"""


def _requires_attachment(task: dict) -> bool:
    """Return whether the GAIA task requires an attached file."""
    return bool(str(task.get("file_name", "")).strip())


def _requires_web(task: dict) -> bool:
    """Return whether the GAIA task appears to require web access."""
    metadata = task.get("Annotator Metadata") or {}
    steps = str(metadata.get("Steps", "")).lower() if isinstance(metadata, dict) else ""
    question = str(task.get("Question", "")).lower()
    return any(keyword in steps or keyword in question for keyword in _WEB_KEYWORDS)


def transform_gaia(
    tasks: list[dict],
    sample: int,
    seed: int,
    exclude_attachments: bool,
    exclude_web: bool,
) -> list[dict]:
    """Filter and transform GAIA Level 1 records into promptfoo cases."""
    pool = list(tasks)
    if exclude_attachments:
        pool = [task for task in pool if not _requires_attachment(task)]
    if exclude_web:
        pool = [task for task in pool if not _requires_web(task)]

    if len(pool) < sample:
        print(
            f"Warning: only {len(pool)} tasks available after filtering "
            f"(requested {sample}). Using full pool."
        )

    rng = random.Random(seed)
    sampled = rng.sample(pool, min(sample, len(pool)))
    cases: list[dict] = []
    for index, task in enumerate(sampled):
        cases.append(
            {
                "description": f"GAIA L1 #{index}: {str(task['Question'])[:60].rstrip()}",
                "vars": {
                    "prompt": task["Question"],
                    "expected_answer": task["Final answer"],
                },
                "assert": [{"type": "javascript", "value": _JS_ASSERTION}],
                "metadata": {
                    "category": "benchmark-gaia",
                    "level": 1,
                },
            }
        )
    return cases


def main() -> None:
    parser = argparse.ArgumentParser(description="Load GAIA Level 1 subset")
    parser.add_argument("--sample", type=int, default=30)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--exclude-attachments", action="store_true")
    parser.add_argument("--exclude-web", action="store_true")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    parquet_path = hf_hub_download(_DATASET_ID, repo_type="dataset", filename=_PARQUET_FILE)
    tasks = pq.read_table(parquet_path).to_pylist()
    revision = hf_dataset_info(_DATASET_ID).sha or "unknown"
    print(f"Loaded {len(tasks)} Level 1 tasks")
    cases = transform_gaia(
        tasks,
        sample=args.sample,
        seed=args.seed,
        exclude_attachments=args.exclude_attachments,
        exclude_web=args.exclude_web,
    )
    command = (
        f"python evals/loaders/load_gaia.py --sample {args.sample} --seed {args.seed}"
        + (" --exclude-attachments" if args.exclude_attachments else "")
        + (" --exclude-web" if args.exclude_web else "")
        + f" --output {args.output}"
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
