"""Tests for REPL dynamic context display prompt."""

from unittest.mock import MagicMock


def _make_repl_with_tokens(tokens: int, threshold: int, show_token_count: bool = True):
    """Create a REPL instance with mocked agent/config for prompt testing."""
    from bourbon.repl import REPL

    repl = object.__new__(REPL)
    repl.agent = MagicMock()
    repl.agent.get_session_tokens.return_value = tokens
    repl.agent.compressor.token_threshold = threshold
    repl.config = MagicMock()
    repl.config.ui.show_token_count = show_token_count
    return repl


def test_get_prompt_shows_context_percentage():
    """_get_prompt displays correct percentage."""
    repl = _make_repl_with_tokens(50_000, 200_000)
    prompt = repl._get_prompt()
    # 25%
    assert "25.0%" in str(prompt)


def test_get_prompt_gray_under_50_percent():
    """Context color is gray when under 50%."""
    repl = _make_repl_with_tokens(20_000, 200_000)
    prompt_str = str(repl._get_prompt())
    assert "#888888" in prompt_str


def test_get_prompt_orange_between_50_and_80_percent():
    """Context color is orange between 50-80%."""
    repl = _make_repl_with_tokens(120_000, 200_000)
    prompt_str = str(repl._get_prompt())
    assert "#FFA500" in prompt_str


def test_get_prompt_red_above_80_percent():
    """Context color is red above 80%."""
    repl = _make_repl_with_tokens(180_000, 200_000)
    prompt_str = str(repl._get_prompt())
    assert "#FF4444" in prompt_str


def test_get_prompt_hidden_when_show_token_count_false():
    """_get_prompt hides context when show_token_count is False."""
    repl = _make_repl_with_tokens(50_000, 200_000, show_token_count=False)
    prompt_str = str(repl._get_prompt())
    assert "context:" not in prompt_str
    assert "bourbon" in prompt_str


def test_get_prompt_caps_at_100_percent():
    """Percentage caps at 100% even if tokens exceed threshold."""
    repl = _make_repl_with_tokens(250_000, 200_000)
    prompt_str = str(repl._get_prompt())
    assert "100.0%" in prompt_str
