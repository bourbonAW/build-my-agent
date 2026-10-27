import type { Span, Tracer } from "@opentelemetry/api";
import { SpanStatusCode } from "@opentelemetry/api";
import {
  AGENT_SPAN_KIND,
  AGENT_SPAN_NAME,
  LLM_SPAN_KIND,
  TOOL_ERROR_ATTR,
  TOOL_IS_ERROR_ATTR,
  TOOL_SPAN_KIND,
  TOOL_SUSPENDED_ATTR,
  agentSpanAttributes,
  llmRequestAttributes,
  llmResponseAttributes,
  llmSpanName,
  toolSpanAttributes,
  toolSpanName,
} from "./semconv";

export const MAX_IO_ATTR_CHARS = 4000;

export class BourbonTracer {
  constructor(private readonly tracer: Tracer | null = null) {}

  get enabled(): boolean {
    return this.tracer !== null;
  }

  startAgentStep(
    workdir: string,
    entrypoint = "step",
    evalCaseId?: string | null,
    evalRunId?: string | null,
    userInput?: string,
  ): Span | null {
    if (!this.tracer) return null;
    const span = this.tracer.startSpan(AGENT_SPAN_NAME, { kind: AGENT_SPAN_KIND });
    span.setAttributes(agentSpanAttributes(workdir, entrypoint, evalCaseId, evalRunId));
    if (userInput !== undefined) span.setAttribute("input", userInput.slice(0, MAX_IO_ATTR_CHARS));
    return span;
  }

  startLlmCall(model: string, maxTokens: number, provider: string): Span | null {
    if (!this.tracer) return null;
    const span = this.tracer.startSpan(llmSpanName(model), { kind: LLM_SPAN_KIND });
    span.setAttributes(llmRequestAttributes(model, maxTokens, provider));
    return span;
  }

  startToolCall(name: string, callId: string, concurrent: boolean): Span | null {
    if (!this.tracer) return null;
    const span = this.tracer.startSpan(toolSpanName(name), { kind: TOOL_SPAN_KIND });
    span.setAttributes(toolSpanAttributes(name, callId, concurrent));
    return span;
  }

  recordAgentOutput(span: Span | null, output: string): void {
    span?.setAttribute("output", output.slice(0, MAX_IO_ATTR_CHARS));
  }

  recordToolIo(span: Span | null, toolInput: unknown, output: string): void {
    if (!span) return;
    let input: string;
    try {
      input = JSON.stringify(toolInput);
    } catch {
      input = String(toolInput);
    }
    span.setAttribute("input", input.slice(0, MAX_IO_ATTR_CHARS));
    span.setAttribute("output", output.slice(0, MAX_IO_ATTR_CHARS));
  }

  recordLlmResponse(
    span: Span | null,
    finishReason: string,
    inputTokens: number | null,
    outputTokens: number | null,
  ): void {
    span?.setAttributes(llmResponseAttributes(finishReason, inputTokens, outputTokens));
  }

  markToolResult(
    span: Span | null,
    isError: boolean,
    errorType = "tool_error",
    message = "",
  ): void {
    if (!span) return;
    span.setAttribute(TOOL_IS_ERROR_ATTR, isError);
    if (isError) {
      span.setAttribute(TOOL_ERROR_ATTR, errorType);
      span.setStatus({ code: SpanStatusCode.ERROR, message });
    }
  }

  markToolSuspended(span: Span | null): void {
    span?.setAttribute(TOOL_SUSPENDED_ATTR, true);
  }

  recordError(span: Span | null, error: unknown): void {
    if (!span) return;
    if (error instanceof Error) {
      span.recordException(error);
      span.setStatus({ code: SpanStatusCode.ERROR, message: error.message });
      span.setAttribute(TOOL_ERROR_ATTR, error.name);
    } else {
      span.setStatus({ code: SpanStatusCode.ERROR, message: String(error) });
    }
  }

  end(span: Span | null): void {
    span?.end();
  }
}
