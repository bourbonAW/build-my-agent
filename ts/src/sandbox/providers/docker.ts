import type { SandboxDockerConfig } from "../../config";
import { CredentialProxy } from "../credential_proxy";
import { FilesystemPolicy } from "../policy";
import type { SandboxContext, SandboxResult, Violation } from "../runtime";
import { runProcess, SandboxProvider, sandboxTimeoutMessage } from "../runtime";

export class DockerProvider extends SandboxProvider {
  private readonly image: string;
  private readonly pullPolicy: string;
  private readonly user: string;

  constructor(config: Partial<SandboxDockerConfig> = {}) {
    super();
    this.image = config.image ?? "python:3.11-slim";
    this.pullPolicy = config.pullPolicy ?? "if-not-present";
    this.user = config.user ?? "nobody";
  }

  static override isAvailable(): boolean {
    if (Bun.which("docker") === null) return false;
    try {
      return (
        Bun.spawnSync(["docker", "info"], {
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
    this.ensureImage();

    const policy = FilesystemPolicy.fromContext(context);
    let proxy: CredentialProxy | null = null;
    let proxyAddress: string | null = null;

    if (context.networkEnabled && context.allowDomains.length) {
      proxy = new CredentialProxy(context.allowDomains);
      proxyAddress = proxy.start();
    }

    try {
      const args = this.buildDockerArgs(command, policy, context, proxyAddress);
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
        violations: this.parseViolations(
          result.exitCode,
          result.stderr,
          context.maxMemory,
          result.timedOut,
        ),
      };
    } finally {
      proxy?.stop();
    }
  }

  getIsolationLevel(): string {
    return `docker (container isolation, image=${this.image})`;
  }

  private ensureImage(): void {
    if (this.pullPolicy === "never") return;
    if (this.pullPolicy === "always") {
      Bun.spawnSync(["docker", "pull", this.image], { stdout: "ignore", stderr: "ignore" });
      return;
    }
    const exists =
      Bun.spawnSync(["docker", "image", "inspect", this.image], {
        stdout: "ignore",
        stderr: "ignore",
      }).exitCode === 0;
    if (!exists) {
      Bun.spawnSync(["docker", "pull", this.image], { stdout: "ignore", stderr: "ignore" });
    }
  }

  private buildDockerArgs(
    command: string,
    policy: FilesystemPolicy,
    context: SandboxContext,
    proxyAddress: string | null,
  ): string[] {
    const args = [
      "docker",
      "run",
      "--rm",
      "--cap-drop=ALL",
      "--security-opt",
      "no-new-privileges",
      "--user",
      this.user,
      "--memory",
      context.maxMemory,
      "--cpus",
      "1",
    ];

    if (!context.networkEnabled) {
      args.push("--network", "none");
    } else if (proxyAddress) {
      args.push(
        "--network",
        "bridge",
        "-e",
        `http_proxy=http://${proxyAddress}`,
        "-e",
        `https_proxy=http://${proxyAddress}`,
        "-e",
        `HTTP_PROXY=http://${proxyAddress}`,
        "-e",
        `HTTPS_PROXY=http://${proxyAddress}`,
      );
    } else {
      args.push("--network", "bridge");
    }

    for (const rule of policy.rules) {
      if (rule.mode === "rw") args.push("-v", `${rule.path}:${rule.path}:rw`);
      else if (rule.mode === "ro") args.push("-v", `${rule.path}:${rule.path}:ro`);
    }

    args.push("-w", context.workdir);
    for (const [key, value] of Object.entries(context.envVars)) {
      args.push("-e", `${key}=${value}`);
    }
    args.push(this.image, "bash", "-c", command);
    return args;
  }

  private parseViolations(
    exitCode: number,
    stderr: string,
    maxMemory: string,
    timedOut: boolean,
  ): Violation[] {
    const violations: Violation[] = [];
    const lower = stderr.toLowerCase();

    if (exitCode === 137 && !timedOut) {
      violations.push({
        type: "oom_killed",
        detail: `process exceeded memory limit (${maxMemory})`,
      });
    }
    if (lower.includes("network is unreachable") || lower.includes("errno 101")) {
      violations.push({
        type: "net_denied",
        detail: "container network disabled (--network=none)",
      });
    }
    if (lower.includes("operation not permitted") && exitCode !== 0) {
      violations.push({
        type: "cap_denied",
        detail: "operation denied by capability restrictions (--cap-drop=ALL)",
      });
    }
    return violations;
  }
}
