import type { Client } from "@modelcontextprotocol/sdk/client/index.js";
import type { McpConfig, McpServerConfig } from "./config";
import { getEnabledServers } from "./config";
import { McpConnector } from "./connector";
import type { Tool, ToolRegistry } from "../tools";

export interface ConnectionResult {
  success: boolean;
  serverName: string;
  toolsCount: number;
  error: string | null;
}

export class MCPManager {
  private readonly connectors = new Map<string, McpConnector>();
  private readonly clients = new Map<string, Client>();
  private readonly results = new Map<string, ConnectionResult>();

  constructor(
    readonly config: McpConfig,
    private readonly toolRegistry: ToolRegistry,
  ) {}

  async connectAll(): Promise<Record<string, ConnectionResult>> {
    if (!this.config.enabled) return {};
    const results: Record<string, ConnectionResult> = {};

    for (const server of getEnabledServers(this.config)) {
      const result = await this.connectServer(server);
      results[server.name] = result;
      this.results.set(server.name, result);
    }
    return results;
  }

  private async connectServer(server: McpServerConfig): Promise<ConnectionResult> {
    let lastError: Error | null = null;

    for (let attempt = 0; attempt < server.maxRetries; attempt += 1) {
      try {
        const connector = new McpConnector(server);
        const client = await connector.connect();
        this.connectors.set(server.name, connector);
        this.clients.set(server.name, client);

        const toolsCount = await this.registerServerTools(server.name, client);
        return { success: true, serverName: server.name, toolsCount, error: null };
      } catch (error) {
        lastError = error instanceof Error ? error : new Error(String(error));
        if (attempt < server.maxRetries - 1) {
          await Bun.sleep(server.retryDelay * 1000 * 2 ** attempt);
        }
      }
    }

    const base = lastError?.message ?? "Unknown error";
    return {
      success: false,
      serverName: server.name,
      toolsCount: 0,
      error: server.maxRetries > 1 ? `Failed after ${server.maxRetries} attempts: ${base}` : base,
    };
  }

  private async registerServerTools(serverName: string, client: Client): Promise<number> {
    const listed = await client.listTools();
    for (const mcpTool of listed.tools) {
      const toolName = `${serverName}-${mcpTool.name}`;
      const tool: Tool = {
        name: toolName,
        description: `[${serverName} MCP] ${mcpTool.description ?? "No description"}`,
        inputSchema: (mcpTool.inputSchema as Record<string, unknown>) ?? {
          type: "object",
          properties: {},
        },
        riskLevel: "medium",
        requiredCapabilities: ["mcp"],
        isConcurrencySafe: () => true,
        run: async (input) => this.callTool(serverName, mcpTool.name, input),
      };
      this.toolRegistry.register(tool);
    }
    return listed.tools.length;
  }

  private async callTool(
    serverName: string,
    toolName: string,
    args: Record<string, unknown>,
  ): Promise<string> {
    const client = this.clients.get(serverName);
    if (!client) return `Error calling ${serverName}:${toolName}: server is not connected`;

    try {
      const result = await client.callTool(
        { name: toolName, arguments: args },
        undefined,
        { timeout: this.config.defaultTimeout * 1000 },
      );
      const content = (result.content ?? []) as Array<Record<string, unknown>>;
      const parts = content.map((block) =>
        block.type === "text" ? String(block.text ?? "") : `[${String(block.type)} content]`,
      );
      return parts.join("\n") || "(no output)";
    } catch (error) {
      return `Error calling ${serverName}:${toolName}: ${
        error instanceof Error ? error.message : String(error)
      }`;
    }
  }

  async disconnectAll(): Promise<void> {
    for (const [name, connector] of this.connectors) {
      try {
        await connector.disconnect();
      } catch {
        // best-effort disconnect
      }
      this.clients.delete(name);
    }
    this.connectors.clear();
    this.results.clear();
  }

  getConnectionStatus(serverName: string): Record<string, unknown> {
    const result = this.results.get(serverName);
    const connector = this.connectors.get(serverName);
    if (!result) return { connected: false, error: "Server not configured" };
    return {
      connected: result.success && (connector?.isConnected() ?? false),
      tools_count: result.toolsCount,
      error: result.error,
    };
  }

  serverNames(): string[] {
    return this.config.servers.map((server) => server.name);
  }

  listMcpTools(): string[] {
    const prefixes = this.serverNames().map((name) => `${name}-`);
    return this.toolRegistry
      .listTools()
      .map((tool) => tool.name)
      .filter((name) => prefixes.some((prefix) => name.startsWith(prefix)));
  }

  getConnectionSummary(): {
    enabled: boolean;
    configured: number;
    attempted: number;
    connected: number;
    failed: number;
    totalTools: number;
    servers: Record<string, { connected: boolean; tools: number; error: string | null }>;
  } {
    const total = this.results.size;
    const connected = [...this.results.values()].filter((result) => result.success).length;
    const totalTools = [...this.results.values()].reduce(
      (sum, result) => sum + result.toolsCount,
      0,
    );

    return {
      enabled: this.config.enabled,
      configured: this.config.servers.length,
      attempted: total,
      connected,
      failed: total - connected,
      totalTools,
      servers: Object.fromEntries(
        [...this.results.entries()].map(([name, result]) => [
          name,
          { connected: result.success, tools: result.toolsCount, error: result.error },
        ]),
      ),
    };
  }
}
