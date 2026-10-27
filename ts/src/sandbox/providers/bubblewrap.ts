import { existsSync } from "node:fs";
import { FilesystemPolicy } from "../policy";
import type { SandboxContext, SandboxResult, Violation } from "../runtime";
import { runProcess, SandboxProvider, sandboxTimeoutMessage } from "../runtime";

const SYSTEM_RO_BINDS = ["/usr", "/lib", "/lib64", "/bin", "/sbin"];

export class BwrapProvider extends SandboxProvider {
  static override isAvailable(): boolean {
    if (process.platform !== "linux" || Bun.which("bwrap") === null) return false;
    try {
      return (
        Bun.spawnSync(["bwrap", "--ro-bind", "/", "/", "--", "true"], {
          stdout: "ignore",
          stderr: "ignore",
          timeout: 5000,
        }).exitCode === 0
      );
    } catch {
      return false;
    }
  }

  async execute(command: string, context: SandboxContext): Promise<SandboxResult> {
    const policy = FilesystemPolicy.fromContext(context);
    const args = this.buildArgs(command, policy, context);
    const result = await runProcess({
      argv: args,
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
  }

  getIsolationLevel(): string {
    return "bubblewrap (Linux namespace)";
  }

  private buildArgs(command: string, policy: FilesystemPolicy, context: SandboxContext): string[] {
    const args = ["bwrap"];
    for (const path of SYSTEM_RO_BINDS) {
      if (existsSync(path)) args.push("--ro-bind", path, path);
    }
    args.push("--proc", "/proc", "--dev", "/dev");

    const mounted: string[] = [];
    for (const rule of policy.rules) {
      if (rule.mode === "rw") {
        args.push("--bind", rule.path, rule.path);
        mounted.push(rule.path);
      } else if (rule.mode === "ro") {
        const covered = SYSTEM_RO_BINDS.some(
          (path) => rule.path === path || rule.path.startsWith(`${path}/`),
        );
        if (!covered && existsSync(rule.path)) {
          args.push("--ro-bind", rule.path, rule.path);
        }
        mounted.push(rule.path);
      }
    }

    for (const rule of policy.rules) {
      const denyCoversMount = mounted.some((mount) => rule.path.startsWith(`${mount}/`));
      if (rule.mode === "deny" && denyCoversMount) {
        args.push("--tmpfs", rule.path);
      }
    }

    if (!context.networkEnabled) args.push("--unshare-net");
    args.push("--unshare-pid", "--new-session", "--die-with-parent", "--clearenv");
    for (const [key, value] of Object.entries(context.envVars)) {
      args.push("--setenv", key, value);
    }
    args.push("--chdir", context.workdir, "--", "bash", "-c", command);
    return args;
  }

  private parseViolations(stderr: string): Violation[] {
    return stderr.includes("Network is unreachable")
      ? [{ type: "net_denied", detail: "network isolated by namespace (--unshare-net)" }]
      : [];
  }
}
