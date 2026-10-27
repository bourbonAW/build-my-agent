import type { PromptContext, PromptSection } from "./types";

export class PromptBuilder {
  private readonly sections: PromptSection[];

  constructor(
    sections: PromptSection[],
    private readonly customPrompt?: string,
    private readonly appendPrompt?: string,
  ) {
    this.sections = [...sections].sort((left, right) => left.order - right.order);
  }

  async build(ctx: PromptContext): Promise<string> {
    let base = this.customPrompt ?? (await this.assembleSections(ctx));
    if (this.appendPrompt !== undefined) {
      base = `${base}\n\n${this.appendPrompt}`;
    }
    return base;
  }

  private async assembleSections(ctx: PromptContext): Promise<string> {
    const parts: string[] = [];
    for (const section of this.sections) {
      const content = section.content;
      const text = typeof content === "string" ? content : await content(ctx);
      if (text) parts.push(text);
    }
    return parts.join("\n\n");
  }
}
