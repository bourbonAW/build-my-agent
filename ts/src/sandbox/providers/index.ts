import type { SandboxDockerConfig } from "../../config";
import type { SandboxProvider } from "../runtime";
import { BwrapProvider } from "./bubblewrap";
import { DockerProvider } from "./docker";
import { LocalProvider } from "./local";
import { SeatbeltProvider } from "./seatbelt";

export class SandboxProviderNotFoundError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "SandboxProviderNotFoundError";
  }
}

export function selectProvider(
  name: string,
  dockerConfig: Partial<SandboxDockerConfig> = {},
): SandboxProvider {
  const normalized = name.toLowerCase();

  if (normalized === "bubblewrap") {
    if (!BwrapProvider.isAvailable()) {
      throw new SandboxProviderNotFoundError(
        'bubblewrap not found. Install it or set provider = "auto"',
      );
    }
    return new BwrapProvider();
  }

  if (normalized === "seatbelt") {
    if (!SeatbeltProvider.isAvailable()) {
      throw new SandboxProviderNotFoundError('seatbelt requires macOS. Set provider = "auto"');
    }
    return new SeatbeltProvider();
  }

  if (normalized === "docker") {
    if (!DockerProvider.isAvailable()) {
      throw new SandboxProviderNotFoundError(
        'docker daemon not available. Ensure Docker is running or set provider = "auto"',
      );
    }
    return new DockerProvider(dockerConfig);
  }

  if (normalized === "local") return new LocalProvider();

  if (normalized === "auto") {
    if (process.platform === "linux" && BwrapProvider.isAvailable()) {
      return new BwrapProvider();
    }
    if (process.platform === "darwin" && SeatbeltProvider.isAvailable()) {
      return new SeatbeltProvider();
    }
    return new LocalProvider();
  }

  throw new SandboxProviderNotFoundError(`Sandbox provider not found: ${name}`);
}

export { LocalProvider } from "./local";
export { SeatbeltProvider } from "./seatbelt";
export { BwrapProvider } from "./bubblewrap";
export { DockerProvider } from "./docker";
