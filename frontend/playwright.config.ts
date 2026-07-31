import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  use: {
    baseURL: "http://127.0.0.1:4173",
    trace: "retain-on-failure",
    ...devices["Desktop Chrome"],
  },
  webServer: [
    {
      command:
        "rtk env PYTHONPATH=../backend VOLUNDR_E2E_DATA_DIR=/tmp/volundr-playwright-fixture ../backend/.venv/bin/python -m app.testing.e2e_fixture_server",
      reuseExistingServer: true,
      url: "http://127.0.0.1:8000/health",
    },
    {
      command: "npm run dev -- --host 127.0.0.1 --port 4173",
      reuseExistingServer: true,
      url: "http://127.0.0.1:4173",
    },
  ],
});
