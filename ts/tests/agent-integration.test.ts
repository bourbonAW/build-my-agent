import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Agent } from "../src/agent/agent";
import type { Message, ToolResultBlock } from "../src/llm";
import { createToolRegistry } from "../src/tools";
import { testConfig } from "./helpers/config";
import { FakeLLM, textResponse, toolResponse } from "./helpers/fake-llm";

let workdir: string;

beforeEach(() => {
  workdir = mkdtempSync(join(tmpdir(), "bourbon-agent-int-"));
});

afterEach(() => {
  rmSync(workdir, { recursive: true, force: true });
});

function toolResults(call: { messages: Message[] }): ToolResultBlock[] {
  const userMessage = [...call.messages].reverse().find((message) => message.role === "user");
  if (!userMessage) return [];
  return userMessage.content.filter(
    (block): block is ToolResultBlock => block.type === "tool_result",
  );
}

function featureConfig() {
  return testConfig({
    ui: { ...testConfig().ui, maxToolRounds: 20 },
    memory: {
      ...testConfig().memory,
      enabled: true,
      storageDir: join(workdir, "memory-root"),
    },
    tasks: { enabled: true, storageDir: join(workdir, "tasks"), defaultListId: "default" },
    audit: { enabled: true, logDir: join(workdir, "audit"), format: "jsonl" },
    sandbox: { ...testConfig().sandbox, enabled: false },
  });
}

function writeDemoSkill(): void {
  const directory = join(workdir, ".agents", "skills", "demo-skill");
  mkdirSync(directory, { recursive: true });
  writeFileSync(
    join(directory, "SKILL.md"),
    "---\nname: demo-skill\ndescription: Demo domain skill\n---\n\nDemo instructions body.\n",
  );
}

function writeAgentsFile(): void {
  writeFileSync(join(workdir, "AGENTS.md"), "# Rules\nAlways run tests.\n");
}

describe("agent feature integration", () => {
  test("runs memory, skills, todos, and tasks through real tools", async () => {
    writeDemoSkill();
    writeAgentsFile();
    const config = featureConfig();
    const script = [
      toolResponse("t1", "memory_write", {
        target: "project",
        content: "Project uses `bun test` for TypeScript checks.",
      }),
      toolResponse("t2", "Skill", { name: "demo-skill" }),
      toolResponse("t3", "TodoWrite", {
        items: [{ content: "verify", status: "in_progress", activeForm: "Verifying" }],
      }),
      toolResponse("t4", "TaskCreate", {
        subject: "Migration",
        description: "port all modules",
      }),
      toolResponse("t5", "TaskUpdate", { taskId: "1", status: "completed" }),
      toolResponse("t6", "TaskList", {}),
      toolResponse("t7", "memory_search", { query: "bun test" }),
      textResponse("all done"),
    ];
    const llm = new FakeLLM(script);
    const agent = new Agent({
      config,
      llm,
      registry: createToolRegistry(),
      workdir,
      sessionDir: join(workdir, "sessions"),
    });

    const answer = await agent.run("exercise features");
    expect(answer).toBe("all done");
    expect(llm.calls[0]!.system).toContain("demo-skill");
    expect(llm.calls[0]!.system).toContain("Always run tests.");
    expect(llm.calls[0]!.tools).toContain("memory_search");
    expect(llm.calls[0]!.tools).toContain("TaskCreate");

    const results = llm.calls.map((call) => toolResults(call));
    expect(String(results[1]![0]!.content)).toContain('"status":"written"');
    expect(String(results[2]![0]!.content)).toContain("Demo instructions body.");
    expect(String(results[3]![0]!.content)).toContain("[>] verify");
    expect(String(results[4]![0]!.content)).toContain('"subject":"Migration"');
    expect(String(results[5]![0]!.content)).toContain('"status":"completed"');
    expect(String(results[6]![0]!.content)).toContain("Migration");
    expect(JSON.parse(String(results[7]![0]!.content)).results).toHaveLength(1);

    const secondLlm = new FakeLLM([textResponse("remembered")]);
    const secondAgent = new Agent({
      config,
      llm: secondLlm,
      registry: createToolRegistry(),
      workdir,
      sessionDir: join(workdir, "sessions"),
    });
    expect(await secondAgent.run("what do you remember?")).toBe("remembered");
    expect(secondLlm.calls[0]!.system).toContain("Memory Index (MEMORY.md)");
    expect(secondLlm.calls[0]!.system).toContain("bun test");
    expect(secondLlm.calls[0]!.system).toContain("Demo domain skill");
  });

  test("auto-compacts context and resumes sessions", async () => {
    const config = testConfig({
      ui: { ...testConfig().ui, tokenThreshold: 1 },
      audit: { enabled: false, logDir: join(workdir, "audit"), format: "jsonl" },
      sandbox: { ...testConfig().sandbox, enabled: false },
    });
    const llm = new FakeLLM([
      textResponse("first"),
      textResponse("second"),
      textResponse("third"),
    ]);
    const agent = new Agent({
      config,
      llm,
      registry: createToolRegistry(),
      workdir,
      sessionDir: join(workdir, "sessions"),
      sessionId: "session-integration",
    });

    expect(await agent.run("one")).toBe("first");
    expect(await agent.run("two")).toBe("second");
    expect(await agent.run("three")).toBe("third");

    const active = agent.session.chain.buildActiveChain();
    expect(active[0]!.isCompactBoundary).toBe(true);
    expect(agent.session.getMessagesForLlm()).toHaveLength(4);
    const manifestPath = join(
      workdir,
      "sessions",
      agent.sessionManager.projectName,
      "session-integration.compact.json",
    );
    expect(existsSync(manifestPath)).toBe(true);
    expect(
      Object.keys(
        (JSON.parse(readFileSync(manifestPath, "utf8")) as { overrides: Record<string, unknown> })
          .overrides,
      ).length,
    ).toBeGreaterThan(0);

    const resumeConfig = testConfig({
      audit: { enabled: false, logDir: join(workdir, "audit"), format: "jsonl" },
      sandbox: { ...testConfig().sandbox, enabled: false },
    });
    const resumedLlm = new FakeLLM([textResponse("resumed")]);
    const resumed = new Agent({
      config: resumeConfig,
      llm: resumedLlm,
      registry: createToolRegistry(),
      workdir,
      sessionDir: join(workdir, "sessions"),
      sessionId: "session-integration",
    });
    expect(resumed.session.sessionId).toBe("session-integration");
    expect(resumed.session.getMessagesForLlm()).toHaveLength(4);
    expect(await resumed.run("four")).toBe("resumed");
    expect(resumedLlm.calls[0]!.messages.length).toBe(5);
    expect(resumed.session.getMessagesForLlm().length).toBeGreaterThanOrEqual(4);
  });
});
