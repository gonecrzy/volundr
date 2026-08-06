import { expect, test } from "@playwright/test";

test.skip(
  (process.env.VITE_VOLUNDR_VALIDATED_CADQUERY_FLOW_ENABLED ?? "false").toLowerCase() === "true",
  "disabled validated-flow scenario; run with the default feature flag",
);

test("keeps the legacy workspace and rejects direct validated creation when disabled", async ({ page }) => {
  await page.goto("/?testing_session=true&test_scenario_id=validated-disabled");

  await expect(page.locator("main.chat-workspace")).toBeVisible();
  await expect(page.getByRole("region", { name: "Validated design workflow" })).toHaveCount(0);
  await expect(page.getByLabel("AI chat message")).toBeVisible();

  const directResponse = await page.request.post(
    `http://127.0.0.1:${process.env.VOLUNDR_E2E_PORT}/api/validated-cadquery/designs`,
    { data: { name: "Disabled probe", intent: "Must remain on the legacy route." } },
  );
  expect(directResponse.status()).toBe(404);
});
