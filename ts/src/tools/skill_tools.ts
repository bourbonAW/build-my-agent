import { SkillManager, SkillValidationError } from "../skills";
import type { Tool } from "./types";
import { requireString } from "./types";

let globalSkillManager: SkillManager | null = null;

export function getGlobalSkillManager(workdir: string): SkillManager {
  globalSkillManager ??= new SkillManager(workdir);
  return globalSkillManager;
}

export const skillTool: Tool = {
  name: "Skill",
  aliases: ["skill"],
  description: `Activate a skill to load specialized instructions and capabilities.

When to use:
- When starting a task that matches a skill's domain
- When the user mentions a specific domain or technology covered by a skill
- When you need guidance on best practices for a specific task type

The skill will provide detailed instructions, examples, and may include scripts or references.`,
  inputSchema: {
    type: "object",
    properties: {
      name: {
        type: "string",
        description: "Name of the skill to activate (as shown in available_skills catalog)",
      },
      args: {
        type: "string",
        description: "Optional arguments passed to the skill ($ARGUMENTS substitution)",
      },
    },
    required: ["name"],
  },
  riskLevel: "low",
  requiredCapabilities: ["skill"],
  run: async (input, ctx) => {
    const manager = ctx.skillManager ?? getGlobalSkillManager(ctx.workdir);
    const name = requireString(input, "name");
    const args = typeof input.args === "string" ? input.args : "";

    try {
      if (manager.isActivated(name)) {
        return `<skill_already_loaded name="${name}"/>\n\nSkill '${name}' is already active.`;
      }
      const content = manager.activate(name, args);
      const skill = manager.getSkill(name);
      if (skill?.allowedTools.length && ctx.onToolsDiscovered) {
        ctx.onToolsDiscovered(new Set(skill.allowedTools));
      }
      return content;
    } catch (error) {
      if (error instanceof SkillValidationError) return `Error: ${error.message}`;
      return `Error activating skill '${name}': ${
        error instanceof Error ? error.message : String(error)
      }`;
    }
  },
};

export const skillResourceTool: Tool = {
  name: "SkillResource",
  aliases: ["skill_read_resource"],
  description: `Read a resource file from an activated skill.

Use this to load scripts, references, or assets referenced by skill instructions.`,
  inputSchema: {
    type: "object",
    properties: {
      skill_name: {
        type: "string",
        description: "Name of the skill containing the resource",
      },
      path: {
        type: "string",
        description: "Relative path to resource (e.g., 'scripts/extract.py')",
      },
    },
    required: ["skill_name", "path"],
  },
  riskLevel: "low",
  isReadOnly: true,
  isConcurrencySafe: () => true,
  run: async (input, ctx) => {
    const manager = ctx.skillManager ?? getGlobalSkillManager(ctx.workdir);
    const skillName = requireString(input, "skill_name");
    const path = requireString(input, "path");
    const skill = manager.getSkill(skillName);
    if (!skill) return `Error: Skill '${skillName}' not found`;

    const resourcePath = skill.getResourcePath(path);
    if (!resourcePath) {
      const available = Object.values(skill.listResources()).flat();
      return `Error: Resource '${path}' not found in skill '${skillName}'. Available: ${
        available.length ? available.join(", ") : "(none)"
      }`;
    }

    try {
      return await Bun.file(resourcePath).text();
    } catch (error) {
      return `Error reading resource: ${error instanceof Error ? error.message : String(error)}`;
    }
  },
};
