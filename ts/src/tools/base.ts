import {
  existsSync,
  mkdirSync,
  readFileSync,
  realpathSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { dirname, isAbsolute, relative, resolve } from "node:path";
import type { Tool, ToolContext } from "./types";
import { optionalNumber, requireString } from "./types";

const MAX_OUTPUT = 50_000;
const DANGEROUS = ["rm -rf /", "sudo ", "shutdown", "reboot", "> /dev/sda", "mkfs."];

const READONLY_COMMANDS = new Set([
  "ls",
  "cat",
  "grep",
  "find",
  "echo",
  "pwd",
  "wc",
  "head",
  "tail",
  "stat",
  "diff",
  "sort",
  "uniq",
]);

const FORBIDDEN_ARGS: Record<string, Set<string>> = {
  find: new Set(["-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprintf", "-fls"]),
  sort: new Set(["-o", "--output"]),
  tail: new Set(["-f", "--follow"]),
};

export function truncate(text: string, limit: number = MAX_OUTPUT): string {
  if (text.length <= limit) return text;
  return `${text.slice(0, limit)}\n... (${text.length - limit} more chars)`;
}

function isInside(root: string, target: string): boolean {
  const rel = relative(root, target);
  return rel === "" || (!rel.startsWith("..") && !isAbsolute(rel));
}

export function safePath(requested: string, workdir: string): string {
  const root = resolve(workdir);
  const target = isAbsolute(requested) ? resolve(requested) : resolve(root, requested);

  if (!isInside(root, target)) {
    throw new Error(`Path escapes workspace: ${requested}`);
  }

  let ancestor = target;
  while (!existsSync(ancestor)) {
    const parent = dirname(ancestor);
    if (parent === ancestor) break;
    ancestor = parent;
  }

  const realRoot = realpathSync(root);
  const realAncestor = realpathSync(ancestor);
  if (!isInside(realRoot, realAncestor)) {
    throw new Error(`Path escapes workspace: ${requested}`);
  }

  return target;
}

export async function runBash(
  command: string,
  workdir: string,
  timeoutSeconds = 120,
  signal?: AbortSignal,
): Promise<string> {
  for (const pattern of DANGEROUS) {
    if (command.includes(pattern)) {
      return `Error: Dangerous command blocked (${pattern.trim()})`;
    }
  }

  const proc = Bun.spawn(["/bin/sh", "-c", command], {
    cwd: workdir,
    stdout: "pipe",
    stderr: "pipe",
  });

  let timedOut = false;
  const kill = () => {
    proc.kill(9);
  };
  const timer = setTimeout(() => {
    timedOut = true;
    kill();
  }, timeoutSeconds * 1000);
  signal?.addEventListener("abort", kill, { once: true });

  try {
    const [stdout, stderr] = await Promise.all([
      new Response(proc.stdout).text(),
      new Response(proc.stderr).text(),
    ]);
    await proc.exited;

    if (timedOut) return `Error: Timeout (${timeoutSeconds}s)`;
    if (signal?.aborted) return "Error: Cancelled";

    const output = (stdout + stderr).trim();
    if (!output) return "(no output)";
    return truncate(output);
  } catch (error) {
    return `Error: ${error instanceof Error ? error.message : String(error)}`;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", kill);
  }
}

function tokenize(command: string): string[] | null {
  const tokens: string[] = [];
  let current = "";
  let quote: '"' | "'" | null = null;

  for (let i = 0; i < command.length; i += 1) {
    const char = command[i]!;
    if (quote) {
      if (char === quote) {
        quote = null;
      } else if (char === "\\" && quote === '"' && i + 1 < command.length) {
        i += 1;
        current += command[i]!;
      } else {
        current += char;
      }
      continue;
    }
    if (char === "'" || char === '"') {
      quote = char;
      continue;
    }
    if (char === "\\" && i + 1 < command.length) {
      i += 1;
      current += command[i]!;
      continue;
    }
    if (/\s/.test(char)) {
      if (current) {
        tokens.push(current);
        current = "";
      }
      continue;
    }
    if (";|&><`$()".includes(char) || char === "\n") {
      return null;
    }
    current += char;
  }

  if (quote) return null;
  if (current) tokens.push(current);
  return tokens;
}

export function isReadonlyBash(command: string): boolean {
  const tokens = tokenize(command);
  if (!tokens?.length) return false;
  const head = tokens[0]!;
  if (head.includes("/") || !READONLY_COMMANDS.has(head)) return false;

  const forbidden = FORBIDDEN_ARGS[head] ?? new Set<string>();
  for (const arg of tokens.slice(1)) {
    if (forbidden.has(arg)) return false;
    for (const flag of forbidden) {
      if (flag.startsWith("--") && arg.startsWith(`${flag}=`)) return false;
    }
  }

  if (head === "uniq") {
    const operands = tokens.slice(1).filter((arg) => !arg.startsWith("-"));
    if (operands.length >= 2) return false;
  }

  return true;
}

function readFile(input: Record<string, unknown>, ctx: ToolContext): string {
  const path = requireString(input, "path");
  try {
    const filePath = safePath(path, ctx.workdir);
    if (!existsSync(filePath)) return `Error: File not found: ${path}`;
    if (!statSync(filePath).isFile()) return `Error: Not a file: ${path}`;

    const allLines = readFileSync(filePath, "utf8").split("\n");
    const total = allLines.length;
    const offset = optionalNumber(input, "offset");
    const limit = optionalNumber(input, "limit");

    const start = Math.max((offset ?? 1) - 1, 0);
    let lines = allLines.slice(start);

    if (limit !== undefined && limit >= 0 && limit < lines.length) {
      const remaining = lines.length - limit;
      lines = [...lines.slice(0, limit), `... (${remaining} more lines)`];
    } else if (start > 0) {
      lines = [...lines, `... (started at line ${start + 1} of ${total})`];
    }

    return truncate(lines.join("\n"));
  } catch (error) {
    return `Error reading ${path}: ${error instanceof Error ? error.message : String(error)}`;
  }
}

function writeFile(input: Record<string, unknown>, ctx: ToolContext): string {
  const path = requireString(input, "path");
  const content = requireString(input, "content");
  try {
    const filePath = safePath(path, ctx.workdir);
    mkdirSync(dirname(filePath), { recursive: true });
    writeFileSync(filePath, content);
    return `Wrote ${Buffer.byteLength(content)} bytes to ${path}`;
  } catch (error) {
    return `Error writing ${path}: ${error instanceof Error ? error.message : String(error)}`;
  }
}

function editFile(input: Record<string, unknown>, ctx: ToolContext): string {
  const path = requireString(input, "path");
  const oldText = requireString(input, "old_text");
  const newText = requireString(input, "new_text");
  try {
    const filePath = safePath(path, ctx.workdir);
    if (!existsSync(filePath)) return `Error: File not found: ${path}`;

    const content = readFileSync(filePath, "utf8");
    if (!content.includes(oldText)) return `Error: Text not found in ${path}`;

    writeFileSync(filePath, content.replace(oldText, newText));
    return `Edited ${path}`;
  } catch (error) {
    return `Error editing ${path}: ${error instanceof Error ? error.message : String(error)}`;
  }
}

export const bashTool: Tool = {
  name: "Bash",
  aliases: ["bash"],
  description: "Run a shell command in the workspace.",
  inputSchema: {
    type: "object",
    properties: {
      command: { type: "string", description: "Shell command to execute" },
    },
    required: ["command"],
  },
  riskLevel: "high",
  isDestructive: true,
  requiredCapabilities: ["exec"],
  isReadOnly: false,
  isConcurrencySafe: (input) =>
    typeof input.command === "string" && isReadonlyBash(input.command),
  run: (input, ctx) =>
    runBash(
      requireString(input, "command"),
      ctx.workdir,
      optionalNumber(input, "timeout") ?? 120,
      ctx.signal,
    ),
};

export const readTool: Tool = {
  name: "Read",
  aliases: ["read_file"],
  description: "Read the contents of a file.",
  inputSchema: {
    type: "object",
    properties: {
      path: { type: "string", description: "Path to the file (relative to workspace)" },
      limit: { type: "integer", description: "Maximum number of lines to read" },
      offset: { type: "integer", description: "1-indexed line number to start reading from" },
    },
    required: ["path"],
  },
  riskLevel: "low",
  isReadOnly: true,
  isConcurrencySafe: () => true,
  requiredCapabilities: ["file_read"],
  run: async (input, ctx) => readFile(input, ctx),
};

export const writeTool: Tool = {
  name: "Write",
  aliases: ["write_file"],
  description: "Write content to a file (creates directories if needed).",
  inputSchema: {
    type: "object",
    properties: {
      path: { type: "string", description: "Path to the file" },
      content: { type: "string", description: "Content to write" },
    },
    required: ["path", "content"],
  },
  riskLevel: "medium",
  isReadOnly: false,
  isConcurrencySafe: () => false,
  requiredCapabilities: ["file_write"],
  run: async (input, ctx) => writeFile(input, ctx),
};

export const editTool: Tool = {
  name: "Edit",
  aliases: ["edit_file"],
  description: "Replace exact text in a file (only first occurrence).",
  inputSchema: {
    type: "object",
    properties: {
      path: { type: "string", description: "Path to the file" },
      old_text: { type: "string", description: "Text to find" },
      new_text: { type: "string", description: "Text to replace with" },
    },
    required: ["path", "old_text", "new_text"],
  },
  riskLevel: "medium",
  isReadOnly: false,
  isConcurrencySafe: () => false,
  requiredCapabilities: ["file_write"],
  run: async (input, ctx) => editFile(input, ctx),
};
