import { defineConfig, devices } from "@playwright/test";

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

const apiPort = process.env.VOLUNDR_LIVE_API_PORT ?? "8200";
const webPort = process.env.VOLUNDR_LIVE_WEB_PORT ?? "4273";
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
    baseURL: `http://127.0.0.1:${webPort}`,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    ...devices["Desktop Chrome"],
  },
  webServer: [
    {
      command:
        `cd ${repoRoot}/backend && . "$VOLUNDR_LIVE_ENV_FILE" && ` +
        `VOLUNDR_AI_PROVIDER=gemini_api VOLUNDR_DATA_DIR="${dataDir}/data" ` +
        `VOLUNDR_CAD_WORKSPACE_DIR="${dataDir}/data/jobs" PYTHONPATH=. ` +
        `../backend/.venv/bin/alembic upgrade head && ` +
        `exec env VOLUNDR_AI_PROVIDER=gemini_api VOLUNDR_DATA_DIR="${dataDir}/data" ` +
        `VOLUNDR_CAD_WORKSPACE_DIR="${dataDir}/data/jobs" PYTHONPATH=. ` +
        `../backend/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port ${apiPort} ` +
        `>"${dataDir}/api.log" 2>&1`,
      reuseExistingServer: false,
      url: `http://127.0.0.1:${apiPort}/health`,
      timeout: 120_000,
    },
    {
      command: `VOLUNDR_E2E_PORT=${apiPort} npm run dev -- --host 127.0.0.1 --port ${webPort}`,
      reuseExistingServer: false,
      url: `http://127.0.0.1:${webPort}`,
      timeout: 120_000,
    },
  ],
});
