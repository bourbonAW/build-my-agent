"""LLM client for multiple providers (Anthropic, OpenAI)."""

import os
from abc import ABC, abstractmethod
from typing import Any

from bourbon.config import Config


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
        """Send chat completion request.

        Args:
            messages: Conversation history
            tools: Available tools
            system: System prompt
            max_tokens: Maximum tokens to generate

        Returns:
            Response dict with content and stop_reason
        """
        pass


class AnthropicClient(LLMClient):
    """Anthropic Claude client."""

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6", base_url: str | None = None):
        """Initialize Anthropic client.

        Args:
            api_key: Anthropic API key
            model: Model identifier
            base_url: Optional API base URL override
        """
        try:
            from anthropic import Anthropic
        except ImportError as e:
            raise ImportError("anthropic package not installed") from e

        self.client = Anthropic(api_key=api_key, base_url=base_url)
        self.model = model

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        system: str | None = None,
        max_tokens: int = 8000,
    ) -> dict:
        """Send chat request to Anthropic."""
        try:
            response = self.client.messages.create(
                model=self.model,
                messages=messages,
                tools=tools,
                system=system,
                max_tokens=max_tokens,
            )

            return {
                "content": response.content,
                "stop_reason": response.stop_reason,
                "usage": {
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                },
            }
        except Exception as e:
            raise LLMError(f"Anthropic API error: {e}") from e


class OpenAIClient(LLMClient):
    """OpenAI client."""

    def __init__(self, api_key: str, model: str = "gpt-4o", base_url: str | None = None):
        """Initialize OpenAI client.

        Args:
            api_key: OpenAI API key
            model: Model identifier
            base_url: Optional API base URL override
        """
        try:
            from openai import OpenAI
        except ImportError as e:
            raise ImportError("openai package not installed") from e

        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        system: str | None = None,
        max_tokens: int = 8000,
    ) -> dict:
        """Send chat request to OpenAI."""
        try:
            # OpenAI uses messages array for system prompt too
            openai_messages = []
            if system:
                openai_messages.append({"role": "system", "content": system})
            openai_messages.extend(messages)

            # Convert tools to OpenAI format
            openai_tools = None
            if tools:
                openai_tools = [
                    {"type": "function", "function": self._convert_tool(tool)}
                    for tool in tools
                ]

            if openai_tools:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=openai_messages,
                    tools=openai_tools,
                    max_tokens=max_tokens,
                )
            else:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=openai_messages,
                    max_tokens=max_tokens,
                )

            message = response.choices[0].message

            # Normalize response format to match Anthropic
            content = []
            if message.content:
                content.append({"type": "text", "text": message.content})

            if message.tool_calls:
                for tool_call in message.tool_calls:
                    content.append({
                        "type": "tool_use",
                        "id": tool_call.id,
                        "name": tool_call.function.name,
                        "input": tool_call.function.arguments,
                    })

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

    def _convert_tool(self, tool: dict) -> dict:
        """Convert tool definition to OpenAI format."""
        return {
            "name": tool["name"],
            "description": tool["description"],
            "parameters": tool["input_schema"],
        }


def create_client(config: Config) -> LLMClient:
    """Create LLM client from configuration.

    Args:
        config: Bourbon configuration

    Returns:
        Configured LLM client

    Raises:
        LLMError: If provider is invalid or API key is missing
    """
    provider = config.llm.default_provider

    if provider == "anthropic":
        api_key = config.llm.anthropic.api_key
        if not api_key:
            raise LLMError("Anthropic API key not configured")
        return AnthropicClient(
            api_key=api_key,
            model=config.llm.anthropic.model,
            base_url=config.llm.anthropic.base_url or None,
        )
    elif provider == "openai":
        api_key = config.llm.openai.api_key
        if not api_key:
            raise LLMError("OpenAI API key not configured")
        return OpenAIClient(
            api_key=api_key,
            model=config.llm.openai.model,
            base_url=config.llm.openai.base_url or None,
        )
    else:
        raise LLMError(f"Unknown provider: {provider}")
