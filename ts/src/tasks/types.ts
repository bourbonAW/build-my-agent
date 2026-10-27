export interface TaskRecordData {
  id: string;
  subject: string;
  description: string;
  status: string;
  activeForm: string | null;
  owner: string | null;
  blocks: string[];
  blockedBy: string[];
  metadata: Record<string, unknown>;
}

export class TaskRecord implements TaskRecordData {
  constructor(
    public id: string,
    public subject: string,
    public description: string,
    public status = "pending",
    public activeForm: string | null = null,
    public owner: string | null = null,
    public blocks: string[] = [],
    public blockedBy: string[] = [],
    public metadata: Record<string, unknown> = {},
  ) {}

  toDict(): TaskRecordData {
    return {
      id: this.id,
      subject: this.subject,
      description: this.description,
      status: this.status,
      activeForm: this.activeForm,
      owner: this.owner,
      blocks: [...this.blocks],
      blockedBy: [...this.blockedBy],
      metadata: { ...this.metadata },
    };
  }

  static fromDict(data: Record<string, unknown>): TaskRecord {
    return new TaskRecord(
      String(data.id),
      String(data.subject),
      String(data.description),
      String(data.status ?? "pending"),
      data.activeForm === null || data.activeForm === undefined
        ? null
        : String(data.activeForm),
      data.owner === null || data.owner === undefined ? null : String(data.owner),
      Array.isArray(data.blocks) ? data.blocks.map(String) : [],
      Array.isArray(data.blockedBy) ? data.blockedBy.map(String) : [],
      (data.metadata as Record<string, unknown>) ?? {},
    );
  }

  clone(): TaskRecord {
    return TaskRecord.fromDict(this.toDict() as unknown as Record<string, unknown>);
  }
}
