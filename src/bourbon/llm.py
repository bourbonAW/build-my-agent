"""LLM client for multiple providers (Anthropic, OpenAI, and compatible APIs)."""

import json
import time
from abc import ABC, abstractmethod
from collections.abc import Generator

import httpx

from bourbon.config import Config
from bourbon.debug import debug_log, prompt_fields

# Optional imports - fail gracefully if not installed
try:
    from anthropic import Anthropic
except ImportError:
    Anthropic = None

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None


class LLMError(Exception):
    """LLM API error."""

    pass


class LLMClient(ABC):
    """Abstract base class for LLM clients."""

    @abstractmethod
    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        system: str | None = None,
        max_tokens: int = 8000,
    ) -> dict:
        """Send chat completion request."""
        pass

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


def _make_http_client_for_compat_api() -> httpx.Client:
    """Return an httpx Client that strips x-stainless-* headers.

    Third-party Anthropic-compatible endpoints (e.g. Kimi Code) rate-limit requests
    that carry the Anthropic SDK's internal telemetry headers. Using event hooks
    removes those headers while keeping system proxy settings intact.
    """
    def _strip_stainless(request: httpx.Request) -> None:
        for key in [k for k in request.headers if k.lower().startswith("x-stainless-")]:
            del request.headers[key]
        request.headers["user-agent"] = "python-httpx/0.28.1"

    client = httpx.Client()
    client.event_hooks["request"] = [_strip_stainless]
    return client


class AnthropicLLMClient(LLMClient):
    """Anthropic Claude client using official SDK with streaming."""

    def __init__(self, api_key: str, model: str, base_url: str | None = None):
        if Anthropic is None:
            raise LLMError("anthropic package not installed. Run: uv pip install anthropic")

        http_client = _make_http_client_for_compat_api() if base_url else None
        self.client = Anthropic(api_key=api_key, base_url=base_url, max_retries=0, timeout=60.0, http_client=http_client)
        self.model = model

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        system: str | None = None,
        max_tokens: int = 8000,
    ) -> dict:
        """Send chat request to Anthropic using streaming mode."""
        try:
            debug_log(
                "llm.anthropic.request",
                model=self.model,
                base_url=str(getattr(self.client, "base_url", "")),
                message_count=len(messages),
                tool_count=len(tools or []),
                max_tokens=max_tokens,
                **prompt_fields(messages, system, tools),
            )
            kwargs = {
                "model": self.model,
                "messages": messages,
                "max_tokens": max_tokens,
            }
            if system:
                kwargs["system"] = system
            if tools:
                kwargs["tools"] = tools

            # Use streaming mode (required by SDK for long operations)
            with self.client.messages.stream(**kwargs) as stream:
                # Collect the final message
                final_message = stream.get_final_message()

                # Normalize to our format
                content = []
                for block in final_message.content:
                    if block.type == "text":
                        content.append({"type": "text", "text": block.text})
                    elif block.type == "tool_use":
                        content.append(
                            {
                                "type": "tool_use",
                                "id": block.id,
                                "name": block.name,
                                "input": block.input,
                            }
                        )

                return {
                    "content": content,
                    "stop_reason": final_message.stop_reason,
                    "usage": {
                        "input_tokens": final_message.usage.input_tokens,
                        "output_tokens": final_message.usage.output_tokens,
                    },
                }
        except Exception as e:
            raise LLMError(f"Anthropic API error: {e}") from e

    def chat_stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        system: str | None = None,
        max_tokens: int = 8000,
    ) -> Generator[dict, None, None]:
        """Stream chat request to Anthropic."""
        started_at = time.monotonic()
        try:
            debug_log(
                "llm.anthropic.stream.start",
                model=self.model,
                base_url=str(getattr(self.client, "base_url", "")),
                message_count=len(messages),
                tool_count=len(tools or []),
                max_tokens=max_tokens,
                **prompt_fields(messages, system, tools),
            )
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
                debug_log(
                    "llm.anthropic.stream.open",
                    elapsed_ms=int((time.monotonic() - started_at) * 1000),
                )
                current_tool = None
                tool_json = ""
                saw_raw_event = False

                for event in stream:
                    debug_log(
                        "llm.anthropic.stream.raw_event",
                        raw_type=event.type,
                        first_event=not saw_raw_event,
                        elapsed_ms=int((time.monotonic() - started_at) * 1000),
                    )
                    saw_raw_event = True
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
                    elif event.type == "content_block_stop" and current_tool is not None:
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

                debug_log(
                    "llm.anthropic.stream.before_final_message",
                    elapsed_ms=int((time.monotonic() - started_at) * 1000),
                )
                final_message = stream.get_final_message()
                debug_log(
                    "llm.anthropic.stream.complete",
                    stop_reason=final_message.stop_reason,
                    elapsed_ms=int((time.monotonic() - started_at) * 1000),
                )
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
            debug_log(
                "llm.anthropic.stream.error",
                error=str(e),
                elapsed_ms=int((time.monotonic() - started_at) * 1000),
            )
            raise LLMError(f"Anthropic API error: {e}") from e


class OpenAILLMClient(LLMClient):
    """OpenAI-compatible client (works with OpenAI, Kimi, and others)."""

    def __init__(self, api_key: str, model: str, base_url: str | None = None):
        if OpenAI is None:
            raise LLMError("openai package not installed. Run: uv pip install openai")

        self.client = OpenAI(api_key=api_key, base_url=base_url, max_retries=0, timeout=60.0)
        self.model = model

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        system: str | None = None,
        max_tokens: int = 8000,
    ) -> dict:
        """Send chat request to OpenAI-compatible API."""
        try:
            debug_log(
                "llm.openai.request",
                model=self.model,
                base_url=str(getattr(self.client, "base_url", "")),
                message_count=len(messages),
                tool_count=len(tools or []),
                max_tokens=max_tokens,
                **prompt_fields(messages, system, tools),
            )
            # Build messages (OpenAI uses system message in messages array)
            openai_messages = []
            if system:
                openai_messages.append({"role": "system", "content": system})

            # Convert messages to OpenAI format
            for msg in messages:
                role = msg.get("role", "user")
                content = msg.get("content", "")

                # Handle list content (tool results)
                if isinstance(content, list):
                    text_parts = []
                    for part in content:
                        if part.get("type") == "text":
                            text_parts.append(part.get("text", ""))
                        elif part.get("type") == "tool_result":
                            text_parts.append(str(part.get("content", "")))
                    content = "\n".join(text_parts)

                openai_messages.append({"role": role, "content": content})

            # Build request
            kwargs = {
                "model": self.model,
                "messages": openai_messages,
                "max_tokens": max_tokens,
            }

            if tools:
                # Convert tools to OpenAI format
                openai_tools = []
                for tool in tools:
                    openai_tools.append(
                        {
                            "type": "function",
                            "function": {
                                "name": tool["name"],
                                "description": tool["description"],
                                "parameters": tool["input_schema"],
                            },
                        }
                    )
                kwargs["tools"] = openai_tools

            response = self.client.chat.completions.create(**kwargs)

            # Normalize to our format
            message = response.choices[0].message
            content = []

            if message.content:
                content.append({"type": "text", "text": message.content})

            if message.tool_calls:
                for tc in message.tool_calls:
                    try:
                        args = json.loads(tc.function.arguments)
                    except json.JSONDecodeError:
                        args = {}
                    content.append(
                        {
                            "type": "tool_use",
                            "id": tc.id,
                            "name": tc.function.name,
                            "input": args,
                        }
                    )

            return {
                "content": content,
                "stop_reason": "tool_use" if message.tool_calls else "end_turn",
                "usage": {
                    "input_tokens": response.usage.prompt_tokens,
                    "output_tokens": response.usage.completion_tokens,
                },
            }
        except Exception as e:
            raise LLMError(f"OpenAI API error: {e}") from e

    def chat_stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        system: str | None = None,
        max_tokens: int = 8000,
    ) -> Generator[dict, None, None]:
        """Stream chat request to OpenAI-compatible API."""
        started_at = time.monotonic()
        try:
            debug_log(
                "llm.openai.stream.start",
                model=self.model,
                base_url=str(getattr(self.client, "base_url", "")),
                message_count=len(messages),
                tool_count=len(tools or []),
                max_tokens=max_tokens,
                **prompt_fields(messages, system, tools),
            )
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
                    openai_tools.append(
                        {
                            "type": "function",
                            "function": {
                                "name": tool["name"],
                                "description": tool["description"],
                                "parameters": tool["input_schema"],
                            },
                        }
                    )
                kwargs["tools"] = openai_tools
                kwargs["tool_choice"] = "auto"

            stream = self.client.chat.completions.create(**kwargs)
            debug_log(
                "llm.openai.stream.open",
                elapsed_ms=int((time.monotonic() - started_at) * 1000),
            )
            current_tool_calls: dict[int, dict] = {}
            input_tokens = 0
            output_tokens = 0
            finish_reason = None
            saw_chunk = False

            for chunk in stream:
                debug_log(
                    "llm.openai.stream.chunk",
                    first_chunk=not saw_chunk,
                    has_choices=bool(chunk.choices),
                    has_usage=bool(chunk.usage),
                    elapsed_ms=int((time.monotonic() - started_at) * 1000),
                )
                saw_chunk = True
                # Guard: the usage-only final chunk may have empty choices
                if chunk.choices:
                    delta = chunk.choices[0].delta
                    if chunk.choices[0].finish_reason:
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

            # After consuming the full stream, emit tool calls, usage, and stop
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
            debug_log(
                "llm.openai.stream.complete",
                stop_reason=stop_reason,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                elapsed_ms=int((time.monotonic() - started_at) * 1000),
            )
            yield {
                "type": "usage",
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            }
            yield {"type": "stop", "stop_reason": stop_reason}
        except Exception as e:
            debug_log(
                "llm.openai.stream.error",
                error=str(e),
                elapsed_ms=int((time.monotonic() - started_at) * 1000),
            )
            raise LLMError(f"OpenAI API error: {e}") from e


def create_client(config: Config) -> LLMClient:
    """Create LLM client from configuration."""
    provider = config.llm.default_provider

    if provider == "anthropic":
        api_key = config.llm.anthropic.api_key
        if not api_key:
            raise LLMError("Anthropic API key not configured")
        return AnthropicLLMClient(
            api_key=api_key,
            model=config.llm.anthropic.model,
            base_url=config.llm.anthropic.base_url or None,
        )

    elif provider in ("openai", "kimi"):
        # Kimi uses OpenAI-compatible API
        api_key = config.llm.openai.api_key
        if not api_key:
            raise LLMError(f"{provider} API key not configured")
        return OpenAILLMClient(
            api_key=api_key,
            model=config.llm.openai.model,
            base_url=config.llm.openai.base_url or None,
        )

    else:
        raise LLMError(f"Unknown provider: {provider}")
