import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { MessageChain } from "../src/session/chain";
import { ContextManager } from "../src/session/context";
import { SessionManager } from "../src/session/manager";
import { TranscriptStore } from "../src/session/storage";
import { createTranscriptMessage } from "../src/session/types";

let root: string;
let store: TranscriptStore;

beforeEach(() => {
  root = mkdtempSync(join(tmpdir(), "bourbon-session-"));
  store = new TranscriptStore(root);
});

afterEach(() => {
  rmSync(root, { recursive: true, force: true });
});

describe("message chain", () => {
  test("links messages through parent uuids", () => {
    const chain = new MessageChain();
    const first = createTranscriptMessage("user", [{ type: "text", text: "one" }]);
    const second = createTranscriptMessage("assistant", [{ type: "text", text: "two" }]);
    chain.append(first);
    chain.append(second);

    expect(second.parentUuid).toBe(first.uuid);
    expect(chain.buildActiveChain().map((message) => message.uuid)).toEqual([
      first.uuid,
      second.uuid,
    ]);
    expect(chain.getLlmMessages()).toHaveLength(2);
  });

  test("compacts old messages behind a boundary", () => {
    const chain = new MessageChain();
    for (let index = 0; index < 6; index += 1) {
      chain.append(
        createTranscriptMessage(index % 2 ? "assistant" : "user", [
          { type: "text", text: `message ${index}` },
        ]),
      );
    }

    const result = chain.compact(3, "summary text", "manual");
    expect(result.success).toBe(true);
    expect(result.archivedCount).toBe(3);
    expect(result.preservedCount).toBe(3);

    const active = chain.buildActiveChain();
    expect(active).toHaveLength(4);
    expect(active[0]!.isCompactBoundary).toBe(true);
    expect(active[0]!.parentUuid).toBeNull();
    expect(chain.getLlmMessages()).toHaveLength(3);
    expect(chain.getLlmMessages()[0]!.content[0]).toMatchObject({ text: "message 3" });
  });

  test("refuses to compact when too few messages", () => {
    const chain = new MessageChain();
    chain.append(createTranscriptMessage("user", [{ type: "text", text: "one" }]));
    const result = chain.compact(3, "summary");
    expect(result.success).toBe(false);
    expect(result.reason).toContain("insufficient_messages");
  });
});

describe("context manager", () => {
  test("prefers recorded provider tokens", () => {
    const chain = new MessageChain();
    const context = new ContextManager(chain, 100);
    expect(context.shouldCompact()).toBe(false);
    context.recordResponseTokens(500);
    expect(context.estimateTokens()).toBe(500);
    expect(context.shouldCompact()).toBe(true);
    expect(context.getStatus().usageRatio).toBe(5);

    context.resetTokenEstimate();
    expect(context.estimateTokens()).toBe(0);
  });

  test("microcompacts old tool results", () => {
    const chain = new MessageChain();
    for (let index = 0; index < 3; index += 1) {
      chain.append(
        createTranscriptMessage("user", [
          {
            type: "tool_result",
            tool_use_id: `call-${index}`,
            content: "x".repeat(200),
          },
        ]),
      );
    }

    new ContextManager(chain, 1000, 1).microcompact();
    const messages = chain.buildActiveChain();
    expect(messages[0]!.content[0]).toMatchObject({ content: "[cleared]" });
    expect(messages[2]!.content[0]).toMatchObject({ content: "x".repeat(200) });
  });
});

describe("session persistence", () => {
  test("persists, resumes, and compacts a session", () => {
    const manager = new SessionManager(store, "project", root, 100_000, 3, 3);
    const session = manager.createSession("session-1", null, "test session");
    const messages = Array.from({ length: 6 }, (_, index) =>
      createTranscriptMessage(index % 2 ? "assistant" : "user", [
        { type: "text", text: `m${index}` },
      ]),
    );
    for (const message of messages) session.addMessage(message);
    session.save();

    expect(session.metadata.messageCount).toBe(6);
    expect(store.loadTranscript("project", "session-1")).toHaveLength(6);

    const resumed = manager.resumeSession("session-1");
    expect(resumed).not.toBeNull();
    expect(resumed!.chain.getLlmMessages()).toHaveLength(6);

    resumed!.contextManager.recordResponseTokens(90_000);
    expect(resumed!.contextManager.estimateTokens()).toBe(90_000);

    const result = resumed!.maybeCompact("manual");
    expect(result?.success).toBe(true);
    expect(resumed!.contextManager.estimateTokens()).toBeLessThan(90_000);
    expect(resumed!.chain.getLlmMessages()).toHaveLength(3);
    expect(store.loadCompactManifest("project", "session-1")).not.toEqual({});
    expect(store.loadTranscript("project", "session-1").length).toBe(7);

    const afterCompact = manager.resumeSession("session-1");
    expect(afterCompact!.chain.buildActiveChain()[0]!.isCompactBoundary).toBe(true);
    expect(afterCompact!.chain.getLlmMessages()).toHaveLength(3);

    const summaries = manager.listSessions();
    expect(summaries[0]!.uuid).toBe("session-1");
    expect(manager.deleteSession("session-1")).toBe(true);
    expect(existsSync(join(root, "project"))).toBe(true);
    expect(store.loadTranscript("project", "session-1")).toHaveLength(0);
  });

  test("skips malformed transcript lines", () => {
    const manager = new SessionManager(store, "project");
    const session = manager.createSession("bad-lines");
    session.addMessage(createTranscriptMessage("user", [{ type: "text", text: "ok" }]));

    const path = join(root, "project", "bad-lines.jsonl");
    const existing = readFileSync(path, "utf8");
    writeFileSync(path, `${existing}{broken\n`);
    expect(store.loadTranscript("project", "bad-lines")).toHaveLength(1);
  });
});
