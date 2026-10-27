import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { ContextInjector } from "../src/prompt/context";
import { PromptBuilder } from "../src/prompt/builder";
import { buildSystemPrompt } from "../src/prompt";
import type { PromptContext } from "../src/prompt/types";

let workdir: string;

beforeEach(() => {
  workdir = mkdtempSync(join(tmpdir(), "bourbon-prompt-"));
});

afterEach(() => {
  rmSync(workdir, { recursive: true, force: true });
});

describe("prompt builder", () => {
  test("orders sections and supports custom prompts", async () => {
    const builder = new PromptBuilder([
      { name: "late", order: 20, content: "LATE" },
      { name: "early", order: 10, content: "EARLY" },
    ]);
    const ctx: PromptContext = { workdir };
    expect(await builder.build(ctx)).toBe("EARLY\n\nLATE");

    const custom = new PromptBuilder([], "CUSTOM", "APPENDED");
    expect(await custom.build(ctx)).toBe("CUSTOM\n\nAPPENDED");
  });

  test("injects AGENTS.md and USER.md anchors", async () => {
    writeFileSync(join(workdir, "AGENTS.md"), "# Rules\nAlways run tests.\n");
    writeFileSync(join(workdir, "USER.md"), "# Preferences\nUse TypeScript.\n");

    const prompt = await buildSystemPrompt({
      workdir,
      memoryManager: { getMemoryDir: () => join(workdir, ".memory") },
      memoryConfig: { memoryMdTokenLimit: 1200, userMdTokenLimit: 600 },
    });

    expect(prompt).toContain("# Project Instructions (AGENTS.md)");
    expect(prompt).toContain("Always run tests.");
    expect(prompt).toContain("# User Preferences (USER.md)");
    expect(prompt).toContain("Use TypeScript.");
    expect(prompt.indexOf("You are Bourbon")).toBeLessThan(
      prompt.indexOf("# Project Instructions"),
    );
  });

  test("adds skills and MCP catalogs last", async () => {
    const prompt = await buildSystemPrompt({
      workdir,
      skillManager: {
        getCatalog: () => "<available_skills>\n  <skill>demo</skill>\n</available_skills>",
      },
      mcpManager: {
        getConnectionSummary: () => ({ enabled: true, totalTools: 2 }),
        listMcpTools: () => ["alpha-echo", "alpha-time", "beta-fetch"],
        serverNames: () => ["alpha", "beta"],
      },
    });

    expect(prompt).toContain("SKILLS");
    expect(prompt).toContain("<available_skills>");
    expect(prompt).toContain("MCP TOOLS");
    expect(prompt).toContain("    - alpha-echo");
    expect(prompt).toContain("  beta:");
    expect(prompt.indexOf("SKILLS")).toBeLessThan(prompt.indexOf("MCP TOOLS"));
  });

  test("injects environment context before the user message", async () => {
    const injected = await new ContextInjector().inject("hello", { workdir });
    expect(injected).toContain("<system-reminder>");
    expect(injected).toContain(`Working directory: ${workdir}`);
    expect(injected.endsWith("hello")).toBe(true);
  });
});
