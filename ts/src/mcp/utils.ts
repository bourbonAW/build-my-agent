import type { McpServerConfig } from "./config";

export function expandEnvVars(value: string): string {
  return value.replace(/\$\{(\w+)\}/g, (match, name: string) => process.env[name] ?? match);
}

export function formatServerInfo(config: McpServerConfig): string {
  const parts = [
    `Server: ${config.name}`,
    `  Transport: ${config.transport}`,
    `  Enabled: ${config.enabled}`,
  ];
  if (config.transport === "stdio") {
    parts.push(`  Command: ${config.command}`);
    if (config.args.length) parts.push(`  Args: ${config.args.join(" ")}`);
    if (Object.keys(config.env).length) {
      parts.push(`  Env: ${Object.keys(config.env).join(", ")}`);
    }
  } else {
    parts.push(`  URL: ${config.url}`);
  }
  return parts.join("\n");
}
