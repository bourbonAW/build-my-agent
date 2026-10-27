export class CredentialProxy {
  private server: ReturnType<typeof Bun.serve> | null = null;

  constructor(
    private readonly allowDomains: string[],
    private readonly host = "127.0.0.1",
  ) {}

  start(): string {
    this.server = Bun.serve({
      hostname: this.host,
      port: 0,
      fetch: async (request) => this.handle(request),
    });
    return this.address;
  }

  stop(): void {
    if (this.server) {
      this.server.stop(true);
      this.server = null;
    }
  }

  get address(): string {
    if (!this.server) throw new Error("CredentialProxy not started - call start() first");
    return `${this.host}:${this.server.port}`;
  }

  isDomainAllowed(target: string): boolean {
    return this.allowDomains.some((pattern) =>
      pattern.startsWith("*.")
        ? target.endsWith(`.${pattern.slice(2)}`)
        : target === pattern,
    );
  }

  private async handle(request: Request): Promise<Response> {
    let target: URL;
    try {
      target = new URL(request.url);
    } catch {
      return new Response("CredentialProxy: invalid URL\n", { status: 400 });
    }

    if (!this.isDomainAllowed(target.hostname)) {
      return new Response(
        `CredentialProxy: domain '${target.hostname}' not in allow_domains\n`,
        { status: 403 },
      );
    }

    const headers = new Headers();
    for (const [key, value] of request.headers) {
      if (["host", "proxy-connection", "content-length"].includes(key.toLowerCase())) {
        continue;
      }
      headers.set(key, value);
    }

    const method = request.method.toUpperCase();
    const init: RequestInit = { method, headers };
    if (method !== "GET" && method !== "HEAD") {
      init.body = await request.arrayBuffer();
    }

    try {
      const upstream = await fetch(target.toString(), init);
      return new Response(upstream.body, {
        status: upstream.status,
        headers: upstream.headers,
      });
    } catch (error) {
      return new Response(
        `CredentialProxy error: ${error instanceof Error ? error.message : String(error)}\n`,
        { status: 502 },
      );
    }
  }
}
