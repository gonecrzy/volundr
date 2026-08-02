import { expect, test } from "@playwright/test";
import {
  advanceToGeneration,
  collectLiveEvidence,
  installBrowserQualityChecks,
  liveEnabled,
  waitForWorkflowOutcome,
} from "./liveEnvironment";

test.describe("live Gemini explicit mounting plate", () => {
  test.skip(!liveEnabled, "Opt-in live suite; set VOLUNDR_RUN_LIVE_E2E=true.");

  test("completes the real explicit-part lifecycle", async ({ page }, testInfo) => {
    const quality = installBrowserQualityChecks(page);
    let projectId = "";

    await page.goto("/?testScenario=explicit-part-live");
    const draftResponsePromise = page.waitForResponse(
      (response) => response.url().endsWith("/api/projects/draft") && response.request().method() === "POST",
    );
    await page.getByLabel("AI chat message").fill(
      "Create a rectangular mounting plate 80 mm wide, 50 mm deep, and 3 mm thick with four 4 mm diameter corner mounting holes. It must be one flat printable part.",
    );
    await page.getByRole("button", { name: "Send", exact: true }).click();
    projectId = (await (await draftResponsePromise).json()).id as string;

    await expect(page.locator('[aria-label="Design requirements"]')).toBeVisible();
    await expect(page.getByText("Your requirements", { exact: true })).toBeVisible();
    await expect(page.getByText("Volundr proposes", { exact: true })).toBeVisible();
    await expect(page.getByText("Clarification needed", { exact: true })).toHaveCount(0);

    await advanceToGeneration(page);
    const outcome = await waitForWorkflowOutcome(page);
    if (outcome === "candidate") {
      await expect(page.getByRole("heading", { name: "New version", exact: true })).toBeVisible();
      await expect(page.locator('[aria-label="Candidate review"]').getByRole("heading", { name: /Printable parts/ }).first()).toBeVisible();
      const accept = page.getByRole("button", { name: "Accept new version", exact: true });
      if (await accept.isEnabled()) {
        await accept.click();
        await expect(page.getByRole("heading", { name: "Current design", exact: true })).toBeVisible();
      }
    } else {
      await expect(page.getByText(/failed|could not|unable|did not implement|mismatch|rejected/i).first()).toBeVisible();
    }

    await collectLiveEvidence(page, projectId, "explicit-part-live", outcome, testInfo, quality.snapshot());
    await quality.assertClean();
  });
});
