import { expect, test } from "@playwright/test";

test.skip(
  (process.env.VITE_VOLUNDR_CHAT_FIRST ?? "true").toLowerCase() !== "true",
  "chat-first workflow suite; run with VITE_VOLUNDR_CHAT_FIRST=true",
);

test("ordinary feedback revisions remain available before and after an exposed control", async ({ page }) => {
  await page.goto("/?testing_session=true&test_scenario_id=requirement-driven-revisions");
  await page.getByLabel("AI chat message").fill("Create an 80 mm mounting plate.");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByText("Version 1", { exact: true }).first()).toBeVisible();
  await page.getByLabel("AI chat message").fill("The printed fit is too tight. Add 0.5 mm clearance per side.");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByRole("heading", { name: "Current working version" })).toBeVisible();

  const projectId = await page.evaluate(async () => {
    const projects = await fetch("/api/projects").then((response) => response.json());
    return projects[0].id;
  });
  const requirements = await page.request.get(`/api/projects/${projectId}/requirements/active`).then((response) => response.json());
  expect(requirements.requirements.some((item: { requirement_id: string }) => item.requirement_id === "fit_clearance_per_side")).toBe(true);

  await page.getByLabel("AI chat message").fill("Expose plate width as an adjustable control.");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByRole("heading", { name: "Current working version" })).toBeVisible();

  const plan = await page.request.get(`/api/projects/${projectId}/design-plan`).then((response) => response.json());
  expect(plan.plan.exposed_controls.map((item: { parameter_id: string }) => item.parameter_id)).toEqual(["plate_width"]);

  await page.getByLabel("AI chat message").fill("Change plate width to 90 mm.");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByRole("heading", { name: "Current working version" })).toBeVisible();

  const project = await page.request.get(`/api/projects/${projectId}`).then((response) => response.json());
  expect(project.active_revision_id).toBeTruthy();
  await page.reload();
  await expect(page.getByRole("heading", { name: "Current working version" })).toBeVisible();
  await page.goto(`/projects/${projectId}`);
  await expect(page.getByRole("heading", { name: "Current working version" })).toBeVisible();
  await page.getByRole("button", { name: "Projects" }).click();
  await expect(page.locator("button.project-item", { hasText: project.name })).toBeVisible();
});
