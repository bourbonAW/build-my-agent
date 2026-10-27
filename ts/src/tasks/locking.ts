import { closeSync, mkdirSync, openSync, statSync, unlinkSync, writeSync } from "node:fs";
import { dirname } from "node:path";

const RETRY_MS = 10;
const TIMEOUT_MS = 5000;
const STALE_MS = 10_000;

function sleepSync(ms: number): void {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
}

export class FileLock {
  private handle: number | null = null;

  constructor(private readonly path: string) {}

  acquire(): void {
    mkdirSync(dirname(this.path), { recursive: true });
    const deadline = Date.now() + TIMEOUT_MS;

    while (true) {
      try {
        this.handle = openSync(this.path, "wx");
        writeSync(this.handle, String(process.pid));
        return;
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
        try {
          if (Date.now() - statSync(this.path).mtimeMs > STALE_MS) {
            unlinkSync(this.path);
            continue;
          }
        } catch {
          continue;
        }
        if (Date.now() >= deadline) {
          throw new Error(`Timed out acquiring lock: ${this.path}`);
        }
        sleepSync(RETRY_MS);
      }
    }
  }

  release(): void {
    if (this.handle !== null) {
      closeSync(this.handle);
      this.handle = null;
    }
    try {
      unlinkSync(this.path);
    } catch {
      // lock may already be gone
    }
  }

  withLock<T>(fn: () => T): T {
    this.acquire();
    try {
      return fn();
    } finally {
      this.release();
    }
  }
}
