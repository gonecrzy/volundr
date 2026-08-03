import { expect, test } from "@playwright/test";
import fs from "node:fs/promises";
import path from "node:path";
import { finishBatch, liveDataDir, PROJECTS, runProject, startBatch } from "./mixed-cad-batches.live.spec";
import { liveEnabled } from "./liveEnvironment";

test.describe.serial("mixed CAD post-correction verification", () => {
  test.skip(
    !liveEnabled || process.env.VOLUNDR_RUN_CORRECTION_E2E !== "true",
    "Opt-in post-correction live suite; set VOLUNDR_RUN_CORRECTION_E2E=true.",
  );

  test("runs one unchanged post-correction five-project batch", async ({ page }) => {
    test.setTimeout(1_800_000);
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/");

    const batchId = await startBatch(
      page,
      "mixed-cad-live-correction-01",
      "Post-correction verification of the same five mixed-CAD prompts; not a controlled provider comparison.",
      undefined,
      "mixed-cad-correction-01",
    );
    const projects = [];
    for (let index = 0; index < PROJECTS.length; index += 1) {
      projects.push(await runProject(page, batchId, "mixed-cad-correction-01", PROJECTS[index], index + 1));
    }
    const report = await finishBatch(page, batchId, "mixed-cad-correction-01");
    const reportResponse = await page.request.get(`/api/debug-batches/${batchId}/report`);
    expect(reportResponse.ok(), "post-correction report").toBeTruthy();
    const refreshed = await reportResponse.json() as { batch: { identity_complete: boolean }; summary: { provider_behavior: Record<string, number> } };
    expect(refreshed.batch.identity_complete, "complete post-correction identities").toBe(true);
    expect(refreshed.summary.provider_behavior.generation_attempts).toBeGreaterThan(0);

    const root = path.join(liveDataDir, "data", "debug-sessions", batchId);
    await fs.writeFile(
      path.join(root, "live-batch-manifest.json"),
      JSON.stringify({ batch_id: batchId, projects, report, comparison_kind: "post-correction" }, null, 2),
      "utf-8",
    );
    const entries = await fs.readdir(root, { recursive: true, withFileTypes: true });
    for (const entry of entries) {
      if (!entry.isFile()) continue;
      const file = path.join(entry.parentPath, entry.name);
      const content = await fs.readFile(file, "utf-8");
      expect(content, `durable evidence path scan: ${file}`).not.toMatch(/(?:\/tmp\/|\/root\/|\/home\/|\/Users\/|GEMINI_API_KEY=|AIza[0-9A-Za-z_-]{10,}|authorization\s*[:=]|cookie\s*[:=])/i);
    }
  });
});
