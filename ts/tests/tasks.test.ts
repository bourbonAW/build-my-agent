import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { TaskService } from "../src/tasks/service";
import { TaskStore } from "../src/tasks/store";
import { TodoManager } from "../src/todos";
import { createToolRegistry } from "../src/tools";
import type { ToolContext } from "../src/tools";
import { testConfig } from "./helpers/config";

let root: string;
let service: TaskService;

beforeEach(() => {
  root = mkdtempSync(join(tmpdir(), "bourbon-tasks-"));
  service = new TaskService(new TaskStore(root));
});

afterEach(() => {
  rmSync(root, { recursive: true, force: true });
});

describe("task store and service", () => {
  test("allocates incremental ids and persists records", () => {
    const first = service.createTask("list", "First", "first task");
    const second = service.createTask("list", "Second", "second task", "Running");
    expect(first.id).toBe("1");
    expect(second.id).toBe("2");
    expect(second.activeForm).toBe("Running");

    const listed = service.listTasks("list");
    expect(listed.map((task) => task.id)).toEqual(["1", "2"]);

    const updated = service.updateTask("list", "1", {
      status: "in_progress",
      owner: "agent-a",
      metadata: { source: "test" },
    });
    expect(updated.status).toBe("in_progress");
    expect(updated.owner).toBe("agent-a");
    expect(updated.metadata).toEqual({ source: "test" });
  });

  test("supports dependency edges and active blockers", () => {
    const blocker = service.createTask("list", "Blocker", "do first");
    const blocked = service.createTask("list", "Blocked", "do second");

    service.updateTask("list", blocked.id, { addBlockedBy: [blocker.id] });
    expect(service.getTask("list", blocker.id)!.blocks).toContain(blocked.id);
    expect(service.listTasks("list").find((task) => task.id === blocked.id)!.blockedBy).toEqual([
      blocker.id,
    ]);

    service.updateTask("list", blocker.id, { status: "completed" });
    expect(service.listTasks("list").find((task) => task.id === blocked.id)!.blockedBy).toEqual([]);
  });

  test("cleans up peers when a task is deleted", () => {
    const blocker = service.createTask("list", "Blocker", "do first");
    const blocked = service.createTask("list", "Blocked", "do second");
    service.updateTask("list", blocked.id, { addBlockedBy: [blocker.id] });

    service.updateTask("list", blocker.id, { status: "deleted" });
    expect(service.getTask("list", blocker.id)).toBeNull();
    expect(service.getTask("list", blocked.id)!.blockedBy).toEqual([]);
  });

  test("agent tool surface creates, updates, and lists tasks", async () => {
    const config = testConfig({ tasks: { enabled: true, storageDir: root, defaultListId: "default" } });
    const ctx = {
      workdir: root,
      config,
      agent: {
        config,
        session: { sessionId: "session-1" },
        taskListIdOverride: null,
      },
    } as unknown as ToolContext;
    const registry = createToolRegistry();

    const created = JSON.parse(
      await registry.call(
        "TaskCreate",
        { subject: "Ship migration", description: "port everything" },
        ctx,
      ),
    ) as { id: string };
    expect(created.id).toBe("1");

    const updated = JSON.parse(
      await registry.call(
        "TaskUpdate",
        { taskId: created.id, status: "in_progress", activeForm: "Porting" },
        ctx,
      ),
    ) as { status: string; activeForm: string };
    expect(updated.status).toBe("in_progress");
    expect(updated.activeForm).toBe("Porting");

    const listed = JSON.parse(await registry.call("TaskList", {}, ctx)) as Array<{
      id: string;
    }>;
    expect(listed).toHaveLength(1);

    const fetched = JSON.parse(
      await registry.call("TaskGet", { taskId: created.id }, ctx),
    ) as { subject: string };
    expect(fetched.subject).toBe("Ship migration");
  });
});

describe("todo manager", () => {
  test("validates and renders todos", () => {
    const todos = new TodoManager();
    expect(
      todos.update([
        { content: "write tests", status: "in_progress", activeForm: "Writing tests" },
        { content: "ship", status: "pending" },
      ]),
    ).toContain("[>] write tests <- Writing tests");
    expect(todos.hasOpenItems()).toBe(true);

    expect(() =>
      todos.update([
        { content: "a", status: "in_progress", activeForm: "A" },
        { content: "b", status: "in_progress", activeForm: "B" },
      ]),
    ).toThrow("Only one in_progress allowed");

    expect(() => todos.update([{ content: "", status: "pending" }])).toThrow(
      "content required",
    );
    expect(() =>
      todos.update([{ content: "a", status: "in_progress" }]),
    ).toThrow("activeForm required");

    todos.update([{ content: "done", status: "completed" }]);
    expect(todos.items).toEqual([]);
  });

  test("TodoWrite tool updates the agent todo list", async () => {
    const todos = new TodoManager();
    const result = await createToolRegistry().call(
      "TodoWrite",
      { items: [{ content: "task", status: "pending" }] },
      { workdir: root, agent: { todos } as never },
    );
    expect(result).toContain("[ ] task");
    expect(todos.items).toHaveLength(1);
  });
});
