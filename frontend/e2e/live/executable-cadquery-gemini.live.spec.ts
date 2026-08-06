import { expect, test, type Page } from "@playwright/test";
import fs from "node:fs/promises";
import path from "node:path";
import { installBrowserQualityChecks, liveEnabled } from "./liveEnvironment";

const frozenPrompt =
  "Create a mounting bracket with a body 80 mm wide, 50 mm deep, and 8 mm thick. Add four 5 mm through-holes with each mounting-hole center 8 mm from its nearest edge. Add a centered recessed pocket 40 mm wide, 20 mm deep, and 3 mm deep. Add one asymmetric 10 mm through-hole centered 18 mm from the left edge and 25 mm from the lower edge. Add a 2 mm external fillet where geometrically valid.";
const evidenceRoot = path.resolve("..", "data", "debug-sessions", "executable-cadquery-gemini-live");

type Workflow = {
  id: string;
  project_id: string;
  parent_workflow_id?: string | null;
  revision_id?: string | null;
  state: string;
  route: string;
  outputs: Array<Record<string, unknown>>;
  provenance: Record<string, any>;
  verification: Record<string, any>;
  diagnostics: Record<string, any>;
  package_available: boolean;
};

async function writeJson(filename: string, payload: unknown) {
  await fs.mkdir(evidenceRoot, { recursive: true });
  await fs.writeFile(path.join(evidenceRoot, filename), `${JSON.stringify(payload, null, 2)}\n`, "utf-8");
}

async function readJson(page: Page, endpoint: string) {
  const response = await page.request.get(endpoint);
  expect(response.ok(), endpoint).toBeTruthy();
  return response.json();
}

async function readWorkflow(page: Page, projectId: string, workflowId: string): Promise<Workflow> {
  return readJson(page, `/api/validated-cadquery/projects/${projectId}/designs/${workflowId}`) as Promise<Workflow>;
}

async function readSource(page: Page, revisionId: string) {
  const response = await page.request.get(`/api/revisions/${revisionId}/source`);
  expect(response.ok(), `source for revision ${revisionId}`).toBeTruthy();
  return response.text();
}

function failureBoundary(workflow: Workflow | null) {
  return workflow?.diagnostics?.first_incorrect_boundary ?? workflow?.provenance?.terminal_reason ?? null;
}

function decisionFor(
  parent: Workflow | null,
  child: Workflow | null,
  attempts: Array<Record<string, any>>,
) {
  const parentAccepted = parent?.state === "accepted";
  const childAccepted = child?.state === "accepted";
  if (parentAccepted && !child) return "executable_cadquery_visible_golden_path_ready";
  if (parentAccepted && childAccepted) return "executable_cadquery_visible_golden_path_ready";
  if (parentAccepted && child) return "executable_cadquery_creation_ready_revision_blocked";
  const history = [
    ...(parent?.provenance?.repair_history ?? []),
    ...(child?.provenance?.repair_history ?? []),
  ];
  if (attempts.some((attempt) => attempt.status === "failed" && attempt.failure_class) || history.length > 0) {
    if (history.some((entry: Record<string, any>) => entry.progress?.measurable_progress)) {
      return "executable_cadquery_repairs_show_progress_but_not_ready";
    }
    if (
      attempts.some((attempt) => attempt.status === "contract_failure") ||
      history.some((entry: Record<string, any>) => entry.failure_class === "provider_response_contract_failure")
    ) {
      return "gemini_complete_source_generation_nonviable";
    }
    if (["execution", "artifact", "semantic", "topology"].includes(String(failureBoundary(child ?? parent)))) {
      return "application_executor_or_validator_requires_narrow_fix";
    }
  }
  return "product_integrity_blocked";
}

test.describe.serial("executable CadQuery Gemini live golden path", () => {
  test.skip(
    !liveEnabled ||
      process.env.VITE_VOLUNDR_EXECUTABLE_CADQUERY_FLOW_ENABLED !== "true" ||
      process.env.VITE_VOLUNDR_VALIDATED_CADQUERY_FLOW_ENABLED === "true",
    "Opt-in complete-source executable CadQuery live experiment.",
  );

  test("creates exactly one frozen design and accepts the candidate", async ({ page }, testInfo) => {
    test.setTimeout(1_800_000);
    const quality = installBrowserQualityChecks(page);
    const creationRequests: string[] = [];
    const revisionRequests: string[] = [];
    const workflowIds: string[] = [];
    let projectId: string | null = null;
    let parent: Workflow | null = null;
    let parentAccepted: Workflow | null = null;
    let child: Workflow | null = null;
    let childAccepted: Workflow | null = null;
    let initialSource: string | null = null;
    let revisedSource: string | null = null;
    let attempts: Array<Record<string, any>> = [];
    let failureKind: string | null = null;

    page.on("request", (request) => {
      const url = new URL(request.url());
      if (request.method() !== "POST") return;
      if (url.pathname === "/api/validated-cadquery/designs") creationRequests.push(request.headers()["idempotency-key"] ?? "");
      if (url.pathname.endsWith("/revision") && url.pathname.includes("/api/validated-cadquery/workflows/")) revisionRequests.push(request.headers()["idempotency-key"] ?? "");
    });

    try {
      await page.goto("/");
      await page.getByLabel("AI chat message").fill(frozenPrompt);
      await page.getByRole("button", { name: "Send", exact: true }).click();

      await expect(page).toHaveURL(/\/projects\/[^/]+\/designs\/[^/]+$/, { timeout: 900_000 });
      const route = new URL(page.url());
      const match = route.pathname.match(/^\/projects\/([^/]+)\/designs\/([^/]+)$/);
      expect(match).toBeTruthy();
      projectId = match![1];
      const parentWorkflowId = match![2];
      workflowIds.push(parentWorkflowId);
      await expect(page.getByRole("heading", { name: "Executable CadQuery experiment", exact: true })).toBeVisible();
      await expect.poll(
        async () => {
          parent = await readWorkflow(page, projectId!, parentWorkflowId);
          return parent.state;
        },
        { timeout: 900_000, intervals: [1_000, 2_000, 5_000] },
      ).toMatch(/candidate_ready|failed|verification_failed/);
      expect(parent.state).toBe("candidate_ready");
      const candidateReview = page.getByRole("region", { name: "Candidate review", exact: true });
      await expect(candidateReview).toHaveCount(1);
      await expect(candidateReview.getByText("Ready to review", { exact: true })).toHaveCount(1);
      await expect(candidateReview.getByText("Ready to review", { exact: true })).toBeVisible();
      await expect(page.locator("canvas").first()).toBeVisible();
      expect(parent.provenance.provider_id).toBe("gemini_api");
      expect(parent.provenance.codex_proxy_used).toBe(false);
      expect(parent.outputs).toHaveLength(1);

      await page.getByRole("region", { name: "Validated design workflow", exact: true }).getByRole("button", { name: "Accept candidate", exact: true }).click();
      await expect(page.getByRole("link", { name: "Download design package", exact: true })).toBeVisible({ timeout: 120_000 });
      await expect(page.locator("canvas").first()).toBeVisible();
      await fs.mkdir(path.join(evidenceRoot, "screenshots"), { recursive: true });
      await page.screenshot({ path: path.join(evidenceRoot, "screenshots", "original-model.png"), fullPage: true });
      parentAccepted = await readWorkflow(page, projectId, parentWorkflowId);
      expect(parentAccepted.state).toBe("accepted");
    } catch (error) {
      failureKind = error instanceof Error ? error.name : "unknown_failure";
      throw error;
    } finally {
      if (projectId) {
        const runs = await readJson(page, `/api/projects/${projectId}/workflow-runs`).catch(() => []);
        attempts = await readJson(page, `/api/projects/${projectId}/generation-attempts`).catch(() => []);
        const allWorkflows = [parentAccepted ?? parent, childAccepted ?? child].filter(Boolean) as Workflow[];
        if (attempts.length === 0) {
          attempts = allWorkflows.flatMap((workflow) => (workflow.provenance?.repair_history ?? []).map((entry: Record<string, any>) => ({
            attempt_number: entry.attempt_number,
            provider: "gemini_api",
            status: entry.provider_attempt?.status ?? "unknown",
            failure_class: entry.failure_class,
            prompt_version: "executable-cadquery-complete-source-v3",
            provider_response: { stage: entry.failure_boundary },
            routing_metadata: { source: "durable_workflow_provenance" },
          })));
        }
        if (attempts.length === 0) {
          attempts = allWorkflows.flatMap((workflow) => {
            const operationCount = Number(workflow.provenance?.automatic_provider_operation_count ?? 0);
            return Array.from({ length: Number.isInteger(operationCount) && operationCount > 0 ? operationCount : 0 }, (_, index) => ({
              attempt_number: index + 1,
              provider: workflow.provenance?.provider_id ?? "gemini_api",
              status: workflow.state === "accepted" ? "succeeded" : workflow.state,
              failure_class: null,
              prompt_version: "executable-cadquery-complete-source-v3",
              provider_response: { stage: "source_extraction" },
              routing_metadata: { source: "durable_workflow_provenance" },
            }));
          });
        }
        if (!initialSource && parent?.revision_id) initialSource = await readSource(page, parent.revision_id).catch(() => null);
        if (!revisedSource && child?.revision_id) revisedSource = await readSource(page, child.revision_id).catch(() => null);
        const contract = parent?.provenance?.executable_design_contract ?? null;
        await writeJson("design_contract.json", contract ?? { unavailable: true });
        await writeJson("provider-response.json", {
          schema_version: "executable-cadquery-live-provider-evidence-v1",
          provider: "gemini_api",
          attempts: attempts.map((attempt: Record<string, any>) => ({
            attempt_number: attempt.attempt_number,
            provider: attempt.provider,
            model: attempt.model,
            status: attempt.status,
            failure_class: attempt.failure_class,
            prompt_version: attempt.prompt_version,
            duration_ms: attempt.duration_ms,
            provider_response: attempt.provider_response,
            routing_metadata: attempt.routing_metadata,
          })),
        });
        await writeJson("source-response.json", {
          schema_version: "executable-cadquery-live-source-evidence-v1",
          revision_id: parent?.revision_id ?? null,
          source: initialSource,
        });
        await writeJson("source-response-repaired.json", {
          schema_version: "executable-cadquery-live-source-evidence-v1",
          revision_id: child?.revision_id ?? null,
          source: revisedSource,
        });
        await writeJson("cadquery-worker-result.json", {
          workflows: allWorkflows.map((workflow) => ({ workflow_id: workflow.id, revision_id: workflow.revision_id, outputs: workflow.outputs })),
        });
        await writeJson("topology-result.json", {
          workflows: allWorkflows.map((workflow) => ({ workflow_id: workflow.id, outputs: workflow.outputs.map((output) => ({ output_id: output.output_id, solid_count: output.solid_count, topology_status: output.topology_status, artifact_metadata: output.artifact_metadata })) })),
        });
        await writeJson("semantic-verification.json", {
          initial: parent?.verification ?? null,
          revision: child?.verification ?? null,
        });
        await writeJson("provenance.json", {
          initial: parent?.provenance ?? null,
          revision: child?.provenance ?? null,
        });
        await writeJson("browser-evidence.json", {
          schema_version: "executable-cadquery-gemini-live-browser-evidence-v1",
          frozen_prompt_used: frozenPrompt,
          exact_revision_instruction_used: null,
          revision_dimension_used: null,
          project_id: projectId,
          workflow_ids: workflowIds,
          one_creation_request: creationRequests.length === 1,
          one_revision_request: revisionRequests.length === 1,
          creation_idempotency_key_present: creationRequests.every((key) => /^[0-9a-f-]{36}$/i.test(key)),
          revision_idempotency_key_present: revisionRequests.every((key) => /^[0-9a-f-]{36}$/i.test(key)),
          original_model_visible: Boolean(parentAccepted),
          original_model_accepted: parentAccepted?.state === "accepted",
          revision_model_visible: Boolean(childAccepted),
          revision_model_accepted: childAccepted?.state === "accepted",
          output_identity_preserved: childAccepted?.verification?.output_identity_preserved ?? child?.verification?.output_identity_preserved ?? false,
          provider_attempt_count: attempts.length,
          workflow_runs: runs,
          browser_quality: quality.snapshot(),
          failure_kind: failureKind,
          test_output_directory: testInfo.outputDir,
        });
        const durableFailureHistory = allWorkflows.flatMap((workflow) => workflow.provenance?.repair_history ?? []);
        const firstDurableFailureClass = durableFailureHistory[0]?.failure_class ?? null;
        await writeJson("decision.json", {
          schema_version: "executable-cadquery-gemini-live-decision-v1",
          decision: decisionFor(parentAccepted ?? parent, childAccepted ?? child, attempts),
          first_incorrect_boundary: failureBoundary(child ?? parent),
          first_failure_kind: firstDurableFailureClass ?? failureKind,
          one_creation_request: creationRequests.length === 1,
          one_revision_request: revisionRequests.length === 1,
          parent_state: parentAccepted?.state ?? parent?.state ?? null,
          revision_state: childAccepted?.state ?? child?.state ?? null,
        });
      } else {
        await writeJson("decision.json", {
          schema_version: "executable-cadquery-gemini-live-decision-v1",
          decision: "product_integrity_blocked",
          first_incorrect_boundary: "browser_creation_request",
          first_failure_kind: failureKind,
          one_creation_request: creationRequests.length === 1,
          one_revision_request: revisionRequests.length === 1,
        });
      }
      if (!failureKind) await quality.assertClean();
    }
  });
});
