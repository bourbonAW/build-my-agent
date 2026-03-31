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


def test_openai_chat_stream_yields_text_events():
    """OpenAI chat_stream yields text events from stream."""
    from bourbon.llm import OpenAILLMClient

    # Chunk 1: text content with finish_reason
    mock_chunk_text = MagicMock()
    mock_chunk_text.choices = [MagicMock()]
    mock_chunk_text.choices[0].delta = MagicMock()
    mock_chunk_text.choices[0].delta.content = "Hello"
    mock_chunk_text.choices[0].delta.tool_calls = None
    mock_chunk_text.choices[0].finish_reason = "stop"
    mock_chunk_text.usage = None

    # Chunk 2: usage-only chunk (choices is empty, per OpenAI docs with include_usage=True)
    mock_chunk_usage = MagicMock()
    mock_chunk_usage.choices = []  # Empty!
    mock_chunk_usage.usage = MagicMock()
    mock_chunk_usage.usage.prompt_tokens = 15
    mock_chunk_usage.usage.completion_tokens = 3

    mock_stream = [mock_chunk_text, mock_chunk_usage]
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_stream

    with patch("bourbon.llm.OpenAI", return_value=mock_client):
        client = OpenAILLMClient(api_key="test", model="gpt-test")
        events = list(client.chat_stream(messages=[{"role": "user", "content": "hi"}]))

    # Verify stream_options was passed
    call_kwargs = mock_client.chat.completions.create.call_args[1]
    assert call_kwargs["stream_options"] == {"include_usage": True}

    # Check text event
    text_events = [e for e in events if e["type"] == "text"]
    assert len(text_events) == 1
    assert text_events[0]["text"] == "Hello"

    # Check usage event (from trailing chunk)
    usage_events = [e for e in events if e["type"] == "usage"]
    assert len(usage_events) == 1
    assert usage_events[0]["input_tokens"] == 15
    assert usage_events[0]["output_tokens"] == 3

    # Check stop event
    stop_events = [e for e in events if e["type"] == "stop"]
    assert len(stop_events) == 1
    assert stop_events[0]["stop_reason"] == "end_turn"


def test_anthropic_chat_stream_accumulates_tool_input_json():
    """Anthropic chat_stream assembles partial tool JSON before yielding tool_use."""
    from bourbon.llm import AnthropicLLMClient

    mock_stream = MagicMock()
    mock_stream.__enter__ = MagicMock(return_value=mock_stream)
    mock_stream.__exit__ = MagicMock(return_value=None)

    start_event = MagicMock()
    start_event.type = "content_block_start"
    start_event.content_block.type = "tool_use"
    start_event.content_block.id = "tool-1"
    start_event.content_block.name = "bash"

    json_event_1 = MagicMock()
    json_event_1.type = "content_block_delta"
    json_event_1.delta.type = "input_json_delta"
    json_event_1.delta.partial_json = '{"command":"ec'

    json_event_2 = MagicMock()
    json_event_2.type = "content_block_delta"
    json_event_2.delta.type = "input_json_delta"
    json_event_2.delta.partial_json = 'ho hi"}'

    stop_event = MagicMock()
    stop_event.type = "content_block_stop"

    mock_final_message = MagicMock()
    mock_final_message.usage.input_tokens = 10
    mock_final_message.usage.output_tokens = 5
    mock_final_message.stop_reason = "tool_use"

    mock_stream.__iter__ = MagicMock(
        return_value=iter([start_event, json_event_1, json_event_2, stop_event])
    )
    mock_stream.get_final_message = MagicMock(return_value=mock_final_message)

    mock_client = MagicMock()
    mock_client.messages.stream.return_value = mock_stream

    with patch("bourbon.llm.Anthropic", return_value=mock_client):
        client = AnthropicLLMClient(api_key="test", model="claude-test")
        events = list(client.chat_stream(messages=[{"role": "user", "content": "hi"}]))

    tool_events = [e for e in events if e["type"] == "tool_use"]
    assert len(tool_events) == 1
    assert tool_events[0]["id"] == "tool-1"
    assert tool_events[0]["name"] == "bash"
    assert tool_events[0]["input"] == {"command": "echo hi"}


def test_openai_chat_stream_accumulates_tool_calls_across_chunks():
    """OpenAI chat_stream merges split tool-call deltas into one tool_use event."""
    from bourbon.llm import OpenAILLMClient

    chunk_1 = MagicMock()
    chunk_1.choices = [MagicMock()]
    chunk_1.choices[0].delta = MagicMock()
    chunk_1.choices[0].delta.content = None
    chunk_1.choices[0].delta.tool_calls = [MagicMock()]
    chunk_1.choices[0].delta.tool_calls[0].index = 0
    chunk_1.choices[0].delta.tool_calls[0].id = "call_1"
    chunk_1.choices[0].delta.tool_calls[0].function = MagicMock()
    chunk_1.choices[0].delta.tool_calls[0].function.name = "bash"
    chunk_1.choices[0].delta.tool_calls[0].function.arguments = '{"command":"ec'
    chunk_1.choices[0].finish_reason = None
    chunk_1.usage = None

    chunk_2 = MagicMock()
    chunk_2.choices = [MagicMock()]
    chunk_2.choices[0].delta = MagicMock()
    chunk_2.choices[0].delta.content = None
    chunk_2.choices[0].delta.tool_calls = [MagicMock()]
    chunk_2.choices[0].delta.tool_calls[0].index = 0
    chunk_2.choices[0].delta.tool_calls[0].id = None
    chunk_2.choices[0].delta.tool_calls[0].function = MagicMock()
    chunk_2.choices[0].delta.tool_calls[0].function.name = None
    chunk_2.choices[0].delta.tool_calls[0].function.arguments = 'ho hi"}'
    chunk_2.choices[0].finish_reason = "tool_calls"
    chunk_2.usage = None

    chunk_3 = MagicMock()
    chunk_3.choices = []
    chunk_3.usage = MagicMock()
    chunk_3.usage.prompt_tokens = 20
    chunk_3.usage.completion_tokens = 4

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = [chunk_1, chunk_2, chunk_3]

    with patch("bourbon.llm.OpenAI", return_value=mock_client):
        client = OpenAILLMClient(api_key="test", model="gpt-test")
        events = list(client.chat_stream(messages=[{"role": "user", "content": "hi"}]))

    tool_events = [e for e in events if e["type"] == "tool_use"]
    assert len(tool_events) == 1
    assert tool_events[0]["id"] == "call_1"
    assert tool_events[0]["name"] == "bash"
    assert tool_events[0]["input"] == {"command": "echo hi"}

    stop_events = [e for e in events if e["type"] == "stop"]
    assert len(stop_events) == 1
    assert stop_events[0]["stop_reason"] == "tool_use"
