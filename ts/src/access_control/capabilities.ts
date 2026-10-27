export type CapabilityType = "file_read" | "file_write" | "exec" | "net" | "skill" | "mcp";

export interface InferredContext {
  capabilities: CapabilityType[];
  filePaths: string[];
}

const FILE_TOOL_CAPABILITIES: Record<string, CapabilityType> = {
  Read: "file_read",
  Write: "file_write",
  Edit: "file_write",
  Grep: "file_read",
  AstGrep: "file_read",
  Glob: "file_read",
  CsvAnalyze: "file_read",
  JsonQuery: "file_read",
  PdfRead: "file_read",
  DocxRead: "file_read",
};

const SEARCH_TOOLS_WITH_WORKDIR_DEFAULT_PATH = new Set(["Grep", "AstGrep", "Glob"]);

const BASH_NET_PATTERNS = [
  "curl ",
  "wget ",
  "http://",
  "https://",
  "pip install ",
  "pip3 install ",
  "git clone ",
  "git pull ",
  "git push ",
];
const BASH_FILE_READ_PATTERNS = ["cat ", "less ", "head ", "tail ", "grep ", "rg ", "sed ", "find ", "ls "];
const BASH_FILE_WRITE_PATTERNS = [">", "tee ", "touch ", "mkdir ", "cp ", "mv "];

function bashCommand(toolInput: Record<string, unknown>): string {
  return typeof toolInput.command === "string" ? toolInput.command : "";
}

function extractPath(toolInput: Record<string, unknown>): string | null {
  if (typeof toolInput.path === "string" && toolInput.path) return toolInput.path;
  if (typeof toolInput.file_path === "string" && toolInput.file_path) return toolInput.file_path;
  return null;
}

function containsAny(value: string, patterns: string[]): boolean {
  return patterns.some((pattern) => value.includes(pattern));
}

export function inferCapabilities(
  toolName: string,
  toolInput: Record<string, unknown>,
  baseCapabilities: CapabilityType[],
): InferredContext {
  const capabilities = [...baseCapabilities];
  const filePaths: string[] = [];

  if (toolName === "Bash") {
    const command = bashCommand(toolInput);
    if (containsAny(command, BASH_NET_PATTERNS)) capabilities.push("net");
    if (containsAny(command, BASH_FILE_READ_PATTERNS)) capabilities.push("file_read");
    if (containsAny(command, BASH_FILE_WRITE_PATTERNS)) capabilities.push("file_write");
  } else if (toolName in FILE_TOOL_CAPABILITIES) {
    capabilities.push(FILE_TOOL_CAPABILITIES[toolName]!);
    const path = extractPath(toolInput);
    if (path) filePaths.push(path);
    else if (SEARCH_TOOLS_WITH_WORKDIR_DEFAULT_PATH.has(toolName)) filePaths.push(".");
  }

  return {
    capabilities: [...new Set(capabilities)],
    filePaths,
  };
}
