"""Run the LLM judge on one split or one regression dataset run."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Callable, cast

from flywheel.judge import Judge, JudgeConfig, JudgeExample

from scripts.common import (
    DEFAULT_ROOT,
    DatasetItem,
    RunOutput,
    ScoreRecord,
    Split,
    ensure_disjoint_splits,
    items_for_split,
    load_dataset_items,
    load_run_outputs,
    write_score_records,
)


def _example(item: DatasetItem) -> JudgeExample:
    if item.frozen_output is None or item.human_label is None:
        raise ValueError(
            f"judge_train item {item.case_id!r} needs frozen_output and binary human_label"
        )
    critique = str(item.metadata.get("critique", item.metadata.get("comment", "human gold label")))
    return JudgeExample(item.input, item.expected, item.frozen_output, item.human_label, critique)


def _anthropic_complete(model: str) -> Callable[[str], str]:
    from anthropic import Anthropic

    client = Anthropic()

    def complete(prompt: str) -> str:
        message = client.messages.create(
            model=model,
            max_tokens=512,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        parts: list[str] = []
        for block in message.content:
            text = getattr(block, "text", None)
            if isinstance(text, str):
                parts.append(text)
        return "\n".join(parts)

    return complete


def _target_outputs_for_frozen(items: list[DatasetItem]) -> list[tuple[DatasetItem, str, str, str]]:
    out: list[tuple[DatasetItem, str, str, str]] = []
    for item in items:
        if item.frozen_output is None:
            raise ValueError(f"{item.splits} item {item.case_id!r} needs frozen_output")
        out.append((item, item.frozen_output, item.trace_url, item.case_id))
    return out


def _target_outputs_for_run(
    items: list[DatasetItem],
    outputs: list[RunOutput],
) -> list[tuple[DatasetItem, str, str, str]]:
    by_case = {item.case_id: item for item in items}
    out: list[tuple[DatasetItem, str, str, str]] = []
    for output in outputs:
        item = by_case.get(output.case_id)
        if item is not None:
            out.append((item, output.output, output.trace_url, output.sample_id))
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default="bourbon")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--dataset-json", type=Path, default=None)
    parser.add_argument("--dataset", default=None)
    parser.add_argument("--split", required=True, choices=("judge_dev", "judge_test", "regression"))
    parser.add_argument("--run", default=None, help="Required when --split regression")
    parser.add_argument("--judge-version", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--prompt-version", required=True)
    parser.add_argument("--canned-response", default=None)
    parser.add_argument(
        "--canned-labels-json",
        type=Path,
        default=None,
        help="Local smoke map of case_id or sample_id to full VERDICT/REASON response.",
    )
    parser.add_argument(
        "--skip-on-protocol-error",
        action="store_true",
        help="Persist operational protocol failures as skip instead of aborting.",
    )
    args = parser.parse_args()

    split = cast(Split, args.split)
    items = load_dataset_items(args.dataset_json, args.dataset)
    ensure_disjoint_splits(items)

    train_items = items_for_split(items, "judge_train")
    if not train_items:
        raise SystemExit("dataset has no judge_train examples")
    examples = tuple(_example(item) for item in train_items)
    canned_by_key = (
        json.loads(args.canned_labels_json.read_text()) if args.canned_labels_json else None
    )
    complete = (
        None
        if canned_by_key
        else (
            (lambda _prompt: args.canned_response)
            if args.canned_response
            else _anthropic_complete(args.model)
        )
    )
    config = JudgeConfig(args.judge_version, args.model, args.prompt_version, examples)

    if split == "regression":
        if not args.run:
            raise SystemExit("--run is required for --split regression")
        target = args.run
        target_items = items_for_split(items, "regression")
        outputs = _target_outputs_for_run(
            target_items, load_run_outputs(args.root, args.project, args.run)
        )
    else:
        target = split
        target_items = items_for_split(items, split)
        outputs = _target_outputs_for_frozen(target_items)

    if not outputs:
        raise SystemExit(f"no outputs to judge for target {target!r}")

    records: list[ScoreRecord] = []
    for item, output, trace_url, sample_id in outputs:
        response = (
            None
            if canned_by_key is None
            else canned_by_key.get(sample_id, canned_by_key.get(item.case_id))
        )
        if canned_by_key is not None and response is None:
            raise ValueError(f"missing canned response for {sample_id!r} / {item.case_id!r}")
        complete_fn: Callable[[str], str]
        if response is not None:
            canned = response
            complete_fn = lambda _prompt: str(canned)  # noqa: E731
        else:
            # response is None only when canned_by_key is None (guarded above),
            # which is exactly when `complete` was built as a live callable.
            assert complete is not None
            complete_fn = complete
        judge = Judge(config, complete=complete_fn)
        try:
            label, critique = judge.score_case(item.input, output, item.expected)
        except ValueError as exc:
            if not args.skip_on_protocol_error:
                raise
            label, critique = "skip", f"operational skip: {exc}"
        records.append(
            ScoreRecord(
                case_id=item.case_id,
                run_id=target,
                judge_version=args.judge_version,
                model=args.model,
                prompt_version=args.prompt_version,
                label=label,
                critique=critique,
                trace_url=trace_url,
                sample_id=sample_id,
            )
        )

    write_score_records(args.root, args.project, target, args.judge_version, records)
    print(
        json.dumps(
            {
                "target": target,
                "judgeVersion": args.judge_version,
                "scores": len(records),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
