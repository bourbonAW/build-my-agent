import { PromptBuilder } from "./builder";
import { DYNAMIC_SECTIONS } from "./dynamic";
import { DEFAULT_SECTIONS } from "./sections";
import type { PromptContext, PromptSection } from "./types";

export const ALL_SECTIONS: PromptSection[] = [...DEFAULT_SECTIONS, ...DYNAMIC_SECTIONS];

export async function buildSystemPrompt(
  ctx: PromptContext,
  customPrompt?: string,
  appendPrompt?: string,
): Promise<string> {
  return new PromptBuilder(ALL_SECTIONS, customPrompt, appendPrompt).build(ctx);
}

export { PromptBuilder } from "./builder";
export { ContextInjector } from "./context";
export type { PromptContext, PromptSection } from "./types";
