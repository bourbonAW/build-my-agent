"""LLM client for multiple providers (Anthropic, OpenAI, and OpenAI-compatible)."""

import json
import os
import re
from abc import ABC, abstractmethod
from typing import Any

import httpx

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


def parse_kimi_tool_calls(content: str) -> list[dict]:
    """Parse Kimi's XML-style tool call format.

    Kimi returns tool calls like:
    <|tool_calls_section_begin|>
    <|tool_call_begin|> functions.View:0
    <|tool_call_argument_begin|> {"path": "/path"}
    <|tool_call_end|>
    <|tool_calls_section_end|>

    Returns list of tool call dicts.
    """
    tool_calls = []

    # Pattern to match tool call blocks
    pattern = r'<\|tool_call_begin\|>\s*(\w+):(\d+)\s*<\|tool_call_argument_begin\|>\s*(\{[^}]*\})\s*<\|tool_call_end\|>'

    matches = re.findall(pattern, content, re.DOTALL)
    for func_name, call_id, args_str in matches:
        try:
            args = json.loads(args_str)
        except json.JSONDecodeError:
            args = {}

        tool_calls.append({
            "id": f"call_{call_id}",
            "type": "tool_use",
            "name": func_name,
            "input": args,
        })

    return tool_calls


class GenericOpenAIClient(LLMClient):
    """Generic OpenAI-compatible API client (works with Kimi, OpenAI, etc.)."""

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        is_kimi: bool = False,
    ):
        """Initialize generic OpenAI-compatible client.

        Args:
            api_key: API key
            model: Model identifier
            base_url: API base URL
            is_kimi: Whether this is a Kimi API (special handling)
        """
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.is_kimi = is_kimi
        self.client = httpx.Client(timeout=120.0)

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        system: str | None = None,
        max_tokens: int = 8000,
    ) -> dict:
        """Send chat request to OpenAI-compatible API."""
        # Build messages
        request_messages = []
        if system:
            request_messages.append({"role": "system", "content": system})

        # Convert our message format to OpenAI format
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if isinstance(content, list):
                # Handle tool results
                text_parts = []
                for part in content:
                    if part.get("type") == "text":
                        text_parts.append(part.get("text", ""))
                    elif part.get("type") == "tool_result":
                        text_parts.append(f"[Tool result: {part.get('content', '')}]")
                    elif part.get("type") == "tool_use":
                        # Skip tool_use blocks in history - they should be handled differently
                        pass
                content = "\n".join(text_parts) if text_parts else ""

            request_messages.append({"role": role, "content": content})

        # Build request
        request_body = {
            "model": self.model,
            "messages": request_messages,
            "max_tokens": max_tokens,
        }

        # Add tools if provided
        if tools:
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
            request_body["tools"] = openai_tools
            request_body["tool_choice"] = "auto"

        # Send request
        try:
            response = self.client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=request_body,
            )
            response.raise_for_status()
            data = response.json()

            # Parse response
            choice = data["choices"][0]
            message = choice["message"]
            response_content = message.get("content", "") or ""

            # Build content blocks
            content = []

            # Check for tool calls in standard format
            if message.get("tool_calls"):
                for tool_call in message["tool_calls"]:
                    try:
                        args = json.loads(tool_call["function"]["arguments"])
                    except (json.JSONDecodeError, KeyError):
                        args = {}

                    content.append({
                        "type": "tool_use",
                        "id": tool_call["id"],
                        "name": tool_call["function"]["name"],
                        "input": args,
                    })

                stop_reason = "tool_use"

            # Check for Kimi's special XML format
            elif self.is_kimi and "<|tool_calls_section_begin|>" in response_content:
                tool_calls = parse_kimi_tool_calls(response_content)
                if tool_calls:
                    content.extend(tool_calls)
                    stop_reason = "tool_use"
                else:
                    # Failed to parse, treat as text
                    content.append({"type": "text", "text": response_content})
                    stop_reason = "end_turn"

            else:
                # Regular text response
                if response_content:
                    content.append({"type": "text", "text": response_content})
                stop_reason = "end_turn"

            return {
                "content": content,
                "stop_reason": stop_reason,
                "usage": data.get("usage", {}),
            }

        except httpx.HTTPError as e:
            raise LLMError(f"HTTP error: {e}") from e
        except Exception as e:
            raise LLMError(f"API error: {e}") from e


class AnthropicClient(LLMClient):
    """Anthropic Claude client using HTTP API."""

    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-4-6",
        base_url: str = "https://api.anthropic.com",
    ):
        """Initialize Anthropic client.

        Args:
            api_key: Anthropic API key
            model: Model identifier
            base_url: API base URL
        """
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(timeout=120.0)

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        system: str | None = None,
        max_tokens: int = 8000,
    ) -> dict:
        """Send chat request to Anthropic API."""
        # Build request body
        request_body = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
        }

        if system:
            request_body["system"] = system

        if tools:
            request_body["tools"] = tools

        # Send request
        try:
            response = self.client.post(
                f"{self.base_url}/v1/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json=request_body,
            )
            response.raise_for_status()
            data = response.json()

            # Normalize response format
            content = []
            for block in data.get("content", []):
                if block["type"] == "text":
                    content.append({"type": "text", "text": block["text"]})
                elif block["type"] == "tool_use":
                    content.append({
                        "type": "tool_use",
                        "id": block["id"],
                        "name": block["name"],
                        "input": block["input"],
                    })

            return {
                "content": content,
                "stop_reason": data.get("stop_reason", "end_turn"),
                "usage": data.get("usage", {}),
            }

        except httpx.HTTPError as e:
            raise LLMError(f"HTTP error: {e}") from e
        except Exception as e:
            raise LLMError(f"API error: {e}") from e


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
            base_url=config.llm.anthropic.base_url,
        )
    elif provider == "openai":
        api_key = config.llm.openai.api_key
        if not api_key:
            raise LLMError("OpenAI API key not configured")
        return GenericOpenAIClient(
            api_key=api_key,
            model=config.llm.openai.model,
            base_url=config.llm.openai.base_url,
            is_kimi=False,
        )
    elif provider == "kimi":
        # Kimi uses OpenAI-compatible API
        api_key = config.llm.openai.api_key
        if not api_key:
            raise LLMError("Kimi API key not configured")
        return GenericOpenAIClient(
            api_key=api_key,
            model=config.llm.openai.model,
            base_url=config.llm.openai.base_url,
            is_kimi=True,
        )
    else:
        raise LLMError(f"Unknown provider: {provider}")
