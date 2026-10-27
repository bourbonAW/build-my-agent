import { randomUUID } from "node:crypto";
import type { Message } from "../llm";
import { MessageChain } from "./chain";
import { ContextManager } from "./context";
import { TranscriptStore } from "./storage";
import type {
  CompactResult,
  CompactTrigger,
  SessionMetadata,
  SessionSummary,
  TranscriptMessage,
} from "./types";

export class Session {
  readonly chain = new MessageChain();
  readonly contextManager: ContextManager;

  constructor(
    readonly metadata: SessionMetadata,
    readonly store: TranscriptStore,
    readonly projectName: string,
    tokenThreshold = 100000,
    keepToolResults = 3,
    readonly compactPreserveCount = 3,
  ) {
    this.contextManager = new ContextManager(
      this.chain,
      tokenThreshold,
      keepToolResults,
      compactPreserveCount,
    );
  }

  get sessionId(): string {
    return this.metadata.uuid;
  }

  addMessage(message: TranscriptMessage): void {
    message.sessionId = this.metadata.uuid;
    this.chain.append(message);
    this.store.appendToTranscript(this.projectName, this.metadata.uuid, [message]);
    this.metadata.messageCount += 1;
    if (message.usage) {
      this.metadata.totalTokensUsed += message.usage.totalTokens;
    }
    this.metadata.lastActivity = new Date().toISOString();
  }

  getMessagesForLlm(): Message[] {
    return this.chain.getLlmMessages();
  }

  save(): void {
    this.store.saveMetadata(this.projectName, this.metadata);
  }

  maybeCompact(trigger: CompactTrigger = "auto_threshold"): CompactResult | null {
    if (trigger === "auto_threshold" && !this.contextManager.shouldCompact()) {
      return null;
    }

    const result = this.chain.compact(
      this.compactPreserveCount,
      this.contextManager.generateSummary(),
      trigger,
    );

    if (result.success && result.boundaryUuid) {
      this.contextManager.resetTokenEstimate();
      const boundary = this.chain.get(result.boundaryUuid);
      if (boundary) {
        this.store.appendToTranscript(this.projectName, this.metadata.uuid, [boundary]);
      }
      this.store.saveCompactManifest(
        this.projectName,
        this.metadata.uuid,
        result.parentUuidOverrides,
      );
      this.save();
    }
    return result;
  }

  loadAndRebuild(): void {
    const transcript = this.store.loadTranscript(this.projectName, this.metadata.uuid);
    const overrides = this.store.loadCompactManifest(this.projectName, this.metadata.uuid);
    this.chain.rebuildFromTranscript(transcript, undefined, overrides);
  }
}

export class SessionManager {
  constructor(
    readonly store: TranscriptStore,
    readonly projectName: string,
    readonly projectDir = "",
    readonly tokenThreshold = 100000,
    readonly keepToolResults = 3,
    readonly compactPreserveCount = 3,
  ) {}

  createSession(
    sessionId?: string,
    parentUuid?: string | null,
    description = "",
  ): Session {
    const now = new Date().toISOString();
    const metadata: SessionMetadata = {
      uuid: sessionId ?? randomUUID(),
      parentUuid: parentUuid ?? null,
      projectDir: this.projectDir,
      createdAt: now,
      lastActivity: now,
      messageCount: 0,
      totalTokensUsed: 0,
      isActive: true,
      description,
    };
    const session = new Session(
      metadata,
      this.store,
      this.projectName,
      this.tokenThreshold,
      this.keepToolResults,
      this.compactPreserveCount,
    );
    session.save();
    return session;
  }

  resumeSession(sessionId: string): Session | null {
    const metadata = this.store.loadMetadata(this.projectName, sessionId);
    if (!metadata) return null;
    const session = new Session(
      metadata,
      this.store,
      this.projectName,
      this.tokenThreshold,
      this.keepToolResults,
      this.compactPreserveCount,
    );
    session.loadAndRebuild();
    return session;
  }

  resumeLatest(): Session | null {
    const summary = this.listSessions().find((item) => item.isResumable);
    return summary ? this.resumeSession(summary.uuid) : null;
  }

  listSessions(): SessionSummary[] {
    return this.store.listSessions(this.projectName);
  }

  deleteSession(sessionId: string): boolean {
    return this.store.deleteSession(this.projectName, sessionId);
  }
}
