"""Tests for LLM streaming."""

from unittest.mock import MagicMock, patch


def test_anthropic_chat_stream_yields_text_events():
    """Anthropic chat_stream yields text events from stream."""
    from bourbon.llm import AnthropicLLMClient

    # Mock the Anthropic client and stream
    mock_stream = MagicMock()
    mock_stream.__enter__ = MagicMock(return_value=mock_stream)
    mock_stream.__exit__ = MagicMock(return_value=None)

    # Mock events
    mock_event_text = MagicMock()
    mock_event_text.type = "content_block_delta"
    mock_event_text.delta.type = "text_delta"
    mock_event_text.delta.text = "Hello"

    mock_final_message = MagicMock()
    mock_final_message.usage.input_tokens = 10
    mock_final_message.usage.output_tokens = 5
    mock_final_message.stop_reason = "end_turn"

    mock_stream.__iter__ = MagicMock(return_value=iter([mock_event_text]))
    mock_stream.get_final_message = MagicMock(return_value=mock_final_message)

    mock_client = MagicMock()
    mock_client.messages.stream.return_value = mock_stream

    with patch("bourbon.llm.Anthropic", return_value=mock_client):
        client = AnthropicLLMClient(api_key="test", model="claude-test")
        events = list(client.chat_stream(messages=[{"role": "user", "content": "hi"}]))

    # Check text event
    text_events = [e for e in events if e["type"] == "text"]
    assert len(text_events) == 1
    assert text_events[0]["text"] == "Hello"

    # Check usage event
    usage_events = [e for e in events if e["type"] == "usage"]
    assert len(usage_events) == 1
    assert usage_events[0]["input_tokens"] == 10

    # Check stop event
    stop_events = [e for e in events if e["type"] == "stop"]
    assert len(stop_events) == 1
