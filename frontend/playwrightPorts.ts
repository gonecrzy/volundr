import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";

export type PlaywrightPorts = {
  host: "127.0.0.1";
  apiPort: number;
  webPort: number;
};

export function resolvePlaywrightPorts(apiEnv: string, webEnv: string): PlaywrightPorts {
  const scriptPath = fileURLToPath(new URL("./scripts/live-harness.mjs", import.meta.url));
  try {
    return JSON.parse(
      execFileSync(
        process.execPath,
        [scriptPath, process.env[apiEnv] ?? "0", process.env[webEnv] ?? "0"],
        { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] },
      ),
    ) as PlaywrightPorts;
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    throw new Error(`Playwright ${apiEnv}/${webEnv} port preflight failed: ${detail}`);
  }
}
