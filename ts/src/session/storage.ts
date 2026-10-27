import {
  appendFileSync,
  existsSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  renameSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import { dirname, join } from "node:path";
import type {
  CompactMetadata,
  SessionMetadata,
  SessionSummary,
  TranscriptMessage,
} from "./types";

interface SerializedBlock {
  type: string;
  text?: string;
  id?: string;
  name?: string;
  input?: Record<string, unknown>;
  tool_use_id?: string;
  content?: string;
  is_error?: boolean;
}

function messageToDict(message: TranscriptMessage): Record<string, unknown> {
  const result: Record<string, unknown> = {
    uuid: message.uuid,
    session_id: message.sessionId,
    role: message.role,
    content: message.content,
    timestamp: message.timestamp,
    parent_uuid: message.parentUuid,
    logical_parent_uuid: message.logicalParentUuid,
    source_tool_uuid: message.sourceToolUuid,
    is_sidechain: message.isSidechain,
    agent_id: message.agentId,
    is_compact_boundary: message.isCompactBoundary,
  };
  if (message.usage) {
    result.usage = {
      input_tokens: message.usage.inputTokens,
      output_tokens: message.usage.outputTokens,
      total_tokens: message.usage.totalTokens,
    };
  }
  if (message.compactMetadata) {
    const meta = message.compactMetadata;
    result.compact_metadata = {
      trigger: meta.trigger,
      pre_compact_token_count: meta.preCompactTokenCount,
      post_compact_token_count: meta.postCompactTokenCount,
      first_archived_uuid: meta.firstArchivedUuid,
      last_archived_uuid: meta.lastArchivedUuid,
      summary: meta.summary,
      archived_at: meta.archivedAt,
    };
  }
  return result;
}

function dictToMessage(data: Record<string, unknown>): TranscriptMessage {
  const usage = data.usage as
    | { input_tokens?: number; output_tokens?: number; total_tokens?: number }
    | undefined;
  const compact = data.compact_metadata as Record<string, unknown> | undefined;

  const message: TranscriptMessage = {
    uuid: String(data.uuid),
    sessionId: String(data.session_id),
    parentUuid: data.parent_uuid ? String(data.parent_uuid) : null,
    logicalParentUuid: data.logical_parent_uuid ? String(data.logical_parent_uuid) : null,
    role: data.role as TranscriptMessage["role"],
    content: (data.content as SerializedBlock[]).map((block) => {
      if (block.type === "text") return { type: "text", text: block.text ?? "" };
      if (block.type === "tool_use") {
        return {
          type: "tool_use",
          id: block.id ?? "",
          name: block.name ?? "",
          input: block.input ?? {},
        };
      }
      if (block.type === "tool_result") {
        return {
          type: "tool_result",
          tool_use_id: block.tool_use_id ?? "",
          content: block.content ?? "",
          ...(block.is_error ? { is_error: true } : {}),
        };
      }
      return { type: "text", text: String(block) };
    }) as TranscriptMessage["content"],
    timestamp: String(data.timestamp),
    sourceToolUuid: data.source_tool_uuid ? String(data.source_tool_uuid) : null,
    isSidechain: Boolean(data.is_sidechain),
    agentId: data.agent_id ? String(data.agent_id) : null,
    isCompactBoundary: Boolean(data.is_compact_boundary),
  };

  if (usage) {
    message.usage = {
      inputTokens: usage.input_tokens ?? 0,
      outputTokens: usage.output_tokens ?? 0,
      totalTokens: usage.total_tokens ?? 0,
    };
  }

  if (compact) {
    message.compactMetadata = {
      trigger: compact.trigger as CompactMetadata["trigger"],
      preCompactTokenCount: Number(compact.pre_compact_token_count ?? 0),
      postCompactTokenCount: Number(compact.post_compact_token_count ?? 0),
      firstArchivedUuid: String(compact.first_archived_uuid ?? ""),
      lastArchivedUuid: String(compact.last_archived_uuid ?? ""),
      summary: String(compact.summary ?? ""),
      archivedAt: String(compact.archived_at ?? ""),
    };
  }

  return message;
}

function writeJsonAtomic(path: string, payload: unknown): void {
  mkdirSync(dirname(path), { recursive: true });
  const temp = `${path}.${process.pid}.tmp`;
  writeFileSync(temp, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
  renameSync(temp, path);
}

export class TranscriptStore {
  constructor(readonly baseDir: string) {}

  private sessionDir(projectName: string): string {
    return join(this.baseDir, projectName);
  }

  private transcriptPath(projectName: string, sessionId: string): string {
    return join(this.sessionDir(projectName), `${sessionId}.jsonl`);
  }

  private metadataPath(projectName: string, sessionId: string): string {
    return join(this.sessionDir(projectName), `${sessionId}.meta.json`);
  }

  private compactManifestPath(projectName: string, sessionId: string): string {
    return join(this.sessionDir(projectName), `${sessionId}.compact.json`);
  }

  appendToTranscript(
    projectName: string,
    sessionId: string,
    messages: TranscriptMessage[],
  ): void {
    if (!messages.length) return;
    const path = this.transcriptPath(projectName, sessionId);
    mkdirSync(dirname(path), { recursive: true });
    const lines = messages
      .map((message) => JSON.stringify(messageToDict(message)))
      .join("\n");
    appendFileSync(path, `${lines}\n`, "utf8");
  }

  loadTranscript(projectName: string, sessionId: string): TranscriptMessage[] {
    const path = this.transcriptPath(projectName, sessionId);
    if (!existsSync(path)) return [];

    const messages: TranscriptMessage[] = [];
    for (const line of readFileSync(path, "utf8").split("\n")) {
      if (!line.trim()) continue;
      try {
        messages.push(dictToMessage(JSON.parse(line) as Record<string, unknown>));
      } catch {
        continue;
      }
    }
    return messages;
  }

  saveMetadata(projectName: string, metadata: SessionMetadata): void {
    writeJsonAtomic(this.metadataPath(projectName, metadata.uuid), {
      uuid: metadata.uuid,
      parent_uuid: metadata.parentUuid,
      project_dir: metadata.projectDir,
      created_at: metadata.createdAt,
      last_activity: metadata.lastActivity,
      message_count: metadata.messageCount,
      total_tokens_used: metadata.totalTokensUsed,
      is_active: metadata.isActive,
      description: metadata.description,
    });
  }

  loadMetadata(projectName: string, sessionId: string): SessionMetadata | null {
    const path = this.metadataPath(projectName, sessionId);
    if (!existsSync(path)) return null;
    try {
      const data = JSON.parse(readFileSync(path, "utf8")) as Record<string, unknown>;
      return {
        uuid: String(data.uuid),
        parentUuid: data.parent_uuid ? String(data.parent_uuid) : null,
        projectDir: String(data.project_dir ?? ""),
        createdAt: String(data.created_at),
        lastActivity: String(data.last_activity),
        messageCount: Number(data.message_count ?? 0),
        totalTokensUsed: Number(data.total_tokens_used ?? 0),
        isActive: Boolean(data.is_active ?? true),
        description: String(data.description ?? ""),
      };
    } catch {
      return null;
    }
  }

  saveCompactManifest(
    projectName: string,
    sessionId: string,
    overrides: Record<string, string | null>,
  ): void {
    writeJsonAtomic(this.compactManifestPath(projectName, sessionId), {
      overrides,
    });
  }

  loadCompactManifest(projectName: string, sessionId: string): Record<string, string | null> {
    const path = this.compactManifestPath(projectName, sessionId);
    if (!existsSync(path)) return {};
    try {
      const data = JSON.parse(readFileSync(path, "utf8")) as {
        overrides?: Record<string, string | null>;
      };
      return data.overrides ?? {};
    } catch {
      return {};
    }
  }

  listSessions(projectName: string): SessionSummary[] {
    const directory = this.sessionDir(projectName);
    if (!existsSync(directory)) return [];

    const summaries: SessionSummary[] = [];
    for (const name of readdirSync(directory)) {
      if (!name.endsWith(".meta.json")) continue;
      const sessionId = name.slice(0, -".meta.json".length);
      const metadata = this.loadMetadata(projectName, sessionId);
      if (!metadata) continue;
      summaries.push({
        uuid: metadata.uuid,
        description: metadata.description,
        lastActivity: metadata.lastActivity,
        messageCount: metadata.messageCount,
        isResumable: metadata.isActive,
      });
    }

    return summaries.sort((left, right) => right.lastActivity.localeCompare(left.lastActivity));
  }

  deleteSession(projectName: string, sessionId: string): boolean {
    let deleted = false;
    for (const path of [
      this.transcriptPath(projectName, sessionId),
      this.metadataPath(projectName, sessionId),
      this.compactManifestPath(projectName, sessionId),
    ]) {
      if (existsSync(path)) {
        unlinkSync(path);
        deleted = true;
      }
    }
    return deleted;
  }
}
