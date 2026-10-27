import { Database } from "bun:sqlite";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, unlinkSync } from "node:fs";
import { dirname } from "node:path";
import type { EmbeddingProvider } from "./embeddings";
import { cosineSimilarity, packVector, unpackVector } from "./embeddings";
import type { MemoryRecord } from "./models";

const INDEX_SCHEMA_VERSION = "memory-search-index-v1";
const SEARCH_TEXT_VERSION = "memory-search-text-v1";

export interface IndexCandidate {
  memoryId: string;
  channel: "fts" | "semantic";
  score: number;
  reason: string;
}

interface PreparedRecord {
  record: MemoryRecord;
  searchText: string;
  vector: number[];
}

export function renderSearchText(record: MemoryRecord): string {
  const parts = [record.content.trim()];
  if (record.cues.length) parts.push(`cues:\n${record.cues.join("\n")}`);
  return parts.filter(Boolean).join("\n\n");
}

function contentHash(searchText: string): string {
  return createHash("sha256").update(searchText).digest("hex");
}

export class MemorySearchIndex {
  constructor(
    readonly indexPath: string,
    readonly provider: EmbeddingProvider,
    readonly topK: number,
    readonly minSimilarity: number,
  ) {}

  private connect(): Database {
    mkdirSync(dirname(this.indexPath), { recursive: true });
    const db = new Database(this.indexPath, { create: true });
    db.exec("pragma journal_mode=wal");
    db.exec("pragma busy_timeout=5000");
    return db;
  }

  private ensureSchema(db: Database): void {
    db.exec(`
      create table if not exists memory_index_meta (
        key text primary key,
        value text not null
      );
      create table if not exists memory_index_records (
        memory_id text primary key,
        target text not null,
        content_hash text not null,
        created_at text not null,
        search_text text not null
      );
      create virtual table if not exists memory_fts using fts5(
        memory_id unindexed,
        search_text,
        tokenize='unicode61'
      );
      create table if not exists memory_vectors (
        memory_id text primary key,
        provider text not null,
        model text not null,
        dimensions integer not null,
        vector blob not null
      );
    `);
    this.setMetaIfAbsent(db, "schema_version", INDEX_SCHEMA_VERSION);
    this.setMetaIfAbsent(db, "search_text_version", SEARCH_TEXT_VERSION);
    this.setMetaIfAbsent(db, "embedding_provider", this.provider.name);
    this.setMetaIfAbsent(db, "embedding_model", this.provider.model);
  }

  private setMeta(db: Database, key: string, value: unknown): void {
    db.run(
      "insert into memory_index_meta(key, value) values (?, ?) on conflict(key) do update set value = excluded.value",
      [key, String(value)],
    );
  }

  private setMetaIfAbsent(db: Database, key: string, value: unknown): void {
    db.run("insert or ignore into memory_index_meta(key, value) values (?, ?)", [
      key,
      String(value),
    ]);
  }

  private readMeta(db: Database): Record<string, string> {
    const rows = db.query("select key, value from memory_index_meta").all() as Array<{
      key: string;
      value: string;
    }>;
    return Object.fromEntries(rows.map((row) => [row.key, row.value]));
  }

  private expectedMeta(): Record<string, string> {
    return {
      schema_version: INDEX_SCHEMA_VERSION,
      search_text_version: SEARCH_TEXT_VERSION,
      embedding_provider: this.provider.name,
      embedding_model: this.provider.model,
    };
  }

  private async needsRebuildFor(
    db: Database,
    records: MemoryRecord[],
    probeText?: string,
  ): Promise<boolean> {
    const meta = this.readMeta(db);
    for (const [key, value] of Object.entries(this.expectedMeta())) {
      if (meta[key] !== value) return true;
    }

    let dimensions = this.provider.dimensions;
    if (dimensions === null && probeText && meta.embedding_dimensions) {
      dimensions = (await this.provider.embedQuery(probeText)).length;
    }
    if (dimensions !== null && meta.embedding_dimensions !== String(dimensions)) {
      return true;
    }

    const actual = new Set(
      (
        db
          .query("select memory_id, target, content_hash from memory_index_records")
          .all() as Array<{ memory_id: string; target: string; content_hash: string }>
      ).map((row) => `${row.memory_id}\u0000${row.target}\u0000${row.content_hash}`),
    );
    const expected = new Set(
      records.map(
        (record) =>
          `${record.id}\u0000${record.target}\u0000${contentHash(renderSearchText(record))}`,
      ),
    );

    if (actual.size !== expected.size) return true;
    for (const item of expected) {
      if (!actual.has(item)) return true;
    }
    if (records.length && !meta.embedding_dimensions) return true;
    return false;
  }

  async needsRebuild(records: MemoryRecord[], probeText?: string): Promise<boolean> {
    const db = this.connect();
    try {
      this.ensureSchema(db);
      return await this.needsRebuildFor(db, records, probeText);
    } finally {
      db.close();
    }
  }

  private async prepareRecords(records: MemoryRecord[]): Promise<PreparedRecord[]> {
    const searchTexts = records.map(renderSearchText);
    const vectors = await this.provider.embedPassages(searchTexts);
    if (vectors.length !== records.length) {
      throw new Error("Embedding provider returned the wrong number of vectors");
    }
    return records.map((record, index) => ({
      record,
      searchText: searchTexts[index]!,
      vector: vectors[index]!,
    }));
  }

  private upsertPrepared(db: Database, prepared: PreparedRecord): void {
    const { record, searchText, vector } = prepared;
    const dimensions = vector.length;

    db.run(
      `insert into memory_index_records(memory_id, target, content_hash, created_at, search_text)
       values (?, ?, ?, ?, ?)
       on conflict(memory_id) do update set
         target = excluded.target,
         content_hash = excluded.content_hash,
         created_at = excluded.created_at,
         search_text = excluded.search_text`,
      [record.id, record.target, contentHash(searchText), record.createdAt, searchText],
    );
    db.run("delete from memory_fts where memory_id = ?", [record.id]);
    db.run("insert into memory_fts(memory_id, search_text) values (?, ?)", [
      record.id,
      searchText,
    ]);
    db.run(
      `insert into memory_vectors(memory_id, provider, model, dimensions, vector)
       values (?, ?, ?, ?, ?)
       on conflict(memory_id) do update set
         provider = excluded.provider,
         model = excluded.model,
         dimensions = excluded.dimensions,
         vector = excluded.vector`,
      [
        record.id,
        this.provider.name,
        this.provider.model,
        dimensions,
        packVector(vector),
      ],
    );
  }

  private writeCurrentMeta(db: Database, dimensions: number | null): void {
    this.setMeta(db, "schema_version", INDEX_SCHEMA_VERSION);
    this.setMeta(db, "search_text_version", SEARCH_TEXT_VERSION);
    this.setMeta(db, "embedding_provider", this.provider.name);
    this.setMeta(db, "embedding_model", this.provider.model);
    if (dimensions !== null) {
      this.setMeta(db, "embedding_dimensions", dimensions);
    }
  }

  private replaceRecords(prepared: PreparedRecord[]): void {
    const dimensions = prepared.length ? prepared[0]!.vector.length : this.provider.dimensions;
    const db = this.connect();
    try {
      this.ensureSchema(db);
      db.transaction(() => {
        db.run("delete from memory_index_records");
        db.run("delete from memory_fts");
        db.run("delete from memory_vectors");
        for (const item of prepared) this.upsertPrepared(db, item);
        this.writeCurrentMeta(db, dimensions);
      })();
    } finally {
      db.close();
    }
  }

  private removeIndexFiles(): void {
    for (const path of [
      this.indexPath,
      `${this.indexPath}-wal`,
      `${this.indexPath}-shm`,
    ]) {
      if (existsSync(path)) unlinkSync(path);
    }
  }

  async rebuild(records: MemoryRecord[]): Promise<void> {
    const prepared = await this.prepareRecords(records);
    try {
      this.replaceRecords(prepared);
    } catch (error) {
      const message = error instanceof Error ? error.message.toLowerCase() : String(error);
      if (
        !message.includes("not a database") &&
        !message.includes("malformed") &&
        !message.includes("encrypted")
      ) {
        throw error;
      }
      this.removeIndexFiles();
      this.replaceRecords(prepared);
    }
  }

  async upsert(record: MemoryRecord): Promise<void> {
    const [prepared] = await this.prepareRecords([record]);
    if (!prepared) return;
    const db = this.connect();
    try {
      this.ensureSchema(db);
      db.transaction(() => {
        this.upsertPrepared(db, prepared);
        this.writeCurrentMeta(db, prepared.vector.length);
      })();
    } finally {
      db.close();
    }
  }

  async delete(memoryId: string): Promise<void> {
    const db = this.connect();
    try {
      this.ensureSchema(db);
      db.run("delete from memory_index_records where memory_id = ?", [memoryId]);
      db.run("delete from memory_fts where memory_id = ?", [memoryId]);
      db.run("delete from memory_vectors where memory_id = ?", [memoryId]);
    } finally {
      db.close();
    }
  }

  async searchFts(
    query: string,
    target: string | null,
    limit: number,
  ): Promise<IndexCandidate[]> {
    if (!query.trim()) return [];
    const db = this.connect();
    try {
      this.ensureSchema(db);
      const rows = db
        .query(
          `select memory_fts.memory_id as memory_id
           from memory_fts
           join memory_index_records on memory_index_records.memory_id = memory_fts.memory_id
           where memory_fts match ?
             and (? is null or memory_index_records.target = ?)
           limit ?`,
        )
        .all(query, target, target, limit) as Array<{ memory_id: string }>;
      return rows.map((row) => ({
        memoryId: row.memory_id,
        channel: "fts" as const,
        score: 1,
        reason: `matched fts: ${query}`,
      }));
    } catch {
      return [];
    } finally {
      db.close();
    }
  }

  async searchVector(
    query: string,
    target: string | null,
    limit: number,
  ): Promise<IndexCandidate[]> {
    if (!query.trim()) return [];
    const queryVector = await this.provider.embedQuery(query);
    const dimensions = queryVector.length;
    const db = this.connect();
    try {
      this.ensureSchema(db);
      const rows = db
        .query(
          `select memory_vectors.memory_id as memory_id, memory_vectors.vector as vector
           from memory_vectors
           join memory_index_records on memory_index_records.memory_id = memory_vectors.memory_id
           where memory_vectors.provider = ?
             and memory_vectors.model = ?
             and memory_vectors.dimensions = ?
             and (? is null or memory_index_records.target = ?)`,
        )
        .all(
          this.provider.name,
          this.provider.model,
          dimensions,
          target,
          target,
        ) as Array<{ memory_id: string; vector: Uint8Array }>;

      const candidates: IndexCandidate[] = [];
      for (const row of rows) {
        const vector = unpackVector(new Uint8Array(row.vector), dimensions);
        const similarity = cosineSimilarity(queryVector, vector);
        if (similarity < this.minSimilarity) continue;
        candidates.push({
          memoryId: row.memory_id,
          channel: "semantic",
          score: similarity,
          reason: `matched semantic: ${similarity.toFixed(2)}`,
        });
      }
      candidates.sort((a, b) => b.score - a.score || a.memoryId.localeCompare(b.memoryId));
      return candidates.slice(0, Math.min(limit, this.topK));
    } finally {
      db.close();
    }
  }
}
