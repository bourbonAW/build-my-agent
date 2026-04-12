# REPL Streaming Output & Context Display Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add LLM streaming output and real-time context display to Bourbon REPL.

**Architecture:** Extend LLM/Agent/REPL layers with `chat_stream()` and `step_stream()` methods while keeping synchronous APIs intact. Stream text chunks in real-time, then re-render with markdown if needed. Display context percentage in the dynamic prompt.

**Tech Stack:** Python, Anthropic SDK, OpenAI SDK, prompt_toolkit, Rich, pytest

---

## File Structure

| File | Responsibility | Action |
|------|---------------|--------|
| `src/bourbon/llm.py` | LLM client abstractions | Add `chat_stream()` abstract + implementations |
| `src/bourbon/agent.py` | Agent conversation loop | Add `step_stream()` + `_run_conversation_loop_stream()` |
| `src/bourbon/repl.py` | REPL interface | Add dynamic prompt `_get_prompt()` + streaming input |
| `tests/test_llm_streaming.py` | LLM streaming tests | New test file |
| `tests/test_agent_streaming.py` | Agent streaming tests | New test file |
| `tests/test_repl_context_display.py` | REPL context display tests | New test file |

---

## Phase 1: LLM Layer - Streaming Support

### Task 1: Add chat_stream() Abstract Method

**Files:**
- Modify: `src/bourbon/llm.py:1-50`

- [ ] **Step 1: Import Generator type**

```python
# Add to imports in src/bourbon/llm.py
from collections.abc import Generator
```

- [ ] **Step 2: Add abstract chat_stream() method to LLMClient**

Add to `src/bourbon/llm.py` after the `chat()` abstract method (around line 38):

```python
@abstractmethod
def chat_stream(
    self,
    messages: list[dict],
    tools: list[dict] | None = None,
    system: str | None = None,
    max_tokens: int = 8000,
) -> Generator[dict, None, None]:
    """Stream chat completion.
    
    Yields events:
    - {"type": "text", "text": "chunk"} - Text token
    - {"type": "tool_use", "id": "...", "name": "...", "input": {...}} - Tool call
    - {"type": "usage", "input_tokens": N, "output_tokens": N} - Final usage
    - {"type": "stop", "stop_reason": "..."} - Stream end
    """
    pass
```

- [ ] **Step 3: Commit**

```bash
git add src/bourbon/llm.py
git commit -m "feat(llm): add chat_stream() abstract method"
```

---

### Task 2: Implement Anthropic Streaming

**Files:**
- Modify: `src/bourbon/llm.py:40-100`
- Test: `tests/test_llm_streaming.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_llm_streaming.py`:

```python
"""Tests for LLM streaming."""

import pytest
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
    
    mock_stream.__iter__ = MagicMock(return_value=iter([mock_event_text]))
    mock_stream.get_final_message = MagicMock(return_value=mock_final_message)
    
    mock_client = MagicMock()
    mock_client.messages.stream.return_value = mock_stream
    
    with patch('bourbon.llm.Anthropic', return_value=mock_client):
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_llm_streaming.py::test_anthropic_chat_stream_yields_text_events -v
```

Expected: FAIL with "NotImplementedError" or method not found

- [ ] **Step 3: Implement Anthropic chat_stream()**

Add to `src/bourbon/llm.py` in `AnthropicLLMClient` class (after `chat()` method):

```python
def chat_stream(
    self,
    messages: list[dict],
    tools: list[dict] | None = None,
    system: str | None = None,
    max_tokens: int = 8000,
) -> Generator[dict, None, None]:
    """Stream chat request to Anthropic."""
    try:
        kwargs = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = tools

        with self.client.messages.stream(**kwargs) as stream:
            current_tool = None
            tool_json = ""

            for event in stream:
                if event.type == "content_block_delta":
                    if event.delta.type == "text_delta":
                        yield {"type": "text", "text": event.delta.text}
                    elif event.delta.type == "input_json_delta":
                        tool_json += event.delta.partial_json
                elif event.type == "content_block_start":
                    if event.content_block.type == "tool_use":
                        current_tool = {
                            "id": event.content_block.id,
                            "name": event.content_block.name,
                        }
                        tool_json = ""
                elif event.type == "content_block_stop":
                    if current_tool is not None:
                        try:
                            current_tool["input"] = json.loads(tool_json)
                        except json.JSONDecodeError:
                            current_tool["input"] = {}
                        yield {
                            "type": "tool_use",
                            "id": current_tool["id"],
                            "name": current_tool["name"],
                            "input": current_tool["input"],
                        }
                        current_tool = None

            final_message = stream.get_final_message()
            yield {
                "type": "usage",
                "input_tokens": final_message.usage.input_tokens,
                "output_tokens": final_message.usage.output_tokens,
            }
            yield {
                "type": "stop",
                "stop_reason": final_message.stop_reason,
            }
    except Exception as e:
        raise LLMError(f"Anthropic API error: {e}") from e
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_llm_streaming.py::test_anthropic_chat_stream_yields_text_events -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_llm_streaming.py src/bourbon/llm.py
git commit -m "feat(llm): implement Anthropic chat_stream()"
```

---

### Task 3: Implement OpenAI Streaming

**Files:**
- Modify: `src/bourbon/llm.py:100-200`
- Test: `tests/test_llm_streaming.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_llm_streaming.py`:

```python
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

    with patch('bourbon.llm.OpenAI', return_value=mock_client):
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_llm_streaming.py::test_openai_chat_stream_yields_text_events -v
```

Expected: FAIL with "NotImplementedError"

- [ ] **Step 3: Implement OpenAI chat_stream()**

Add to `src/bourbon/llm.py` in `OpenAILLMClient` class (after `chat()` method):

```python
def chat_stream(
    self,
    messages: list[dict],
    tools: list[dict] | None = None,
    system: str | None = None,
    max_tokens: int = 8000,
) -> Generator[dict, None, None]:
    """Stream chat request to OpenAI-compatible API."""
    try:
        # Build messages inline (same logic as chat() — no helper exists)
        openai_messages = []
        if system:
            openai_messages.append({"role": "system", "content": system})
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if isinstance(content, list):
                text_parts = []
                for part in content:
                    if part.get("type") == "text":
                        text_parts.append(part.get("text", ""))
                    elif part.get("type") == "tool_result":
                        text_parts.append(str(part.get("content", "")))
                content = "\n".join(text_parts)
            openai_messages.append({"role": role, "content": content})

        kwargs = {
            "model": self.model,
            "messages": openai_messages,
            "max_tokens": max_tokens,
            "stream": True,
            # Required for usage data on the final chunk
            "stream_options": {"include_usage": True},
        }

        if tools:
            # Normalize tools inline (same logic as chat())
            openai_tools = []
            for tool in tools:
                openai_tools.append({
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool["description"],
                        "parameters": tool["input_schema"],
                    },
                })
            kwargs["tools"] = openai_tools
            kwargs["tool_choice"] = "auto"

        stream = self.client.chat.completions.create(**kwargs)
        current_tool_calls: dict[int, dict] = {}
        input_tokens = 0
        output_tokens = 0
        finish_reason = None

        for chunk in stream:
            # Guard: the usage-only final chunk may have empty choices
            if chunk.choices:
                delta = chunk.choices[0].delta
                finish_reason = chunk.choices[0].finish_reason

                if delta.content:
                    yield {"type": "text", "text": delta.content}

                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in current_tool_calls:
                            current_tool_calls[idx] = {
                                "id": tc.id or "",
                                "name": tc.function.name or "",
                                "arguments": "",
                            }
                        if tc.function and tc.function.arguments:
                            current_tool_calls[idx]["arguments"] += tc.function.arguments
                        if tc.id and not current_tool_calls[idx]["id"]:
                            current_tool_calls[idx]["id"] = tc.id

            # Usage appears on the final chunk (with include_usage=True)
            if chunk.usage:
                input_tokens = chunk.usage.prompt_tokens
                output_tokens = chunk.usage.completion_tokens

            if finish_reason:
                # Emit accumulated tool calls
                for idx in sorted(current_tool_calls.keys()):
                    tc = current_tool_calls[idx]
                    try:
                        args = json.loads(tc["arguments"])
                    except json.JSONDecodeError:
                        args = {}
                    yield {
                        "type": "tool_use",
                        "id": tc["id"],
                        "name": tc["name"],
                        "input": args,
                    }

                stop_reason = "tool_use" if finish_reason == "tool_calls" else "end_turn"
                yield {
                    "type": "usage",
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                }
                yield {"type": "stop", "stop_reason": stop_reason}
                # Reset so we don't re-emit on the usage-only trailing chunk
                finish_reason = None
    except Exception as e:
        raise LLMError(f"OpenAI API error: {e}") from e
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_llm_streaming.py::test_openai_chat_stream_yields_text_events -v
```

Expected: PASS

- [ ] **Step 5: Run all LLM streaming tests**

```bash
pytest tests/test_llm_streaming.py -v
```

Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add tests/test_llm_streaming.py src/bourbon/llm.py
git commit -m "feat(llm): implement OpenAI chat_stream()"
```

---

## Phase 2: Agent Layer - Streaming Support

### Task 4: Add get_session_tokens() Helper

**Files:**
- Modify: `src/bourbon/agent.py`
- Test: `tests/test_agent_streaming.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_agent_streaming.py`:

```python
"""Tests for Agent streaming support."""

import pytest
from pathlib import Path


def test_get_session_tokens_returns_estimate():
    """get_session_tokens returns estimated token count."""
    from bourbon.agent import Agent
    from bourbon.config import Config
    
    config = Config()
    agent = object.__new__(Agent)
    agent.messages = [{"role": "user", "content": "Hello world"}]
    
    # Mock compressor
    class MockCompressor:
        def estimate_tokens(self, msgs):
            return 25
    
    agent.compressor = MockCompressor()
    
    tokens = agent.get_session_tokens()
    assert tokens == 25
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_agent_streaming.py::test_get_session_tokens_returns_estimate -v
```

Expected: FAIL with "AttributeError: 'Agent' object has no attribute 'get_session_tokens'"

- [ ] **Step 3: Implement get_session_tokens()**

Add to `src/bourbon/agent.py` in `Agent` class (after `get_token_usage()` method around line 698):

```python
def get_session_tokens(self) -> int:
    """Estimate current session token count."""
    return self.compressor.estimate_tokens(self.messages)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_agent_streaming.py::test_get_session_tokens_returns_estimate -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_agent_streaming.py src/bourbon/agent.py
git commit -m "feat(agent): add get_session_tokens() helper"
```

---

### Task 5: Implement step_stream()

**Files:**
- Modify: `src/bourbon/agent.py:278-410`
- Test: `tests/test_agent_streaming.py`

- [ ] **Step 1: Write failing test for step_stream**

> **Note:** There is no `tests/conftest.py` in this repo. MockLLM classes are defined
> inline in each test file (see `tests/test_agent_error_policy.py` and
> `tests/test_agent_security_integration.py`). The `chat_stream()` method is added
> directly to each test's MockLLM.

- [ ] **Step 2: Write failing test for step_stream**

Add to `tests/test_agent_streaming.py`:

```python
def test_step_stream_calls_callback_for_chunks():
    """step_stream calls on_text_chunk for each text chunk."""
    from bourbon.agent import Agent
    from bourbon.config import Config
    from types import SimpleNamespace
    
    config = Config()
    agent = object.__new__(Agent)
    agent.config = config
    agent.workdir = Path.cwd()
    agent.messages = []
    agent._rounds_without_todo = 0
    agent._max_tool_rounds = 50
    agent.pending_confirmation = None
    
    # Mock LLM
    class MockLLM:
        def chat_stream(self, **kwargs):
            yield {"type": "text", "text": "Hello "}
            yield {"type": "text", "text": "world"}
            yield {"type": "usage", "input_tokens": 10, "output_tokens": 2}
            yield {"type": "stop", "stop_reason": "end_turn"}
    
    agent.llm = MockLLM()
    agent.system_prompt = "You are a test agent"
    
    # Mock compressor
    class MockCompressor:
        def microcompact(self, msgs): pass
        def should_compact(self, msgs): return False
    
    agent.compressor = MockCompressor()
    
    chunks = []
    def on_chunk(text):
        chunks.append(text)
    
    result = agent.step_stream("test", on_chunk)
    
    assert len(chunks) == 2
    assert chunks[0] == "Hello "
    assert chunks[1] == "world"
    assert result == "Hello world"
```

- [ ] **Step 3: Run test to verify it fails**

```bash
pytest tests/test_agent_streaming.py::test_step_stream_calls_callback_for_chunks -v
```

Expected: FAIL with "AttributeError: 'Agent' object has no attribute 'step_stream'"

- [ ] **Step 4: Implement step_stream()**

Add to `src/bourbon/agent.py` after `step()` method (around line 296):

```python
def step_stream(
    self,
    user_input: str,
    on_text_chunk: Callable[[str], None],
) -> str:
    """Process user input with streaming text output.
    
    Args:
        user_input: User's message
        on_text_chunk: Callback invoked for each text chunk (for real-time display).
                      The callback should handle immediate UI updates.
    
    Returns:
        Complete response text (for history and optional markdown re-rendering)
    """
    # Check if we're resuming from a pending confirmation
    if self.pending_confirmation:
        return self._handle_confirmation_response(user_input)

    # Add user message
    self.messages.append({"role": "user", "content": user_input})

    # Pre-process: micro-compact
    self.compressor.microcompact(self.messages)

    # Check if we need full compression
    if self.compressor.should_compact(self.messages):
        self._auto_compact()

    # Run the streaming conversation loop
    return self._run_conversation_loop_stream(on_text_chunk)

def _run_conversation_loop_stream(
    self,
    on_text_chunk: Callable[[str], None],
) -> str:
    """Run conversation loop with streaming output."""
    tool_round = 0
    accumulated_text = ""

    while tool_round < self._max_tool_rounds:
        # Call LLM with streaming
        try:
            event_stream = self.llm.chat_stream(
                messages=self.messages,
                tools=definitions(),
                system=self.system_prompt,
                max_tokens=64000,
            )

            current_text = ""
            has_tool_calls = False
            # Collect ALL tool_use events (model may return multiple per turn)
            tool_use_blocks: list[dict] = []

            for event in event_stream:
                if event["type"] == "text":
                    text_chunk = event["text"]
                    current_text += text_chunk
                    accumulated_text += text_chunk
                    # Protect callback — log and continue on error (per design spec)
                    try:
                        on_text_chunk(text_chunk)
                    except Exception:
                        import logging
                        logging.getLogger(__name__).warning(
                            "on_text_chunk callback error", exc_info=True
                        )

                elif event["type"] == "tool_use":
                    has_tool_calls = True
                    tool_use_blocks.append(event)

                elif event["type"] == "usage":
                    usage = event
                    self.token_usage["input_tokens"] += usage.get("input_tokens", 0)
                    self.token_usage["output_tokens"] += usage.get("output_tokens", 0)
                    self.token_usage["total_tokens"] = (
                        self.token_usage["input_tokens"] + self.token_usage["output_tokens"]
                    )

                elif event["type"] == "stop":
                    stop_reason = event.get("stop_reason", "end_turn")
                    has_tool_calls = stop_reason == "tool_use" or has_tool_calls

            # Build assistant response content
            content = []
            if current_text:
                content.append({"type": "text", "text": current_text})
            for tool_data in tool_use_blocks:
                content.append({
                    "type": "tool_use",
                    "id": tool_data["id"],
                    "name": tool_data["name"],
                    "input": tool_data["input"],
                })

            # Add assistant response to history
            self.messages.append({"role": "assistant", "content": content})

            if not has_tool_calls or not tool_use_blocks:
                # Final response - return accumulated text
                return accumulated_text

            # Execute ALL tool calls (matches sync _run_conversation_loop behavior)
            tool_results = self._execute_tools(tool_use_blocks)

            # Check if we have a pending confirmation
            if self.pending_confirmation:
                return accumulated_text + "\n" + self._format_confirmation_prompt()

            # Add tool results to history
            self.messages.append({"role": "user", "content": tool_results})

        except LLMError as e:
            # Fallback: retry once with non-streaming API (per design spec)
            import logging
            logging.getLogger(__name__).warning(
                f"Streaming API error, falling back to non-streaming: {e}"
            )
            try:
                return self._run_conversation_loop()
            except Exception:
                error_msg = f"LLM Error: {e}"
                self.messages.append({"role": "assistant", "content": error_msg})
                return accumulated_text + error_msg

        tool_round += 1

    return (
        accumulated_text +
        "\n[Reached maximum tool execution rounds. "
        "Providing final response based on what was learned.]"
    )
```

- [ ] **Step 5: Run test to verify it passes**

```bash
pytest tests/test_agent_streaming.py::test_step_stream_calls_callback_for_chunks -v
```

Expected: PASS

- [ ] **Step 6: Run all Agent streaming tests**

```bash
pytest tests/test_agent_streaming.py -v
```

Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add tests/test_agent_streaming.py src/bourbon/agent.py
git commit -m "feat(agent): implement step_stream() with streaming support"
```

---

## Phase 3: REPL Layer - Streaming & Context Display

### Task 6: Add Dynamic Context Prompt

**Files:**
- Modify: `src/bourbon/repl.py:60-80`

- [ ] **Step 1: Import HTML for colored prompts**

```python
# Add to imports in src/bourbon/repl.py
from prompt_toolkit.formatted_text import HTML
```

- [ ] **Step 2: Add _get_prompt() method**

Add to `src/bourbon/repl.py` in `REPL` class:

```python
def _get_prompt(self) -> HTML:
    """Generate dynamic prompt with context usage indicator."""
    # Check if context display is disabled
    if not getattr(self.config.ui, 'show_token_count', True):
        return HTML("🥃 bourbon >> ")
    
    try:
        tokens = self.agent.get_session_tokens()
        threshold = self.agent.compressor.token_threshold
        
        # Calculate percentage
        percent = min(100.0, (tokens / threshold * 100) if threshold > 0 else 0)
        
        # Format numbers
        tokens_k = tokens / 1000
        threshold_k = threshold / 1000
        
        # Color coding
        if percent < 50:
            color = "#888888"  # gray
        elif percent < 80:
            color = "#FFA500"  # orange  
        else:
            color = "#FF4444"  # red
        
        return HTML(
            f'<style fg="{color}">context: {percent:.1f}% ({tokens_k:.1f}k/{threshold_k:.1f}k)</style>\n'
            f'🥃 bourbon >> '
        )
    except Exception:
        # Fallback if anything goes wrong
        return HTML("🥃 bourbon >> ")
```

- [ ] **Step 3: Update PromptSession to use callable**

Modify `src/bourbon/repl.py` line ~68:

```python
# Change from:
# self.session = PromptSession(
#     history=FileHistory(str(history_file)),
#     ...
# )

# To:
self.session = PromptSession(
    message=self._get_prompt,  # Callable for dynamic prompt
    history=FileHistory(str(history_file)),
    auto_suggest=AutoSuggestFromHistory(),
    enable_history_search=True,
)
```

- [ ] **Step 4: Update run() to use dynamic prompt**

The `run()` method currently passes a fixed string `"🥃 bourbon >> "` to `self.session.prompt()`,
which overrides the callable `message` set on PromptSession. Remove the explicit string so the
callable takes effect:

```python
# In run(), change from:
user_input = self.session.prompt(
    "🥃 bourbon >> ",
    style=self.style,
)

# To (omit the message argument — PromptSession uses self._get_prompt):
user_input = self.session.prompt(
    style=self.style,
)
```

- [ ] **Step 5: Test the changes**

```bash
# Run existing REPL tests
pytest tests/ -k repl -v

# Or just verify syntax is correct
python -c "from bourbon.repl import REPL; print('Import OK')"
```

Expected: No import errors

- [ ] **Step 6: Commit**

```bash
git add src/bourbon/repl.py
git commit -m "feat(repl): add dynamic context usage prompt"
```

---

### Task 7: Implement Streaming Input Processing

**Files:**
- Modify: `src/bourbon/repl.py:149-225`

- [ ] **Step 1: Add _process_input_streaming method**

Add to `src/bourbon/repl.py` in `REPL` class after `_process_input()`:

```python
def _process_input_streaming(self, user_input: str) -> None:
    """Process user input with streaming output."""
    chunks: list[str] = []
    
    def on_chunk(text: str) -> None:
        chunks.append(text)
        # Real-time display: print chunk immediately without newline
        self.console.print(text, end="")
    
    try:
        self.console.print()  # New line before streaming starts
        response = self.agent.step_stream(user_input, on_chunk)
    except Exception as e:
        self.console.print(f"[red]Error: {e}[/red]")
        return
    
    # If response contains markdown (code blocks, etc.), re-render with proper formatting
    if "```" in response:
        # Clear the streamed text by moving cursor up
        lines_count = response.count('\n') + 1
        if lines_count > 0:
            # Use ANSI escape to clear lines (simplified approach)
            self.console.print(f"\r\033[{lines_count}A\033[J", end="")
        self.console.print(Markdown(response))
    
    # Handle pending confirmation if needed
    if self.agent.pending_confirmation:
        self._handle_pending_confirmation()
```

- [ ] **Step 2: Switch _process_input to use streaming**

Replace the existing `_process_input()` method in `src/bourbon/repl.py`:

```python
def _process_input(self, user_input: str) -> None:
    """Process user input through agent (now with streaming)."""
    # Use streaming version
    self._process_input_streaming(user_input)
```

- [ ] **Step 3: Remove "Thinking..." message**

The old synchronous code showed "Thinking..." but with streaming the user sees output immediately. Remove or comment out that line (around line 156 in original).

- [ ] **Step 4: Test the changes**

```bash
# Verify syntax
python -c "from bourbon.repl import REPL; print('Import OK')"

# Run existing tests
pytest tests/ -v --tb=short
```

Expected: All existing tests pass (MockLLM already has chat_stream)

- [ ] **Step 5: Commit**

```bash
git add src/bourbon/repl.py
git commit -m "feat(repl): implement streaming input processing"
```

---

### Task 8: Add REPL Context Display Tests

> **Required by design spec** (section "Testing Strategy", item 3: `test_repl_context_display.py`).

**Files:**
- New: `tests/test_repl_context_display.py`

- [ ] **Step 1: Write tests for _get_prompt()**

Create `tests/test_repl_context_display.py`:

```python
"""Tests for REPL dynamic context display prompt."""

import pytest
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
```

- [ ] **Step 2: Run tests (expect failure before Task 6 implementation)**

```bash
pytest tests/test_repl_context_display.py -v
```

Expected: FAIL until `_get_prompt()` is implemented in Task 6

- [ ] **Step 3: After Task 6 is complete, verify all pass**

```bash
pytest tests/test_repl_context_display.py -v
```

Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_repl_context_display.py
git commit -m "test: add REPL context display prompt tests"
```

---

## Phase 4: Integration & Polish

### Task 9: Update MockLLM in All Test Files

**Files:**
- Modify: `tests/test_agent_error_policy.py`
- Modify: `tests/test_agent_security_integration.py`
- Modify: Any other test files with MockLLM

- [ ] **Step 1: Find all MockLLM classes**

```bash
grep -r "class MockLLM" tests/
```

- [ ] **Step 2: Add chat_stream() to each MockLLM**

For each MockLLM found, add:

```python
def chat_stream(self, **kwargs):
    """Mock streaming for tests."""
    yield {"type": "text", "text": "Mock response"}
    yield {"type": "usage", "input_tokens": 10, "output_tokens": 5}
    yield {"type": "stop", "stop_reason": "end_turn"}
```

- [ ] **Step 3: Run all tests**

```bash
pytest tests/ -v --tb=short
```

Expected: All tests pass

- [ ] **Step 4: Commit**

```bash
git add tests/
git commit -m "test: add chat_stream() to all MockLLM classes"
```

---

### Task 10: Add Tool Call Streaming Test

**Files:**
- Test: `tests/test_agent_streaming.py`

- [ ] **Step 1: Write test for tool call in stream**

Add to `tests/test_agent_streaming.py`:

```python
def test_step_stream_handles_tool_calls():
    """step_stream pauses for tool calls and continues."""
    from bourbon.agent import Agent
    from bourbon.config import Config
    from types import SimpleNamespace
    
    config = Config()
    agent = object.__new__(Agent)
    agent.config = config
    agent.workdir = Path.cwd()
    agent.messages = []
    agent._rounds_without_todo = 0
    agent._max_tool_rounds = 50
    agent.pending_confirmation = None
    agent.on_tool_start = None
    agent.on_tool_end = None
    agent.token_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    
    call_count = 0
    
    class MockLLM:
        def chat_stream(self, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First call: tool use
                yield {"type": "tool_use", "id": "tool-1", "name": "bash", "input": {"command": "ls"}}
                yield {"type": "usage", "input_tokens": 10, "output_tokens": 5}
                yield {"type": "stop", "stop_reason": "tool_use"}
            else:
                # Second call: final text
                yield {"type": "text", "text": "Done"}
                yield {"type": "usage", "input_tokens": 10, "output_tokens": 2}
                yield {"type": "stop", "stop_reason": "end_turn"}
    
    agent.llm = MockLLM()
    agent.system_prompt = "You are a test agent"
    
    class MockCompressor:
        def microcompact(self, msgs): pass
        def should_compact(self, msgs): return False
        token_threshold = 100000
    
    agent.compressor = MockCompressor()
    
    # Mock _execute_tools to return simple result
    agent._execute_tools = lambda tools: [{"type": "tool_result", "tool_use_id": "tool-1", "content": "file.txt"}]
    
    chunks = []
    def on_chunk(text):
        chunks.append(text)
    
    result = agent.step_stream("list files", on_chunk)
    
    assert call_count == 2  # Two LLM calls
    assert result == "Done"
    assert chunks == ["Done"]
```

- [ ] **Step 2: Write test for MULTIPLE tool calls in one turn**

This verifies Finding 1 fix — all tool_use events must be collected and executed,
not just the last one:

```python
def test_step_stream_handles_multiple_tool_calls_per_turn():
    """step_stream collects and executes ALL tool calls in a single turn."""
    from bourbon.agent import Agent
    from bourbon.config import Config

    config = Config()
    agent = object.__new__(Agent)
    agent.config = config
    agent.workdir = Path.cwd()
    agent.messages = []
    agent._rounds_without_todo = 0
    agent._max_tool_rounds = 50
    agent.pending_confirmation = None
    agent.on_tool_start = None
    agent.on_tool_end = None
    agent.token_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

    call_count = 0

    class MockLLM:
        def chat_stream(self, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First call: TWO tool calls in one turn
                yield {"type": "tool_use", "id": "tool-1", "name": "bash", "input": {"command": "ls"}}
                yield {"type": "tool_use", "id": "tool-2", "name": "bash", "input": {"command": "pwd"}}
                yield {"type": "usage", "input_tokens": 10, "output_tokens": 5}
                yield {"type": "stop", "stop_reason": "tool_use"}
            else:
                yield {"type": "text", "text": "Done"}
                yield {"type": "usage", "input_tokens": 10, "output_tokens": 2}
                yield {"type": "stop", "stop_reason": "end_turn"}

    agent.llm = MockLLM()
    agent.system_prompt = "You are a test agent"

    class MockCompressor:
        def microcompact(self, msgs): pass
        def should_compact(self, msgs): return False
        token_threshold = 100000

    agent.compressor = MockCompressor()

    # Track which tool blocks were passed to _execute_tools
    executed_tools = []
    def mock_execute(tools):
        executed_tools.extend(tools)
        return [
            {"type": "tool_result", "tool_use_id": t["id"], "content": "ok"}
            for t in tools
        ]
    agent._execute_tools = mock_execute

    result = agent.step_stream("do stuff", lambda t: None)

    # Both tool calls must have been executed
    assert len(executed_tools) == 2
    assert executed_tools[0]["id"] == "tool-1"
    assert executed_tools[1]["id"] == "tool-2"
    assert result == "Done"
```

- [ ] **Step 3: Run tests**

```bash
pytest tests/test_agent_streaming.py::test_step_stream_handles_tool_calls tests/test_agent_streaming.py::test_step_stream_handles_multiple_tool_calls_per_turn -v
```

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_agent_streaming.py
git commit -m "test: add tool call streaming tests (single and multi-tool)"
```

---

### Task 11: Final Verification

- [ ] **Step 1: Run full test suite**

```bash
pytest tests/ -v --tb=short
```

Expected: All tests pass

- [ ] **Step 2: Verify imports work**

```bash
python -c "
from bourbon.llm import LLMClient, AnthropicLLMClient, OpenAILLMClient
from bourbon.agent import Agent
from bourbon.repl import REPL
print('All imports successful')
"
```

Expected: "All imports successful"

- [ ] **Step 3: Check code style**

```bash
ruff check src/bourbon/llm.py src/bourbon/agent.py src/bourbon/repl.py
ruff format --check src/bourbon/llm.py src/bourbon/agent.py src/bourbon/repl.py
```

Expected: Clean (no errors)

- [ ] **Step 4: Final commit**

```bash
git status  # Should be clean
git log --oneline -5  # Review recent commits
```

---

## Summary

This plan implements (11 tasks):

1. **LLM Layer**: `chat_stream()` abstract + Anthropic/OpenAI implementations
2. **Agent Layer**: `step_stream()` + `get_session_tokens()` + `_run_conversation_loop_stream()`
3. **REPL Layer**: Dynamic `_get_prompt()` with context display + streaming input processing
4. **Tests**: New test files (`test_llm_streaming.py`, `test_agent_streaming.py`, `test_repl_context_display.py`) + updated MockLLM classes

All changes maintain backward compatibility - the original `step()` method remains unchanged.

### Key design decisions in this plan

- **Multiple tool calls per turn**: The streaming loop collects ALL `tool_use` events into a list and passes them to `_execute_tools()` as a batch, matching the sync loop behavior.
- **OpenAI `stream_options`**: Passes `{"include_usage": True}` and guards against the trailing usage-only chunk where `choices` is empty.
- **Error handling**: Streaming API errors fall back to non-streaming retry; `on_text_chunk` callback exceptions are logged and swallowed (per design spec).
- **Dynamic prompt**: Both `PromptSession(message=...)` AND the `run()` call site are updated; the latter must omit its explicit string or it overrides the callable.
- **No `tests/conftest.py`**: MockLLM classes are defined inline in each test file; `chat_stream()` is added to each one individually.
- **No `_build_messages()` / `_normalize_tools()` helpers**: OpenAI streaming inlines the same message/tool normalization logic used in `chat()`.
