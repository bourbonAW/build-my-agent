import {
  existsSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  renameSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import { dirname, join } from "node:path";
import { normalizeTaskListId } from "./list_id";
import { FileLock } from "./locking";
import { TaskRecord } from "./types";

const HIGH_WATERMARK_FILE = ".highwatermark";
const LOCK_FILE = ".lock";

export class TaskStore {
  constructor(readonly baseDir: string) {}

  private listDir(taskListId: string): string {
    return join(this.baseDir, normalizeTaskListId(taskListId));
  }

  private taskPath(taskListId: string, taskId: string): string {
    return join(this.listDir(taskListId), `${taskId}.json`);
  }

  private highWatermarkPath(taskListId: string): string {
    return join(this.listDir(taskListId), HIGH_WATERMARK_FILE);
  }

  private lockPath(taskListId: string): string {
    return join(this.listDir(taskListId), LOCK_FILE);
  }

  private ensureListDir(taskListId: string): string {
    const directory = this.listDir(taskListId);
    mkdirSync(directory, { recursive: true });
    return directory;
  }

  private writeJsonAtomic(path: string, payload: unknown): void {
    mkdirSync(dirname(path), { recursive: true });
    const temp = `${path}.${process.pid}.tmp`;
    writeFileSync(temp, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
    renameSync(temp, path);
  }

  private allocateTaskId(taskListId: string): string {
    const path = this.highWatermarkPath(taskListId);
    let current = 0;
    if (existsSync(path)) {
      const raw = readFileSync(path, "utf8").trim();
      if (raw) current = Number.parseInt(raw, 10) || 0;
    }
    const next = current + 1;
    writeFileSync(path, String(next), "utf8");
    return String(next);
  }

  create(taskListId: string, record: TaskRecord): string {
    this.ensureListDir(taskListId);
    return new FileLock(this.lockPath(taskListId)).withLock(() => {
      const taskId = this.allocateTaskId(taskListId);
      const stored = new TaskRecord(
        taskId,
        record.subject,
        record.description,
        record.status,
        record.activeForm,
        record.owner,
        [...record.blocks],
        [...record.blockedBy],
        { ...record.metadata },
      );
      this.writeJsonAtomic(this.taskPath(taskListId, taskId), stored.toDict());
      return taskId;
    });
  }

  loadTask(taskListId: string, taskId: string): TaskRecord | null {
    const path = this.taskPath(taskListId, taskId);
    if (!existsSync(path)) return null;
    try {
      return TaskRecord.fromDict(
        JSON.parse(readFileSync(path, "utf8")) as Record<string, unknown>,
      );
    } catch {
      return null;
    }
  }

  listTasks(taskListId: string): TaskRecord[] {
    const directory = this.listDir(taskListId);
    if (!existsSync(directory)) return [];

    const tasks: TaskRecord[] = [];
    for (const name of readdirSync(directory)) {
      if (!name.endsWith(".json")) continue;
      try {
        tasks.push(
          TaskRecord.fromDict(
            JSON.parse(readFileSync(join(directory, name), "utf8")) as Record<
              string,
              unknown
            >,
          ),
        );
      } catch {
        continue;
      }
    }
    return tasks.sort((left, right) => Number(left.id) - Number(right.id));
  }

  updateTask(taskListId: string, record: TaskRecord): TaskRecord {
    this.ensureListDir(taskListId);
    return new FileLock(this.lockPath(taskListId)).withLock(() => {
      const path = this.taskPath(taskListId, record.id);
      if (!existsSync(path)) {
        throw new Error(`Task not found: ${taskListId}/${record.id}`);
      }
      if (record.status === "deleted") {
        unlinkSync(path);
        return record;
      }
      this.writeJsonAtomic(path, record.toDict());
      return record;
    });
  }

  deleteTask(taskListId: string, taskId: string): void {
    this.ensureListDir(taskListId);
    new FileLock(this.lockPath(taskListId)).withLock(() => {
      const path = this.taskPath(taskListId, taskId);
      if (existsSync(path)) unlinkSync(path);
    });
  }
}
