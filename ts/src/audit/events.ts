export type EventType =
  | "policy_decision"
  | "sandbox_exec"
  | "sandbox_violation"
  | "tool_call"
  | "memory_write"
  | "memory_search"
  | "memory_delete";

const RESERVED_KEYS = new Set(["timestamp", "event_type", "tool_name", "tool_input_summary"]);

export class AuditEvent {
  constructor(
    readonly timestamp: string,
    readonly eventType: EventType,
    readonly toolName: string,
    readonly toolInputSummary: string,
    readonly extra: Record<string, unknown> = {},
  ) {}

  toDict(): Record<string, unknown> {
    const collisions = Object.keys(this.extra).filter((key) => RESERVED_KEYS.has(key));
    if (collisions.length) {
      throw new Error(`extra contains reserved audit field(s): ${collisions.sort().join(", ")}`);
    }
    return {
      timestamp: this.timestamp,
      event_type: this.eventType,
      tool_name: this.toolName,
      tool_input_summary: this.toolInputSummary,
      ...this.extra,
    };
  }

  static create(
    eventType: EventType,
    fields: {
      toolName: string;
      toolInputSummary: string;
      extra?: Record<string, unknown>;
    },
  ): AuditEvent {
    return new AuditEvent(
      new Date().toISOString(),
      eventType,
      fields.toolName,
      fields.toolInputSummary,
      fields.extra ?? {},
    );
  }

  static policyDecision(
    toolName: string,
    toolInputSummary: string,
    extra: Record<string, unknown> = {},
  ): AuditEvent {
    return AuditEvent.create("policy_decision", {
      toolName,
      toolInputSummary,
      extra,
    });
  }

  static sandboxExec(
    toolName: string,
    toolInputSummary: string,
    extra: Record<string, unknown> = {},
  ): AuditEvent {
    return AuditEvent.create("sandbox_exec", { toolName, toolInputSummary, extra });
  }

  static sandboxViolation(
    toolName: string,
    toolInputSummary: string,
    extra: Record<string, unknown> = {},
  ): AuditEvent {
    return AuditEvent.create("sandbox_violation", { toolName, toolInputSummary, extra });
  }

  static toolCall(
    toolName: string,
    toolInputSummary: string,
    extra: Record<string, unknown> = {},
  ): AuditEvent {
    return AuditEvent.create("tool_call", { toolName, toolInputSummary, extra });
  }
}
