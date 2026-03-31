"""Tests for REPL activity indicator renderable."""

from unittest.mock import patch

from rich.console import Console


def _render_text(renderable, now: float) -> str:
    """Render a Rich renderable to plain text with a mocked clock."""
    console = Console(record=True, width=100, force_terminal=False, color_system=None)
    with patch("bourbon.repl.time.monotonic", return_value=now):
        console.print(renderable)
    return console.export_text()


def test_activity_indicator_shows_thinking_before_first_chunk():
    """The live status should reassure the user before streaming begins."""
    from bourbon.repl import StreamingDisplay

    display = StreamingDisplay(started_at=100.0)

    output = _render_text(display, now=100.25)

    assert "Bourbon is thinking..." in output
    assert "🥃" in output


def test_activity_indicator_switches_to_replying_after_chunk():
    """Once text starts arriving, the status should reflect active replying."""
    from bourbon.repl import StreamingDisplay

    display = StreamingDisplay(started_at=100.0)
    display.append_chunk("Hello world")

    output = _render_text(display, now=100.25)

    assert "Bourbon is replying..." in output


def test_activity_indicator_renders_stable_prefix_and_buffers_pending_tail():
    """Live render should show stable markdown while buffering incomplete tail text."""
    from bourbon.repl import StreamingDisplay

    display = StreamingDisplay(started_at=100.0)
    display.append_chunk("## Heading\n- ite")

    output = _render_text(display, now=100.25)

    assert "Heading" in output
    assert "- ite" in output
    assert " • ite" not in output


def test_activity_indicator_renders_complete_markdown_list_item():
    """Once a markdown line is complete, it should move into rendered output."""
    from bourbon.repl import StreamingDisplay

    display = StreamingDisplay(started_at=100.0)
    display.append_chunk("## Heading\n- item\n")

    output = _render_text(display, now=100.25)

    assert "Heading" in output
    assert " • item" in output


def test_activity_indicator_buffers_unclosed_fenced_code_block():
    """An unclosed fenced block should remain in the pending tail until closed."""
    from bourbon.repl import StreamingDisplay

    display = StreamingDisplay(started_at=100.0)
    display.append_chunk("Before\n```python\nprint('x')\n")

    output = _render_text(display, now=100.25)

    assert "Before" in output
    assert "```python" in output


def test_activity_indicator_buffers_unclosed_link_line():
    """A line with an unfinished markdown link should remain in the pending tail."""
    from bourbon.repl import StreamingDisplay

    display = StreamingDisplay(started_at=100.0)
    display.append_chunk("A [link](https://example.com\n")

    output = _render_text(display, now=100.25)

    assert "A [link](https://example.com" in output
    assert "A link" not in output


def test_activity_indicator_renders_complete_markdown_link():
    """A completed markdown link should render in the stable prefix."""
    from bourbon.repl import StreamingDisplay

    display = StreamingDisplay(started_at=100.0)
    display.append_chunk("A [link](https://example.com)\n")

    output = _render_text(display, now=100.25)

    assert "A link" in output


def test_activity_indicator_buffers_incomplete_table_header():
    """A lone table header should remain pending until the table structure is complete."""
    from bourbon.repl import StreamingDisplay

    display = StreamingDisplay(started_at=100.0)
    display.append_chunk("| Col | Val |\n")

    output = _render_text(display, now=100.25)

    assert "| Col | Val |" in output


def test_activity_indicator_renders_table_once_separator_arrives():
    """Header plus separator should move into rendered markdown output."""
    from bourbon.repl import StreamingDisplay

    display = StreamingDisplay(started_at=100.0)
    display.append_chunk("| Col | Val |\n| --- | --- |\n")

    output = _render_text(display, now=100.25)

    assert " Col  Val " in output


def test_split_stable_markdown_keeps_unclosed_link_in_pending_tail():
    """Unclosed markdown links should not enter the stable prefix."""
    from bourbon.repl import _split_stable_markdown

    stable_prefix, pending_tail = _split_stable_markdown("A [link](https://example.com\n")

    assert stable_prefix == ""
    assert pending_tail == "A [link](https://example.com\n"


def test_split_stable_markdown_keeps_lone_table_header_in_pending_tail():
    """A table header alone should wait for the separator row."""
    from bourbon.repl import _split_stable_markdown

    stable_prefix, pending_tail = _split_stable_markdown("| Col | Val |\n")

    assert stable_prefix == ""
    assert pending_tail == "| Col | Val |\n"


def test_activity_indicator_frame_changes_over_time():
    """The indicator should animate even without new chunks."""
    from bourbon.repl import StreamingDisplay

    display = StreamingDisplay(started_at=100.0)

    first = _render_text(display, now=100.00)
    second = _render_text(display, now=100.25)

    assert first.splitlines()[0] != second.splitlines()[0]
