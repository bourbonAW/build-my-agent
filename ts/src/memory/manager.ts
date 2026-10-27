import { randomBytes } from "node:crypto";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { AuditEvent, type AuditLogger } from "../audit";
import type { MemoryConfig } from "../config";
import { expandQueryTerms, generateCues } from "./cues";
import { TransformersJsProvider } from "./embeddings";
import type {
  MemoryActor,
  MemoryRecord,
  MemoryRecordDraft,
  MemorySearchResult,
  MemorySystemInfo,
  RecentWriteSummary,
} from "./models";
import { MEMORY_TARGETS, validateMemoryTarget } from "./models";
import { checkDeletePermission, checkWritePermission } from "./policy";
import { MemoryRetriever } from "./retriever";
import { MemorySearchIndex } from "./search_index";
import { MEMORY_INDEX_LINE_LIMIT, MemoryStore, recordPreview } from "./store";

export class MemoryManager {
  private readonly store: MemoryStore;
  private readonly searchIndex: MemorySearchIndex | null;
  private readonly retriever: MemoryRetriever | null;
  private recentWrites: RecentWriteSummary[] = [];
  private lastExpandedTerms: string[] = [];
  private readonly memoryDir: string;

  constructor(
    private readonly config: MemoryConfig,
    readonly projectKey: string,
    readonly workdir: string,
    private readonly audit?: AuditLogger,
  ) {
    this.memoryDir = join(
      config.storageDir.replace(/^~(?=\/|$)/, homedir()),
      projectKey,
      "memory",
    );
    this.store = new MemoryStore(this.memoryDir);
    this.searchIndex = this.makeSearchIndex();
    this.retriever = this.searchIndex
      ? new MemoryRetriever(this.store, this.searchIndex)
      : null;
  }

  private makeSearchIndex(): MemorySearchIndex | null {
    const semantic = this.config.semantic;
    if (!semantic.enabled) return null;
    if (!["fastembed", "transformers", "transformers-js", "auto"].includes(semantic.provider)) {
      return null;
    }
    return new MemorySearchIndex(
      join(this.memoryDir, "search_index.sqlite"),
      new TransformersJsProvider(semantic.model),
      semantic.topK,
      semantic.minSimilarity,
    );
  }

  private async ensureSearchIndexCurrent(probeText?: string): Promise<boolean> {
    if (!this.searchIndex) return false;
    try {
      const records = this.store.listRecords();
      if (!(await this.searchIndex.needsRebuild(records, probeText))) return false;
      await this.searchIndex.rebuild(records);
      return true;
    } catch {
      return false;
    }
  }

  getMemoryDir(): string {
    return this.memoryDir;
  }

  getLastExpandedTerms(): string[] {
    return [...this.lastExpandedTerms];
  }

  async write(draft: MemoryRecordDraft, actor: MemoryActor): Promise<MemoryRecord> {
    const target = validateMemoryTarget(draft.target);
    const content = draft.content.trim();
    if (!content) throw new Error("Memory content must be non-empty");
    if (!checkWritePermission(actor, target)) {
      throw new Error(`Actor ${actor.kind}:${actor.agentType ?? ""} cannot write target=${target}`);
    }
    if (!this.audit) throw new Error("memory writes require audit");

    const record: MemoryRecord = {
      id: `mem_${randomBytes(4).toString("hex")}`,
      target,
      content,
      createdAt: new Date().toISOString(),
      cues: generateCues(content),
    };

    this.store.writeRecord(record);
    if (this.searchIndex) {
      try {
        const rebuilt = await this.ensureSearchIndexCurrent();
        if (!rebuilt) await this.searchIndex.upsert(record);
      } catch {
        // semantic index is best-effort
      }
    }

    this.recentWrites.push({
      id: record.id,
      target: record.target,
      preview: recordPreview(record),
      createdAt: record.createdAt,
    });
    this.recentWrites = this.recentWrites.slice(-10);

    this.recordAudit("memory_write", recordPreview(record), {
      memory_id: record.id,
      target: record.target,
      actor_kind: actor.kind,
      session_id: actor.sessionId,
      run_id: actor.runId,
      agent_type: actor.agentType,
      content_preview: recordPreview(record),
    });
    return record;
  }

  async search(
    query: string,
    options: { target?: string | null; limit?: number } = {},
  ): Promise<MemorySearchResult[]> {
    const target = options.target ? validateMemoryTarget(options.target) : null;
    const limit = options.limit ?? this.config.recallLimit;
    const terms = expandQueryTerms(query);
    this.lastExpandedTerms = terms;

    if (this.retriever) {
      try {
        await this.ensureSearchIndexCurrent(query);
        const results = await this.retriever.search({ query, terms, target, limit });
        this.recordSearchAudit(query, target, results.length);
        return results;
      } catch {
        // fall through to exact matching
      }
    }

    const results: MemorySearchResult[] = [];
    const seen = new Set<string>();
    for (const term of terms) {
      for (const result of this.store.search(term, target, limit)) {
        if (seen.has(result.id)) continue;
        results.push(result);
        seen.add(result.id);
        if (results.length >= limit) {
          this.recordSearchAudit(query, target, results.length);
          return results;
        }
      }
    }
    this.recordSearchAudit(query, target, results.length);
    return results;
  }

  async delete(memoryId: string, actor: MemoryActor): Promise<void> {
    checkDeletePermission(actor);
    this.store.deleteRecord(memoryId);
    if (this.searchIndex) {
      try {
        await this.searchIndex.delete(memoryId);
      } catch {
        // best-effort
      }
    }
    this.recordAudit("memory_delete", memoryId, {
      memory_id: memoryId,
      actor_kind: actor.kind,
      session_id: actor.sessionId,
      run_id: actor.runId,
      agent_type: actor.agentType,
    });
  }

  getStatus(actor: MemoryActor): MemorySystemInfo {
    const writableTargets = actor.kind === "subagent" ? ["project"] : [...MEMORY_TARGETS];
    let memoryFileCount = 0;
    if (existsSync(this.memoryDir)) {
      memoryFileCount = readdirSync(this.memoryDir).filter(
        (name) => name.endsWith(".md") && name !== "MEMORY.md",
      ).length;
    }

    const indexPath = join(this.memoryDir, "MEMORY.md");
    let indexAtCapacity = false;
    if (existsSync(indexPath)) {
      const lines = readFileSync(indexPath, "utf8")
        .split("\n")
        .filter((line) => line.length > 0);
      indexAtCapacity = lines.length >= MEMORY_INDEX_LINE_LIMIT;
    }

    return {
      readableTargets: [...MEMORY_TARGETS],
      writableTargets,
      recentWrites: [...this.recentWrites],
      indexAtCapacity,
      memoryFileCount,
    };
  }

  private recordSearchAudit(query: string, target: string | null, resultCount: number): void {
    this.recordAudit("memory_search", query.slice(0, 100), {
      query,
      target,
      result_count: resultCount,
    });
  }

  private recordAudit(
    eventType: "memory_write" | "memory_search" | "memory_delete",
    summary: string,
    extra: Record<string, unknown>,
  ): void {
    this.audit?.record(AuditEvent.create(eventType, {
      toolName: "memory",
      toolInputSummary: summary,
      extra,
    }));
  }
}
