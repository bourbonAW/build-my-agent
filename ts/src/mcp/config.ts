import { expandEnvVars } from "./utils";

export interface McpServerConfig {
  name: string;
  transport: "stdio" | "http";
  enabled: boolean;
  maxRetries: number;
  retryDelay: number;
  command?: string;
  args: string[];
  env: Record<string, string>;
  stdin?: string;
  url?: string;
  headers: Record<string, string>;
  timeout?: number;
}

export interface McpConfig {
  enabled: boolean;
  defaultTimeout: number;
  servers: McpServerConfig[];
}

type TomlTable = Record<string, unknown>;

function table(value: unknown): TomlTable {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as TomlTable)
    : {};
}

function str(value: unknown, fallback: string): string {
  return typeof value === "string" ? value : fallback;
}

function num(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function bool(value: unknown, fallback: boolean): boolean {
  return typeof value === "boolean" ? value : fallback;
}

function strArray(value: unknown): string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string")
    ? [...value]
    : [];
}

function strRecord(value: unknown): Record<string, string> {
  const data = table(value);
  return Object.fromEntries(
    Object.entries(data)
      .filter((entry): entry is [string, string] => typeof entry[1] === "string")
      .map(([key, raw]) => [key, expandEnvVars(raw)]),
  );
}

export function parseServer(value: unknown): McpServerConfig {
  const data = table(value);
  const transport = str(data.transport, "stdio") === "http" ? "http" : "stdio";
  const server: McpServerConfig = {
    name: str(data.name, ""),
    transport,
    enabled: bool(data.enabled, true),
    maxRetries: num(data.max_retries, 3),
    retryDelay: num(data.retry_delay, 1),
    args: strArray(data.args),
    env: strRecord(data.env),
    headers: strRecord(data.headers),
  };

  if (typeof data.command === "string") server.command = data.command;
  if (typeof data.stdin === "string") server.stdin = data.stdin;
  if (typeof data.url === "string") server.url = data.url;
  if (typeof data.timeout === "number") server.timeout = data.timeout;

  validateServer(server);
  return server;
}

export function validateServer(server: McpServerConfig): void {
  if (!server.name) throw new Error("MCP server name is required");
  if (server.transport === "stdio" && !server.command) {
    throw new Error(`MCP server '${server.name}': command is required for stdio transport`);
  }
  if (server.transport === "http" && !server.url) {
    throw new Error(`MCP server '${server.name}': url is required for http transport`);
  }
}

export function parseMcpConfig(value: unknown): McpConfig {
  const data = table(value);
  const servers: McpServerConfig[] = [];

  if (Array.isArray(data.servers)) {
    for (const raw of data.servers) {
      try {
        servers.push(parseServer(raw));
      } catch (error) {
        process.stderr.write(
          `Warning: Skipping invalid MCP server config: ${
            error instanceof Error ? error.message : String(error)
          }\n`,
        );
      }
    }
  }

  return {
    enabled: bool(data.enabled, true),
    defaultTimeout: num(data.default_timeout, 30),
    servers,
  };
}

export function getEnabledServers(config: McpConfig): McpServerConfig[] {
  return config.servers.filter((server) => server.enabled);
}
