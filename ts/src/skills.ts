import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { parse as parseYaml } from "yaml";

export class SkillValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "SkillValidationError";
  }
}

export interface SkillFrontmatter {
  license?: string;
  compatibility?: string;
  metadata?: Record<string, string>;
  allowedTools?: string[];
}

export class Skill {
  constructor(
    readonly name: string,
    readonly description: string,
    readonly location: string,
    readonly body: string,
    readonly license = "",
    readonly compatibility = "",
    readonly metadata: Record<string, string> = {},
    readonly allowedTools: string[] = [],
  ) {
    this.validateName();
  }

  private validateName(): void {
    if (!this.name) throw new SkillValidationError("Skill name is required");
    if (this.name.length > 64) {
      throw new SkillValidationError(`Skill name exceeds 64 characters: ${this.name}`);
    }
    if (!/^[a-z0-9]+(-[a-z0-9]+)*$/.test(this.name)) {
      throw new SkillValidationError(
        `Invalid skill name '${this.name}'. Must be lowercase alphanumeric with hyphens only.`,
      );
    }
  }

  get baseDir(): string {
    return dirname(this.location);
  }

  private resourceDir(name: string): string | null {
    const path = join(this.baseDir, name);
    return existsSync(path) && statSync(path).isDirectory() ? path : null;
  }

  listResources(): Record<string, string[]> {
    const resources: Record<string, string[]> = {};
    for (const category of ["scripts", "references", "assets"]) {
      const directory = this.resourceDir(category);
      if (!directory) continue;
      resources[category] = readdirSync(directory)
        .filter((name) => statSync(join(directory, name)).isFile())
        .map((name) => `${category}/${name}`);
    }
    return resources;
  }

  getResourcePath(relativePath: string): string | null {
    const path = join(this.baseDir, relativePath);
    return existsSync(path) && statSync(path).isFile() ? path : null;
  }

  renderCatalogEntry(): string {
    const lines = [
      "  <skill>",
      `    <name>${this.name}</name>`,
      `    <description>${this.description}</description>`,
      `    <location>${this.location}</location>`,
    ];
    if (this.compatibility) {
      lines.push(`    <compatibility>${this.compatibility}</compatibility>`);
    }
    lines.push("  </skill>");
    return lines.join("\n");
  }

  renderForActivation(args = ""): string {
    const lines = [
      `<skill_content name="${this.name}">`,
      this.body,
      "",
      `Skill directory: ${this.baseDir}`,
      "Relative paths in this skill are relative to the skill directory.",
    ];

    const resources = this.listResources();
    if (Object.keys(resources).length) {
      lines.push("", "<skill_resources>");
      for (const files of Object.values(resources)) {
        for (const file of files) lines.push(`  <file>${file}</file>`);
      }
      lines.push("</skill_resources>");
    }

    lines.push("</skill_content>");
    return lines
      .join("\n")
      .replaceAll("$ARGUMENTS", args)
      .replaceAll("${CLAUDE_SKILL_DIR}", this.baseDir);
  }
}

const DEFAULT_SCOPES = [
  "{workdir}/.agents/skills",
  "{workdir}/.bourbon/skills",
  "{workdir}/.kimi/skills",
  "{workdir}/.claude/skills",
  "~/.agents/skills",
  "~/.bourbon/skills",
  "~/.claude/skills",
];

export class SkillScanner {
  private diagnostics: string[] = [];

  constructor(
    private readonly workdir: string,
    private readonly additionalScopes: string[] = [],
  ) {}

  scan(): Map<string, Skill> {
    this.diagnostics = [];
    const skills = new Map<string, Skill>();
    const scopes: string[] = [];

    for (const template of DEFAULT_SCOPES) {
      const path = template.replace("{workdir}", this.workdir).replace("~", homedir());
      if (existsSync(path) && statSync(path).isDirectory()) scopes.push(path);
    }
    for (const scope of this.additionalScopes) {
      const path = scope.replace("~", homedir());
      if (existsSync(path)) scopes.push(path);
    }

    for (const scope of scopes.reverse()) {
      for (const directory of this.discoverSkillDirs(scope)) {
        try {
          const skill = this.parseSkill(join(directory, "SKILL.md"));
          const existing = skills.get(skill.name);
          if (existing) {
            this.diagnostics.push(
              `Skill collision: '${skill.name}' in ${directory} overrides ${existing.location}`,
            );
          }
          skills.set(skill.name, skill);
        } catch (error) {
          const message = error instanceof Error ? error.message : String(error);
          this.diagnostics.push(`Invalid skill in ${directory}: ${message}`);
        }
      }
    }

    return skills;
  }

  getDiagnostics(): string[] {
    return [...this.diagnostics];
  }

  private discoverSkillDirs(scope: string): string[] {
    const directories: string[] = [];
    try {
      for (const entry of readdirSync(scope, { withFileTypes: true })) {
        if (!entry.isDirectory()) continue;
        if (entry.name.startsWith(".")) continue;
        if (["node_modules", "__pycache__", ".git"].includes(entry.name)) continue;
        const skillPath = join(scope, entry.name, "SKILL.md");
        if (existsSync(skillPath) && statSync(skillPath).isFile()) {
          directories.push(join(scope, entry.name));
        }
      }
    } catch {
      this.diagnostics.push(`Permission denied: ${scope}`);
    }
    return directories;
  }

  private parseSkill(skillPath: string): Skill {
    const text = readFileSync(skillPath, "utf8");
    const match = /^---\s*\n([\s\S]*?)\n---\s*\n([\s\S]*)$/.exec(text);
    if (!match) throw new SkillValidationError("Missing or invalid YAML frontmatter");

    const frontmatter = (parseYaml(match[1]!) ?? {}) as Record<string, unknown>;
    const name = typeof frontmatter.name === "string" ? frontmatter.name : this.dirName(skillPath);
    const description = typeof frontmatter.description === "string" ? frontmatter.description : "";
    if (!description) throw new SkillValidationError("Missing required 'description' field");

    let allowedTools: string[] = [];
    const rawAllowed = frontmatter["allowed-tools"];
    if (typeof rawAllowed === "string") allowedTools = rawAllowed.split(/\s+/).filter(Boolean);
    else if (Array.isArray(rawAllowed)) allowedTools = rawAllowed.map(String);

    const metadata: Record<string, string> = {};
    if (frontmatter.metadata && typeof frontmatter.metadata === "object") {
      for (const [key, value] of Object.entries(frontmatter.metadata as Record<string, unknown>)) {
        metadata[key] = String(value);
      }
    }

    return new Skill(
      name,
      description,
      skillPath,
      match[2]!.trim(),
      typeof frontmatter.license === "string" ? frontmatter.license : "",
      typeof frontmatter.compatibility === "string" ? frontmatter.compatibility : "",
      metadata,
      allowedTools,
    );
  }

  private dirName(path: string): string {
    return path.split("/").slice(-2, -1)[0] ?? "";
  }
}

export class SkillManager {
  private readonly scanner: SkillScanner;
  private skills = new Map<string, Skill>();
  private readonly activated = new Set<string>();

  constructor(readonly workdir: string, additionalScopes: string[] = []) {
    this.scanner = new SkillScanner(workdir, additionalScopes);
    this.discover();
  }

  private discover(): void {
    this.skills = this.scanner.scan();
  }

  get availableSkills(): string[] {
    return [...this.skills.keys()];
  }

  get activatedSkills(): string[] {
    return [...this.activated];
  }

  getSkill(name: string): Skill | undefined {
    return this.skills.get(name);
  }

  getCatalog(): string {
    if (!this.skills.size) return "";
    const lines = ["<available_skills>"];
    for (const skill of [...this.skills.values()].sort((a, b) => a.name.localeCompare(b.name))) {
      lines.push(skill.renderCatalogEntry());
    }
    lines.push("</available_skills>");
    return lines.join("\n");
  }

  activate(name: string, args = ""): string {
    const skill = this.skills.get(name);
    if (!skill) {
      const available = [...this.skills.keys()].sort().join(", ");
      throw new SkillValidationError(
        `Unknown skill '${name}'. Available: ${available || "(none)"}`,
      );
    }
    this.activated.add(name);
    return skill.renderForActivation(args);
  }

  isActivated(name: string): boolean {
    return this.activated.has(name);
  }

  getDiagnostics(): string[] {
    return this.scanner.getDiagnostics();
  }
}
