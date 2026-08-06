import { expect, test } from "@playwright/test";

test.skip(
  (process.env.VITE_VOLUNDR_VALIDATED_CADQUERY_FLOW_ENABLED ?? "false").toLowerCase() !== "true",
  "validated product shell suite; run with VITE_VOLUNDR_VALIDATED_CADQUERY_FLOW_ENABLED=true",
);

test("runs one validated design through review, package download, bounded revision, and stable reload", async ({ page }) => {
  const designRequests: string[] = [];
  const workflowReads: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (request.method() === "POST" && url.pathname.endsWith("/api/validated-cadquery/designs")) {
      designRequests.push(request.headers()["idempotency-key"] ?? "");
    }
    if (request.method() === "GET" && /\/api\/validated-cadquery\/projects\/[^/]+\/designs\/[^/]+$/.test(url.pathname)) {
      workflowReads.push(url.pathname);
    }
  });

  await page.goto("/?testing_session=true&test_scenario_id=validated-product-shell");
  await page.getByLabel("AI chat message").fill("Create a printable mounting plate with one required output.");
  await page.getByRole("button", { name: "Send" }).click();

  await expect(page).toHaveURL(/\/projects\/[^/]+\/designs\/[^/]+$/);
  await expect(page.getByRole("heading", { name: "Validated design", exact: true })).toBeVisible();
  await expect(page.getByText("Ready to review", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Validated outputs").getByRole("article")).toHaveCount(1);
  await expect(page.getByText("Ready", { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Start design" })).toHaveCount(0);
  expect(designRequests).toHaveLength(1);
  expect(designRequests[0]).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i);

  const readsBeforeTerminalWait = workflowReads.length;
  await page.waitForTimeout(3500);
  expect(workflowReads.length).toBe(readsBeforeTerminalWait);

  await page.getByRole("button", { name: "Accept candidate" }).click();
  await expect(page.getByRole("link", { name: "Download design package" })).toBeVisible();
  const packageDownload = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("link", { name: "Download design package" }).click(),
  ]);
  expect((await packageDownload[0].suggestedFilename()).toLowerCase()).toMatch(/^validated-cadquery-.*\.zip$/);

  await page.getByLabel("What should change?").fill("Make the plate wider while preserving the required output.");
  await page.getByLabel("New dimension value (optional)").fill("96 mm");
  await page.getByRole("button", { name: "Start revision" }).click();
  await expect(page.getByText("Revision ready to review", { exact: true })).toBeVisible();

  const stableUrl = page.url();
  await page.reload();
  await expect(page).toHaveURL(stableUrl);
  await expect(page.getByText("Revision ready to review", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Validated printable parts", exact: true })).toBeVisible();
});
