import pytest

from flywheel.judge import Judge, JudgeConfig, JudgeExample


def _judge(canned: str) -> Judge:
    cfg = JudgeConfig(
        judge_version="judge-v1",
        model="claude-opus-4-8",
        prompt_version="p1",
        examples=(JudgeExample("in", "must meet criteria", "good out", "pass", "meets criteria"),),
    )
    return Judge(cfg, complete=lambda prompt: canned)


def test_judge_parses_pass() -> None:
    label, critique = _judge("VERDICT: pass\nREASON: tool args correct").score_case(
        "q", "a", "args must be correct"
    )
    assert label == "pass"
    assert "tool args correct" in critique


def test_judge_parses_fail() -> None:
    label, _ = _judge("VERDICT: fail\nREASON: wrong arg shape").score_case(
        "q", "a", "args must be correct"
    )
    assert label == "fail"


def test_judge_parses_uncertain() -> None:
    label, _ = _judge("VERDICT: uncertain\nREASON: criteria don't decide").score_case(
        "q", "a", "ambiguous"
    )
    assert label == "uncertain"


def test_judge_config_rejects_bad_judge_version() -> None:
    with pytest.raises(ValueError, match="invalid judge_version"):
        JudgeConfig("judge:v1", "claude-opus-4-8", "p1", ())


def test_unparseable_verdict_raises() -> None:
    with pytest.raises(ValueError, match="no parseable VERDICT"):
        _judge("the model rambled with no verdict line").score_case("q", "a", "criteria")


def test_missing_reason_critique_raises() -> None:
    with pytest.raises(ValueError, match="no REASON critique"):
        _judge("VERDICT: pass").score_case("q", "a", "criteria")


def test_fewshot_label_must_be_binary() -> None:
    with pytest.raises(ValueError, match="invalid few-shot label"):
        JudgeExample("i", "e", "o", "uncertain", "c")  # type: ignore[arg-type]


def test_judge_prompt_includes_fewshot_and_acceptance() -> None:
    seen: dict[str, str] = {}
    cfg = JudgeConfig(
        "judge-v1",
        "claude-opus-4-8",
        "p1",
        (JudgeExample("ex-in", "ex-expected", "ex-out", "fail", "missing offset"),),
    )
    j = Judge(
        cfg, complete=lambda prompt: seen.__setitem__("p", prompt) or "VERDICT: pass\nREASON: ok"
    )
    label, critique = j.score_case("q", "a", "must page through all results")
    assert label == "pass" and critique == "ok"
    assert "missing offset" in seen["p"]
    assert "must page through all results" in seen["p"]
