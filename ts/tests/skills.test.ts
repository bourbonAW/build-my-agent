import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Skill, SkillManager, SkillScanner, SkillValidationError } from "../src/skills";
import { createToolRegistry } from "../src/tools";
import type { ToolContext } from "../src/tools";
import { ToolRegistry } from "../src/tools/types";
import { toolSearchTool } from "../src/tools/tool_search";
import { webFetchTool } from "../src/tools/web";
import { testConfig } from "./helpers/config";

let workdir: string;

function writeSkill(
  root: string,
  name: string,
  description: string,
  body: string,
  extraFiles: Record<string, string> = {},
): string {
  const directory = join(root, "skills", name);
  mkdirSync(directory, { recursive: true });
  writeFileSync(
    join(directory, "SKILL.md"),
    `---\nname: ${name}\ndescription: ${description}\nallowed-tools: WebFetch Read\ncompatibility: Requires bun\nmetadata:\n  author: test\n---\n\n${body}\n`,
  );
  for (const [relative, content] of Object.entries(extraFiles)) {
    const path = join(directory, relative);
    mkdirSync(join(path, ".."), { recursive: true });
    writeFileSync(path, content);
  }
  return directory;
}

beforeEach(() => {
  workdir = mkdtempSync(join(tmpdir(), "bourbon-skills-"));
});

afterEach(() => {
  rmSync(workdir, { recursive: true, force: true });
});

describe("skill discovery", () => {
  test("discovers project skills and renders catalog", () => {
    writeSkill(
      join(workdir, ".agents"),
      "demo-skill",
      "Demo skill for tests",
      "Do the demo: $ARGUMENTS",
      { "scripts/run.sh": "echo demo\n", "references/guide.md": "# Guide\n" },
    );

    const manager = new SkillManager(workdir);
    expect(manager.availableSkills).toContain("demo-skill");
    expect(manager.getCatalog()).toContain("<name>demo-skill</name>");
    expect(manager.getCatalog()).toContain("<location>");

    const content = manager.activate("demo-skill", "with args");
    expect(content).toContain('<skill_content name="demo-skill">');
    expect(content).toContain("Do the demo: with args");
    expect(content).toContain("<file>scripts/run.sh</file>");
    expect(content).toContain("<file>references/guide.md</file>");
    expect(manager.isActivated("demo-skill")).toBe(true);
    expect(() => manager.activate("unknown")).toThrow("Unknown skill");
  });

  test("project-level .agents skills override .bourbon skills", () => {
    writeSkill(join(workdir, ".bourbon"), "same-skill", "lower priority", "low");
    writeSkill(join(workdir, ".agents"), "same-skill", "higher priority", "high");

    const manager = new SkillManager(workdir);
    expect(manager.getSkill("same-skill")!.description).toBe("higher priority");
    expect(manager.getDiagnostics().join("\n")).toContain("Skill collision");
  });

  test("reports invalid skill metadata", () => {
    const directory = join(workdir, ".agents", "skills", "invalid");
    mkdirSync(directory, { recursive: true });
    writeFileSync(join(directory, "SKILL.md"), "---\nname: Bad_Name\ndescription: x\n---\nbody");

    const scanner = new SkillScanner(workdir);
    expect(scanner.scan().has("invalid")).toBe(false);
    expect(scanner.getDiagnostics().join("\n")).toContain("Invalid skill");

    expect(
      () => new Skill("Bad_Name", "x", "/tmp/SKILL.md", ""),
    ).toThrow(SkillValidationError);
  });
});

describe("skill tools", () => {
  test("Skill and SkillResource tools load content", async () => {
    writeSkill(
      join(workdir, ".agents"),
      "demo-skill",
      "Demo skill",
      "Follow the guide.",
      { "references/guide.md": "# Guide\nSteps here.\n" },
    );
    const manager = new SkillManager(workdir);
    const registry = createToolRegistry();
    const discovered = new Set<string>();
    const ctx = {
      workdir,
      skillManager: manager,
      config: testConfig(),
      onToolsDiscovered: (names: Set<string>) => {
        for (const name of names) discovered.add(name);
      },
    } as ToolContext;

    const activated = await registry.call("Skill", { name: "demo-skill" }, ctx);
    expect(activated).toContain("Follow the guide.");
    expect(discovered).toEqual(new Set(["WebFetch", "Read"]));

    const again = await registry.call("Skill", { name: "demo-skill" }, ctx);
    expect(again).toContain("skill_already_loaded");

    const resource = await registry.call(
      "SkillResource",
      { skill_name: "demo-skill", path: "references/guide.md" },
      ctx,
    );
    expect(resource).toContain("Steps here.");

    const missing = await registry.call(
      "SkillResource",
      { skill_name: "demo-skill", path: "missing.md" },
      ctx,
    );
    expect(missing).toContain("not found");
  });
});

describe("deferred tool discovery", () => {
  test("ToolSearch reveals deferred tools", async () => {
    const registry = new ToolRegistry();
    registry.register(toolSearchTool);
    registry.register(webFetchTool);

    const before = registry.definitions(new Set()).map((tool) => tool.name);
    expect(before).toEqual(["ToolSearch"]);

    const discovered = new Set<string>();
    const result = await registry.call(
      "ToolSearch",
      { query: "fetch web page" },
      {
        workdir,
        registry,
        onToolsDiscovered: (names) => {
          for (const name of names) discovered.add(name);
        },
      },
    );

    expect(result).toContain("Found 1 tool(s)");
    expect(discovered).toEqual(new Set(["WebFetch"]));
    expect(registry.definitions(discovered).map((tool) => tool.name)).toContain("WebFetch");
  });
});
