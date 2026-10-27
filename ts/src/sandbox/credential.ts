function fnmatch(value: string, pattern: string): boolean {
  const regex = pattern
    .split("")
    .map((char) => (char === "*" ? ".*" : char.replace(/[.+^${}()|[\]\\?]/g, "\\$&")))
    .join("");
  return new RegExp(`^${regex}$`).test(value);
}

const SENSITIVE_PATTERNS = [
  "*_KEY",
  "*_SECRET",
  "*_TOKEN",
  "*_PASSWORD",
  "AWS_*",
  "OPENAI_*",
  "ANTHROPIC_*",
  "DATABASE_URL",
  "REDIS_URL",
];

export class CredentialManager {
  cleanEnv(
    passthroughVars: string[],
    sourceEnv: Record<string, string | undefined> = process.env,
  ): Record<string, string> {
    const result: Record<string, string> = {};
    for (const [key, value] of Object.entries(sourceEnv)) {
      if (value === undefined) continue;
      if (passthroughVars.includes(key) && !this.isSensitive(key)) {
        result[key] = value;
      }
    }
    return result;
  }

  isSensitive(key: string): boolean {
    return SENSITIVE_PATTERNS.some((pattern) => fnmatch(key, pattern));
  }
}
