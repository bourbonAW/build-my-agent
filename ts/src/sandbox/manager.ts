import { AuditEvent, type AuditLogger } from "../audit";
import type { SandboxConfig } from "../config";
import { CredentialManager } from "./credential";
import { LocalProvider, selectProvider } from "./providers";
import type { SandboxContext, SandboxProvider, SandboxResult } from "./runtime";

const NETWORK_PATTERNS = [
  "curl ",
  "wget ",
  "http://",
  "https://",
  "pip install ",
  "pip3 install ",
  "git clone ",
  "git pull ",
  "git push ",
];

export class SandboxManager {
  readonly enabled: boolean;
  readonly provider: SandboxProvider | null;
  private readonly credentialManager = new CredentialManager();

  constructor(
    private readonly config: SandboxConfig,
    private readonly workdir: string,
    private readonly audit: AuditLogger,
  ) {
    this.enabled = config.enabled;
    this.provider = config.enabled
      ? selectProvider(config.provider, config.docker)
      : null;
  }

  async execute(command: string, toolName = "bash"): Promise<SandboxResult> {
    if (!this.enabled || !this.provider) {
      throw new Error("SandboxManager.execute() called but sandbox is disabled");
    }

    const { credentials, network, resources, filesystem } = this.config;
    const envVars = credentials.cleanEnv
      ? this.credentialManager.cleanEnv(credentials.passthroughVars)
      : Object.fromEntries(
          Object.entries(process.env).filter(
            (entry): entry is [string, string] =>
              entry[1] !== undefined && credentials.passthroughVars.includes(entry[0]),
          ),
        );

    const context: SandboxContext = {
      workdir: this.workdir,
      writablePaths: this.resolvePaths(filesystem.writable),
      readonlyPaths: this.resolvePaths(filesystem.readonly),
      denyPaths: this.resolvePaths(filesystem.deny),
      networkEnabled: network.enabled,
      allowDomains: [...network.allowDomains],
      timeout: resources.timeout,
      maxMemory: resources.maxMemory,
      maxOutput: resources.maxOutput,
      envVars,
    };

    if (
      !context.networkEnabled &&
      this.provider instanceof LocalProvider &&
      this.containsNetworkActivity(command)
    ) {
      this.audit.record(
        AuditEvent.sandboxViolation(toolName, command.slice(0, 200), {
          reason: "network access disabled by sandbox policy",
        }),
      );
      return {
        stdout: "",
        stderr: "Network access disabled by sandbox policy.",
        exitCode: 1,
        timedOut: false,
        resourceUsage: { cpuTime: 0, memoryPeak: "0M", filesWritten: [] },
        violations: [],
      };
    }

    const result = await this.provider.execute(command, context);
    for (const violation of result.violations) {
      this.audit.record(
        AuditEvent.sandboxViolation(toolName, command.slice(0, 200), {
          reason: `${violation.type}: ${violation.detail}`,
        }),
      );
    }
    this.audit.record(
      AuditEvent.sandboxExec(toolName, command.slice(0, 200), {
        provider: this.provider.getIsolationLevel(),
        exit_code: result.exitCode,
        timed_out: result.timedOut,
        resource_usage: {
          cpu_time: result.resourceUsage.cpuTime,
          memory_peak: result.resourceUsage.memoryPeak,
          files_written: result.resourceUsage.filesWritten,
        },
      }),
    );
    return result;
  }

  formatOutput(result: SandboxResult): string {
    if (result.timedOut) {
      return `Error: Timeout (${Math.round(result.resourceUsage.cpuTime)}s)`;
    }
    const output = `${result.stdout}${result.stderr}`.trim();
    return output || "(no output)";
  }

  private resolvePaths(paths: string[]): string[] {
    return paths.map((path) => path.replaceAll("{workdir}", this.workdir));
  }

  private containsNetworkActivity(command: string): boolean {
    return NETWORK_PATTERNS.some((pattern) => command.includes(pattern));
  }
}
