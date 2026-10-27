import type { PromptContext } from "./types";

const GIT_TIMEOUT_MS = 2000;
const GIT_STATUS_MAX_LINES = 50;

export class ContextInjector {
  async inject(userMessage: string, ctx: PromptContext): Promise<string> {
    const environment = await this.getEnvInfo(ctx);
    return `<system-reminder>\n${environment}\n</system-reminder>\n${userMessage}`;
  }

  private async getEnvInfo(ctx: PromptContext): Promise<string> {
    const parts = [
      `Working directory: ${ctx.workdir}`,
      `Today's date: ${new Date().toISOString().slice(0, 10)}`,
    ];
    const git = await this.getGitStatus(ctx.workdir);
    if (git) parts.push(`Git status:\n${git}`);
    return parts.join("\n");
  }

  private async getGitStatus(workdir: string): Promise<string | null> {
    try {
      const proc = Bun.spawn(["git", "-C", workdir, "status", "--short", "-b"], {
        stdout: "pipe",
        stderr: "pipe",
      });
      const timer = setTimeout(() => proc.kill(9), GIT_TIMEOUT_MS);
      try {
        const [stdout, , code] = await Promise.all([
          new Response(proc.stdout).text(),
          new Response(proc.stderr).text(),
          proc.exited,
        ]);
        if (code !== 0) return null;
        const text = stdout.trim();
        return text ? this.truncateGitStatus(text) : null;
      } finally {
        clearTimeout(timer);
      }
    } catch {
      return null;
    }
  }

  private truncateGitStatus(text: string): string {
    const lines = text.split("\n");
    if (lines.length <= GIT_STATUS_MAX_LINES) return text;
    const omitted = lines.length - GIT_STATUS_MAX_LINES;
    return [...lines.slice(0, GIT_STATUS_MAX_LINES), `[... ${omitted} more lines truncated ...]`].join(
      "\n",
    );
  }
}
