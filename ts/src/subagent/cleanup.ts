import type { SubagentRun } from "./types";

export class ResourceManager {
  private readonly runs = new Map<string, SubagentRun>();

  constructor(registerExitHook = true) {
    if (registerExitHook) {
      process.once("exit", () => this.cleanupAll());
    }
  }

  register(run: SubagentRun): void {
    this.runs.set(run.runId, run);
  }

  cleanupAll(): void {
    for (const run of this.runs.values()) {
      if (run.status === "running") this.cleanupRun(run);
    }
  }

  cleanupRun(run: SubagentRun): void {
    run.abortController.abort();
    try {
      run.subagent?.shutdownMCP?.();
    } catch {
      // best-effort cleanup
    }
    run.status = "killed";
  }
}
