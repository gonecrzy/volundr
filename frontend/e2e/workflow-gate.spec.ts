import { expect, test } from "@playwright/test";

test.skip(
  (process.env.VITE_VOLUNDR_CHAT_FIRST ?? "true").toLowerCase() !== "true",
  "chat-first workflow suite; run with VITE_VOLUNDR_CHAT_FIRST=true",
);

test.describe.configure({ mode: "serial" });

test("explicit part auto-creates a Current working version and keeps export explicit", async ({ page }) => {
  const consoleErrors: string[] = [];
  page.on("console", (entry) => {
    if (entry.type() === "error") consoleErrors.push(entry.text());
  });

  await page.goto("/?testing_session=true&test_scenario_id=simple-explicit-part");
  await page.getByLabel("AI chat message").fill("Create an 80 mm mounting plate.");
  await page.getByRole("button", { name: "Send" }).click();

  const viewportWidth = await page.evaluate(() => window.innerWidth);
  if (viewportWidth < 1000) {
    await page.getByRole("button", { name: "Model", exact: true }).click();
  } else if (viewportWidth < 1280) {
    await page.getByRole("button", { name: "Details", exact: true }).click();
  }
  await expect(page.getByText("Version 1", { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Accept new version" })).toHaveCount(0);
  if (viewportWidth < 1000) {
    await page.getByRole("button", { name: "Details", exact: true }).click();
  }
  const technicalDetails = viewportWidth >= 1000 && viewportWidth < 1280
    ? page.getByLabel("Design details").getByText("Technical details", { exact: true })
    : page.getByLabel("Design summary").getByText("Technical details", { exact: true });
  await technicalDetails.click();
  const bundle = page.getByRole("link", { name: "Download diagnostic bundle" });
  await expect(bundle).toBeVisible();
  const download = await Promise.all([page.waitForEvent("download"), bundle.click()]);
  expect((await download[0].suggestedFilename())).toContain("workflow-debug-");

  if (viewportWidth >= 1000 && viewportWidth < 1280) {
    await page.getByLabel("Design details").getByRole("button", { name: "Close" }).click();
  }
  await page.locator("button.topbar-export").click();
  const exportDownload = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: "Create project package" }).click(),
  ]);
  expect((await exportDownload[0].suggestedFilename())).toMatch(/^[a-z0-9-]+_project_r1\.zip$/);
  await expect.poll(async () => page.evaluate(async () =>
    fetch("/api/test-fixture/latest-summary").then((response) => response.json()),
  )).toMatchObject({
    provider_call_count: expect.any(Number),
    provider_calls: expect.arrayContaining(["requirement_extraction", "source_generation"]),
    artifact_types: expect.arrayContaining(["planning_route_decision", "cad_brief", "geometry_execution_context", "prompt_context_pack"]),
    workflow_event_types: expect.arrayContaining(["candidate.classified", "candidate.accepted", "working_version.promoted"]),
    frontend_actions: expect.arrayContaining(["chat_message_submitted", "export_requested"]),
    revisions: [expect.objectContaining({ is_accepted: true, review_state: "accepted" })],
  });
  expect((await page.evaluate(async () => fetch("/api/test-fixture/latest-summary").then((response) => response.json()))).provider_calls).not.toContain("design_plan_generation");
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
  await expect(page.getByText("Version 1", { exact: true }).first()).toBeVisible();
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
