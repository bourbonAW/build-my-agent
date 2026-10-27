import { homedir } from "node:os";
import { join } from "node:path";
import type { PromptContext } from "../prompt/types";
import { readFileAnchor, renderMergedUserMdForPrompt } from "./files";

const AGENTS_MD_TOKEN_LIMIT = 8000;
export const MEMORY_ANCHOR_ORDER = 15;

export function memoryAnchorsSection(ctx: PromptContext): string {
  if (!ctx.memoryManager) return "";

  const parts: string[] = [];
  const agents = readFileAnchor(join(ctx.workdir, "AGENTS.md"), AGENTS_MD_TOKEN_LIMIT);
  if (agents) {
    parts.push(`# Project Instructions (AGENTS.md)\n\n${agents}`);
  }

  const user = renderMergedUserMdForPrompt(
    join(homedir(), ".bourbon", "USER.md"),
    join(ctx.workdir, "USER.md"),
    ctx.memoryConfig?.userMdTokenLimit ?? 600,
  );
  if (user) {
    parts.push(`# User Preferences (USER.md)\n\n${user}`);
  }

  const memory = readFileAnchor(
    join(ctx.memoryManager.getMemoryDir(), "MEMORY.md"),
    ctx.memoryConfig?.memoryMdTokenLimit ?? 1200,
  );
  if (memory) {
    parts.push(`# Memory Index (MEMORY.md)\n\n${memory}`);
  }

  return parts.join("\n\n---\n\n");
}
