import { appendFileSync, existsSync, mkdirSync, writeFileSync } from "node:fs";
import { randomUUID } from "node:crypto";
import { join } from "node:path";
import type { AuditEvent } from "./events";

export class AuditLogger {
  readonly events: AuditEvent[] = [];
  readonly logFile: string | null = null;

  constructor(
    readonly logDir: string,
    readonly enabled = true,
  ) {
    if (!enabled) return;
    mkdirSync(logDir, { recursive: true });
    this.logFile = join(logDir, `session-${randomUUID().replaceAll("-", "")}.jsonl`);
    if (!existsSync(this.logFile)) writeFileSync(this.logFile, "", "utf8");
  }

  record(event: AuditEvent): void {
    if (!this.enabled || !this.logFile) return;
    appendFileSync(this.logFile, `${JSON.stringify(event.toDict())}\n`, "utf8");
    this.events.push(event);
  }

  query(filters: Record<string, unknown> = {}): AuditEvent[] {
    if (!this.enabled) return [];
    return this.events.filter((event) =>
      Object.entries(filters).every(([key, value]) => {
        if (key === "event_type") return event.eventType === value;
        if (key === "timestamp") return event.timestamp === value;
        if (key === "extra") return JSON.stringify(event.extra) === JSON.stringify(value);
        if (key in event) return (event as unknown as Record<string, unknown>)[key] === value;
        return event.extra[key] === value;
      }),
    );
  }

  summary(): Record<string, number> {
    let policyDenied = 0;
    let policyNeedApproval = 0;
    let sandboxExecutions = 0;
    let violations = 0;

    for (const event of this.events) {
      if (event.eventType === "policy_decision") {
        if (event.extra.decision === "deny") policyDenied += 1;
        else if (event.extra.decision === "need_approval") policyNeedApproval += 1;
      } else if (event.eventType === "sandbox_exec") {
        sandboxExecutions += 1;
      } else if (event.eventType === "sandbox_violation") {
        violations += 1;
      }
    }

    return {
      total_events: this.events.length,
      policy_denied: policyDenied,
      policy_need_approval: policyNeedApproval,
      sandbox_executions: sandboxExecutions,
      violations,
    };
  }
}
