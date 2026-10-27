import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { Server } from "bun";

const tsDir = join(import.meta.dir, "..");
let home: string;
let workdir: string;
let server: Server<unknown> | null = null;

beforeEach(() => {
  home = mkdtempSync(join(tmpdir(), "bourbon-cli-home-"));
  workdir = mkdtempSync(join(tmpdir(), "bourbon-cli-work-"));
  mkdirSync(join(home, ".bourbon"), { recursive: true });
});

afterEach(() => {
  server?.stop(true);
  server = null;
  rmSync(home, { recursive: true, force: true });
  rmSync(workdir, { recursive: true, force: true });
});

async function spawnCli(
  args: string[],
  stdinText?: string,
): Promise<{ stdout: string; stderr: string; exitCode: number }> {
  const proc = Bun.spawn([process.execPath, "run", "src/index.ts", ...args], {
    cwd: tsDir,
    env: { ...process.env, HOME: home },
    stdin: stdinText === undefined ? "ignore" : "pipe",
    stdout: "pipe",
    stderr: "pipe",
  });

  if (stdinText !== undefined && proc.stdin) {
    proc.stdin.write(stdinText);
    proc.stdin.end();
  }

  const [stdout, stderr, exitCode] = await Promise.all([
    new Response(proc.stdout).text(),
    new Response(proc.stderr).text(),
    proc.exited,
  ]);
  return { stdout, stderr, exitCode };
}

function writeConfig(extra = ""): void {
  writeFileSync(
    join(home, ".bourbon", "config.toml"),
    `[llm]
default_provider = "anthropic"

[llm.anthropic]
api_key = "fake-key"
model = "mock-model"
base_url = "http://127.0.0.1:1"

[sandbox]
enabled = false

[audit]
enabled = false

[memory]
enabled = true
${extra}
`,
  );
}

function writeSkill(): void {
  const directory = join(workdir, ".agents", "skills", "demo-skill");
  mkdirSync(directory, { recursive: true });
  writeFileSync(
    join(directory, "SKILL.md"),
    "---\nname: demo-skill\ndescription: Demo skill for CLI tests\n---\n\nUse this demo.\n",
  );
}

describe("CLI", () => {
  test("prints version and help", async () => {
    writeConfig();
    const version = await spawnCli(["--version"]);
    expect(version.stdout.trim()).toBe("0.1.0");
    expect(version.exitCode).toBe(0);

    const help = await spawnCli(["--help"]);
    expect(help.stdout).toContain("--session-id");
    expect(help.stdout).toContain("--resume-last");
  });

  test("handles slash commands interactively with piped input", async () => {
    writeConfig();
    writeSkill();

    const result = await spawnCli(
      ["-w", workdir],
      [
        "/help",
        "/skills",
        "/skill/demo-skill",
        "/todos",
        "/tasks",
        "/task",
        "/runs",
        "/run-show",
        "/run-stop",
        "/mcp",
        "/compact",
        "/tokens",
        "/unknown",
        "/clear",
        "/exit",
      ].join("\n") + "\n",
    );

    expect(result.exitCode).toBe(0);
    expect(result.stdout).toContain("Bourbon");
    expect(result.stdout).toContain("Available commands");
    expect(result.stdout).toContain("demo-skill");
    expect(result.stdout).toContain("Skill 'demo-skill' activated");
    expect(result.stdout).toContain("No todos.");
    expect(result.stdout).toContain("No workflow tasks.");
    expect(result.stdout).toContain("Usage: /task <id>");
    expect(result.stdout).toContain("No runtime jobs.");
    expect(result.stdout).toContain("MCP Server Status");
    expect(result.stdout).toContain("Context compressed.");
    expect(result.stdout).toContain("0 in / 0 out tokens");
    expect(result.stdout).toContain("Unknown command");
    expect(result.stdout).toContain("Conversation history cleared.");
    expect(result.stdout).toContain("Goodbye!");
    expect(existsSync(join(home, ".bourbon", "history", "bourbon_history_ts"))).toBe(true);
  });

  test("initializes a configuration", async () => {
    const result = await spawnCli(["--init"], "\n\n");
    expect(result.exitCode).toBe(0);
    expect(result.stdout).toContain("Configuration saved to:");
    expect(existsSync(join(home, ".bourbon", "config.toml"))).toBe(true);
    expect(readFileSync(join(home, ".bourbon", "config.toml"), "utf8")).toContain(
      "default_provider",
    );
  });

  test("prints one-shot answers through the Anthropic client", async () => {
    let capturedBody: Record<string, unknown> | null = null;
    server = Bun.serve({
      port: 0,
      async fetch(request) {
        capturedBody = (await request.json()) as Record<string, unknown>;
        const events = [
          [
            "message_start",
            {
              type: "message_start",
              message: {
                id: "msg_mock",
                type: "message",
                role: "assistant",
                model: "mock-model",
                content: [],
                stop_reason: null,
                stop_sequence: null,
                usage: { input_tokens: 11, output_tokens: 1 },
              },
            },
          ],
          [
            "content_block_start",
            {
              type: "content_block_start",
              index: 0,
              content_block: { type: "text", text: "" },
            },
          ],
          [
            "content_block_delta",
            {
              type: "content_block_delta",
              index: 0,
              delta: { type: "text_delta", text: "mock reply" },
            },
          ],
          ["content_block_stop", { type: "content_block_stop", index: 0 }],
          [
            "message_delta",
            {
              type: "message_delta",
              delta: { stop_reason: "end_turn", stop_sequence: null },
              usage: { output_tokens: 2 },
            },
          ],
          ["message_stop", { type: "message_stop" }],
        ];
        const body = `${events
          .map(([event, data]) => `event: ${event}\ndata: ${JSON.stringify(data)}\n`)
          .join("\n")}\n`;
        return new Response(body, {
          headers: { "content-type": "text/event-stream" },
        });
      },
    });

    writeConfig();
    // Point the client at the live mock server.
    const configPath = join(home, ".bourbon", "config.toml");
    const config = readFileSync(configPath, "utf8").replace(
      'base_url = "http://127.0.0.1:1"',
      `base_url = "http://127.0.0.1:${server.port}"`,
    );
    writeFileSync(configPath, config);

    writeSkill();
    writeFileSync(join(workdir, "AGENTS.md"), "# Rules\nBe terse.\n");

    const result = await spawnCli(["-w", workdir, "-p", "say hi"]);

    expect(result.exitCode, `stderr: ${result.stderr}`).toBe(0);
    expect(result.stdout).toContain("mock reply");
    expect(result.stdout.split("mock reply").length - 1).toBe(1);
    expect(capturedBody).not.toBeNull();
    expect(capturedBody!.model).toBe("mock-model");
    expect(String(capturedBody!.system)).toContain("demo-skill");
    expect(String(capturedBody!.system)).toContain("Be terse.");

    const sessionsDir = join(home, ".bourbon", "sessions");
    const projectDirs = readdirSync(sessionsDir);
    expect(projectDirs.length).toBe(1);
    const files = readdirSync(join(sessionsDir, projectDirs[0]!));
    const transcript = files.find((file) => file.endsWith(".jsonl"))!;
    const content = readFileSync(join(sessionsDir, projectDirs[0]!, transcript), "utf8");
    expect(content).toContain("say hi");
    expect(content).toContain("mock reply");
    expect(files.some((file) => file.endsWith(".meta.json"))).toBe(true);
  });
});
