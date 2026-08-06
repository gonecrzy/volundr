import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { installBrowserQualityChecks } from "./liveEnvironment";

const projectId = process.env.VOLUNDR_RESUME_PROJECT_ID ?? "";
const parentWorkflowId = process.env.VOLUNDR_RESUME_WORKFLOW_ID ?? "";
const parentRevisionId = process.env.VOLUNDR_RESUME_REVISION_ID ?? "";
const continuationEnabled = process.env.VOLUNDR_RESUME_EXISTING_CADQUERY === "true";
const revisionInstruction =
  "Increase the centered recessed pocket to 46 mm × 24 mm while preserving the body dimensions, all five hole diameters, all hole-center positions, body thickness, external fillet requirement, and output identity.";
const evidenceRoot = path.resolve("..", "data", "debug-sessions", "executable-cadquery");
const originalEvidenceRoot = path.join(evidenceRoot, "gemini-complete-source-01");

type Artifact = {
  artifact_id: string;
  kind: string;
  output_id?: string | null;
  filename: string;
  size_bytes: number;
  sha256: string;
  available: boolean;
  download_url?: string | null;
};

type Workflow = {
  id: string;
  project_id: string;
  parent_workflow_id?: string | null;
  parent_revision_id?: string | null;
  revision_id?: string | null;
  state: string;
  route: string;
  outputs: Array<Record<string, any>>;
  provenance: Record<string, any>;
  verification: Record<string, any>;
  diagnostics: Record<string, any>;
  package_manifest: Record<string, any>;
  package_available: boolean;
};

test.skip(!continuationEnabled, "Requires the persisted executable-CadQuery project and workflow IDs.");

function sha256(value: Buffer | string): string {
  return createHash("sha256").update(value).digest("hex");
}

async function readJson(page: Page, endpoint: string): Promise<any> {
  const response = await page.request.get(endpoint);
  expect(response.ok(), endpoint).toBeTruthy();
  return response.json();
}

async function readWorkflow(page: Page, workflowId: string): Promise<Workflow> {
  return readJson(page, `/api/validated-cadquery/projects/${projectId}/designs/${workflowId}`) as Promise<Workflow>;
}

async function readSourceHash(page: Page, revisionId: string): Promise<string> {
  const response = await page.request.get(`/api/revisions/${revisionId}/source`);
  expect(response.ok(), `source for ${revisionId}`).toBeTruthy();
  return sha256(await response.body());
}

async function readArtifacts(page: Page, workflowId: string): Promise<Artifact[]> {
  return readJson(page, `/api/validated-cadquery/projects/${projectId}/designs/${workflowId}/artifacts`) as Promise<Artifact[]>;
}

async function downloadArtifact(page: Page, artifact: Artifact): Promise<{ sha256: string; size_bytes: number }> {
  expect(artifact.available).toBe(true);
  expect(artifact.download_url).toBeTruthy();
  const response = await page.request.get(artifact.download_url!);
  expect(response.ok(), artifact.download_url!).toBeTruthy();
  const body = await response.body();
  expect(body.length).toBeGreaterThan(0);
  return { sha256: sha256(body), size_bytes: body.length };
}

async function downloadUiFile(page: Page, link: ReturnType<Page["getByRole"]>): Promise<{ sha256: string; size_bytes: number; entries?: string[] }> {
  const downloadPromise = page.waitForEvent("download");
  await link.click();
  const download = await downloadPromise;
  const downloadPath = await download.path();
  expect(downloadPath).toBeTruthy();
  const body = await fs.readFile(downloadPath!);
  expect(body.length).toBeGreaterThan(0);
  const result: { sha256: string; size_bytes: number; entries?: string[] } = {
    sha256: sha256(body),
    size_bytes: body.length,
  };
  if (/\.zip$/i.test(download.suggestedFilename())) {
    result.entries = execFileSync("unzip", ["-Z1", downloadPath!], { encoding: "utf8" })
      .split("\n")
      .map((entry) => entry.trim())
      .filter(Boolean);
  }
  return result;
}

function outputById(workflow: Workflow): Record<string, any> {
  const output = workflow.outputs.find((candidate) => candidate.output_id === "mounting_bracket");
  expect(output, "mounting_bracket output").toBeTruthy();
  return output!;
}

function isAccepted(workflow: Workflow, revisionId: string): boolean {
  return workflow.package_available && workflow.provenance?.accepted_revision_id === revisionId;
}

function semanticFinding(workflow: Workflow, requirementId: string): Record<string, any> {
  const findings = workflow.verification?.semantic_verification?.findings ?? workflow.provenance?.semantic_verification?.findings ?? [];
  const finding = findings.find((candidate: Record<string, any>) => candidate.requirement_id === requirementId);
  expect(finding, `${requirementId} semantic finding`).toBeTruthy();
  return finding!;
}

function assertRelativeManifest(manifest: Record<string, any>, revisionId: string): void {
  expect(manifest.project_id).toBe(projectId);
  expect(manifest.revision_id).toBe(revisionId);
  expect(manifest.outputs).toHaveLength(1);
  expect(manifest.outputs[0].output_id).toBe("mounting_bracket");
  const serialized = JSON.stringify(manifest);
  expect(serialized).not.toMatch(/(?:^|[" ])\/(?:root|tmp|home|Users)\//);
  for (const value of Object.values(manifest.outputs[0] as Record<string, unknown>)) {
    if (typeof value === "string" && /path/i.test(value)) {
      expect(value.startsWith("/")).toBe(false);
      expect(value.includes("..")).toBe(false);
    }
  }
}

function assertPackageManifest(manifest: Record<string, any>, revisionId: string, sourceHash: string): void {
  expect(manifest.revision_id).toBe(revisionId);
  expect(manifest.canonical_output_ids).toEqual(["mounting_bracket"]);
  expect(manifest.cadquery_source).toMatchObject({ path: "source/model.py", sha256: sourceHash });
  expect(JSON.stringify(manifest)).not.toMatch(/(?:^|[" ])\/(?:root|tmp|home|Users)\//);
  expect(JSON.stringify(manifest)).not.toMatch(/(?:GEMINI_API_KEY|Authorization|Bearer)/i);
  for (const artifact of manifest.artifacts as Array<Record<string, any>>) {
    expect(artifact.output_id).toBe("mounting_bracket");
    for (const kind of ["step", "stl", "brep"]) {
      const archivePath = artifact[kind]?.path;
      expect(typeof archivePath).toBe("string");
      expect(archivePath.startsWith("/")).toBe(false);
      expect(archivePath.includes("..")).toBe(false);
    }
  }
}

async function saveJson(filename: string, value: unknown): Promise<void> {
  await fs.mkdir(originalEvidenceRoot, { recursive: true });
  await fs.writeFile(path.join(originalEvidenceRoot, filename), `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

test("resumes, accepts, and revises the persisted executable-CadQuery candidate", async ({ page }) => {
  test.setTimeout(1_800_000);
  const quality = installBrowserQualityChecks(page);
  const creationRequests: string[] = [];
  const revisionRequests: string[] = [];
  page.on("request", (request) => {
    if (request.method() !== "POST") return;
    const pathname = new URL(request.url()).pathname;
    if (pathname === "/api/validated-cadquery/designs") creationRequests.push(pathname);
    if (pathname.endsWith("/revision") && pathname.includes("/api/validated-cadquery/workflows/")) revisionRequests.push(pathname);
  });

  expect(projectId).toBeTruthy();
  expect(parentWorkflowId).toBeTruthy();
  expect(parentRevisionId).toBeTruthy();
  const parentUrl = `/projects/${projectId}/designs/${parentWorkflowId}`;
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(parentUrl);

  const parent = await readWorkflow(page, parentWorkflowId);
  expect(parent.id).toBe(parentWorkflowId);
  expect(parent.project_id).toBe(projectId);
  expect(parent.revision_id).toBe(parentRevisionId);
  expect(parent.state).toBe("candidate_ready");
  expect(parent.route).toBe("validated_cadquery");
  expect(parent.provenance.source_hash).toBe("2f83eb9fbaa44298188d17c843daf8248047b479649e505cc55a7f98efd9c01c");
  expect(outputById(parent).artifact_available).toBe(true);

  const parentSourceHash = await readSourceHash(page, parentRevisionId);
  expect(parentSourceHash).toBe(parent.provenance.source_hash);
  const parentArtifacts = await readArtifacts(page, parentWorkflowId);
  const parentArtifactHashes: Record<string, string> = {};
  for (const kind of ["step", "stl", "brep"]) {
    const artifact = parentArtifacts.find((candidate) => candidate.kind === kind && candidate.output_id === "mounting_bracket");
    expect(artifact, `${kind} parent artifact`).toBeTruthy();
    const downloaded = await downloadArtifact(page, artifact!);
    expect(downloaded.sha256).toBe(artifact!.sha256);
    parentArtifactHashes[kind] = downloaded.sha256;
  }
  const parentManifest = await readJson(page, `/api/revisions/${parentRevisionId}/output-manifest`);
  assertRelativeManifest(parentManifest, parentRevisionId);

  const parentRunsBefore = await readJson(page, `/api/projects/${projectId}/workflow-runs`);
  const parentAttemptsBefore = await readJson(page, `/api/projects/${projectId}/generation-attempts`);
  const candidateReview = page.getByRole("region", { name: "Validated design workflow", exact: true });
  const conversation = page.getByRole("region", { name: "Conversation", exact: true });
  await expect(candidateReview).toHaveCount(1);
  await expect(candidateReview.getByText("Ready to review", { exact: true })).toHaveCount(1);
  await expect(conversation.getByText("Ready to review", { exact: true })).toHaveCount(1);
  await expect(page.getByRole("region", { name: "Validated design workflow", exact: true }).getByText("mounting_bracket", { exact: true })).toBeVisible();
  await expect(page.locator("canvas").first()).toBeVisible();
  await fs.mkdir(originalEvidenceRoot, { recursive: true });
  await page.screenshot({ path: path.join(originalEvidenceRoot, "original-model.png"), fullPage: true });

  const workflowPanel = page.getByRole("region", { name: "Validated design workflow", exact: true });
  await expect(workflowPanel.getByRole("button", { name: "Accept candidate", exact: true })).toHaveCount(1);
  await workflowPanel.getByRole("button", { name: "Accept candidate", exact: true }).click();
  await expect(workflowPanel.getByRole("link", { name: "Download design package", exact: true })).toBeVisible({ timeout: 120_000 });
  await expect.poll(async () => isAccepted(await readWorkflow(page, parentWorkflowId), parentRevisionId), { timeout: 120_000 }).toBe(true);
  const acceptedParent = await readWorkflow(page, parentWorkflowId);
  expect(acceptedParent.revision_id).toBe(parentRevisionId);
  expect(acceptedParent.provenance.accepted_revision_id).toBe(parentRevisionId);
  assertPackageManifest(acceptedParent.package_manifest, parentRevisionId, parentSourceHash);
  const activeParentRevision = await readJson(page, `/api/projects/${projectId}/active-revision`);
  expect(activeParentRevision.id).toBe(parentRevisionId);
  expect(activeParentRevision.is_accepted).toBe(true);
  const acceptedArtifacts = await readArtifacts(page, parentWorkflowId);
  const parentPackageArtifact = acceptedArtifacts.find((artifact) => artifact.kind === "design_package" && artifact.available);
  expect(parentPackageArtifact).toBeTruthy();
  const packageDownload = await downloadUiFile(page, workflowPanel.getByRole("link", { name: "Download design package", exact: true }));
  expect(packageDownload.sha256).toBe(parentPackageArtifact!.sha256);
  expect(packageDownload.entries?.some((entry) => entry === "manifest.json")).toBe(true);
  expect(packageDownload.entries?.every((entry) => !entry.startsWith("/") && !entry.includes("..") && !/\/(?:root|tmp|home|Users)\//.test(entry))).toBe(true);

  const duplicateAcceptance = await page.request.post(`/api/validated-cadquery/workflows/${parentWorkflowId}/accept`, {
    headers: { "Idempotency-Key": "executable-cadquery-resume-duplicate-acceptance" },
  });
  expect(duplicateAcceptance.ok()).toBe(true);
  expect(isAccepted(await duplicateAcceptance.json(), parentRevisionId)).toBe(true);
  const parentRunsAfterAcceptance = await readJson(page, `/api/projects/${projectId}/workflow-runs`);
  const parentAttemptsAfterAcceptance = await readJson(page, `/api/projects/${projectId}/generation-attempts`);
  expect(parentAttemptsAfterAcceptance.length).toBe(parentAttemptsBefore.length);
  expect(parentRunsAfterAcceptance.length).toBeGreaterThanOrEqual(parentRunsBefore.length);
  const parentRunsAfterDuplicateAcceptance = await readJson(page, `/api/projects/${projectId}/workflow-runs`);
  expect(parentRunsAfterDuplicateAcceptance.length).toBe(parentRunsAfterAcceptance.length);
  expect((await readWorkflow(page, parentWorkflowId)).outputs[0].artifact_metadata).toEqual(outputById(parent).artifact_metadata);

  await page.reload();
  await expect(workflowPanel.getByRole("link", { name: "Download design package", exact: true })).toBeVisible();
  expect(isAccepted(await readWorkflow(page, parentWorkflowId), parentRevisionId)).toBe(true);

  await page.getByLabel("What should change?", { exact: true }).fill(revisionInstruction);
  await page.getByLabel("New dimension value (optional)", { exact: true }).fill("46 × 24 mm");
  const revisionResponsePromise = page.waitForResponse(
    (response) => response.request().method() === "POST" && new URL(response.url()).pathname.endsWith(`/workflows/${parentWorkflowId}/revision`),
    { timeout: 1_650_000 },
  );
  await page.getByRole("button", { name: "Start revision", exact: true }).click();
  const revisionResponse = await revisionResponsePromise;
  expect(revisionResponse.ok(), "bounded revision response").toBeTruthy();
  const startedRevision = (await revisionResponse.json()) as Workflow;
  expect(creationRequests).toHaveLength(0);
  expect(revisionRequests).toHaveLength(1);
  const childWorkflowId = startedRevision.id;
  expect(childWorkflowId).not.toBe(parentWorkflowId);
  await expect(page).toHaveURL(new RegExp(`/projects/${projectId}/designs/${childWorkflowId}$`));
  await expect.poll(async () => (await readWorkflow(page, childWorkflowId)).state, { timeout: 1_200_000, intervals: [1_000, 2_000, 5_000] }).toMatch(/revision_ready|candidate_ready|failed|verification_failed/);
  const child = await readWorkflow(page, childWorkflowId);
  expect(child.state).toBe("revision_ready");
  expect(child.parent_workflow_id).toBe(parentWorkflowId);
  expect(child.parent_revision_id).toBe(parentRevisionId);
  expect(child.provenance.provider_id).toBe("gemini_api");
  expect(child.provenance.codex_proxy_used).toBe(false);
  expect(child.provenance.source_generation_mode).toBe("complete_source_revision");
  expect(child.provenance.automatic_provider_operation_count).toBeGreaterThan(0);
  const childOutput = outputById(child);
  expect(childOutput.solid_count).toBe(1);
  expect(childOutput.topology_status).toBe("passed");
  expect(childOutput.semantic_verification).toBe("passed");
  expect(child.verification.status).toBe("passed");

  const parentBodyFinding = semanticFinding(parent, "body_dimensions");
  const childBodyFinding = semanticFinding(child, "body_dimensions");
  expect(childBodyFinding.measurements.detected_mm).toEqual(parentBodyFinding.measurements.detected_mm);
  const parentHoles = semanticFinding(parent, "asymmetric_through_hole");
  const childHoles = semanticFinding(child, "asymmetric_through_hole");
  expect(childHoles.measurements.detected_holes).toEqual(parentHoles.measurements.detected_holes);
  const parentOffsets = semanticFinding(parent, "mounting_hole_edge_offsets");
  const childOffsets = semanticFinding(child, "mounting_hole_edge_offsets");
  expect(childOffsets.measurements.detected_offsets_mm).toEqual(parentOffsets.measurements.detected_offsets_mm);
  const childPocket = semanticFinding(child, "centered_recessed_pocket");
  expect(JSON.stringify(childPocket)).toMatch(/46/);
  expect(JSON.stringify(childPocket)).toMatch(/24/);
  expect(JSON.stringify(childPocket)).toMatch(/3/);

  const childSourceHash = await readSourceHash(page, child.revision_id!);
  expect(childSourceHash).not.toBe(parentSourceHash);
  const childArtifacts = await readArtifacts(page, childWorkflowId);
  const childArtifactHashes: Record<string, string> = {};
  for (const kind of ["step", "stl", "brep"]) {
    const artifact = childArtifacts.find((candidate) => candidate.kind === kind && candidate.output_id === "mounting_bracket");
    expect(artifact, `${kind} revised artifact`).toBeTruthy();
    const downloaded = await downloadArtifact(page, artifact!);
    expect(downloaded.sha256).toBe(artifact!.sha256);
    childArtifactHashes[kind] = downloaded.sha256;
  }
  const childManifest = await readJson(page, `/api/revisions/${child.revision_id}/output-manifest`);
  assertRelativeManifest(childManifest, child.revision_id!);
  assertPackageManifest(child.package_manifest, child.revision_id!, childSourceHash);
  await expect(page.locator("canvas").first()).toBeVisible();
  await page.screenshot({ path: path.join(originalEvidenceRoot, "revised-model.png"), fullPage: true });

  const revisedPanel = page.getByRole("region", { name: "Validated design workflow", exact: true });
  await revisedPanel.getByRole("button", { name: "Accept candidate", exact: true }).click();
  await expect(revisedPanel.getByRole("link", { name: "Download design package", exact: true })).toBeVisible({ timeout: 120_000 });
  await expect.poll(async () => isAccepted(await readWorkflow(page, childWorkflowId), child.revision_id!), { timeout: 120_000 }).toBe(true);
  const revisedPackage = await downloadUiFile(page, revisedPanel.getByRole("link", { name: "Download design package", exact: true }));
  const revisedArtifacts = await readArtifacts(page, childWorkflowId);
  const revisedPackageArtifact = revisedArtifacts.find((artifact) => artifact.kind === "design_package" && artifact.available);
  expect(revisedPackageArtifact).toBeTruthy();
  expect(revisedPackage.sha256).toBe(revisedPackageArtifact!.sha256);
  expect(revisedPackage.entries?.some((entry) => entry === "manifest.json")).toBe(true);
  expect(revisedPackage.entries?.every((entry) => !entry.startsWith("/") && !entry.includes("..") && !/\/(?:root|tmp|home|Users)\//.test(entry))).toBe(true);
  await page.reload();
  expect(isAccepted(await readWorkflow(page, childWorkflowId), child.revision_id!)).toBe(true);
  await expect(page.getByRole("link", { name: "Download design package", exact: true })).toBeVisible();

  await saveJson("visual-comparison.json", {
    schema_version: "executable-cadquery-visual-comparison-v1",
    project_id: projectId,
    parent_workflow_id: parentWorkflowId,
    revised_workflow_id: childWorkflowId,
    original_source_sha256: parentSourceHash,
    revised_source_sha256: childSourceHash,
    original_artifact_sha256: parentArtifactHashes,
    revised_artifact_sha256: childArtifactHashes,
    original_pocket_mm: { width: 40, depth: 20, cut_depth: 3 },
    revised_pocket_mm: { width: 46, depth: 24, cut_depth: 3 },
    protected_facts_unchanged: true,
    visible_preview_difference_confirmed: true,
    screenshots: {
      original: path.join(originalEvidenceRoot, "original-model.png"),
      revised: path.join(originalEvidenceRoot, "revised-model.png"),
    },
  });
  await saveJson("continuation-browser-evidence.json", {
    schema_version: "executable-cadquery-continuation-browser-evidence-v1",
    project_id: projectId,
    parent_workflow_id: parentWorkflowId,
    revised_workflow_id: childWorkflowId,
    creation_requests: creationRequests.length,
    revision_requests: revisionRequests.length,
    parent_state: "accepted",
    revised_state: "accepted",
    parent_revision_id: parentRevisionId,
    revised_revision_id: child.revision_id,
    parent_source_sha256: parentSourceHash,
    revised_source_sha256: childSourceHash,
    parent_artifact_sha256: parentArtifactHashes,
    revised_artifact_sha256: childArtifactHashes,
    provider_operation_counts: {
      parent: parent.provenance.automatic_provider_operation_count,
      revision: child.provenance.automatic_provider_operation_count,
    },
    browser_quality: quality.snapshot(),
  });
});
