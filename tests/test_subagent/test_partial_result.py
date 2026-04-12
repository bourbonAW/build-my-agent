from bourbon.session.types import MessageRole, TextBlock, ToolUseBlock, TranscriptMessage
from bourbon.subagent.partial_result import extract_partial_result


def test_extract_partial_from_assistant_message():
    messages = [
        TranscriptMessage(
            role=MessageRole.USER,
            content=[TextBlock(text="Hello")],
        ),
        TranscriptMessage(
            role=MessageRole.ASSISTANT,
            content=[TextBlock(text="Working on it...")],
        ),
    ]

    result = extract_partial_result(messages)

    assert result == "Working on it..."


def test_extract_partial_skips_empty_assistant_messages():
    messages = [
        TranscriptMessage(
            role=MessageRole.ASSISTANT,
            content=[ToolUseBlock(id="1", name="Read", input={})],
        ),
        TranscriptMessage(
            role=MessageRole.ASSISTANT,
            content=[TextBlock(text="Final result")],
        ),
    ]

    result = extract_partial_result(messages)

    assert result == "Final result"


def test_extract_partial_combines_text_blocks_from_latest_assistant_message():
    messages = [
        TranscriptMessage(
            role=MessageRole.ASSISTANT,
            content=[TextBlock(text="Older result")],
        ),
        TranscriptMessage(
            role=MessageRole.ASSISTANT,
            content=[TextBlock(text="Line 1"), TextBlock(text="Line 2")],
        ),
    ]

    result = extract_partial_result(messages)

    assert result == "Line 1\nLine 2"


def test_extract_partial_truncates_long_content():
    long_text = "x" * 3000
    messages = [
        TranscriptMessage(
            role=MessageRole.ASSISTANT,
            content=[TextBlock(text=long_text)],
        ),
    ]

    result = extract_partial_result(messages)

    assert len(result) < 2500
    assert result.endswith("... (truncated)")


def test_extract_partial_no_content():
    messages = [
        TranscriptMessage(
            role=MessageRole.USER,
            content=[TextBlock(text="Hello")],
        ),
    ]

    result = extract_partial_result(messages)

    assert "No partial result" in result
