import pc from "picocolors";

export function summarizeInput(name: string, input: Record<string, unknown>): string {
  const path = typeof input.path === "string" ? input.path : "";
  switch (name) {
    case "Bash":
      return String(input.command ?? "");
    case "Read":
    case "Write":
    case "Edit":
    case "PdfRead":
    case "DocxRead":
    case "CsvAnalyze":
    case "JsonQuery":
      return path;
    case "Grep":
      return `/${String(input.pattern ?? "")}/ ${path}`.trim();
    case "Glob":
      return `${String(input.pattern ?? "")} ${path}`.trim();
    case "Agent":
      return `${String(input.subagent_type ?? "default")}: ${String(input.description ?? "")}`;
    default: {
      const json = JSON.stringify(input);
      return json.length > 100 ? `${json.slice(0, 100)}...` : json;
    }
  }
}

export function toolStartLine(name: string, input: Record<string, unknown>): string {
  return `${pc.dim("▶")} ${pc.bold(name)} ${pc.dim(summarizeInput(name, input))}`;
}

export function toolEndLine(name: string, output: string, isError: boolean): string {
  const firstLine = output.split("\n").find((line) => line.trim().length > 0) ?? output;
  const preview = firstLine.length > 120 ? `${firstLine.slice(0, 120)}...` : firstLine;
  const lineCount = output.split("\n").length;
  const suffix = lineCount > 1 ? pc.dim(` (${lineCount} lines)`) : "";
  return isError || output.startsWith("Error")
    ? `${pc.red("✗")} ${pc.red(`${name}: ${preview}`)}${suffix}`
    : `${pc.green("✓")} ${pc.green(`${name}: ${preview}`)}${suffix}`;
}

export function usageLine(inputTokens: number, outputTokens: number): string {
  return pc.dim(
    `· ${inputTokens.toLocaleString()} in / ${outputTokens.toLocaleString()} out tokens`,
  );
}

export function contextLine(tokens: number, threshold: number): string {
  const percent = threshold > 0 ? Math.min(100, (tokens / threshold) * 100) : 0;
  const text = `context: ${percent.toFixed(1)}% (${(tokens / 1000).toFixed(1)}k/${(threshold / 1000).toFixed(1)}k)`;
  if (percent < 50) return pc.dim(text);
  if (percent < 80) return pc.yellow(text);
  return pc.red(text);
}

const FRAMES = ["[     ]", "[=    ]", "[==   ]", "[===  ]", "[==== ]", "[=====]"];

export class ActivitySpinner {
  private timer: ReturnType<typeof setInterval> | null = null;
  private frame = 0;
  private startedAt = 0;

  constructor(private readonly enabled: boolean) {}

  start(): void {
    if (!this.enabled || this.timer) return;
    this.startedAt = Date.now();
    this.timer = setInterval(() => {
      const label = Date.now() - this.startedAt > 800 ? "Bourbon is replying..." : "Bourbon is thinking...";
      const frame = FRAMES[this.frame % FRAMES.length]!;
      this.frame += 1;
      process.stdout.write(`\r${pc.dim(`${frame} ${label}`)}`);
    }, 150);
  }

  stop(): void {
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = null;
      process.stdout.write("\r\x1b[2K");
    }
  }
}

export function helpText(): string {
  return `Available commands:
  /exit, /quit        Exit the REPL
  /compact            Manually compress context
  /todos              Show legacy in-memory todo list
  /tasks              Show persistent workflow tasks
  /task <id>          Show one workflow task
  /runs               List subagent runtime jobs
  /run-show <id>      Show one subagent runtime job output
  /run-stop <id>      Stop a running subagent runtime job
  /skills             List available skills
  /mcp                Show MCP server status
  /tokens             Show token usage
  /clear              Clear conversation history
  /help               Show this help
  /skill/name         Activate a skill

All other input is sent to the AI agent.`;
}

export const BANNER = `${pc.bold("Bourbon")} - General-Purpose Agent
Type your message or use /help for commands.
Use Ctrl+D or /exit to quit.`;
