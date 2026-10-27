import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import type { McpServerConfig } from "./config";

export class McpConnectionError extends Error {
  constructor(message: string, options?: ErrorOptions) {
    super(message, options);
    this.name = "McpConnectionError";
  }
}

export class McpServerNotInstalledError extends McpConnectionError {
  constructor(message: string) {
    super(message);
    this.name = "McpServerNotInstalledError";
  }
}

function normalizePackageName(packageSpec: string): string {
  if (packageSpec.startsWith("@")) {
    const index = packageSpec.lastIndexOf("@");
    return index > 0 ? packageSpec.slice(0, index) : packageSpec;
  }
  const index = packageSpec.indexOf("@");
  return index > 0 ? packageSpec.slice(0, index) : packageSpec;
}

function firstPackageArg(args: string[]): string | null {
  return args.find((arg) => !arg.startsWith("-")) ?? null;
}

function runQuiet(command: string[]): { code: number; stdout: string } {
  try {
    const result = Bun.spawnSync(command, {
      stdout: "pipe",
      stderr: "pipe",
      timeout: 10_000,
    });
    return {
      code: result.exitCode ?? 1,
      stdout: result.stdout?.toString() ?? "",
    };
  } catch {
    return { code: 1, stdout: "" };
  }
}

function validateNpxPackage(config: McpServerConfig): void {
  const packageSpec = firstPackageArg(config.args);
  if (!packageSpec) return;
  const packageName = normalizePackageName(packageSpec);
  const binaryName = packageName.split("/").at(-1)!;

  if (Bun.which(binaryName)) return;
  if (runQuiet(["npm", "list", "-g", packageName]).code === 0) return;
  if (runQuiet(["npm", "list", packageName]).code === 0) return;

  const cacheResult = runQuiet(["npm", "config", "get", "cache"]);
  const cacheRoot = cacheResult.code === 0 ? cacheResult.stdout.trim() : join(homedir(), ".npm");
  const npxCache = join(cacheRoot, "_npx");
  if (existsSync(npxCache)) {
    for (const entry of readdirSync(npxCache)) {
      const manifest = join(npxCache, entry, "package.json");
      if (!existsSync(manifest)) continue;
      try {
        const data = JSON.parse(readFileSync(manifest, "utf8")) as {
          dependencies?: Record<string, string>;
        };
        if (packageName in (data.dependencies ?? {})) return;
      } catch {
        continue;
      }
    }
  }

  throw new McpServerNotInstalledError(
    `MCP server package '${packageName}' is not installed. ` +
      `Install it first (npm install -g ${packageName}) or disable this MCP server in config.`,
  );
}

export class McpConnector {
  private client: Client | null = null;

  constructor(private readonly config: McpServerConfig) {}

  async connect(): Promise<Client> {
    if (this.config.transport === "stdio") {
      if (!this.config.command) {
        throw new McpConnectionError("No command specified for stdio transport");
      }
      if (!Bun.which(this.config.command) && !existsSync(this.config.command)) {
        throw new McpConnectionError(
          `Command '${this.config.command}' not found. Please install it first.`,
        );
      }
      if (this.config.command === "npx") {
        validateNpxPackage(this.config);
      }

      const transport = new StdioClientTransport({
        command: this.config.command,
        args: this.config.args,
        ...(Object.keys(this.config.env).length ? { env: this.config.env } : {}),
      });
      const client = new Client({ name: "bourbon", version: "0.1.0" }, { capabilities: {} });
      await client.connect(transport);
      this.client = client;
      return client;
    }

    if (!this.config.url) {
      throw new McpConnectionError("No URL specified for HTTP transport");
    }

    const transport = new StreamableHTTPClientTransport(new URL(this.config.url), {
      ...(Object.keys(this.config.headers).length
        ? { requestInit: { headers: this.config.headers } }
        : {}),
    });
    const client = new Client({ name: "bourbon", version: "0.1.0" }, { capabilities: {} });
    await client.connect(transport);
    this.client = client;
    return client;
  }

  async disconnect(): Promise<void> {
    if (this.client) {
      await this.client.close();
      this.client = null;
    }
  }

  isConnected(): boolean {
    return this.client !== null;
  }
}
