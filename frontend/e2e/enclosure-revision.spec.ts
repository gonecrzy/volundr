import { expect, test } from "@playwright/test";

test.skip(
  (process.env.VITE_VOLUNDR_CHAT_FIRST ?? "true").toLowerCase() !== "true",
  "chat-first workflow suite; run with VITE_VOLUNDR_CHAT_FIRST=true",
);

test("enclosure lid chat revision persists its Revision Plan and auto-promotes", async ({ page }) => {
  const seeded = await page.request.post("/api/test-fixture/scenarios/revise-enclosure-lid");
  expect(seeded.status()).toBe(201);
  const fixture = await seeded.json();
  const projectId = fixture.project.id as string;

  await page.goto("/?testScenario=revise-enclosure-lid");
  await page.getByRole("button", { name: "Projects" }).click();
  await page.getByRole("button", { name: fixture.project.name }).click();
  await expect(page.getByRole("heading", { name: "Current working version" })).toBeVisible();

  await page.getByLabel("AI chat message").fill("Add a recessed finger pull to the lid only. Keep the enclosure body and lid fit unchanged.");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByRole("heading", { name: "Current working version" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Review planned changes" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Accept new version" })).toHaveCount(0);

  const summary = await page.request.get(`/api/test-fixture/projects/${projectId}/summary`).then((response) => response.json());
  expect(summary.provider_calls).toEqual([
    "requirement_extraction",
    "design_plan_generation",
    "source_generation",
    "revision_plan_generation",
    "component_revision",
  ]);
  expect(summary.revision_plans).toEqual(expect.arrayContaining([
    expect.objectContaining({ review_state: "approved" }),
  ]));
  expect(summary.revisions.filter((revision: { is_accepted: boolean }) => revision.is_accepted)).toHaveLength(2);
  expect(summary.workflow_event_types).toEqual(expect.arrayContaining([
    "revision_plan.approved",
    "candidate.accepted",
    "working_version.promoted",
  ]));

  const bundleRun = summary.workflow_runs.find((run: { workflow_type: string }) => run.workflow_type === "component_revision");
  expect(bundleRun).toBeTruthy();
  const bundle = await page.request.get(`/api/workflow-runs/${bundleRun.id}/debug-bundle.zip`);
  expect(bundle.status()).toBe(200);
  expect((await bundle.body()).toString("latin1")).toContain("revision_plan");
});
