import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { parse } from "smol-toml";
import { parseMcpConfig } from "./mcp/config";
import type { McpConfig } from "./mcp/config";

export interface ProviderConfig {
  apiKey: string;
  model: string;
  baseUrl: string;
  maxTokens: number;
  temperature: number;
}

export interface BashConfig {
  allowedCommands: string[];
  blockedCommands: string[];
  timeoutSeconds: number;
}

export interface RgConfig {
  binaryPath: string;
  defaultArgs: string[];
  maxResults: number;
}

export interface AstGrepConfig {
  binaryPath: string;
  defaultArgs: string[];
}

export interface ToolsConfig {
  bash: BashConfig;
  rg: RgConfig;
  astGrep: AstGrepConfig;
}

export interface UiConfig {
  theme: string;
  autoCompact: boolean;
  tokenThreshold: number;
  showTokenCount: boolean;
  syntaxHighlighting: boolean;
  maxToolRounds: number;
}

export interface TasksConfig {
  enabled: boolean;
  storageDir: string;
  defaultListId: string;
}

export interface MemorySemanticConfig {
  enabled: boolean;
  provider: string;
  model: string;
  topK: number;
  minSimilarity: number;
}

export interface MemoryConfig {
  enabled: boolean;
  storageDir: string;
  recallLimit: number;
  memoryMdTokenLimit: number;
  userMdTokenLimit: number;
  semantic: MemorySemanticConfig;
}

export interface ObservabilityConfig {
  enabled: boolean;
  serviceName: string;
  otlpEndpoint: string;
  otlpHeaders: Record<string, string>;
}

export interface FileAccessControlConfig {
  allow: string[];
  deny: string[];
  mandatoryDeny: string[];
}

export interface CommandAccessControlConfig {
  denyPatterns: string[];
  needApprovalPatterns: string[];
}

export interface AccessControlConfig {
  defaultAction: "allow" | "deny" | "need_approval";
  file: FileAccessControlConfig;
  command: CommandAccessControlConfig;
}

export interface SandboxFilesystemConfig {
  writable: string[];
  readonly: string[];
  deny: string[];
}

export interface SandboxNetworkConfig {
  enabled: boolean;
  allowDomains: string[];
}

export interface SandboxResourcesConfig {
  timeout: number;
  maxMemory: string;
  maxOutput: number;
}

export interface SandboxCredentialsConfig {
  cleanEnv: boolean;
  passthroughVars: string[];
}

export interface SandboxDockerConfig {
  image: string;
  pullPolicy: string;
  user: string;
}

export interface SandboxConfig {
  enabled: boolean;
  provider: string;
  filesystem: SandboxFilesystemConfig;
  network: SandboxNetworkConfig;
  resources: SandboxResourcesConfig;
  credentials: SandboxCredentialsConfig;
  docker: SandboxDockerConfig;
}

export interface AuditConfig {
  enabled: boolean;
  logDir: string;
  format: string;
}

export type ProviderName = "anthropic" | "openai" | "kimi";

export interface BourbonConfig {
  defaultProvider: ProviderName;
  anthropic: ProviderConfig;
  openai: ProviderConfig;
  tools: ToolsConfig;
  ui: UiConfig;
  tasks: TasksConfig;
  memory: MemoryConfig;
  observability: ObservabilityConfig;
  mcp: McpConfig;
  accessControl: AccessControlConfig;
  sandbox: SandboxConfig;
  audit: AuditConfig;
}

export const CONFIG_PATH = join(homedir(), ".bourbon", "config.toml");

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

function strArray(value: unknown, fallback: string[]): string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string")
    ? [...value]
    : [...fallback];
}

function strRecord(value: unknown): Record<string, string> {
  const data = table(value);
  return Object.fromEntries(
    Object.entries(data)
      .filter((entry): entry is [string, string] => typeof entry[1] === "string"),
  );
}

function provider(value: unknown, defaults: ProviderConfig): ProviderConfig {
  const data = table(value);
  return {
    apiKey: str(data.api_key, defaults.apiKey),
    model: str(data.model, defaults.model),
    baseUrl: str(data.base_url, defaults.baseUrl),
    maxTokens: num(data.max_tokens, defaults.maxTokens),
    temperature: num(data.temperature, defaults.temperature),
  };
}

function parseAccessControl(value: unknown): AccessControlConfig {
  const data = table(value);
  const file = table(data.file);
  const command = table(data.command);
  return {
    defaultAction: str(data.default_action, "allow") as AccessControlConfig["defaultAction"],
    file: {
      allow: strArray(file.allow, ["{workdir}/**"]),
      deny: strArray(file.deny, ["~/.ssh/**", "~/.aws/**"]),
      mandatoryDeny: strArray(file.mandatory_deny, ["~/.ssh/**"]),
    },
    command: {
      denyPatterns: strArray(command.deny_patterns, [
        "rm -rf /",
        "sudo *",
        "shutdown",
        "reboot",
        "> /dev/sda",
        "mkfs.",
      ]),
      needApprovalPatterns: strArray(command.need_approval_patterns, ["pip install *", "apt *"]),
    },
  };
}

function parseSandbox(value: unknown): SandboxConfig {
  const data = table(value);
  const filesystem = table(data.filesystem);
  const network = table(data.network);
  const resources = table(data.resources);
  const credentials = table(data.credentials);
  const docker = table(data.docker);
  return {
    enabled: bool(data.enabled, true),
    provider: str(data.provider, "auto"),
    filesystem: {
      writable: strArray(filesystem.writable, ["{workdir}"]),
      readonly: strArray(filesystem.readonly, ["/usr", "/lib"]),
      deny: strArray(filesystem.deny, ["~/.ssh", "~/.aws"]),
    },
    network: {
      enabled: bool(network.enabled, false),
      allowDomains: strArray(network.allow_domains, []),
    },
    resources: {
      timeout: num(resources.timeout, 120),
      maxMemory: str(resources.max_memory, "512M"),
      maxOutput: num(resources.max_output, 50000),
    },
    credentials: {
      cleanEnv: bool(credentials.clean_env, true),
      passthroughVars: strArray(credentials.passthrough_vars, ["PATH", "HOME", "LANG"]),
    },
    docker: {
      image: str(docker.image, "python:3.11-slim"),
      pullPolicy: str(docker.pull_policy, "if-not-present"),
      user: str(docker.user, "nobody"),
    },
  };
}

function parseMemory(value: unknown): MemoryConfig {
  const data = table(value);
  const semantic = table(data.semantic);
  return {
    enabled: bool(data.enabled, true),
    storageDir: str(data.storage_dir, "~/.bourbon/projects"),
    recallLimit: num(data.recall_limit, 8),
    memoryMdTokenLimit: num(data.memory_md_token_limit, 1200),
    userMdTokenLimit: num(data.user_md_token_limit, 600),
    semantic: {
      enabled: bool(semantic.enabled, true),
      provider: str(semantic.provider, "fastembed"),
      model: str(
        semantic.model,
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
      ),
      topK: num(semantic.top_k, 16),
      minSimilarity: num(semantic.min_similarity, 0.25),
    },
  };
}

function parseTools(value: unknown): ToolsConfig {
  const data = table(value);
  const bash = table(data.bash);
  const rg = table(data.rg);
  const astGrep = table(data.ast_grep);
  return {
    bash: {
      allowedCommands: strArray(bash.allowed_commands, ["*"]),
      blockedCommands: strArray(bash.blocked_commands, [
        "rm -rf /",
        "sudo",
        "shutdown",
        "reboot",
        "> /dev/sda",
      ]),
      timeoutSeconds: num(bash.timeout_seconds, 120),
    },
    rg: {
      binaryPath: str(rg.binary_path, "rg"),
      defaultArgs: strArray(rg.default_args, ["--smart-case", "--hidden", "--glob", "!.git"]),
      maxResults: num(rg.max_results, 100),
    },
    astGrep: {
      binaryPath: str(astGrep.binary_path, "ast-grep"),
      defaultArgs: strArray(astGrep.default_args, ["--json"]),
    },
  };
}

export function loadConfig(path: string = CONFIG_PATH): BourbonConfig {
  let raw: string;
  try {
    raw = readFileSync(path, "utf8");
  } catch {
    throw new Error(
      `Configuration not found at ${path}\nRun 'bourbon-ts --init' to create one.`,
    );
  }

  const data = table(parse(raw));
  const llm = table(data.llm);
  const ui = table(data.ui);
  const tasks = table(data.tasks);
  const observability = table(data.observability);
  const audit = table(data.audit);
  const providerName = str(llm.default_provider, "anthropic");

  if (!["anthropic", "openai", "kimi"].includes(providerName)) {
    throw new Error(`Unknown default_provider: ${providerName}`);
  }

  return {
    defaultProvider: providerName as ProviderName,
    anthropic: provider(llm.anthropic, {
      apiKey: "",
      model: "claude-sonnet-4-6",
      baseUrl: "https://api.anthropic.com",
      maxTokens: 8000,
      temperature: 0.7,
    }),
    openai: provider(llm.openai, {
      apiKey: "",
      model: "gpt-4o",
      baseUrl: "https://api.openai.com/v1",
      maxTokens: 8000,
      temperature: 0.7,
    }),
    tools: parseTools(data.tools),
    ui: {
      theme: str(ui.theme, "dracula"),
      autoCompact: bool(ui.auto_compact, true),
      tokenThreshold: num(ui.token_threshold, 100000),
      showTokenCount: bool(ui.show_token_count, true),
      syntaxHighlighting: bool(ui.syntax_highlighting, true),
      maxToolRounds: num(ui.max_tool_rounds, 50),
    },
    tasks: {
      enabled: bool(tasks.enabled, true),
      storageDir: str(tasks.storage_dir, "~/.bourbon/tasks"),
      defaultListId: str(tasks.default_list_id, "default"),
    },
    memory: parseMemory(data.memory),
    observability: {
      enabled: bool(observability.enabled, false),
      serviceName: str(observability.service_name, "bourbon"),
      otlpEndpoint: str(observability.otlp_endpoint, ""),
      otlpHeaders: strRecord(observability.otlp_headers),
    },
    mcp: parseMcpConfig(data.mcp),
    accessControl: parseAccessControl(data.access_control),
    sandbox: parseSandbox(data.sandbox),
    audit: {
      enabled: bool(audit.enabled, true),
      logDir: str(audit.log_dir, "~/.bourbon/audit/"),
      format: str(audit.format, "jsonl"),
    },
  };
}

export function activeProvider(config: BourbonConfig): ProviderConfig {
  return config.defaultProvider === "anthropic" ? config.anthropic : config.openai;
}

export function defaultConfigToml(anthropicKey: string, openaiKey: string): string {
  return `[llm]
default_provider = "anthropic"

[llm.anthropic]
api_key = ${JSON.stringify(anthropicKey)}
model = "claude-sonnet-4-6"
base_url = "https://api.anthropic.com"
max_tokens = 8000
temperature = 0.7

[llm.openai]
api_key = ${JSON.stringify(openaiKey)}
model = "gpt-4o"
base_url = "https://api.openai.com/v1"
max_tokens = 8000
temperature = 0.7

[tools.bash]
allowed_commands = ["*"]
blocked_commands = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/sda"]
timeout_seconds = 120

[tools.rg]
binary_path = "rg"
default_args = ["--smart-case", "--hidden", "--glob", "!.git"]
max_results = 100

[tools.ast_grep]
binary_path = "ast-grep"
default_args = ["--json"]

[ui]
theme = "dracula"
auto_compact = true
token_threshold = 100000
show_token_count = true
syntax_highlighting = true
max_tool_rounds = 50

[tasks]
enabled = true
storage_dir = "~/.bourbon/tasks"
default_list_id = "default"

[memory]
enabled = true
storage_dir = "~/.bourbon/projects"
recall_limit = 8
memory_md_token_limit = 1200
user_md_token_limit = 600

[memory.semantic]
enabled = true
provider = "fastembed"
model = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
top_k = 16
min_similarity = 0.25

[observability]
enabled = false
service_name = "bourbon"
otlp_endpoint = ""
otlp_headers = {}

[mcp]
enabled = true

[access_control]
default_action = "allow"

[access_control.file]
allow = ["{workdir}/**"]
deny = ["~/.ssh/**", "~/.aws/**"]
mandatory_deny = ["~/.ssh/**"]

[access_control.command]
deny_patterns = ["rm -rf /", "sudo *", "shutdown", "reboot", "> /dev/sda", "mkfs."]
need_approval_patterns = ["pip install *", "apt *"]

[sandbox]
enabled = true
provider = "auto"

[sandbox.filesystem]
writable = ["{workdir}"]
readonly = ["/usr", "/lib"]
deny = ["~/.ssh", "~/.aws"]

[sandbox.network]
enabled = false
allow_domains = []

[sandbox.resources]
timeout = 120
max_memory = "512M"
max_output = 50000

[sandbox.credentials]
clean_env = true
passthrough_vars = ["PATH", "HOME", "LANG"]

[sandbox.docker]
image = "python:3.11-slim"
pull_policy = "if-not-present"
user = "nobody"

[audit]
enabled = true
log_dir = "~/.bourbon/audit/"
format = "jsonl"
`;
}

export function writeDefaultConfig(
  anthropicKey: string,
  openaiKey: string,
  path: string = CONFIG_PATH,
): void {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, defaultConfigToml(anthropicKey, openaiKey), { mode: 0o600 });
}
