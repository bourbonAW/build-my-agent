import { homedir } from "node:os";
import { TaskService, UNSET } from "../tasks/service";
import { TaskStore } from "../tasks/store";
import type { TaskUpdateInput } from "../tasks/service";
import type { Tool, ToolContext } from "./types";

function resolveTaskListId(ctx: ToolContext, explicit?: string): string {
  if (explicit) return explicit;
  if (ctx.agent?.taskListIdOverride) return ctx.agent.taskListIdOverride;
  if (ctx.agent?.session?.sessionId) return String(ctx.agent.session.sessionId);
  if (ctx.config?.tasks.defaultListId) return ctx.config.tasks.defaultListId;
  return "default";
}

function taskService(ctx: ToolContext): TaskService {
  const storageDir = (ctx.config?.tasks.storageDir ?? "~/.bourbon/tasks").replace(
    /^~(?=\/|$)/,
    homedir(),
  );
  return new TaskService(new TaskStore(storageDir));
}

export const taskCreateTool: Tool = {
  name: "TaskCreate",
  description: "Create a persistent workflow task in the current task list.",
  inputSchema: {
    type: "object",
    properties: {
      taskListId: { type: "string" },
      subject: { type: "string" },
      description: { type: "string" },
      activeForm: { type: ["string", "null"] },
      metadata: { type: "object" },
    },
    required: ["subject", "description"],
  },
  riskLevel: "medium",
  requiredCapabilities: ["file_write"],
  run: async (input, ctx) => {
    const service = taskService(ctx);
    const taskListId = resolveTaskListId(
      ctx,
      typeof input.taskListId === "string" ? input.taskListId : undefined,
    );
    const metadata =
      input.metadata && typeof input.metadata === "object"
        ? (input.metadata as Record<string, unknown>)
        : {};
    const record = service.createTask(
      taskListId,
      String(input.subject ?? ""),
      String(input.description ?? ""),
      typeof input.activeForm === "string" ? input.activeForm : null,
      metadata,
    );
    ctx.executionMarkers?.add("task");
    return JSON.stringify(record.toDict());
  },
};

export const taskUpdateTool: Tool = {
  name: "TaskUpdate",
  description: "Update a persistent workflow task.",
  inputSchema: {
    type: "object",
    properties: {
      taskListId: { type: "string" },
      taskId: { type: "string" },
      subject: { type: "string" },
      description: { type: "string" },
      status: { type: "string" },
      activeForm: { type: ["string", "null"] },
      owner: { type: ["string", "null"] },
      metadata: { type: "object" },
      addBlocks: { type: "array", items: { type: "string" } },
      addBlockedBy: { type: "array", items: { type: "string" } },
    },
    required: ["taskId"],
  },
  riskLevel: "medium",
  requiredCapabilities: ["file_write"],
  run: async (input, ctx) => {
    const service = taskService(ctx);
    const taskListId = resolveTaskListId(
      ctx,
      typeof input.taskListId === "string" ? input.taskListId : undefined,
    );
    const taskId = String(input.taskId ?? "");
    const update: TaskUpdateInput = {
      subject: typeof input.subject === "string" ? input.subject : undefined,
      description: typeof input.description === "string" ? input.description : undefined,
      status: typeof input.status === "string" ? input.status : undefined,
      addBlocks: Array.isArray(input.addBlocks) ? input.addBlocks.map(String) : undefined,
      addBlockedBy: Array.isArray(input.addBlockedBy)
        ? input.addBlockedBy.map(String)
        : undefined,
    };
    if ("activeForm" in input) {
      update.activeForm =
        input.activeForm === null || typeof input.activeForm === "string"
          ? (input.activeForm as string | null)
          : UNSET;
    }
    if ("owner" in input) {
      update.owner =
        input.owner === null || typeof input.owner === "string"
          ? (input.owner as string | null)
          : UNSET;
    }
    if ("metadata" in input) {
      update.metadata =
        input.metadata && typeof input.metadata === "object"
          ? (input.metadata as Record<string, unknown>)
          : input.metadata === null
            ? null
            : UNSET;
    }
    const record = service.updateTask(taskListId, taskId, update);
    ctx.executionMarkers?.add("task");
    return JSON.stringify(record.toDict());
  },
};

export const taskListTool: Tool = {
  name: "TaskList",
  description: "List persistent workflow tasks in the current task list.",
  inputSchema: {
    type: "object",
    properties: {
      taskListId: { type: "string" },
    },
  },
  riskLevel: "low",
  isReadOnly: true,
  requiredCapabilities: ["file_read"],
  isConcurrencySafe: () => true,
  run: async (input, ctx) => {
    const service = taskService(ctx);
    const taskListId = resolveTaskListId(
      ctx,
      typeof input.taskListId === "string" ? input.taskListId : undefined,
    );
    return JSON.stringify(service.listTasks(taskListId).map((record) => record.toDict()));
  },
};

export const taskGetTool: Tool = {
  name: "TaskGet",
  description: "Get one persistent workflow task by id.",
  inputSchema: {
    type: "object",
    properties: {
      taskListId: { type: "string" },
      taskId: { type: "string" },
    },
    required: ["taskId"],
  },
  riskLevel: "low",
  isReadOnly: true,
  requiredCapabilities: ["file_read"],
  isConcurrencySafe: () => true,
  run: async (input, ctx) => {
    const service = taskService(ctx);
    const taskListId = resolveTaskListId(
      ctx,
      typeof input.taskListId === "string" ? input.taskListId : undefined,
    );
    const record = service.getTask(taskListId, String(input.taskId ?? ""));
    return JSON.stringify(record ? record.toDict() : null);
  },
};
