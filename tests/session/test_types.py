"""Tests for session core types."""

from bourbon.session.types import (
    CompactResult,
    MessageRole,
    TextBlock,
    TokenUsage,
    ToolResultBlock,
    ToolUseBlock,
    TranscriptMessage,
)


def test_transcript_message_creation():
    msg = TranscriptMessage(
        role=MessageRole.USER,
        content=[TextBlock(text="Hello")],
    )
    assert msg.role == MessageRole.USER
    assert msg.parent_uuid is None
    assert msg.logical_parent_uuid is None


def test_transcript_message_to_llm_format():
    msg = TranscriptMessage(
        role=MessageRole.ASSISTANT,
        content=[
            TextBlock(text="Let me check"),
            ToolUseBlock(id="tool_1", name="read_file", input={"path": "test.py"}),
        ],
    )

    llm_format = msg.to_llm_format()
    assert llm_format["role"] == "assistant"
    assert len(llm_format["content"]) == 2
    assert llm_format["content"][0]["type"] == "text"
    assert llm_format["content"][1]["type"] == "tool_use"


def test_tool_result_block():
    block = ToolResultBlock(
        tool_use_id="tool_1",
        content="File content",
        is_error=False,
    )
    assert block.tool_use_id == "tool_1"
    assert block.is_error is False


def test_token_usage_addition():
    u1 = TokenUsage(input_tokens=100, output_tokens=50)
    u2 = TokenUsage(input_tokens=50, output_tokens=25)
    total = u1 + u2
    assert total.input_tokens == 150
    assert total.output_tokens == 75


def test_compact_result():
    result = CompactResult(
        success=True,
        archived_count=10,
        preserved_count=5,
        reason="test",
    )
    assert result.success is True
    assert result.archived_count == 10
