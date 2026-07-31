import { expect, test } from "@playwright/test";
import {
  advanceToGeneration,
  answerRequirementClarificationIfShown,
  collectLiveEvidence,
  installBrowserQualityChecks,
  liveEnabled,
  waitForWorkflowOutcome,
} from "./liveEnvironment";

test.describe("live Gemini intent-first holder", () => {
  test.skip(!liveEnabled, "Opt-in live suite; set VOLUNDR_RUN_LIVE_E2E=true.");

  test("keeps fit requirements separate from proposed holder dimensions", async ({ page }, testInfo) => {
    const quality = installBrowserQualityChecks(page);
    let projectId = "";

    await page.goto("/?testScenario=intent-first-holder-live");
    const draftResponsePromise = page.waitForResponse(
      (response) => response.url().endsWith("/api/projects/draft") && response.request().method() === "POST",
    );
    await page.getByLabel("AI chat message").fill(
      "Make a printable holder for a rectangular PCB that is 70 mm wide and 45 mm deep. It should hold the board securely with a removable top. Propose noncritical dimensions and keep the design suitable for FDM printing.",
    );
    await page.getByRole("button", { name: "Send", exact: true }).click();
    projectId = (await (await draftResponsePromise).json()).id as string;

    const clarification = await answerRequirementClarificationIfShown(page);
    expect(clarification.count, "clarification remains bounded").toBeLessThanOrEqual(5);
    if (!clarification.ready) {
      await expect(page.getByRole("button", { name: "Review proposed design", exact: true })).toBeVisible();
    }
    await expect(page.getByText("Volundr proposes", { exact: true })).toBeVisible();
    await advanceToGeneration(page);

    const outcome = await waitForWorkflowOutcome(page);
    if (outcome === "candidate") {
      await expect(page.getByRole("heading", { name: "New version", exact: true })).toBeVisible();
      await expect(page.locator('[aria-label="Candidate review"]').getByRole("heading", { name: /Printable parts/ }).first()).toBeVisible();
    } else {
      await expect(page.getByText(/failed|could not|unable|did not implement|mismatch|rejected/i).first()).toBeVisible();
    }

    await collectLiveEvidence(page, projectId, "intent-first-holder-live", outcome, testInfo, quality.snapshot());
    await quality.assertClean();
  });
});
