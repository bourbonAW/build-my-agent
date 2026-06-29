from typing import get_args

import pytest

from flywheel.identity import Harness, HumanLabel, Label, validate_judge_version


def test_label_values() -> None:
    assert set(get_args(Label)) == {"pass", "fail", "skip", "uncertain"}


def test_judge_version_slug_accepts_and_rejects() -> None:
    assert validate_judge_version("judge-v2.1@m") == "judge-v2.1@m"
    for bad in ("judge:v1", "judge/v1", "judge v1", "judge-v1\n", ".", "..", ""):
        with pytest.raises(ValueError, match="invalid judge_version"):
            validate_judge_version(bad)


def test_human_label_is_binary() -> None:
    assert set(get_args(HumanLabel)) == {"pass", "fail"}


def test_harness_id_is_short_and_stable() -> None:
    h = Harness(git_sha="abc1234def", model="claude-opus-4-8")
    assert h.id() == "abc1234@claude-opus-4-8"
    assert Harness(git_sha="abc1234def", model="claude-opus-4-8").id() == h.id()


def test_harness_id_changes_with_model() -> None:
    a = Harness(git_sha="abc1234def", model="claude-opus-4-8").id()
    b = Harness(git_sha="abc1234def", model="claude-sonnet-4-6").id()
    assert a != b
