import { existsSync } from "node:fs";
import { dirname, isAbsolute, resolve } from "node:path";

export interface MatchCandidate {
  toolName: string;
  kind: "command_prefix" | "exact_file" | "parent_dir" | "fallback";
  value: string;
}

export function buildMatchCandidate(
  toolName: string,
  toolInput: Record<string, unknown>,
  workdir: string,
): MatchCandidate {
  if (toolName === "Bash") {
    const command = String(toolInput.command ?? "").trim();
    const tokens = command.split(/\s+/).filter(Boolean);
    return {
      toolName,
      kind: "command_prefix",
      value: tokens.length >= 2 ? tokens.slice(0, 2).join(" ") : command,
    };
  }

  if (toolName === "Write") {
    const resolved = resolvePath(String(toolInput.path ?? ""), workdir);
    const exact = existsSync(resolved);
    return {
      toolName,
      kind: exact ? "exact_file" : "parent_dir",
      value: exact ? resolved : dirname(resolved),
    };
  }

  if (toolName === "Edit") {
    return {
      toolName,
      kind: "exact_file",
      value: resolvePath(String(toolInput.path ?? ""), workdir),
    };
  }

  const fields = Object.entries(toolInput)
    .filter(([key]) => ["path", "command", "url"].includes(key))
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([key, value]) => `${key}=${String(value)}`);

  return { toolName, kind: "fallback", value: fields.join("|") };
}

export function sessionRuleMatches(
  candidate: MatchCandidate,
  toolName: string,
  toolInput: Record<string, unknown>,
  workdir: string,
): boolean {
  const current = buildMatchCandidate(toolName, toolInput, workdir);
  return (
    candidate.toolName === current.toolName &&
    candidate.kind === current.kind &&
    candidate.value === current.value
  );
}

function resolvePath(path: string, workdir: string): string {
  return isAbsolute(path) ? resolve(path) : resolve(workdir, path);
}
