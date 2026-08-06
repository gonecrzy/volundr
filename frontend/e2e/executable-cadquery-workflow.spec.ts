import { expect, test } from "@playwright/test";

test.skip(
  (process.env.VITE_VOLUNDR_EXECUTABLE_CADQUERY_FLOW_ENABLED ?? "false").toLowerCase() !== "true",
  "executable CadQuery fixture suite; run with the experimental flag",
);

test("shows the complete-source model and accepts one bounded pocket revision", async ({ page }) => {
  await page.goto("/?testing_session=true&test_scenario_id=executable-cadquery");
  await page.getByLabel("AI chat message").fill(
    "Create a mounting bracket with a body 80 mm wide, 50 mm deep, and 8 mm thick. Add four 5 mm through-holes with each mounting-hole center 8 mm from its nearest edge. Add a centered recessed pocket 40 mm wide, 20 mm deep, and 3 mm deep. Add one asymmetric 10 mm through-hole centered 18 mm from the left edge and 25 mm from the lower edge. Add a 2 mm external fillet where geometrically valid.",
  );
  await page.getByRole("button", { name: "Send" }).click();

  await expect(page).toHaveURL(/\/projects\/[^/]+\/designs\/[^/]+$/, { timeout: 30_000 });
  await expect(page.getByLabel("Validated design workflow").getByText("Ready to review", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Executable CadQuery experiment", exact: true })).toBeVisible();
  await expect(page.getByText("Gemini supplied a complete CadQuery source file.")).toBeVisible();
  await expect(page.getByLabel("Validated printable outputs").getByRole("article")).toHaveCount(1);
  await expect(page.locator("canvas").first()).toBeVisible();

  await page.getByRole("button", { name: "Accept candidate" }).click();
  await expect(page.getByRole("link", { name: "Download design package" })).toBeVisible();

  await page.getByLabel("What should change?").fill(
    "Increase the centered recessed pocket to 46 mm × 24 mm while preserving the body dimensions, all five hole diameters, all hole-center positions, body thickness, and output identity.",
  );
  await page.getByLabel("New dimension value (optional)").fill("46 × 24 mm");
  await page.getByRole("button", { name: "Start revision" }).click();
  await expect(page.getByText("Revision ready to review", { exact: true })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("Output identity preserved for this revision.", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Accept candidate" }).click();
  await expect(page.getByRole("link", { name: "Download design package" })).toBeVisible({ timeout: 10_000 });
  await expect(page.locator("canvas").first()).toBeVisible();
});
