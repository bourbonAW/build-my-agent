import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createToolRegistry } from "../src/tools";
import type { ToolContext } from "../src/tools";
import { testConfig } from "./helpers/config";
import { buildDocx, buildPdf } from "./helpers/fixtures";

let workdir: string;
const registry = createToolRegistry();

function ctx(): ToolContext {
  return { workdir, config: testConfig() };
}

beforeEach(() => {
  workdir = mkdtempSync(join(tmpdir(), "bourbon-tools-"));
});

afterEach(() => {
  rmSync(workdir, { recursive: true, force: true });
});

describe("WebFetch", () => {
  test("fetches a local page and reports HTTP errors", async () => {
    const server = Bun.serve({
      port: 0,
      fetch(request) {
        const url = new URL(request.url);
        if (url.pathname === "/missing") {
          return new Response("not found", { status: 404 });
        }
        return new Response("<html><body>hello web</body></html>", {
          headers: { "content-type": "text/html" },
        });
      },
    });

    try {
      const body = await registry.call(
        "WebFetch",
        { url: `http://127.0.0.1:${server.port}/page` },
        ctx(),
      );
      expect(body).toContain("hello web");

      const missing = await registry.call(
        "WebFetch",
        { url: `http://127.0.0.1:${server.port}/missing` },
        ctx(),
      );
      expect(missing).toContain("Error:");
    } finally {
      server.stop(true);
    }
  });

  test("rejects invalid URLs", async () => {
    const result = await registry.call("WebFetch", { url: "not-a-url" }, ctx());
    expect(result).toContain("Invalid URL format");
  });
});

describe("data tools", () => {
  test("analyzes CSV statistics and groups", async () => {
    writeFileSync(
      join(workdir, "data.csv"),
      'name,score,team\nAlice,10,red\nBob,20,blue\n"Carol, Jr.",30,red\n',
    );

    const result = JSON.parse(
      await registry.call(
        "CsvAnalyze",
        { file_path: "data.csv", operations: ["summary", "groupby:team"] },
        ctx(),
      ),
    ) as {
      row_count: number;
      columns: string[];
      stats: Record<string, { mean: number }>;
      groups: Record<string, Record<string, number>>;
      sample: Array<Record<string, string>>;
    };

    expect(result.row_count).toBe(3);
    expect(result.columns).toEqual(["name", "score", "team"]);
    expect(result.stats.score!.mean).toBe(20);
    expect(result.groups.team).toEqual({ red: 2, blue: 1 });
    expect(result.sample[2]!.name).toBe("Carol, Jr.");
  });

  test("queries nested JSON with dot notation", async () => {
    writeFileSync(
      join(workdir, "data.json"),
      JSON.stringify({ users: [{ name: "Ada" }, { name: "Grace" }], count: 2 }),
    );

    const result = JSON.parse(
      await registry.call(
        "JsonQuery",
        { file_path: "data.json", query: "users.1.name" },
        ctx(),
      ),
    ) as { data: string };
    expect(result.data).toBe("Grace");

    const missing = await registry.call(
      "JsonQuery",
      { file_path: "data.json", query: "users.9.name" },
      ctx(),
    );
    expect(missing).toContain("out of range");
  });
});

describe("document tools", () => {
  test("extracts text from PDFs", async () => {
    writeFileSync(join(workdir, "doc.pdf"), buildPdf("Hello PDF"));

    const text = await registry.call("PdfRead", { file_path: "doc.pdf" }, ctx());
    expect(text).toContain("Hello PDF");
    expect(text).toContain("--- Page 1 ---");

    const laterPage = await registry.call(
      "PdfRead",
      { file_path: "doc.pdf", page_range: [1, 2] },
      ctx(),
    );
    expect(laterPage).toBe("");
  });

  test("converts DOCX to markdown", async () => {
    const path = join(workdir, "doc.docx");
    buildDocx(path, "Title", "Hello docx");

    const markdown = await registry.call("DocxRead", { file_path: "doc.docx" }, ctx());
    expect(markdown).toContain("# Title");
    expect(markdown).toContain("Hello docx");
  });

  test("reports missing documents", async () => {
    expect(await registry.call("PdfRead", { file_path: "missing.pdf" }, ctx())).toContain(
      "Error:",
    );
    expect(await registry.call("DocxRead", { file_path: "missing.docx" }, ctx())).toContain(
      "Error:",
    );
  });
});

describe("AstGrep", () => {
  test("either searches or reports a missing binary", async () => {
    writeFileSync(join(workdir, "sample.ts"), "const value = 1;\n");
    const result = await registry.call(
      "AstGrep",
      { pattern: "const $A = $B", path: ".", language: "typescript" },
      ctx(),
    );
    expect(result.includes("Error: ast-grep not found") || result.includes("Found")).toBe(true);
  });
});
