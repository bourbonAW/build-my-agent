# REPL Streaming Output & Context Display Design

**Date:** 2026-03-30  
**Author:** Bourbon Agent  
**Status:** Approved for Implementation

---

## Summary

优化 Bourbon REPL 的 UI/UX 设计，解决两个核心问题：
1. **同步输出滞后感** - LLM 应用应利用流式输出特性，让用户立即看到响应
2. **Context 用量不可见** - 用户不知道当前 session 消耗了多少 context，以及何时会触发压缩

## Goals

- 实现真正的 LLM API 流式输出（非本地模拟）
- 在 prompt 中实时显示 context 用量百分比
- 保持向后兼容，现有同步 API 不受影响
- 改动最小化，不引入过度设计

## Non-Goals

- 不支持 tool call 过程的流式显示（只流式文本回复）
- 不替换现有 `step()` 同步 API
- 不添加复杂的 UI 框架或浏览器组件

---

## Architecture

```
┌─────────────┐     ┌─────────────────┐     ┌──────────────────┐
│   REPL      │────▶│  Agent          │────▶│  LLM Client      │
│             │     │                 │     │                  │
│ _get_prompt │     │ step_stream()   │     │ chat_stream()    │
│   (dynamic) │     │   └─ Generator  │     │   └─ Generator   │
│             │◀────│ on_text_chunk   │◀────│ text/tool/stop   │
│   Markdown  │     │                 │     │                  │
└─────────────┘     └─────────────────┘     └──────────────────┘
```

---

## Design Details

### 1. LLM Layer (`llm.py`)

#### New Abstract Method
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
```

#### Anthropic Implementation
- Use existing `messages.stream()` context manager
- Parse `content_block_delta` events for text chunks
- Accumulate `input_json_delta` for tool calls
- Yield events as they arrive

#### OpenAI Implementation
- Use `stream=True` parameter
- Parse SSE chunks from `chat.completions.create()`
- Accumulate `delta.tool_calls` across chunks
- Yield events on content/tool completion

### 2. Agent Layer (`agent.py`)

#### New Public Method
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
```

#### Internal Flow (`_run_conversation_loop_stream`)
1. Call `llm.chat_stream()` to get event generator
2. For each event:
   - `text`: Accumulate + call `on_text_chunk`
   - `tool_use`: Pause stream, execute tool, continue
   - `usage`: Update token usage stats
   - `stop`: Break loop, return accumulated text
3. Handle pending confirmation (high-risk errors)
4. Return complete text for history storage

#### Context Token Helper
```python
def get_session_tokens(self) -> int:
    """Estimate current session token count."""
    return self.compressor.estimate_tokens(self.messages)
```

### 3. REPL Layer (`repl.py`)

#### Dynamic Prompt
```python
def _get_prompt(self) -> HTML:
    """Generate dynamic prompt with context usage."""
    tokens = self.agent.get_session_tokens()
    threshold = self.agent.compressor.token_threshold
    percent = min(100.0, tokens / threshold * 100)
    
    # Color coding
    if percent < 50:
        color = "#888888"  # gray
    elif percent < 80:
        color = "#FFA500"  # orange
    else:
        color = "#FF4444"  # red
    
    return HTML(
        f'<style fg="{color}">context: {percent:.1f}% ({tokens/1000:.1f}k/{threshold/1000:.1f}k)</style>\n'
        f'🥃 bourbon >> '
    )
```

Update `PromptSession` initialization:
```python
self.session = PromptSession(
    message=self._get_prompt,  # Callable instead of static string
    ...
)
```

#### Streaming Input Processing
```python
def _process_input_streaming(self, user_input: str) -> None:
    """Process input with streaming output."""
    chunks: list[str] = []
    
    def on_chunk(text: str) -> None:
        chunks.append(text)
        # Real-time display: print chunk immediately without newline
        self.console.print(text, end="", flush=True)
    
    try:
        self.console.print()  # New line before streaming starts
        response = self.agent.step_stream(user_input, on_chunk)
    except Exception as e:
        self.console.print(f"[red]Error: {e}[/red]")
        return
    
    # If response contains markdown (code blocks, etc.), re-render with proper formatting
    if "```" in response:
        # Clear the streamed text (move up and overwrite)
        lines_count = response.count('\n') + 1
        self.console.print(f"\r\033[{lines_count}A", end="")
        self.console.print(Markdown(response))
    
    # Handle pending confirmation if needed
    if self.agent.pending_confirmation:
        self._handle_pending_confirmation()
```

### 4. Configuration

No new config options. Use existing:
- `UIConfig.token_threshold` - Context threshold for percentage calc
- `UIConfig.show_token_count` - If False, hide context display from prompt

---

## Error Handling

| Scenario | Strategy |
|----------|----------|
| Stream interrupted | Return accumulated text, log warning |
| API error during stream | Raise LLMError, fall back to non-streaming retry |
| Token estimation fails | Display "context: --" instead of crashing |
| Callback throws exception | Log error, continue streaming |

---

## Testing Strategy

### Unit Tests

1. **LLM Streaming** (`test_llm_streaming.py`):
   - Mock Anthropic stream events parsed correctly
   - Mock OpenAI SSE chunks parsed correctly
   - Tool call accumulation works

2. **Agent Streaming** (`test_agent_streaming.py`):
   - `step_stream()` calls callback for each chunk
   - Tool calls pause and resume correctly
   - Token usage updated
   - Pending confirmation still works

3. **REPL Context Display** (`test_repl_context_display.py`):
   - `_get_prompt()` formats correctly at different percentages
   - Color changes at thresholds
   - Respects `show_token_count` config

### Mock Updates

Update existing test mocks:
```python
class MockLLM:
    def chat_stream(self, **kwargs):
        yield {"type": "text", "text": "Hello "}
        yield {"type": "text", "text": "world"}
        yield {"type": "usage", "input_tokens": 10, "output_tokens": 2}
        yield {"type": "stop", "stop_reason": "end_turn"}
```

---

## Implementation Phases

### Phase 1: LLM Layer
- Add `chat_stream()` abstract method
- Implement for Anthropic
- Implement for OpenAI

### Phase 2: Agent Layer
- Add `step_stream()` method
- Implement `_run_conversation_loop_stream()`
- Add `get_session_tokens()` helper

### Phase 3: REPL Layer
- Convert prompt to callable `_get_prompt()`
- Update `_process_input()` to use streaming
- Test context display formatting

### Phase 4: Tests & Polish
- Update MockLLM
- Add streaming-specific tests
- Verify backward compatibility

---

## Risks & Mitigation

| Risk | Impact | Mitigation |
|------|--------|------------|
| Breaking existing tests | Medium | Keep `step()` unchanged, only add new methods |
| Markdown rendering delay | Low | Accept trade-off for consistent formatting |
| Token estimation inaccurate | Low | Use for UI only, not billing/logic |
| OpenAI streaming quirks | Low | Test with real API, handle missing usage fields |

---

## Success Criteria

- [ ] User sees first token within 500ms of API call (vs. waiting for full response)
- [ ] Prompt shows context percentage that updates each turn
- [ ] All existing tests pass without modification
- [ ] New streaming tests pass
- [ ] No regression in tool execution or confirmation flows

---

## Appendix: Event Format Reference

### Anthropic Events
```python
# Text delta
{"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hello"}}

# Tool call start
{"type": "content_block_start", "content_block": {"type": "tool_use", "id": "...", "name": "..."}}

# Tool input delta
{"type": "content_block_delta", "delta": {"type": "input_json_delta", "partial_json": '{"key": "val"}'}}
```

### OpenAI Events
```python
# Content delta
{"choices": [{"delta": {"content": "Hello"}}]}

# Tool call delta
{"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": '{"key": "val"}'}}]}}]}
```
