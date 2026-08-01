import { expect, test, type Page } from "@playwright/test";

test.skip(
  (process.env.VITE_VOLUNDR_CHAT_FIRST ?? "true").toLowerCase() === "true",
  "staged workflow suite; run with VITE_VOLUNDR_CHAT_FIRST=false",
);

async function openEnclosure(page: Page, projectName: string) {
  await page.goto("/?testScenario=revise-enclosure-lid");
  await page.getByRole("button", { name: "Projects" }).click();
  await page.getByRole("button", { name: projectName }).last().click();
}

test("revision generation is gated until plan approval and duplicate requests stay idempotent", async ({ page }) => {
  const seeded = await page.request.post("/api/test-fixture/scenarios/revise-enclosure-lid");
  expect(seeded.status()).toBe(201);
  const fixture = await seeded.json();
  const projectId = fixture.project.id as string;
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("response", (response) => {
    if (response.status() >= 400 && !response.url().includes("/generate")) {
      errors.push(`${response.status()} ${response.url()}`);
    }
  });

  await openEnclosure(page, fixture.project.name);
  await page.getByLabel("AI chat message").fill(
    "Add a recessed finger pull to the lid only. Keep the enclosure body and lid fit unchanged.",
  );
  await page.getByRole("button", { name: "Change the design" }).click();
  await expect(page.getByRole("button", { name: "Generate new version" })).toBeDisabled();

  const planned = await page.request.get(`/api/test-fixture/projects/${projectId}/summary`);
  const plannedSummary = await planned.json();
  const revisionPlan = plannedSummary.revision_plans.at(-1);
  const beforeCalls = plannedSummary.provider_call_count;
  const beforeApproval = await page.request.post(`/api/revision-plans/${revisionPlan.id}/generate`);
  expect(beforeApproval.status()).toBe(409);
  const afterCalls = await (await page.request.get(`/api/test-fixture/projects/${projectId}/summary`)).json();
  expect(afterCalls.provider_call_count).toBe(beforeCalls);
  expect(errors).toEqual([]);
});

for (const mode of ["protected_base_drift", "identity_replacement"] as const) {
  test(`rejects ${mode} before worker execution`, async ({ page }) => {
    const seeded = await page.request.post(
      `/api/test-fixture/scenarios/revise-enclosure-lid?mode=${mode}`,
    );
    expect(seeded.status()).toBe(201);
    const fixture = await seeded.json();
    const projectId = fixture.project.id as string;
    await openEnclosure(page, fixture.project.name);

    const planResponse = await page.request.post(`/api/projects/${projectId}/revision-plans`, {
      data: {
        base_revision_id: fixture.current_revision.id,
        user_instruction: "Add a recessed finger pull to the lid only. Keep the enclosure body and lid fit unchanged.",
        reason: "user_request",
      },
    });
    expect(planResponse.status()).toBe(201);
    const plan = await planResponse.json();
    const approved = await page.request.post(`/api/revision-plans/${plan.id}/approve`);
    expect(approved.status()).toBe(200);
    const failed = await page.request.post(`/api/revision-plans/${plan.id}/generate`);
    expect(failed.status()).toBe(409);

    const summary = await (await page.request.get(`/api/test-fixture/projects/${projectId}/summary`)).json();
    expect(summary.worker_calls).toHaveLength(1);
    expect(summary.revisions.filter((revision: { is_accepted: boolean }) => !revision.is_accepted)).toHaveLength(0);
  });
}
