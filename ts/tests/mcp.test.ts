import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { mkdtempSync, rmSync } from "node:fs";
import { createServer } from "node:http";
import type { AddressInfo } from "node:net";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import { z } from "zod";
import { MCPManager, parseMcpConfig } from "../src/mcp";
import type { McpConfig } from "../src/mcp";
import { buildSystemPrompt } from "../src/prompt";
import { createToolRegistry } from "../src/tools";

let root: string;

beforeEach(() => {
  root = mkdtempSync(join(tmpdir(), "bourbon-mcp-"));
});

afterEach(() => {
  rmSync(root, { recursive: true, force: true });
});

function stdioConfig(): McpConfig {
  return {
    enabled: true,
    defaultTimeout: 10,
    servers: [
      {
        name: "local",
        transport: "stdio",
        enabled: true,
        maxRetries: 1,
        retryDelay: 0.01,
        command: Bun.which("bun") ?? "bun",
        args: [join(import.meta.dir, "fixtures", "mcp-server.ts")],
        env: {},
        headers: {},
      },
    ],
  };
}

describe("MCP config", () => {
  test("parses servers and defaults", () => {
    const config = parseMcpConfig({
      enabled: true,
      default_timeout: 12,
      servers: [
        {
          name: "files",
          transport: "stdio",
          command: "bun",
          args: ["server.ts"],
          env: { TOKEN: "abc" },
        },
        {
          name: "remote",
          transport: "http",
          url: "https://example.com/mcp",
          headers: { Authorization: "Bearer x" },
        },
      ],
    });

    expect(config.defaultTimeout).toBe(12);
    expect(config.servers).toHaveLength(2);
    expect(config.servers[0]).toMatchObject({
      name: "files",
      enabled: true,
      maxRetries: 3,
    });
    expect(config.servers[1]!.transport).toBe("http");
    expect(config.servers[1]!.url).toBe("https://example.com/mcp");
    const invalid = parseMcpConfig({ servers: [{ name: "bad", transport: "stdio" }] });
    expect(invalid.servers).toHaveLength(0);
  });
});

describe("MCP client", () => {
  test("connects over stdio, registers tools, calls them, and feeds the prompt", async () => {
    const registry = createToolRegistry();
    const manager = new MCPManager(stdioConfig(), registry);

    const results = await manager.connectAll();
    expect(results.local?.success).toBe(true);
    expect(results.local?.toolsCount).toBe(2);

    const summary = manager.getConnectionSummary();
    expect(summary.connected).toBe(1);
    expect(summary.totalTools).toBe(2);
    expect(manager.listMcpTools().sort()).toEqual(["local-add", "local-echo"]);

    const echo = await registry.call("local-echo", { text: "hello" }, { workdir: root });
    expect(echo).toBe("echo:hello");

    const add = await registry.call("local-add", { a: 2, b: 3 }, { workdir: root });
    expect(add).toBe("5");

    const prompt = await buildSystemPrompt({ workdir: root, mcpManager: manager });
    expect(prompt).toContain("MCP TOOLS");
    expect(prompt).toContain("local-echo");

    await manager.disconnectAll();
    expect(manager.getConnectionSummary().connected).toBe(0);
  });

  test("connects over streamable HTTP", async () => {
    const httpServer = createServer(async (request, response) => {
      if (request.method !== "POST") {
        response.writeHead(405).end();
        return;
      }

      const chunks: Uint8Array[] = [];
      for await (const chunk of request) chunks.push(chunk as Uint8Array);
      const body = JSON.parse(Buffer.concat(chunks).toString("utf8")) as unknown;

      const server = new McpServer({ name: "http-test", version: "1.0.0" });
      server.registerTool(
        "ping",
        {
          description: "Return pong",
          inputSchema: { value: z.string() },
        },
        async ({ value }) => ({ content: [{ type: "text", text: `pong:${value}` }] }),
      );
      const transport = new StreamableHTTPServerTransport({ sessionIdGenerator: undefined });
      await server.connect(transport);
      await transport.handleRequest(request, response, body);
      response.on("close", () => {
        void transport.close();
        void server.close();
      });
    });
    await new Promise<void>((resolveListen) => {
      httpServer.listen(0, "127.0.0.1", resolveListen);
    });
    const port = (httpServer.address() as AddressInfo).port;

    const config: McpConfig = {
      enabled: true,
      defaultTimeout: 10,
      servers: [
        {
          name: "remote",
          transport: "http",
          enabled: true,
          maxRetries: 1,
          retryDelay: 0.01,
          url: `http://127.0.0.1:${port}/mcp`,
          args: [],
          env: {},
          headers: {},
        },
      ],
    };

    const registry = createToolRegistry();
    const manager = new MCPManager(config, registry);
    try {
      const results = await manager.connectAll();
      expect(results.remote?.success).toBe(true);
      expect(results.remote?.toolsCount).toBe(1);
      expect(await registry.call("remote-ping", { value: "x" }, { workdir: root })).toBe(
        "pong:x",
      );
    } finally {
      await manager.disconnectAll();
      await new Promise<void>((resolveClose) => httpServer.close(() => resolveClose()));
    }
  });

  test("reports connection failures without throwing", async () => {
    const config: McpConfig = {
      enabled: true,
      defaultTimeout: 5,
      servers: [
        {
          name: "missing",
          transport: "stdio",
          enabled: true,
          maxRetries: 2,
          retryDelay: 0.01,
          command: "/definitely/not/a/command",
          args: [],
          env: {},
          headers: {},
        },
      ],
    };
    const manager = new MCPManager(config, createToolRegistry());
    const results = await manager.connectAll();
    expect(results.missing?.success).toBe(false);
    expect(results.missing?.error).toContain("not found");
  });
});
