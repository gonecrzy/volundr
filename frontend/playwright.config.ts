import { defineConfig, devices } from "@playwright/test";
import { resolvePlaywrightPorts } from "./playwrightPorts";

const ports = resolvePlaywrightPorts("VOLUNDR_E2E_PORT", "VOLUNDR_E2E_WEB_PORT");
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
    baseURL: `http://${ports.host}:${ports.webPort}`,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    ...devices["Desktop Chrome"],
    ...(configuredViewport ? { viewport: configuredViewport } : {}),
  },
  webServer: [
    {
      command:
        `VOLUNDR_E2E_PORT=${ports.apiPort} ./scripts/run-fixture-backend.sh`,
      reuseExistingServer: false,
      url: `http://${ports.host}:${ports.apiPort}/health`,
    },
    {
      command: `VITE_VOLUNDR_CHAT_FIRST=${process.env.VITE_VOLUNDR_CHAT_FIRST ?? "true"} VOLUNDR_E2E_PORT=${ports.apiPort} VOLUNDR_VITE_HOST=${ports.host} VOLUNDR_VITE_PORT=${ports.webPort} npm run dev -- --host ${ports.host} --port ${ports.webPort}`,
      reuseExistingServer: false,
      url: `http://${ports.host}:${ports.webPort}`,
    },
  ],
});
