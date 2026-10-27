import type { BourbonConfig } from "../../src/config";

export function testConfig(overrides: Partial<BourbonConfig> = {}): BourbonConfig {
  return {
    defaultProvider: "anthropic",
    anthropic: {
      apiKey: "test",
      model: "fake-model",
      baseUrl: "http://localhost",
      maxTokens: 256,
      temperature: 0,
    },
    openai: {
      apiKey: "",
      model: "gpt-4o",
      baseUrl: "http://localhost",
      maxTokens: 256,
      temperature: 0,
    },
    tools: {
      bash: { allowedCommands: ["*"], blockedCommands: [], timeoutSeconds: 120 },
      rg: { binaryPath: "rg", defaultArgs: [], maxResults: 100 },
      astGrep: { binaryPath: "ast-grep", defaultArgs: [] },
    },
    ui: {
      theme: "dracula",
      autoCompact: true,
      tokenThreshold: 100_000,
      showTokenCount: true,
      syntaxHighlighting: true,
      maxToolRounds: 4,
    },
    tasks: {
      enabled: true,
      storageDir: "/tmp/bourbon-ts-tasks",
      defaultListId: "default",
    },
    memory: {
      enabled: false,
      storageDir: "/tmp/bourbon-ts-memory",
      recallLimit: 8,
      memoryMdTokenLimit: 1200,
      userMdTokenLimit: 600,
      semantic: {
        enabled: false,
        provider: "fastembed",
        model: "test",
        topK: 16,
        minSimilarity: 0.25,
      },
    },
    observability: {
      enabled: false,
      serviceName: "bourbon-test",
      otlpEndpoint: "",
      otlpHeaders: {},
    },
    mcp: { enabled: false, defaultTimeout: 30, servers: [] },
    accessControl: {
      defaultAction: "allow",
      file: { allow: ["{workdir}/**"], deny: [], mandatoryDeny: [] },
      command: { denyPatterns: [], needApprovalPatterns: [] },
    },
    sandbox: {
      enabled: false,
      provider: "local",
      filesystem: { writable: ["{workdir}"], readonly: [], deny: [] },
      network: { enabled: false, allowDomains: [] },
      resources: { timeout: 10, maxMemory: "512M", maxOutput: 50000 },
      credentials: { cleanEnv: true, passthroughVars: ["PATH", "HOME"] },
      docker: { image: "python:3.11-slim", pullPolicy: "never", user: "nobody" },
    },
    audit: { enabled: false, logDir: "/tmp/bourbon-ts-audit", format: "jsonl" },
    ...overrides,
  };
}
