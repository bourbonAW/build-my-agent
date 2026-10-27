import { appendFileSync, mkdirSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, isAbsolute, join } from "node:path";

function debugLogPath(): string | null {
  const explicit = process.env.BOURBON_DEBUG_LOG;
  if (explicit) {
    return explicit.startsWith("~")
      ? explicit.replace(/^~(?=\/|$)/, homedir())
      : isAbsolute(explicit)
        ? explicit
        : join(process.cwd(), explicit);
  }

  const enabled = ["BOURBON_DEBUG", "BOURBON_DEBUG_PROMPTS"].some((flag) =>
    ["1", "true", "yes", "on"].includes((process.env[flag] ?? "").toLowerCase()),
  );
  return enabled ? join(homedir(), ".bourbon", "logs", "debug.jsonl") : null;
}

export function promptFields(
  messages: unknown[] | null,
  system?: string,
  tools?: Array<{ name?: string }>,
): Record<string, unknown> {
  const enabled = ["1", "true", "yes", "on"].includes(
    (process.env.BOURBON_DEBUG_PROMPTS ?? "").toLowerCase(),
  );
  if (!enabled) return {};
  return {
    messages,
    system,
    tool_names: (tools ?? []).map((tool) => tool.name),
  };
}

export function debugLog(event: string, fields: Record<string, unknown> = {}): void {
  const path = debugLogPath();
  if (!path) return;

  const record = {
    ts: Date.now() / 1000,
    event,
    pid: process.pid,
    ...fields,
  };

  try {
    mkdirSync(dirname(path), { recursive: true });
    appendFileSync(path, `${JSON.stringify(record)}\n`, "utf8");
  } catch {
    // diagnostics must never break the product path
  }
}
