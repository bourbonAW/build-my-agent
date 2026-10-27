export function normalizeTaskListId(taskListId: string): string {
  const normalized = taskListId.trim();
  if (!normalized) throw new Error("Task list id cannot be empty");
  if (normalized.includes("/") || normalized === "." || normalized === "..") {
    throw new Error(`Invalid task list id: ${taskListId}`);
  }
  return normalized;
}
