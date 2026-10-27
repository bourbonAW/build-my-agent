import { SpanKind } from "@opentelemetry/api";

export const AGENT_SPAN_NAME = "invoke_agent bourbon";
export const AGENT_SPAN_KIND = SpanKind.INTERNAL;
export const LLM_SPAN_KIND = SpanKind.CLIENT;
export const TOOL_SPAN_KIND = SpanKind.INTERNAL;

export const AGENT_WORKDIR_ATTR = "bourbon.agent.workdir";
export const AGENT_ENTRYPOINT_ATTR = "bourbon.agent.entrypoint";
export const EVAL_CASE_ID_ATTR = "eval.case_id";
export const EVAL_RUN_ID_ATTR = "eval.run_id";
export const TOOL_IS_ERROR_ATTR = "bourbon.tool.is_error";
export const TOOL_SUSPENDED_ATTR = "bourbon.tool.suspended";
export const TOOL_ERROR_ATTR = "error.type";

export function llmSpanName(model: string): string {
  return `chat ${model}`;
}

export function toolSpanName(name: string): string {
  return `execute_tool ${name}`;
}

export function agentSpanAttributes(
  workdir: string,
  entrypoint: string,
  evalCaseId?: string | null,
  evalRunId?: string | null,
): Record<string, unknown> {
  const attributes: Record<string, unknown> = {
    "gen_ai.operation.name": "invoke_agent",
    "gen_ai.provider.name": "bourbon",
    "gen_ai.agent.name": "bourbon",
    [AGENT_WORKDIR_ATTR]: workdir,
    [AGENT_ENTRYPOINT_ATTR]: entrypoint,
  };
  if (evalCaseId) attributes[EVAL_CASE_ID_ATTR] = evalCaseId;
  if (evalRunId) attributes[EVAL_RUN_ID_ATTR] = evalRunId;
  return attributes;
}

export function llmRequestAttributes(
  model: string,
  maxTokens: number,
  provider: string,
): Record<string, unknown> {
  return {
    "gen_ai.operation.name": "chat",
    "gen_ai.provider.name": provider,
    "gen_ai.request.model": model,
    "gen_ai.request.max_tokens": maxTokens,
  };
}

export function llmResponseAttributes(
  finishReason: string,
  inputTokens: number | null,
  outputTokens: number | null,
): Record<string, unknown> {
  const attributes: Record<string, unknown> = {
    "gen_ai.response.finish_reasons": [finishReason],
  };
  if (inputTokens !== null) attributes["gen_ai.usage.input_tokens"] = inputTokens;
  if (outputTokens !== null) attributes["gen_ai.usage.output_tokens"] = outputTokens;
  return attributes;
}

export function toolSpanAttributes(
  name: string,
  callId: string,
  concurrent: boolean,
): Record<string, unknown> {
  return {
    "gen_ai.operation.name": "execute_tool",
    "gen_ai.tool.name": name,
    "gen_ai.tool.call.id": callId,
    "bourbon.tool.concurrent": concurrent,
  };
}
