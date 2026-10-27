import pc from "picocolors";
import { displayWidth, truncateToWidth } from "./markdown";

const RESET = "\x1b[0m";
const FOOTER_ROWS = 2;
const MIN_ROWS = 8;
const TICK_MS = 120;
const REDRAW_MS = 80;
const SYNC_BEGIN = "\x1b[?2026h";
const SYNC_END = "\x1b[?2026l";
const SAVE_CURSOR = "\x1b7";
const RESTORE_CURSOR = "\x1b8";
const FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];

export interface StatusSnapshot {
  model: string;
  cwd: string;
  branch?: string;
  inputTokens: number;
  outputTokens: number;
  contextTokens: number;
  contextLimit: number;
}

export interface StatusActivity {
  label: string;
  startedAt: number;
  frame: number;
}

export interface StatusOutput {
  write(chunk: string): unknown;
  isTTY?: boolean;
  rows?: number;
  columns?: number;
}

export interface StatusBarOptions {
  out?: StatusOutput;
  enabled?: boolean;
  color?: boolean;
}

export function formatTokens(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return "0";
  if (value < 1000) return String(Math.round(value));
  if (value < 999_950) {
    const thousands = value / 1000;
    return `${thousands >= 100 ? Math.round(thousands) : thousands.toFixed(1).replace(/\.0$/, "")}k`;
  }
  const millions = value / 1_000_000;
  return `${millions >= 100 ? Math.round(millions) : millions.toFixed(1).replace(/\.0$/, "")}M`;
}

function formatCount(value: number): string {
  return Math.max(0, Math.round(value)).toLocaleString("en-US");
}

function formatPercent(percent: number): string {
  return `${percent >= 10 ? Math.round(percent) : percent.toFixed(1).replace(/\.0$/, "")}%`;
}

function formatElapsed(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) {
    const minutes = Math.floor(seconds / 60);
    return `${minutes}m ${String(seconds % 60).padStart(2, "0")}s`;
  }
  const hours = Math.floor(seconds / 3600);
  return `${hours}h ${String(Math.floor((seconds % 3600) / 60)).padStart(2, "0")}m`;
}

function style(text: string, codes: string, color: boolean): string {
  return color && text ? `\x1b[${codes}m${text}${RESET}` : text;
}

function shortenHome(path: string): string {
  const home = process.env.HOME;
  if (home && (path === home || path.startsWith(`${home}/`))) return `~${path.slice(home.length)}`;
  return path;
}

function truncateMiddle(text: string, width: number): string {
  if (width <= 0) return "";
  if (displayWidth(text) <= width) return text;
  const characters = [...text];
  const ellipsis = "…";
  let head = "";
  let tail = "";
  let index = 0;
  while (index < characters.length) {
    const nextHead = head + characters[index]!;
    const nextTail = characters[characters.length - 1 - index]! + tail;
    if (displayWidth(nextHead) + displayWidth(ellipsis) + displayWidth(nextTail) > width) break;
    head = nextHead;
    tail = nextTail;
    index += 1;
  }
  if (!head && !tail) return truncateToWidth(text, width);
  return `${head}${ellipsis}${tail}`;
}

function activityText(activity: StatusActivity, now: number): string {
  const frame = FRAMES[activity.frame % FRAMES.length]!;
  const seconds = Math.max(0, Math.floor((now - activity.startedAt) / 1000));
  const elapsed = seconds >= 1 ? ` ${formatElapsed(seconds)}` : "";
  return `${frame} ${activity.label}${elapsed}`;
}

export interface FooterRenderOptions {
  color?: boolean;
  now?: number;
}

export function renderStatusFooter(
  snapshot: StatusSnapshot,
  activity: StatusActivity | null,
  width: number,
  options: FooterRenderOptions = {},
): [string, string] {
  const color = options.color ?? pc.isColorSupported;
  const now = options.now ?? Date.now();
  const columns = Math.max(10, Math.floor(width));

  const pathText = `${shortenHome(snapshot.cwd)}${snapshot.branch ? ` (${snapshot.branch})` : ""}`;
  const activityString = activity ? activityText(activity, now) : "";
  let pathLine: string;
  if (activityString) {
    const pathBudget = Math.max(6, columns - displayWidth(activityString) - 2);
    const visiblePath = truncateMiddle(pathText, pathBudget);
    const activityBudget = Math.max(0, columns - displayWidth(visiblePath) - 2);
    const visibleActivity = truncateToWidth(activityString, activityBudget);
    const gap = Math.max(2, columns - displayWidth(visiblePath) - displayWidth(visibleActivity));
    pathLine = `${style(visiblePath, "2", color)}${" ".repeat(gap)}${style(visibleActivity, "36", color)}`;
  } else {
    pathLine = style(truncateMiddle(pathText, columns), "2", color);
  }

  const limit = Math.max(0, snapshot.contextLimit);
  const tokens = Math.max(0, snapshot.contextTokens);
  const percent = limit > 0 ? Math.min(100, (tokens / limit) * 100) : null;
  const contextText =
    percent === null
      ? `context ${formatTokens(tokens)}/?`
      : `context ${formatTokens(tokens)}/${formatTokens(limit)} (${formatPercent(percent)})`;
  const contextCodes = percent !== null && percent >= 80 ? "31" : percent !== null && percent >= 50 ? "33" : "";
  const contextStyled = contextCodes ? style(contextText, contextCodes, color) : contextText;

  const usageText =
    snapshot.inputTokens > 0 || snapshot.outputTokens > 0
      ? `↑ ${formatCount(snapshot.inputTokens)}  ↓ ${formatCount(snapshot.outputTokens)}`
      : "";
  const separator = style("  ·  ", "2", color);

  const model = snapshot.model || "no-model";
  const modelWidth = Math.min(displayWidth(model), Math.max(1, columns - 2));
  const maxLeft = Math.max(0, columns - modelWidth - 2);

  const buildLeft = (includeUsage: boolean): string => {
    const segments: string[] = [];
    if (includeUsage && usageText) segments.push(style(usageText, "2", color));
    segments.push(contextStyled);
    return segments.join(separator);
  };

  let leftStyled = buildLeft(true);
  if (displayWidth(leftStyled) > maxLeft) leftStyled = buildLeft(false);
  if (displayWidth(leftStyled) > maxLeft) leftStyled = truncateToWidth(leftStyled, maxLeft);
  const leftWidth = displayWidth(leftStyled);

  const visibleModel = truncateToWidth(model, modelWidth);
  const modelStyled = style(visibleModel, "2", color);
  const gap = Math.max(2, columns - leftWidth - displayWidth(visibleModel));
  let statsLine = `${leftStyled}${" ".repeat(gap)}${modelStyled}`;
  if (displayWidth(statsLine) > columns) statsLine = truncateToWidth(statsLine, columns);

  return [pathLine, statsLine];
}

export class StatusBar {
  readonly enabled: boolean;
  private readonly out: StatusOutput;
  private readonly color: boolean;
  private state: StatusSnapshot | null = null;
  private activity: StatusActivity | null = null;
  private attached = false;
  private rows: number;
  private columns: number;
  private footerTop = 1;
  private redrawTimer: ReturnType<typeof setTimeout> | null = null;
  private tickTimer: ReturnType<typeof setInterval> | null = null;
  private exitHandler: (() => void) | null = null;

  constructor(options: StatusBarOptions = {}) {
    this.out = options.out ?? process.stdout;
    this.color = options.color ?? pc.isColorSupported;
    this.rows = this.out.rows ?? 24;
    this.columns = this.out.columns ?? 80;
    this.enabled =
      options.enabled ??
      (Boolean(this.out.isTTY) && process.env.BOURBON_PLAIN !== "1" && this.rows >= MIN_ROWS);
  }

  get isAttached(): boolean {
    return this.attached;
  }

  attach(snapshot: StatusSnapshot): boolean {
    if (!this.enabled || this.attached) return this.enabled;
    this.state = { ...snapshot };
    return this.open();
  }

  resume(): boolean {
    if (!this.enabled) return false;
    if (this.attached) return true;
    if (!this.state) return false;
    if ((this.out.rows ?? this.rows) < MIN_ROWS) return false;
    return this.open(true);
  }

  private open(scrollBefore = false): boolean {
    this.attached = true;
    this.rows = this.out.rows ?? this.rows;
    this.columns = this.out.columns ?? this.columns;
    this.footerTop = this.footerTopFor(this.rows);
    if (scrollBefore) {
      this.out.write(`\x1b[${this.rows};1H\n\n\n`);
    }
    this.out.write(`\x1b[1;${this.bottomMargin()}r`);
    this.draw();
    this.preparePrompt();
    this.exitHandler = () => this.emergencyReset();
    process.once("exit", this.exitHandler);
    return true;
  }

  promptRow(): number {
    return this.bottomMargin();
  }

  update(partial: Partial<StatusSnapshot>): void {
    if (!this.state) return;
    this.state = { ...this.state, ...partial };
    if (this.attached) this.schedule();
  }

  setActivity(label: string): void {
    if (!this.enabled || !this.attached) return;
    const changed = !this.activity || this.activity.label !== label;
    if (this.activity) {
      this.activity.label = label;
    } else {
      this.activity = { label, startedAt: Date.now(), frame: 0 };
    }
    if (!this.tickTimer) {
      this.tickTimer = setInterval(() => {
        if (!this.activity) return;
        this.activity.frame = (this.activity.frame + 1) % FRAMES.length;
        this.drawWithCursor();
      }, TICK_MS);
    }
    if (changed) this.schedule();
  }

  stopActivity(): void {
    if (!this.activity) return;
    this.activity = null;
    this.clearTick();
    if (this.attached) this.schedule();
  }

  preparePrompt(): void {
    if (!this.attached) return;
    this.out.write(`\x1b[${this.bottomMargin()};1H`);
  }

  redraw(): void {
    if (!this.attached) return;
    this.drawWithCursor();
  }

  resize(): void {
    if (!this.attached) return;
    const rows = this.out.rows ?? this.rows;
    const columns = this.out.columns ?? this.columns;
    if (rows === this.rows && columns === this.columns) return;
    this.clearRedraw();
    this.out.write(`${SAVE_CURSOR}\x1b[r`);
    if (this.footerTop >= 1 && this.footerTop <= rows) {
      this.out.write(`\x1b[${this.footerTop};1H\x1b[J`);
    }
    this.rows = rows;
    this.columns = columns;
    this.footerTop = this.footerTopFor(rows);
    this.out.write(`\x1b[1;${this.bottomMargin()}r`);
    this.draw();
    this.out.write(RESTORE_CURSOR);
  }

  dispose(): void {
    if (!this.attached) return;
    this.attached = false;
    this.clearRedraw();
    this.clearTick();
    this.activity = null;
    if (this.exitHandler) {
      process.off("exit", this.exitHandler);
      this.exitHandler = null;
    }
    const rows = this.out.rows ?? this.rows;
    const top = Math.min(this.footerTop, Math.max(1, rows));
    this.out.write(`\x1b[r\x1b[${top};1H\x1b[J\x1b[${top};1H`);
  }

  private footerTopFor(rows: number): number {
    return Math.max(1, rows - FOOTER_ROWS + 1);
  }

  private bottomMargin(): number {
    return Math.max(1, this.rows - FOOTER_ROWS);
  }

  private schedule(): void {
    if (!this.attached || this.redrawTimer) return;
    this.redrawTimer = setTimeout(() => {
      this.redrawTimer = null;
      if (this.attached) this.drawWithCursor();
    }, REDRAW_MS);
  }

  private clearRedraw(): void {
    if (!this.redrawTimer) return;
    clearTimeout(this.redrawTimer);
    this.redrawTimer = null;
  }

  private clearTick(): void {
    if (!this.tickTimer) return;
    clearInterval(this.tickTimer);
    this.tickTimer = null;
  }

  private drawWithCursor(): void {
    this.out.write(SAVE_CURSOR);
    this.draw();
    this.out.write(RESTORE_CURSOR);
  }

  private draw(): void {
    if (!this.state) return;
    const [pathLine, statsLine] = renderStatusFooter(this.state, this.activity, this.columns, {
      color: this.color,
    });
    this.out.write(
      `${SYNC_BEGIN}\x1b[${this.footerTop};1H${pathLine}\x1b[K` +
        `\x1b[${this.footerTop + 1};1H${statsLine}\x1b[K${SYNC_END}`,
    );
  }

  private emergencyReset(): void {
    if (!this.attached) return;
    this.attached = false;
    this.clearRedraw();
    this.clearTick();
    const rows = this.out.rows ?? this.rows;
    const top = Math.min(this.footerTop, Math.max(1, rows));
    this.out.write(`\x1b[r\x1b[${top};1H\x1b[J\x1b[${top};1H`);
  }
}
