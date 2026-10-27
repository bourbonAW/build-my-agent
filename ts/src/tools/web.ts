import type { Tool } from "./types";
import { requireString } from "./types";

export interface FetchResult {
  success: boolean;
  url: string;
  statusCode?: number;
  text?: string;
  error?: string;
}

export async function fetchUrl(
  url: string,
  timeout = 30,
  maxLength = 100000,
): Promise<FetchResult> {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return { success: false, url, error: "Invalid URL format. Must be http:// or https://" };
  }
  if (!["http:", "https:"].includes(parsed.protocol) || !parsed.hostname) {
    return { success: false, url, error: "Invalid URL format. Must be http:// or https://" };
  }

  try {
    const response = await fetch(url, {
      signal: AbortSignal.timeout(timeout * 1000),
    });
    let text = await response.text();
    if (text.length > maxLength) {
      text = `${text.slice(0, maxLength)}\n... [truncated]`;
    }
    return {
      success: response.status < 400,
      url,
      statusCode: response.status,
      text,
    };
  } catch (error) {
    const name = error instanceof Error ? error.name : "";
    if (name === "TimeoutError" || name === "AbortError") {
      return { success: false, url, error: `Timeout after ${timeout}s` };
    }
    return {
      success: false,
      url,
      error: error instanceof Error ? error.message : String(error),
    };
  }
}

export const webFetchTool: Tool = {
  name: "WebFetch",
  aliases: ["fetch_url"],
  description: "Fetch and extract content from a URL.",
  inputSchema: {
    type: "object",
    properties: {
      url: { type: "string", description: "URL to fetch (http:// or https://)" },
      timeout: { type: "integer", description: "Request timeout in seconds", default: 30 },
      max_length: { type: "integer", description: "Maximum response length", default: 100000 },
    },
    required: ["url"],
  },
  riskLevel: "medium",
  alwaysLoad: false,
  shouldDefer: true,
  isConcurrencySafe: () => true,
  requiredCapabilities: ["net"],
  searchHint: "web fetch url http download browser",
  run: async (input) => {
    const result = await fetchUrl(
      requireString(input, "url"),
      typeof input.timeout === "number" ? input.timeout : 30,
      typeof input.max_length === "number" ? input.max_length : 100000,
    );
    if (!result.success) {
      return `Error: ${result.error ?? `HTTP ${result.statusCode ?? "unknown"}`}`;
    }
    return result.text ?? "";
  },
};
