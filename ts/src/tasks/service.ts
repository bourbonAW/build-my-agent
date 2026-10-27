import type { TaskStore } from "./store";
import { TaskRecord } from "./types";

export const UNSET = Symbol("unset");

export interface TaskUpdateInput {
  subject?: string | null;
  description?: string | null;
  status?: string | null;
  activeForm?: string | null | typeof UNSET;
  metadata?: Record<string, unknown> | null | typeof UNSET;
  owner?: string | null | typeof UNSET;
  addBlocks?: string[] | null;
  addBlockedBy?: string[] | null;
}

export class TaskService {
  constructor(private readonly store: TaskStore) {}

  createTask(
    taskListId: string,
    subject: string,
    description: string,
    activeForm: string | null = null,
    metadata: Record<string, unknown> = {},
  ): TaskRecord {
    const taskId = this.store.create(
      taskListId,
      new TaskRecord("", subject, description, "pending", activeForm, null, [], [], {
        ...metadata,
      }),
    );
    const record = this.store.loadTask(taskListId, taskId);
    if (!record) throw new Error(`Task not found after create: ${taskListId}/${taskId}`);
    return record;
  }

  updateTask(taskListId: string, taskId: string, input: TaskUpdateInput): TaskRecord {
    const record = this.requireTask(taskListId, taskId);

    if (input.subject !== undefined && input.subject !== null) record.subject = input.subject;
    if (input.description !== undefined && input.description !== null) {
      record.description = input.description;
    }
    if (input.status !== undefined && input.status !== null) record.status = input.status;
    if (input.activeForm !== undefined && input.activeForm !== UNSET) {
      record.activeForm = input.activeForm as string | null;
    }
    if (input.metadata !== undefined && input.metadata !== UNSET) {
      record.metadata = { ...((input.metadata as Record<string, unknown> | null) ?? {}) };
    }
    if (input.owner !== undefined && input.owner !== UNSET) {
      record.owner = input.owner as string | null;
    }

    const peers = new Map<string, TaskRecord>();

    for (const blockedId of input.addBlocks ?? []) {
      const blocked = this.requireTask(taskListId, blockedId);
      record.blocks = appendUnique(record.blocks, blockedId);
      blocked.blockedBy = appendUnique(blocked.blockedBy, taskId);
      peers.set(blockedId, blocked);
    }

    for (const blockerId of input.addBlockedBy ?? []) {
      const blocker = this.requireTask(taskListId, blockerId);
      record.blockedBy = appendUnique(record.blockedBy, blockerId);
      blocker.blocks = appendUnique(blocker.blocks, taskId);
      peers.set(blockerId, blocker);
    }

    if (record.status === "deleted") {
      this.cleanupPeerDependencies(taskListId, record);
      this.store.deleteTask(taskListId, taskId);
      return record;
    }

    const saved = this.store.updateTask(taskListId, record);
    for (const [peerId, peer] of peers) {
      if (peerId === taskId || peer.status === "deleted") continue;
      this.store.updateTask(taskListId, peer);
    }
    return saved;
  }

  getTask(taskListId: string, taskId: string): TaskRecord | null {
    return this.store.loadTask(taskListId, taskId);
  }

  listTasks(taskListId: string): TaskRecord[] {
    const tasks = this.store.listTasks(taskListId);
    const byId = new Map(tasks.map((task) => [task.id, task]));

    return tasks.map((task) => {
      const activeBlockedBy = task.blockedBy.filter((blockerId) => {
        const blocker = byId.get(blockerId);
        return blocker !== undefined && blocker.status !== "completed";
      });
      return new TaskRecord(
        task.id,
        task.subject,
        task.description,
        task.status,
        task.activeForm,
        task.owner,
        [...task.blocks],
        activeBlockedBy,
        { ...task.metadata },
      );
    });
  }

  claimTask(taskListId: string, taskId: string, owner: string): TaskRecord {
    return this.updateTask(taskListId, taskId, { owner });
  }

  private requireTask(taskListId: string, taskId: string): TaskRecord {
    const record = this.store.loadTask(taskListId, taskId);
    if (!record) throw new Error(`Task not found: ${taskListId}/${taskId}`);
    return record;
  }

  private cleanupPeerDependencies(taskListId: string, record: TaskRecord): void {
    const peerIds = new Set([...record.blocks, ...record.blockedBy]);
    for (const peerId of peerIds) {
      const peer = this.store.loadTask(taskListId, peerId);
      if (!peer || peer.status === "deleted") continue;
      peer.blocks = peer.blocks.filter((id) => id !== record.id);
      peer.blockedBy = peer.blockedBy.filter((id) => id !== record.id);
      this.store.updateTask(taskListId, peer);
    }
  }
}

function appendUnique(values: string[], value: string): string[] {
  return values.includes(value) ? [...values] : [...values, value];
}
