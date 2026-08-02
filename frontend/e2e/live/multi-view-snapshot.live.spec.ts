import { expect, test } from "@playwright/test";
import {
  installBrowserQualityChecks,
  liveEnabled,
  waitForWorkflowOutcome,
} from "./liveEnvironment";

test.describe("live deterministic multi-view snapshot evidence", () => {
  test.skip(!liveEnabled, "Opt-in live suite; set VOLUNDR_RUN_LIVE_E2E=true.");

  test("records the exact spacer request and one requirement revision", async ({ page }, testInfo) => {
    const quality = installBrowserQualityChecks(page);
    const initialRequest =
      "Create a rectangular spacer plate that is 80 mm wide, 45 mm tall, and 6 mm thick. Add two through-holes, each 5 mm in diameter. Place the first hole center 12 mm from the left edge and centered vertically. Place the second hole center 18 mm from the right edge and centered vertically. Round the four outside corners with a 2 mm radius. Produce one printable part.";
    const revisionRequest =
      "Increase the plate thickness from 6 mm to 8 mm and move the left hole 3 mm to the right. Preserve the plate width, height, right-hole position, hole diameters, and corner fillets.";

    await page.goto("/?testScenario=multi-view-snapshot-live");
    const draftResponsePromise = page.waitForResponse(
      (response) => response.url().endsWith("/api/projects/draft") && response.request().method() === "POST",
    );
    let projectId = "";
    const chatResponsePromise = page.waitForResponse(
      (response) => response.url().endsWith(`/api/projects/${projectId}/chat`) && response.request().method() === "POST",
    );
    await page.getByLabel("AI chat message").fill(initialRequest);
    await page.getByRole("button", { name: "Send", exact: true }).click();
    projectId = (await (await draftResponsePromise).json()).id as string;
    const initialChat = await chatResponsePromise;
    const initialChatText = await initialChat.text();
    expect(initialChat.ok(), `initial chat progression: ${initialChatText}`).toBeTruthy();
    const initialChatPayload = JSON.parse(initialChatText) as Record<string, unknown>;

    const planResponse = await page.request.get(`/api/projects/${projectId}/design-plan`);
    const planText = await planResponse.text();
    expect(planResponse.ok(), `direct brief was persisted: ${planText}`).toBeTruthy();
    const plan = JSON.parse(planText) as Record<string, unknown>;
    expect(["cad-brief-v1", "compact-cad-plan-v1"]).toContain(plan.schema_version);

    const initialOutcome = await waitForWorkflowOutcome(page);
    const initialRevisions = await page.request.get(`/api/projects/${projectId}/revisions`).then((response) => response.json());
    const initialRevision = initialRevisions.at(-1) as Record<string, any> | undefined;
    expect(initialRevision, "initial revision exists").toBeTruthy();
    const initialSnapshot = initialRevision
      ? await page.request.get(`/api/revisions/${String(initialRevision.id)}/snapshots`)
      : null;
    const initialPacketResponse = initialSnapshot?.ok() ? await initialSnapshot.json() : null;
    const initialPacket = initialPacketResponse?.schema_version ? initialPacketResponse : null;
    const initialOutputs = initialRevision
      ? await page.request.get(`/api/revisions/${String(initialRevision.id)}/outputs`).then((response) => response.json())
      : [];
    const initialWorkerReached = initialOutputs.some((output: Record<string, any>) => output.execution_state !== "pending");

    const evidence: Record<string, unknown> = {
      project_id: projectId,
      initial_request: initialRequest,
      initial_route: initialChatPayload.planning_depth ?? plan.planning_depth ?? null,
      initial_plan: plan,
      initial_outcome: initialOutcome,
      initial_revision: initialRevision,
      initial_worker_reached: initialWorkerReached,
      initial_outputs: initialOutputs,
      initial_snapshot_status: initialSnapshot?.status() ?? null,
      initial_snapshot: initialPacket,
      revision_request: revisionRequest,
    };

    if (initialOutcome !== "candidate" || !initialRevision || initialRevision.is_accepted !== true) {
      await testInfo.attach("multi-view-snapshot-live-evidence.json", {
        body: JSON.stringify({ ...evidence, revision_skipped: "No accepted current working version was produced." }, null, 2),
        contentType: "application/json",
      });
      await collectSnapshotApiEvidence(page, projectId, initialOutcome, testInfo, evidence, quality.snapshot());
      await quality.assertClean();
      return;
    }

    expect(initialSnapshot?.ok(), "successful worker geometry has a snapshot packet").toBeTruthy();
    const packet = initialPacket as Record<string, any>;
    expect(packet.views.length).toBeGreaterThanOrEqual(4);
    expect(packet.timing.total_ms).toBeGreaterThan(0);
    expect(packet.views.every((view: Record<string, unknown>) => view.image_hash)).toBeTruthy();

    const exportResponse = await page.request.post(`/api/projects/${projectId}/exports`, {
      data: { export_type: "project_package", revision_id: initialRevision.id },
    });
    evidence.initial_export = {
      status: exportResponse.status(),
      body: exportResponse.ok() ? await exportResponse.json() : await exportResponse.text(),
    };

    await page.getByLabel("AI chat message").fill(revisionRequest);
    await page.getByRole("button", { name: "Send", exact: true }).click();
    await expect.poll(
      async () => (await page.request.get(`/api/projects/${projectId}/revisions`).then((response) => response.json())).length,
      { timeout: 240_000, intervals: [1_000, 2_000, 5_000] },
    ).toBeGreaterThan(1);
    const revisions = await page.request.get(`/api/projects/${projectId}/revisions`).then((response) => response.json());
    await expect.poll(
      async () => (await page.request.get(`/api/projects/${projectId}/revisions`).then((response) => response.json())).at(-1).status,
      { timeout: 240_000, intervals: [1_000, 2_000, 5_000] },
    ).toMatch(/succeeded|failed/);
    const settledRevisions = await page.request.get(`/api/projects/${projectId}/revisions`).then((response) => response.json());
    const settledRevision = settledRevisions.at(-1) as Record<string, any>;
    const comparisonResponse = await page.request.get(`/api/revisions/${String(settledRevision.id)}/comparison`);
    const revisedSnapshotResponse = await page.request.get(`/api/revisions/${String(settledRevision.id)}/snapshots`);
    const revisedPacketResponse = revisedSnapshotResponse.ok() ? await revisedSnapshotResponse.json() : null;
    const revisedPacket = revisedPacketResponse?.schema_version ? revisedPacketResponse : null;
    const comparisonResponseBody = comparisonResponse.ok() ? await comparisonResponse.json() : null;
    const comparison = comparisonResponseBody?.schema_version ? comparisonResponseBody : null;
    evidence.revision = {
      revision: settledRevision,
      revisions,
      snapshot_status: revisedSnapshotResponse.status(),
      snapshot: revisedPacket,
      comparison_status: comparisonResponse.status(),
      comparison,
    };
    expect(settledRevision.parent_revision_id).toBe(initialRevision.id);
    if (revisedSnapshotResponse.ok() && revisedPacket) {
      expect(revisedPacket.packet_hash).toBeTruthy();
      expect(comparisonResponse.ok(), "revision snapshot comparison is durable").toBeTruthy();
    }

    await testInfo.attach("multi-view-snapshot-live-evidence.json", {
      body: JSON.stringify(evidence, null, 2),
      contentType: "application/json",
    });
    await collectSnapshotApiEvidence(page, projectId, "candidate", testInfo, evidence, quality.snapshot());
    await quality.assertClean();
  });
});

async function collectSnapshotApiEvidence(
  page: import("@playwright/test").Page,
  projectId: string,
  finalState: string,
  testInfo: import("@playwright/test").TestInfo,
  evidence: Record<string, unknown>,
  browserQuality: unknown,
): Promise<void> {
  const [runsResponse, attemptsResponse, revisionsResponse] = await Promise.all([
    page.request.get(`/api/projects/${projectId}/workflow-runs`),
    page.request.get(`/api/projects/${projectId}/generation-attempts`),
    page.request.get(`/api/projects/${projectId}/revisions`),
  ]);
  const runs = runsResponse.ok() ? await runsResponse.json() : [];
  const attempts = attemptsResponse.ok() ? await attemptsResponse.json() : [];
  const revisions = revisionsResponse.ok() ? await revisionsResponse.json() : [];
  const latestRevision = revisions.at(-1) as Record<string, any> | undefined;
  const outputs = latestRevision
    ? await page.request.get(`/api/revisions/${String(latestRevision.id)}/outputs`).then((response) => response.ok() ? response.json() : [])
    : [];
  evidence.final_state = finalState;
  evidence.workflow_runs = runs;
  evidence.provider_attempts = attempts;
  evidence.revisions = revisions;
  evidence.latest_outputs = outputs;
  evidence.browser_quality = browserQuality;
  await testInfo.attach("multi-view-snapshot-live-api-evidence.json", {
    body: JSON.stringify(evidence, null, 2),
    contentType: "application/json",
  });
}
