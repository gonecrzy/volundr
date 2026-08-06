import { createHash } from "node:crypto";
import { expect, test, type Page } from "@playwright/test";
import { installBrowserQualityChecks } from "./liveEnvironment";

const projectId = process.env.VOLUNDR_RESUME_PROJECT_ID ?? "";
const parentWorkflowId = process.env.VOLUNDR_RESUME_WORKFLOW_ID ?? "";
const parentRevisionId = process.env.VOLUNDR_RESUME_REVISION_ID ?? "";
const childWorkflowId = process.env.VOLUNDR_RESUME_CHILD_WORKFLOW_ID ?? "";
const enabled = process.env.VOLUNDR_VERIFY_EXISTING_CADQUERY_RESTART === "true";

type Workflow = {
  id: string;
  project_id: string;
  revision_id?: string | null;
  state: string;
  provenance: Record<string, any>;
  diagnostics: Record<string, any>;
  package_available: boolean;
  outputs: Array<Record<string, any>>;
};

type Artifact = {
  kind: string;
  output_id?: string | null;
  sha256: string;
  available: boolean;
  download_url?: string | null;
};

test.skip(!enabled, "Requires the persisted executable-CadQuery workflow IDs.");

async function readJson(page: Page, endpoint: string): Promise<any> {
  const response = await page.request.get(endpoint);
  expect(response.ok(), endpoint).toBeTruthy();
  return response.json();
}

async function readWorkflow(page: Page, workflowId: string): Promise<Workflow> {
  return readJson(page, `/api/validated-cadquery/projects/${projectId}/designs/${workflowId}`) as Promise<Workflow>;
}

async function readArtifacts(page: Page, workflowId: string): Promise<Artifact[]> {
  return readJson(page, `/api/validated-cadquery/projects/${projectId}/designs/${workflowId}/artifacts`) as Promise<Artifact[]>;
}

async function assertArtifactHashes(page: Page, workflowId: string, expected: Record<string, string>): Promise<void> {
  const artifacts = await readArtifacts(page, workflowId);
  for (const kind of ["step", "stl", "brep"]) {
    const artifact = artifacts.find((candidate) => candidate.kind === kind && candidate.output_id === "mounting_bracket");
    expect(artifact, `${kind} artifact`).toBeTruthy();
    expect(artifact!.available).toBe(true);
    const response = await page.request.get(artifact!.download_url!);
    expect(response.ok()).toBe(true);
    const body = await response.body();
    expect(body.length).toBeGreaterThan(0);
    expect(createHash("sha256").update(body).digest("hex")).toBe(expected[kind]);
  }
}

test("retains executable-CadQuery continuation state across API restart and navigation", async ({ page }) => {
  const quality = installBrowserQualityChecks(page);
  const postRequests: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST") postRequests.push(new URL(request.url()).pathname);
  });
  const originalHashes = {
    step: "48702b25c7af57462186db45ae3d3e9a4fee2a15040d5da6e6e5dffb4fbe68b8",
    stl: "f7709224c1ca51d73b691514fd918320faeac02fbcece20df54900e87bcb9901",
    brep: "fb1abbb0059eebd5013cf018b8143aeccdb92eb1dc40cd3ede864cbfd83adb4f",
  };
  const parentUrl = `/projects/${projectId}/designs/${parentWorkflowId}`;
  const childUrl = `/projects/${projectId}/designs/${childWorkflowId}`;

  await page.goto(parentUrl);
  const parent = await readWorkflow(page, parentWorkflowId);
  expect(parent.project_id).toBe(projectId);
  expect(parent.revision_id).toBe(parentRevisionId);
  expect(parent.provenance.accepted_revision_id).toBe(parentRevisionId);
  expect(parent.package_available).toBe(true);
  await expect(page.getByRole("link", { name: "Download design package", exact: true })).toBeVisible();
  await expect(page.locator("canvas").first()).toBeVisible();
  await assertArtifactHashes(page, parentWorkflowId, originalHashes);

  await page.goto(childUrl);
  const child = await readWorkflow(page, childWorkflowId);
  expect(child.parent_workflow_id).toBe(parentWorkflowId);
  expect(child.parent_revision_id).toBe(parentRevisionId);
  expect(child.state).toBe("failed");
  expect(child.diagnostics.source_contract_valid).toBe(true);
  expect(child.diagnostics.first_incorrect_boundary).toBe("artifact");
  expect(child.package_available).toBe(false);
  const operationCountBefore = [parent, child].map((workflow) => workflow.provenance.automatic_provider_operation_count);

  await page.goBack();
  await expect(page).toHaveURL(new RegExp(`${parentUrl}$`));
  expect((await readWorkflow(page, parentWorkflowId)).provenance.accepted_revision_id).toBe(parentRevisionId);
  await page.goForward();
  await expect(page).toHaveURL(new RegExp(`${childUrl}$`));
  const childAfterNavigation = await readWorkflow(page, childWorkflowId);
  expect(childAfterNavigation.state).toBe("failed");
  expect([parent, child].map((workflow) => workflow.provenance.automatic_provider_operation_count)).toEqual(operationCountBefore);
  expect(postRequests).toEqual([]);
  await quality.assertClean();
});
