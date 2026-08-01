import { expect, test } from "@playwright/test";
import {
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
    const chatResponsePromise = page.waitForResponse(
      (response) => response.url().endsWith(`/api/projects/${projectId}/chat`) && response.request().method() === "POST",
    );
    await page.getByRole("button", { name: "Send", exact: true }).click();
    projectId = (await (await draftResponsePromise).json()).id as string;
    await chatResponsePromise;

    const specificationResponse = await page.request.get(`/api/projects/${projectId}/design-specification`);
    expect(specificationResponse.ok(), "requirements were created").toBeTruthy();
    const specification = await specificationResponse.json();
    expect(specification.outcome).toBe("generation_ready");

    const planResponse = await page.request.get(`/api/projects/${projectId}/design-plan`);
    const planBody = await planResponse.text();
    expect(planResponse.ok(), `Design Plan was created (${planResponse.status()}): ${planBody}`).toBeTruthy();
    const plan = JSON.parse(planBody);
    expect(plan.review_state).toMatch(/approved|ready|pending_review/);

    const outcome = await waitForWorkflowOutcome(page);
    console.log(`bottle-holder live outcome=${outcome} project=${projectId}`);
    if (outcome === "candidate") {
      await expect(page.getByRole("heading", { name: /Current working version|New version/, exact: true })).toBeVisible();
      await expect(page.getByText(/functional checks/i).first()).toBeVisible();
    } else {
      await expect(page.getByText(/failed|could not|unable|mismatch|rejected|blocked|unchanged/i).first()).toBeVisible();
      await expect(page.getByText(/current working version is unchanged/i)).toBeVisible();
    }

    await collectLiveEvidence(page, projectId, "bottle-holder-live", outcome, testInfo, quality.snapshot());
    await quality.assertClean();
  });
});
