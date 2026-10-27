import type { Message } from "../llm";
import type { CompactResult, CompactTrigger, TranscriptMessage } from "./types";
import { createTranscriptMessage, toLlmMessage } from "./types";

export class MessageChain {
  private readonly messages = new Map<string, TranscriptMessage>();
  private leafUuid: string | null = null;
  private rootUuid: string | null = null;

  get leaf(): string | null {
    return this.leafUuid;
  }

  get messageCount(): number {
    return this.messages.size;
  }

  append(message: TranscriptMessage): void {
    if (this.leafUuid) {
      message.parentUuid = this.leafUuid;
    } else {
      this.rootUuid = message.uuid;
    }
    this.messages.set(message.uuid, message);
    this.leafUuid = message.uuid;
  }

  get(uuid: string): TranscriptMessage | undefined {
    return this.messages.get(uuid);
  }

  buildActiveChain(): TranscriptMessage[] {
    const chain: TranscriptMessage[] = [];
    const seen = new Set<string>();
    let current = this.leafUuid;

    while (current && !seen.has(current)) {
      seen.add(current);
      const message = this.messages.get(current);
      if (!message) break;
      chain.push(message);
      current = message.parentUuid;
    }

    chain.reverse();
    return chain;
  }

  getLlmMessages(): Message[] {
    return this.buildActiveChain()
      .filter((message) => !message.isCompactBoundary && !message.isSidechain)
      .map(toLlmMessage);
  }

  compact(
    preserveCount = 3,
    summary = "",
    trigger: CompactTrigger = "auto_threshold",
  ): CompactResult {
    const chain = this.buildActiveChain();
    if (chain.length <= preserveCount) {
      return {
        success: false,
        archivedCount: 0,
        preservedCount: chain.length,
        boundaryUuid: null,
        reason: `insufficient_messages: ${chain.length} <= ${preserveCount}`,
        parentUuidOverrides: {},
      };
    }

    const toArchive = chain.slice(0, -preserveCount);
    const toPreserve = chain.slice(-preserveCount);
    const firstArchived = toArchive[0]!;
    const lastArchived = toArchive.at(-1)!;
    const firstPreserved = toPreserve[0]!;

    const boundary = createTranscriptMessage(
      "system",
      [{ type: "text", text: `[Context compressed: ${summary}]` }],
      {
        isCompactBoundary: true,
        compactMetadata: {
          trigger,
          preCompactTokenCount: toArchive.length,
          postCompactTokenCount: toPreserve.length,
          firstArchivedUuid: firstArchived.uuid,
          lastArchivedUuid: lastArchived.uuid,
          summary,
          archivedAt: new Date().toISOString(),
        },
      },
    );

    for (const message of toArchive) {
      this.messages.delete(message.uuid);
    }

    boundary.parentUuid = null;
    boundary.logicalParentUuid = lastArchived.uuid;
    this.messages.set(boundary.uuid, boundary);

    firstPreserved.parentUuid = boundary.uuid;
    firstPreserved.logicalParentUuid = lastArchived.uuid;

    this.leafUuid = toPreserve.at(-1)!.uuid;
    this.rootUuid = boundary.uuid;

    return {
      success: true,
      archivedCount: toArchive.length,
      preservedCount: toPreserve.length,
      boundaryUuid: boundary.uuid,
      reason: "",
      parentUuidOverrides: {
        [boundary.uuid]: null,
        [firstPreserved.uuid]: boundary.uuid,
      },
    };
  }

  clear(): void {
    this.messages.clear();
    this.leafUuid = null;
    this.rootUuid = null;
  }

  rebuildFromTranscript(
    transcript: TranscriptMessage[],
    resumeFrom?: string,
    parentUuidOverrides: Record<string, string | null> = {},
  ): void {
    this.clear();
    if (!transcript.length) return;

    const messageMap = new Map(transcript.map((message) => [message.uuid, message]));
    for (const [uuid, parent] of Object.entries(parentUuidOverrides)) {
      const message = messageMap.get(uuid);
      if (message) message.parentUuid = parent;
    }

    let start = resumeFrom;
    if (!start) {
      for (let index = transcript.length - 1; index >= 0; index -= 1) {
        const message = transcript[index]!;
        if (!message.isCompactBoundary) {
          start = message.uuid;
          break;
        }
      }
    }
    if (!start || !messageMap.has(start)) return;

    const chain: TranscriptMessage[] = [];
    const seen = new Set<string>();
    let current: string | null = start;

    while (current && !seen.has(current)) {
      seen.add(current);
      const message = messageMap.get(current);
      if (!message) break;
      chain.push(message);
      current = message.parentUuid;
    }

    chain.reverse();
    for (const message of chain) {
      this.messages.set(message.uuid, message);
    }
    if (chain.length) {
      this.rootUuid = chain[0]!.uuid;
      this.leafUuid = chain.at(-1)!.uuid;
    }
  }
}

export function buildConversationFromTranscript(
  transcript: TranscriptMessage[],
): TranscriptMessage[] {
  if (!transcript.length) return [];
  const messageMap = new Map(transcript.map((message) => [message.uuid, message]));
  let current: string | null = null;
  for (let index = transcript.length - 1; index >= 0; index -= 1) {
    const message = transcript[index]!;
    if (!message.isCompactBoundary) {
      current = message.uuid;
      break;
    }
  }
  if (!current) return [];

  const chain: TranscriptMessage[] = [];
  const seen = new Set<string>();
  while (current && !seen.has(current)) {
    seen.add(current);
    const message = messageMap.get(current);
    if (!message) break;
    chain.push(message);
    current = message.logicalParentUuid ?? message.parentUuid;
  }
  chain.reverse();
  return chain;
}
