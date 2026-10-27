import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { existsSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { inferCapabilities } from "../src/access_control/capabilities";
import { PolicyEngine } from "../src/access_control/policy";
import { AuditEvent, AuditLogger } from "../src/audit";
import type { LLMResponse } from "../src/llm";
import { Agent } from "../src/agent/agent";
import { buildMatchCandidate } from "../src/permissions/matching";
import { SessionPermissionStore } from "../src/permissions/runtime";
import { createToolRegistry } from "../src/tools";
import { testConfig } from "./helpers/config";
import { FakeLLM, textResponse, toolResponse } from "./helpers/fake-llm";
import type { PermissionChoice } from "../src/permissions/runtime";

let workdir: string;

beforeEach(() => {
  workdir = mkdtempSync(join(tmpdir(), "bourbon-security-"));
});

afterEach(() => {
  rmSync(workdir, { recursive: true, force: true });
});

function accessConfig(overrides: Partial<ReturnType<typeof testConfig>["accessControl"]> = {}) {
  const base = testConfig().accessControl;
  return {
    ...base,
    ...overrides,
    file: { ...base.file, ...(overrides.file ?? {}) },
    command: { ...base.command, ...(overrides.command ?? {}) },
  };
}

describe("capability inference", () => {
  test("infers bash and file capabilities", () => {
    expect(inferCapabilities("Bash", { command: "curl https://x.dev" }, ["exec"]).capabilities).toEqual(
      ["exec", "net"],
    );
    expect(
      inferCapabilities("Bash", { command: "cat a > b" }, ["exec"]).capabilities,
    ).toEqual(["exec", "file_read", "file_write"]);

    const read = inferCapabilities("Read", { path: "a.txt" }, ["file_read"]);
    expect(read.filePaths).toEqual(["a.txt"]);
    expect(inferCapabilities("Grep", {}, ["file_read"]).filePaths).toEqual(["."]);
  });
});

describe("policy engine", () => {
  test("enforces file allow and deny rules", () => {
    const denyDir = join(workdir, "secret");
    const engine = new PolicyEngine(
      "allow",
      accessConfig({
        file: {
          allow: ["{workdir}/**"],
          deny: [`${denyDir}/**`],
          mandatoryDeny: [],
        },
      }),
      workdir,
    );

    const allowed = engine.evaluate({ capabilities: ["file_read"], filePaths: ["src/a.ts"] });
    expect(allowed.action).toBe("allow");

    const denied = engine.evaluate({ capabilities: ["file_read"], filePaths: ["secret/a.key"] });
    expect(denied.action).toBe("deny");
    expect(denied.reason).toContain("file.deny");

    const outside = engine.evaluate({ capabilities: ["file_read"], filePaths: ["../escape"] });
    expect(outside.action).toBe("deny");
  });

  test("enforces command deny and approval patterns", () => {
    const engine = new PolicyEngine(
      "allow",
      accessConfig({
        command: {
          denyPatterns: ["rm -rf /", "sudo *"],
          needApprovalPatterns: ["git push *", "pip install *"],
        },
      }),
      workdir,
    );

    expect(engine.evaluateCommand("sudo rm x", { capabilities: ["exec"], filePaths: [] }).action).toBe(
      "deny",
    );
    expect(
      engine.evaluateCommand("git push origin main", { capabilities: ["exec"], filePaths: [] })
        .action,
    ).toBe("need_approval");
    expect(
      engine.evaluateCommand("echo hi", { capabilities: ["exec"], filePaths: [] }).action,
    ).toBe("allow");
  });

  test("allows net capabilities at the access-control layer", () => {
    const engine = new PolicyEngine("allow", accessConfig(), workdir);
    const decision = engine.evaluateCommand("curl https://x.dev", {
      capabilities: ["exec", "net"],
      filePaths: [],
    });
    expect(decision.action).toBe("allow");
    expect(decision.reason).toBe("all capabilities allowed");
  });
});

describe("permission matching", () => {
  test("builds and matches stable candidates", () => {
    const store = new SessionPermissionStore();
    const candidate = buildMatchCandidate("Bash", { command: "git push origin main" }, workdir);
    expect(candidate).toMatchObject({ kind: "command_prefix", value: "git push" });

    expect(store.hasMatch("Bash", { command: "git push other" }, workdir)).toBe(false);
    store.add(candidate);
    expect(store.hasMatch("Bash", { command: "git push other" }, workdir)).toBe(true);
    expect(store.hasMatch("Bash", { command: "git pull" }, workdir)).toBe(false);

    const write = buildMatchCandidate("Write", { path: "new/file.txt" }, workdir);
    expect(write.kind).toBe("parent_dir");
  });
});

describe("agent permission flow", () => {
  function approvalConfig() {
    return testConfig({
      accessControl: accessConfig({
        command: { denyPatterns: [], needApprovalPatterns: ["echo *"] },
      }),
      audit: { enabled: true, logDir: join(workdir, "audit"), format: "jsonl" },
      sandbox: { ...testConfig().sandbox, enabled: false },
    });
  }

  async function startAgent(script: LLMResponse[]) {
    const llm = new FakeLLM(script);
    const ends: string[] = [];
    const agent = new Agent({
      config: approvalConfig(),
      llm,
      registry: createToolRegistry(),
      workdir,
      sessionDir: join(workdir, "sessions"),
      callbacks: {
        onToolEnd: (name, output) => ends.push(`${name}:${output}`),
      },
    });
    return { agent, llm, ends };
  }

  test("suspends for approval, allows once, and executes", async () => {
    const { agent } = await startAgent([
      toolResponse("t1", "Bash", { command: "echo approved > once.txt" }),
      textResponse("done"),
    ]);

    const partial = await agent.run("needs approval");
    expect(partial).toBe("");
    expect(agent.activePermissionRequest?.toolName).toBe("Bash");
    expect(existsSync(join(workdir, "once.txt"))).toBe(false);

    const resumed = await agent.resumePermission("allow_once");
    expect(resumed).toBe("done");
    expect(existsSync(join(workdir, "once.txt"))).toBe(true);
    expect(agent.activePermissionRequest).toBeNull();
    expect(agent.audit.events.some((event) => event.extra.decision === "need_approval")).toBe(true);
  });

  test("allow_session reuses the rule for the same command prefix", async () => {
    const { agent } = await startAgent([
      toolResponse("t1", "Bash", { command: "echo hi > session.txt" }),
      toolResponse("t2", "Bash", { command: "echo hi > session2.txt" }),
      textResponse("done twice"),
    ]);

    await agent.run("first");
    expect(agent.activePermissionRequest).not.toBeNull();
    await agent.resumePermission("allow_session");
    expect(agent.activePermissionRequest).toBeNull();
    expect(existsSync(join(workdir, "session.txt"))).toBe(true);
    expect(existsSync(join(workdir, "session2.txt"))).toBe(true);
  });

  test("reject returns an error tool result without executing", async () => {
    const { agent, llm } = await startAgent([
      toolResponse("t1", "Bash", { command: "echo nope > rejected.txt" }),
      textResponse("rejected"),
    ]);

    await agent.run("try");
    const answer = await agent.resumePermission("reject" as PermissionChoice);
    expect(answer).toBe("rejected");
    expect(existsSync(join(workdir, "rejected.txt"))).toBe(false);

    const toolResult = llm.calls[1]!.messages.at(-1)!.content[0]!;
    expect(toolResult).toMatchObject({
      type: "tool_result",
      is_error: true,
    });
    expect(String((toolResult as { content: string }).content)).toContain("User rejected");
  });
});

describe("audit logger", () => {
  test("records events and summarizes them", () => {
    const dir = join(workdir, "audit");
    const logger = new AuditLogger(dir, true);
    logger.record(
      AuditEventFactory.policy("Bash", "ls", { decision: "need_approval" }),
    );
    logger.record(AuditEventFactory.policy("Bash", "rm", { decision: "deny" }));
    logger.record(AuditEventFactory.sandbox("Bash", "ls"));

    const summary = logger.summary();
    expect(summary.total_events).toBe(3);
    expect(summary.policy_need_approval).toBe(1);
    expect(summary.policy_denied).toBe(1);
    expect(summary.sandbox_executions).toBe(1);
    expect(logger.query({ event_type: "policy_decision" })).toHaveLength(2);
    expect(existsSync(logger.logFile!)).toBe(true);
  });
});

const AuditEventFactory = {
  policy(tool: string, summary: string, extra: Record<string, unknown>) {
    return AuditEvent.policyDecision(tool, summary, extra);
  },
  sandbox(tool: string, summary: string) {
    return AuditEvent.sandboxExec(tool, summary);
  },
};
