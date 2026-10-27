import type { MemoryActor, MemoryRecordDraft } from "../memory";
import { validateMemoryTarget } from "../memory";
import type { Tool } from "./types";
import { requireString } from "./types";

function disabled(): string {
  return JSON.stringify({ error: "Memory system is not enabled" });
}

export const memorySearchTool: Tool = {
  name: "memory_search",
  aliases: ["MemorySearch"],
  description: "Search stored memory records by keyword.",
  inputSchema: {
    type: "object",
    properties: {
      query: { type: "string", description: "Search query keywords" },
      target: { type: "string", enum: ["user", "project"], description: "Optional target filter" },
      limit: { type: "integer", default: 8, description: "Maximum results" },
      debug_terms: {
        type: "boolean",
        default: false,
        description: "Include expanded query terms used for search",
      },
    },
    required: ["query"],
  },
  riskLevel: "low",
  isReadOnly: true,
  requiredCapabilities: ["file_read"],
  isConcurrencySafe: () => true,
  run: async (input, ctx) => {
    const manager = ctx.memoryManager;
    if (!manager) return disabled();

    try {
      const results = await manager.search(requireString(input, "query"), {
        target: typeof input.target === "string" ? input.target : null,
        limit: typeof input.limit === "number" ? input.limit : undefined,
      });
      const payload: Record<string, unknown> = {
        results: results.map((result) => ({
          id: result.id,
          target: result.target,
          snippet: result.snippet,
          why_matched: result.whyMatched,
        })),
      };
      if (input.debug_terms === true) {
        payload.expanded_terms = manager.getLastExpandedTerms();
      }
      return JSON.stringify(payload);
    } catch (error) {
      return JSON.stringify({ error: error instanceof Error ? error.message : String(error) });
    }
  },
};

export const memoryWriteTool: Tool = {
  name: "memory_write",
  aliases: ["MemoryWrite"],
  description:
    "Write a memory record for future recall. Use target='user' for durable user preferences and target='project' for repository decisions, files, workflows, and references. Do not write ephemeral task state to memory.",
  inputSchema: {
    type: "object",
    properties: {
      target: { type: "string", enum: ["user", "project"], description: "Memory target" },
      content: { type: "string", description: "Memory content" },
    },
    required: ["target", "content"],
  },
  riskLevel: "medium",
  requiredCapabilities: ["file_write"],
  run: async (input, ctx) => {
    const manager = ctx.memoryManager;
    if (!manager) return disabled();

    try {
      const draft: MemoryRecordDraft = {
        target: validateMemoryTarget(requireString(input, "target")),
        content: requireString(input, "content"),
      };
      const actor: MemoryActor = ctx.memoryActor ?? { kind: "agent" };
      const record = await manager.write(draft, actor);
      return JSON.stringify({
        id: record.id,
        target: record.target,
        status: "written",
        file: `${record.id}.md`,
      });
    } catch (error) {
      return JSON.stringify({ error: error instanceof Error ? error.message : String(error) });
    }
  },
};

export const memoryDeleteTool: Tool = {
  name: "memory_delete",
  aliases: ["MemoryDelete"],
  description: "Delete a stored memory record by id.",
  inputSchema: {
    type: "object",
    properties: {
      memory_id: { type: "string", description: "ID of the memory record to delete" },
    },
    required: ["memory_id"],
  },
  riskLevel: "medium",
  requiredCapabilities: ["file_write"],
  run: async (input, ctx) => {
    const manager = ctx.memoryManager;
    if (!manager) return disabled();

    try {
      const actor: MemoryActor = ctx.memoryActor ?? { kind: "agent" };
      const memoryId = requireString(input, "memory_id");
      await manager.delete(memoryId, actor);
      return JSON.stringify({ id: memoryId, status: "deleted" });
    } catch (error) {
      return JSON.stringify({ error: error instanceof Error ? error.message : String(error) });
    }
  },
};

export const memoryStatusTool: Tool = {
  name: "memory_status",
  aliases: ["MemoryStatus"],
  description: "Return current memory system status and recent writes.",
  inputSchema: { type: "object", properties: {} },
  riskLevel: "low",
  isReadOnly: true,
  requiredCapabilities: ["file_read"],
  isConcurrencySafe: () => true,
  run: async (_input, ctx) => {
    const manager = ctx.memoryManager;
    if (!manager) return disabled();

    const actor: MemoryActor = ctx.memoryActor ?? { kind: "agent" };
    const status = manager.getStatus(actor);
    return JSON.stringify({
      readable_targets: status.readableTargets,
      writable_targets: status.writableTargets,
      index_at_capacity: status.indexAtCapacity,
      memory_file_count: status.memoryFileCount,
      recent_writes: status.recentWrites.map((write) => ({
        id: write.id,
        target: write.target,
        preview: write.preview,
      })),
    });
  },
};
