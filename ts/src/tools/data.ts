import { existsSync, readFileSync } from "node:fs";
import { safePath } from "./base";
import type { Tool } from "./types";
import { requireString } from "./types";

export function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let field = "";
  let quoted = false;

  for (let index = 0; index < text.length; index += 1) {
    const char = text[index]!;
    if (quoted) {
      if (char === '"') {
        if (text[index + 1] === '"') {
          field += '"';
          index += 1;
        } else {
          quoted = false;
        }
      } else {
        field += char;
      }
      continue;
    }

    if (char === '"') {
      quoted = true;
    } else if (char === ",") {
      row.push(field);
      field = "";
    } else if (char === "\n" || char === "\r") {
      if (char === "\r" && text[index + 1] === "\n") index += 1;
      row.push(field);
      field = "";
      if (row.some((value) => value.length > 0)) rows.push(row);
      row = [];
    } else {
      field += char;
    }
  }

  row.push(field);
  if (row.some((value) => value.length > 0)) rows.push(row);
  return rows;
}

function numericStats(values: number[]): {
  count: number;
  mean: number | null;
  std: number | null;
  min: number | null;
  max: number | null;
} {
  if (!values.length) return { count: 0, mean: null, std: null, min: null, max: null };
  const mean = values.reduce((sum, value) => sum + value, 0) / values.length;
  const variance =
    values.length > 1
      ? values.reduce((sum, value) => sum + (value - mean) ** 2, 0) / (values.length - 1)
      : 0;
  return {
    count: values.length,
    mean,
    std: values.length > 1 ? Math.sqrt(variance) : null,
    min: Math.min(...values),
    max: Math.max(...values),
  };
}

export function csvAnalyze(
  filePath: string,
  operations: string[] = ["summary"],
): Record<string, unknown> {
  if (!existsSync(filePath)) {
    return { success: false, error: `File not found: ${filePath}` };
  }

  const rows = parseCsv(readFileSync(filePath, "utf8"));
  if (!rows.length) {
    return { success: false, error: "CSV file is empty" };
  }

  const [header, ...dataRows] = rows;
  const columns = header!;
  const records = dataRows.map((row) =>
    Object.fromEntries(columns.map((column, index) => [column, row[index] ?? ""])),
  );

  const stats: Record<string, ReturnType<typeof numericStats>> = {};
  const groups: Record<string, Record<string, number>> = {};
  const numericColumns = columns.filter((column) => {
    const values = records
      .map((record) => record[column] ?? "")
      .filter((value) => value.trim() !== "");
    return (
      values.length > 0 &&
      values.every((value) => Number.isFinite(Number(value)))
    );
  });

  for (const operation of operations.length ? operations : ["summary"]) {
    if (operation === "summary") {
      for (const column of numericColumns) {
        stats[column] = numericStats(
          records
            .map((record) => Number(record[column]))
            .filter((value) => Number.isFinite(value)),
        );
      }
    } else if (operation.startsWith("groupby:")) {
      const column = operation.slice("groupby:".length);
      if (!columns.includes(column)) continue;
      const counts: Record<string, number> = {};
      for (const record of records) {
        const key = String(record[column] ?? "");
        counts[key] = (counts[key] ?? 0) + 1;
      }
      groups[column] = counts;
    }
  }

  return {
    success: true,
    file_path: filePath,
    row_count: records.length,
    columns,
    stats,
    groups,
    sample: records.slice(0, 5),
    error: "",
  };
}

export function jsonQuery(filePath: string, query?: string): Record<string, unknown> {
  if (!existsSync(filePath)) {
    return { success: false, error: `File not found: ${filePath}` };
  }

  try {
    let data: unknown = JSON.parse(readFileSync(filePath, "utf8"));
    if (query) {
      for (const part of query.split(".")) {
        if (Array.isArray(data)) {
          if (!/^\d+$/.test(part)) {
            return { success: false, error: "Cannot navigate into array with non-numeric key" };
          }
          const index = Number(part);
          if (index < 0 || index >= data.length) {
            return { success: false, error: `Index ${index} out of range` };
          }
          data = data[index];
        } else if (data !== null && typeof data === "object") {
          data = (data as Record<string, unknown>)[part];
        } else {
          return { success: false, error: `Cannot navigate into ${typeof data}` };
        }
      }
    }
    return { success: true, file_path: filePath, query, data };
  } catch (error) {
    return { success: false, error: error instanceof Error ? error.message : String(error) };
  }
}

export const csvAnalyzeTool: Tool = {
  name: "CsvAnalyze",
  aliases: ["csv_analyze"],
  description: "Analyze CSV file with statistics and grouping.",
  inputSchema: {
    type: "object",
    properties: {
      file_path: { type: "string", description: "Path to CSV file" },
      operations: {
        type: "array",
        description: "List of operations to perform",
        items: { type: "string" },
        default: ["summary"],
      },
    },
    required: ["file_path"],
  },
  riskLevel: "low",
  alwaysLoad: false,
  shouldDefer: true,
  isReadOnly: true,
  requiredCapabilities: ["file_read"],
  searchHint: "csv data analyze statistics spreadsheet",
  run: async (input, ctx) => {
    try {
      const resolved = safePath(requireString(input, "file_path"), ctx.workdir);
      const operations = Array.isArray(input.operations)
        ? input.operations.map(String)
        : ["summary"];
      const result = csvAnalyze(resolved, operations);
      if (!result.success) return `Error: ${String(result.error ?? "Unknown error")}`;
      return JSON.stringify(result, null, 2);
    } catch (error) {
      return `Error: ${error instanceof Error ? error.message : String(error)}`;
    }
  },
};

export const jsonQueryTool: Tool = {
  name: "JsonQuery",
  aliases: ["json_query"],
  description: "Query JSON file with path expression.",
  inputSchema: {
    type: "object",
    properties: {
      file_path: { type: "string", description: "Path to JSON file" },
      query: { type: "string", description: "Dot-notation query path (e.g., 'users.0.name')" },
    },
    required: ["file_path"],
  },
  riskLevel: "low",
  alwaysLoad: false,
  shouldDefer: true,
  isReadOnly: true,
  requiredCapabilities: ["file_read"],
  searchHint: "json query filter jq data",
  run: async (input, ctx) => {
    try {
      const resolved = safePath(requireString(input, "file_path"), ctx.workdir);
      const query = typeof input.query === "string" ? input.query : undefined;
      const result = jsonQuery(resolved, query);
      if (!result.success) return `Error: ${String(result.error ?? "Unknown error")}`;
      return JSON.stringify(result, null, 2);
    } catch (error) {
      return `Error: ${error instanceof Error ? error.message : String(error)}`;
    }
  },
};
