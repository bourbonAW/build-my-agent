export class AsyncExecutor {
  private readonly promises = new Map<string, Promise<unknown>>();

  submit<T>(runId: string, task: () => Promise<T>): Promise<T> {
    const promise = task().finally(() => {
      this.promises.delete(runId);
    });
    this.promises.set(runId, promise);
    return promise;
  }

  get(runId: string): Promise<unknown> | undefined {
    return this.promises.get(runId);
  }

  async wait(runId: string, timeoutSeconds?: number | null): Promise<"done" | "timeout"> {
    const promise = this.promises.get(runId);
    if (!promise) return "done";
    if (timeoutSeconds === undefined || timeoutSeconds === null) {
      await promise.catch(() => undefined);
      return "done";
    }

    let timer: ReturnType<typeof setTimeout> | undefined;
    const timeout = new Promise<"timeout">((resolve) => {
      timer = setTimeout(() => resolve("timeout"), timeoutSeconds * 1000);
    });
    try {
      const outcome = await Promise.race([
        promise.then(() => "done" as const).catch(() => "done" as const),
        timeout,
      ]);
      return outcome;
    } finally {
      if (timer) clearTimeout(timer);
    }
  }

  shutdown(): void {
    this.promises.clear();
  }
}
