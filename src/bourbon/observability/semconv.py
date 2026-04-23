"""Centralized OpenTelemetry span names, kinds, and attribute builders for Bourbon."""

from __future__ import annotations

from opentelemetry.trace import SpanKind

AGENT_SPAN_NAME = "invoke_agent bourbon"
AGENT_SPAN_KIND = SpanKind.INTERNAL
LLM_SPAN_KIND = SpanKind.CLIENT
TOOL_SPAN_KIND = SpanKind.INTERNAL

AGENT_WORKDIR_ATTR = "bourbon.agent.workdir"
AGENT_ENTRYPOINT_ATTR = "bourbon.agent.entrypoint"
TOOL_IS_ERROR_ATTR = "bourbon.tool.is_error"
TOOL_SUSPENDED_ATTR = "bourbon.tool.suspended"
TOOL_ERROR_ATTR = "error.type"


def llm_span_name(model: str) -> str:
    return f"chat {model}"


def tool_span_name(name: str) -> str:
    return f"execute_tool {name}"


def agent_span_attributes(workdir: str, entrypoint: str) -> dict[str, object]:
    return {
        "gen_ai.operation.name": "invoke_agent",
        "gen_ai.provider.name": "bourbon",
        "gen_ai.agent.name": "bourbon",
        AGENT_WORKDIR_ATTR: workdir,
        AGENT_ENTRYPOINT_ATTR: entrypoint,
    }


def llm_request_attributes(model: str, max_tokens: int, provider: str) -> dict[str, object]:
    return {
        "gen_ai.operation.name": "chat",
        "gen_ai.provider.name": provider,
        "gen_ai.request.model": model,
        "gen_ai.request.max_tokens": max_tokens,
    }


def llm_response_attributes(
    finish_reason: str,
    input_tokens: int | None,
    output_tokens: int | None,
) -> dict[str, object]:
    attributes: dict[str, object] = {
        "gen_ai.response.finish_reasons": [finish_reason],
    }
    if input_tokens is not None:
        attributes["gen_ai.usage.input_tokens"] = input_tokens
    if output_tokens is not None:
        attributes["gen_ai.usage.output_tokens"] = output_tokens
    return attributes


def tool_span_attributes(name: str, call_id: str, concurrent: bool) -> dict[str, object]:
    return {
        "gen_ai.operation.name": "execute_tool",
        "gen_ai.tool.name": name,
        "gen_ai.tool.call.id": call_id,
        "bourbon.tool.concurrent": concurrent,
    }
