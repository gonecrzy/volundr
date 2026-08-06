import { expect, test } from "@playwright/test";

const locatorFixture = `<!doctype html>
  <html><body>
    <main>
      <section aria-label="Conversation"><span>Ready to review</span></section>
      <section aria-label="Candidate review">
        <h2>New version</h2>
        <span class="review-state">Ready to review</span>
        <button type="button" data-revision-id="candidate-r1">Accept candidate</button>
        <output aria-label="Acceptance state"></output>
      </section>
    </main>
    <script>
      document.querySelector('[data-revision-id="candidate-r1"]').addEventListener('click', (event) => {
        const button = event.currentTarget;
        button.dataset.accepted = 'true';
        document.querySelector('[aria-label="Acceptance state"]').textContent = 'candidate-r1 accepted';
      });
    </script>
  </body></html>`;

test("candidate-review status and acceptance locators remain scoped and provider-free", async ({ page }) => {
  const providerRequests: string[] = [];
  page.on("request", (request) => {
    const pathname = new URL(request.url()).pathname;
    if (/gemini|generateContent|provider/i.test(pathname)) providerRequests.push(pathname);
  });
  await page.route("**/__candidate-review-locator__", (route) => route.fulfill({
    status: 200,
    contentType: "text/html",
    body: locatorFixture,
  }));

  await page.goto("/__candidate-review-locator__");
  const conversation = page.getByRole("region", { name: "Conversation", exact: true });
  const candidateReview = page.getByRole("region", { name: "Candidate review", exact: true });
  await expect(page.getByText("Ready to review", { exact: true })).toHaveCount(2);
  await expect(conversation.getByText("Ready to review", { exact: true })).toHaveCount(1);
  await expect(candidateReview).toHaveCount(1);
  await expect(candidateReview.getByText("Ready to review", { exact: true })).toHaveCount(1);
  const accept = candidateReview.getByRole("button", { name: "Accept candidate", exact: true });
  await expect(accept).toHaveCount(1);
  await accept.click();
  await expect(candidateReview.getByLabel("Acceptance state")).toHaveText("candidate-r1 accepted");
  await expect(accept).toHaveAttribute("data-accepted", "true");

  await page.reload();
  const refreshedReview = page.getByRole("region", { name: "Candidate review", exact: true });
  await expect(refreshedReview.getByText("Ready to review", { exact: true })).toHaveCount(1);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(refreshedReview.getByText("Ready to review", { exact: true })).toHaveCount(1);
  await page.setViewportSize({ width: 1440, height: 900 });
  await expect(refreshedReview.getByText("Ready to review", { exact: true })).toHaveCount(1);
  expect(providerRequests).toEqual([]);
});
