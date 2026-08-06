import { expect, test } from "@playwright/test";

test.skip(
  (process.env.VITE_VOLUNDR_VALIDATED_CADQUERY_FLOW_ENABLED ?? "false").toLowerCase() !== "true",
  "validated authentication boundary scenario; run with VITE_VOLUNDR_VALIDATED_CADQUERY_FLOW_ENABLED=true",
);

test("allows proxied browser traffic but rejects caller-selected direct identity", async ({ page }) => {
  await page.goto("/?testing_session=true&test_scenario_id=validated-auth-boundary");
  await expect(page.getByLabel("AI chat message")).toBeVisible();

  const response = await page.request.post(
    `http://127.0.0.1:${process.env.VOLUNDR_E2E_PORT}/api/validated-cadquery/designs`,
    {
      headers: {
        Authorization: "Bearer caller-selected-token",
        "X-Volundr-Actor-Id": "caller-selected-actor",
      },
      data: { name: "Unauthorized probe", intent: "Must not enter the validated route." },
    },
  );
  expect(response.status()).toBe(401);
});
