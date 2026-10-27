import { realpathSync } from "node:fs";
import { homedir } from "node:os";
import { resolve } from "node:path";
import type { SandboxContext } from "./runtime";

export type MountMode = "ro" | "rw" | "deny";

export interface MountRule {
  path: string;
  mode: MountMode;
}

export class FilesystemPolicy {
  constructor(readonly rules: MountRule[]) {}

  static fromContext(context: SandboxContext): FilesystemPolicy {
    const rules: MountRule[] = [];
    const seen = new Set<string>();

    const workdir = resolvePath(context.workdir);
    rules.push({ path: workdir, mode: "rw" });
    seen.add(workdir);

    for (const path of context.writablePaths) {
      const resolved = resolvePath(path);
      if (seen.has(resolved)) continue;
      rules.push({ path: resolved, mode: "rw" });
      seen.add(resolved);
    }

    for (const path of context.readonlyPaths) {
      const resolved = resolvePath(path);
      if (seen.has(resolved)) continue;
      rules.push({ path: resolved, mode: "ro" });
      seen.add(resolved);
    }

    for (const path of context.denyPaths) {
      rules.push({ path: resolvePath(path), mode: "deny" });
    }

    return new FilesystemPolicy(rules);
  }
}

function resolvePath(path: string): string {
  const expanded = path.replace(/^~(?=\/|$)/, homedir());
  try {
    return realpathSync(expanded);
  } catch {
    return resolve(expanded);
  }
}
