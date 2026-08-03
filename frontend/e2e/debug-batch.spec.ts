import { expect, test, type Page } from "@playwright/test";

test.describe.serial("developer live debug batches", () => {
  test.beforeEach(async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/");
  });

  test.afterEach(async ({ page }) => {
    const response = await page.request.get("/api/debug-batches?state=active");
    if (!response.ok()) return;
    const active = await response.json();
    for (const batch of active) {
      await page.request.post(`/api/debug-batches/${batch.id}/finish`);
    }
  });

  async function closeBatchDrawer(page: Page) {
    const close = page.locator(".debug-batch-drawer").getByRole("button", { name: "Close", exact: true });
    if (await close.isVisible()) {
      await close.click();
    }
  }

  async function startBatch(page: Page, label: string, baseline?: string) {
    await page.getByRole("button", { name: "Debug batch", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Start live debug batch", exact: true })).toBeVisible();
    await page.getByLabel("Batch name").fill(label);
    await page.getByLabel("Target projects").fill("5");
    if (baseline) {
      await page.getByLabel("Baseline batch").selectOption(baseline);
    }
    await page.getByRole("button", { name: "Start batch", exact: true }).click();
    await expect(page.getByText(new RegExp(`Debug batch: ${label}`))).toBeVisible();
  }

  async function createFixtureProject(page: Page, prompt: string) {
    const name = `Fixture ${prompt.slice(0, 18)}`;
    const response = await page.request.post("/api/projects", {
      data: { name, original_intent: prompt },
    });
    expect(response.ok()).toBeTruthy();
    await page.reload();
  }

  test("developer visibility is controlled by the backend capability", async ({ page }) => {
    await page.route("**/api/capabilities", async (route) => {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ developer_tools_enabled: false }) });
    });
    await page.reload();
    await expect(page.getByRole("button", { name: "Debug batch", exact: true })).toHaveCount(0);
    await page.screenshot({ path: "test-results/debug-batch-feature-disabled.png", fullPage: true });
  });

  test("starts a batch and preserves the active banner", async ({ page }) => {
    await startBatch(page, "fixture-live-01");
    await expect(page.getByText("0 of 5 projects", { exact: false })).toBeVisible();
    await page.screenshot({ path: "test-results/debug-batch-start-modal.png", fullPage: true });
    await expect(page.getByRole("heading", { name: "fixture-live-01", exact: true })).toBeVisible();
    await page.screenshot({ path: "test-results/debug-batch-empty-drawer.png", fullPage: true });
  });

  test("creates ordered members and shows high-level outcomes", async ({ page }) => {
    await startBatch(page, "fixture-live-02");
    await closeBatchDrawer(page);
    await createFixtureProject(page, "Create a simple 20 mm fixture plate.");
    await createFixtureProject(page, "Create a second simple fixture plate.");
    const active = await page.request.get("/api/debug-batches?state=active").then((response) => response.json());
    expect(active[0].memberships).toHaveLength(2);
    await page.getByRole("button", { name: "View batch", exact: true }).click();
    await expect(page.getByRole("heading", { name: "fixture-live-02", exact: true })).toBeVisible();
    await expect(page.getByText(/Not started|Working version created|In progress/).first()).toBeVisible();
    await page.screenshot({ path: "test-results/debug-batch-drawer-two-projects.png", fullPage: true });
  });

  test("finishes and produces a redacted result without browser Codex execution", async ({ page }) => {
    await startBatch(page, "fixture-live-03");
    await page.locator(".debug-batch-drawer").getByRole("button", { name: "Finish batch", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Finish debug batch?", exact: true })).toBeVisible();
    await page.screenshot({ path: "test-results/debug-batch-finish-confirmation.png", fullPage: true });
    const codexRequests: string[] = [];
    page.on("request", (request) => { if (request.url().toLowerCase().includes("codex")) codexRequests.push(request.url()); });
    await page.getByRole("button", { name: "Finish batch", exact: true }).last().click();
    await expect(page.getByRole("heading", { name: "Debug batch complete", exact: true })).toBeVisible();
    expect(codexRequests).toEqual([]);
    await page.screenshot({ path: "test-results/debug-batch-complete-result.png", fullPage: true });
  });

  test("starts a frozen-baseline comparison and marks matching identities controlled", async ({ page }) => {
    await startBatch(page, "fixture-baseline");
    await page.locator(".debug-batch-drawer").getByRole("button", { name: "Finish batch", exact: true }).click();
    await page.getByRole("button", { name: "Finish batch", exact: true }).last().click();
    await expect(page.getByRole("heading", { name: "Debug batch complete", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Start comparison batch", exact: true }).click();
    await page.getByLabel("Batch name").fill("fixture-comparison");
    await expect(page.getByLabel("Baseline batch")).not.toHaveValue("");
    await page.getByRole("button", { name: "Start batch", exact: true }).click();
    await page.locator(".debug-batch-drawer").getByRole("button", { name: "Finish batch", exact: true }).click();
    await page.getByRole("button", { name: "Finish batch", exact: true }).last().click();
    await expect(page.getByText(/Controlled comparison/).last()).toBeVisible();
    await page.screenshot({ path: "test-results/debug-batch-comparison-result.png", fullPage: true });
  });
});
