import { afterEach, describe, expect, test } from "bun:test";
import type { Server } from "bun";
import { createLLMClient, OpenAIClient } from "../src/llm";
import type { Message } from "../src/llm";
import { testConfig } from "./helpers/config";

interface MockState {
  body: Record<string, unknown> | null;
}

function chunk(delta: Record<string, unknown>, finish: string | null = null): string {
  return JSON.stringify({
    id: "chatcmpl-1",
    object: "chat.completion.chunk",
    created: 1,
    model: "mock",
    choices: [{ index: 0, delta, finish_reason: finish }],
  });
}

function usage(prompt: number, completion: number): string {
  return JSON.stringify({
    id: "chatcmpl-1",
    object: "chat.completion.chunk",
    created: 1,
    model: "mock",
    choices: [],
    usage: { prompt_tokens: prompt, completion_tokens: completion, total_tokens: prompt + completion },
  });
}

function sse(chunks: string[]): Response {
  return new Response(
    `${chunks.map((item) => `data: ${item}\n\n`).join("")}data: [DONE]\n\n`,
    { headers: { "content-type": "text/event-stream" } },
  );
}

let server: Server<unknown> | null = null;

afterEach(() => {
  server?.stop(true);
  server = null;
});

describe("OpenAI-compatible client", () => {
  test("streams text and usage", async () => {
    server = Bun.serve({
      port: 0,
      async fetch(request) {
        const body = (await request.json()) as Record<string, unknown>;
        (server as unknown as MockState).body = body;
        return sse([
          chunk({ content: "Hel" }),
          chunk({ content: "lo" }),
          chunk({}, "stop"),
          usage(9, 2),
        ]);
      },
    });

    const client = new OpenAIClient({
      apiKey: "test",
      model: "mock",
      baseUrl: `http://127.0.0.1:${server.port}/v1`,
      maxTokens: 128,
      temperature: 0,
    });

    const chunks: string[] = [];
    const response = await client.streamChat({
      messages: [{ role: "user", content: [{ type: "text", text: "hi" }] }],
      system: "system prompt",
      maxTokens: 128,
      onText: (text) => chunks.push(text),
    });

    expect(chunks.join("")).toBe("Hello");
    expect(response.content).toEqual([{ type: "text", text: "Hello" }]);
    expect(response.stopReason).toBe("end_turn");
    expect(response.usage).toEqual({ inputTokens: 9, outputTokens: 2 });

    const body = (server as unknown as MockState).body!;
    expect((body.messages as Array<{ role: string }>)[0]!.role).toBe("system");
    expect(body.stream).toBe(true);
    expect(body.max_tokens).toBe(128);
  });

  test("accumulates tool call fragments", async () => {
    server = Bun.serve({
      port: 0,
      async fetch(request) {
        await request.json();
        return sse([
          chunk({
            tool_calls: [
              {
                index: 0,
                id: "call_1",
                type: "function",
                function: { name: "Read", arguments: '{"path":' },
              },
            ],
          }),
          chunk({
            tool_calls: [{ index: 0, function: { arguments: '"a.txt"}' } }],
          }),
          chunk({}, "tool_calls"),
          usage(12, 4),
        ]);
      },
    });

    const client = new OpenAIClient({
      apiKey: "test",
      model: "mock",
      baseUrl: `http://127.0.0.1:${server.port}/v1`,
      maxTokens: 128,
      temperature: 0,
    });

    const response = await client.streamChat({
      messages: [{ role: "user", content: [{ type: "text", text: "read" }] }],
      tools: [
        {
          name: "Read",
          description: "Read a file",
          input_schema: {
            type: "object",
            properties: { path: { type: "string" } },
            required: ["path"],
          },
        },
      ],
      maxTokens: 128,
    });

    expect(response.stopReason).toBe("tool_use");
    expect(response.content[0]).toEqual({
      type: "tool_use",
      id: "call_1",
      name: "Read",
      input: { path: "a.txt" },
    });
  });

  test("converts tool results into OpenAI tool messages", async () => {
    server = Bun.serve({
      port: 0,
      async fetch(request) {
        (server as unknown as MockState).body = (await request.json()) as Record<string, unknown>;
        return sse([chunk({ content: "ok" }, "stop"), usage(20, 1)]);
      },
    });

    const messages: Message[] = [
      { role: "user", content: [{ type: "text", text: "read a.txt" }] },
      {
        role: "assistant",
        content: [
          {
            type: "tool_use",
            id: "call_1",
            name: "Read",
            input: { path: "a.txt" },
          },
        ],
      },
      {
        role: "user",
        content: [{ type: "tool_result", tool_use_id: "call_1", content: "file body" }],
      },
    ];

    const client = new OpenAIClient({
      apiKey: "test",
      model: "mock",
      baseUrl: `http://127.0.0.1:${server.port}/v1`,
      maxTokens: 128,
      temperature: 0,
    });
    await client.streamChat({ messages, maxTokens: 128 });

    const body = (server as unknown as MockState).body!;
    const converted = body.messages as Array<Record<string, unknown>>;
    expect(converted[1]).toMatchObject({ role: "assistant" });
    expect((converted[1]!.tool_calls as unknown[]).length).toBe(1);
    expect(converted[2]).toMatchObject({
      role: "tool",
      tool_call_id: "call_1",
      content: "file body",
    });
  });

  test("createLLMClient selects providers from config", () => {
    expect(createLLMClient(testConfig()).constructor.name).toBe("AnthropicClient");

    const openai = testConfig({ defaultProvider: "openai" });
    openai.openai.apiKey = "test";
    expect(createLLMClient(openai).constructor.name).toBe("OpenAIClient");

    const kimi = testConfig({ defaultProvider: "kimi" });
    kimi.openai.apiKey = "test";
    expect(createLLMClient(kimi).constructor.name).toBe("OpenAIClient");

    const missing = testConfig({ defaultProvider: "openai" });
    expect(() => createLLMClient(missing)).toThrow("OpenAI API key not configured");
  });
});
