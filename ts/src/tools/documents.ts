import { PDFParse } from "pdf-parse";
import mammoth from "mammoth";
import { safePath } from "./base";
import type { Tool } from "./types";
import { requireString } from "./types";

export async function pdfToText(
  filePath: string,
  pageRange?: number[],
): Promise<Record<string, unknown>> {
  try {
    const data = new Uint8Array(await Bun.file(filePath).arrayBuffer());
    const parser = new PDFParse({ data });
    try {
      const result = await parser.getText();
      const pages = result.pages.filter((_page, index) => {
        if (!pageRange || pageRange.length !== 2) return true;
        const [start, end] = pageRange as [number, number];
        return index >= start && index < Math.min(end, result.pages.length);
      });

      const text = pages
        .filter((page) => page.text.trim())
        .map((page) => `--- Page ${page.num} ---\n${page.text}`)
        .join("\n");

      return {
        success: true,
        file_path: filePath,
        text,
        page_count: result.pages.length,
        pages_extracted: pages.length,
      };
    } finally {
      await parser.destroy();
    }
  } catch (error) {
    return { success: false, error: error instanceof Error ? error.message : String(error) };
  }
}

function htmlToMarkdown(html: string): string {
  let text = html;
  for (let level = 6; level >= 1; level -= 1) {
    const regex = new RegExp(`<h${level}[^>]*>([\\s\\S]*?)</h${level}>`, "gi");
    text = text.replace(regex, (_match, content: string) => {
      return `\n${"#".repeat(level)} ${content.replace(/<[^>]+>/g, "").trim()}\n`;
    });
  }
  text = text
    .replace(/<li[^>]*>([\s\S]*?)<\/li>/gi, (_match, content: string) => {
      return `- ${content.replace(/<[^>]+>/g, "").trim()}\n`;
    })
    .replace(/<p[^>]*>([\s\S]*?)<\/p>/gi, (_match, content: string) => {
      return `${content.replace(/<[^>]+>/g, "").trim()}\n\n`;
    })
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<\/?strong[^>]*>|<\/?b[^>]*>/gi, "**")
    .replace(/<\/?em[^>]*>|<\/?i[^>]*>/gi, "*")
    .replace(/<[^>]+>/g, "");

  return text
    .replaceAll("&amp;", "&")
    .replaceAll("&lt;", "<")
    .replaceAll("&gt;", ">")
    .replaceAll("&quot;", '"')
    .replaceAll("&#39;", "'")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

export async function docxToMarkdown(filePath: string): Promise<Record<string, unknown>> {
  try {
    const result = await mammoth.convertToHtml({ path: filePath });
    return {
      success: true,
      file_path: filePath,
      text: htmlToMarkdown(result.value),
    };
  } catch (error) {
    return { success: false, error: error instanceof Error ? error.message : String(error) };
  }
}

export const pdfReadTool: Tool = {
  name: "PdfRead",
  aliases: ["pdf_to_text"],
  description: "Extract text from PDF file.",
  inputSchema: {
    type: "object",
    properties: {
      file_path: { type: "string", description: "Path to PDF file" },
      page_range: {
        type: "array",
        description: "Optional [start, end] page range (0-indexed)",
        items: { type: "integer" },
      },
    },
    required: ["file_path"],
  },
  riskLevel: "low",
  alwaysLoad: false,
  shouldDefer: true,
  isReadOnly: true,
  requiredCapabilities: ["file_read"],
  searchHint: "pdf document read extract text",
  run: async (input, ctx) => {
    try {
      const resolved = safePath(requireString(input, "file_path"), ctx.workdir);
      const pageRange = Array.isArray(input.page_range)
        ? input.page_range.map(Number)
        : undefined;
      const result = await pdfToText(resolved, pageRange);
      if (!result.success) return `Error: ${String(result.error ?? "Unknown error")}`;
      return String(result.text ?? "");
    } catch (error) {
      return `Error: ${error instanceof Error ? error.message : String(error)}`;
    }
  },
};

export const docxReadTool: Tool = {
  name: "DocxRead",
  aliases: ["docx_to_markdown"],
  description: "Convert Word document to markdown.",
  inputSchema: {
    type: "object",
    properties: {
      file_path: { type: "string", description: "Path to Word document (.docx)" },
    },
    required: ["file_path"],
  },
  riskLevel: "low",
  alwaysLoad: false,
  shouldDefer: true,
  isReadOnly: true,
  requiredCapabilities: ["file_read"],
  searchHint: "docx word document read convert markdown",
  run: async (input, ctx) => {
    try {
      const resolved = safePath(requireString(input, "file_path"), ctx.workdir);
      const result = await docxToMarkdown(resolved);
      if (!result.success) return `Error: ${String(result.error ?? "Unknown error")}`;
      return String(result.text ?? "");
    } catch (error) {
      return `Error: ${error instanceof Error ? error.message : String(error)}`;
    }
  },
};
