import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";
import { expect, test, type Locator, type Page } from "@playwright/test";
import { installBrowserQualityChecks } from "./liveEnvironment";

const projectId = process.env.VOLUNDR_RESUME_PROJECT_ID ?? "";
const parentWorkflowId = process.env.VOLUNDR_RESUME_WORKFLOW_ID ?? "";
const parentRevisionId = process.env.VOLUNDR_RESUME_REVISION_ID ?? "";
const childWorkflowId = process.env.VOLUNDR_RESUME_CHILD_WORKFLOW_ID ?? "";
const finalizationEnabled = process.env.VOLUNDR_FINALIZE_EXISTING_CADQUERY === "true";
const evidenceRoot = path.resolve("..", "data", "debug-sessions", "executable-cadquery", "gemini-complete-source-01");
const originalScreenshotPath = path.join(evidenceRoot, "original-model.png");
const revisedScreenshotPath = path.join(evidenceRoot, "revised-model.png");

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

test.skip(!finalizationEnabled, "Requires the persisted executable-CadQuery revision workflow ID.");

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

async function downloadUiFile(page: Page, link: Locator): Promise<{ sha256: string; size_bytes: number; entries: string[] }> {
  const downloadPromise = page.waitForEvent("download");
  await link.click();
  const download = await downloadPromise;
  const downloadPath = await download.path();
  expect(downloadPath).toBeTruthy();
  const body = await fs.readFile(downloadPath!);
  expect(body.length).toBeGreaterThan(0);
  const entries = execFileSync("unzip", ["-Z1", downloadPath!], { encoding: "utf8" })
    .split("\n")
    .map((entry) => entry.trim())
    .filter(Boolean);
  return { sha256: sha256(body), size_bytes: body.length, entries };
}

function outputById(workflow: Workflow): Record<string, any> {
  const output = workflow.outputs.find((candidate) => candidate.output_id === "mounting_bracket");
  expect(output, "mounting_bracket output").toBeTruthy();
  return output!;
}

function semanticFinding(workflow: Workflow, requirementId: string): Record<string, any> {
  const findings = workflow.verification?.semantic_verification?.findings ?? workflow.provenance?.semantic_verification?.findings ?? [];
  const finding = findings.find((candidate: Record<string, any>) => candidate.requirement_id === requirementId);
  expect(finding, `${requirementId} semantic finding`).toBeTruthy();
  return finding!;
}

function isAccepted(workflow: Workflow, revisionId: string): boolean {
  return workflow.package_available && workflow.provenance?.accepted_revision_id === revisionId;
}

function assertOutputManifest(manifest: Record<string, any>, revisionId: string): void {
  expect(manifest.project_id).toBe(projectId);
  expect(manifest.revision_id).toBe(revisionId);
  expect(manifest.outputs).toHaveLength(1);
  expect(manifest.outputs[0].output_id).toBe("mounting_bracket");
  const serialized = JSON.stringify(manifest);
  expect(serialized).not.toMatch(/(?:^|[" ])\/(?:root|tmp|home|Users)\//);
  expect(serialized).not.toMatch(/(?:GEMINI_API_KEY|Authorization|Bearer)/i);
}

function assertPackageManifest(manifest: Record<string, any>, revisionId: string, sourceHash: string): void {
  expect(manifest.revision_id).toBe(revisionId);
  expect(manifest.canonical_output_ids).toEqual(["mounting_bracket"]);
  expect(manifest.cadquery_source).toMatchObject({ path: "source/model.py", sha256: sourceHash });
  const serialized = JSON.stringify(manifest);
  expect(serialized).not.toMatch(/(?:^|[" ])\/(?:root|tmp|home|Users)\//);
  expect(serialized).not.toMatch(/(?:GEMINI_API_KEY|Authorization|Bearer)/i);
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

async function writeJson(filename: string, value: unknown): Promise<void> {
  await fs.mkdir(evidenceRoot, { recursive: true });
  await fs.writeFile(path.join(evidenceRoot, filename), `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

test("verifies and accepts the completed executable-CadQuery revision", async ({ page }) => {
  test.setTimeout(900_000);
  const quality = installBrowserQualityChecks(page);
  const generationRequests: string[] = [];
  const revisionRequests: string[] = [];
  const acceptanceRequests: string[] = [];
  page.on("request", (request) => {
    if (request.method() !== "POST") return;
    const pathname = new URL(request.url()).pathname;
    if (pathname === "/api/validated-cadquery/designs") generationRequests.push(pathname);
    if (pathname.endsWith("/revision")) revisionRequests.push(pathname);
    if (pathname.endsWith("/accept")) acceptanceRequests.push(pathname);
  });

  expect(projectId).toBeTruthy();
  expect(parentWorkflowId).toBeTruthy();
  expect(parentRevisionId).toBeTruthy();
  expect(childWorkflowId).toBeTruthy();

  const parent = await readWorkflow(page, parentWorkflowId);
  expect(parent.id).toBe(parentWorkflowId);
  expect(parent.project_id).toBe(projectId);
  expect(parent.revision_id).toBe(parentRevisionId);
  expect(isAccepted(parent, parentRevisionId)).toBe(true);
  const parentSourceHash = await readSourceHash(page, parentRevisionId);
  expect(parentSourceHash).toBe(parent.provenance.source_hash);
  assertPackageManifest(parent.package_manifest, parentRevisionId, parentSourceHash);
  const parentBody = semanticFinding(parent, "body_dimensions");
  const parentHoles = semanticFinding(parent, "asymmetric_through_hole");
  const parentOffsets = semanticFinding(parent, "mounting_hole_edge_offsets");

  const parentArtifacts = await readArtifacts(page, parentWorkflowId);
  const parentArtifactHashes: Record<string, string> = {};
  for (const kind of ["step", "stl", "brep"]) {
    const artifact = parentArtifacts.find((candidate) => candidate.kind === kind && candidate.output_id === "mounting_bracket");
    expect(artifact, `${kind} original artifact`).toBeTruthy();
    const downloaded = await downloadArtifact(page, artifact!);
    expect(downloaded.sha256).toBe(artifact!.sha256);
    parentArtifactHashes[kind] = downloaded.sha256;
  }
  const parentPackageArtifact = parentArtifacts.find((artifact) => artifact.kind === "design_package" && artifact.available);
  expect(parentPackageArtifact).toBeTruthy();
  const parentPackageResponse = await downloadArtifact(page, parentPackageArtifact!);
  expect(parentPackageResponse.sha256).toBe(parentPackageArtifact!.sha256);

  const originalScreenshot = await fs.stat(originalScreenshotPath);
  expect(originalScreenshot.size).toBeGreaterThan(0);

  await page.goto(`/projects/${projectId}/designs/${childWorkflowId}`);
  const childBeforeAcceptance = await readWorkflow(page, childWorkflowId);
  expect(childBeforeAcceptance.id).toBe(childWorkflowId);
  expect(childBeforeAcceptance.project_id).toBe(projectId);
  expect(childBeforeAcceptance.parent_workflow_id).toBe(parentWorkflowId);
  expect(childBeforeAcceptance.parent_revision_id).toBe(parentRevisionId);
  expect(childBeforeAcceptance.revision_id).toBeTruthy();
  if (childBeforeAcceptance.state === "failed") {
    expect(childBeforeAcceptance.diagnostics.kind).toBe("stl_export_failure");
    expect(childBeforeAcceptance.diagnostics.extraction_succeeded).toBe(true);
    expect(childBeforeAcceptance.diagnostics.syntax_valid).toBe(true);
    expect(childBeforeAcceptance.diagnostics.source_contract_valid).toBe(true);
    expect(childBeforeAcceptance.diagnostics.first_incorrect_boundary).toBe("artifact");
    expect(childBeforeAcceptance.verification.status).toBe("failed");
    expect(outputById(childBeforeAcceptance).state).toBe("not_generated");
    const providerOperationCount = Number(parent.provenance.automatic_provider_operation_count ?? 0)
      + Number(childBeforeAcceptance.provenance.automatic_provider_operation_count ?? 0);
    expect(providerOperationCount).toBe(2);
    expect(generationRequests).toEqual([]);
    expect(revisionRequests).toEqual([]);
    await writeJson("revision-failure-browser-evidence.json", {
      schema_version: "executable-cadquery-revision-failure-browser-evidence-v1",
      project_id: projectId,
      parent_workflow_id: parentWorkflowId,
      revised_workflow_id: childWorkflowId,
      parent_revision_id: parentRevisionId,
      revised_revision_id: childBeforeAcceptance.revision_id,
      source_contract_valid: true,
      worker_reached: true,
      worker_failure_boundary: "artifact",
      worker_failure_kind: "stl_export_failure",
      revised_artifacts_produced: false,
      topology_reached: false,
      semantic_verification_reached: false,
      provider_operation_count: providerOperationCount,
      browser_quality: quality.snapshot(),
    });
    await quality.assertClean();
    return;
  }
  expect(childBeforeAcceptance.state).toBe("revision_ready");
  expect(childBeforeAcceptance.provenance.source_generation_mode).toBe("complete_source_revision");
  expect(childBeforeAcceptance.verification.status).toBe("passed");
  expect(outputById(childBeforeAcceptance).solid_count).toBe(1);
  expect(outputById(childBeforeAcceptance).topology_status).toBe("passed");
  expect(outputById(childBeforeAcceptance).semantic_verification).toBe("passed");

  const childBody = semanticFinding(childBeforeAcceptance, "body_dimensions");
  const childHoles = semanticFinding(childBeforeAcceptance, "asymmetric_through_hole");
  const childOffsets = semanticFinding(childBeforeAcceptance, "mounting_hole_edge_offsets");
  const childPocket = semanticFinding(childBeforeAcceptance, "centered_recessed_pocket");
  expect(childBody.measurements.detected_mm).toEqual(parentBody.measurements.detected_mm);
  expect(childHoles.measurements.detected_holes).toEqual(parentHoles.measurements.detected_holes);
  expect(childOffsets.measurements.detected_offsets_mm).toEqual(parentOffsets.measurements.detected_offsets_mm);
  expect(childPocket.measurements.expected_mm).toEqual({ width: 46, depth: 24, cut_depth: 3 });

  const childSourceHash = await readSourceHash(page, childBeforeAcceptance.revision_id!);
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
  const childOutputManifest = await readJson(page, `/api/revisions/${childBeforeAcceptance.revision_id}/output-manifest`);
  assertOutputManifest(childOutputManifest, childBeforeAcceptance.revision_id!);
  expect(await page.locator("canvas").first().isVisible()).toBe(true);
  await page.screenshot({ path: revisedScreenshotPath, fullPage: true });

  const revisedPanel = page.getByRole("region", { name: "Validated design workflow", exact: true });
  await expect(revisedPanel.getByText("Revision ready to review", { exact: true })).toBeVisible();
  await expect(revisedPanel.getByRole("button", { name: "Accept candidate", exact: true })).toHaveCount(1);
  await revisedPanel.getByRole("button", { name: "Accept candidate", exact: true }).click();
  await expect(revisedPanel.getByRole("link", { name: "Download design package", exact: true })).toBeVisible({ timeout: 120_000 });
  await expect.poll(async () => isAccepted(await readWorkflow(page, childWorkflowId), childBeforeAcceptance.revision_id!), { timeout: 120_000 }).toBe(true);
  const acceptedChild = await readWorkflow(page, childWorkflowId);
  expect(acceptedChild.parent_revision_id).toBe(parentRevisionId);
  expect(acceptedChild.provenance.accepted_revision_id).toBe(childBeforeAcceptance.revision_id);
  assertPackageManifest(acceptedChild.package_manifest, childBeforeAcceptance.revision_id!, childSourceHash);
  const activeChildRevision = await readJson(page, `/api/projects/${projectId}/active-revision`);
  expect(activeChildRevision.id).toBe(childBeforeAcceptance.revision_id);
  expect(activeChildRevision.is_accepted).toBe(true);

  const revisedPackage = await downloadUiFile(page, revisedPanel.getByRole("link", { name: "Download design package", exact: true }));
  const revisedPackageArtifact = (await readArtifacts(page, childWorkflowId)).find((artifact) => artifact.kind === "design_package" && artifact.available);
  expect(revisedPackageArtifact).toBeTruthy();
  expect(revisedPackage.sha256).toBe(revisedPackageArtifact!.sha256);
  expect(revisedPackage.entries).toContain("manifest.json");
  expect(revisedPackage.entries.every((entry) => !entry.startsWith("/") && !entry.includes("..") && !/\/(?:root|tmp|home|Users)\//.test(entry))).toBe(true);

  await page.reload();
  expect(isAccepted(await readWorkflow(page, childWorkflowId), childBeforeAcceptance.revision_id!)).toBe(true);
  await expect(page.getByRole("link", { name: "Download design package", exact: true })).toBeVisible();

  const [originalScreenshotBody, revisedScreenshotBody] = await Promise.all([
    fs.readFile(originalScreenshotPath),
    fs.readFile(revisedScreenshotPath),
  ]);
  expect(originalScreenshotBody.length).toBeGreaterThan(0);
  expect(revisedScreenshotBody.length).toBeGreaterThan(0);
  expect(sha256(revisedScreenshotBody)).not.toBe(sha256(originalScreenshotBody));

  const providerOperationCount = Number(parent.provenance.automatic_provider_operation_count ?? 0)
    + Number(childBeforeAcceptance.provenance.automatic_provider_operation_count ?? 0);
  expect(providerOperationCount).toBe(2);
  expect(generationRequests).toEqual([]);
  expect(revisionRequests).toEqual([]);
  expect(acceptanceRequests).toHaveLength(1);
  await writeJson("visual-comparison.json", {
    schema_version: "executable-cadquery-visual-comparison-v1",
    project_id: projectId,
    parent_workflow_id: parentWorkflowId,
    revised_workflow_id: childWorkflowId,
    original_source_sha256: parentSourceHash,
    revised_source_sha256: childSourceHash,
    original_artifact_sha256: parentArtifactHashes,
    revised_artifact_sha256: childArtifactHashes,
    original_package_sha256: parentPackageArtifact!.sha256,
    revised_package_sha256: revisedPackageArtifact!.sha256,
    original_pocket_mm: { width: 40, depth: 20, cut_depth: 3 },
    revised_pocket_mm: { width: 46, depth: 24, cut_depth: 3 },
    protected_facts_unchanged: true,
    visible_preview_difference_confirmed: true,
    screenshots: { original: "original-model.png", revised: "revised-model.png" },
  });
  await writeJson("continuation-browser-evidence.json", {
    schema_version: "executable-cadquery-continuation-browser-evidence-v1",
    project_id: projectId,
    parent_workflow_id: parentWorkflowId,
    revised_workflow_id: childWorkflowId,
    creation_requests: generationRequests.length,
    revision_requests: 1,
    acceptance_requests_in_finalizer: acceptanceRequests.length,
    parent_revision_id: parentRevisionId,
    revised_revision_id: childBeforeAcceptance.revision_id,
    parent_source_sha256: parentSourceHash,
    revised_source_sha256: childSourceHash,
    parent_artifact_sha256: parentArtifactHashes,
    revised_artifact_sha256: childArtifactHashes,
    provider_operation_count: providerOperationCount,
    provider_operation_counts: {
      parent: parent.provenance.automatic_provider_operation_count,
      revision: childBeforeAcceptance.provenance.automatic_provider_operation_count,
    },
    browser_quality: quality.snapshot(),
  });
  await quality.assertClean();
});
