import { expect, test } from "@playwright/test";

test("configure-organizer changes four columns to six without a provider call", async ({ page }) => {
  const consoleErrors: string[] = [];
  const failedRequests: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") {
      consoleErrors.push(`${message.text()} ${message.location().url}`);
    }
  });
  page.on("response", (response) => {
    if (response.status() >= 400) {
      failedRequests.push(`${response.status()} ${response.url()}`);
    }
  });

  const seeded = await page.request.post("/api/test-fixture/scenarios/configure-organizer");
  expect(seeded.status()).toBe(201);
  const fixture = await seeded.json();
  const projectId = fixture.project.id as string;

  await page.goto("/?testScenario=configure-organizer");
  await page.getByRole("button", { name: "Projects" }).click();
  await page.getByRole("button", { name: "Configurable organizer" }).first().click();

  await expect(page.getByRole("heading", { name: "Current design" })).toBeVisible();
  await expect(page.getByText("Organizer", { exact: false }).first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "Adjust parameters" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Change the design" })).toBeVisible();
  await expect(page.getByText("Technical details", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Column count")).toHaveValue("4");

  await page.getByLabel("Column count").fill("6");
  await page.getByRole("button", { name: "Preview effects" }).click();
  const configurationPanel = page.getByRole("region", { name: "Configure parameters" });
  await expect(configurationPanel.getByText("Configuration ready")).toBeVisible();
  await expect(configurationPanel.getByText("1 component, 1 output")).toBeVisible();
  await expect(configurationPanel.getByRole("heading", { name: "Direct changes" })).toBeVisible();
  await expect(configurationPanel.getByText(/Column count: 4.*6/)).toBeVisible();
  await expect(configurationPanel.getByRole("heading", { name: "Calculated effects" })).toBeVisible();
  await expect(configurationPanel.getByText("overall_width")).toBeVisible();
  await expect(configurationPanel.getByRole("heading", { name: "Affected printable parts" })).toBeVisible();
  await expect(configurationPanel.getByText("plate", { exact: true })).toBeVisible();
  await expect(configurationPanel.getByRole("heading", { name: "Unchanged values" })).toBeVisible();
  await expect(configurationPanel.getByText(/Wall thickness: 3/)).toBeVisible();

  await expect.poll(async () => page.evaluate(async (id) => {
    const response = await fetch(`/api/test-fixture/projects/${id}/summary`);
    return response.json();
  }, projectId)).toMatchObject({
    frontend_actions: expect.arrayContaining(["configuration_opened", "configuration_previewed"]),
  });

  const beforeGenerate = await page.evaluate(async (id) => {
    const response = await fetch(`/api/test-fixture/projects/${id}/summary`);
    return response.json();
  }, projectId);
  expect(beforeGenerate.provider_call_count).toBe(3);
  const baseManifest = await page.request.get(`/api/revisions/${fixture.current_revision.id}/output-manifest`);
  expect(baseManifest.status()).toBe(200);
  const baseManifestBody = await baseManifest.json();

  await page.getByRole("button", { name: "Create new version" }).click();
  await expect(page.getByRole("heading", { name: "New version" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Accept new version" })).toBeEnabled();

  const afterGenerate = await page.evaluate(async (id) => {
    const response = await fetch(`/api/test-fixture/projects/${id}/summary`);
    return response.json();
  }, projectId);
  expect(afterGenerate.provider_call_count).toBe(beforeGenerate.provider_call_count);
  expect(afterGenerate.artifact_types).toEqual(expect.arrayContaining([
    "configuration_change",
    "parameter_manifest",
  ]));
  expect(afterGenerate.frontend_actions).toEqual(expect.arrayContaining([
    "configuration_opened",
    "configuration_previewed",
    "configuration_submitted",
    "candidate_opened",
  ]));
  const candidateRevisionBeforeAcceptance = afterGenerate.revisions.find(
    (revision: { is_accepted: boolean }) => !revision.is_accepted,
  );
  expect(candidateRevisionBeforeAcceptance).toBeTruthy();
  const candidateManifest = await page.request.get(
    `/api/revisions/${candidateRevisionBeforeAcceptance.id}/output-manifest`,
  );
  expect(candidateManifest.status()).toBe(200);
  const candidateManifestBody = await candidateManifest.json();
  expect(candidateManifestBody.source.sha256).toBe(baseManifestBody.source.sha256);
  expect(candidateManifestBody.parameter_hash).not.toBe(baseManifestBody.parameter_hash);

  await expect(page.getByRole("heading", { name: "New version" })).toBeVisible();
  const beforeAcceptanceProject = await page.evaluate(async (id) => {
    const response = await fetch(`/api/projects/${id}`);
    return response.json();
  }, projectId);
  expect(beforeAcceptanceProject.active_revision_id).toBe(fixture.project.active_revision_id);
  await page.getByRole("button", { name: "Accept new version" }).click();
  await expect(page.getByRole("heading", { name: "Current design" })).toBeVisible();

  await expect.poll(async () => page.evaluate(async (id) => {
    const response = await fetch(`/api/test-fixture/projects/${id}/summary`);
    return response.json();
  }, projectId)).toMatchObject({
    frontend_actions: expect.arrayContaining(["candidate_accepted"]),
  });
  const persistedSummary = await page.evaluate(async (id) => {
    const response = await fetch(`/api/test-fixture/projects/${id}/summary`);
    return response.json();
  }, projectId);
  expect(persistedSummary.revisions.filter((revision: { is_accepted: boolean }) => revision.is_accepted)).toHaveLength(2);
  const configurationRun = persistedSummary.workflow_runs.find(
    (run: { workflow_type: string }) => run.workflow_type === "configuration_change",
  );
  const baselineRun = persistedSummary.workflow_runs.find(
    (run: { workflow_type: string }) => run.workflow_type === "source_generation",
  );
  expect(configurationRun).toBeTruthy();
  expect(baselineRun).toBeTruthy();
  expect(configurationRun.parent_workflow_run_id).toBe(baselineRun.root_workflow_run_id);
  expect(configurationRun.root_workflow_run_id).toBe(baselineRun.root_workflow_run_id);
  expect(configurationRun.correlation_id).toBe(baselineRun.correlation_id);
  const configuredRevision = persistedSummary.revisions.find(
    (revision: { id: string; configuration_change_id: string | null }) => revision.configuration_change_id,
  );
  expect(configuredRevision).toBeTruthy();
  const acceptanceEvent = persistedSummary.workflow_event_details.find(
    (event: { event_type: string; revision_id: string | null }) =>
      event.event_type === "candidate.accepted" && event.revision_id === configuredRevision.id,
  );
  expect(acceptanceEvent).toBeTruthy();
  const acceptanceRun = persistedSummary.workflow_runs.find(
    (run: { id: string; workflow_type: string }) =>
      run.workflow_type === "candidate_acceptance" && run.id === acceptanceEvent.workflow_run_id,
  );
  expect(acceptanceRun).toBeTruthy();
  expect(acceptanceRun.root_workflow_run_id).toBe(configurationRun.root_workflow_run_id);
  const configurationFrontendEvents = persistedSummary.frontend_event_details.filter(
    (event: { action_name: string }) => [
      "configuration_opened",
      "configuration_previewed",
      "configuration_submitted",
      "candidate_opened",
      "candidate_accepted",
    ].includes(event.action_name),
  );
  expect(configurationFrontendEvents.map((event: { action_name: string }) => event.action_name)).toEqual([
    "configuration_opened",
    "configuration_previewed",
    "configuration_submitted",
    "candidate_opened",
    "candidate_accepted",
  ]);
  expect(configurationFrontendEvents.slice(0, 4).map((event: { correlation_id: string }) => event.correlation_id)).toEqual(
    configurationFrontendEvents.slice(0, 4).map(() => configurationRun.correlation_id),
  );
  expect(configurationFrontendEvents[4].correlation_id).toBe(acceptanceRun.correlation_id);
  const comparison = await page.evaluate(async ({ baselineId, configurationId }) => {
    const response = await fetch(`/api/workflow-runs/${baselineId}/compare/${configurationId}`);
    return { status: response.status, body: await response.json() };
  }, { baselineId: baselineRun.id, configurationId: configurationRun.id });
  expect(comparison.status).toBe(200);
  expect(JSON.stringify(comparison.body)).toContain("column_count");
  expect(JSON.stringify(comparison.body)).toContain("intended_parameter_change");
  expect(JSON.stringify(comparison.body)).not.toContain("source drift");
  const bundle = await page.request.get(`/api/workflow-runs/${configurationRun.id}/debug-bundle.zip`);
  expect(bundle.status()).toBe(200);
  expect((await bundle.body()).subarray(0, 2).toString()).toBe("PK");
  const bundleText = (await bundle.body()).toString("latin1");
  expect(bundleText).toContain("redaction-report.json");
  expect(bundleText).toContain("frontend-events.ndjson");
  await page.reload();
  await page.getByRole("button", { name: "Projects" }).click();
  await page.getByRole("button", { name: "Configurable organizer" }).first().click();
  await expect(page.getByRole("heading", { name: "Current design" })).toBeVisible();
  await expect(page.getByText(/R2 active/)).toBeVisible();
  expect(consoleErrors).toEqual([]);
  expect(failedRequests).toEqual([]);
});
