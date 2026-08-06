import { expect, test } from "@playwright/test";

test.skip(
  (process.env.VITE_VOLUNDR_VALIDATED_CADQUERY_FLOW_ENABLED ?? "false").toLowerCase() !== "true",
  "validated clarification scenario; run with VITE_VOLUNDR_VALIDATED_CADQUERY_FLOW_ENABLED=true",
);

test("keeps clarification in the normal conversation workflow and deduplicates duplicate submits", async ({ page }) => {
  let clarificationRequests = 0;
  const clarificationKeys: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().includes("/validated-cadquery/workflows/") && request.url().endsWith("/clarification")) {
      clarificationRequests += 1;
      clarificationKeys.push(request.headers()["idempotency-key"] ?? "");
    }
  });

  await page.goto("/?testing_session=true&test_scenario_id=validated-clarification");
  await page.getByLabel("AI chat message").fill("Create a holder for my device.");
  await page.getByRole("button", { name: "Send" }).click();

  await expect(page).toHaveURL(/\/projects\/[^/]+\/designs\/[^/]+$/);
  const workflowUrl = page.url();
  const question = "What is the maximum available height?";
  await expect(page.getByText(question, { exact: true })).toBeVisible();
  await page.reload();
  await expect(page).toHaveURL(workflowUrl);
  await expect(page.getByText(question, { exact: true })).toBeVisible();
  const answer = page.getByLabel(question);
  await answer.fill("45 mm");
  const submit = page.getByRole("button", { name: "Submit detail" });
  await submit.evaluate((button) => {
    button.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, view: window }));
    button.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, view: window }));
  });

  await expect(page.getByText("Ready to review", { exact: true })).toBeVisible();
  await expect(page).toHaveURL(workflowUrl);
  expect(clarificationRequests).toBe(2);
  expect(new Set(clarificationKeys)).toEqual(new Set([clarificationKeys[0]]));
  expect(clarificationKeys[0]).toMatch(/^[0-9a-f-]{36}$/i);
});
