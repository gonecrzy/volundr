import { expect, test } from "@playwright/test";

test.describe.configure({ mode: "serial" });

test("explicit part auto-creates a Current working version and keeps export explicit", async ({ page }) => {
  const consoleErrors: string[] = [];
  page.on("console", (entry) => {
    if (entry.type() === "error") consoleErrors.push(entry.text());
  });

  await page.goto("/?testing_session=true&test_scenario_id=simple-explicit-part");
  await page.getByLabel("AI chat message").fill("Create an 80 mm mounting plate.");
  await page.getByRole("button", { name: "Send" }).click();

  await expect(page.getByRole("heading", { name: "Current working version" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Accept new version" })).toHaveCount(0);
  await page.getByText("Technical details", { exact: true }).click();
  const bundle = page.getByRole("link", { name: "Download diagnostic bundle" });
  await expect(bundle).toBeVisible();
  const download = await Promise.all([page.waitForEvent("download"), bundle.click()]);
  expect((await download[0].suggestedFilename())).toContain("workflow-debug-");

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
    workflow_event_types: expect.arrayContaining(["candidate.classified", "candidate.accepted", "working_version.promoted"]),
    frontend_actions: expect.arrayContaining(["chat_message_submitted", "export_requested"]),
    revisions: [expect.objectContaining({ is_accepted: true, review_state: "accepted" })],
  });
  expect(consoleErrors).toEqual([]);
});

test("intent-first holder asks one essential clarification and resumes automatically", async ({ page }) => {
  await page.goto("/?testing_session=true&test_scenario_id=intent-first-holder");
  await page.getByLabel("AI chat message").fill("Create a holder for my 70 mm wide device.");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByText("What is the maximum available height?", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Approve proposed design" })).toHaveCount(0);

  await page.getByLabel("AI chat message").fill("45 mm");
  await page.getByRole("button", { name: "Answer" }).click();
  await expect(page.getByRole("heading", { name: "Current working version" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Generate design" })).toHaveCount(0);

  await expect.poll(async () => page.evaluate(async () =>
    fetch("/api/test-fixture/latest-summary").then((response) => response.json()),
  )).toMatchObject({
    frontend_actions: expect.arrayContaining(["chat_message_submitted", "clarification_requested"]),
    workflow_runs: expect.arrayContaining([
      expect.objectContaining({ workflow_type: "initial_generation" }),
      expect.objectContaining({ workflow_type: "requirement_clarification" }),
    ]),
  });
});
