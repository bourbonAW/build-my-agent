"""Tests for REPL streaming display behavior."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from rich.markdown import Markdown
from rich.text import Text


def _make_repl():
    from bourbon.repl import REPL

    repl = object.__new__(REPL)
    repl.console = MagicMock()
    repl.agent = MagicMock()
    repl._handle_pending_confirmation = MagicMock()
    repl._active_stream = None
    return repl


def test_process_input_streaming_renders_markdown():
    """Streaming responses should render with markdown formatting."""
    repl = _make_repl()

    def step_stream(_user_input, on_chunk):
        on_chunk("Hello ")
        on_chunk("**world**")
        return "Hello **world**"

    repl.agent.step_stream.side_effect = step_stream
    repl.agent.pending_confirmation = None

    with patch('bourbon.repl.Live') as mock_live:
        mock_live.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_live.return_value.__exit__ = MagicMock(return_value=False)
        repl._process_input_streaming("hi")

    # Should print the final markdown-rendered output
    repl.console.print.assert_called()
    repl._handle_pending_confirmation.assert_not_called()


def test_process_input_streaming_does_not_reprint_streamed_response():
    """Already-streamed plain text should not be rendered a second time."""
    repl = _make_repl()

    def step_stream(_user_input, on_chunk):
        on_chunk("Hello world")
        return "Hello world"

    repl.agent.step_stream.side_effect = step_stream
    repl.agent.pending_confirmation = None

    with patch('bourbon.repl.Live') as mock_live:
        mock_live.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_live.return_value.__exit__ = MagicMock(return_value=False)
        repl._process_input_streaming("hi")

    # The console.print is called multiple times (for newlines and final output)
    # but should not print the same text twice
    repl._handle_pending_confirmation.assert_not_called()


def test_process_input_streaming_prints_stable_markdown_during_stream():
    """Completed markdown lines should flush before the final response arrives."""
    repl = _make_repl()

    def step_stream(_user_input, on_chunk):
        on_chunk("First line\n")
        on_chunk("Second")
        return "First line\nSecond"

    repl.agent.step_stream.side_effect = step_stream
    repl.agent.pending_confirmation = None

    with patch("bourbon.repl.Live") as mock_live:
        mock_live.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_live.return_value.__exit__ = MagicMock(return_value=False)
        repl._process_input_streaming("hi")

    printed_args = [call.args[0] for call in repl.console.print.call_args_list if call.args]
    markdown_calls = [arg for arg in printed_args if isinstance(arg, Markdown)]
    text_calls = [arg for arg in printed_args if isinstance(arg, Text)]

    assert len(markdown_calls) >= 1
    assert any(getattr(arg, "markup", "") == "First line\n" for arg in markdown_calls)
    assert any(arg.plain == "Second" for arg in text_calls)


def test_process_input_streaming_interleaves_tool_events_with_text_timeline():
    """Tool events should print in the same append-only timeline as streamed output."""
    repl = _make_repl()

    def step_stream(_user_input, on_chunk):
        on_chunk("Intro line\npartial")
        repl._on_tool_start("bash", {"command": "ls"})
        repl._on_tool_end("bash", "file.txt")
        on_chunk("\nDone")
        return "Intro line\npartial\nDone"

    repl.agent.step_stream.side_effect = step_stream
    repl.agent.pending_confirmation = None

    with patch("bourbon.repl.Live") as mock_live:
        mock_live.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_live.return_value.__exit__ = MagicMock(return_value=False)
        repl._process_input_streaming("hi")

    printed_args = [call.args[0] for call in repl.console.print.call_args_list if call.args]

    intro_index = next(
        i
        for i, arg in enumerate(printed_args)
        if isinstance(arg, Markdown) and getattr(arg, "markup", "") == "Intro line\n"
    )
    partial_index = next(
        i for i, arg in enumerate(printed_args) if isinstance(arg, Text) and arg.plain == "partial"
    )
    tool_start_index = next(
        i for i, arg in enumerate(printed_args) if isinstance(arg, str) and "▶ bash(" in arg
    )
    tool_end_index = next(
        i for i, arg in enumerate(printed_args) if isinstance(arg, str) and "✓ bash:" in arg
    )
    done_index = next(
        i for i, arg in enumerate(printed_args) if isinstance(arg, Text) and arg.plain == "Done"
    )

    assert intro_index < partial_index < tool_start_index < tool_end_index < done_index


def test_process_input_streaming_renders_ordered_list_as_markdown():
    """Ordered lists should use Rich Markdown rendering instead of plain text."""
    repl = _make_repl()

    def step_stream(_user_input, _on_chunk):
        return "Next steps:\n1. one\n2. two"

    repl.agent.step_stream.side_effect = step_stream
    repl.agent.pending_confirmation = None

    with patch("bourbon.repl.Live") as mock_live:
        mock_live.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_live.return_value.__exit__ = MagicMock(return_value=False)
        repl._process_input_streaming("hi")

    printed_args = [call.args[0] for call in repl.console.print.call_args_list if call.args]
    assert any(isinstance(arg, Markdown) for arg in printed_args)


def test_process_input_streaming_keeps_list_block_together_until_blank_line():
    """A multi-line list should flush as one markdown block instead of line-by-line."""
    repl = _make_repl()

    def step_stream(_user_input, on_chunk):
        on_chunk("Summary\n")
        on_chunk("\n")
        on_chunk("1. one\n")
        on_chunk("2. two\n")
        on_chunk("\nNext paragraph")
        return "Summary\n\n1. one\n2. two\n\nNext paragraph"

    repl.agent.step_stream.side_effect = step_stream
    repl.agent.pending_confirmation = None

    with patch("bourbon.repl.Live") as mock_live:
        mock_live.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_live.return_value.__exit__ = MagicMock(return_value=False)
        repl._process_input_streaming("hi")

    printed_args = [call.args[0] for call in repl.console.print.call_args_list if call.args]
    markdown_blocks = [
        getattr(arg, "markup", "")
        for arg in printed_args
        if isinstance(arg, Markdown)
    ]

    assert "1. one\n2. two\n\n" in markdown_blocks


def test_process_input_streaming_does_not_print_raw_ansi_clear_sequence():
    """REPL should avoid raw ANSI clear codes before final markdown rendering."""
    repl = _make_repl()

    def step_stream(_user_input, _on_chunk):
        return "A paragraph\n\n1. one\n2. two"

    repl.agent.step_stream.side_effect = step_stream
    repl.agent.pending_confirmation = None

    with patch("bourbon.repl.Live") as mock_live:
        mock_live.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_live.return_value.__exit__ = MagicMock(return_value=False)
        repl._process_input_streaming("hi")

    assert not any(
        call.args and call.args[0] == "\r\033[K" for call in repl.console.print.call_args_list
    )


def test_activate_skill_persists_session_metadata(tmp_path: Path):
    """Skill activation should persist the injected skill message in session metadata."""
    from bourbon.repl import REPL
    from bourbon.session.manager import SessionManager
    from bourbon.session.storage import TranscriptStore

    repl = object.__new__(REPL)
    repl.console = MagicMock()
    repl.agent = MagicMock()

    store = TranscriptStore(base_dir=tmp_path)
    manager = SessionManager(store=store, project_name="test", project_dir=str(tmp_path))
    repl.agent.session = manager.create_session()
    repl.agent.skills.activate.return_value = "<skill_content name=\"demo\">demo</skill_content>"

    repl._activate_skill("demo")

    transcript = store.load_transcript("test", repl.agent.session.session_id)
    assert len(transcript) == 1
    assert "[User activated skill: demo]" in transcript[0].content[0].text

    metadata = store.load_metadata("test", repl.agent.session.session_id)
    assert metadata is not None
    assert metadata.message_count == 1
