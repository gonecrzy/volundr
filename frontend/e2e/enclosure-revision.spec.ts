import { expect, test } from "@playwright/test";

test("revise-enclosure-lid changes only the lid through the approved revision workflow", async ({ page }) => {
  const consoleErrors: string[] = [];
  const failedRequests: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") {
      consoleErrors.push(message.text());
    }
  });
  page.on("response", (response) => {
    if (response.status() >= 400) {
      failedRequests.push(`${response.status()} ${response.url()}`);
    }
  });

  const seeded = await page.request.post("/api/test-fixture/scenarios/revise-enclosure-lid");
  expect(seeded.status()).toBe(201);
  const fixture = await seeded.json();
  const projectId = fixture.project.id as string;

  await page.goto("/?testScenario=revise-enclosure-lid");
  await page.getByRole("button", { name: "Projects" }).click();
  await page.getByRole("button", { name: fixture.project.name }).click();

  await expect(page.getByRole("heading", { name: "Current design" })).toBeVisible();
  await expect(page.getByText("Printable parts - 2")).toBeVisible();
  await expect(page.getByRole("button", { name: /Enclosure base/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /Snap lid/ })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Adjust parameters" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Change the design" })).toBeVisible();
  await expect(page.getByText("Technical details", { exact: true })).toBeVisible();

  await page.getByLabel("AI chat message").fill(
    "Add a recessed finger pull to the lid only. Keep the enclosure body and lid fit unchanged.",
  );
  await page.getByRole("button", { name: "Change the design" }).click();

  const plannedChanges = page.getByLabel("Planned changes");
  await expect(plannedChanges).toBeVisible();
  await expect(plannedChanges.getByText("lid_panel: flat lid -> recessed finger pull", { exact: true })).toBeVisible();
  await expect(plannedChanges.getByText("snap_lid", { exact: true })).toBeVisible();
  await expect(plannedChanges.getByText("lid", { exact: true })).toBeVisible();
  await expect(plannedChanges.getByText("Component base_shell", { exact: true })).toBeVisible();
  await expect(plannedChanges.getByText("Output base", { exact: true })).toBeVisible();
  await expect(plannedChanges.getByText(/body_width: 80 mm/)).toBeVisible();
  await expect(plannedChanges.getByText(/fit_clearance: 0.4 mm/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Generate new version" })).toBeDisabled();

  const plannedSummary = await page.evaluate(async (id) => {
    const response = await fetch(`/api/test-fixture/projects/${id}/summary`);
    return response.json();
  }, projectId);
  expect(plannedSummary.provider_calls).toEqual(["requirement_extraction", "design_plan_generation", "source_generation", "revision_plan_generation"]);
  expect(plannedSummary.frontend_actions).toEqual(expect.arrayContaining(["revision_opened", "revision_requested"]));

  await page.getByRole("button", { name: "Review planned changes" }).click();
  await expect(page.getByRole("heading", { name: "New version" })).toBeVisible();
  await expect(page.getByText("Printable parts - 2")).toBeVisible();
  await expect(page.getByText(/base: verified unchanged/)).toBeVisible();
  await expect(page.getByText(/lid: changed/)).toBeVisible();
  await expect(page.getByText("Revision scope checks")).toBeVisible();
  await expect(page.getByText("Passed approved revision scope")).toBeVisible();
  await expect(page.getByText("Revision verification")).toBeVisible();
  await expect(page.getByRole("button", { name: "Accept new version" })).toBeEnabled();

  const generatedSummary = await page.evaluate(async (id) => {
    const response = await fetch(`/api/test-fixture/projects/${id}/summary`);
    return response.json();
  }, projectId);
  expect(generatedSummary.provider_calls).toEqual([
    "requirement_extraction",
    "design_plan_generation",
    "source_generation",
    "revision_plan_generation",
    "component_revision",
  ]);
  expect(generatedSummary.worker_calls.at(-1).output_ids).toEqual(["base", "lid"]);
  expect(generatedSummary.frontend_actions).toEqual(expect.arrayContaining([
    "revision_plan_approved",
    "candidate_opened",
  ]));
  expect(generatedSummary.artifact_stages).toEqual(expect.arrayContaining([
    "source_generation",
    "cad_execution",
    "output_preservation",
  ]));
  expect(generatedSummary.artifact_types).toEqual(expect.arrayContaining([
    "source_validation_result",
    "revision_compliance_result",
    "component_revision_summary",
    "design_consistency_result",
    "topology_result",
  ]));
  expect(generatedSummary.workflow_event_types).toEqual(expect.arrayContaining([
    "revision_plan_generation.completed",
    "revision_plan.approved",
    "source_contract.passed",
    "component_revision.started",
    "component_revision.completed",
    "candidate.classified",
  ]));

  const candidateRevision = generatedSummary.revisions.find(
    (revision: { is_accepted: boolean }) => !revision.is_accepted,
  );
  expect(candidateRevision).toBeTruthy();
  const source = await page.request.get(`/api/revisions/${candidateRevision.id}/source`);
  expect(await source.text()).toContain("recessed finger pull");
  const beforeAcceptanceProject = await page.request.get(`/api/projects/${projectId}`);
  expect((await beforeAcceptanceProject.json()).active_revision_id).toBe(fixture.project.active_revision_id);

  const componentPlan = generatedSummary.revision_plans.find(
    (plan: { generated_revision_id: string | null }) => plan.generated_revision_id === candidateRevision.id,
  );
  expect(componentPlan.payload.targeted_components).toEqual(["snap_lid"]);
  expect(componentPlan.payload.protected_outputs).toEqual(["base"]);

  await page.getByRole("button", { name: "Accept new version" }).click();
  await expect(page.getByRole("heading", { name: "Current design" })).toBeVisible();
  const acceptedSummary = await page.evaluate(async (id) => {
    const response = await fetch(`/api/test-fixture/projects/${id}/summary`);
    return response.json();
  }, projectId);
  expect(acceptedSummary.frontend_actions).toEqual(expect.arrayContaining(["candidate_accepted"]));
  expect(acceptedSummary.revisions.filter((revision: { is_accepted: boolean }) => revision.is_accepted)).toHaveLength(2);
  expect(acceptedSummary.workflow_runs.some((run: { workflow_type: string }) => run.workflow_type === "component_revision")).toBe(true);

  const componentRun = acceptedSummary.workflow_runs.find(
    (run: { workflow_type: string }) => run.workflow_type === "component_revision",
  );
  const planningRun = acceptedSummary.workflow_runs.find(
    (run: { workflow_type: string }) => run.workflow_type === "revision_planning",
  );
  expect(planningRun).toBeTruthy();
  expect(componentRun.parent_workflow_run_id).toBe(planningRun.id);
  expect(componentRun.root_workflow_run_id).toBe(planningRun.root_workflow_run_id);
  const componentEvents = await page.request.get(`/api/workflow-runs/${componentRun.id}/events`);
  expect(componentEvents.status()).toBe(200);
  const componentEventRows = await componentEvents.json();
  expect(componentEventRows.map((event: { sequence_number: number }) => event.sequence_number)).toEqual(
    [...componentEventRows.map((event: { sequence_number: number }) => event.sequence_number)].sort((a, b) => a - b),
  );
  const acceptanceEvent = acceptedSummary.workflow_event_details.find(
    (event: { event_type: string; revision_id: string | null }) =>
      event.event_type === "candidate.accepted" && event.revision_id === candidateRevision.id,
  );
  expect(acceptanceEvent.workflow_run_id).not.toBe(componentRun.id);
  expect(acceptanceEvent.root_workflow_run_id).toBe(componentRun.root_workflow_run_id);

  const bundle = await page.request.get(`/api/workflow-runs/${componentRun.id}/debug-bundle.zip`);
  expect(bundle.status()).toBe(200);
  const bundleText = (await bundle.body()).toString("latin1");
  expect(bundleText).toContain("revision_plan");
  expect(bundleText).toContain("component_revised_source");
  expect(bundleText).toContain("scope_compliance_result");
  expect(bundleText).toContain("output_preservation_result");
  expect(bundleText).toContain("redaction-report.json");
  expect(bundleText).not.toContain("AIza");

  const baselineRun = acceptedSummary.workflow_runs.find(
    (run: { workflow_type: string }) => run.workflow_type === "source_generation",
  );
  const comparison = await page.request.get(
    `/api/workflow-runs/${baselineRun.id}/compare/${componentRun.id}`,
  );
  expect(comparison.status()).toBe(200);
  const comparisonBody = await comparison.json();
  expect(JSON.stringify(comparisonBody)).toContain("intended_component_change");
  expect(JSON.stringify(comparisonBody)).toContain("output_preservation");
  expect(JSON.stringify(comparisonBody)).toContain("lid");
  expect(JSON.stringify(comparisonBody)).toContain("base");
  expect(JSON.stringify(comparisonBody)).not.toContain("unauthorized");

  await page.reload();
  await page.getByRole("button", { name: "Projects" }).click();
  await page.getByRole("button", { name: fixture.project.name }).click();
  await expect(page.getByRole("heading", { name: "Current design" })).toBeVisible();
  await expect(page.getByText(/R2 active/)).toBeVisible();
  expect(consoleErrors).toEqual([]);
  expect(failedRequests).toEqual([]);
});
