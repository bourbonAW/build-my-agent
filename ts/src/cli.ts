import { existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { createInterface } from "node:readline";
import { Writable } from "node:stream";
import pc from "picocolors";
import { Agent } from "./agent/agent";
import type { AgentCallbacks } from "./agent/agent";
import { CONFIG_PATH, loadConfig, writeDefaultConfig } from "./config";
import { MarkdownStream, renderMarkdown } from "./markdown";
import { createTranscriptMessage } from "./session/types";
import { StatusBar } from "./status";
import { TaskService } from "./tasks/service";
import { TaskStore } from "./tasks/store";
import {
  ActivitySpinner,
  BANNER,
  contextLine,
  helpText,
  toolEndLine,
  toolStartLine,
  usageLine,
} from "./render";

export const VERSION = "0.1.0";

export const HELP = `Bourbon (TypeScript) ${VERSION}

Usage:
  bourbon-ts [options] [prompt]

Options:
  --init             Initialize configuration
  --session-id ID    Resume a specific session
  --resume-last      Resume the most recent session for this workdir
  -p, --print        Run one prompt non-interactively and exit
  -w, --workdir DIR  Workspace directory (default: current directory)
  -h, --help         Show this help
  -v, --version      Show version
`;

export interface RunOptions {
  workdir: string;
  sessionId?: string;
  resumeLast?: boolean;
}

class LineQueue {
  private readonly buffer: string[] = [];
  private readonly waiters: Array<(line: string | null) => void> = [];
  private closed = false;

  push(line: string): void {
    if (this.closed) return;
    const waiter = this.waiters.shift();
    if (waiter) {
      waiter(line);
      return;
    }
    this.buffer.push(line);
  }

  close(): void {
    this.closed = true;
    for (const waiter of this.waiters.splice(0)) waiter(null);
  }

  next(): Promise<string | null> {
    const line = this.buffer.shift();
    if (line !== undefined) return Promise.resolve(line);
    if (this.closed) return Promise.resolve(null);
    return new Promise((resolvePromise) => this.waiters.push(resolvePromise));
  }
}

interface StreamDisplay {
  start(): void;
  endLine(): void;
  onText(text: string): void;
  onToolStart(name: string, input: Record<string, unknown>): void;
  onToolEnd(name: string, output: string, isError: boolean): void;
  spinner: ActivitySpinner;
}

function useTerminalMarkdown(): boolean {
  return Boolean(process.stdout.isTTY) && process.env.BOURBON_PLAIN !== "1";
}

function terminalWidth(): number {
  return Math.max(20, (process.stdout.columns ?? 80) - 1);
}

function createDisplay(
  enabledSpinner: boolean,
  status: StatusBar,
  refreshStatus: () => void,
): StreamDisplay {
  const spinner = new ActivitySpinner(enabledSpinner && !status.enabled);
  const markdown = useTerminalMarkdown();
  let stream: MarkdownStream | null = null;
  let rawLineOpen = false;
  let textPrinted = false;

  const finishStream = () => {
    if (!stream) return;
    stream.finish();
    stream = null;
  };

  const separate = () => {
    finishStream();
    if (rawLineOpen) {
      process.stdout.write("\n");
      rawLineOpen = false;
    }
    if (textPrinted) {
      process.stdout.write("\n");
      textPrinted = false;
    }
  };

  return {
    spinner,
    start() {
      if (status.enabled) {
        status.setActivity("thinking");
        return;
      }
      spinner.start();
    },
    endLine() {
      spinner.stop();
      separate();
      status.stopActivity();
      refreshStatus();
    },
    onText(text) {
      if (!text) return;
      spinner.stop();
      status.setActivity("replying");
      textPrinted = true;
      if (!markdown) {
        if (!rawLineOpen) {
          process.stdout.write("\n");
          rawLineOpen = true;
        }
        process.stdout.write(text);
        return;
      }
      if (!stream) {
        process.stdout.write("\n");
        stream = new MarkdownStream(process.stdout, { width: terminalWidth });
      }
      stream.push(text);
    },
    onToolStart(name, input) {
      spinner.stop();
      status.setActivity(`Running ${name}`);
      refreshStatus();
      separate();
      process.stdout.write(`${toolStartLine(name, input)}\n`);
    },
    onToolEnd(name, output, isError) {
      status.setActivity("thinking");
      process.stdout.write(`${toolEndLine(name, output, isError)}\n`);
    },
  };
}

function callbacksFor(display: StreamDisplay): AgentCallbacks {
  return {
    onText: (text) => display.onText(text),
    onToolStart: (name, input) => display.onToolStart(name, input),
    onToolEnd: (name, output, isError) => display.onToolEnd(name, output, isError),
  };
}

function buildAgent(options: RunOptions, callbacks: AgentCallbacks): Agent {
  const config = loadConfig();
  return new Agent({
    config,
    workdir: options.workdir,
    callbacks,
    ...(options.sessionId ? { sessionId: options.sessionId } : {}),
    ...(options.resumeLast ? { resumeLast: options.resumeLast } : {}),
  });
}

function resolveWorkdir(requested: string | undefined): string {
  const workdir = resolve(requested ?? process.cwd());
  if (!existsSync(workdir) || !statSync(workdir).isDirectory()) {
    throw new Error(`Workdir does not exist: ${workdir}`);
  }
  return workdir;
}

function printError(error: unknown): void {
  process.stderr.write(
    `${pc.red("Error:")} ${error instanceof Error ? error.message : String(error)}\n`,
  );
}

async function getGitBranch(workdir: string): Promise<string | undefined> {
  try {
    const proc = Bun.spawn(["git", "-C", workdir, "rev-parse", "--abbrev-ref", "HEAD"], {
      stdout: "pipe",
      stderr: "pipe",
    });
    const timer = setTimeout(() => proc.kill(9), 1500);
    try {
      const [stdout, , code] = await Promise.all([
        new Response(proc.stdout).text(),
        new Response(proc.stderr).text(),
        proc.exited,
      ]);
      if (code !== 0) return undefined;
      const branch = stdout.trim();
      return branch && branch !== "HEAD" ? branch : undefined;
    } finally {
      clearTimeout(timer);
    }
  } catch {
    return undefined;
  }
}

async function initializeMcp(
  agent: Agent,
  out: NodeJS.WriteStream = process.stdout,
): Promise<void> {
  if (!agent.config.mcp.enabled) return;
  await agent.initializeMCP();
  const summary = agent.mcp.getConnectionSummary();
  if (summary.connected > 0) {
    out.write(
      `${pc.dim(`MCP: Connected to ${summary.connected} server(s), ${summary.totalTools} tool(s) available`)}\n`,
    );
  }
  if (summary.failed > 0) {
    out.write(`${pc.yellow(`MCP: ${summary.failed} server(s) failed to connect`)}\n`);
    for (const [name, status] of Object.entries(summary.servers)) {
      if (!status.connected) {
        out.write(`${pc.yellow(`  ${name}: ${status.error ?? "unknown error"}`)}\n`);
      }
    }
  }
}

export async function runPrint(prompt: string, options: RunOptions): Promise<number> {
  const callbacks: AgentCallbacks = {
    onText: () => {},
    onToolStart: (name, input) => {
      process.stderr.write(`${toolStartLine(name, input)}\n`);
    },
    onToolEnd: (name, output, isError) => {
      process.stderr.write(`${toolEndLine(name, output, isError)}\n`);
    },
  };

  let agent: Agent;
  try {
    agent = buildAgent(options, callbacks);
  } catch (error) {
    printError(error);
    return 1;
  }

  const controller = new AbortController();
  const onSigint = () => controller.abort();
  process.on("SIGINT", onSigint);

  try {
    await initializeMcp(agent, process.stderr);
    let answer = await agent.run(prompt, controller.signal);

    while (agent.activePermissionRequest) {
      process.stderr.write(
        `${pc.yellow("Permission required:")} ${agent.activePermissionRequest.description}\n`,
      );
      answer += await agent.resumePermission("reject", controller.signal);
    }

    const rendered = useTerminalMarkdown()
      ? renderMarkdown(answer, { width: terminalWidth() })
      : answer;
    process.stdout.write(`${rendered}\n`);
    return 0;
  } catch (error) {
    if (controller.signal.aborted) {
      process.stderr.write(`${pc.dim("Cancelled.")}\n`);
      return 130;
    }
    printError(error);
    return 1;
  } finally {
    process.off("SIGINT", onSigint);
    await agent.shutdown();
  }
}

function historyPath(): string {
  return join(homedir(), ".bourbon", "history", "bourbon_history_ts");
}

function loadHistory(): string[] {
  try {
    const lines = readFileSync(historyPath(), "utf8")
      .split("\n")
      .filter(Boolean);
    return lines.slice(-500).reverse();
  } catch {
    return [];
  }
}

function saveHistory(history: string[]): void {
  try {
    mkdirSync(dirname(historyPath()), { recursive: true });
    writeFileSync(historyPath(), [...history].reverse().join("\n") + (history.length ? "\n" : ""), {
      mode: 0o600,
    });
  } catch {
    // history is best-effort
  }
}

async function handlePermissionRequest(
  agent: Agent,
  queue: LineQueue,
  signal: AbortSignal,
  display: StreamDisplay,
): Promise<void> {
  while (agent.activePermissionRequest) {
    const request = agent.activePermissionRequest;
    process.stdout.write(
      `\n${pc.bold(pc.yellow(request.title))}\n${pc.dim("━".repeat(50))}\n` +
        `${pc.bold("Tool:")} ${request.toolName}\n` +
        `${pc.bold("Reason:")} ${request.reason}\n` +
        `${pc.bold("Summary:")} ${request.description}\n\n` +
        `  ${pc.bold("[1]")} Allow once\n` +
        `  ${pc.bold("[2]")} Allow for session\n` +
        `  ${pc.bold("[3]")} Reject\n\n` +
        `Enter your choice: `,
    );

    let choice: "allow_once" | "allow_session" | "reject" | null = null;
    while (!choice) {
      const line = await queue.next();
      if (line === null) {
        await agent.resumePermission("reject", signal);
        return;
      }
      const value = line.trim();
      if (value === "1") choice = "allow_once";
      else if (value === "2") choice = "allow_session";
      else if (value === "3") choice = "reject";
      else process.stdout.write(`${pc.red("Invalid choice. Please try again.")}\nEnter your choice: `);
    }

    display.start();
    await agent.resumePermission(choice, signal);
    display.endLine();
  }
}

function taskServiceFor(agent: Agent): { service: TaskService; listId: string } {
  const storageDir = agent.config.tasks.storageDir.replace(/^~(?=\/|$)/, homedir());
  return {
    service: new TaskService(new TaskStore(storageDir)),
    listId: agent.session.sessionId ?? agent.config.tasks.defaultListId,
  };
}

function handleSlashCommand(
  command: string,
  agent: Agent,
): { exit: boolean; handled: boolean } {
  const [baseRaw, ...rest] = command.split(/\s+/);
  const base = baseRaw!.toLowerCase();
  const arg = rest.join(" ").trim();

  if (base.startsWith("/skill/")) {
    const skillName = command.slice("/skill/".length).trim();
    if (!skillName) {
      process.stdout.write(`${pc.red("Usage: /skill/skill-name")}\n`);
      return { exit: false, handled: true };
    }
    try {
      const content = agent.skills.activate(skillName);
      process.stdout.write(`${pc.green(`✓ Skill '${skillName}' activated`)}\n`);
      agent.session.addMessage(
        createTranscriptMessage("user", [
          { type: "text", text: `[User activated skill: ${skillName}]\n\n${content}` },
        ]),
      );
      agent.session.save();
      process.stdout.write(`${pc.dim("Skill instructions loaded into context.")}\n`);
    } catch (error) {
      printError(error);
    }
    return { exit: false, handled: true };
  }

  switch (base) {
    case "/exit":
    case "/quit":
      process.stdout.write(`${pc.dim("Goodbye!")}\n`);
      return { exit: true, handled: true };
    case "/compact": {
      const result = agent.manualCompact();
      process.stdout.write(
        result?.success
          ? `${pc.dim(`Context compressed: ${result.archivedCount} messages archived.`)}\n`
          : `${pc.dim("Context compressed.")}\n`,
      );
      return { exit: false, handled: true };
    }
    case "/todos":
      process.stdout.write(`${agent.getTodos()}\n`);
      return { exit: false, handled: true };
    case "/tasks": {
      try {
        const { service, listId } = taskServiceFor(agent);
        const records = service.listTasks(listId);
        if (!records.length) {
          process.stdout.write("No workflow tasks.\n");
        } else {
          for (const record of records) {
            let line = `${record.id}. [${record.status}] ${record.subject}`;
            if (record.activeForm) line += ` <- ${record.activeForm}`;
            if (record.owner) line += ` (owner: ${record.owner})`;
            if (record.blockedBy.length) line += ` blocked_by=${record.blockedBy.join(",")}`;
            process.stdout.write(`${line}\n`);
          }
        }
      } catch (error) {
        printError(error);
      }
      return { exit: false, handled: true };
    }
    case "/task":
    case "/task-show": {
      if (!arg) {
        process.stdout.write(`${pc.red(`Usage: ${base} <id>`)}\n`);
        return { exit: false, handled: true };
      }
      try {
        const { service, listId } = taskServiceFor(agent);
        const record = service.getTask(listId, arg);
        if (!record) {
          process.stdout.write(`Task not found: ${arg}\n`);
        } else {
          process.stdout.write(
            `ID: ${record.id}\nSubject: ${record.subject}\nDescription: ${record.description}\n` +
              `Status: ${record.status}\nActive: ${record.activeForm ?? "-"}\n` +
              `Owner: ${record.owner ?? "-"}\nBlocks: ${record.blocks.join(", ") || "-"}\n` +
              `Blocked by: ${record.blockedBy.join(", ") || "-"}\n`,
          );
        }
      } catch (error) {
        printError(error);
      }
      return { exit: false, handled: true };
    }
    case "/runs":
      process.stdout.write(`${agent.subagentManager.renderRunList()}\n`);
      return { exit: false, handled: true };
    case "/run-show":
      process.stdout.write(
        `${arg ? agent.subagentManager.getRunOutput(arg) : pc.red("Usage: /run-show <id>")}\n`,
      );
      return { exit: false, handled: true };
    case "/run-stop":
      process.stdout.write(
        `${arg ? agent.subagentManager.stopRun(arg) : pc.red("Usage: /run-stop <id>")}\n`,
      );
      return { exit: false, handled: true };
    case "/skills": {
      const skills = agent.skills.availableSkills;
      if (!skills.length) {
        process.stdout.write(`${pc.dim("No skills available.")}\n`);
      } else {
        process.stdout.write(`${pc.bold("Available skills:")}\n`);
        for (const name of [...skills].sort()) {
          const skill = agent.skills.getSkill(name);
          process.stdout.write(`  • ${pc.bold(name)}: ${skill?.description ?? ""}\n`);
        }
      }
      return { exit: false, handled: true };
    }
    case "/mcp": {
      const summary = agent.mcp.getConnectionSummary();
      if (!summary.enabled) {
        process.stdout.write(`${pc.dim("MCP is disabled.")}\n`);
        return { exit: false, handled: true };
      }
      process.stdout.write(
        `${pc.bold("MCP Server Status:")}\n  Enabled: ${summary.enabled}\n  Configured: ${summary.configured} server(s)\n` +
          `  Connected: ${summary.connected} server(s)\n  Failed: ${summary.failed} server(s)\n  Total Tools: ${summary.totalTools}\n`,
      );
      for (const [name, status] of Object.entries(summary.servers)) {
        process.stdout.write(
          status.connected
            ? `  • ${pc.green(name)}: Connected (${status.tools} tools)\n`
            : `  • ${pc.red(name)}: Failed - ${status.error ?? "unknown error"}\n`,
        );
      }
      const tools = agent.mcp.listMcpTools();
      if (tools.length) {
        process.stdout.write(`${pc.bold("Available MCP Tools:")}\n`);
        for (const tool of tools.sort()) process.stdout.write(`  • ${tool}\n`);
      }
      return { exit: false, handled: true };
    }
    case "/tokens":
      process.stdout.write(
        `${usageLine(agent.usage.inputTokens, agent.usage.outputTokens)}\n` +
          `${contextLine(agent.getSessionTokens(), agent.session.contextManager.tokenThreshold)}\n`,
      );
      return { exit: false, handled: true };
    case "/clear":
      agent.clearHistory();
      process.stdout.write(`${pc.dim("Conversation history cleared.")}\n`);
      return { exit: false, handled: true };
    case "/help":
      process.stdout.write(`${helpText()}\n`);
      return { exit: false, handled: true };
    default:
      process.stdout.write(`${pc.red(`Unknown command: ${command}`)}\nType /help for available commands.\n`);
      return { exit: false, handled: true };
  }
}

export async function runRepl(options: RunOptions): Promise<number> {
  const status = new StatusBar();
  let agentForStatus: Agent | null = null;
  const refreshStatus = () => {
    if (!agentForStatus) return;
    status.update({
      inputTokens: agentForStatus.usage.inputTokens,
      outputTokens: agentForStatus.usage.outputTokens,
      contextTokens: agentForStatus.getSessionTokens(),
      contextLimit: agentForStatus.session.contextManager.tokenThreshold,
    });
  };
  const display = createDisplay(Boolean(process.stdin.isTTY), status, refreshStatus);
  let agent: Agent;
  try {
    agent = buildAgent(options, callbacksFor(display));
    agentForStatus = agent;
  } catch (error) {
    printError(error);
    return 1;
  }

  const history = loadHistory();
  // Readline redraws itself on output "resize" and erases everything below the
  // prompt, which would fight the fixed footer. It still reads live columns on
  // each refresh; only the spontaneous resize redraw is suppressed.
  const readlineOutput = new Writable({
    write(chunk, _encoding, callback) {
      process.stdout.write(chunk);
      callback();
    },
  });
  Object.defineProperties(readlineOutput, {
    isTTY: { get: () => Boolean(process.stdout.isTTY) },
    columns: { get: () => process.stdout.columns },
    rows: { get: () => process.stdout.rows },
  });
  const rl = createInterface({
    input: process.stdin,
    output: readlineOutput,
    terminal: Boolean(process.stdin.isTTY),
    historySize: 200,
    history,
  });

  let closed = false;
  const queue = new LineQueue();
  rl.on("line", (line) => queue.push(line));
  rl.on("close", () => {
    closed = true;
    queue.close();
  });

  let activeController: AbortController | null = null;
  rl.on("SIGINT", () => {
    if (activeController) {
      activeController.abort();
      return;
    }
    process.stdout.write("\n");
    rl.close();
  });

  let footerSuspended = false;
  let ready = false;
  let resizeTimer: ReturnType<typeof setTimeout> | null = null;

  const prompt = () => {
    if (closed) return;
    refreshStatus();
    if (footerSuspended && status.resume()) footerSuspended = false;
    status.preparePrompt();
    rl.prompt();
    status.redraw();
  };

  const onStdinData = () => {
    setImmediate(() => status.redraw());
  };
  if (status.enabled) process.stdin.on("data", onStdinData);

  const onResize = () => {
    if (resizeTimer) clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      resizeTimer = null;
      if (activeController || closed || !ready) {
        status.resize();
        return;
      }
      if (status.enabled && rl.line.length > 0) {
        status.dispose();
        footerSuspended = true;
        return;
      }
      if (footerSuspended && status.resume()) footerSuspended = false;
      if (status.isAttached) {
        process.stdout.write(`\x1b[${status.promptRow()};1H\x1b[2K`);
      }
      status.resize();
      status.preparePrompt();
      rl.prompt(true);
      status.redraw();
    }, 60);
  };
  process.stdout.on("resize", onResize);

  process.stdout.write(`${BANNER}\n\n`);
  await initializeMcp(agent);

  if (!status.enabled) {
    process.stdout.write(`${pc.dim(`Model: ${agent.model} · Workdir: ${agent.workdir}`)}\n\n`);
  } else {
    const branch = await getGitBranch(agent.workdir);
    status.attach({
      model: agent.model,
      cwd: agent.workdir,
      ...(branch ? { branch } : {}),
      inputTokens: agent.usage.inputTokens,
      outputTokens: agent.usage.outputTokens,
      contextTokens: agent.getSessionTokens(),
      contextLimit: agent.session.contextManager.tokenThreshold,
    });
  }

  rl.setPrompt(pc.green("🥃 bourbon >> "));
  prompt();
  ready = true;

  try {
    while (true) {
      const line = await queue.next();
      if (line === null) break;
      const input = line.trim();
      if (!input) {
        prompt();
        continue;
      }

      if (input.startsWith("/")) {
        const outcome = handleSlashCommand(input, agent);
        if (outcome.exit) break;
        prompt();
        continue;
      }

      const controller = new AbortController();
      activeController = controller;
      display.endLine();
      display.start();

      try {
        await agent.run(input, controller.signal);
        display.endLine();

        if (agent.activePermissionRequest) {
          await handlePermissionRequest(agent, queue, controller.signal, display);
          display.endLine();
        }

        if (!status.enabled) {
          process.stdout.write(
            `${usageLine(agent.usage.inputTokens, agent.usage.outputTokens)}\n` +
              `${contextLine(agent.getSessionTokens(), agent.session.contextManager.tokenThreshold)}\n\n`,
          );
        }
      } catch (error) {
        display.spinner.stop();
        display.endLine();
        if (controller.signal.aborted) {
          process.stdout.write(`${pc.dim("Cancelled.")}\n\n`);
        } else {
          printError(error);
          process.stdout.write("\n");
        }
      } finally {
        activeController = null;
        if (!history.includes(input)) {
          history.unshift(input);
          if (history.length > 500) history.pop();
        }
      }

      prompt();
    }
  } finally {
    if (resizeTimer) clearTimeout(resizeTimer);
    process.stdout.off("resize", onResize);
    if (status.enabled) process.stdin.off("data", onStdinData);
    status.dispose();
    saveHistory(history);
    rl.close();
    await agent.shutdown();
  }

  return 0;
}

export async function initConfig(): Promise<number> {
  process.stdout.write(`${pc.bold("Bourbon Configuration Setup")}\n\n`);

  const tty = Boolean(process.stdin.isTTY);
  const rl = createInterface({ input: process.stdin, output: process.stdout, terminal: tty });
  const queue = new LineQueue();
  rl.on("line", (line) => queue.push(line));
  rl.on("close", () => queue.close());

  const ask = async (question: string): Promise<string> => {
    process.stdout.write(question);
    return (await queue.next() ?? "").trim();
  };

  const askHidden = async (question: string): Promise<string> => {
    if (tty) Bun.spawnSync(["stty", "-echo"]);
    const answer = await ask(question);
    if (tty) {
      Bun.spawnSync(["stty", "echo"]);
      process.stdout.write("\n");
    }
    return answer;
  };

  try {
    if (existsSync(CONFIG_PATH)) {
      const answer = await ask("Configuration already exists. Overwrite? [y/N] ");
      if (answer.toLowerCase() !== "y") {
        process.stdout.write(`${pc.dim("Setup cancelled.")}\n`);
        return 0;
      }
    }

    const anthropicKey = await askHidden("Anthropic API key (press Enter to skip): ");
    const openaiKey = await askHidden("OpenAI API key (press Enter to skip): ");

    writeDefaultConfig(anthropicKey, openaiKey);
    process.stdout.write(`\n${pc.green("Configuration saved to:")} ${CONFIG_PATH}\n`);
    if (anthropicKey) process.stdout.write(`${pc.green("✓")} Anthropic configured\n`);
    if (openaiKey) process.stdout.write(`${pc.green("✓")} OpenAI configured\n`);
    if (!anthropicKey && !openaiKey) {
      process.stdout.write(
        `${pc.yellow("⚠ No API keys configured.")}\nRun --init again to add keys.\n`,
      );
    }
    return 0;
  } finally {
    rl.close();
  }
}

export { resolveWorkdir };
