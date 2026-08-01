import { expect, test, type Page } from "@playwright/test";

test.skip(
  (process.env.VITE_VOLUNDR_CHAT_FIRST ?? "true").toLowerCase() === "true",
  "staged workflow suite; run with VITE_VOLUNDR_CHAT_FIRST=false",
);

async function loadBlockedFixture(page: Page, failureMode: string) {
  const seeded = await page.request.post(
    `/api/test-fixture/scenarios/recoverable-blocked-part?failure_mode=${failureMode}`,
  );
  expect(seeded.status()).toBe(201);
  const fixture = await seeded.json();

  await page.goto("/?testScenario=recoverable-blocked-part");
  await page.getByRole("button", { name: "Projects" }).click();
  await page.getByRole("button", { name: fixture.project.name }).click();
  await expect(page.getByRole("heading", { name: "Current design" })).toBeVisible();
  await expect(page.getByText(/R1 active/)).toBeVisible();

  const pendingRevision = page.getByRole("button", { name: /R2/ });
  await expect(pendingRevision).toBeVisible();
  await pendingRevision.click();
  await expect(page.getByRole("heading", { name: "New version" })).toBeVisible();
  return { fixture, projectId: fixture.project.id as string };
}

function attachBrowserQualityChecks(page: Page) {
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
  return { consoleErrors, failedRequests };
}

test("multiple-solid blocked version stays safe and routes to part revision", async ({ page }) => {
  const { consoleErrors, failedRequests } = attachBrowserQualityChecks(page);
  const { fixture, projectId } = await loadBlockedFixture(page, "multiple_solids");

  await expect(page.getByText("The full design cannot be accepted because one required printable part is blocked.")).toBeVisible();
  await expect(page.getByText("Mounting plate", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Blocked", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("This printable part contains separate solid bodies that were expected to be connected.")).toBeVisible();
  await expect(page.getByText("Your current design was not changed.")).toBeVisible();

  const accept = page.getByRole("button", { name: "Accept new version" });
  await expect(accept).toBeDisabled();
  await page.getByRole("button", { name: /Mounting plate/ }).click();
  await expect(page.getByText("Solids 2/1")).toBeVisible();

  await page.getByRole("button", { name: "Revise this part" }).click();
  await expect(page.getByLabel("AI chat message")).toHaveValue(/Revise the Mounting plate/);
  await expect(page.getByText(/Revision request prepared for Mounting plate/)).toBeVisible();

  const summary = await page.request.get(`/api/test-fixture/projects/${projectId}/summary`);
  const body = await summary.json();
  expect(body.provider_call_count).toBe(4);
  expect(body.frontend_actions).toEqual(expect.arrayContaining([
    "candidate_opened",
    "output_selected",
    "visible_error_displayed",
    "failure_recovery_selected",
  ]));

  await page.getByText("Technical details", { exact: true }).click();
  await expect(page.getByText(/Workflow run:/)).toBeVisible();
  const bundle = page.getByRole("link", { name: "Download diagnostic bundle" });
  const download = await Promise.all([page.waitForEvent("download"), bundle.click()]);
  expect((await download[0].suggestedFilename())).toContain("workflow-debug-");
  const bundleHref = await bundle.getAttribute("href");
  const bundleResponse = await page.request.get(bundleHref as string);
  expect(bundleResponse.status()).toBe(200);
  expect((await bundleResponse.body()).subarray(0, 2).toString()).toBe("PK");

  const directAccept = await page.request.post(`/api/candidates/${fixture.blocked_revision.id}/accept`);
  expect(directAccept.status()).toBe(409);
  await page.reload();
  await page.getByRole("button", { name: "Projects" }).click();
  await page.getByRole("button", { name: fixture.project.name }).click();
  await expect(page.getByText(/R1 active/)).toBeVisible();
  expect(failedRequests).toEqual([]);
  expect(consoleErrors).toEqual([]);
});

test("worker-failed part retries without a provider and preserves the current design", async ({ page }) => {
  const { consoleErrors, failedRequests } = attachBrowserQualityChecks(page);
  const { fixture, projectId } = await loadBlockedFixture(page, "worker_failure");

  await expect(page.getByRole("heading", { name: "Volundr could not finish building this required printable part." })).toBeVisible();
  await expect(page.getByText("Your current design was not changed.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Accept new version" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Retry building this part" }).first()).toBeVisible();

  const before = await page.request.get(`/api/test-fixture/projects/${projectId}/summary`).then((response) => response.json());
  await page.getByRole("button", { name: "Retry building this part" }).first().click();
  await expect(page.getByRole("button", { name: "Accept new version" })).toBeEnabled();
  await expect(page.getByRole("button", { name: /Mounting plate.*Ready/ })).toBeVisible();

  const after = await page.request.get(`/api/test-fixture/projects/${projectId}/summary`).then((response) => response.json());
  expect(after.provider_call_count).toBe(before.provider_call_count);
  expect(after.worker_calls.length).toBe(before.worker_calls.length + 1);
  expect(after.workflow_event_types).toEqual(expect.arrayContaining([
    "output_retry.started",
    "worker.submitted",
    "worker.completed",
    "candidate.classified",
  ]));
  expect(after.frontend_actions).toEqual(expect.arrayContaining([
    "candidate_opened",
    "visible_error_displayed",
    "failure_recovery_selected",
  ]));

  await page.getByText("Technical details", { exact: true }).click();
  const diagnosticLink = page.getByRole("link", { name: "Download diagnostic bundle" });
  const diagnosticDownload = await Promise.all([
    page.waitForEvent("download"),
    diagnosticLink.click(),
  ]);
  expect((await diagnosticDownload[0].suggestedFilename())).toContain("workflow-debug-");

  const candidate = after.revisions.find((revision: { id: string }) => revision.id === fixture.blocked_revision.id);
  expect(candidate.review_state).toBe("ready_with_warnings");
  await page.getByRole("button", { name: "Accept new version" }).click();
  await expect(page.getByRole("heading", { name: "Current design" })).toBeVisible();
  expect((await page.request.get(`/api/projects/${projectId}`).then((response) => response.json())).active_revision_id)
    .toBe(fixture.blocked_revision.id);

  const retryRun = after.workflow_runs.find((run: { workflow_type: string }) => run.workflow_type === "output_retry");
  expect(retryRun).toBeTruthy();
  const bundle = await page.request.get(`/api/workflow-runs/${retryRun.id}/debug-bundle.zip`);
  expect(bundle.status()).toBe(200);
  const bundleText = (await bundle.body()).toString("latin1");
  expect(bundleText).toContain("pre_retry_worker_result");
  expect(bundleText).toContain("retry_output_manifest");
  expect(bundleText).toContain("redaction-report.json");
  expect(bundleText).not.toContain("AIza");
  const finalSummary = await page.request.get(`/api/test-fixture/projects/${projectId}/summary`).then((response) => response.json());
  expect(finalSummary.frontend_actions).toContain("diagnostic_bundle_requested");
  expect(consoleErrors).toEqual([]);
  expect(failedRequests).toEqual([]);
});
