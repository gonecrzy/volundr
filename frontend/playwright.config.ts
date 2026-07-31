import { defineConfig, devices } from "@playwright/test";

const e2eApiPort = process.env.VOLUNDR_E2E_PORT ?? "8000";
const e2eWebPort = process.env.VOLUNDR_E2E_WEB_PORT ?? "4173";
const viewportWidth = Number(process.env.VOLUNDR_E2E_VIEWPORT_WIDTH);
const viewportHeight = Number(process.env.VOLUNDR_E2E_VIEWPORT_HEIGHT);
const configuredViewport =
  Number.isFinite(viewportWidth) && Number.isFinite(viewportHeight)
    ? { width: viewportWidth, height: viewportHeight }
    : undefined;

export default defineConfig({
  testDir: "./e2e",
  workers: 1,
  timeout: 30_000,
  use: {
    baseURL: `http://127.0.0.1:${e2eWebPort}`,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    ...devices["Desktop Chrome"],
    ...(configuredViewport ? { viewport: configuredViewport } : {}),
  },
  webServer: [
    {
      command:
        `fixture_root=$(mktemp -d /tmp/volundr-playwright-fixture.XXXXXX) && exec rtk env PYTHONPATH=../backend VOLUNDR_E2E_DATA_DIR=$fixture_root VOLUNDR_E2E_PORT=${e2eApiPort} ../backend/.venv/bin/python -m app.testing.e2e_fixture_server`,
      reuseExistingServer: false,
      url: `http://127.0.0.1:${e2eApiPort}/health`,
    },
    {
      command: `npm run dev -- --host 127.0.0.1 --port ${e2eWebPort}`,
      reuseExistingServer: true,
      url: `http://127.0.0.1:${e2eWebPort}`,
    },
  ],
});
