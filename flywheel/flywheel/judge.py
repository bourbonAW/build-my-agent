"""LLM judge runner (Engine §6; llm-eval stage 4)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, get_args

from .identity import HumanLabel, Label, validate_judge_version

_NEUTRAL_SYSTEM = (
    "You are grading whether an agent's output satisfies the case's acceptance "
    "criteria. Reply with two lines:\nVERDICT: pass|fail|uncertain\nREASON: <one line>"
    "\nUse 'uncertain' only when the acceptance criteria genuinely do not let you "
    "decide; prefer pass or fail."
)


@dataclass(frozen=True)
class JudgeExample:
    input: str
    expected: str
    output: str
    label: HumanLabel
    critique: str

    def __post_init__(self) -> None:
        if self.label not in get_args(HumanLabel):
            raise ValueError(
                f"invalid few-shot label {self.label!r}; examples carry binary human gold, "
                f"expected {get_args(HumanLabel)}"
            )


@dataclass(frozen=True)
class JudgeConfig:
    judge_version: str
    model: str
    prompt_version: str
    examples: tuple[JudgeExample, ...]

    def __post_init__(self) -> None:
        validate_judge_version(self.judge_version)


class Judge:
    def __init__(self, config: JudgeConfig, complete: Callable[[str], str]):
        self._config = config
        self._complete = complete

    def _prompt(self, case_input: str, case_output: str, acceptance: str) -> str:
        shots = "\n\n".join(
            f"INPUT: {example.input}\nACCEPTANCE: {example.expected}\n"
            f"OUTPUT: {example.output}\nVERDICT: {example.label}\nREASON: {example.critique}"
            for example in self._config.examples
        )
        return (
            f"{_NEUTRAL_SYSTEM}\n\n# Examples\n{shots}\n\n"
            f"# Case\nINPUT: {case_input}\nACCEPTANCE: {acceptance}\nOUTPUT: {case_output}\n"
        )

    def score_case(self, case_input: str, case_output: str, acceptance: str) -> tuple[Label, str]:
        raw = self._complete(self._prompt(case_input, case_output, acceptance))
        verdict: str | None = None
        critique = ""
        for line in raw.splitlines():
            stripped = line.strip()
            low = stripped.lower()
            if low.startswith("verdict:"):
                verdict = low.split(":", 1)[1].strip()
            elif low.startswith("reason:"):
                critique = stripped.split(":", 1)[1].strip()
        if verdict not in ("pass", "fail", "uncertain"):
            raise ValueError(
                f"judge response has no parseable VERDICT (pass/fail/uncertain): {raw!r}"
            )
        if not critique:
            raise ValueError(f"judge verdict has no REASON critique: {raw!r}")
        if verdict == "pass":
            return "pass", critique
        if verdict == "fail":
            return "fail", critique
        return "uncertain", critique
