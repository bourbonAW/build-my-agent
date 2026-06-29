"""Minimal eval identity (Engine §4). Four concepts carry the loop:
case_id, run_id, label, trace_id. case_id/run_id live as Langfuse dataset item
ids and run names, mirrored on spans as eval.case_id / eval.run_id. This module
holds the two small typed extras: the label enum and the harness fingerprint."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

Label = Literal["pass", "fail", "skip", "uncertain"]
HumanLabel = Literal["pass", "fail"]
JudgeVersion = str

_JUDGE_VERSION_RE = re.compile(r"[A-Za-z0-9._@-]+")


def validate_judge_version(value: str) -> str:
    """Enforce the JudgeVersion slug contract at the typed boundary."""
    if not _JUDGE_VERSION_RE.fullmatch(value) or value in (".", ".."):
        raise ValueError(
            f"invalid judge_version {value!r}; must be a slug [A-Za-z0-9._@-]+ "
            "and not '.'/'..'"
        )
    return value


@dataclass(frozen=True)
class Harness:
    git_sha: str
    model: str

    def id(self) -> str:
        return f"{self.git_sha[:7]}@{self.model}"
