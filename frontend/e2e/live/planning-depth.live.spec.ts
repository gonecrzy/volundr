import { expect, test, type Page, type TestInfo } from "@playwright/test";
import {
  installBrowserQualityChecks,
  liveEnabled,
  waitForWorkflowOutcome,
} from "./liveEnvironment";

test.skip(!liveEnabled, "Opt-in live suite; set VOLUNDR_RUN_LIVE_E2E=true.");

const CASES = [
  {
    id: "direct-brief-spacer",
    route: "direct_brief",
    request:
      "Create a rectangular spacer plate that is 80 mm wide, 45 mm tall, and 6 mm thick. Add two through-holes, each 5 mm in diameter. Place the first hole center 12 mm from the left edge and centered vertically. Place the second hole center 18 mm from the right edge and centered vertically. Round the four outside corners with a 2 mm radius. Produce one printable part.",
  },
  {
    id: "compact-plan-holder",
    route: "compact_plan",
    request:
      "Create a wall-mounted holder for an 81 mm bottle, suitable for a moving boat, with one-handed removal and two #8 mounting screws.",
  },
  {
    id: "detailed-plan-enclosure",
    route: "detailed_plan",
    request:
      "Create a two-piece enclosure for a 100 mm by 65 mm by 24 mm electronics board. Use a removable lid with four screws, a cable opening on the left side, ventilation on top, and four internal mounting posts.",
  },
] as const;

for (const scenario of CASES) {
  test(`routes the exact ${scenario.id} case proportionally`, async ({ page }, testInfo) => {
    const quality = installBrowserQualityChecks(page);
    await page.goto(`/?testScenario=${scenario.id}`);

    const draftResponsePromise = page.waitForResponse(
      (response) => response.url().endsWith("/api/projects/draft") && response.request().method() === "POST",
    );
    let projectId = "";
    const chatResponsePromise = page.waitForResponse(
      (response) => {
        const path = new URL(response.url()).pathname;
        return path.endsWith(`/api/projects/${projectId}/chat`) && response.request().method() === "POST";
      },
    );
    await page.getByLabel("AI chat message").fill(scenario.request);
    await page.getByRole("button", { name: "Send", exact: true }).click();
    projectId = (await (await draftResponsePromise).json()).id as string;
    const chatResponse = await chatResponsePromise;
    const chat = await chatResponse.json();
    expect(chat.planning_depth, "selected planning route").toBe(scenario.route);
    expect(chat.input_required, "exact cases do not need an approval or clarification click").toBe(false);

    const specificationResponse = await page.request.get(`/api/projects/${projectId}/design-specification`);
    expect(specificationResponse.ok(), "requirements artifact").toBeTruthy();
    const specification = await specificationResponse.json();
    expect(specification.outcome).toBe("generation_ready");

    const planResponse = await page.request.get(`/api/projects/${projectId}/design-plan`);
    if (!planResponse.ok()) {
      await collectPlanningEvidence(page, projectId, scenario.id, "planning_failure", testInfo, quality.snapshot());
      await quality.assertClean();
      return;
    }
    const plan = await planResponse.json();
    if (scenario.route === "direct_brief") {
      expect(plan.schema_version).toBe("cad-brief-v1");
    } else if (scenario.route === "compact_plan") {
      expect(plan.schema_version).toBe("compact-cad-plan-v1");
    } else {
      expect(plan.schema_version).not.toBe("cad-brief-v1");
      expect(plan.schema_version).not.toBe("compact-cad-plan-v1");
    }

    const outcome = await waitForWorkflowOutcome(page);
    if (outcome === "candidate") {
      await expect(page.getByRole("heading", { name: /Current working version|New version/, exact: true })).toBeVisible();
    } else {
      await expect(page.getByText(/failed|could not|unable|mismatch|rejected|blocked|unchanged/i).first()).toBeVisible();
    }
    await collectPlanningEvidence(page, projectId, scenario.id, outcome, testInfo, quality.snapshot());
    await quality.assertClean();
  });
}

async function collectPlanningEvidence(
  page: Page,
  projectId: string,
  scenario: string,
  finalState: string,
  testInfo: TestInfo,
  browserQuality: ReturnType<ReturnType<typeof installBrowserQualityChecks>["snapshot"]>,
): Promise<void> {
  const runsResponse = await page.request.get(`/api/projects/${projectId}/workflow-runs`);
  const attemptsResponse = await page.request.get(`/api/projects/${projectId}/generation-attempts`);
  const revisionsResponse = await page.request.get(`/api/projects/${projectId}/revisions`);
  expect(runsResponse.ok(), "workflow run listing").toBeTruthy();
  expect(attemptsResponse.ok(), "generation attempt listing").toBeTruthy();
  expect(revisionsResponse.ok(), "revision listing").toBeTruthy();
  const runs = await runsResponse.json();
  const attempts = await attemptsResponse.json();
  const revisions = await revisionsResponse.json();
  expect(attempts.some((attempt: { provider: string }) => attempt.provider === "gemini_api")).toBeTruthy();
  const latestRevision = revisions.at(-1);
  const outputs = latestRevision
    ? await page.request.get(`/api/revisions/${String(latestRevision.id)}/outputs`).then((response) => response.ok() ? response.json() : [])
    : [];
  await testInfo.attach(`${scenario}-live-evidence.json`, {
    body: JSON.stringify({ scenario, project_id: projectId, final_state: finalState, runs, attempts, revisions, outputs, browser_quality: browserQuality }, null, 2),
    contentType: "application/json",
  });
}
