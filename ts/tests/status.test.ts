import { describe, expect, test } from "bun:test";
import { displayWidth, stripAnsi, truncateToWidth } from "../src/markdown";
import {
  formatTokens,
  renderStatusFooter,
  StatusBar,
  type StatusSnapshot,
} from "../src/status";

class FakeOutput {
  readonly chunks: string[] = [];
  constructor(
    public rows = 12,
    public columns = 80,
    public isTTY = true,
  ) {}

  write(chunk: string): boolean {
    this.chunks.push(chunk);
    return true;
  }

  get text(): string {
    return this.chunks.join("");
  }
}

const snapshot: StatusSnapshot = {
  model: "deepseek-v4.1-flash-1017",
  cwd: "/Users/whf/github_project/build-my-agent",
  branch: "feat/ts-rewrite",
  inputTokens: 3894,
  outputTokens: 159,
  contextTokens: 3900,
  contextLimit: 100000,
};

describe("status formatting", () => {
  test("formats token counts compactly", () => {
    expect(formatTokens(0)).toBe("0");
    expect(formatTokens(999)).toBe("999");
    expect(formatTokens(1000)).toBe("1k");
    expect(formatTokens(3900)).toBe("3.9k");
    expect(formatTokens(100000)).toBe("100k");
    expect(formatTokens(999999)).toBe("1M");
    expect(formatTokens(1500000)).toBe("1.5M");
  });

  test("renders path, usage, context, and model on two lines", () => {
    const [pathLine, statsLine] = renderStatusFooter(snapshot, null, 100, { color: false });
    expect(pathLine).toContain("github_project/build-my-agent (feat/ts-rewrite)");
    expect(statsLine).toContain("↑ 3,894");
    expect(statsLine).toContain("↓ 159");
    expect(statsLine).toContain("context 3.9k/100k (3.9%)");
    expect(statsLine.endsWith("deepseek-v4.1-flash-1017")).toBe(true);
    expect(displayWidth(pathLine)).toBeLessThanOrEqual(100);
    expect(displayWidth(statsLine)).toBe(100);
  });

  test("renders an activity indicator with elapsed time", () => {
    const now = Date.now();
    const [pathLine] = renderStatusFooter(
      snapshot,
      { label: "Running Bash", startedAt: now - 65_000, frame: 3 },
      120,
      { color: false, now },
    );
    expect(pathLine).toContain("Running Bash 1m 05s");
    expect(pathLine).toContain("⠸");
    expect(pathLine).toContain("github_project/build-my-agent");
  });

  test("colors context usage as it approaches the limit", () => {
    const normal = renderStatusFooter(snapshot, null, 120, { color: true })[1];
    expect(normal).not.toContain("\x1b[33m");
    expect(normal).not.toContain("\x1b[31m");

    const warning = renderStatusFooter(
      { ...snapshot, contextTokens: 60_000 },
      null,
      120,
      { color: true },
    )[1];
    expect(warning).toContain("\x1b[33mcontext");

    const danger = renderStatusFooter(
      { ...snapshot, contextTokens: 90_000 },
      null,
      120,
      { color: true },
    )[1];
    expect(danger).toContain("\x1b[31mcontext");
  });

  test("drops lower-priority segments before clipping at narrow widths", () => {
    const [pathLine, statsLine] = renderStatusFooter(snapshot, null, 50, { color: false });
    expect(statsLine).toContain("context 3.9k/100k (3.9%)");
    expect(statsLine).not.toContain("↑");
    expect(statsLine.endsWith("deepseek-v4.1-flash-1017")).toBe(true);
    expect(displayWidth(statsLine)).toBeLessThanOrEqual(50);
    expect(displayWidth(pathLine)).toBeLessThanOrEqual(50);
  });

  test("keeps the model readable on very narrow terminals", () => {
    const [pathLine, statsLine] = renderStatusFooter(snapshot, null, 24, { color: false });
    expect(displayWidth(pathLine)).toBeLessThanOrEqual(24);
    expect(displayWidth(statsLine)).toBeLessThanOrEqual(24);
    expect(statsLine).toContain("deepseek");
  });

  test("truncates ANSI-styled text without breaking escape sequences", () => {
    const cut = truncateToWidth("\x1b[1mhello world\x1b[0m", 5);
    expect(stripAnsi(cut)).toBe("hello");
    expect(cut.startsWith("\x1b[1m")).toBe(true);
    expect(cut.endsWith("\x1b[0m")).toBe(true);
  });
});

describe("status bar terminal control", () => {
  test("reserves the bottom rows and clears them on dispose", () => {
    const out = new FakeOutput(12, 40);
    const bar = new StatusBar({ out, enabled: true, color: false });
    expect(bar.attach(snapshot)).toBe(true);
    expect(out.text).toContain("\x1b[1;10r");
    expect(out.text).toContain("\x1b[11;1H");
    expect(out.text).toContain("\x1b[12;1H");
    expect(out.text).toContain("\x1b[K");
    expect(out.text).toContain("\x1b[10;1H");
    expect(out.text).toContain("deepseek-v4.1-flash-1017");

    out.chunks.length = 0;
    bar.dispose();
    expect(out.text).toContain("\x1b[r");
    expect(out.text).toContain("\x1b[11;1H\x1b[J");
  });

  test("redraws usage updates into the footer", async () => {
    const out = new FakeOutput(12, 90);
    const bar = new StatusBar({ out, enabled: true, color: false });
    bar.attach(snapshot);
    out.chunks.length = 0;
    bar.update({ contextTokens: 42000, outputTokens: 900 });
    await Bun.sleep(120);
    expect(out.text).toContain("42k/100k");
    expect(out.text).toContain("↓ 900");
    bar.dispose();
  });

  test("animates activity and stops cleanly", async () => {
    const out = new FakeOutput(12, 80);
    const bar = new StatusBar({ out, enabled: true, color: false });
    bar.attach(snapshot);
    out.chunks.length = 0;
    bar.setActivity("Running Read");
    await Bun.sleep(150);
    expect(out.text).toContain("Running Read");
    bar.stopActivity();
    out.chunks.length = 0;
    await Bun.sleep(120);
    expect(out.text).not.toContain("Running Read");
    bar.dispose();
  });

  test("reopens after a resize suspension and scrolls content clear of the footer", () => {
    const out = new FakeOutput(12, 60);
    const bar = new StatusBar({ out, enabled: true, color: false });
    bar.attach(snapshot);
    bar.dispose();
    expect(bar.isAttached).toBe(false);

    out.chunks.length = 0;
    bar.update({ contextTokens: 12_000 });
    expect(bar.resume()).toBe(true);
    expect(bar.isAttached).toBe(true);
    expect(out.text).toContain("\x1b[12;1H\n\n\n");
    expect(out.text).toContain("\x1b[1;10r");
    expect(out.text).toContain("12k/100k");
    bar.dispose();
  });

  test("recomputes footer rows on resize", () => {
    const out = new FakeOutput(12, 40);
    const bar = new StatusBar({ out, enabled: true, color: false });
    bar.attach(snapshot);
    out.chunks.length = 0;
    out.rows = 16;
    out.columns = 50;
    bar.resize();
    expect(out.text).toContain("\x1b[1;14r");
    expect(out.text).toContain("\x1b[15;1H");
    expect(out.text).toContain("\x1b[16;1H");
    bar.dispose();
  });

  test("stays disabled without a TTY or with BOURBON_PLAIN", () => {
    const notTty = new StatusBar({ out: new FakeOutput(24, 80, false) });
    expect(notTty.enabled).toBe(false);

    const previous = process.env.BOURBON_PLAIN;
    process.env.BOURBON_PLAIN = "1";
    try {
      const plain = new StatusBar({ out: new FakeOutput(24, 80, true) });
      expect(plain.enabled).toBe(false);
    } finally {
      if (previous === undefined) delete process.env.BOURBON_PLAIN;
      else process.env.BOURBON_PLAIN = previous;
    }

    const short = new StatusBar({ out: new FakeOutput(6, 80, true) });
    expect(short.enabled).toBe(false);
  });
});
