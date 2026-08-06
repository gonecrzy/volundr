import { expect, test } from "@playwright/test";

test.skip(
  (process.env.VITE_VOLUNDR_VALIDATED_CADQUERY_FLOW_ENABLED ?? "false").toLowerCase() !== "true",
  "validated partial-output scenario; run with VITE_VOLUNDR_VALIDATED_CADQUERY_FLOW_ENABLED=true",
);

test("keeps a successful sibling downloadable while withholding complete-candidate acceptance", async ({ page }) => {
  await page.request.post("/api/test-fixture/scenarios/configure-validated?mode=partial_output_failure");
  await page.goto("/?testing_session=true&test_scenario_id=validated-partial");
  await page.getByLabel("AI chat message").fill("Create a two-part electronics enclosure.");
  await page.getByRole("button", { name: "Send" }).click();

  await expect(page.getByText("Partially complete", { exact: true })).toBeVisible();
  const outputArea = page.getByLabel("Validated outputs");
  await expect(outputArea.getByRole("article")).toHaveCount(2);
  await expect(outputArea.getByText("Ready", { exact: true })).toBeVisible();
  await expect(outputArea.getByText("Could not finish building", { exact: true })).toBeVisible();
  await expect(page.getByText("Incomplete package unavailable until every required output passes.", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Accept candidate" })).toHaveCount(0);
  await expect(outputArea.getByRole("link", { name: "STL" })).toBeVisible();
});
