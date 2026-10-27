import type { LLMClient, LLMResponse, Message, StreamChatParams } from "../../src/llm";

export class FakeLLM implements LLMClient {
  readonly model = "fake-model";
  readonly calls: Array<{ messages: Message[]; system?: string; tools?: string[] }> = [];

  constructor(private readonly script: LLMResponse[]) {}

  async streamChat(params: StreamChatParams): Promise<LLMResponse> {
    this.calls.push({
      messages: structuredClone(params.messages),
      ...(params.system ? { system: params.system } : {}),
      ...(params.tools ? { tools: params.tools.map((tool) => tool.name) } : {}),
    });
    const response = this.script.shift();
    if (!response) throw new Error("FakeLLM script exhausted");
    for (const block of response.content) {
      if (block.type === "text") params.onText?.(block.text);
    }
    return response;
  }
}

export function textResponse(text: string): LLMResponse {
  return {
    content: [{ type: "text", text }],
    stopReason: "end_turn",
    usage: { inputTokens: 10, outputTokens: 5 },
  };
}

export function toolResponse(
  id: string,
  name: string,
  input: Record<string, unknown>,
): LLMResponse {
  return {
    content: [{ type: "tool_use", id, name, input }],
    stopReason: "tool_use",
    usage: { inputTokens: 12, outputTokens: 3 },
  };
}

export function multiToolResponse(
  calls: Array<{ id: string; name: string; input: Record<string, unknown> }>,
): LLMResponse {
  return {
    content: calls.map((call) => ({
      type: "tool_use" as const,
      id: call.id,
      name: call.name,
      input: call.input,
    })),
    stopReason: "tool_use",
    usage: { inputTokens: 20, outputTokens: 6 },
  };
}
