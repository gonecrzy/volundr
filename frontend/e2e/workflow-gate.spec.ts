import { expect, test } from "@playwright/test";

test.describe.configure({ mode: "serial" });

test("explicit part completes through the real API, persistence, and diagnostic bundle", async ({ page }) => {
  const consoleErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") {
      consoleErrors.push(`${message.text()} ${message.location().url}`);
    }
  });

  await page.goto("/?testing_session=true&test_scenario_id=simple-explicit-part");
  await page.getByLabel("AI chat message").fill("Create an 80 mm mounting plate.");
  await page.getByRole("button", { name: "Send" }).click();

  await expect(page.getByRole("region", { name: "Design requirements" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Your requirements" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Volundr proposes" }).first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "Calculated" }).first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Review proposed design" })).toBeVisible();

  await page.getByRole("button", { name: "Review proposed design" }).click();
  await expect(page.getByRole("region", { name: "Proposed design" })).toBeVisible();
  await page.getByRole("button", { name: "Generate design" }).click();

  await expect(page.getByRole("region", { name: "Candidate review" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "New version" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Accept new version" })).toBeEnabled();

  await page.getByText("Technical details", { exact: true }).click();
  const bundle = page.getByRole("link", { name: "Download diagnostic bundle" });
  await expect(bundle).toBeVisible();
  const download = await Promise.all([page.waitForEvent("download"), bundle.click()]);
  expect((await download[0].suggestedFilename())).toContain("workflow-debug-");

  await page.getByRole("button", { name: "Accept new version" }).click();
  await expect(page.getByRole("heading", { name: "Current design" })).toBeVisible();
  const exportDownload = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("link", { name: "Export design" }).click(),
  ]);
  expect((await exportDownload[0].suggestedFilename())).toBe("volundr-project.zip");

  await expect.poll(async () => page.evaluate(async () =>
    fetch("/api/test-fixture/latest-summary").then((response) => response.json()),
  )).toMatchObject({
    provider_call_count: 3,
    provider_calls: expect.arrayContaining(["requirement_extraction", "design_plan_generation", "source_generation"]),
    workflow_event_types: expect.arrayContaining(["candidate.classified", "candidate.accepted"]),
    frontend_actions: expect.arrayContaining(["request_submitted", "candidate_accepted", "export_requested"]),
    revisions: [expect.objectContaining({ is_accepted: true, review_state: "accepted" })],
  });
  expect(consoleErrors).toEqual([]);
});

test("intent-first holder asks one essential clarification and preserves the root trace", async ({ page }) => {
  await page.goto("/?testing_session=true&test_scenario_id=intent-first-holder");
  await page.getByLabel("AI chat message").fill("Create a holder for my 70 mm wide device.");
  await page.getByRole("button", { name: "Send" }).click();

  const requirements = page.getByRole("region", { name: "Design requirements" });
  await expect(requirements).toBeVisible();
  await expect(requirements.getByText("A few details are still needed")).toBeVisible();
  await expect(requirements.getByText("What is the maximum available height?")).toBeVisible();
  await expect(requirements.getByText("Why this matters: The holder must fit its available space.")).toBeVisible();
  await expect(requirements.getByText("What is the maximum available height?")).toHaveCount(1);
  await requirements.getByRole("textbox").fill("45 mm");
  await requirements.getByRole("button", { name: "Continue" }).click();

  await expect(requirements.getByRole("heading", { name: "Your requirements" })).toBeVisible();
  await expect(requirements.getByRole("heading", { name: "Volundr proposes" }).first()).toBeVisible();
  await expect(requirements.getByRole("heading", { name: "Calculated" }).first()).toBeVisible();
  await page.getByRole("button", { name: "Review proposed design" }).click();
  await page.getByRole("button", { name: "Generate design" }).click();
  await expect(page.getByRole("region", { name: "Candidate review" })).toBeVisible();

  await expect.poll(async () => page.evaluate(async () =>
    fetch("/api/test-fixture/latest-summary").then((response) => response.json()),
  )).toMatchObject({
    frontend_actions: expect.arrayContaining(["clarification_displayed", "clarification_answered"]),
    workflow_runs: expect.arrayContaining([
      expect.objectContaining({ workflow_type: "initial_generation" }),
      expect.objectContaining({ workflow_type: "requirement_clarification" }),
    ]),
  });
  const summary = await page.evaluate(async () =>
    fetch("/api/test-fixture/latest-summary").then((response) => response.json()),
  );
  const root = summary.workflow_runs.find((run: { workflow_type: string }) => run.workflow_type === "initial_generation");
  const clarification = summary.workflow_runs.find(
    (run: { workflow_type: string }) => run.workflow_type === "requirement_clarification",
  );
  expect(clarification.parent_workflow_run_id).toBe(root.id);
  expect(clarification.root_workflow_run_id).toBe(root.id);
  expect(clarification.correlation_id).toBe(root.correlation_id);
});
