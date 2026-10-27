import { randomBytes } from "node:crypto";
import { buildMatchCandidate } from "./matching";
import type { PermissionDecision, PermissionRequest } from "./runtime";

export function buildPermissionRequest(options: {
  toolName: string;
  toolInput: Record<string, unknown>;
  toolUseId: string;
  decision: PermissionDecision;
  workdir: string;
}): PermissionRequest {
  const { toolName, toolInput, toolUseId, decision, workdir } = options;

  let title: string;
  let description: string;

  if (toolName === "Bash") {
    title = "Bash command";
    description = String(toolInput.command ?? "");
  } else if (toolName === "Write") {
    title = "Write file";
    description = `${String(toolInput.path)} (${String(toolInput.content ?? "").length} chars)`;
  } else if (toolName === "Edit") {
    title = "Edit file";
    description = String(toolInput.path ?? "");
  } else {
    title = `${toolName} request`;
    description = JSON.stringify(toolInput);
  }

  return {
    requestId: `perm-${randomBytes(4).toString("hex")}`,
    toolUseId,
    toolName,
    toolInput,
    title,
    description,
    reason: decision.reason,
    matchCandidate: buildMatchCandidate(toolName, toolInput, workdir),
    options: ["allow_once", "allow_session", "reject"],
  };
}
