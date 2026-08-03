import { expect, test, type Page } from "@playwright/test";

test.skip(
  (process.env.VITE_VOLUNDR_CHAT_FIRST ?? "true").toLowerCase() !== "true",
  "geometry-slot observability is covered by the chat-first workflow",
);

test.describe.configure({ mode: "serial" });

async function openTechnicalDetails(page: Page) {
  const viewportWidth = await page.evaluate(() => window.innerWidth);
  if (viewportWidth < 1000) {
    await page.getByRole("button", { name: "Model", exact: true }).click();
  } else if (viewportWidth < 1280) {
    await page.getByRole("button", { name: "Details", exact: true }).click();
  }
  const details = viewportWidth >= 1000 && viewportWidth < 1280
    ? page.getByLabel("Design details")
    : page.getByLabel("Design summary");
  await details.getByText("Technical details", { exact: true }).click();
  return { details, viewportWidth };
}

test("direct generation exposes the selected geometry contract without duplicate chat progress", async ({ page }) => {
  await page.goto("/?testing_session=true&testScenario=geometry-slots-direct");
  await page.getByLabel("AI chat message").fill("Create an 80 mm mounting plate.");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByText("Version 1", { exact: true }).first()).toBeVisible();

  const { details } = await openTechnicalDetails(page);
  await expect(details.getByText("Geometry contract:").locator("..")).toContainText("volundr-geometry-slots-v1");
  await expect(details.getByText("focused completion call")).toHaveCount(0);
  const conversation = page.getByRole("region", { name: "Conversation" });
  await expect(conversation.getByRole("article")).toHaveCount(2);
  await expect(conversation.getByRole("article").last()).not.toContainText(/slot|completion call|fallback/i);

  await page.screenshot({
    path: "../data/debug-sessions/geometry-slots-deterministic/direct-1440x900.png",
    fullPage: true,
  });
});

test("compact generation retains one user-facing outcome and reports slot telemetry in technical details", async ({ page }) => {
  await page.goto("/?testing_session=true&testScenario=geometry-slots-compact");
  await page.getByLabel("AI chat message").fill("Create a holder for my 70 mm wide device.");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByText("What is the maximum available height?", { exact: true })).toBeVisible();

  await page.getByLabel("AI chat message").fill("45 mm");
  await page.getByRole("button", { name: "Answer" }).click();
  await expect(page.getByText("Version 1", { exact: true }).first()).toBeVisible();

  const { details } = await openTechnicalDetails(page);
  await expect(details.getByText("Geometry contract:").locator("..")).toContainText("volundr-geometry-slots-v1");
  const conversation = page.getByRole("region", { name: "Conversation" });
  await expect(conversation.getByRole("article")).toHaveCount(4);
  await expect(conversation.getByRole("article").last()).not.toContainText(/slot|completion call|fallback/i);

  await page.screenshot({
    path: "../data/debug-sessions/geometry-slots-deterministic/compact-1440x900.png",
    fullPage: true,
  });
});
