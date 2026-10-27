import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { homedir } from "node:os";
import { isAbsolute, join, relative } from "node:path";
import type { Tool, ToolContext } from "./types";
import { optionalBoolean, optionalString, requireString } from "./types";
import { safePath, truncate } from "./base";

const MAX_RESULTS = 100;
const SKIP_DIRS = new Set([".git", "node_modules", ".venv", "dist", "build", ".mypy_cache"]);

function displayPath(file: string, workdir: string): string {
  const rel = relative(workdir, file);
  return rel && !rel.startsWith("..") && !isAbsolute(rel) ? rel : file;
}

export function globFiles(pattern: string, path: string, workdir: string): string {
  try {
    const base = safePath(path, workdir);
    if (!existsSync(base)) return `Error: Path not found: ${path}`;
    if (!statSync(base).isDirectory()) return `Error: Not a directory: ${path}`;

    const glob = new Bun.Glob(pattern);
    const matches = [...glob.scanSync({ cwd: base, onlyFiles: true, dot: false })].sort();
    if (!matches.length) return `No files matching '${pattern}'`;

    const truncated = matches.length > MAX_RESULTS;
    const lines = matches
      .slice(0, MAX_RESULTS)
      .map((match) => displayPath(join(base, match), workdir));

    if (truncated) lines.push(`... (results truncated to ${MAX_RESULTS} files)`);
    return truncate(lines.join("\n"));
  } catch (error) {
    return `Error: ${error instanceof Error ? error.message : String(error)}`;
  }
}

function findRipgrep(preferred = "rg"): string | null {
  const configured = Bun.which(preferred) ?? (existsSync(preferred) ? preferred : null);
  if (configured) return configured;

  const candidates = [
    join(homedir(), ".local", "bin", "rg"),
    "/opt/homebrew/bin/rg",
    "/usr/local/bin/rg",
    join(homedir(), ".cargo", "bin", "rg"),
  ];
  return candidates.find(existsSync) ?? null;
}

function findAstGrep(preferred = "ast-grep"): string | null {
  return Bun.which(preferred) ?? (existsSync(preferred) ? preferred : null);
}

function formatMatches(
  pattern: string,
  matches: Array<{ file: string; line: number; content: string }>,
  truncated: boolean,
): string {
  const lines = [`Found ${matches.length} matches for '${pattern}':\n`];
  for (const match of matches) {
    lines.push(`${match.file}:${match.line}: ${match.content}`);
  }
  if (truncated) lines.push(`\n... (results truncated to ${MAX_RESULTS})`);
  return truncate(lines.join("\n"));
}

async function rgSearch(
  rg: string,
  pattern: string,
  base: string,
  workdir: string,
  glob: string | undefined,
  caseSensitive: boolean,
  maxResults: number,
): Promise<string> {
  const args = ["--json", "--context", "2", caseSensitive ? "--case-sensitive" : "--smart-case"];
  if (glob) args.push("--glob", glob);
  args.push("--glob", "!.git", pattern, base);

  const proc = Bun.spawn([rg, ...args], { stdout: "pipe", stderr: "pipe" });
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    proc.kill(9);
  }, 60_000);

  try {
    const [stdout, stderr, code] = await Promise.all([
      new Response(proc.stdout).text(),
      new Response(proc.stderr).text(),
      proc.exited,
    ]);
    if (timedOut) return "Error: Search timed out (60s)";
    if (code !== 0 && code !== 1) {
      return `Error: rg failed with code ${code}: ${stderr.trim()}`;
    }
    if (!stdout.trim()) return `No matches for '${pattern}'`;

    const matches: Array<{ file: string; line: number; content: string }> = [];
    for (const line of stdout.trim().split("\n")) {
      try {
        const data = JSON.parse(line) as {
          type?: string;
          data?: {
            path?: { text?: string };
            line_number?: number;
            lines?: { text?: string };
          };
        };
        if (data.type !== "match") continue;

        const file = data.data?.path?.text;
        const lineNumber = data.data?.line_number;
        const content = data.data?.lines?.text?.split("\n").find((item) => item.length > 0);
        if (!file || typeof lineNumber !== "number" || !content) continue;

        matches.push({
          file: displayPath(file, workdir),
          line: lineNumber,
          content,
        });
      } catch {
        continue;
      }
    }

    if (!matches.length) return `No matches for '${pattern}'`;
    return formatMatches(pattern, matches.slice(0, maxResults), matches.length > maxResults);
  } finally {
    clearTimeout(timer);
  }
}

function jsGrep(
  pattern: string,
  base: string,
  workdir: string,
  glob: string | undefined,
  caseSensitive: boolean,
  maxResults: number,
): string {
  let regex: RegExp;
  try {
    regex = new RegExp(pattern, caseSensitive ? "" : "i");
  } catch (error) {
    return `Error: Invalid regex: ${error instanceof Error ? error.message : String(error)}`;
  }

  const globMatcher = glob ? new Bun.Glob(glob) : null;
  const matches: Array<{ file: string; line: number; content: string }> = [];

  const walk = (dir: string): boolean => {
    let entries;
    try {
      entries = readdirSync(dir, { withFileTypes: true });
    } catch {
      return false;
    }

    for (const entry of entries) {
      if (matches.length > maxResults) return true;
      if (entry.name.startsWith(".") && entry.isDirectory()) continue;

      const fullPath = join(dir, entry.name);
      if (entry.isDirectory()) {
        if (SKIP_DIRS.has(entry.name)) continue;
        if (walk(fullPath)) return true;
        continue;
      }
      if (!entry.isFile()) continue;

      if (globMatcher && !globMatcher.match(relative(base, fullPath))) continue;

      let buffer: Buffer;
      try {
        if (statSync(fullPath).size > 2_000_000) continue;
        buffer = readFileSync(fullPath);
      } catch {
        continue;
      }
      if (buffer.includes(0)) continue;

      const lines = buffer.toString("utf8").split("\n");
      for (let i = 0; i < lines.length; i += 1) {
        const line = lines[i]!;
        if (regex.test(line)) {
          matches.push({
            file: displayPath(fullPath, workdir),
            line: i + 1,
            content: line,
          });
          if (matches.length > maxResults) break;
        }
      }
    }
    return false;
  };

  if (existsSync(base) && statSync(base).isFile()) {
    const globOk = !globMatcher || globMatcher.match(displayPath(base, workdir));
    if (globOk) {
      const lines = readFileSync(base, "utf8").split("\n");
      for (let i = 0; i < lines.length; i += 1) {
        const line = lines[i]!;
        if (regex.test(line)) {
          matches.push({ file: displayPath(base, workdir), line: i + 1, content: line });
          if (matches.length > maxResults) break;
        }
      }
    }
  } else {
    walk(base);
  }

  if (!matches.length) return `No matches for '${pattern}'`;
  return formatMatches(pattern, matches.slice(0, maxResults), matches.length > maxResults);
}

export async function grepFiles(
  input: Record<string, unknown>,
  ctx: ToolContext,
): Promise<string> {
  const pattern = requireString(input, "pattern");
  const path = optionalString(input, "path") ?? ".";
  const glob = optionalString(input, "glob");
  const caseSensitive = optionalBoolean(input, "case_sensitive") ?? false;

  try {
    const base = safePath(path, ctx.workdir);
    if (!existsSync(base)) return `Error: Path not found: ${path}`;

    const maxResults = ctx.config?.tools.rg.maxResults ?? MAX_RESULTS;
    const rg = findRipgrep(ctx.config?.tools.rg.binaryPath ?? "rg");
    if (!rg) {
      return jsGrep(pattern, base, ctx.workdir, glob, caseSensitive, maxResults);
    }
    return await rgSearch(
      rg,
      pattern,
      base,
      ctx.workdir,
      glob,
      caseSensitive,
      maxResults,
    );
  } catch (error) {
    return `Error during search: ${error instanceof Error ? error.message : String(error)}`;
  }
}

export async function astGrepFiles(
  pattern: string,
  path: string,
  language: string | undefined,
  workdir: string,
  binary = "ast-grep",
): Promise<string> {
  const binaryPath = findAstGrep(binary);
  if (!binaryPath) {
    return "Error: ast-grep not found. Please install it: https://ast-grep.github.io/";
  }

  try {
    const base = safePath(path, workdir);
    const args = [binaryPath, "run", "--json", "--pattern", pattern];
    if (language) args.push("--lang", language);
    args.push(base);

    const proc = Bun.spawn(args, { stdout: "pipe", stderr: "pipe" });
    const timer = setTimeout(() => proc.kill(9), 60_000);
    try {
      const [stdout, , code] = await Promise.all([
        new Response(proc.stdout).text(),
        new Response(proc.stderr).text(),
        proc.exited,
      ]);
      if (code !== 0 && !stdout.trim()) return `No matches for pattern '${pattern}'`;

      let matches: Array<Record<string, unknown>>;
      try {
        const parsed = stdout.trim() ? (JSON.parse(stdout) as unknown) : [];
        matches = Array.isArray(parsed)
          ? (parsed as Array<Record<string, unknown>>)
          : [parsed as Record<string, unknown>];
      } catch {
        return `No matches for pattern '${pattern}'`;
      }
      if (!matches.length) return `No matches for pattern '${pattern}'`;

      const truncated = matches.length > MAX_RESULTS;
      const lines = [`Found ${Math.min(matches.length, MAX_RESULTS)} AST matches for '${pattern}':\n`];
      for (const match of matches.slice(0, MAX_RESULTS)) {
        const range = (match.range as { start?: { line?: number } } | undefined)?.start;
        const text = String(match.text ?? "").replaceAll("\n", " ").slice(0, 100);
        lines.push(
          `${displayPath(String(match.file ?? ""), workdir)}:${range?.line ?? 0}: ${text}`,
        );
      }
      if (truncated) lines.push(`\n... (results truncated to ${MAX_RESULTS})`);
      return truncate(lines.join("\n"));
    } finally {
      clearTimeout(timer);
    }
  } catch (error) {
    return `Error during search: ${error instanceof Error ? error.message : String(error)}`;
  }
}

export const grepTool: Tool = {
  name: "Grep",
  aliases: ["rg_search"],
  description: "Search files using ripgrep (regex-based text search).",
  inputSchema: {
    type: "object",
    properties: {
      pattern: { type: "string", description: "Regex pattern to search for" },
      path: { type: "string", description: "Directory or file to search (default: current directory)" },
      glob: { type: "string", description: "File glob pattern, e.g., '*.py'" },
      case_sensitive: { type: "boolean", description: "Case-sensitive search" },
    },
    required: ["pattern"],
  },
  riskLevel: "low",
  isReadOnly: true,
  isConcurrencySafe: () => true,
  requiredCapabilities: ["file_read"],
  run: grepFiles,
};

export const globTool: Tool = {
  name: "Glob",
  description: "Find files matching a glob pattern (e.g. '**/*.py', 'src/**/*.ts').",
  inputSchema: {
    type: "object",
    properties: {
      pattern: { type: "string", description: "Glob pattern, e.g. '**/*.py'" },
      path: { type: "string", description: "Base directory to search (default: workspace root)" },
    },
    required: ["pattern"],
  },
  riskLevel: "low",
  isReadOnly: true,
  isConcurrencySafe: () => true,
  requiredCapabilities: ["file_read"],
  run: async (input, ctx) =>
    globFiles(
      requireString(input, "pattern"),
      optionalString(input, "path") ?? ".",
      ctx.workdir,
    ),
};

export const astGrepTool: Tool = {
  name: "AstGrep",
  aliases: ["ast_grep_search"],
  description: "Search code using ast-grep (structural/AST-based search).",
  inputSchema: {
    type: "object",
    properties: {
      pattern: {
        type: "string",
        description: "ast-grep pattern (e.g., 'class $NAME:', 'def $FUNC($$$ARGS):')",
      },
      path: { type: "string", description: "Directory or file to search" },
      language: {
        type: "string",
        description: "Language hint (python, javascript, rust, etc.)",
      },
    },
    required: ["pattern"],
  },
  riskLevel: "low",
  isReadOnly: true,
  isConcurrencySafe: () => true,
  requiredCapabilities: ["file_read"],
  run: async (input, ctx) =>
    astGrepFiles(
      requireString(input, "pattern"),
      optionalString(input, "path") ?? ".",
      optionalString(input, "language"),
      ctx.workdir,
      ctx.config?.tools.astGrep.binaryPath ?? "ast-grep",
    ),
};
