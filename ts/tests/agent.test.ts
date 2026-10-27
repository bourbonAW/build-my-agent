import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Agent } from "../src/agent/agent";
import type { LLMClient, LLMResponse, Message, StreamChatParams } from "../src/llm";
import { TaskService } from "../src/tasks/service";
import { TaskStore } from "../src/tasks/store";
import { createToolRegistry } from "../src/tools";
import { testConfig } from "./helpers/config";

class FakeLLM implements LLMClient {
  readonly model = "fake-model";
  readonly calls: Array<{ messages: Message[]; system?: string }> = [];

  constructor(private readonly script: LLMResponse[]) {}

  async streamChat(params: StreamChatParams): Promise<LLMResponse> {
    this.calls.push({ messages: structuredClone(params.messages), system: params.system });
    const response = this.script.shift();
    if (!response) throw new Error("FakeLLM script exhausted");
    for (const block of response.content) {
      if (block.type === "text") params.onText?.(block.text);
    }
    return response;
  }
}

const config = testConfig();

function textResponse(text: string): LLMResponse {
  return {
    content: [{ type: "text", text }],
    stopReason: "end_turn",
    usage: { inputTokens: 10, outputTokens: 5 },
  };
}

function toolResponse(id: string, name: string, input: Record<string, unknown>): LLMResponse {
  return {
    content: [{ type: "tool_use", id, name, input }],
    stopReason: "tool_use",
    usage: { inputTokens: 12, outputTokens: 3 },
  };
}

let workdir: string;

beforeEach(() => {
  workdir = mkdtempSync(join(tmpdir(), "bourbon-ts-agent-"));
});

afterEach(() => {
  rmSync(workdir, { recursive: true, force: true });
});

describe("agent loop", () => {
  test("executes a tool and returns the final answer", async () => {
    const llm = new FakeLLM([
      toolResponse("t1", "Write", { path: "out.txt", content: "hi" }),
      textResponse("done"),
    ]);
    const starts: string[] = [];
    const ends: string[] = [];

    const agent = new Agent({
      config,
      llm,
      registry: createToolRegistry(),
      workdir,
      sessionDir: join(workdir, ".sessions"),
      callbacks: {
        onToolStart: (name) => starts.push(name),
        onToolEnd: (name, _output, isError) => ends.push(`${name}:${isError}`),
      },
    });

    const answer = await agent.run("write a file");

    expect(answer).toBe("done");
    expect(readFileSync(join(workdir, "out.txt"), "utf8")).toBe("hi");
    expect(starts).toEqual(["Write"]);
    expect(ends).toEqual(["Write:false"]);
    expect(agent.usage).toEqual({ inputTokens: 22, outputTokens: 8 });
    expect(agent.totalTokens).toBe(30);
    expect(llm.calls).toHaveLength(2);

    const toolResultMessage = llm.calls[1]!.messages.at(-1)!;
    expect(toolResultMessage.role).toBe("user");
    expect(toolResultMessage.content[0]).toMatchObject({
      type: "tool_result",
      tool_use_id: "t1",
      content: "Wrote 2 bytes to out.txt",
    });
  });

  test("streams text chunks through the callback", async () => {
    const llm = new FakeLLM([textResponse("hello there")]);
    const chunks: string[] = [];
    const agent = new Agent({
      config,
      llm,
      registry: createToolRegistry(),
      workdir,
      sessionDir: join(workdir, ".sessions"),
      callbacks: { onText: (chunk) => chunks.push(chunk) },
    });

    const answer = await agent.run("say hi");

    expect(answer).toBe("hello there");
    expect(chunks.join("")).toBe("hello there");
  });

  test("stops after max tool rounds with a forced summary", async () => {
    const script = Array.from({ length: config.ui.maxToolRounds }, (_, index) =>
      toolResponse(`t${index}`, "Bash", { command: "true" }),
    );
    script.push(textResponse("summary after max rounds"));
    const llm = new FakeLLM(script);
    const agent = new Agent({
      config,
      llm,
      registry: createToolRegistry(),
      workdir,
      sessionDir: join(workdir, ".sessions"),
    });

    const answer = await agent.run("loop forever");

    expect(llm.calls).toHaveLength(config.ui.maxToolRounds + 1);
    expect(answer).toContain("summary after max rounds");
  });

  test("reports unknown tools as errors", async () => {
    const llm = new FakeLLM([
      toolResponse("t1", "DoesNotExist", {}),
      textResponse("gave up"),
    ]);
    const agent = new Agent({
      config,
      llm,
      registry: createToolRegistry(),
      workdir,
      sessionDir: join(workdir, ".sessions"),
    });

    const answer = await agent.run("use a bad tool");

    expect(answer).toBe("gave up");
    const toolResult = llm.calls[1]!.messages.at(-1)!.content[0]!;
    expect(toolResult).toMatchObject({
      type: "tool_result",
      content: "Unknown tool: DoesNotExist",
      is_error: true,
    });
  });

  test("nudges the model about pending tasks after repeated non-task rounds", async () => {
    const tasksDir = join(workdir, "tasks");
    const configWithTasks = testConfig({
      ui: { ...testConfig().ui, maxToolRounds: 12 },
      tasks: { enabled: true, storageDir: tasksDir, defaultListId: "default" },
      audit: { enabled: false, logDir: join(workdir, "audit"), format: "jsonl" },
      sandbox: { ...testConfig().sandbox, enabled: false },
    });
    const script = Array.from({ length: 10 }, (_, index) =>
      toolResponse(`t${index}`, "Read", { path: `missing-${index}.txt` }),
    );
    script.push(textResponse("finished"));
    const llm = new FakeLLM(script);
    const agent = new Agent({
      config: configWithTasks,
      llm,
      registry: createToolRegistry(),
      workdir,
      sessionDir: join(workdir, ".sessions"),
    });
    new TaskService(new TaskStore(tasksDir)).createTask(
      agent.session.sessionId,
      "Pending migration",
      "still open",
    );

    expect(await agent.run("keep reading")).toBe("finished");

    const lastCall = llm.calls.at(-1)!;
    const lastUser = [...lastCall.messages].reverse().find((message) => message.role === "user")!;
    const reminder = lastUser.content.find(
      (block) => block.type === "text" && block.text.includes("<task_reminder>"),
    );
    expect(reminder).toBeDefined();
    expect((reminder as { text: string }).text).toContain("Pending migration");
  });

  test("clears history", async () => {
    const llm = new FakeLLM([textResponse("one"), textResponse("two")]);
    const agent = new Agent({
      config,
      llm,
      registry: createToolRegistry(),
      workdir,
      sessionDir: join(workdir, ".sessions"),
    });

    await agent.run("first");
    expect(agent.history).toHaveLength(2);

    agent.clearHistory();
    expect(agent.history).toHaveLength(0);

    await agent.run("second");
    expect(llm.calls[1]!.messages).toHaveLength(1);
  });
});
