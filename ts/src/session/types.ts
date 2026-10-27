import { randomUUID } from "node:crypto";
import type { Message, ToolResultBlock, ToolUseBlock, TextBlock } from "../llm";

export type MessageRole = "user" | "assistant" | "system";
export type CompactTrigger = "manual" | "auto_threshold" | "auto_emergency";

export interface SessionTokenUsage {
  inputTokens: number;
  outputTokens: number;
  totalTokens: number;
}

export interface CompactMetadata {
  trigger: CompactTrigger;
  preCompactTokenCount: number;
  postCompactTokenCount: number;
  firstArchivedUuid: string;
  lastArchivedUuid: string;
  summary: string;
  archivedAt: string;
}

export interface TranscriptMessage {
  uuid: string;
  sessionId: string;
  parentUuid: string | null;
  logicalParentUuid: string | null;
  role: MessageRole;
  content: Array<TextBlock | ToolUseBlock | ToolResultBlock>;
  timestamp: string;
  usage?: SessionTokenUsage;
  sourceToolUuid: string | null;
  isSidechain: boolean;
  agentId: string | null;
  isCompactBoundary: boolean;
  compactMetadata?: CompactMetadata;
}

export interface SessionMetadata {
  uuid: string;
  parentUuid: string | null;
  projectDir: string;
  createdAt: string;
  lastActivity: string;
  messageCount: number;
  totalTokensUsed: number;
  isActive: boolean;
  description: string;
}

export interface SessionSummary {
  uuid: string;
  description: string;
  lastActivity: string;
  messageCount: number;
  isResumable: boolean;
}

export interface CompactResult {
  success: boolean;
  archivedCount: number;
  preservedCount: number;
  boundaryUuid: string | null;
  reason: string;
  parentUuidOverrides: Record<string, string | null>;
}

export function createTranscriptMessage(
  role: MessageRole,
  content: TranscriptMessage["content"],
  options: Partial<Omit<TranscriptMessage, "uuid" | "role" | "content" | "timestamp">> = {},
): TranscriptMessage {
  return {
    uuid: randomUUID(),
    sessionId: options.sessionId ?? randomUUID(),
    parentUuid: options.parentUuid ?? null,
    logicalParentUuid: options.logicalParentUuid ?? null,
    role,
    content,
    timestamp: new Date().toISOString(),
    sourceToolUuid: options.sourceToolUuid ?? null,
    isSidechain: options.isSidechain ?? false,
    agentId: options.agentId ?? null,
    isCompactBoundary: options.isCompactBoundary ?? false,
    ...(options.usage ? { usage: options.usage } : {}),
    ...(options.compactMetadata ? { compactMetadata: options.compactMetadata } : {}),
  };
}

export function toLlmMessage(message: TranscriptMessage): Message {
  return {
    role: message.role === "assistant" ? "assistant" : "user",
    content: message.content.map((block) => ({ ...block })),
  };
}
