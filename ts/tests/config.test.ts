import { describe, expect, test } from "bun:test";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { loadConfig, writeDefaultConfig } from "../src/config";

describe("config loader", () => {
  test("parses full configuration", () => {
    const directory = mkdtempSync(join(tmpdir(), "bourbon-config-"));
    const path = join(directory, "config.toml");
    writeFileSync(
      path,
      `[llm]
default_provider = "kimi"

[llm.anthropic]
api_key = "anthropic-key"
model = "claude-test"
base_url = "https://api.anthropic.com"
max_tokens = 1234

[llm.openai]
api_key = "openai-key"
model = "kimi-model"
base_url = "https://api.moonshot.ai/v1"
max_tokens = 4321

[ui]
max_tool_rounds = 7
token_threshold = 5000
auto_compact = false

[tasks]
storage_dir = "~/custom-tasks"
default_list_id = "list-x"

[memory]
enabled = false

[memory.semantic]
provider = "fastembed"
model = "custom-model"
top_k = 4
min_similarity = 0.5

[observability]
enabled = true
service_name = "svc"
otlp_endpoint = "http://collector"

[audit]
enabled = false
log_dir = "~/audit-test"

[access_control]
default_action = "allow"

[access_control.file]
allow = ["{workdir}/**"]
deny = ["~/.ssh/**"]
mandatory_deny = ["~/.ssh/**"]

[access_control.command]
deny_patterns = ["systemctl *"]
need_approval_patterns = ["git push *"]

[sandbox]
enabled = false
provider = "local"

[sandbox.filesystem]
writable = ["{workdir}"]
readonly = ["/usr"]
deny = ["~/.aws"]

[sandbox.network]
enabled = true
allow_domains = ["*.example.com"]

[sandbox.resources]
timeout = 15
max_memory = "1G"
max_output = 1000

[sandbox.credentials]
clean_env = false
passthrough_vars = ["PATH"]

[sandbox.docker]
image = "alpine"
pull_policy = "never"
user = "root"

[mcp]
enabled = true
default_timeout = 12

[[mcp.servers]]
name = "docs"
transport = "stdio"
command = "bun"
args = ["server.ts"]
`,
    );

    try {
      const config = loadConfig(path);
      expect(config.defaultProvider).toBe("kimi");
      expect(config.anthropic.apiKey).toBe("anthropic-key");
      expect(config.openai.model).toBe("kimi-model");
      expect(config.ui.maxToolRounds).toBe(7);
      expect(config.ui.autoCompact).toBe(false);
      expect(config.tasks.storageDir).toBe("~/custom-tasks");
      expect(config.memory.enabled).toBe(false);
      expect(config.memory.semantic.topK).toBe(4);
      expect(config.observability.enabled).toBe(true);
      expect(config.audit.enabled).toBe(false);
      expect(config.accessControl.command.denyPatterns).toContain("systemctl *");
      expect(config.sandbox.enabled).toBe(false);
      expect(config.sandbox.network.allowDomains).toEqual(["*.example.com"]);
      expect(config.sandbox.credentials.cleanEnv).toBe(false);
      expect(config.sandbox.docker.image).toBe("alpine");
      expect(config.mcp.enabled).toBe(true);
      expect(config.mcp.defaultTimeout).toBe(12);
      expect(config.mcp.servers[0]!.name).toBe("docs");
    } finally {
      rmSync(directory, { recursive: true, force: true });
    }
  });

  test("applies defaults for a minimal config", () => {
    const directory = mkdtempSync(join(tmpdir(), "bourbon-config-"));
    const path = join(directory, "config.toml");
    writeFileSync(path, `[llm.anthropic]\napi_key = "x"\nmodel = "m"\n`);

    try {
      const config = loadConfig(path);
      expect(config.defaultProvider).toBe("anthropic");
      expect(config.ui.maxToolRounds).toBe(50);
      expect(config.memory.enabled).toBe(true);
      expect(config.memory.semantic.provider).toBe("fastembed");
      expect(config.sandbox.enabled).toBe(true);
      expect(config.sandbox.provider).toBe("auto");
      expect(config.mcp.enabled).toBe(true);
      expect(config.accessControl.defaultAction).toBe("allow");
    } finally {
      rmSync(directory, { recursive: true, force: true });
    }
  });

  test("writes a usable default config", () => {
    const directory = mkdtempSync(join(tmpdir(), "bourbon-config-"));
    const path = join(directory, "config.toml");
    try {
      writeDefaultConfig("anthropic-key", "openai-key", path);
      const config = loadConfig(path);
      expect(config.anthropic.apiKey).toBe("anthropic-key");
      expect(config.openai.apiKey).toBe("openai-key");
      expect(readFileSync(path, "utf8")).toContain("[llm.anthropic]");
    } finally {
      rmSync(directory, { recursive: true, force: true });
    }
  });

  test("rejects missing and invalid configs", () => {
    expect(() => loadConfig("/definitely/missing/config.toml")).toThrow(
      "Configuration not found",
    );

    const directory = mkdtempSync(join(tmpdir(), "bourbon-config-"));
    const path = join(directory, "config.toml");
    writeFileSync(path, `[llm]\ndefault_provider = "unknown"\n`);
    try {
      expect(() => loadConfig(path)).toThrow("Unknown default_provider");
    } finally {
      rmSync(directory, { recursive: true, force: true });
    }
  });
});
