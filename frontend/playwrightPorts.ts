import { execFileSync } from "node:child_process";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

export type PlaywrightPorts = {
  host: "127.0.0.1";
  apiPort: number;
  webPort: number;
};

export function resolvePlaywrightPorts(apiEnv: string, webEnv: string): PlaywrightPorts {
  const scriptPath = fileURLToPath(new URL("./scripts/live-harness.mjs", import.meta.url));
  const configuredApiPort = process.env[apiEnv] ?? "0";
  const configuredWebPort = process.env[webEnv] ?? "0";
  const filePath = process.env.VOLUNDR_PLAYWRIGHT_PORT_FILE ?? join(
    tmpdir(),
    `volundr-playwright-ports-${apiEnv}-${webEnv}.json`,
  );
  try {
    if (configuredApiPort !== "0" || configuredWebPort !== "0") {
      return runPortHelper(process.execPath, scriptPath, configuredApiPort, configuredWebPort);
    }
    if (existsSync(filePath)) {
      try {
        const saved = JSON.parse(readFileSync(filePath, "utf8")) as PlaywrightPorts & { ownerPid?: number };
        if (saved.ownerPid && processIsAlive(saved.ownerPid)) {
          return saved;
        }
        const validated = runPortHelper(process.execPath, scriptPath, String(saved.apiPort), String(saved.webPort));
        const owned = { ...validated, ownerPid: process.pid };
        writeFileSync(filePath, `${JSON.stringify(owned)}\n`, { mode: 0o600 });
        return owned;
      } catch {
        // A stale or occupied saved pair is never reused; allocate a new pair.
      }
    }
    const ports = runPortHelper(process.execPath, scriptPath, "0", "0");
    writeFileSync(filePath, `${JSON.stringify({ ...ports, ownerPid: process.pid })}\n`, { mode: 0o600 });
    return ports;
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    throw new Error(`Playwright ${apiEnv}/${webEnv} port preflight failed: ${detail}`);
  }
}

function processIsAlive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

function runPortHelper(
  nodePath: string,
  scriptPath: string,
  apiPort: string,
  webPort: string,
): PlaywrightPorts {
  return JSON.parse(
    execFileSync(nodePath, [scriptPath, apiPort, webPort], {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
    }),
  ) as PlaywrightPorts;
}
