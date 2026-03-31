"""Tests for REPL dynamic context display in bottom toolbar."""

from unittest.mock import MagicMock


def _make_repl_with_tokens(tokens: int, threshold: int, show_token_count: bool = True):
    """Create a REPL instance with mocked agent/config for toolbar testing."""
    from bourbon.repl import REPL

    repl = object.__new__(REPL)
    repl.agent = MagicMock()
    repl.agent.get_session_tokens.return_value = tokens
    repl.agent.compressor.token_threshold = threshold
    repl.config = MagicMock()
    repl.config.ui.show_token_count = show_token_count
    return repl


def test_get_prompt_simple():
    """_get_prompt returns simple prompt without context."""
    repl = _make_repl_with_tokens(50_000, 200_000)
    prompt = repl._get_prompt()
    assert "bourbon >>" in str(prompt)
    # Context should NOT be in prompt anymore
    assert "context:" not in str(prompt)


def test_get_bottom_toolbar_shows_context_percentage():
    """_get_bottom_toolbar displays correct percentage."""
    repl = _make_repl_with_tokens(50_000, 200_000)
    toolbar = repl._get_bottom_toolbar()
    # 25%
    assert "25.0%" in str(toolbar)


def test_get_bottom_toolbar_gray_under_50_percent():
    """Context color is gray when under 50%."""
    repl = _make_repl_with_tokens(20_000, 200_000)
    toolbar_str = str(repl._get_bottom_toolbar())
    assert "#888888" in toolbar_str


def test_get_bottom_toolbar_orange_between_50_and_80_percent():
    """Context color is orange between 50-80%."""
    repl = _make_repl_with_tokens(120_000, 200_000)
    toolbar_str = str(repl._get_bottom_toolbar())
    assert "#FFA500" in toolbar_str


def test_get_bottom_toolbar_red_above_80_percent():
    """Context color is red above 80%."""
    repl = _make_repl_with_tokens(180_000, 200_000)
    toolbar_str = str(repl._get_bottom_toolbar())
    assert "#FF4444" in toolbar_str


def test_get_bottom_toolbar_hidden_when_show_token_count_false():
    """_get_bottom_toolbar hides context when show_token_count is False."""
    repl = _make_repl_with_tokens(50_000, 200_000, show_token_count=False)
    toolbar_str = str(repl._get_bottom_toolbar())
    assert "context:" not in toolbar_str
    assert "bourbon" not in toolbar_str  # Empty toolbar


def test_get_bottom_toolbar_caps_at_100_percent():
    """Percentage caps at 100% even if tokens exceed threshold."""
    repl = _make_repl_with_tokens(250_000, 200_000)
    toolbar_str = str(repl._get_bottom_toolbar())
    assert "100.0%" in toolbar_str


def test_get_bottom_toolbar_shows_unknown_context_when_estimation_fails():
    """Token estimation failures still show a context indicator."""
    from bourbon.repl import REPL

    repl = object.__new__(REPL)
    repl.agent = MagicMock()
    repl.agent.get_session_tokens.side_effect = RuntimeError("boom")
    repl.agent.compressor.token_threshold = 200_000
    repl.config = MagicMock()
    repl.config.ui.show_token_count = True

    toolbar_str = str(repl._get_bottom_toolbar())
    assert "context: --" in toolbar_str
