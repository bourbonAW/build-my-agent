import type { ObservabilityConfig } from "../config";
import { BourbonTracer } from "./tracer";

function appendTracePath(endpoint: string): string {
  const stripped = endpoint.replace(/\/+$/, "");
  return stripped.endsWith("/v1/traces") ? stripped : `${stripped}/v1/traces`;
}

function resolveTraceEndpoint(config: ObservabilityConfig): string {
  if (process.env.OTEL_EXPORTER_OTLP_TRACES_ENDPOINT) {
    return process.env.OTEL_EXPORTER_OTLP_TRACES_ENDPOINT;
  }
  if (process.env.OTEL_EXPORTER_OTLP_ENDPOINT) {
    return appendTracePath(process.env.OTEL_EXPORTER_OTLP_ENDPOINT);
  }
  return config.otlpEndpoint ? appendTracePath(config.otlpEndpoint) : "";
}

function resolveHeaders(config: ObservabilityConfig): Record<string, string> {
  const headers = { ...config.otlpHeaders };
  const raw =
    process.env.OTEL_EXPORTER_OTLP_TRACES_HEADERS ??
    process.env.OTEL_EXPORTER_OTLP_HEADERS ??
    "";
  for (const pair of raw.split(",")) {
    const index = pair.indexOf("=");
    if (index === -1) continue;
    headers[pair.slice(0, index).trim()] = pair.slice(index + 1).trim();
  }
  return headers;
}

interface ProviderLike {
  shutdown(): Promise<void>;
  forceFlush(options?: { timeoutMillis?: number }): Promise<unknown>;
}

export class ObservabilityManager {
  private readonly tracer: BourbonTracer;
  private provider: ProviderLike | null = null;
  private shutdownCalled = false;

  constructor(config: ObservabilityConfig) {
    this.tracer = this.build(config);
  }

  getTracer(): BourbonTracer {
    return this.tracer;
  }

  async shutdown(timeoutSeconds = 2): Promise<void> {
    if (this.shutdownCalled) return;
    this.shutdownCalled = true;
    if (!this.provider) return;

    const provider = this.provider;
    this.provider = null;
    await Promise.race([
      provider.shutdown(),
      Bun.sleep(timeoutSeconds * 1000),
    ]);
  }

  async forceFlush(timeoutSeconds = 2): Promise<boolean> {
    if (!this.provider) return true;
    try {
      await this.provider.forceFlush({
        timeoutMillis: Math.max(0, timeoutSeconds * 1000),
      });
      return true;
    } catch {
      return false;
    }
  }

  private build(config: ObservabilityConfig): BourbonTracer {
    if (!config.enabled) return new BourbonTracer(null);
    const endpoint = resolveTraceEndpoint(config);
    if (!endpoint) return new BourbonTracer(null);

    const serviceName = process.env.OTEL_SERVICE_NAME ?? config.serviceName;
    const headers = resolveHeaders(config);

    // The SDK is loaded lazily so the default CLI path stays light.
    const ready = (async () => {
      try {
        const [{ NodeTracerProvider }, { BatchSpanProcessor }, { OTLPTraceExporter }, { resourceFromAttributes }, { trace }] =
          await Promise.all([
            import("@opentelemetry/sdk-trace-node"),
            import("@opentelemetry/sdk-trace-base"),
            import("@opentelemetry/exporter-trace-otlp-proto"),
            import("@opentelemetry/resources"),
            import("@opentelemetry/api"),
          ]);

        const provider = new NodeTracerProvider({
          resource: resourceFromAttributes({ "service.name": serviceName }),
          spanProcessors: [
            new BatchSpanProcessor(
              new OTLPTraceExporter({ url: endpoint, headers }),
              { maxQueueSize: 2048 },
            ),
          ],
        });
        provider.register();
        this.provider = provider as unknown as ProviderLike;
        return new BourbonTracer(trace.getTracer("bourbon"));
      } catch {
        return new BourbonTracer(null);
      }
    })();

    // Avoid making agent construction async: spans start no-op until the SDK resolves.
    const tracer: BourbonTracer = new BourbonTracer(null);
    void ready.then((actual) => {
      Object.assign(tracer, actual);
    });
    return tracer;
  }
}
