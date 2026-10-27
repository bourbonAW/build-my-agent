import type { SandboxContext, SandboxResult } from "../runtime";
import { runProcess, SandboxProvider, sandboxTimeoutMessage } from "../runtime";

export class LocalProvider extends SandboxProvider {
  async execute(command: string, context: SandboxContext): Promise<SandboxResult> {
    const result = await runProcess({
      argv: ["/bin/sh", "-c", command],
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
      violations: [],
    };
  }

  getIsolationLevel(): string {
    return "local (no OS isolation)";
  }
}
