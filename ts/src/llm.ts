import Anthropic from "@anthropic-ai/sdk";
import OpenAI from "openai";
import type { BourbonConfig, ProviderConfig } from "./config";

export interface TextBlock {
  type: "text";
  text: string;
}

export interface ToolUseBlock {
  type: "tool_use";
  id: string;
  name: string;
  input: Record<string, unknown>;
}

export interface ToolResultBlock {
  type: "tool_result";
  tool_use_id: string;
  content: string;
  is_error?: boolean;
}

export type ContentBlock = TextBlock | ToolUseBlock | ToolResultBlock;
export type AssistantBlock = TextBlock | ToolUseBlock;

export interface Message {
  role: "user" | "assistant";
  content: ContentBlock[];
}

export interface ToolDefinition {
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
}

export interface StreamChatParams {
  messages: Message[];
  tools?: ToolDefinition[];
  system?: string;
  maxTokens: number;
  signal?: AbortSignal;
  onText?: (text: string) => void;
}

export interface LLMResponse {
  content: AssistantBlock[];
  stopReason: string | null;
  usage: {
    inputTokens: number;
    outputTokens: number;
  };
}

export interface LLMClient {
  readonly model: string;
  streamChat(params: StreamChatParams): Promise<LLMResponse>;
}

export class LLMError extends Error {
  constructor(message: string, options?: ErrorOptions) {
    super(message, options);
    this.name = "LLMError";
  }
}

export function isToolUse(block: AssistantBlock): block is ToolUseBlock {
  return block.type === "tool_use";
}

export class AnthropicClient implements LLMClient {
  readonly model: string;
  private readonly client: Anthropic;

  constructor(config: ProviderConfig) {
    this.model = config.model;
    this.client = new Anthropic({
      apiKey: config.apiKey,
      baseURL: config.baseUrl || undefined,
      maxRetries: 0,
      timeout: 120_000,
    });
  }

  async streamChat(params: StreamChatParams): Promise<LLMResponse> {
    const request: Anthropic.MessageCreateParamsStreaming = {
      model: this.model,
      max_tokens: params.maxTokens,
      messages: params.messages as Anthropic.MessageParam[],
      stream: true,
      ...(params.system ? { system: params.system } : {}),
      ...(params.tools?.length
        ? { tools: params.tools as unknown as Anthropic.Tool[] }
        : {}),
    };

    try {
      const stream = this.client.messages.stream(request, {
        signal: params.signal,
      });
      if (params.onText) {
        stream.on("text", (text) => params.onText?.(text));
      }

      const final = await stream.finalMessage();
      const content: AssistantBlock[] = [];

      for (const block of final.content) {
        if (block.type === "text") {
          content.push({ type: "text", text: block.text });
        } else if (block.type === "tool_use") {
          content.push({
            type: "tool_use",
            id: block.id,
            name: block.name,
            input: block.input as Record<string, unknown>,
          });
        }
      }

      return {
        content,
        stopReason: final.stop_reason ?? null,
        usage: {
          inputTokens: final.usage.input_tokens ?? 0,
          outputTokens: final.usage.output_tokens ?? 0,
        },
      };
    } catch (error) {
      if (params.signal?.aborted) {
        throw new LLMError("Request cancelled", { cause: error });
      }
      const message = error instanceof Error ? error.message : String(error);
      throw new LLMError(`Anthropic API error: ${message}`, { cause: error });
    }
  }
}

interface OpenAIToolAccumulator {
  id: string;
  name: string;
  args: string;
}

function toOpenAIMessages(messages: Message[]): Array<Record<string, unknown>> {
  const converted: Array<Record<string, unknown>> = [];

  for (const message of messages) {
    if (message.role === "assistant") {
      const text = message.content
        .filter((block): block is TextBlock => block.type === "text")
        .map((block) => block.text)
        .join("");
      const toolCalls = message.content
        .filter((block): block is ToolUseBlock => block.type === "tool_use")
        .map((block) => ({
          id: block.id,
          type: "function" as const,
          function: { name: block.name, arguments: JSON.stringify(block.input) },
        }));
      converted.push({
        role: "assistant",
        content: text || null,
        ...(toolCalls.length ? { tool_calls: toolCalls } : {}),
      });
      continue;
    }

    const text = message.content
      .filter((block): block is TextBlock => block.type === "text")
      .map((block) => block.text)
      .join("\n");
    const toolResults = message.content.filter(
      (block): block is ToolResultBlock => block.type === "tool_result",
    );

    if (text) converted.push({ role: "user", content: text });
    for (const result of toolResults) {
      converted.push({
        role: "tool",
        tool_call_id: result.tool_use_id,
        content: result.content,
      });
    }
    if (!text && !toolResults.length) converted.push({ role: "user", content: "" });
  }

  return converted;
}

export class OpenAIClient implements LLMClient {
  readonly model: string;
  private readonly client: OpenAI;

  constructor(config: ProviderConfig) {
    this.model = config.model;
    this.client = new OpenAI({
      apiKey: config.apiKey,
      baseURL: config.baseUrl || undefined,
      maxRetries: 0,
      timeout: 120_000,
    });
  }

  async streamChat(params: StreamChatParams): Promise<LLMResponse> {
    const convertedMessages = toOpenAIMessages(params.messages);
    if (params.system) {
      convertedMessages.unshift({ role: "system", content: params.system });
    }

    const request: Record<string, unknown> = {
      model: this.model,
      messages: convertedMessages,
      max_tokens: params.maxTokens,
      stream: true,
      stream_options: { include_usage: true },
      ...(params.tools?.length
        ? {
            tools: params.tools.map((tool) => ({
              type: "function",
              function: {
                name: tool.name,
                description: tool.description,
                parameters: tool.input_schema,
              },
            })),
          }
        : {}),
    };

    try {
      const stream = (await this.client.chat.completions.create(
        request as unknown as OpenAI.Chat.Completions.ChatCompletionCreateParamsStreaming,
        { signal: params.signal },
      )) as AsyncIterable<OpenAI.Chat.Completions.ChatCompletionChunk>;

      let text = "";
      let finishReason = "";
      let inputTokens = 0;
      let outputTokens = 0;
      const toolAccumulators = new Map<number, OpenAIToolAccumulator>();

      for await (const chunk of stream) {
        const choice = chunk.choices?.[0];
        const delta = choice?.delta;
        if (delta?.content) {
          text += delta.content;
          params.onText?.(delta.content);
        }
        for (const call of delta?.tool_calls ?? []) {
          const index = call.index ?? 0;
          const accumulator = toolAccumulators.get(index) ?? {
            id: "",
            name: "",
            args: "",
          };
          if (call.id) accumulator.id = call.id;
          if (call.function?.name) accumulator.name = call.function.name;
          if (call.function?.arguments) accumulator.args += call.function.arguments;
          toolAccumulators.set(index, accumulator);
        }
        if (choice?.finish_reason) finishReason = choice.finish_reason;
        if (chunk.usage) {
          inputTokens = chunk.usage.prompt_tokens ?? 0;
          outputTokens = chunk.usage.completion_tokens ?? 0;
        }
      }

      const content: AssistantBlock[] = [];
      if (text) content.push({ type: "text", text });
      for (const [, call] of [...toolAccumulators.entries()].sort(([left], [right]) => left - right)) {
        let input: Record<string, unknown> = {};
        try {
          input = call.args ? (JSON.parse(call.args) as Record<string, unknown>) : {};
        } catch {
          input = {};
        }
        content.push({
          type: "tool_use",
          id: call.id,
          name: call.name,
          input,
        });
      }

      return {
        content,
        stopReason: content.some((block) => block.type === "tool_use")
          ? "tool_use"
          : "end_turn",
        usage: { inputTokens, outputTokens },
      };
    } catch (error) {
      if (params.signal?.aborted) {
        throw new LLMError("Request cancelled", { cause: error });
      }
      const message = error instanceof Error ? error.message : String(error);
      throw new LLMError(`OpenAI API error: ${message}`, { cause: error });
    }
  }
}

export function createLLMClient(config: BourbonConfig): LLMClient {
  if (config.defaultProvider !== "anthropic") {
    const keyName = config.defaultProvider === "kimi" ? "Kimi" : "OpenAI";
    if (!config.openai.apiKey) {
      throw new LLMError(`${keyName} API key not configured`);
    }
    return new OpenAIClient(config.openai);
  }
  if (!config.anthropic.apiKey) {
    throw new LLMError("Anthropic API key not configured");
  }
  return new AnthropicClient(config.anthropic);
}
