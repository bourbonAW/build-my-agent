import type { Session } from "../session/manager";
import { SessionManager } from "../session/manager";
import type { TranscriptStore } from "../session/storage";

export class SubagentSessionAdapter {
  readonly projectName: string;

  constructor(
    private readonly parentStore: TranscriptStore,
    projectName: string,
    private readonly projectDir: string,
    private readonly runId: string,
  ) {
    this.projectName = `${projectName}/subagents`;
  }

  createSession(): Session {
    const manager = new SessionManager(
      this.parentStore,
      this.projectName,
      this.projectDir,
    );
    return manager.createSession(undefined, null, `Subagent run ${this.runId}`);
  }
}
