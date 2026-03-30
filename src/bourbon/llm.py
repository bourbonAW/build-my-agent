"""LLM client for multiple providers (Anthropic, OpenAI, and compatible APIs)."""

import json
from abc import ABC, abstractmethod
from collections.abc import Generator

from bourbon.config import Config

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


class AnthropicLLMClient(LLMClient):
    """Anthropic Claude client using official SDK with streaming."""

    def __init__(self, api_key: str, model: str, base_url: str | None = None):
        if Anthropic is None:
            raise LLMError("anthropic package not installed. Run: uv pip install anthropic")

        self.client = Anthropic(api_key=api_key, base_url=base_url)
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


class OpenAILLMClient(LLMClient):
    """OpenAI-compatible client (works with OpenAI, Kimi, and others)."""

    def __init__(self, api_key: str, model: str, base_url: str | None = None):
        if OpenAI is None:
            raise LLMError("openai package not installed. Run: uv pip install openai")

        self.client = OpenAI(api_key=api_key, base_url=base_url)
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
