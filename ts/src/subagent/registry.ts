import type { RunStatus, SubagentRun } from "./types";

export class RunRegistry {
  private readonly runs = new Map<string, SubagentRun>();

  register(run: SubagentRun): void {
    this.runs.set(run.runId, run);
  }

  get(runId: string): SubagentRun | undefined {
    return this.runs.get(runId);
  }

  list(filter: { status?: RunStatus; agentType?: string } = {}): SubagentRun[] {
    return [...this.runs.values()].filter(
      (run) =>
        (filter.status === undefined || run.status === filter.status) &&
        (filter.agentType === undefined || run.agentType === filter.agentType),
    );
  }

  updateStatus(runId: string, status: RunStatus): boolean {
    const run = this.runs.get(runId);
    if (!run) return false;
    run.status = status;
    if (status === "running" && !run.startedAt) run.startedAt = new Date().toISOString();
    return true;
  }

  complete(runId: string, result: string): boolean {
    const run = this.runs.get(runId);
    if (!run) return false;
    run.status = "completed";
    run.result = result;
    run.completedAt = new Date().toISOString();
    return true;
  }

  fail(runId: string, error: string): boolean {
    const run = this.runs.get(runId);
    if (!run) return false;
    run.status = "failed";
    run.error = error;
    run.completedAt = new Date().toISOString();
    return true;
  }
}
