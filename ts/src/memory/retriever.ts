import type { MemoryRecord, MemorySearchResult } from "./models";
import type { IndexCandidate } from "./search_index";
import { recordPreview, type MemoryStore } from "./store";

export interface SearchIndex {
  searchFts(query: string, target: string | null, limit: number): Promise<IndexCandidate[]>;
  searchVector(query: string, target: string | null, limit: number): Promise<IndexCandidate[]>;
  rebuild(records: MemoryRecord[]): Promise<void>;
}

interface Ranked {
  score: number;
  reason: string;
}

export class MemoryRetriever {
  constructor(
    private readonly store: MemoryStore,
    private readonly index: SearchIndex,
  ) {}

  async rebuildIndex(): Promise<void> {
    await this.index.rebuild(this.store.listRecords());
  }

  async search(options: {
    query: string;
    terms: string[];
    target: string | null;
    limit: number;
  }): Promise<MemorySearchResult[]> {
    const { query, terms, target, limit } = options;
    const ranked = new Map<string, Ranked>();

    for (const term of terms) {
      for (const result of this.store.search(term, target, limit)) {
        const entry = ranked.get(result.id) ?? { score: 0, reason: "" };
        entry.score += result.whyMatched.startsWith("matched cue:") ? 3.2 : 3.0;
        if (!entry.reason) entry.reason = result.whyMatched;
        ranked.set(result.id, entry);
      }
    }

    for (const candidate of await this.safeFts(query, target, limit)) {
      const entry = ranked.get(candidate.memoryId) ?? { score: 0, reason: "" };
      entry.score += 1.5 * candidate.score;
      if (!entry.reason) entry.reason = candidate.reason;
      ranked.set(candidate.memoryId, entry);
    }

    for (const candidate of await this.safeVector(query, target, limit)) {
      const entry = ranked.get(candidate.memoryId) ?? { score: 0, reason: "" };
      entry.score += 1.2 * candidate.score;
      if (!entry.reason) entry.reason = candidate.reason;
      ranked.set(candidate.memoryId, entry);
    }

    const ordered = [...ranked.entries()].sort(
      ([idA, a], [idB, b]) => b.score - a.score || idA.localeCompare(idB),
    );

    const results: MemorySearchResult[] = [];
    for (const [memoryId, entry] of ordered) {
      const record = this.store.readRecord(memoryId);
      if (!record) continue;
      if (target !== null && record.target !== target) continue;
      results.push({
        id: record.id,
        target: record.target,
        snippet: recordPreview(record),
        whyMatched: entry.reason,
      });
      if (results.length >= limit) break;
    }
    return results;
  }

  private async safeFts(
    query: string,
    target: string | null,
    limit: number,
  ): Promise<IndexCandidate[]> {
    try {
      return await this.index.searchFts(query, target, limit);
    } catch {
      return [];
    }
  }

  private async safeVector(
    query: string,
    target: string | null,
    limit: number,
  ): Promise<IndexCandidate[]> {
    try {
      return await this.index.searchVector(query, target, limit);
    } catch {
      return [];
    }
  }
}
