import { expect, test } from "@playwright/test";

test("start over preserves the prior working version and creates a new lineage", async ({ page }) => {
  await page.goto("/?testing_session=true&test_scenario_id=start-over");
  await page.getByLabel("AI chat message").fill("Create an 80 mm mounting plate.");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByRole("heading", { name: "Current working version" })).toBeVisible();

  await page.getByLabel("AI chat message").fill("Start over, but keep the 80 mm fit. Use a different approach.");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByRole("heading", { name: "Current working version" })).toBeVisible();

  const projectId = await page.evaluate(async () => {
    const projects = await fetch("/api/projects").then((response) => response.json());
    return projects[0].id;
  });
  const [project, revisions, specification] = await Promise.all([
    page.request.get(`/api/projects/${projectId}`).then((response) => response.json()),
    page.request.get(`/api/projects/${projectId}/revisions`).then((response) => response.json()),
    page.request.get(`/api/projects/${projectId}/design-specification`).then((response) => response.json()),
  ]);
  expect(revisions.length).toBe(2);
  expect(revisions[1].parent_revision_id).toBe(revisions[0].id);
  expect(revisions.every((revision: { is_accepted: boolean }) => revision.is_accepted)).toBe(true);
  expect(project.active_revision_id).toBe(revisions[1].id);
  expect(specification.superseded_specification_id).toBeTruthy();
});
