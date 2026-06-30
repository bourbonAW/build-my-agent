"""Run Bourbon on regression dataset items and mirror dataset-run outputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import TYPE_CHECKING

from flywheel.identity import Harness

if TYPE_CHECKING:
    from bourbon.agent import Agent

from scripts.common import (
    DEFAULT_ROOT,
    RunOutput,
    current_git_sha,
    ensure_disjoint_splits,
    items_for_split,
    load_dataset_items,
    require_failure_labels,
    slugify,
    utc_timestamp_slug,
    write_run_outputs,
)


def _build_agent(workdir: Path, model: str) -> "Agent":
    from bourbon.agent import Agent
    from bourbon.config import ConfigManager

    config = ConfigManager().load_config()
    provider = config.llm.default_provider
    if provider == "anthropic":
        config.llm.anthropic.model = model
    elif provider == "openai":
        config.llm.openai.model = model
    return Agent(config=config, workdir=workdir)


def _render_template(
    template: str, *, case_id: str, run_id: str, repeat_index: int, text: str
) -> str:
    return template.format(case_id=case_id, run_id=run_id, repeat_index=repeat_index, input=text)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default="bourbon")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--dataset-json", type=Path, default=None)
    parser.add_argument("--dataset", default=None)
    parser.add_argument("--workdir", type=Path, default=Path.cwd().parent)
    parser.add_argument("--git-sha", default=None)
    parser.add_argument("--model", required=True)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument(
        "--output-template",
        default=None,
        help="Local smoke shortcut; if set, do not invoke Bourbon.",
    )
    parser.add_argument(
        "--trace-url-template",
        default="",
        help="Optional format string with {case_id}, {run_id}, and {sample_id}.",
    )
    args = parser.parse_args()

    if args.repeat < 1:
        raise SystemExit("--repeat must be >= 1")

    items = load_dataset_items(args.dataset_json, args.dataset)
    ensure_disjoint_splits(items)
    regression_items = items_for_split(items, "regression")
    require_failure_labels(regression_items)
    if not regression_items:
        raise SystemExit("dataset has no regression items")

    git_sha = args.git_sha or current_git_sha(args.workdir)
    harness = Harness(git_sha=git_sha, model=args.model)
    run_id = args.run_id or f"{slugify(harness.id())}-{utc_timestamp_slug()}"
    outputs: list[RunOutput] = []

    for item in regression_items:
        for repeat_index in range(args.repeat):
            sample_id = f"{item.case_id}-r{repeat_index + 1}"
            if args.output_template is None:
                agent = _build_agent(args.workdir, args.model)
                agent.set_eval_context(case_id=item.case_id, run_id=run_id)
                output = agent.step(item.input)
            else:
                output = _render_template(
                    args.output_template,
                    case_id=item.case_id,
                    run_id=run_id,
                    repeat_index=repeat_index + 1,
                    text=item.input,
                )
            trace_url = (
                args.trace_url_template.format(
                    case_id=item.case_id,
                    run_id=run_id,
                    sample_id=sample_id,
                )
                if args.trace_url_template
                else ""
            )
            outputs.append(
                RunOutput(
                    case_id=item.case_id,
                    run_id=run_id,
                    harness_id=harness.id(),
                    output=output,
                    trace_url=trace_url,
                    repeat_index=repeat_index + 1,
                    sample_id=sample_id,
                )
            )

    write_run_outputs(
        args.root,
        args.project,
        run_id,
        outputs,
        {
            "runId": run_id,
            "harness": harness.id(),
            "gitSha": git_sha,
            "model": args.model,
            "createdAt": utc_timestamp_slug(),
            "repeat": args.repeat,
        },
    )
    print(
        json.dumps(
            {
                "runId": run_id,
                "harness": harness.id(),
                "cases": len(regression_items),
                "outputs": len(outputs),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
