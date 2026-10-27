import { afterEach, describe, expect, test } from "bun:test";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { Server } from "bun";
import { debugLog, promptFields } from "../src/debug";
import { ObservabilityManager } from "../src/observability/manager";
import { testConfig } from "./helpers/config";

let server: Server<unknown> | null = null;
const paths: string[] = [];

afterEach(() => {
  server?.stop(true);
  server = null;
  for (const path of paths.splice(0)) {
    rmSync(path, { recursive: true, force: true });
  }
  delete process.env.BOURBON_DEBUG_LOG;
  delete process.env.BOURBON_DEBUG_PROMPTS;
});

describe("debug logging", () => {
  test("writes JSONL records when enabled", () => {
    const directory = mkdtempSync(join(tmpdir(), "bourbon-debug-"));
    paths.push(directory);
    const logPath = join(directory, "debug.jsonl");
    process.env.BOURBON_DEBUG_LOG = logPath;

    debugLog("test.event", { value: 42 });
    const record = JSON.parse(readFileSync(logPath, "utf8").trim()) as Record<string, unknown>;
    expect(record.event).toBe("test.event");
    expect(record.value).toBe(42);
    expect(record.pid).toBe(process.pid);
  });

  test("prompt fields are gated behind the prompt flag", () => {
    expect(promptFields([{ role: "user" }], "sys", [{ name: "Read" }])).toEqual({});
    process.env.BOURBON_DEBUG_PROMPTS = "1";
    expect(promptFields([{ role: "user" }], "sys", [{ name: "Read" }])).toEqual({
      messages: [{ role: "user" }],
      system: "sys",
      tool_names: ["Read"],
    });
  });
});

describe("observability manager", () => {
  test("is a no-op when disabled", async () => {
    const manager = new ObservabilityManager({
      enabled: false,
      serviceName: "test",
      otlpEndpoint: "",
      otlpHeaders: {},
    });
    const tracer = manager.getTracer();
    expect(tracer.enabled).toBe(false);
    const span = tracer.startAgentStep("/tmp", "test", null, null, "hi");
    expect(span).toBeNull();
    await manager.shutdown();
    expect(await manager.forceFlush()).toBe(true);
  });

  test("exports spans to an OTLP HTTP endpoint", async () => {
    let requests = 0;
    server = Bun.serve({
      port: 0,
      async fetch(request) {
        requests += 1;
        await request.arrayBuffer();
        return new Response("", { status: 200 });
      },
    });

    const manager = new ObservabilityManager({
      enabled: true,
      serviceName: "bourbon-test",
      otlpEndpoint: `http://127.0.0.1:${server.port}`,
      otlpHeaders: { "x-test": "1" },
    });

    const tracer = manager.getTracer();
    for (let attempt = 0; attempt < 40 && !tracer.enabled; attempt += 1) {
      await Bun.sleep(25);
    }
    expect(tracer.enabled).toBe(true);

    const span = tracer.startAgentStep("/tmp", "test", "case-1", "run-1", "hello");
    tracer.recordAgentOutput(span, "world");
    tracer.end(span);

    expect(await manager.forceFlush(2)).toBe(true);
    await Bun.sleep(100);
    expect(requests).toBeGreaterThanOrEqual(1);

    await manager.shutdown();
  });
});

test("otel config defaults in test helper", () => {
  expect(testConfig().observability.enabled).toBe(false);
});
