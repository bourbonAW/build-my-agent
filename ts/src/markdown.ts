import pc from "picocolors";

const RESET = "\x1b[0m";
const ANSI_PATTERN = /\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*(?:\x07|\x1b\\)/g;
const LIST_PATTERN = /^(\s*)([-+*]|\d{1,3}[.)])\s+(.*)$/;
const HR_PATTERN = /^ {0,3}([-*_])(?:\s*\1){2,}\s*$/;

export interface MarkdownOptions {
  width?: number;
  color?: boolean;
}

export interface RenderedMarkdown {
  lines: string[];
  /** First line of the still-open block; lines before it are stable. */
  liveStart: number;
}

interface InlineStyle {
  bold?: boolean;
  italic?: boolean;
  underline?: boolean;
  strike?: boolean;
  code?: boolean;
  dim?: boolean;
  link?: string;
}

interface Span {
  text: string;
  style: InlineStyle;
}

export function stripAnsi(text: string): string {
  return text.replace(ANSI_PATTERN, "");
}

function sanitizeText(text: string): string {
  return text
    .replace(/\t/g, "    ")
    .replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/g, "");
}

export function displayWidth(text: string): number {
  const plain = stripAnsi(text);
  if (typeof Bun !== "undefined" && typeof Bun.stringWidth === "function") {
    return Bun.stringWidth(plain);
  }
  let width = 0;
  for (const char of plain) {
    const code = char.codePointAt(0) ?? 0;
    if (code === 0x200d || (code >= 0x0300 && code <= 0x036f) || (code >= 0xfe00 && code <= 0xfe0f)) {
      continue;
    }
    width += isWideCodePoint(code) ? 2 : 1;
  }
  return width;
}

function isWideCodePoint(code: number): boolean {
  return (
    (code >= 0x1100 && code <= 0x115f) ||
    (code >= 0x2e80 && code <= 0x303e) ||
    (code >= 0x3041 && code <= 0x33ff) ||
    (code >= 0x3400 && code <= 0x4dbf) ||
    (code >= 0x4e00 && code <= 0x9fff) ||
    (code >= 0xa000 && code <= 0xa4cf) ||
    (code >= 0xac00 && code <= 0xd7a3) ||
    (code >= 0xf900 && code <= 0xfaff) ||
    (code >= 0xfe30 && code <= 0xfe4f) ||
    (code >= 0xff00 && code <= 0xff60) ||
    (code >= 0xffe0 && code <= 0xffe6) ||
    (code >= 0x1f300 && code <= 0x1faff) ||
    (code >= 0x20000 && code <= 0x3fffd)
  );
}

let segmenter: Intl.Segmenter | null | undefined;

function graphemes(text: string): string[] {
  if (segmenter === undefined) {
    segmenter =
      typeof Intl !== "undefined" && "Segmenter" in Intl
        ? new Intl.Segmenter(undefined, { granularity: "grapheme" })
        : null;
  }
  if (!segmenter) return [...text];
  return [...segmenter.segment(text)].map((entry) => entry.segment);
}

function paint(text: string, codes: string, color: boolean): string {
  return color ? `\x1b[${codes}m${text}${RESET}` : text;
}

function stylePrefix(style: InlineStyle, color: boolean): string {
  if (!color) return "";
  const codes: string[] = [];
  if (style.bold) codes.push("1");
  if (style.dim) codes.push("2");
  if (style.italic) codes.push("3");
  if (style.underline || style.link) codes.push("4");
  if (style.strike) codes.push("9");
  if (style.code) codes.push("36");
  return codes.length ? `\x1b[${codes.join(";")}m` : "";
}

function sameStyle(left: InlineStyle, right: InlineStyle): boolean {
  return (
    Boolean(left.bold) === Boolean(right.bold) &&
    Boolean(left.italic) === Boolean(right.italic) &&
    Boolean(left.underline) === Boolean(right.underline) &&
    Boolean(left.strike) === Boolean(right.strike) &&
    Boolean(left.code) === Boolean(right.code) &&
    Boolean(left.dim) === Boolean(right.dim) &&
    left.link === right.link
  );
}

function pushSpan(spans: Span[], text: string, style: InlineStyle): void {
  if (!text) return;
  const last = spans[spans.length - 1];
  if (last && sameStyle(last.style, style)) {
    last.text += text;
    return;
  }
  spans.push({ text, style: { ...style } });
}

function renderSpans(spans: Span[], color: boolean): string {
  let output = "";
  for (const span of spans) {
    const prefix = stylePrefix(span.style, color);
    const text = span.style.link
      ? `${color ? `\x1b]8;;${span.style.link}\x07` : ""}${span.text}${color ? "\x1b]8;;\x07" : ""}`
      : span.text;
    output += `${prefix}${text}${prefix ? RESET : ""}`;
  }
  return output;
}

function runLength(text: string, start: number, char: string): number {
  let index = start;
  while (index < text.length && text[index] === char) index += 1;
  return index - start;
}

function findClosingMarker(text: string, marker: string, from: number): number {
  let index = text.indexOf(marker, from);
  while (index !== -1) {
    const startsRun = index === 0 || text[index - 1] !== marker[0];
    if (
      startsRun &&
      runLength(text, index, marker[0]!) === marker.length &&
      index > from
    ) {
      const previous = text[index - 1];
      if (previous !== undefined && !/\s/.test(previous)) return index;
    }
    index = text.indexOf(marker, index + marker.length);
  }
  return -1;
}

interface ParsedLink {
  label: string;
  url: string;
  end: number;
}

function parseLink(text: string, start: number): ParsedLink | null {
  if (text[start] !== "[") return null;
  let depth = 0;
  let index = start;
  for (; index < text.length; index += 1) {
    const char = text[index];
    if (char === "\\") {
      index += 1;
      continue;
    }
    if (char === "[") depth += 1;
    else if (char === "]") {
      depth -= 1;
      if (depth === 0) break;
    }
  }
  if (depth !== 0 || index >= text.length) return null;
  const label = text.slice(start + 1, index);
  if (text[index + 1] !== "(") return null;
  let close = index + 2;
  let parens = 1;
  for (; close < text.length; close += 1) {
    const char = text[close];
    if (char === "\\") {
      close += 1;
      continue;
    }
    if (char === "(") parens += 1;
    else if (char === ")") {
      parens -= 1;
      if (parens === 0) break;
    }
  }
  if (parens !== 0) return null;
  const url = text.slice(index + 2, close).trim();
  if (!url) return null;
  return { label, url, end: close + 1 };
}

const EMPHASIS_RULES: Array<{ marker: string; apply: (style: InlineStyle) => InlineStyle }> = [
  { marker: "***", apply: (style) => ({ ...style, bold: true, italic: true }) },
  { marker: "___", apply: (style) => ({ ...style, bold: true, italic: true }) },
  { marker: "**", apply: (style) => ({ ...style, bold: true }) },
  { marker: "__", apply: (style) => ({ ...style, bold: true }) },
  { marker: "~~", apply: (style) => ({ ...style, strike: true }) },
  { marker: "*", apply: (style) => ({ ...style, italic: true }) },
  { marker: "_", apply: (style) => ({ ...style, italic: true }) },
];

function parseInline(text: string, base: InlineStyle = {}, depth = 0): Span[] {
  const spans: Span[] = [];
  let buffer = "";
  let index = 0;

  const flush = () => {
    if (!buffer) return;
    pushSpan(spans, buffer, base);
    buffer = "";
  };

  while (index < text.length) {
    const char = text[index]!;

    if (char === "\\" && index + 1 < text.length && /[\\`*_{}[\]()#+\-.!~>|]/.test(text[index + 1]!)) {
      buffer += text[index + 1];
      index += 2;
      continue;
    }

    if (char === "`") {
      const ticks = runLength(text, index, "`");
      const close = text.indexOf("`".repeat(ticks), index + ticks);
      if (close > index + ticks) {
        flush();
        pushSpan(spans, text.slice(index + ticks, close), { ...base, code: true });
        index = close + ticks;
        continue;
      }
    }

    if (char === "!" && text[index + 1] === "[") {
      const link = parseLink(text, index + 1);
      if (link) {
        flush();
        const label = parseInline(link.label, { ...base, link: link.url }, depth + 1);
        if (label.length) spans.push(...label);
        else pushSpan(spans, link.url, { ...base, link: link.url });
        if (link.label !== link.url) {
          pushSpan(spans, ` (${link.url})`, { ...base, dim: true, link: link.url });
        }
        index = link.end;
        continue;
      }
    }

    if (char === "[") {
      const link = parseLink(text, index);
      if (link) {
        flush();
        const label = parseInline(link.label, { ...base, link: link.url }, depth + 1);
        if (label.length) spans.push(...label);
        else pushSpan(spans, link.url, { ...base, link: link.url });
        if (link.label !== link.url) {
          pushSpan(spans, ` (${link.url})`, { ...base, dim: true, link: link.url });
        }
        index = link.end;
        continue;
      }
    }

    if (char === "<") {
      const match = /^<((?:https?:\/\/|mailto:)[^>\s]+)>/.exec(text.slice(index));
      if (match) {
        flush();
        const url = match[1]!;
        const label = url.startsWith("mailto:") ? url.slice("mailto:".length) : url;
        pushSpan(spans, label, { ...base, link: url });
        index += match[0].length;
        continue;
      }
    }

    if (depth < 6 && (char === "*" || char === "_" || char === "~")) {
      let matched = false;
      for (const rule of EMPHASIS_RULES) {
        const marker = rule.marker;
        if (!text.startsWith(marker, index)) continue;
        const after = text[index + marker.length];
        if (after === undefined || /\s/.test(after)) continue;
        if (marker[0] === "_" && index > 0) {
          const before = text[index - 1]!;
          if (/[\p{L}\p{N}]/u.test(before) && /[\p{L}\p{N}]/u.test(after)) continue;
        }
        const close = findClosingMarker(text, marker, index + marker.length);
        if (close === -1) continue;
        flush();
        spans.push(...parseInline(text.slice(index + marker.length, close), rule.apply(base), depth + 1));
        index = close + marker.length;
        matched = true;
        break;
      }
      if (matched) continue;
    }

    buffer += char;
    index += 1;
  }

  flush();
  return spans;
}

interface Word {
  spans: Span[];
  width: number;
}

function sumWidth(spans: Span[]): number {
  return spans.reduce((total, span) => total + displayWidth(span.text), 0);
}

function spansToWords(spans: Span[]): Word[] {
  const words: Word[] = [];
  let current: Span[] = [];
  const commit = () => {
    if (!current.length) return;
    words.push({ spans: current, width: sumWidth(current) });
    current = [];
  };
  for (const span of spans) {
    const parts = span.text.split(" ");
    for (let index = 0; index < parts.length; index += 1) {
      if (index > 0) commit();
      const part = parts[index]!;
      if (part) pushSpan(current, part, span.style);
    }
  }
  commit();
  return words;
}

function breakWord(spans: Span[], maxWidth: number): Span[][] {
  if (maxWidth <= 0) return [spans];
  const chunks: Span[][] = [];
  let current: Span[] = [];
  let width = 0;
  for (const span of spans) {
    for (const grapheme of graphemes(span.text)) {
      const size = displayWidth(grapheme);
      if (width + size > maxWidth && current.length) {
        chunks.push(current);
        current = [];
        width = 0;
      }
      pushSpan(current, grapheme, span.style);
      width += size;
    }
  }
  if (current.length) chunks.push(current);
  return chunks.length ? chunks : [spans];
}

function wrapWords(
  spans: Span[],
  firstPrefix: string,
  continuationPrefix: string,
  width: number,
  color: boolean,
): string[] {
  const words = spansToWords(spans);
  const lines: string[] = [];
  let prefix = firstPrefix;
  let lineSpans: Span[] = [];
  let lineWidth = displayWidth(prefix);
  const chunkWidth = Math.max(
    1,
    width - Math.max(displayWidth(firstPrefix), displayWidth(continuationPrefix)),
  );

  const emit = () => {
    const body = renderSpans(lineSpans, color);
    lines.push(body ? `${prefix}${body}` : prefix.trimEnd());
    prefix = continuationPrefix;
    lineSpans = [];
    lineWidth = displayWidth(prefix);
  };

  for (const word of words) {
    const chunks = word.width > chunkWidth ? breakWord(word.spans, chunkWidth) : [word.spans];
    for (const chunk of chunks) {
      const chunkSize = sumWidth(chunk);
      if (lineSpans.length && lineWidth + 1 + chunkSize > width) emit();
      if (lineSpans.length) {
        pushSpan(lineSpans, " ", {});
        lineWidth += 1;
      }
      for (const span of chunk) pushSpan(lineSpans, span.text, span.style);
      lineWidth += chunkSize;
    }
  }

  if (lineSpans.length || lines.length === 0) emit();
  return lines;
}

function hardWrapPlain(text: string, width: number): string[] {
  if (!text) return [""];
  const lines: string[] = [];
  let current = "";
  let currentWidth = 0;
  for (const grapheme of graphemes(text)) {
    const size = displayWidth(grapheme);
    if (current && currentWidth + size > width) {
      lines.push(current);
      current = "";
      currentWidth = 0;
    }
    current += grapheme;
    currentWidth += size;
  }
  if (current) lines.push(current);
  return lines.length ? lines : [""];
}

interface SyntaxSpec {
  keywords: Set<string>;
  literals: Set<string>;
  strings: string[];
  lineComment?: string;
}

function keywordSet(words: string): Set<string> {
  return new Set(words.split(/\s+/).filter(Boolean));
}

const TS_KEYWORDS = keywordSet(
  "abstract as async await break case catch class const continue declare default delete do else enum export extends finally for from function get if implements import in instanceof interface keyof let namespace new of private protected public readonly return satisfies set static super switch this throw try type typeof undefined unique unknown var void while with yield",
);
const PY_KEYWORDS = keywordSet(
  "and as assert async await break class continue def del elif else except finally for from global if import in is lambda nonlocal not or pass raise return try while with yield",
);
const SH_KEYWORDS = keywordSet(
  "case do done elif else esac fi for function if in local return select then time until while export readonly declare unset source",
);
const SQL_KEYWORDS = keywordSet(
  "select from where join left right inner outer on group by order having limit offset insert into values update set delete create table alter drop index view as and or not null distinct union all exists case when then else end",
);
const GO_KEYWORDS = keywordSet(
  "break case chan const continue default defer else fallthrough for func go goto if import interface map package range return select struct switch type var",
);
const RUST_KEYWORDS = keywordSet(
  "as async await break const continue crate dyn else enum extern false fn for if impl in let loop match mod move mut pub ref return self Self static struct super trait true type unsafe use where while",
);
const JAVA_KEYWORDS = keywordSet(
  "abstract assert boolean break byte case catch char class const continue default do double else enum extends final finally float for if implements import instanceof int interface long native new package private protected public return short static strictfp super switch synchronized this throw throws transient try void volatile while",
);

const SYNTAX: Record<string, SyntaxSpec> = {
  ts: { keywords: TS_KEYWORDS, literals: keywordSet("true false null undefined NaN Infinity"), strings: ['"', "'", "`"], lineComment: "//" },
  js: { keywords: TS_KEYWORDS, literals: keywordSet("true false null undefined NaN Infinity"), strings: ['"', "'", "`"], lineComment: "//" },
  json: { keywords: keywordSet(""), literals: keywordSet("true false null"), strings: ['"'], lineComment: undefined },
  py: { keywords: PY_KEYWORDS, literals: keywordSet("True False None self cls"), strings: ['"', "'"], lineComment: "#" },
  sh: { keywords: SH_KEYWORDS, literals: keywordSet("true false"), strings: ['"', "'"], lineComment: "#" },
  go: { keywords: GO_KEYWORDS, literals: keywordSet("true false nil iota"), strings: ['"', "'", "`"], lineComment: "//" },
  rust: { keywords: RUST_KEYWORDS, literals: keywordSet("true false None Some Ok Err"), strings: ['"'], lineComment: "//" },
  java: { keywords: JAVA_KEYWORDS, literals: keywordSet("true false null"), strings: ['"', "'"], lineComment: "//" },
  sql: { keywords: SQL_KEYWORDS, literals: keywordSet("true false null"), strings: ["'"], lineComment: "--" },
  yaml: { keywords: keywordSet(""), literals: keywordSet("true false null yes no on off"), strings: ['"', "'"], lineComment: "#" },
  toml: { keywords: keywordSet(""), literals: keywordSet("true false"), strings: ['"', "'"], lineComment: "#" },
};

const SYNTAX_ALIASES: Record<string, string> = {
  typescript: "ts",
  tsx: "ts",
  javascript: "js",
  jsx: "js",
  mjs: "js",
  cjs: "js",
  python: "py",
  bash: "sh",
  shell: "sh",
  zsh: "sh",
  console: "sh",
  golang: "go",
  rs: "rust",
  yml: "yaml",
  jsonc: "json",
  json5: "json",
};

function highlightCode(line: string, language: string | undefined, color: boolean): string {
  if (!color || !language) return line;
  const key = SYNTAX_ALIASES[language] ?? language;
  const spec = SYNTAX[key];
  if (!spec) return line;

  let output = "";
  let index = 0;
  while (index < line.length) {
    if (spec.lineComment && line.startsWith(spec.lineComment, index)) {
      output += paint(line.slice(index), "90", color);
      break;
    }
    const char = line[index]!;
    if (spec.strings.includes(char)) {
      let close = index + 1;
      while (close < line.length) {
        if (line[close] === "\\") {
          close += 2;
          continue;
        }
        if (line[close] === char) {
          close += 1;
          break;
        }
        close += 1;
      }
      output += paint(line.slice(index, close), "32", color);
      index = close;
      continue;
    }
    if (/[0-9]/.test(char) && (index === 0 || !/[\w$]/.test(line[index - 1]!))) {
      let end = index + 1;
      while (end < line.length && /[\w.]/.test(line[end]!)) end += 1;
      output += paint(line.slice(index, end), "33", color);
      index = end;
      continue;
    }
    if (/[A-Za-z_$]/.test(char)) {
      let end = index + 1;
      while (end < line.length && /[\w$]/.test(line[end]!)) end += 1;
      const word = line.slice(index, end);
      if (spec.keywords.has(word)) output += paint(word, "35", color);
      else if (spec.literals.has(word)) output += paint(word, "36", color);
      else output += word;
      index = end;
      continue;
    }
    output += char;
    index += 1;
  }
  return output;
}

function renderCodeBlock(
  codeLines: string[],
  language: string,
  width: number,
  color: boolean,
): string[] {
  const bar = paint("▏", "2", color);
  const contentWidth = Math.max(4, width - 2);
  const output: string[] = [];
  for (const line of codeLines) {
    const chunks = hardWrapPlain(line, contentWidth);
    for (const chunk of chunks) {
      output.push(chunk ? `${bar} ${highlightCode(chunk, language, color)}` : bar);
    }
  }
  if (!output.length) output.push(bar);
  return output;
}

function splitTableRow(line: string): string[] {
  const parts: string[] = [];
  let current = "";
  let inCode = false;
  let escaped = false;
  for (const char of line) {
    if (escaped) {
      current += char;
      escaped = false;
      continue;
    }
    if (char === "\\") {
      current += char;
      escaped = true;
      continue;
    }
    if (char === "`") {
      inCode = !inCode;
      current += char;
      continue;
    }
    if (char === "|" && !inCode) {
      parts.push(current);
      current = "";
      continue;
    }
    current += char;
  }
  parts.push(current);
  if (parts.length && parts[0]!.trim() === "") parts.shift();
  if (parts.length && parts[parts.length - 1]!.trim() === "") parts.pop();
  return parts.map((part) => part.replace(/\\\|/g, "|").trim());
}

function isTableSeparator(line: string): boolean {
  if (!line.includes("|")) return false;
  const cells = splitTableRow(line);
  return cells.length > 0 && cells.every((cell) => /^:?-{3,}:?$/.test(cell.replace(/\s+/g, "")));
}

type Alignment = "left" | "center" | "right";

function alignmentFor(cell: string): Alignment {
  const trimmed = cell.trim();
  const left = trimmed.startsWith(":");
  const right = trimmed.endsWith(":");
  if (left && right) return "center";
  if (right) return "right";
  return "left";
}

function fitColumnWidths(widths: number[], totalWidth: number): void {
  const minimum = 3;
  const overhead = widths.length * 3 + 1;
  const available = Math.max(widths.length * minimum, totalWidth - overhead);
  const total = () => widths.reduce((sum, width) => sum + width, 0);
  while (total() > available) {
    let widest = 0;
    for (let index = 1; index < widths.length; index += 1) {
      if (widths[index]! > widths[widest]!) widest = index;
    }
    if (widths[widest]! <= minimum) break;
    widths[widest] = widths[widest]! - 1;
  }
}

function padVisible(text: string, width: number, alignment: Alignment): string {
  const padding = Math.max(0, width - displayWidth(text));
  if (alignment === "right") return " ".repeat(padding) + text;
  if (alignment === "center") {
    const left = Math.floor(padding / 2);
    return " ".repeat(left) + text + " ".repeat(padding - left);
  }
  return text + " ".repeat(padding);
}

function renderTable(
  header: string[],
  rows: string[][],
  alignments: Alignment[],
  width: number,
  color: boolean,
): string[] {
  const columns = Math.max(header.length, alignments.length, ...rows.map((row) => row.length));
  if (columns === 0) return [];

  const headerSpans = Array.from({ length: columns }, (_, column) =>
    parseInline(header[column] ?? "", { bold: true }),
  );
  const bodySpans = rows.map((row) =>
    Array.from({ length: columns }, (_, column) => parseInline(row[column] ?? "")),
  );

  const widths = Array.from({ length: columns }, (_, column) => {
    const cells = [headerSpans[column]!, ...bodySpans.map((row) => row[column]!)];
    return Math.max(3, ...cells.map((cell) => displayWidth(renderSpans(cell, false))));
  });
  fitColumnWidths(widths, width);

  const columnsWithAlignment = Array.from(
    { length: columns },
    (_, column) => alignments[column] ?? "left",
  );

  const layout = (cells: Span[][]): string[][] =>
    cells.map((cell, column) => wrapWords(cell, "", "", widths[column]!, color));

  const headerLines = layout(headerSpans);
  const bodyLines = bodySpans.map(layout);

  const border = (left: string, middle: string, right: string, fill: string): string =>
    paint(left + widths.map((columnWidth) => fill.repeat(columnWidth + 2)).join(middle) + right, "2", color);

  const rowLines = (cells: string[][], vertical: string): string[] => {
    const height = Math.max(1, ...cells.map((cell) => cell.length));
    const output: string[] = [];
    for (let lineIndex = 0; lineIndex < height; lineIndex += 1) {
      const parts = cells.map((cell, column) =>
        ` ${padVisible(cell[lineIndex] ?? "", widths[column]!, columnsWithAlignment[column]!)} `,
      );
      output.push(`${vertical}${parts.join(vertical)}${vertical}`);
    }
    return output;
  };

  const heavyVertical = paint("┃", "2", color);
  const lightVertical = paint("│", "2", color);
  const output: string[] = [border("┏", "┳", "┓", "━")];
  output.push(...rowLines(headerLines, heavyVertical));
  if (bodyLines.length) {
    output.push(border("┡", "╇", "┩", "━"));
    for (const row of bodyLines) {
      output.push(...rowLines(row, lightVertical));
    }
  }
  output.push(border("└", "┴", "┘", "─"));
  return output;
}

export function truncateToWidth(text: string, width: number): string {
  if (width <= 0) return "";
  if (displayWidth(text) <= width) return text;
  let output = "";
  let visible = 0;
  let index = 0;
  while (index < text.length && visible < width) {
    const ansi = /^\x1b\[[0-9;?]*[A-Za-z]|^\x1b\][^\x07]*(?:\x07|\x1b\\)/.exec(text.slice(index));
    if (ansi) {
      output += ansi[0];
      index += ansi[0].length;
      continue;
    }
    const grapheme = graphemes(text.slice(index))[0] ?? text[index]!;
    const size = displayWidth(grapheme);
    if (visible + size > width) break;
    output += grapheme;
    visible += size;
    index += grapheme.length;
  }
  const closeLink = text.includes("\x1b]8;") ? "\x1b]8;;\x07" : "";
  const closeStyle = text.includes("\x1b[") ? RESET : "";
  return `${output}${closeLink}${closeStyle}`;
}

function isClosingFence(line: string, char: string, length: number): boolean {
  const trimmed = line.trim();
  if (trimmed.length < length) return false;
  for (const candidate of trimmed) {
    if (candidate !== char) return false;
  }
  return true;
}

function isBlockStart(line: string, next: string | undefined): boolean {
  if (/^\s*(`{3,}|~{3,})/.test(line)) return true;
  if (/^#{1,6}\s+/.test(line)) return true;
  if (/^ {0,3}>/.test(line)) return true;
  if (HR_PATTERN.test(line)) return true;
  if (LIST_PATTERN.test(line)) return true;
  if (next !== undefined && line.includes("|") && isTableSeparator(next)) return true;
  return false;
}

export function renderMarkdownDetailed(
  markdown: string,
  options: MarkdownOptions = {},
): RenderedMarkdown {
  const width = Math.max(20, Math.floor(options.width ?? 80));
  const color = options.color ?? pc.isColorSupported;
  const sourceLines = markdown
    .replace(/\r\n?/g, "\n")
    .split("\n")
    .map((line) => sanitizeText(line));
  const endsWithBlank =
    sourceLines.length >= 2 &&
    sourceLines[sourceLines.length - 1] === "" &&
    sourceLines[sourceLines.length - 2]!.trim() === "";

  const lines: string[] = [];
  let index = 0;
  let lastBlockStart = 0;
  let finalBlockClosed = false;

  const blank = () => {
    if (lines.length && lines[lines.length - 1] !== "") lines.push("");
  };

  while (index < sourceLines.length) {
    const line = sourceLines[index]!;
    if (line.trim() === "") {
      index += 1;
      continue;
    }

    const fence = /^\s*(`{3,}|~{3,})(.*)$/.exec(line);
    if (fence) {
      blank();
      const blockStart = lines.length;
      const fenceToken = fence[1]!;
      const fenceChar = fenceToken[0]!;
      const fenceLength = fenceToken.length;
      const language = (fence[2]!.trim().split(/\s+/)[0] ?? "").replace(/^\{|\}$/g, "").toLowerCase();
      const codeLines: string[] = [];
      let closed = false;
      index += 1;
      while (index < sourceLines.length) {
        const current = sourceLines[index]!;
        if (isClosingFence(current, fenceChar, fenceLength)) {
          closed = true;
          index += 1;
          break;
        }
        codeLines.push(current);
        index += 1;
      }
      lines.push(...renderCodeBlock(codeLines, language, width, color));
      lastBlockStart = blockStart;
      finalBlockClosed = closed;
      continue;
    }

    const heading = /^(#{1,6})\s+(.*)$/.exec(line);
    if (heading) {
      blank();
      const blockStart = lines.length;
      const level = heading[1]!.length;
      const content = heading[2]!.replace(/\s+#+\s*$/, "").trim();
      const style: InlineStyle =
        level === 1
          ? { bold: true, underline: true }
          : { bold: true, dim: level >= 4 };
      lines.push(...wrapWords(parseInline(content, style), "", "", width, color));
      lines.push("");
      index += 1;
      lastBlockStart = blockStart;
      finalBlockClosed = false;
      continue;
    }

    if (HR_PATTERN.test(line)) {
      blank();
      const blockStart = lines.length;
      lines.push(paint("─".repeat(width), "2", color));
      index += 1;
      lastBlockStart = blockStart;
      finalBlockClosed = false;
      continue;
    }

    if (/^ {0,3}>/.test(line)) {
      blank();
      const blockStart = lines.length;
      const quoted: string[] = [];
      while (index < sourceLines.length) {
        const current = sourceLines[index]!;
        const match = /^ {0,3}>\s?(.*)$/.exec(current);
        if (!match) break;
        quoted.push(match[1]!);
        index += 1;
      }
      const inner = renderMarkdownDetailed(quoted.join("\n"), {
        width: width - 2,
        color,
      });
      const bar = paint("▎", "2", color);
      for (const innerLine of inner.lines) {
        lines.push(innerLine ? `${bar} ${innerLine}` : bar);
      }
      if (!inner.lines.length) lines.push(bar);
      lastBlockStart = blockStart;
      finalBlockClosed = false;
      continue;
    }

    if (LIST_PATTERN.test(line)) {
      blank();
      const blockStart = lines.length;
      while (index < sourceLines.length) {
        const current = sourceLines[index]!;
        const match = LIST_PATTERN.exec(current);
        if (!match) break;
        const indentation = match[1]!;
        const marker = match[2]!;
        let content = match[3]!;
        index += 1;
        const continuation: string[] = [];
        while (index < sourceLines.length) {
          const next = sourceLines[index]!;
          if (next.trim() === "" || LIST_PATTERN.test(next) || isBlockStart(next, sourceLines[index + 1])) {
            break;
          }
          if (/^\s+/.test(next)) {
            continuation.push(next.trim());
            index += 1;
            continue;
          }
          break;
        }

        const level = Math.min(6, Math.floor(indentation.length / 2));
        const indent = "  ".repeat(level);
        let prefix: string;
        const task = /^\[([ xX])\]\s+(.*)$/.exec(content);
        if (task) {
          const checked = task[1]!.toLowerCase() === "x";
          prefix = `${indent}${paint(checked ? "☑" : "☐", "36", color)} `;
          content = task[2]!;
        } else if (/^\d/.test(marker)) {
          prefix = `${indent}${paint(marker, "2", color)} `;
        } else {
          const bullet = level === 0 ? "•" : level === 1 ? "◦" : "▪";
          prefix = `${indent}${paint(bullet, "36", color)} `;
        }
        const continuationPrefix = " ".repeat(displayWidth(prefix));
        const text = [content, ...continuation].join(" ");
        lines.push(
          ...wrapWords(parseInline(text), prefix, continuationPrefix, width, color),
        );

        let lookahead = index;
        while (lookahead < sourceLines.length && sourceLines[lookahead]!.trim() === "") {
          lookahead += 1;
        }
        if (
          lookahead > index &&
          lookahead < sourceLines.length &&
          LIST_PATTERN.test(sourceLines[lookahead]!)
        ) {
          index = lookahead;
        }
      }
      lastBlockStart = blockStart;
      finalBlockClosed = false;
      continue;
    }

    if (line.includes("|") && index + 1 < sourceLines.length && isTableSeparator(sourceLines[index + 1]!)) {
      blank();
      const blockStart = lines.length;
      const header = splitTableRow(line);
      const separator = splitTableRow(sourceLines[index + 1]!);
      const alignments = separator.map(alignmentFor);
      const rows: string[][] = [];
      index += 2;
      while (index < sourceLines.length) {
        const current = sourceLines[index]!;
        if (current.trim() === "" || !current.includes("|")) break;
        rows.push(splitTableRow(current));
        index += 1;
      }
      lines.push(...renderTable(header, rows, alignments, width, color));
      lastBlockStart = blockStart;
      finalBlockClosed = false;
      continue;
    }

    blank();
    const blockStart = lines.length;
    const paragraph: string[] = [];
    while (index < sourceLines.length) {
      const current = sourceLines[index]!;
      if (current.trim() === "") break;
      if (paragraph.length > 0 && isBlockStart(current, sourceLines[index + 1])) break;
      paragraph.push(current.trim());
      index += 1;
    }
    const text = paragraph.join(" ").replace(/\s+/g, " ").trim();
    if (text) lines.push(...wrapWords(parseInline(text), "", "", width, color));
    lastBlockStart = blockStart;
    finalBlockClosed = false;
  }

  while (lines.length && lines[lines.length - 1] === "") lines.pop();
  const liveStart =
    endsWithBlank || finalBlockClosed ? lines.length : Math.min(lastBlockStart, lines.length);

  return {
    lines: lines.map((line) => (displayWidth(line) <= width ? line : truncateToWidth(line, width))),
    liveStart,
  };
}

export function renderMarkdown(markdown: string, options: MarkdownOptions = {}): string {
  return renderMarkdownDetailed(markdown, options).lines.join("\n");
}

export interface MarkdownOutput {
  write(chunk: string): unknown;
  columns?: number;
  rows?: number;
}

export interface MarkdownStreamOptions {
  color?: boolean;
  width?: number | (() => number);
}

const FRAME_INTERVAL_MS = 33;

// Finished blocks are committed once and never redrawn; only the unfinished tail moves,
// which keeps streaming flicker-free and cursor-up bounded by the viewport.
export class MarkdownStream {
  private buffer = "";
  private renderedLines: string[] = [];
  private committed = 0;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private finished = false;
  private readonly color: boolean;
  private readonly out: MarkdownOutput;
  private readonly widthOption: number | (() => number) | undefined;

  constructor(out: MarkdownOutput = process.stdout, options: MarkdownStreamOptions = {}) {
    this.out = out;
    this.color = options.color ?? pc.isColorSupported;
    this.widthOption = options.width;
  }

  get text(): string {
    return this.buffer;
  }

  push(text: string): void {
    if (this.finished || !text) return;
    this.buffer += text;
    if (this.timer === null) {
      this.timer = setTimeout(() => {
        this.timer = null;
        this.flush();
      }, FRAME_INTERVAL_MS);
    }
  }

  finish(): void {
    if (this.finished) return;
    this.finished = true;
    if (this.timer !== null) {
      clearTimeout(this.timer);
      this.timer = null;
    }
    this.flush();
  }

  private maxLiveLines(): number {
    return Math.max(6, (this.out.rows ?? 24) - 3);
  }

  private flush(): void {
    const width = Math.max(
      20,
      Math.floor(
        (typeof this.widthOption === "function" ? this.widthOption() : this.widthOption) ??
          this.out.columns ??
          80,
      ),
    );
    const rendered = renderMarkdownDetailed(this.buffer, { width, color: this.color });
    const next = rendered.lines;
    const maxLive = this.maxLiveLines();
    const liveTarget =
      next.length - rendered.liveStart > maxLive ? next.length - maxLive : rendered.liveStart;

    if (this.committed > next.length) this.committed = next.length;

    const oldLength = this.renderedLines.length;
    let start = Math.min(this.committed, oldLength);
    while (
      start < oldLength &&
      start < next.length &&
      this.renderedLines[start] === next[start]
    ) {
      start += 1;
    }

    if (start === oldLength && oldLength === next.length) {
      this.committed = Math.max(this.committed, Math.min(liveTarget, next.length));
      return;
    }

    let output = "";
    const up = oldLength - start;
    if (up > 0) output += `\x1b[${up}A`;
    output += "\r";
    for (let index = start; index < next.length; index += 1) {
      output += `${next[index] ?? ""}\x1b[K\n`;
    }

    const stale = Math.max(0, oldLength - next.length);
    if (stale > 0) {
      for (let index = 0; index < stale; index += 1) {
        output += index === stale - 1 ? "\x1b[2K" : "\x1b[2K\n";
      }
      if (stale > 1) output += `\x1b[${stale - 1}A`;
    }
    this.out.write(output);

    this.renderedLines = next;
    this.committed = Math.max(this.committed, Math.min(liveTarget, next.length));
  }
}
