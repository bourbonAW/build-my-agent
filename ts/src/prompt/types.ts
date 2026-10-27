export interface SkillCatalogSource {
  getCatalog(): string;
}

export interface McpCatalogSource {
  getConnectionSummary(): {
    enabled: boolean;
    totalTools: number;
  };
  listMcpTools(): string[];
  serverNames(): string[];
}

export interface MemoryAnchorSource {
  getMemoryDir(): string;
}

export interface PromptContext {
  workdir: string;
  skillManager?: SkillCatalogSource;
  mcpManager?: McpCatalogSource;
  memoryManager?: MemoryAnchorSource;
  memoryConfig?: {
    memoryMdTokenLimit: number;
    userMdTokenLimit: number;
  };
}

export type PromptSectionContent =
  | string
  | ((ctx: PromptContext) => string | Promise<string>);

export interface PromptSection {
  name: string;
  order: number;
  content: PromptSectionContent;
}
