export interface Violation {
  type: string;
  detail: string;
}

export interface ResourceUsage {
  cpuTime: number;
  memoryPeak: string;
  filesWritten: string[];
}

export interface SandboxContext {
  workdir: string;
  writablePaths: string[];
  readonlyPaths: string[];
  denyPaths: string[];
  networkEnabled: boolean;
  allowDomains: string[];
  timeout: number;
  maxMemory: string;
  maxOutput: number;
  envVars: Record<string, string>;
}

export interface SandboxResult {
  stdout: string;
  stderr: string;
  exitCode: number;
  timedOut: boolean;
  resourceUsage: ResourceUsage;
  violations: Violation[];
}

export class BoundedOutput {
  private chunks: string[] = [];
  private captured = 0;
  private truncated = false;

  constructor(private readonly maxOutput: number) {}

  append(chunk: string): void {
    if (!chunk) return;
    if (this.maxOutput <= 0) {
      this.chunks.push(chunk);
      return;
    }
    const remaining = this.maxOutput - this.captured;
    if (remaining > 0) {
      const kept = chunk.slice(0, remaining);
      this.chunks.push(kept);
      this.captured += kept.length;
    }
    if (chunk.length > Math.max(remaining, 0)) this.truncated = true;
  }

  render(): string {
    const data = this.chunks.join("");
    return this.truncated ? `${data}...` : data;
  }
}

export abstract class SandboxProvider {
  abstract execute(command: string, context: SandboxContext): Promise<SandboxResult>;
  abstract getIsolationLevel(): string;

  static isAvailable(): boolean {
    return true;
  }
}

export async function readStream(
  stream: ReadableStream<Uint8Array>,
  buffer: BoundedOutput,
): Promise<void> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      if (value) buffer.append(decoder.decode(value, { stream: true }));
    }
    buffer.append(decoder.decode());
  } finally {
    reader.releaseLock();
  }
}

export async function runProcess(options: {
  argv: string[];
  cwd?: string;
  env?: Record<string, string>;
  timeout: number;
  maxOutput: number;
}): Promise<{
  stdout: string;
  stderr: string;
  exitCode: number;
  timedOut: boolean;
  elapsed: number;
}> {
  const started = Date.now();
  const proc = Bun.spawn(options.argv, {
    cwd: options.cwd,
    env: options.env,
    stdout: "pipe",
    stderr: "pipe",
  });

  const stdout = new BoundedOutput(options.maxOutput);
  const stderr = new BoundedOutput(options.maxOutput);
  let timedOut = false;

  const timer = setTimeout(() => {
    timedOut = true;
    proc.kill(9);
  }, options.timeout * 1000);

  try {
    const [, , code] = await Promise.all([
      readStream(proc.stdout, stdout),
      readStream(proc.stderr, stderr),
      proc.exited,
    ]);
    return {
      stdout: stdout.render(),
      stderr: stderr.render(),
      exitCode: code,
      timedOut,
      elapsed: (Date.now() - started) / 1000,
    };
  } finally {
    clearTimeout(timer);
  }
}

export function sandboxTimeoutMessage(stderr: string, timeout: number): string {
  const message = `Command timed out after ${timeout} seconds.`;
  return stderr ? `${message}\n${stderr}` : message;
}
