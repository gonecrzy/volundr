import { expect, test } from "@playwright/test";
import {
  advanceToGeneration,
  collectLiveEvidence,
  installBrowserQualityChecks,
  liveEnabled,
  waitForWorkflowOutcome,
} from "./liveEnvironment";

test.describe("live Gemini bottle holder", () => {
  test.skip(!liveEnabled, "Opt-in live suite; set VOLUNDR_RUN_LIVE_E2E=true.");

  test("runs the exact functional bottle-holder request", async ({ page }, testInfo) => {
    const quality = installBrowserQualityChecks(page);
    let projectId = "";

    await page.goto("/?testScenario=bottle-holder-live");
    const draftResponsePromise = page.waitForResponse(
      (response) => response.url().endsWith("/api/projects/draft") && response.request().method() === "POST",
    );
    await page.getByLabel("AI chat message").fill(
      "Create a wall-mounted holder for an 81 mm bottle, suitable for a moving boat, with one-handed removal and two #8 mounting screws.",
    );
    await page.getByRole("button", { name: "Send", exact: true }).click();
    projectId = (await (await draftResponsePromise).json()).id as string;

    await expect(page.locator('[aria-label="Design requirements"]')).toBeVisible();
    await expect(page.getByText("Volundr proposes", { exact: true })).toBeVisible();
    await advanceToGeneration(page);

    const outcome = await waitForWorkflowOutcome(page);
    console.log(`bottle-holder live outcome=${outcome} project=${projectId}`);
    if (outcome === "candidate") {
      await expect(page.getByRole("heading", { name: "New version", exact: true })).toBeVisible();
      await expect(page.getByText(/functional checks/i).first()).toBeVisible();
    } else {
      await expect(page.getByText(/failed|could not|unable|mismatch|rejected|blocked/i).first()).toBeVisible();
    }

    await collectLiveEvidence(page, projectId, "bottle-holder-live", outcome, testInfo, quality.snapshot());
    await quality.assertClean();
  });
});
