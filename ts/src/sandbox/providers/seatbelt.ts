import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { FilesystemPolicy } from "../policy";
import type { SandboxContext, SandboxResult, Violation } from "../runtime";
import { runProcess, SandboxProvider, sandboxTimeoutMessage } from "../runtime";

export class SeatbeltProvider extends SandboxProvider {
  static override isAvailable(): boolean {
    return process.platform === "darwin" && Bun.which("sandbox-exec") !== null;
  }

  async execute(command: string, context: SandboxContext): Promise<SandboxResult> {
    const policy = FilesystemPolicy.fromContext(context);
    const profile = this.buildProfile(policy, context.networkEnabled);
    const directory = mkdtempSync(join(tmpdir(), "bourbon-seatbelt-"));
    const profilePath = join(directory, "profile.sb");
    writeFileSync(profilePath, profile, "utf8");

    try {
      const result = await runProcess({
        argv: ["sandbox-exec", "-f", profilePath, "bash", "-c", command],
        cwd: context.workdir,
        env: context.envVars,
        timeout: context.timeout,
        maxOutput: context.maxOutput,
      });

      return {
        stdout: result.stdout,
        stderr: result.timedOut
          ? sandboxTimeoutMessage(result.stderr, context.timeout)
          : result.stderr,
        exitCode: result.timedOut ? -1 : result.exitCode,
        timedOut: result.timedOut,
        resourceUsage: { cpuTime: result.elapsed, memoryPeak: "0M", filesWritten: [] },
        violations: this.parseViolations(result.stderr),
      };
    } finally {
      rmSync(directory, { recursive: true, force: true });
    }
  }

  getIsolationLevel(): string {
    return "seatbelt (macOS sandbox-exec)";
  }

  private buildProfile(policy: FilesystemPolicy, networkEnabled: boolean): string {
    const lines = [
      "(version 1)",
      "(deny default)",
      "",
      "; === base system permissions ===",
      "(allow process-exec)",
      "(allow process-fork)",
      "(allow sysctl-read)",
      "(allow mach-lookup)",
      "(allow ipc-posix-shm-read*)",
      "(allow ipc-posix-shm-write*)",
      "(allow signal (target self))",
      "",
      "(allow file-read*)",
      "",
      "; === /dev access ===",
      '(allow file-read* file-write* (subpath "/dev"))',
      "",
      "; === filesystem rules (allow first, deny last to override) ===",
    ];

    for (const rule of policy.rules) {
      if (rule.mode === "rw") {
        lines.push(`(allow file-read* file-write* (subpath "${rule.path}"))`);
      } else if (rule.mode === "ro") {
        lines.push(`(allow file-read* (subpath "${rule.path}"))`);
      }
    }

    for (const rule of policy.rules) {
      if (rule.mode === "deny") {
        lines.push(`(deny file-read* file-write* (subpath "${rule.path}"))`);
      }
    }

    lines.push("", networkEnabled ? "(allow network*)" : "(deny network*)");
    return lines.join("\n");
  }

  private parseViolations(stderr: string): Violation[] {
    const violations: Violation[] = [];
    if (stderr.includes("Operation not permitted")) {
      violations.push({
        type: "path_denied",
        detail: "filesystem access denied by seatbelt profile",
      });
    }
    const lower = stderr.toLowerCase();
    if ((lower.includes("network") || lower.includes("connect")) && lower.includes("denied")) {
      violations.push({
        type: "net_denied",
        detail: "network access denied by seatbelt profile",
      });
    }
    return violations;
  }
}
