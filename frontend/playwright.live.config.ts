import { execFileSync } from "node:child_process";
import { defineConfig, devices } from "@playwright/test";
import { resolvePlaywrightPorts } from "./playwrightPorts";

const liveEnabled = process.env.VOLUNDR_RUN_LIVE_E2E === "true";
const credentialNames = [
  "GEMINI_API_KEY",
  "GEMINI_API_KEY_2",
  "VOLUNDR_GEMINI_PRIMARY_API_KEY",
  "VOLUNDR_GEMINI_FALLBACK_API_KEY",
];
if (liveEnabled && credentialNames.some((name) => process.env[name])) {
  throw new Error(
    "The live E2E wrapper must remove Gemini credentials before starting Playwright. Use npm run test:e2e:live.",
  );
}
if (liveEnabled && !process.env.VOLUNDR_LIVE_ENV_FILE) {
  throw new Error(
    "Live E2E requires the backend-only environment wrapper. Use VOLUNDR_RUN_LIVE_E2E=true npm run test:e2e:live.",
  );
}

const ports = resolvePlaywrightPorts("VOLUNDR_LIVE_API_PORT", "VOLUNDR_LIVE_WEB_PORT");
const dataDir = process.env.VOLUNDR_LIVE_DATA_DIR ?? "/tmp/volundr-live-e2e-unconfigured";
const repoRoot = "..";
const buildSha = process.env.VITE_BUILD_SHA ?? execFileSync("git", ["rev-parse", "HEAD"], { encoding: "utf8" }).trim();
const buildTimestamp = process.env.VITE_BUILD_TIMESTAMP ?? execFileSync("git", ["show", "-s", "--format=%cI", "HEAD"], { encoding: "utf8" }).trim();
const buildDirty = process.env.VITE_BUILD_DIRTY ?? (execFileSync("git", ["status", "--porcelain"], { encoding: "utf8" }).trim() ? "true" : "false");
const buildReleaseLabel = process.env.VITE_BUILD_RELEASE_LABEL ?? "";

export default defineConfig({
  testDir: "./e2e/live",
  workers: 1,
  fullyParallel: false,
  retries: 0,
  timeout: 240_000,
  expect: { timeout: 60_000 },
  outputDir: "test-results/live",
  use: {
    baseURL: `http://${ports.host}:${ports.webPort}`,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    ...devices["Desktop Chrome"],
  },
  webServer: [
    {
      command:
        `VOLUNDR_LIVE_API_PORT=${ports.apiPort} ./scripts/run-live-api.sh`,
      reuseExistingServer: false,
      url: `http://${ports.host}:${ports.apiPort}/health`,
      timeout: 120_000,
    },
    {
      command: `VITE_VOLUNDR_CHAT_FIRST=${process.env.VITE_VOLUNDR_CHAT_FIRST ?? "true"} VITE_VOLUNDR_VALIDATED_CADQUERY_FLOW_ENABLED=${process.env.VITE_VOLUNDR_VALIDATED_CADQUERY_FLOW_ENABLED ?? "false"} VITE_VOLUNDR_EXECUTABLE_CADQUERY_FLOW_ENABLED=${process.env.VITE_VOLUNDR_EXECUTABLE_CADQUERY_FLOW_ENABLED ?? "false"} VITE_BUILD_SHA=${buildSha} VITE_BUILD_TIMESTAMP=${buildTimestamp} VITE_BUILD_DIRTY=${buildDirty} VITE_BUILD_RELEASE_LABEL=${buildReleaseLabel} VOLUNDR_E2E_PORT=${ports.apiPort} VOLUNDR_VITE_HOST=${ports.host} VOLUNDR_VITE_PORT=${ports.webPort} npm run dev -- --host ${ports.host} --port ${ports.webPort}`,
      reuseExistingServer: false,
      url: `http://${ports.host}:${ports.webPort}`,
      timeout: 120_000,
    },
  ],
});
