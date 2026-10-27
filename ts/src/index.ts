#!/usr/bin/env bun
import { parseArgs } from "node:util";
import {
  HELP,
  VERSION,
  initConfig,
  resolveWorkdir,
  runPrint,
  runRepl,
} from "./cli";

const { values, positionals } = parseArgs({
  args: process.argv.slice(2),
  options: {
    init: { type: "boolean", default: false },
    print: { type: "boolean", short: "p", default: false },
    workdir: { type: "string", short: "w" },
    "session-id": { type: "string" },
    "resume-last": { type: "boolean", default: false },
    help: { type: "boolean", short: "h", default: false },
    version: { type: "boolean", short: "v", default: false },
  },
  allowPositionals: true,
});

if (values.help) {
  process.stdout.write(HELP);
  process.exit(0);
}

if (values.version) {
  process.stdout.write(`${VERSION}\n`);
  process.exit(0);
}

if (values.init) {
  process.exit(await initConfig());
}

const workdir = resolveWorkdir(values.workdir);
const options = {
  workdir,
  ...(values["session-id"] ? { sessionId: values["session-id"] } : {}),
  ...(values["resume-last"] ? { resumeLast: true } : {}),
};

try {
  if (values.print) {
    const prompt = positionals.join(" ").trim();
    if (!prompt) {
      process.stderr.write("Error: --print requires a prompt argument.\n");
      process.exit(1);
    }
    process.exit(await runPrint(prompt, options));
  }
  process.exit(await runRepl(options));
} catch (error) {
  const message = error instanceof Error ? error.message : String(error);
  process.stderr.write(`Error: ${message}\n`);
  process.exit(1);
}
