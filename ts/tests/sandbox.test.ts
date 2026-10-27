import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { createServer, request as httpRequest } from "node:http";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Agent } from "../src/agent/agent";
import { AuditLogger } from "../src/audit";
import { CredentialManager } from "../src/sandbox/credential";
import { CredentialProxy } from "../src/sandbox/credential_proxy";
import { SandboxManager } from "../src/sandbox/manager";
import { FilesystemPolicy } from "../src/sandbox/policy";
import type { SandboxContext } from "../src/sandbox/runtime";
import { BwrapProvider } from "../src/sandbox/providers/bubblewrap";
import { DockerProvider } from "../src/sandbox/providers/docker";
import { LocalProvider } from "../src/sandbox/providers/local";
import { SeatbeltProvider } from "../src/sandbox/providers/seatbelt";
import { createToolRegistry } from "../src/tools";
import { testConfig } from "./helpers/config";
import { FakeLLM, textResponse, toolResponse } from "./helpers/fake-llm";

let workdir: string;
let audit: AuditLogger;

function context(overrides: Partial<SandboxContext> = {}): SandboxContext {
  return {
    workdir,
    writablePaths: [workdir],
    readonlyPaths: [],
    denyPaths: [],
    networkEnabled: false,
    allowDomains: [],
    timeout: 10,
    maxMemory: "512M",
    maxOutput: 50000,
    envVars: { PATH: process.env.PATH ?? "/usr/bin:/bin", HOME: process.env.HOME ?? "" },
    ...overrides,
  };
}

beforeEach(() => {
  workdir = mkdtempSync(join(tmpdir(), "bourbon-sandbox-"));
  audit = new AuditLogger(join(workdir, "audit"), true);
});

afterEach(() => {
  rmSync(workdir, { recursive: true, force: true });
});

describe("sandbox providers", () => {
  test("local provider executes commands in the workdir", async () => {
    const result = await new LocalProvider().execute("pwd && echo local", context());
    expect(result.exitCode).toBe(0);
    expect(result.stdout).toContain(workdir);
    expect(result.stdout).toContain("local");
    expect(result.timedOut).toBe(false);
  });

  test("local provider times out long commands", async () => {
    const result = await new LocalProvider().execute(
      "sleep 2",
      context({ timeout: 0.1 }),
    );
    expect(result.timedOut).toBe(true);
    expect(result.exitCode).toBe(-1);
    expect(result.stderr).toContain("timed out");
  });

  test("seatbelt provider enforces deny paths on macOS", async () => {
    if (!SeatbeltProvider.isAvailable()) return;
    const result = await new SeatbeltProvider().execute("echo seatbelt-ok", context());
    expect(result.exitCode).toBe(0);
    expect(result.stdout).toContain("seatbelt-ok");

    const denyDir = mkdtempSync(join(tmpdir(), "bourbon-denied-"));
    writeFileSync(join(denyDir, "secret.txt"), "classified");
    try {
      const denied = await new SeatbeltProvider().execute(
        `cat ${join(denyDir, "secret.txt")}`,
        context({ denyPaths: [denyDir] }),
      );
      expect(denied.exitCode).not.toBe(0);
      expect(denied.stdout).not.toContain("classified");
    } finally {
      rmSync(denyDir, { recursive: true, force: true });
    }
  });

  test("provider availability probes return booleans", () => {
    expect(typeof BwrapProvider.isAvailable()).toBe("boolean");
    expect(typeof DockerProvider.isAvailable()).toBe("boolean");
  });
});

describe("sandbox manager", () => {
  test("blocks network commands for the local provider", async () => {
    const manager = new SandboxManager(
      {
        ...testConfig().sandbox,
        enabled: true,
        provider: "local",
        network: { enabled: false, allowDomains: [] },
      },
      workdir,
      audit,
    );
    const result = await manager.execute("curl https://example.com", "Bash");
    expect(result.exitCode).toBe(1);
    expect(result.stderr).toContain("Network access disabled");
    expect(audit.summary().violations).toBe(1);
  });

  test("executes allowed commands and audits them", async () => {
    const manager = new SandboxManager(
      {
        ...testConfig().sandbox,
        enabled: true,
        provider: "local",
      },
      workdir,
      audit,
    );
    const result = await manager.execute("echo hello", "Bash");
    expect(result.exitCode).toBe(0);
    expect(result.stdout).toContain("hello");
    expect(audit.summary().sandbox_executions).toBe(1);
  });

  test("filters credentials from the sandbox environment", async () => {
    const manager = new SandboxManager(
      {
        ...testConfig().sandbox,
        enabled: true,
        provider: "local",
        credentials: {
          cleanEnv: true,
          passthroughVars: ["PATH", "HOME", "OPENAI_API_KEY", "CUSTOM_VALUE"],
        },
      },
      workdir,
      audit,
    );
    process.env.CUSTOM_VALUE = "visible";
    process.env.OPENAI_API_KEY = "should-not-leak";
    try {
      const result = await manager.execute(
        "printf '%s|%s' \"$CUSTOM_VALUE\" \"$OPENAI_API_KEY\"",
        "Bash",
      );
      expect(result.stdout).toBe("visible|");
    } finally {
      delete process.env.CUSTOM_VALUE;
      delete process.env.OPENAI_API_KEY;
    }
  });

  test("agent routes destructive bash tools through the sandbox", async () => {
    const config = testConfig({
      sandbox: { ...testConfig().sandbox, enabled: true, provider: "local" },
      audit: { enabled: true, logDir: join(workdir, "agent-audit"), format: "jsonl" },
    });
    const agent = new Agent({
      config,
      llm: new FakeLLM([
        toolResponse("t1", "Bash", { command: "echo from-sandbox > sandbox.txt" }),
        textResponse("done"),
      ]),
      registry: createToolRegistry(),
      workdir,
      sessionDir: join(workdir, "sessions"),
    });

    const answer = await agent.run("use sandbox");
    expect(answer).toBe("done");
    expect(await Bun.file(join(workdir, "sandbox.txt")).text()).toContain("from-sandbox");
    expect(agent.audit.summary().sandbox_executions).toBe(1);
  });
});

describe("policy and credentials", () => {
  test("filesystem policy orders rw, ro, then deny", () => {
    const policy = FilesystemPolicy.fromContext(
      context({
        writablePaths: [join(workdir, "src")],
        readonlyPaths: ["/usr"],
        denyPaths: [join(workdir, "secret")],
      }),
    );
    const modes = policy.rules.map((rule) => rule.mode);
    expect(modes.at(-1)).toBe("deny");
    expect(modes).toContain("rw");
    expect(modes).toContain("ro");
  });

  test("credential proxy enforces domain allowlists", async () => {
    const target = createServer((_request, response) => {
      response.writeHead(200, { "content-type": "text/plain" });
      response.end("target-ok");
    });
    await new Promise<void>((resolveListen) => target.listen(0, "127.0.0.1", resolveListen));
    const targetPort = (target.address() as { port: number }).port;

    const proxy = new CredentialProxy(["127.0.0.1"]);
    const address = proxy.start();
    const [host, portText] = address.split(":");
    const proxyPort = Number(portText);

    const fetchViaProxy = (absoluteUrl: string): Promise<{ status: number; body: string }> =>
      new Promise((resolveResponse, rejectResponse) => {
        const request = httpRequest(
          {
            host,
            port: proxyPort,
            path: absoluteUrl,
            method: "GET",
            headers: { Host: new URL(absoluteUrl).host },
          },
          (response) => {
            let body = "";
            response.on("data", (chunk) => {
              body += chunk;
            });
            response.on("end", () => resolveResponse({ status: response.statusCode ?? 0, body }));
          },
        );
        request.on("error", rejectResponse);
        request.end();
      });

    try {
      expect(proxy.isDomainAllowed("api.example.com")).toBe(false);
      const wildcard = new CredentialProxy(["*.example.com"]);
      expect(wildcard.isDomainAllowed("api.example.com")).toBe(true);
      expect(wildcard.isDomainAllowed("example.com")).toBe(false);

      const allowed = await fetchViaProxy(`http://127.0.0.1:${targetPort}/page`);
      expect(allowed.status).toBe(200);
      expect(allowed.body).toBe("target-ok");

      const denied = await fetchViaProxy(`http://localhost:${targetPort}/page`);
      expect(denied.status).toBe(403);
      expect(denied.body).toContain("not in allow_domains");
    } finally {
      proxy.stop();
      await new Promise<void>((resolveClose) => target.close(() => resolveClose()));
    }
  });

  test("credential manager strips sensitive variables", () => {
    const manager = new CredentialManager();
    const env = manager.cleanEnv(
      ["PATH", "ANTHROPIC_API_KEY", "AWS_SECRET_ACCESS_KEY", "NORMAL"],
      {
        PATH: "/bin",
        ANTHROPIC_API_KEY: "secret",
        AWS_SECRET_ACCESS_KEY: "secret",
        NORMAL: "ok",
      },
    );
    expect(env).toEqual({ PATH: "/bin", NORMAL: "ok" });
  });
});
