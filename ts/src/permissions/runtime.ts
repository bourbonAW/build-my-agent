import type { ToolResultBlock, ToolUseBlock } from "../llm";
import type { MatchCandidate } from "./matching";
import { sessionRuleMatches } from "./matching";

export type PermissionAction = "allow" | "ask" | "deny";
export type PermissionChoice = "allow_once" | "allow_session" | "reject";

export interface PermissionDecision {
  action: PermissionAction;
  reason: string;
  title?: string;
  description?: string;
  matchCandidate?: MatchCandidate;
}

export interface PermissionRequest {
  requestId: string;
  toolUseId: string;
  toolName: string;
  toolInput: Record<string, unknown>;
  title: string;
  description: string;
  reason: string;
  matchCandidate?: MatchCandidate;
  options: [PermissionChoice, PermissionChoice, PermissionChoice];
}

export interface SuspendedToolRound {
  toolUseBlocks: ToolUseBlock[];
  completedResults: ToolResultBlock[];
  nextToolIndex: number;
  activeRequest: PermissionRequest;
}

export class SessionPermissionStore {
  private readonly rules: MatchCandidate[] = [];

  add(candidate: MatchCandidate): void {
    this.rules.push({ ...candidate });
  }

  hasMatch(
    toolName: string,
    toolInput: Record<string, unknown>,
    workdir: string,
  ): boolean {
    return this.rules.some((rule) =>
      sessionRuleMatches(rule, toolName, toolInput, workdir),
    );
  }
}
