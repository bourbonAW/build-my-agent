import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { AuditLogger } from "../src/audit";
import type { MemoryConfig } from "../src/config";
import {
  expandQueryTerms,
  generateCues,
  MEMORY_TARGETS,
  MemoryManager,
  MemoryStore,
  sanitizeProjectKey,
  validateMemoryTarget,
} from "../src/memory";
import { cosineSimilarity, packVector, type EmbeddingProvider } from "../src/memory/embeddings";
import { MemoryRetriever } from "../src/memory/retriever";
import { MemorySearchIndex } from "../src/memory/search_index";
import { createToolRegistry } from "../src/tools";

class FakeEmbeddingProvider implements EmbeddingProvider {
  readonly name = "fake";
  readonly model = "fake-3d";
  dimensions: number | null = 3;

  private vector(text: string): number[] {
    const lower = text.toLowerCase();
    return [
      lower.includes("alpha") ? 1 : 0,
      lower.includes("beta") ? 1 : 0,
      0.1,
    ];
  }

  async embedPassages(texts: string[]): Promise<number[][]> {
    return texts.map((text) => this.vector(text));
  }

  async embedQuery(text: string): Promise<number[]> {
    return this.vector(text);
  }
}

function memoryConfig(storageDir: string): MemoryConfig {
  return {
    enabled: true,
    storageDir,
    recallLimit: 8,
    memoryMdTokenLimit: 1200,
    userMdTokenLimit: 600,
    semantic: {
      enabled: false,
      provider: "fastembed",
      model: "test",
      topK: 16,
      minSimilarity: 0.25,
    },
  };
}

let root: string;
let audit: AuditLogger;

beforeEach(() => {
  root = mkdtempSync(join(tmpdir(), "bourbon-memory-"));
  audit = new AuditLogger(join(root, "audit"), true);
});

afterEach(() => {
  rmSync(root, { recursive: true, force: true });
});

describe("cues", () => {
  test("extracts explicit and derived cues", () => {
    const cues = generateCues(
      "Users prefer `pnpm` for package management. Run `bun test` in `ts/` before merging.",
    );
    expect(cues).toContain("pnpm");
    expect(cues).toContain("bun test");
    expect(cues).toContain("ts/");
    expect(cues.length).toBeLessThanOrEqual(12);
  });

  test("expands queries with explicit terms", () => {
    const terms = expandQueryTerms("where is `search_index.sqlite` used?");
    expect(terms[0]).toBe("where is `search_index.sqlite` used?");
    expect(terms).toContain("search_index.sqlite");
  });

  test("validates targets", () => {
    expect(validateMemoryTarget("user")).toBe("user");
    expect(() => validateMemoryTarget("global")).toThrow("Invalid memory target");
    expect(MEMORY_TARGETS).toEqual(["user", "project"]);
  });
});

describe("memory store", () => {
  test("writes, indexes, searches, and deletes records", () => {
    const store = new MemoryStore(join(root, "memory"));
    const record = {
      id: "mem_test1",
      target: "user" as const,
      content: "Prefer bun test for TypeScript checks.",
      createdAt: new Date().toISOString(),
      cues: ["bun test", "TypeScript"],
    };
    store.writeRecord(record);

    const file = join(root, "memory", "mem_test1.md");
    expect(existsSync(file)).toBe(true);
    expect(readFileSync(file, "utf8")).toContain("cues:");

    expect(store.readRecord("mem_test1")?.content).toContain("bun test");
    expect(store.search("bun test")[0]).toMatchObject({
      id: "mem_test1",
      whyMatched: "matched cue: bun test",
    });
    expect(readFileSync(join(root, "memory", "MEMORY.md"), "utf8")).toContain("mem_test1.md");

    store.deleteRecord("mem_test1");
    expect(store.readRecord("mem_test1")).toBeNull();
  });

  test("sanitizes project keys", () => {
    const key = sanitizeProjectKey("/Users/whf/github_project/build-my-agent");
    expect(key).toMatch(/^[a-z0-9-]+-[a-f0-9]{8}$/);
    expect(key.length).toBeLessThanOrEqual(73);
  });
});

describe("semantic index and retriever", () => {
  test("indexes FTS and vector channels and fuses results", async () => {
    const dir = join(root, "semantic");
    const store = new MemoryStore(dir);
    store.writeRecord({
      id: "mem_alpha",
      target: "project",
      content: "Alpha service endpoint",
      createdAt: new Date().toISOString(),
      cues: ["alpha"],
    });
    store.writeRecord({
      id: "mem_beta",
      target: "project",
      content: "Beta service endpoint",
      createdAt: new Date().toISOString(),
      cues: ["beta"],
    });

    const index = new MemorySearchIndex(
      join(dir, "search_index.sqlite"),
      new FakeEmbeddingProvider(),
      16,
      0.25,
    );
    await index.rebuild(store.listRecords());

    const fts = await index.searchFts("alpha", null, 10);
    expect(fts.map((item) => item.memoryId)).toContain("mem_alpha");

    const vector = await index.searchVector("alpha", null, 10);
    expect(vector[0]!.memoryId).toBe("mem_alpha");
    expect(vector[0]!.reason).toContain("matched semantic");

    const retriever = new MemoryRetriever(store, index);
    const results = await retriever.search({
      query: "alpha",
      terms: ["alpha"],
      target: "project",
      limit: 5,
    });
    expect(results[0]!.id).toBe("mem_alpha");
    expect(results.some((result) => result.id === "mem_beta")).toBe(false);
  });

  test("packs and unpacks vectors and computes cosine similarity", () => {
    const packed = packVector([1, 2, 3]);
    expect(packed.byteLength).toBe(12);
    expect(cosineSimilarity([1, 0], [0, 1])).toBe(0);
    expect(cosineSimilarity([1, 1], [1, 1])).toBeCloseTo(1);
  });
});

describe("memory manager and tools", () => {
  test("writes, searches, reports status, and deletes", async () => {
    const manager = new MemoryManager(
      memoryConfig(join(root, "memory")),
      "project-key",
      root,
      audit,
    );

    const userRecord = await manager.write(
      { target: "user", content: "Prefer `bun test` for checks." },
      { kind: "agent", sessionId: "s1" },
    );
    const projectRecord = await manager.write(
      { target: "project", content: "Session transcripts live in `~/.bourbon/sessions`." },
      { kind: "agent", sessionId: "s1" },
    );

    expect(userRecord.id).toMatch(/^mem_/);
    expect(existsSync(join(root, "memory", "project-key", "memory", "MEMORY.md"))).toBe(true);

    const results = await manager.search("bun test", {});
    expect(results[0]!.id).toBe(userRecord.id);
    expect(manager.getLastExpandedTerms().length).toBeGreaterThan(0);

    const status = manager.getStatus({ kind: "agent" });
    expect(status.memoryFileCount).toBe(2);
    expect(status.writableTargets).toEqual(["user", "project"]);
    expect(status.recentWrites).toHaveLength(2);

    const subagentStatus = manager.getStatus({ kind: "subagent" });
    expect(subagentStatus.writableTargets).toEqual(["project"]);

    await manager.delete(projectRecord.id, { kind: "user" });
    expect(manager.getStatus({ kind: "agent" }).memoryFileCount).toBe(1);
  });

  test("enforces subagent write and delete permissions", async () => {
    const manager = new MemoryManager(
      memoryConfig(join(root, "memory")),
      "project-key",
      root,
      audit,
    );
    await expect(
      manager.write({ target: "user", content: "nope" }, { kind: "subagent" }),
    ).rejects.toThrow("cannot write target=user");
    await expect(manager.delete("mem_x", { kind: "subagent" })).rejects.toThrow(
      "Subagents cannot delete",
    );
  });

  test("memory tools return JSON payloads", async () => {
    const manager = new MemoryManager(
      memoryConfig(join(root, "memory")),
      "project-key",
      root,
      audit,
    );
    const registry = createToolRegistry();
    const ctx = {
      workdir: root,
      memoryManager: manager,
      memoryActor: { kind: "agent" as const, sessionId: "s1" },
    };

    const written = JSON.parse(
      await registry.call(
        "memory_write",
        { target: "project", content: "Use `bun test` in ts/." },
        ctx,
      ),
    ) as { id: string; status: string; file: string };
    expect(written.status).toBe("written");
    expect(written.file).toBe(`${written.id}.md`);

    const search = JSON.parse(
      await registry.call("memory_search", { query: "bun test" }, ctx),
    ) as { results: Array<{ id: string }> };
    expect(search.results[0]!.id).toBe(written.id);

    const status = JSON.parse(await registry.call("memory_status", {}, ctx)) as {
      memory_file_count: number;
    };
    expect(status.memory_file_count).toBe(1);

    const deleted = JSON.parse(
      await registry.call("memory_delete", { memory_id: written.id }, ctx),
    ) as { status: string };
    expect(deleted.status).toBe("deleted");
  });
});
