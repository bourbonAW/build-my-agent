"""Judge validation (Engine §6; llm-eval stage 5)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import get_args

from .identity import HumanLabel, Label, validate_judge_version
from .metrics import precision_recall_f1


@dataclass(frozen=True)
class LabeledCase:
    case_id: str
    human: HumanLabel
    judge: Label

    def __post_init__(self) -> None:
        if self.human not in get_args(HumanLabel):
            raise ValueError(f"invalid human label {self.human!r}; expected {get_args(HumanLabel)}")
        if self.judge not in get_args(Label):
            raise ValueError(f"invalid judge label {self.judge!r}; expected {get_args(Label)}")


@dataclass(frozen=True)
class JudgeReport:
    judge_version: str
    model: str
    prompt_version: str
    f1: float
    threshold: float
    per_label: list[dict[str, object]]
    confusion: dict[str, int]
    gold_fail_abstained: int
    gold_pass_abstained: int
    validation_set_size: int
    min_class_support: int

    def passes(self) -> bool:
        c = self.confusion
        _, _, fail_f1 = precision_recall_f1(c["tp"], c["fp"], c["fn"])
        gold_fail = c["tp"] + c["fn"]
        gold_pass = c["fp"] + c["tn"]
        return (
            self.f1 >= self.threshold
            and fail_f1 >= self.threshold
            and gold_fail >= self.min_class_support
            and gold_pass >= self.min_class_support
        )


def validate(
    cases: list[LabeledCase],
    *,
    judge_version: str,
    model: str,
    prompt_version: str,
    threshold: float = 0.70,
    min_class_support: int = 5,
) -> JudgeReport:
    validate_judge_version(judge_version)
    ids = [case.case_id for case in cases]
    if len(set(ids)) != len(ids):
        raise ValueError(
            "duplicate case_id in validation split; judge_test is scored once per case — "
            "collapse or drop repeats before validate()"
        )

    tp = sum(1 for case in cases if case.human == "fail" and case.judge == "fail")
    fp = sum(1 for case in cases if case.human != "fail" and case.judge == "fail")
    fn = sum(1 for case in cases if case.human == "fail" and case.judge != "fail")
    tn = sum(1 for case in cases if case.human != "fail" and case.judge != "fail")

    abstain = ("uncertain", "skip")
    gold_fail_abstained = sum(
        1 for case in cases if case.human == "fail" and case.judge in abstain
    )
    gold_pass_abstained = sum(
        1 for case in cases if case.human != "fail" and case.judge in abstain
    )

    per_label: list[dict[str, object]] = []
    class_f1: list[float] = []
    for label in ("pass", "fail"):
        ltp = sum(1 for case in cases if case.human == label and case.judge == label)
        lfp = sum(1 for case in cases if case.human != label and case.judge == label)
        lfn = sum(1 for case in cases if case.human == label and case.judge != label)
        precision, recall, f1 = precision_recall_f1(ltp, lfp, lfn)
        per_label.append({"label": label, "precision": precision, "recall": recall, "f1": f1})
        class_f1.append(f1)
    macro_f1 = sum(class_f1) / len(class_f1)

    return JudgeReport(
        judge_version=judge_version,
        model=model,
        prompt_version=prompt_version,
        f1=macro_f1,
        threshold=threshold,
        per_label=per_label,
        confusion={"tp": tp, "fp": fp, "fn": fn, "tn": tn},
        gold_fail_abstained=gold_fail_abstained,
        gold_pass_abstained=gold_pass_abstained,
        validation_set_size=len(cases),
        min_class_support=min_class_support,
    )
