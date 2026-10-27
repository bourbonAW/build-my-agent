import { homedir } from "node:os";
import { isAbsolute, resolve } from "node:path";
import type { AccessControlConfig } from "../config";
import type { CapabilityType, InferredContext } from "./capabilities";

export type PolicyAction = "allow" | "deny" | "need_approval";

export interface CapabilityDecision {
  capability: CapabilityType;
  action: PolicyAction;
  matchedRule: string | null;
}

export class PolicyDecision {
  constructor(
    readonly action: PolicyAction,
    readonly reason: string,
    readonly decisions: CapabilityDecision[] = [],
  ) {}

  get deniedCapability(): CapabilityType | null {
    return this.decisions.find((decision) => decision.action === "deny")?.capability ?? null;
  }

  static merge(decisions: CapabilityDecision[]): PolicyDecision {
    if (!decisions.length) {
      return new PolicyDecision("allow", "no capabilities to check");
    }

    const priority: Record<PolicyAction, number> = {
      allow: 0,
      need_approval: 1,
      deny: 2,
    };
    const strictest = decisions.reduce((best, decision) =>
      priority[decision.action] > priority[best.action] ? decision : best,
    );

    const reasons = decisions
      .filter((decision) => decision.action !== "allow")
      .map(
        (decision) =>
          `${decision.capability}: ${decision.action} (${decision.matchedRule ?? "default"})`,
      );

    return new PolicyDecision(
      strictest.action,
      reasons.length ? reasons.join("; ") : "all capabilities allowed",
      decisions,
    );
  }
}

function globToRegExp(pattern: string): RegExp {
  let regex = "";
  for (let index = 0; index < pattern.length; index += 1) {
    const char = pattern[index]!;
    if (char === "*") {
      regex += ".*";
    } else if (char === "?") {
      regex += ".";
    } else if (char === "[") {
      const end = pattern.indexOf("]", index + 1);
      if (end === -1) {
        regex += "\\[";
      } else {
        regex += `[${pattern.slice(index + 1, end)}]`;
        index = end;
      }
    } else {
      regex += char.replace(/[.+^${}()|\\]/g, "\\$&");
    }
  }
  return new RegExp(`^${regex}$`, "s");
}

function fnmatch(value: string, pattern: string): boolean {
  return globToRegExp(pattern).test(value);
}

export class PolicyEngine {
  private readonly fileAllow: string[];
  private readonly fileDeny: string[];
  private readonly fileMandatoryDeny: string[];
  private readonly commandDeny: string[];
  private readonly commandNeedApproval: string[];

  constructor(
    private readonly defaultAction: PolicyAction,
    config: AccessControlConfig,
    private readonly workdir: string,
  ) {
    this.fileAllow = config.file.allow;
    this.fileDeny = config.file.deny;
    this.fileMandatoryDeny = config.file.mandatoryDeny;
    this.commandDeny = config.command.denyPatterns;
    this.commandNeedApproval = config.command.needApprovalPatterns;
  }

  evaluate(context: InferredContext): PolicyDecision {
    const decisions: CapabilityDecision[] = [];

    for (const capability of context.capabilities) {
      if (capability === "file_read" || capability === "file_write") {
        if (context.filePaths.length) {
          for (const path of context.filePaths) {
            decisions.push(this.checkFilePath(path, capability));
          }
        } else {
          decisions.push({
            capability,
            action: this.defaultAction,
            matchedRule: "default",
          });
        }
      } else {
        decisions.push({
          capability,
          action: this.defaultAction,
          matchedRule: "default",
        });
      }
    }

    if (!decisions.length) {
      decisions.push({ capability: "exec", action: this.defaultAction, matchedRule: "default" });
    }

    return PolicyDecision.merge(decisions);
  }

  evaluateCommand(command: string, context: InferredContext): PolicyDecision {
    const decisions: CapabilityDecision[] = [];

    for (const pattern of this.commandDeny) {
      if (this.commandMatches(command, pattern)) {
        decisions.push({
          capability: "exec",
          action: "deny",
          matchedRule: `command.deny: ${pattern}`,
        });
        return PolicyDecision.merge(decisions);
      }
    }

    const approval = this.commandNeedApproval.find((pattern) =>
      this.commandMatches(command, pattern),
    );
    if (approval) {
      decisions.push({
        capability: "exec",
        action: "need_approval",
        matchedRule: `command.need_approval: ${approval}`,
      });
    } else {
      decisions.push({ capability: "exec", action: "allow", matchedRule: null });
    }

    for (const capability of context.capabilities) {
      if (capability === "file_read" || capability === "file_write") {
        if (context.filePaths.length) {
          for (const path of context.filePaths) {
            decisions.push(this.checkFilePath(path, capability));
          }
        } else {
          decisions.push({
            capability,
            action: this.defaultAction,
            matchedRule: "default",
          });
        }
      } else if (capability === "net") {
        decisions.push({ capability, action: "allow", matchedRule: "net deferred to sandbox" });
      } else if (capability !== "exec") {
        decisions.push({
          capability,
          action: this.defaultAction,
          matchedRule: "default",
        });
      }
    }

    return PolicyDecision.merge(decisions);
  }

  private checkFilePath(path: string, capability: CapabilityType): CapabilityDecision {
    const expanded = path.replace(/^~(?=\/|$)/, homedir());
    const resolved = isAbsolute(expanded)
      ? resolve(expanded)
      : resolve(this.workdir, expanded);
    const withSlash =
      !isAbsolute(expanded) && resolved === resolve(this.workdir) ? `${resolved}/` : resolved;

    for (const pattern of this.fileMandatoryDeny) {
      if (this.pathMatchesPattern(withSlash, pattern)) {
        return {
          capability,
          action: "deny",
          matchedRule: `file.mandatory_deny: ${pattern}`,
        };
      }
    }
    for (const pattern of this.fileDeny) {
      if (this.pathMatchesPattern(withSlash, pattern)) {
        return { capability, action: "deny", matchedRule: `file.deny: ${pattern}` };
      }
    }
    for (const pattern of this.fileAllow) {
      if (this.pathMatchesPattern(withSlash, pattern)) {
        return { capability, action: "allow", matchedRule: `file.allow: ${pattern}` };
      }
    }

    if (this.fileAllow.length) {
      return { capability, action: "deny", matchedRule: "default" };
    }
    return { capability, action: this.defaultAction, matchedRule: "default" };
  }

  private pathMatchesPattern(resolvedPath: string, pattern: string): boolean {
    const resolvedPattern = this.resolvePattern(pattern);
    return (
      fnmatch(resolvedPath, resolvedPattern) || fnmatch(`${resolvedPath}/`, resolvedPattern)
    );
  }

  private resolvePattern(pattern: string): string {
    const normalized = pattern.replaceAll("{workdir}", this.workdir);
    if (normalized.startsWith("~") || isAbsolute(normalized)) {
      return this.resolveGlobPattern(normalized);
    }
    return resolve(normalized.replace(/^~(?=\/|$)/, homedir()));
  }

  private resolveGlobPattern(pattern: string): string {
    const globIndex = Math.min(
      ...["*", "?", "["]
        .map((char) => pattern.indexOf(char))
        .filter((index) => index !== -1),
      Number.POSITIVE_INFINITY,
    );
    if (globIndex === Number.POSITIVE_INFINITY) {
      return resolve(pattern.replace(/^~(?=\/|$)/, homedir()));
    }

    const prefixEnd = pattern.lastIndexOf("/", globIndex);
    if (prefixEnd === -1) return pattern;

    const prefix = pattern.slice(0, prefixEnd);
    const suffix = pattern.slice(prefixEnd + 1);
    return `${resolve(prefix.replace(/^~(?=\/|$)/, homedir()))}/${suffix}`;
  }

  private commandMatches(command: string, pattern: string): boolean {
    return pattern.includes("*") ? fnmatch(command, pattern) : command.includes(pattern);
  }
}
