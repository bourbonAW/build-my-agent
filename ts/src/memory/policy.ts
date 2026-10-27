import type { MemoryActor, MemoryTarget } from "./models";

export function checkWritePermission(actor: MemoryActor, target: MemoryTarget): boolean {
  if (actor.kind === "subagent") return target === "project";
  return ["user", "agent", "system"].includes(actor.kind);
}

export function checkDeletePermission(actor: MemoryActor): void {
  if (actor.kind === "subagent") {
    throw new Error("Subagents cannot delete memory records");
  }
}
