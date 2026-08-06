import { expect, test, type Page } from "@playwright/test";
import fs from "node:fs/promises";
import path from "node:path";
import { installBrowserQualityChecks, liveEnabled } from "./liveEnvironment";

const intent =
  "Create one compact asymmetric mounting plate with explicit dimensions: 96 mm wide, 64 mm deep, and 4 mm thick. Add two feature types: three mounting holes and one recessed irregular slot arrangement. Place the features asymmetrically and keep exactly one printable output.";

async function readWorkflow(page: Page, projectId: string, workflowId: string) {
  const response = await page.request.get(`/api/validated-cadquery/projects/${projectId}/designs/${workflowId}`);
  expect(response.ok(), "durable validated workflow read").toBeTruthy();
  return response.json();
}

test.describe.serial("validated product shell live smoke", () => {
  test.skip(
    !liveEnabled || process.env.VITE_VOLUNDR_VALIDATED_CADQUERY_FLOW_ENABLED !== "true",
    "Opt-in validated product-shell live smoke.",
  );

  test("creates one design, accepts one bounded revision, and preserves package history", async ({ page }, testInfo) => {
    test.setTimeout(1_200_000);
    const quality = installBrowserQualityChecks(page);
    const liveDataDir = process.env.VOLUNDR_LIVE_DATA_DIR;
    expect(liveDataDir, "live data directory").toBeTruthy();
    const markerPath = path.join(liveDataDir!, "validated-product-shell-restart-marker.json");
    const designRequestKeys: string[] = [];
    const workflowIds: string[] = [];

    page.on("request", (request) => {
      const url = new URL(request.url());
      if (request.method() === "POST" && url.pathname === "/api/validated-cadquery/designs") {
        designRequestKeys.push(request.headers()["idempotency-key"] ?? "");
        void fs.writeFile(markerPath, JSON.stringify({
          schema_version: "validated-product-shell-restart-marker-v1",
          created_at: new Date().toISOString(),
          boundary: "browser_creation_request_started",
        }), "utf-8");
      }
    });

    await page.goto("/");
    await page.getByLabel("AI chat message").fill(intent);
    await page.getByRole("button", { name: "Send", exact: true }).click();

    await expect(page).toHaveURL(/\/projects\/[^/]+\/designs\/[^/]+$/);
    await expect(page.getByRole("heading", { name: "Validated design", exact: true })).toBeVisible();
    const route = new URL(page.url());
    const [, projectId, workflowId] = route.pathname.match(/^\/projects\/([^/]+)\/designs\/([^/]+)$/) ?? [];
    expect(projectId).toBeTruthy();
    expect(workflowId).toBeTruthy();
    workflowIds.push(workflowId);
    expect(designRequestKeys).toHaveLength(1);
    expect(designRequestKeys[0]).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i);

    if (await page.getByText("A detail is needed", { exact: true }).count()) {
      const clarification = page.locator('[aria-label="Validated design workflow"] input').last();
      await clarification.fill("Use millimeters, preserve the one-output limit, and keep the specified dimensions authoritative.");
      await page.getByRole("button", { name: "Submit detail", exact: true }).click();
    }

    await expect(page.getByText("Ready to review", { exact: true })).toBeVisible({ timeout: 900_000 });
    const initialWorkflow = await readWorkflow(page, projectId, workflowId);
    expect(initialWorkflow.state).toBe("candidate_ready");
    expect(initialWorkflow.outputs).toHaveLength(1);
    expect(initialWorkflow.requirements).toBeTruthy();
    expect(initialWorkflow.plan).toBeTruthy();
    expect(initialWorkflow.provenance?.provider).toBe("gemini_api");
    expect(initialWorkflow.outputs[0].artifact_available).toBe(true);
    expect(initialWorkflow.outputs[0].semantic_verification).toBeTruthy();

    const initialRuns = await page.request.get(`/api/projects/${projectId}/workflow-runs`).then((response) => response.json());
    const initialAttempts = await page.request.get(`/api/projects/${projectId}/generation-attempts`).then((response) => response.json());
    expect(initialRuns.length, "initial durable workflow runs").toBeGreaterThan(0);
    expect(initialAttempts.length, "initial provider attempts").toBeGreaterThan(0);
    expect(initialAttempts.every((attempt: { provider: string }) => attempt.provider === "gemini_api")).toBe(true);

    await page.getByRole("button", { name: "Accept candidate", exact: true }).click();
    await expect(page.getByRole("link", { name: "Download design package", exact: true })).toBeVisible({ timeout: 120_000 });
    const packageDownload = await Promise.all([
      page.waitForEvent("download"),
      page.getByRole("link", { name: "Download design package", exact: true }).click(),
    ]);
    expect((await packageDownload[0].suggestedFilename()).toLowerCase()).toMatch(/^validated-cadquery-.*\.zip$/);

    await page.getByLabel("What should change?").fill(
      "Add one bounded recessed 8 mm by 4 mm slot near the upper-right feature group while preserving the three mounting holes, the one-output identity, and all protected dimensions.",
    );
    await page.getByLabel("New dimension value (optional)").fill("100 mm");
    await page.getByRole("button", { name: "Start revision", exact: true }).click();
    await expect(page.getByText("Revision ready to review", { exact: true })).toBeVisible({ timeout: 900_000 });

    const revisionUrl = page.url();
    const revisionRoute = new URL(revisionUrl);
    const [, revisionProjectId, revisionWorkflowId] = revisionRoute.pathname.match(/^\/projects\/([^/]+)\/designs\/([^/]+)$/) ?? [];
    expect(revisionProjectId).toBe(projectId);
    expect(revisionWorkflowId).not.toBe(workflowId);
    workflowIds.push(revisionWorkflowId);
    const revisedWorkflow = await readWorkflow(page, projectId, revisionWorkflowId);
    expect(revisedWorkflow.state).toBe("revision_ready");
    expect(revisedWorkflow.parent_workflow_id).toBe(workflowId);
    expect(revisedWorkflow.outputs.map((output: { output_id: string }) => output.output_id)).toEqual(initialWorkflow.outputs.map((output: { output_id: string }) => output.output_id));
    expect(revisedWorkflow.provenance?.protected_facts).toBeTruthy();
    expect(revisedWorkflow.provenance?.provider).toBe("gemini_api");
    expect(revisedWorkflow.outputs[0].artifact_available).toBe(true);

    await page.goBack();
    await expect(page).toHaveURL(/\/projects\/[^/]+\/designs\/[^/]+$/);
    await expect(page.getByText("Ready to review", { exact: true })).toBeVisible();
    await page.goForward();
    await expect(page).toHaveURL(revisionUrl);
    await expect(page.getByText("Revision ready to review", { exact: true })).toBeVisible();
    await page.reload();
    await expect(page).toHaveURL(revisionUrl);
    await expect(page.getByText("Revision ready to review", { exact: true })).toBeVisible();

    await page.getByRole("button", { name: "Accept candidate", exact: true }).click();
    await expect(page.getByRole("link", { name: "Download design package", exact: true })).toBeVisible({ timeout: 120_000 });
    const revisedPackage = await page.request.get(`/api/validated-cadquery/projects/${projectId}/designs/${revisionWorkflowId}/artifacts`);
    expect(revisedPackage.ok()).toBeTruthy();
    const artifacts = await revisedPackage.json();
    expect(artifacts.some((artifact: { kind: string; available: boolean }) => artifact.kind === "design_package" && artifact.available)).toBe(true);

    const finalRuns = await page.request.get(`/api/projects/${projectId}/workflow-runs`).then((response) => response.json());
    const finalAttempts = await page.request.get(`/api/projects/${projectId}/generation-attempts`).then((response) => response.json());
    expect(finalRuns.length).toBeGreaterThan(initialRuns.length);
    expect(finalAttempts.length).toBeGreaterThan(initialAttempts.length);
    expect(finalAttempts.every((attempt: { provider: string }) => attempt.provider === "gemini_api")).toBe(true);

    await fs.writeFile(path.join(liveDataDir!, "validated-product-shell-browser-evidence.json"), JSON.stringify({
      schema_version: "validated-product-shell-browser-evidence-v1",
      project_id: projectId,
      workflow_ids: workflowIds,
      one_creation_request: designRequestKeys.length === 1,
      initial_state: initialWorkflow.state,
      revised_state: revisedWorkflow.state,
      output_ids_preserved: revisedWorkflow.outputs.map((output: { output_id: string }) => output.output_id),
      initial_run_count: initialRuns.length,
      final_run_count: finalRuns.length,
      initial_attempt_count: initialAttempts.length,
      final_attempt_count: finalAttempts.length,
      package_available: true,
      browser_quality: quality.snapshot(),
      test_output_directory: testInfo.outputDir,
    }, null, 2), "utf-8");
    await quality.assertClean();
  });
});
