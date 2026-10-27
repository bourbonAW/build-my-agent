export interface TodoItem {
  content: string;
  status: "pending" | "in_progress" | "completed";
  activeForm: string;
}

const VALID_STATUSES = new Set(["pending", "in_progress", "completed"]);

export class TodoManager {
  readonly MAX_TODOS = 20;
  items: TodoItem[] = [];

  update(rawItems: Array<Record<string, unknown>>): string {
    const validated: TodoItem[] = [];
    let inProgress = 0;

    rawItems.forEach((item, index) => {
      const content = String(item.content ?? "").trim();
      const status = String(item.status ?? "pending").toLowerCase();
      const activeForm = String(item.activeForm ?? "").trim();

      if (!content) throw new Error(`Item ${index}: content required`);
      if (!VALID_STATUSES.has(status)) {
        throw new Error(`Item ${index}: invalid status '${status}'`);
      }
      if (status === "in_progress" && !activeForm) {
        throw new Error(`Item ${index}: activeForm required for in_progress`);
      }
      if (status === "in_progress") inProgress += 1;

      validated.push({
        content,
        status: status as TodoItem["status"],
        activeForm,
      });
    });

    if (validated.length > this.MAX_TODOS) {
      throw new Error(`Max ${this.MAX_TODOS} todos`);
    }
    if (inProgress > 1) {
      throw new Error("Only one in_progress allowed");
    }

    this.items =
      validated.length && validated.every((item) => item.status === "completed")
        ? []
        : validated;
    return this.render();
  }

  render(): string {
    if (!this.items.length) return "No todos.";

    const lines = this.items.map((item) => {
      const mark =
        item.status === "completed" ? "x" : item.status === "in_progress" ? ">" : " ";
      const suffix = item.status === "in_progress" ? ` <- ${item.activeForm}` : "";
      return `[${mark}] ${item.content}${suffix}`;
    });

    const completed = this.items.filter((item) => item.status === "completed").length;
    lines.push(`\n(${completed}/${this.items.length} completed)`);
    return lines.join("\n");
  }

  hasOpenItems(): boolean {
    return this.items.some((item) => item.status !== "completed");
  }

  toList(): Array<Record<string, string>> {
    return this.items.map((item) => ({
      content: item.content,
      status: item.status,
      activeForm: item.activeForm,
    }));
  }
}
