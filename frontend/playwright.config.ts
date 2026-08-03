import { execFileSync } from "node:child_process";
import { defineConfig, devices } from "@playwright/test";
import { resolvePlaywrightPorts } from "./playwrightPorts";

const ports = resolvePlaywrightPorts("VOLUNDR_E2E_PORT", "VOLUNDR_E2E_WEB_PORT");
const viewportWidth = Number(process.env.VOLUNDR_E2E_VIEWPORT_WIDTH);
const viewportHeight = Number(process.env.VOLUNDR_E2E_VIEWPORT_HEIGHT);
const configuredViewport =
  Number.isFinite(viewportWidth) && Number.isFinite(viewportHeight)
    ? { width: viewportWidth, height: viewportHeight }
    : undefined;
const buildSha = process.env.VITE_BUILD_SHA ?? execFileSync("git", ["rev-parse", "HEAD"], { encoding: "utf8" }).trim();
const buildTimestamp = process.env.VITE_BUILD_TIMESTAMP ?? execFileSync("git", ["show", "-s", "--format=%cI", "HEAD"], { encoding: "utf8" }).trim();
const buildDirty = process.env.VITE_BUILD_DIRTY ?? (execFileSync("git", ["status", "--porcelain"], { encoding: "utf8" }).trim() ? "true" : "false");
const buildBranch = process.env.VOLUNDR_BUILD_BRANCH ?? execFileSync("git", ["branch", "--show-current"], { encoding: "utf8" }).trim();

export default defineConfig({
  testDir: "./e2e",
  testIgnore: ["**/live/**"],
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
        `VOLUNDR_E2E_PORT=${ports.apiPort} VOLUNDR_BUILD_GIT_SHA=${buildSha} VOLUNDR_BUILD_BRANCH=${buildBranch} VOLUNDR_BUILD_TIMESTAMP=${buildTimestamp} VOLUNDR_BUILD_DIRTY=${buildDirty} VOLUNDR_WORKER_BUILD_GIT_SHA=${buildSha} VOLUNDR_WORKER_BUILD_TIMESTAMP=${buildTimestamp} VOLUNDR_WORKER_BUILD_DIRTY=${buildDirty} ./scripts/run-fixture-backend.sh`,
      reuseExistingServer: false,
      url: `http://${ports.host}:${ports.apiPort}/health`,
    },
    {
      command: `VITE_VOLUNDR_CHAT_FIRST=${process.env.VITE_VOLUNDR_CHAT_FIRST ?? "true"} VITE_BUILD_SHA=${buildSha} VITE_BUILD_TIMESTAMP=${buildTimestamp} VITE_BUILD_DIRTY=${buildDirty} VOLUNDR_E2E_PORT=${ports.apiPort} VOLUNDR_VITE_HOST=${ports.host} VOLUNDR_VITE_PORT=${ports.webPort} npm run dev -- --host ${ports.host} --port ${ports.webPort}`,
      reuseExistingServer: false,
      url: `http://${ports.host}:${ports.webPort}`,
    },
  ],
});
