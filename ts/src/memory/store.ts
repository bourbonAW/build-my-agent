import { createHash } from "node:crypto";
import {
  existsSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  renameSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import { join } from "node:path";
import { parse as parseYaml, stringify as stringifyYaml } from "yaml";
import type { MemoryRecord, MemorySearchResult, MemoryTarget } from "./models";
import { MEMORY_TARGETS, validateMemoryTarget } from "./models";
import { normalizeCues } from "./cues";

export const MEMORY_INDEX_LINE_LIMIT = 200;

export function sanitizeProjectKey(canonicalPath: string): string {
  const slug = canonicalPath
    .replace(/[/\\ ]/g, "-")
    .toLowerCase()
    .replace(/[^a-z0-9-]/g, "")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 64);
  return `${slug}-${createHash("sha256").update(canonicalPath).digest("hex").slice(0, 8)}`;
}

export function recordPreview(record: MemoryRecord, limit = 100): string {
  const firstLine = record.content.split("\n").find((line) => line.trim()) ?? "";
  return (firstLine.trim() || record.content.trim()).slice(0, limit).trimEnd();
}

function recordFilename(record: MemoryRecord): string {
  return `${record.id}.md`;
}

function recordToFileContent(record: MemoryRecord): string {
  const frontmatter: Record<string, unknown> = {
    id: record.id,
    target: record.target,
    created_at: record.createdAt,
  };
  if (record.cues.length) frontmatter.cues = record.cues;
  return `---\n${stringifyYaml(frontmatter, { lineWidth: 0 })}---\n\n${record.content.trimEnd()}\n`;
}

function parseFile(path: string): { frontmatter: Record<string, unknown>; body: string } {
  const text = readFileSync(path, "utf8");
  if (!text.startsWith("---\n")) return { frontmatter: {}, body: text };

  const endMarker = text.indexOf("\n---\n", 4);
  if (endMarker === -1) return { frontmatter: {}, body: text };

  const raw = text.slice(4, endMarker);
  const body = text.slice(endMarker + "\n---\n".length);
  const loaded = parseYaml(raw) ?? {};
  return {
    frontmatter:
      loaded && typeof loaded === "object" && !Array.isArray(loaded)
        ? (loaded as Record<string, unknown>)
        : {},
    body,
  };
}

function resolveTarget(frontmatter: Record<string, unknown>): MemoryTarget {
  for (const key of ["target", "scope", "kind"]) {
    const value = frontmatter[key];
    if (value === undefined || value === null) continue;
    const candidate = String(value);
    if ((MEMORY_TARGETS as string[]).includes(candidate)) {
      return candidate as MemoryTarget;
    }
  }
  throw new Error("target");
}

function frontmatterToRecord(
  frontmatter: Record<string, unknown>,
  body: string,
): MemoryRecord {
  const rawCues = Array.isArray(frontmatter.cues) ? frontmatter.cues : [];
  return {
    id: String(frontmatter.id),
    target: validateMemoryTarget(resolveTarget(frontmatter)),
    content: body.trim(),
    createdAt: String(frontmatter.created_at),
    cues: normalizeCues(rawCues),
  };
}

export class MemoryStore {
  private readonly idToFilename = new Map<string, string>();

  constructor(readonly memoryDir: string) {
    this.scanExisting();
  }

  private scanExisting(): void {
    if (!existsSync(this.memoryDir)) return;
    for (const name of readdirSync(this.memoryDir)) {
      if (!name.endsWith(".md") || name === "MEMORY.md") continue;
      try {
        const { frontmatter } = parseFile(join(this.memoryDir, name));
        if (frontmatter.id !== undefined) {
          this.idToFilename.set(String(frontmatter.id), name);
        }
      } catch {
        continue;
      }
    }
  }

  private atomicWrite(path: string, content: string): void {
    mkdirSync(this.memoryDir, { recursive: true });
    const temp = `${path}.${process.pid}.tmp`;
    writeFileSync(temp, content, "utf8");
    renameSync(temp, path);
  }

  writeRecord(record: MemoryRecord): string {
    mkdirSync(this.memoryDir, { recursive: true });
    const filename = recordFilename(record);
    const path = join(this.memoryDir, filename);
    this.atomicWrite(path, recordToFileContent(record));
    this.idToFilename.set(record.id, filename);
    this.rebuildIndex();
    return path;
  }

  deleteRecord(memoryId: string): void {
    let filename = this.idToFilename.get(memoryId);
    if (!filename) {
      this.scanExisting();
      filename = this.idToFilename.get(memoryId);
    }
    if (!filename) throw new Error(`Unknown memory id: ${memoryId}`);

    const path = join(this.memoryDir, filename);
    if (existsSync(path)) unlinkSync(path);
    this.idToFilename.delete(memoryId);
    this.rebuildIndex();
  }

  readRecord(memoryId: string): MemoryRecord | null {
    let filename = this.idToFilename.get(memoryId);
    if (!filename) {
      this.scanExisting();
      filename = this.idToFilename.get(memoryId);
    }
    if (!filename) return null;

    const path = join(this.memoryDir, filename);
    if (!existsSync(path)) return null;
    const { frontmatter, body } = parseFile(path);
    if (frontmatter.id === undefined) return null;
    return frontmatterToRecord(frontmatter, body);
  }

  listRecords(): MemoryRecord[] {
    if (!existsSync(this.memoryDir)) return [];
    const records: MemoryRecord[] = [];
    for (const name of readdirSync(this.memoryDir).sort()) {
      if (!name.endsWith(".md") || name === "MEMORY.md") continue;
      try {
        const { frontmatter, body } = parseFile(join(this.memoryDir, name));
        if (frontmatter.id === undefined) continue;
        records.push(frontmatterToRecord(frontmatter, body));
      } catch {
        continue;
      }
    }
    return records.sort((left, right) => right.createdAt.localeCompare(left.createdAt));
  }

  rebuildIndex(): boolean {
    const records = this.listRecords().slice(0, MEMORY_INDEX_LINE_LIMIT);
    const lines = records.map((record) => {
      const filename = recordFilename(record);
      return `- [${record.target}] ${recordPreview(record)} ([${filename}](${filename}))`;
    });
    const content = lines.length ? `${lines.join("\n")}\n` : "";
    this.atomicWrite(join(this.memoryDir, "MEMORY.md"), content);
    return records.length >= MEMORY_INDEX_LINE_LIMIT;
  }

  search(query: string, target: string | null = null, limit = 8): MemorySearchResult[] {
    const normalized = query.toLowerCase();
    const results: MemorySearchResult[] = [];

    for (const record of this.listRecords()) {
      if (target !== null && record.target !== target) continue;
      const contentMatch = record.content.toLowerCase().includes(normalized);
      const matchedCue = record.cues.find((cue) => cue.toLowerCase().includes(normalized));
      if (!contentMatch && matchedCue === undefined) continue;

      results.push({
        id: record.id,
        target: record.target,
        snippet: recordPreview(record),
        whyMatched:
          matchedCue !== undefined ? `matched cue: ${matchedCue}` : `matched content: ${query}`,
      });
      if (results.length >= limit) break;
    }

    return results;
  }
}
