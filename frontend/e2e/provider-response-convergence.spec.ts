import { expect, test, type Page } from "@playwright/test";

async function openSeededCase(page: Page, mode: string) {
  const seeded = await page.request.post(`/api/test-fixture/scenarios/provider-convergence?mode=${mode}`);
  expect(seeded.status()).toBe(201);
  const fixture = await seeded.json() as { project: { id: string; name: string }; batch_id: string | null };
  await page.goto("/?testScenario=provider-convergence");
  await page.getByRole("button", { name: "Projects" }).click();
  await page.getByRole("button", { name: fixture.project.name }).click();
  await expect(page.getByText(fixture.project.name, { exact: true }).first()).toBeVisible();
  return fixture;
}

test("syntax-repaired requirements are shown as normalized without raw JSON", async ({ page }) => {
  await openSeededCase(page, "syntax-repaired-requirements");
  await page.getByText("Technical details", { exact: true }).click();
  await expect(page.getByText(/Deterministically normalized/)).toBeVisible();
  await expect(page.getByText(/Focused repair: valid_after_repair/)).toBeVisible();
  await expect(page.getByText(/\{\"/)).toHaveCount(0);
});

test("provenance-normalized compact Plan reports an accepted normalized response", async ({ page }) => {
  await openSeededCase(page, "provenance-normalized-plan");
  await page.getByText("Technical details", { exact: true }).click();
  await expect(page.getByText(/Deterministically normalized/)).toBeVisible();
  await expect(page.getByText(/Accepted/)).toBeVisible();
});

test("unchanged repair produces one final blocked chat outcome", async ({ page }) => {
  await openSeededCase(page, "unchanged-repair");
  await expect(page.getByText("Volundr could not complete the design plan for this request. No working version was created.", { exact: true })).toBeVisible();
  await page.getByText("Technical details", { exact: true }).click();
  await expect(page.getByText(/Blocked: unchanged repair/)).toBeVisible();
  await expect(page.getByText("Volundr could not complete the design plan for this request. No working version was created.", { exact: true })).toHaveCount(1);
});

test("regressive repair is visible as blocked and does not imply acceptance", async ({ page }) => {
  await openSeededCase(page, "regressive-repair");
  await expect(page.getByText("Volundr could not complete the design plan for this request. No working version was created.", { exact: true })).toBeVisible();
  await page.getByText("Technical details", { exact: true }).click();
  await expect(page.getByText(/Blocked: regressive repair/)).toBeVisible();
  await expect(page.getByText("Accepted", { exact: true })).toHaveCount(0);
});

test("debug report keeps provider calls and repairs separate", async ({ page }) => {
  const fixture = await openSeededCase(page, "debug-report-counts");
  expect(fixture.batch_id).toBeTruthy();
  await page.getByRole("button", { name: "View batch", exact: true }).click();
  await page.locator(".debug-batch-drawer").getByRole("button", { name: "Finish batch", exact: true }).click();
  await page.getByRole("button", { name: "Finish batch", exact: true }).last().click();
  await expect(page.getByRole("heading", { name: "Debug batch complete", exact: true })).toBeVisible();
  const reportResponse = await page.request.get(`/api/debug-batches/${fixture.batch_id}/report`);
  expect(reportResponse.ok()).toBeTruthy();
  const report = await reportResponse.json() as { summary: { provider_behavior: Record<string, number> } };
  expect(report.summary.provider_behavior.provider_calls).toBe(2);
  expect(report.summary.provider_behavior.content_repairs).toBe(1);
  expect(report.summary.provider_behavior.provider_retries).toBe(0);
});
