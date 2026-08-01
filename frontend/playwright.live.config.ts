import { defineConfig, devices } from "@playwright/test";
import { resolvePlaywrightPorts } from "./playwrightPorts";

const liveEnabled = process.env.VOLUNDR_RUN_LIVE_E2E === "true";
if (liveEnabled && process.env.GEMINI_API_KEY) {
  throw new Error(
    "The live E2E wrapper must remove GEMINI_API_KEY before starting Playwright. Use npm run test:e2e:live.",
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

export default defineConfig({
  testDir: "./e2e/live",
  workers: 1,
  fullyParallel: false,
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
      command: `VITE_VOLUNDR_CHAT_FIRST=${process.env.VITE_VOLUNDR_CHAT_FIRST ?? "true"} VOLUNDR_E2E_PORT=${ports.apiPort} VOLUNDR_VITE_HOST=${ports.host} VOLUNDR_VITE_PORT=${ports.webPort} npm run dev -- --host ${ports.host} --port ${ports.webPort}`,
      reuseExistingServer: false,
      url: `http://${ports.host}:${ports.webPort}`,
      timeout: 120_000,
    },
  ],
});
