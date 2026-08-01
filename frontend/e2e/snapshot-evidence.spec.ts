import { expect, test } from "@playwright/test";

test.skip(
  (process.env.VITE_VOLUNDR_CHAT_FIRST ?? "true").toLowerCase() !== "true",
  "snapshot evidence is part of the chat-first workspace",
);

async function openDetailsIfNeeded(page: import("@playwright/test").Page) {
  const width = await page.evaluate(() => window.innerWidth);
  if (width < 1000) {
    await page.getByRole("button", { name: "Details", exact: true }).click();
  }
  return width;
}

test("successful worker geometry exposes durable standard views", async ({ page }) => {
  await page.goto("/?testing_session=true&test_scenario_id=simple-explicit-part");
  await page.getByLabel("AI chat message").fill("Create an 80 mm mounting plate.");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByText("Version 1", { exact: true }).first()).toBeVisible();

  const width = await openDetailsIfNeeded(page);
  const details = width >= 1280 ? page.getByLabel("Design summary") : page.getByLabel("Design details");
  await expect(details.getByRole("heading", { name: "Views" })).toBeVisible();
  await expect(details.getByRole("button", { name: /isometric view/i })).toBeVisible();
  await expect(details.getByRole("button", { name: /front view/i })).toBeVisible();
  await expect(details.getByRole("button", { name: /right view/i })).toBeVisible();
  await expect(details.getByRole("button", { name: /top view/i })).toBeVisible();

  await page.reload();
  await openDetailsIfNeeded(page);
  const refreshedDetails = page.getByLabel("Design summary").or(page.getByLabel("Design details"));
  await expect(refreshedDetails.getByRole("heading", { name: "Views" })).toBeVisible();
  const summary = await page.evaluate(async () => fetch("/api/test-fixture/latest-summary").then((response) => response.json()));
  expect(summary.artifact_types).toEqual(expect.arrayContaining(["geometry_snapshot_packet", "geometry_snapshot", "component_snapshot"]));
});

test("successful revision exposes deterministic comparison evidence", async ({ page }) => {
  await page.goto("/?testing_session=true&test_scenario_id=requirement-driven-revisions");
  await page.getByLabel("AI chat message").fill("Create an 80 mm mounting plate.");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByText("Version 1", { exact: true }).first()).toBeVisible();
  await page.getByLabel("AI chat message").fill("The printed fit is too tight. Add 0.5 mm clearance per side.");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByRole("heading", { name: "Current working version" })).toBeVisible();

  const projectId = await page.evaluate(async () => (await fetch("/api/projects").then((response) => response.json()))[0].id);
  const revisions = await page.request.get(`/api/projects/${projectId}/revisions`).then((response) => response.json());
  const latest = revisions.at(-1);
  expect(latest?.parent_revision_id).toBeTruthy();
  await expect.poll(async () => page.request.get(`/api/revisions/${latest.id}/comparison`).then((response) => response.status())).toBe(200);
  const comparison = await page.request.get(`/api/revisions/${latest.id}/comparison`).then((response) => response.json());
  expect(comparison.artifacts.paired_view_ids.length).toBeGreaterThan(0);
  expect(comparison.geometry).toHaveProperty("bounding_box_delta");
  expect(comparison).not.toHaveProperty("raw_source");
});
