import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { existsSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Agent } from "../src/agent/agent";
import { SessionManager } from "../src/session/manager";
import { TranscriptStore } from "../src/session/storage";
import {
  AGENT_TYPE_CONFIGS,
  SubagentManager,
  SubagentSessionAdapter,
  ToolFilter,
} from "../src/subagent";
import type { AgentFactory } from "../src/subagent";
import { createToolRegistry } from "../src/tools";
import { agentTool, agentWaitTool } from "../src/tools/agent_tool";
import type { ToolContext } from "../src/tools";
import { testConfig } from "./helpers/config";
import { FakeLLM, textResponse, toolResponse } from "./helpers/fake-llm";

let workdir: string;

beforeEach(() => {
  workdir = mkdtempSync(join(tmpdir(), "bourbon-subagent-"));
});

afterEach(() => {
  rmSync(workdir, { recursive: true, force: true });
});

function fakeFactory(delay = 0): AgentFactory {
  return () => ({
    run: async (prompt: string) => {
      if (delay) await Bun.sleep(delay);
      return `sub-result:${prompt}`;
    },
    usage: { inputTokens: 7, outputTokens: 3 },
    toolCallCount: 2,
  });
}

describe("tool filtering", () => {
  const filter = new ToolFilter();

  test("restricts explore and plan to read-only tools", () => {
    const explore = AGENT_TYPE_CONFIGS.explore!;
    expect(filter.isAllowed("Read", explore)).toBe(true);
    expect(filter.isAllowed("WebFetch", explore)).toBe(true);
    expect(filter.isAllowed("Bash", explore)).toBe(false);
    expect(filter.isAllowed("Write", explore)).toBe(false);
    expect(filter.isAllowed("Agent", explore)).toBe(false);
    expect(filter.isAllowed("TodoWrite", explore)).toBe(false);
  });

  test("hides task tools from async runs but keeps them for teammates", () => {
    const definition = AGENT_TYPE_CONFIGS.default!;
    expect(filter.isAllowed("TaskCreate", definition, "async")).toBe(false);
    expect(filter.isAllowed("TaskCreate", definition, "teammate")).toBe(true);
    expect(filter.isAllowed("TaskCreate", definition, "normal")).toBe(true);
  });
});

describe("subagent manager", () => {
  test("runs foreground jobs and records usage", async () => {
    const manager = new SubagentManager(testConfig(), workdir, null, {
      agentFactory: fakeFactory(),
    });

    const result = await manager.spawn("demo", "hello");
    expect(typeof result).not.toBe("string");
    if (typeof result === "string") return;

    expect(result.content).toBe("sub-result:hello");
    expect(result.totalTokens).toBe(10);
    expect(result.totalToolCalls).toBe(2);

    const run = manager.getRun(result.runId)!;
    expect(run.status).toBe("completed");
    expect(run.toolCallCount).toBe(2);
    expect(manager.renderRunList()).toContain("completed");
  });

  test("runs background jobs and waits for them", async () => {
    const manager = new SubagentManager(testConfig(), workdir, null, {
      agentFactory: fakeFactory(50),
    });

    const runId = await manager.spawn("background", "work", {
      runInBackground: true,
    });
    expect(typeof runId).toBe("string");

    const output = await manager.waitForRuns([runId as string], 5);
    expect(output).toContain("sub-result:work");
    expect(output).toContain("[completed]");
    expect(manager.getRunOutput(runId as string)).toBe("sub-result:work");
  });

  test("stops a running job", async () => {
    const manager = new SubagentManager(testConfig(), workdir, null, {
      agentFactory: fakeFactory(1000),
    });
    const runId = (await manager.spawn("long", "work", {
      runInBackground: true,
    })) as string;

    expect(manager.stopRun(runId)).toContain("Stopped run");
    expect(manager.getRun(runId)!.status).toBe("killed");
  });

  test("agent tools spawn and wait through the manager", async () => {
    const manager = new SubagentManager(testConfig(), workdir, null, {
      agentFactory: fakeFactory(20),
    });
    const ctx = {
      workdir,
      config: testConfig(),
      agent: { subagentManager: manager },
    } as unknown as ToolContext;

    const background = await agentTool.run(
      {
        description: "bg",
        prompt: "do it",
        run_in_background: true,
      },
      ctx,
    );
    const runId = /Started background run: (\w+)/.exec(background)?.[1];
    expect(runId).toBeTruthy();

    const waited = await agentWaitTool.run(
      { run_ids: [runId], timeout_seconds: 5 },
      ctx,
    );
    expect(waited).toContain("sub-result:do it");
  });
});

describe("real subagent integration", () => {
  test("runs a real Agent with explore tool filtering and an isolated session", async () => {
    const config = testConfig();
    const store = new TranscriptStore(join(workdir, "sessions"));
    const parentManager = new SessionManager(store, "parent-project", workdir);
    const parentSession = parentManager.createSession();
    const parent = new Agent({
      config,
      workdir,
      llm: new FakeLLM([textResponse("parent")]),
      registry: createToolRegistry(),
      session: parentSession,
      sessionDir: join(workdir, "sessions"),
    });

    const subLlm = new FakeLLM([textResponse("sub answer")]);
    let receivedDefinition = null as null | { systemPromptSuffix: string | null };
    const manager = new SubagentManager(config, workdir, parent, {
      agentFactory: (_run, definition) => {
        receivedDefinition = definition;
        return new Agent({
          config,
          workdir,
          llm: subLlm,
          registry: createToolRegistry(),
          sessionDir: join(workdir, "sessions"),
        });
      },
    });

    const result = await manager.spawn("explore", "read only", {
      agentType: "explore",
    });
    expect(typeof result).not.toBe("string");
    if (typeof result === "string") return;

    expect(result.content).toBe("sub answer");
    expect(subLlm.calls[0]!.tools).toContain("Read");
    expect(subLlm.calls[0]!.tools).toContain("Grep");
    expect(subLlm.calls[0]!.tools).not.toContain("Bash");
    expect(subLlm.calls[0]!.tools).not.toContain("Agent");
    expect(subLlm.calls[0]!.tools).not.toContain("TodoWrite");
    expect(receivedDefinition?.systemPromptSuffix).toContain("READ-ONLY");
  });

  test("parent Agent executes the Agent tool end to end", async () => {
    const config = testConfig();
    const parentLlm = new FakeLLM([
      toolResponse("t1", "Agent", {
        description: "inspect",
        prompt: "look around",
        subagent_type: "explore",
      }),
      textResponse("parent final"),
    ]);
    const parent = new Agent({
      config,
      workdir,
      llm: parentLlm,
      registry: createToolRegistry(),
      sessionDir: join(workdir, "sessions"),
    });

    const manager = new SubagentManager(config, workdir, parent, {
      agentFactory: () =>
        new Agent({
          config,
          workdir,
          llm: new FakeLLM([textResponse("child findings")]),
          registry: createToolRegistry(),
          sessionDir: join(workdir, "sessions"),
        }),
    });
    (parent as unknown as { subagentManager: SubagentManager }).subagentManager = manager;

    const answer = await parent.run("delegate this");
    expect(answer).toBe("parent final");

    const toolResult = parentLlm.calls[1]!.messages.at(-1)!.content[0]!;
    expect(JSON.stringify(toolResult)).toContain("child findings");
    expect(manager.listRuns()).toHaveLength(1);
    expect(manager.listRuns()[0]!.status).toBe("completed");
  });

  test("session adapter isolates subagent transcripts", () => {
    const store = new TranscriptStore(join(workdir, "sessions"));
    const adapter = new SubagentSessionAdapter(store, "parent", workdir, "run-1");
    expect(adapter.projectName).toBe("parent/subagents");
    const session = adapter.createSession();
    expect(session.metadata.description).toBe("Subagent run run-1");
    expect(
      existsSync(join(workdir, "sessions", "parent", "subagents", `${session.sessionId}.meta.json`)),
    ).toBe(true);
  });
});
