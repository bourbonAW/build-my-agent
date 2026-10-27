import type { MessageChain } from "./chain";

export interface TokenStatus {
  estimatedTokens: number;
  threshold: number;
  usageRatio: number;
  shouldCompact: boolean;
}

export class ContextManager {
  private lastActualInputTokens = 0;

  constructor(
    readonly chain: MessageChain,
    readonly tokenThreshold: number = 100000,
    readonly keepToolResults: number = 3,
    readonly compactPreserveCount: number = 3,
  ) {}

  recordResponseTokens(inputTokens: number): void {
    if (inputTokens > 0) {
      this.lastActualInputTokens = inputTokens;
    }
  }

  resetTokenEstimate(): void {
    this.lastActualInputTokens = 0;
  }

  estimateTokens(): number {
    if (this.lastActualInputTokens > 0) {
      return this.lastActualInputTokens;
    }
    return Math.floor(JSON.stringify(this.chain.getLlmMessages()).length / 4);
  }

  shouldCompact(): boolean {
    return this.estimateTokens() > this.tokenThreshold;
  }

  getStatus(): TokenStatus {
    const estimated = this.estimateTokens();
    return {
      estimatedTokens: estimated,
      threshold: this.tokenThreshold,
      usageRatio: this.tokenThreshold ? estimated / this.tokenThreshold : 0,
      shouldCompact: estimated > this.tokenThreshold,
    };
  }

  generateSummary(): string {
    const chain = this.chain.buildActiveChain();
    const users = chain.filter((message) => message.role === "user").length;
    const assistants = chain.filter((message) => message.role === "assistant").length;
    return `${users} user messages, ${assistants} assistant responses archived`;
  }

  microcompact(): void {
    const chain = this.chain.buildActiveChain();
    const toolResultMessages = chain.filter((message) =>
      message.content.some((block) => block.type === "tool_result"),
    );

    if (toolResultMessages.length <= this.keepToolResults) return;

    const toClear = toolResultMessages.slice(0, -this.keepToolResults);
    for (const message of toClear) {
      message.content = message.content.map((block) => {
        if (block.type === "tool_result" && block.content.length > 100) {
          return {
            ...block,
            content: "[cleared]",
            ...(block.is_error ? { is_error: true } : {}),
          };
        }
        return block;
      });
    }
  }
}
