export type MemoryTarget = "user" | "project";
export const MEMORY_TARGETS: MemoryTarget[] = ["user", "project"];

export function validateMemoryTarget(value: string): MemoryTarget {
  if (value !== "user" && value !== "project") {
    throw new Error(
      `Invalid memory target ${JSON.stringify(value)}; expected one of: ${MEMORY_TARGETS.join(", ")}`,
    );
  }
  return value;
}

export type MemoryActorKind = "user" | "agent" | "subagent" | "system";

export interface MemoryActor {
  kind: MemoryActorKind;
  sessionId?: string;
  runId?: string;
  agentType?: string;
}

export interface MemoryRecordDraft {
  target: MemoryTarget;
  content: string;
}

export interface MemoryRecord {
  id: string;
  target: MemoryTarget;
  content: string;
  createdAt: string;
  cues: string[];
}

export interface MemorySearchResult {
  id: string;
  target: MemoryTarget;
  snippet: string;
  whyMatched: string;
}

export interface RecentWriteSummary {
  id: string;
  target: MemoryTarget;
  preview: string;
  createdAt: string;
}

export interface MemorySystemInfo {
  readableTargets: string[];
  writableTargets: string[];
  recentWrites: RecentWriteSummary[];
  indexAtCapacity: boolean;
  memoryFileCount: number;
}
