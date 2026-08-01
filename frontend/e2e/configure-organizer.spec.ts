import { expect, test } from "@playwright/test";

test.skip(
  (process.env.VITE_VOLUNDR_CHAT_FIRST ?? "true").toLowerCase() !== "true",
  "chat-first workflow suite; run with VITE_VOLUNDR_CHAT_FIRST=true",
);

test("organizer parameter messages route provider-free and promote the new version", async ({ page }) => {
  const seeded = await page.request.post("/api/test-fixture/scenarios/configure-organizer");
  expect(seeded.status()).toBe(201);
  const fixture = await seeded.json();
  const projectId = fixture.project.id as string;

  await page.goto("/?testScenario=configure-organizer");
  await page.getByRole("button", { name: "Projects" }).click();
  await page.locator("button.project-item", { hasText: "Configurable organizer" }).click();
  await expect(page.getByText("Version 1", { exact: true }).first()).toBeVisible();
  const before = await page.request.get(`/api/test-fixture/projects/${projectId}/summary`).then((response) => response.json());
  expect(before.provider_call_count).toBe(3);
  await page.getByLabel("AI chat message").fill("Change columns from four to six.");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByRole("heading", { name: "Current working version" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Accept new version" })).toHaveCount(0);

  const after = await page.request.get(`/api/test-fixture/projects/${projectId}/summary`).then((response) => response.json());
  expect(after.provider_call_count).toBe(before.provider_call_count);
  expect(after.revisions.filter((revision: { is_accepted: boolean }) => revision.is_accepted)).toHaveLength(2);
  expect(after.artifact_types).toEqual(expect.arrayContaining(["configuration_change", "parameter_manifest"]));
  expect(after.workflow_event_types).toEqual(expect.arrayContaining(["configuration_execution.completed", "working_version.promoted"]));

  const currentProject = await page.request.get(`/api/projects/${projectId}`).then((response) => response.json());
  expect(currentProject.active_revision_id).not.toBe(fixture.project.active_revision_id);
  await page.reload();
  await page.getByRole("button", { name: "Projects" }).click();
  await page.locator("button.project-item", { hasText: "Configurable organizer" }).click();
  await expect(page.getByText("Version 2", { exact: true }).first()).toBeVisible();
});
