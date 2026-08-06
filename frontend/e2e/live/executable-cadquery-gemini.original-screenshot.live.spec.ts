import fs from "node:fs/promises";
import path from "node:path";
import { expect, test } from "@playwright/test";

const projectId = process.env.VOLUNDR_RESUME_PROJECT_ID ?? "";
const workflowId = process.env.VOLUNDR_RESUME_WORKFLOW_ID ?? "";
const enabled = process.env.VOLUNDR_CAPTURE_EXISTING_CADQUERY_SCREENSHOT === "true";
const screenshotPath = path.resolve("..", "data", "debug-sessions", "executable-cadquery", "gemini-complete-source-01", "original-model.png");

test.skip(!enabled, "Requires the persisted executable-CadQuery workflow ID.");

test("captures the rendered original candidate without provider activity", async ({ page }) => {
  const postRequests: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST") postRequests.push(new URL(request.url()).pathname);
  });
  await page.goto(`/projects/${projectId}/designs/${workflowId}`);
  const panel = page.getByRole("region", { name: "Validated design workflow", exact: true });
  await expect(panel.getByText("Ready to review", { exact: true })).toBeVisible();
  await expect(panel.getByText("mounting_bracket", { exact: true })).toBeVisible();
  await expect(page.locator("canvas").first()).toBeVisible();
  await page.waitForTimeout(2_000);
  await fs.mkdir(path.dirname(screenshotPath), { recursive: true });
  await page.screenshot({ path: screenshotPath, fullPage: true });
  expect(postRequests).toEqual([]);
});
