import { describe, expect, test } from "bun:test";
import {
  displayWidth,
  MarkdownStream,
  renderMarkdown,
  renderMarkdownDetailed,
  stripAnsi,
} from "../src/markdown";

class FakeOutput {
  readonly chunks: string[] = [];
  constructor(
    readonly columns = 60,
    readonly rows = 24,
  ) {}

  write(chunk: string): boolean {
    this.chunks.push(chunk);
    return true;
  }

  get text(): string {
    return this.chunks.join("");
  }
}

describe("markdown display helpers", () => {
  test("strips ANSI and link escapes", () => {
    expect(stripAnsi("\x1b[1mbold\x1b[0m plain")).toBe("bold plain");
    expect(stripAnsi("\x1b]8;;https://example.com\x07link\x1b]8;;\x07")).toBe("link");
  });

  test("measures wide characters and ignores escape codes", () => {
    expect(displayWidth("abc")).toBe(3);
    expect(displayWidth("你好")).toBe(4);
    expect(displayWidth("\x1b[36mcode\x1b[0m")).toBe(4);
    expect(displayWidth("🥃")).toBe(2);
  });
});

describe("markdown inline rendering", () => {
  test("applies emphasis and inline code styles", () => {
    const rendered = renderMarkdown("**bold** *italic* ~~gone~~ `code`", {
      color: true,
      width: 80,
    });
    expect(rendered).toContain("\x1b[1mbold\x1b[0m");
    expect(rendered).toContain("\x1b[3mitalic\x1b[0m");
    expect(rendered).toContain("\x1b[9mgone\x1b[0m");
    expect(rendered).toContain("\x1b[36mcode\x1b[0m");
    expect(stripAnsi(rendered)).toBe("bold italic gone code");
  });

  test("nested and mixed emphasis runs", () => {
    expect(stripAnsi(renderMarkdown("*a **b** c*", { color: false }))).toBe("a b c");
    expect(stripAnsi(renderMarkdown("***both***", { color: false }))).toBe("both");
    expect(stripAnsi(renderMarkdown("snake_case_name", { color: false }))).toBe("snake_case_name");
  });

  test("does not parse markup inside inline code", () => {
    expect(stripAnsi(renderMarkdown("`a **b** [c](d)`", { color: false }))).toBe("a **b** [c](d)");
  });

  test("renders links with an OSC 8 hyperlink and visible url", () => {
    const rendered = renderMarkdown("[docs](https://example.com/a_(b))", { color: true, width: 80 });
    expect(rendered).toContain("\x1b]8;;https://example.com/a_(b)\x07docs\x1b]8;;\x07");
    expect(stripAnsi(rendered)).toBe("docs (https://example.com/a_(b))");
  });

  test("renders images and autolinks", () => {
    expect(stripAnsi(renderMarkdown("![alt](https://img/x.png)", { color: false }))).toBe(
      "alt (https://img/x.png)",
    );
    expect(stripAnsi(renderMarkdown("<https://example.com>", { color: false }))).toBe(
      "https://example.com",
    );
  });
});

describe("markdown blocks", () => {
  test("styles headings and separates them with a blank line", () => {
    const rendered = renderMarkdown("# Title\n\nbody", { color: true, width: 40 });
    expect(rendered.startsWith("\x1b[1;4mTitle\x1b[0m\n\nbody")).toBe(true);
  });

  test("renders code blocks with a bar and syntax colors", () => {
    const rendered = renderMarkdown("```ts\nconst answer: number = 42; // comment\n```", {
      color: true,
      width: 60,
    });
    const lines = rendered.split("\n");
    expect(stripAnsi(lines[0]!)).toStartWith("▏ const");
    expect(lines[0]).toContain("\x1b[35mconst\x1b[0m");
    expect(lines[0]).toContain("\x1b[33m42\x1b[0m");
    expect(lines[0]).toContain("\x1b[90m// comment\x1b[0m");
  });

  test("strips terminal control characters and expands tabs", () => {
    const injected = renderMarkdown("hello \x1b[31mred\x1b[0m\x07 world", { color: false });
    expect(injected).not.toContain("\x1b");
    expect(injected).toContain("hello [31mred[0m world");
    expect(renderMarkdown("```\n\tconst a = 1;\n```", { color: false })).toBe("▏     const a = 1;");
  });

  test("hard-wraps long code lines to the terminal width", () => {
    const code = "const value = " + JSON.stringify("x".repeat(120)) + ";";
    const rendered = renderMarkdown("```ts\n" + code + "\n```", { color: false, width: 40 });
    for (const line of rendered.split("\n")) {
      expect(displayWidth(line)).toBeLessThanOrEqual(40);
    }
    expect(stripAnsi(rendered).replace(/[▏\s]/g, "")).toBe(code.replace(/\s/g, ""));
  });

  test("renders nested lists with hanging indents and task checkboxes", () => {
    const rendered = renderMarkdown(
      "- first item that is long enough to wrap across another line for the indent\n  - nested\n  - [x] done\n  - [ ] pending\n1. ordered",
      { color: false, width: 36 },
    );
    const lines = rendered.split("\n");
    expect(lines[0]!.startsWith("• first")).toBe(true);
    expect(lines[1]!.startsWith("  ")).toBe(true);
    expect(rendered).toContain("  ◦ nested");
    expect(rendered).toContain("☑ done");
    expect(rendered).toContain("☐ pending");
    expect(rendered).toContain("1. ordered");
    for (const line of lines) expect(displayWidth(line)).toBeLessThanOrEqual(36);
  });

  test("renders tables with alignment and box borders", () => {
    const rendered = renderMarkdown(
      "| Name | Kind | Notes |\n|:-----|:----:|------:|\n| Bash | tool | runs |\n| Read | tool | reads files |",
      { color: false, width: 60 },
    );
    const lines = rendered.split("\n");
    expect(lines[0]).toStartWith("┏");
    expect(lines[1]).toContain("┃ Name ");
    expect(lines[2]).toStartWith("┡");
    expect(rendered).toContain("│ tool │");
    expect(rendered).toContain("│        runs │");
    expect(lines[lines.length - 1]).toStartWith("└");
  });

  test("keeps pipes inside inline code within one table cell", () => {
    const rendered = renderMarkdown(
      "| Expr | Note |\n|---|---|\n| `a|b` | pipe |\n| `c\\|d` | escaped |",
      { color: false, width: 60 },
    );
    expect(rendered).toContain("a|b");
    expect(rendered).toContain("c|d");
    expect(rendered).toContain("Note");
    expect(rendered).not.toContain("│ b ");
  });

  test("fits wide tables to the terminal width", () => {
    const rendered = renderMarkdown(
      "| alpha beta gamma | delta epsilon | zeta eta theta | iota kappa lambda |\n|---|---|---|---|\n| one two three | four five | six seven | eight nine |",
      { color: false, width: 40 },
    );
    for (const line of rendered.split("\n")) {
      expect(displayWidth(line)).toBeLessThanOrEqual(40);
    }
  });

  test("renders blockquotes with a bar on every line", () => {
    const rendered = renderMarkdown(`> ${"Less, but better. ".repeat(5).trim()}`, {
      color: false,
      width: 30,
    });
    const lines = rendered.split("\n");
    expect(lines.length).toBeGreaterThan(1);
    for (const line of lines) expect(line.startsWith("▎ ")).toBe(true);
    expect(stripAnsi(rendered).replace(/▎ /g, "").replace(/\n/g, " ")).toBe(
      "Less, but better. ".repeat(5).trim(),
    );
  });

  test("wraps paragraphs without exceeding the width", () => {
    const text = "word ".repeat(40).trim();
    const rendered = renderMarkdown(text, { color: false, width: 30 });
    for (const line of rendered.split("\n")) {
      expect(displayWidth(line)).toBeLessThanOrEqual(30);
    }
    expect(stripAnsi(rendered).split(/\s+/).join(" ")).toBe(text);
  });

  test("breaks long unspaced words and wide CJK text", () => {
    const rendered = renderMarkdown("你好世界".repeat(10), { color: false, width: 20 });
    const lines = rendered.split("\n");
    expect(lines.length).toBeGreaterThan(1);
    for (const line of lines) expect(displayWidth(line)).toBeLessThanOrEqual(20);
    expect(stripAnsi(rendered).split("\n").join("")).toBe("你好世界".repeat(10));
  });
});

describe("markdown stream live region", () => {
  test("keeps open paragraphs live and commits closed blocks", () => {
    const paragraph = renderMarkdownDetailed("hello", { color: false });
    expect(paragraph.liveStart).toBe(0);
    expect(paragraph.liveStart).toBeLessThan(paragraph.lines.length);

    const closedParagraph = renderMarkdownDetailed("hello\n\n", { color: false });
    expect(closedParagraph.liveStart).toBe(closedParagraph.lines.length);

    const closedFence = renderMarkdownDetailed("```ts\nconst a = 1;\n```", { color: false });
    expect(closedFence.liveStart).toBe(closedFence.lines.length);

    const openFence = renderMarkdownDetailed("text\n\n```ts\nconst a", { color: false });
    expect(openFence.liveStart).toBe(2);
    expect(openFence.liveStart).toBeLessThan(openFence.lines.length);
  });

  test("finishes immediately with the full rendered output", () => {
    const output = new FakeOutput(40);
    const stream = new MarkdownStream(output, { color: false, width: 40 });
    stream.push("one\n\ntwo");
    stream.finish();
    expect(stripAnsi(output.text).replace(/\r/g, "")).toBe("one\n\ntwo\n");
  });

  test("redraws the live tail as new deltas arrive", async () => {
    const output = new FakeOutput(40);
    const stream = new MarkdownStream(output, { color: false, width: 40 });
    stream.push("Hello **wor");
    await Bun.sleep(120);
    stream.push("ld**.\n\nNext");
    await Bun.sleep(120);
    stream.finish();
    expect(output.text).toContain("\x1b[1A");
    expect(output.text.endsWith("Hello world.\x1b[K\n\x1b[K\nNext\x1b[K\n")).toBe(true);
    expect(output.text).not.toContain("\x1b[J");
  });

  test("keeps a large live region bounded by the viewport", async () => {
    const output = new FakeOutput(60, 10);
    const stream = new MarkdownStream(output, { color: false, width: 60 });
    stream.push(Array.from({ length: 30 }, (_, index) => `paragraph ${index} text`).join("\n"));
    await Bun.sleep(120);
    stream.push("\nmore");
    await Bun.sleep(120);
    stream.finish();
    const moves = [...output.text.matchAll(/\x1b\[(\d+)A/g)].map((match) => Number(match[1]));
    expect(Math.max(...moves)).toBeLessThanOrEqual(7);
  });
});
