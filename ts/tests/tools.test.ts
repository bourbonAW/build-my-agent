import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createToolRegistry } from "../src/tools";
import { isReadonlyBash, runBash, safePath, truncate } from "../src/tools/base";
import { globFiles } from "../src/tools/search";

let workdir: string;
const registry = createToolRegistry();

beforeEach(() => {
  workdir = mkdtempSync(join(tmpdir(), "bourbon-ts-test-"));
});

afterEach(() => {
  rmSync(workdir, { recursive: true, force: true });
});

describe("file tools", () => {
  test("writes and reads a file", async () => {
    const write = await registry.call(
      "Write",
      { path: "nested/hello.txt", content: "hello\nworld" },
      { workdir },
    );
    expect(write).toContain("Wrote");

    const read = await registry.call("Read", { path: "nested/hello.txt" }, { workdir });
    expect(read).toBe("hello\nworld");
  });

  test("edits only the first occurrence", async () => {
    writeFileSync(join(workdir, "a.txt"), "foo foo");

    const result = await registry.call(
      "Edit",
      { path: "a.txt", old_text: "foo", new_text: "bar" },
      { workdir },
    );
    expect(result).toBe("Edited a.txt");

    const read = await registry.call("Read", { path: "a.txt" }, { workdir });
    expect(read).toBe("bar foo");
  });

  test("reports missing edit target", async () => {
    writeFileSync(join(workdir, "a.txt"), "foo");
    const result = await registry.call(
      "Edit",
      { path: "a.txt", old_text: "nope", new_text: "bar" },
      { workdir },
    );
    expect(result).toBe("Error: Text not found in a.txt");
  });

  test("reads with offset and limit", async () => {
    writeFileSync(join(workdir, "a.txt"), "1\n2\n3\n4\n5");
    const result = await registry.call(
      "Read",
      { path: "a.txt", offset: 2, limit: 2 },
      { workdir },
    );
    expect(result).toBe("2\n3\n... (2 more lines)");
  });

  test("blocks path escape", async () => {
    expect(() => safePath("../outside.txt", workdir)).toThrow("Path escapes workspace");
    const result = await registry.call("Read", { path: "../outside.txt" }, { workdir });
    expect(result).toContain("Path escapes workspace");
  });
});

describe("bash tool", () => {
  test("runs a command in the workspace", async () => {
    const result = await runBash("echo hi", workdir);
    expect(result).toBe("hi");
  });

  test("blocks dangerous commands", async () => {
    const result = await runBash("rm -rf /", workdir);
    expect(result).toBe("Error: Dangerous command blocked (rm -rf /)");
  });

  test("times out long commands", async () => {
    const result = await runBash("sleep 2", workdir, 0.1);
    expect(result).toBe("Error: Timeout (0.1s)");
  });

  test("detects read-only commands conservatively", () => {
    expect(isReadonlyBash("cat README.md")).toBe(true);
    expect(isReadonlyBash("find . -name '*.ts'")).toBe(true);
    expect(isReadonlyBash("cat a > b")).toBe(false);
    expect(isReadonlyBash("ls; rm x")).toBe(false);
    expect(isReadonlyBash("find . -delete")).toBe(false);
    expect(isReadonlyBash("echo $(whoami)")).toBe(false);
    expect(isReadonlyBash("uniq a b")).toBe(false);
  });
});

describe("search tools", () => {
  test("finds files by glob", () => {
    mkdirSync(join(workdir, "src"));
    writeFileSync(join(workdir, "src/a.ts"), "");
    writeFileSync(join(workdir, "src/b.py"), "");

    const result = globFiles("**/*.ts", ".", workdir);
    expect(result).toBe("src/a.ts");
  });

  test("reports empty glob", () => {
    expect(globFiles("**/*.rs", ".", workdir)).toBe("No files matching '**/*.rs'");
  });

  test("finds text matches", async () => {
    writeFileSync(join(workdir, "a.txt"), "alpha\nbeta");
    const result = await registry.call("Grep", { pattern: "beta" }, { workdir });
    expect(result).toContain("Found 1 matches for 'beta'");
    expect(result).toContain("a.txt:2: beta");
  });

  test("reports no matches", async () => {
    writeFileSync(join(workdir, "a.txt"), "alpha");
    const result = await registry.call("Grep", { pattern: "gamma" }, { workdir });
    expect(result).toBe("No matches for 'gamma'");
  });
});

test("truncates long output", () => {
  expect(truncate("abcdef", 3)).toBe("abc\n... (3 more chars)");
});
