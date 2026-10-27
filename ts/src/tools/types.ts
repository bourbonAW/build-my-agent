import type { CapabilityType } from "../access_control/capabilities";
import type { Agent } from "../agent/agent";
import type { BourbonConfig } from "../config";
import type { ToolDefinition } from "../llm";
import type { MemoryActor, MemoryManager } from "../memory";
import type { SkillManager } from "../skills";

export type RiskLevel = "low" | "medium" | "high";

export interface ToolContext {
  workdir: string;
  signal?: AbortSignal;
  agent?: Agent;
  config?: BourbonConfig;
  executionMarkers?: Set<string>;
  skillManager?: SkillManager;
  onToolsDiscovered?: (names: Set<string>) => void;
  memoryManager?: MemoryManager;
  memoryActor?: MemoryActor;
  registry?: ToolRegistry;
}

export interface Tool {
  name: string;
  description: string;
  inputSchema: Record<string, unknown>;
  riskLevel: RiskLevel;
  aliases?: string[];
  alwaysLoad?: boolean;
  shouldDefer?: boolean;
  isReadOnly?: boolean;
  isDestructive?: boolean;
  riskPatterns?: string[];
  isConcurrencySafe?: (input: Record<string, unknown>) => boolean;
  requiredCapabilities?: CapabilityType[];
  searchHint?: string;
  run: (input: Record<string, unknown>, ctx: ToolContext) => Promise<string>;
}

export class ToolRegistry {
  private readonly tools = new Map<string, Tool>();
  private readonly aliases = new Map<string, string>();

  register(tool: Tool): void {
    const alwaysLoad = tool.alwaysLoad ?? !tool.shouldDefer;
    if (tool.shouldDefer && tool.alwaysLoad === true) {
      throw new Error(
        `Tool '${tool.name}': shouldDefer=true implies alwaysLoad=false; set alwaysLoad=false explicitly.`,
      );
    }
    this.tools.set(tool.name, { ...tool, alwaysLoad });
    for (const alias of tool.aliases ?? []) {
      this.aliases.set(alias, tool.name);
    }
  }

  get(name: string): Tool | undefined {
    const direct = this.tools.get(name);
    if (direct) return direct;
    const canonical = this.aliases.get(name);
    return canonical ? this.tools.get(canonical) : undefined;
  }

  listTools(): Tool[] {
    return [...this.tools.values()];
  }

  definitions(discovered: Set<string> = new Set()): ToolDefinition[] {
    return this.listTools()
      .filter((tool) => tool.alwaysLoad || discovered.has(tool.name))
      .map((tool) => ({
        name: tool.name,
        description: tool.description,
        input_schema: tool.inputSchema,
      }));
  }

  async call(name: string, input: Record<string, unknown>, ctx: ToolContext): Promise<string> {
    const tool = this.get(name);
    if (!tool) throw new Error(`Unknown tool '${name}'`);
    return tool.run(input, ctx);
  }
}

export function requireString(input: Record<string, unknown>, key: string): string {
  const value = input[key];
  if (typeof value !== "string") {
    throw new Error(`Missing required string parameter: ${key}`);
  }
  return value;
}

export function optionalString(
  input: Record<string, unknown>,
  key: string,
): string | undefined {
  const value = input[key];
  return typeof value === "string" ? value : undefined;
}

export function optionalNumber(
  input: Record<string, unknown>,
  key: string,
): number | undefined {
  const value = input[key];
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

export function optionalBoolean(
  input: Record<string, unknown>,
  key: string,
): boolean | undefined {
  const value = input[key];
  return typeof value === "boolean" ? value : undefined;
}

export function optionalStringArray(
  input: Record<string, unknown>,
  key: string,
): string[] | undefined {
  const value = input[key];
  return Array.isArray(value) && value.every((item) => typeof item === "string")
    ? value
    : undefined;
}
