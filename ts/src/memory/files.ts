import { existsSync, readFileSync } from "node:fs";

const PREAMBLE_KEY = "__preamble__";

export function estimateTokens(text: string): number {
  return Math.floor(text.length / 4);
}

export function truncateToTokens(text: string, tokenLimit: number): string {
  if (tokenLimit <= 0) return "";
  if (estimateTokens(text) <= tokenLimit) return text;

  const charLimit = tokenLimit * 4;
  let truncated = text.slice(0, charLimit);
  const lastNewline = truncated.lastIndexOf("\n");
  if (lastNewline > charLimit / 2) {
    truncated = truncated.slice(0, lastNewline);
  }
  return `${truncated.trimEnd()}\n\n[... truncated to token limit ...]`;
}

export function readFileAnchor(path: string, tokenLimit: number): string {
  if (!existsSync(path)) return "";
  try {
    return truncateToTokens(readFileSync(path, "utf8"), tokenLimit);
  } catch {
    return "";
  }
}

function parseSections(text: string): Array<[string, string]> {
  const sections: Array<[string, string]> = [];
  let currentKey = PREAMBLE_KEY;
  let currentLines: string[] = [];

  for (const line of text.split("\n")) {
    if (line.startsWith("#")) {
      if (currentLines.length) {
        sections.push([currentKey, currentLines.join("\n").trim()]);
      }
      currentKey = line.replace(/^#+/, "").trim().toLowerCase();
      currentLines = [line];
      continue;
    }
    currentLines.push(line);
  }

  if (currentLines.length) {
    sections.push([currentKey, currentLines.join("\n").trim()]);
  }
  return sections.filter(([, content]) => content.length > 0);
}

function readText(path: string | null): string {
  if (!path || !existsSync(path)) return "";
  try {
    return readFileSync(path, "utf8");
  } catch {
    return "";
  }
}

function mergeUserMdText(globalText: string, projectText: string): string {
  if (!globalText) return projectText;
  if (!projectText) return globalText;

  const globalSections = parseSections(globalText);
  const projectSections = parseSections(projectText);
  const onlyPreamble = (sections: Array<[string, string]>) =>
    sections.every(([key]) => key === PREAMBLE_KEY);

  if (onlyPreamble(globalSections) && onlyPreamble(projectSections)) {
    return projectText;
  }

  const globalMap = new Map(globalSections);
  const projectMap = new Map(projectSections);
  const parts: string[] = [];

  const preamble = projectMap.get(PREAMBLE_KEY) ?? globalMap.get(PREAMBLE_KEY);
  if (preamble) parts.push(preamble);

  const seen = new Set<string>();
  for (const [key, content] of globalSections) {
    if (key === PREAMBLE_KEY) continue;
    parts.push(projectMap.get(key) ?? content);
    seen.add(key);
  }

  for (const [key, content] of projectSections) {
    if (key === PREAMBLE_KEY || seen.has(key)) continue;
    parts.push(content);
  }

  return `${parts.filter(Boolean).join("\n\n").trim()}\n`;
}

export function mergeUserMd(globalPath: string | null, projectPath: string | null): string {
  return mergeUserMdText(readText(globalPath), readText(projectPath));
}

export function renderMergedUserMdForPrompt(
  globalPath: string | null,
  projectPath: string | null,
  tokenLimit: number,
): string {
  return truncateToTokens(mergeUserMd(globalPath, projectPath), tokenLimit);
}
