import { createHash, randomUUID } from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";

const enabled = process.env.VOLUNDR_REPEATABILITY_WAVE === "true";
const evidenceRoot = path.resolve("..", "data", "debug-sessions", "executable-cadquery", "repeatability-wave-01");
const manifestPath = path.join(evidenceRoot, "corpus-manifest.json");

type CorpusProject = {
  project_id: string;
  title: string;
  prompt: string;
  contract: {
    outputs: Array<{ output_id: string; required: boolean }>;
    requirements: Array<{ requirement_id: string }>;
  };
};

type Artifact = {
  artifact_id: string;
  kind: string;
  output_id?: string | null;
  sha256: string;
  available: boolean;
  download_url?: string | null;
};

type Workflow = {
  id: string;
  project_id: string;
  revision_id?: string | null;
  state: string;
  route: string;
  provenance: Record<string, any>;
  verification: Record<string, any>;
  diagnostics: Record<string, any>;
  package_manifest: Record<string, any>;
  package_available: boolean;
  outputs: Array<Record<string, any>>;
};

test.skip(!enabled, "Requires the opt-in six-project Gemini repeatability wave.");

async function writeJson(filename: string, value: unknown): Promise<void> {
  await fs.mkdir(evidenceRoot, { recursive: true });
  await fs.writeFile(path.join(evidenceRoot, filename), `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

async function readWorkflow(page: Page, workflowId: string): Promise<Workflow> {
  const response = await page.request.get(`/api/validated-cadquery/workflows/${workflowId}`);
  expect(response.ok(), `workflow ${workflowId}`).toBeTruthy();
  return response.json() as Promise<Workflow>;
}

async function readArtifacts(page: Page, workflowId: string): Promise<Artifact[]> {
  const response = await page.request.get(`/api/validated-cadquery/workflows/${workflowId}/artifacts`);
  expect(response.ok(), `artifacts ${workflowId}`).toBeTruthy();
  return response.json() as Promise<Artifact[]>;
}

async function downloadHash(page: Page, artifact: Artifact): Promise<{ sha256: string; size_bytes: number }> {
  if (!artifact.available || !artifact.download_url) {
    return { sha256: "", size_bytes: 0 };
  }
  const response = await page.request.get(artifact.download_url);
  if (!response.ok()) {
    return { sha256: "", size_bytes: 0 };
  }
  const body = await response.body();
  return { sha256: createHash("sha256").update(body).digest("hex"), size_bytes: body.length };
}

function semanticCoverage(workflow: Workflow, project: CorpusProject): {
  status: string;
  missing_requirement_ids: string[];
  findings: Array<Record<string, any>>;
} {
  const semantic = workflow.verification?.semantic_verification ?? {};
  const findings = Array.isArray(semantic.findings) ? semantic.findings : [];
  const found = new Set(findings.map((finding: Record<string, any>) => String(finding.requirement_id ?? "")));
  return {
    status: typeof semantic.status === "string" ? semantic.status : "missing",
    missing_requirement_ids: project.contract.requirements
      .map((requirement) => requirement.requirement_id)
      .filter((requirementId) => !found.has(requirementId)),
    findings,
  };
}

function operationEvidence(workflow: Workflow): Array<Record<string, any>> {
  const history = Array.isArray(workflow.provenance?.repair_history)
    ? workflow.provenance.repair_history
    : [];
  return history.map((entry: Record<string, any>, index: number) => ({
    operation: index === 0 && entry.repair_level === "initial" ? "initial" : "repair",
    level: entry.repair_level ?? null,
    ordinal: entry.repair_ordinal ?? index,
    source_hash: entry.source_hash ?? entry.provider_attempt?.extracted_source_hash ?? null,
    normalized_failure: entry.normalized_error ?? entry.provider_attempt?.normalized_error ?? null,
    progress_decision: entry.progress ?? null,
    parent_operation_id: entry.parent_operation_id ?? null,
    credential_slot: entry.provider_attempt?.credential_slot ?? null,
    operation_id: entry.operation_id ?? null,
  }));
}

function failureRecord(workflow: Workflow, semantic: ReturnType<typeof semanticCoverage>): {
  owner: string;
  boundary: string;
  failure_class: string;
  stop_reason: string;
} | null {
  if (workflow.state === "candidate_ready" && semantic.status === "passed" && semantic.missing_requirement_ids.length > 0) {
    return {
      owner: "validator",
      boundary: "semantic",
      failure_class: "semantic_requirement_unverifiable",
      stop_reason: "semantic verifier returned no finding for one or more frozen requirements",
    };
  }
  const history = Array.isArray(workflow.provenance?.repair_history) ? workflow.provenance.repair_history : [];
  const last = history.at(-1) ?? {};
  const diagnostics = workflow.diagnostics ?? {};
  if (workflow.state === "candidate_ready") return null;
  return {
    owner: String(diagnostics.first_incorrect_owner ?? last.failure_owner ?? "application"),
    boundary: String(diagnostics.first_incorrect_boundary ?? last.failure_boundary ?? "workflow"),
    failure_class: String(diagnostics.failure_class ?? last.failure_class ?? "source_execution_error"),
    stop_reason: String(diagnostics.safe_message ?? last.normalized_error ?? "workflow did not reach a verified candidate"),
  };
}

async function recordNotRun(project: CorpusProject, reason: string): Promise<void> {
  await writeJson(`${project.project_id}-result.json`, {
    schema_version: "executable-cadquery-repeatability-project-result-v1",
    project_id: project.project_id,
    title: project.title,
    status: "not_run_shared_defect_stop",
    terminal_stop_reason: reason,
    provider_operations: [],
    visible_success: false,
    accepted: false,
    package_validated: false,
  });
}

test("qualifies the frozen corpus sequentially until the objective stop rule", async ({ page }) => {
  test.setTimeout(3_600_000);
  const manifest = JSON.parse(await fs.readFile(manifestPath, "utf8")) as { projects: CorpusProject[] };
  expect(manifest.projects).toHaveLength(6);
  const failureSignatures = new Map<string, number>();
  const projectResults: Array<Record<string, any>> = [];
  let stopReason: string | null = null;

  for (const project of manifest.projects) {
    if (stopReason) {
      await recordNotRun(project, stopReason);
      continue;
    }

    const startedAt = new Date().toISOString();
    const idempotencyKey = randomUUID();
    const startResponse = await page.request.post("/api/validated-cadquery/designs", {
      headers: { "Idempotency-Key": idempotencyKey },
      data: { name: `${project.project_id} ${project.title}`, intent: project.prompt },
      timeout: 1_500_000,
    });
    if (!startResponse.ok()) {
      const body = await startResponse.text();
      const result = {
        schema_version: "executable-cadquery-repeatability-project-result-v1",
        project_id: project.project_id,
        title: project.title,
        started_at: startedAt,
        status: "failed",
        observed_boundary: "browser_creation_request",
        first_incorrect_owner: "application",
        normalized_failure: body.slice(0, 500),
        failure_class: `http_${startResponse.status()}`,
        visible_success: false,
        accepted: false,
        package_validated: false,
      };
      await writeJson(`${project.project_id}-result.json`, result);
      projectResults.push(result);
      continue;
    }

    const workflow = (await startResponse.json()) as Workflow;
    const semantic = semanticCoverage(workflow, project);
    await page.goto(`/projects/${workflow.project_id}/designs/${workflow.id}`);
    await page.waitForTimeout(750);
    const browserModelVisible = await page.locator("canvas").first().isVisible().catch(() => false);
    const screenshotPath = path.join(evidenceRoot, `${project.project_id}-model.png`);
    if (["candidate_ready", "revision_ready", "accepted"].includes(workflow.state)) {
      await page.screenshot({ path: screenshotPath, fullPage: true });
    }
    const failure = failureRecord(workflow, semantic);
    const qualificationCandidate = workflow.state === "candidate_ready"
      && browserModelVisible
      && semantic.status === "passed"
      && semantic.missing_requirement_ids.length === 0;
    let accepted = false;
    let packageValidated = false;
    let artifactResults: Array<Record<string, any>> = [];
    let acceptedWorkflow = workflow;
    if (qualificationCandidate) {
      const acceptResponse = await page.request.post(`/api/validated-cadquery/workflows/${workflow.id}/accept`, {
        headers: { "Idempotency-Key": randomUUID() },
      });
      if (acceptResponse.ok()) {
        acceptedWorkflow = (await acceptResponse.json()) as Workflow;
        accepted = acceptedWorkflow.provenance?.accepted_revision_id === acceptedWorkflow.revision_id;
        const artifacts = await readArtifacts(page, workflow.id);
        for (const output of project.contract.outputs.filter((item) => item.required)) {
          for (const kind of ["step", "stl", "brep"]) {
            const artifact = artifacts.find((candidate) => candidate.output_id === output.output_id && candidate.kind === kind);
            const downloaded = artifact ? await downloadHash(page, artifact) : { sha256: "", size_bytes: 0 };
            artifactResults.push({
              output_id: output.output_id,
              kind,
              available: Boolean(artifact?.available),
              registered_sha256: artifact?.sha256 ?? null,
              downloaded_sha256: downloaded.sha256,
              size_bytes: downloaded.size_bytes,
              hash_match: Boolean(artifact?.sha256 && artifact.sha256 === downloaded.sha256),
            });
          }
        }
        packageValidated = accepted && acceptedWorkflow.package_available && artifactResults.every((artifact) => artifact.available && artifact.hash_match);
      }
    }
    const result = {
      schema_version: "executable-cadquery-repeatability-project-result-v1",
      project_id: project.project_id,
      title: project.title,
      started_at: startedAt,
      workflow_id: workflow.id,
      database_project_id: workflow.project_id,
      revision_id: acceptedWorkflow.revision_id ?? workflow.revision_id ?? null,
      state_reported_by_application: workflow.state,
      status: qualificationCandidate ? "accepted" : failure ? "failed" : "candidate_not_qualified",
      first_incorrect_owner: failure?.owner ?? null,
      observed_boundary: failure?.boundary ?? null,
      failure_class: failure?.failure_class ?? null,
      terminal_stop_reason: failure?.stop_reason ?? null,
      semantic_verification: {
        status: semantic.status,
        finding_count: semantic.findings.length,
        missing_requirement_ids: semantic.missing_requirement_ids,
      },
      browser_model_visible: browserModelVisible,
      visible_success: qualificationCandidate,
      accepted,
      package_validated: packageValidated,
      artifact_results: artifactResults,
      repair_convergence: {
        initial_generation_succeeded: operationEvidence(workflow).some((operation) => operation.operation === "initial" && !operation.normalized_failure),
        repairs: Object.fromEntries(["L0", "L1", "L2", "L3"].map((level) => [level, operationEvidence(workflow).filter((operation) => operation.level === level && operation.operation === "repair").length])),
        total_model_operations: Number(workflow.provenance?.automatic_provider_operation_count ?? operationEvidence(workflow).length),
        highest_stage_reached: qualificationCandidate ? "candidate_ready" : workflow.state,
        visible_success: qualificationCandidate,
      },
      model_operations: operationEvidence(workflow),
      provenance_safe: !JSON.stringify(workflow).match(/GEMINI_API_KEY|Authorization|Bearer|sk-[A-Za-z0-9]/i),
      completed_at: new Date().toISOString(),
    };
    await writeJson(`${project.project_id}-result.json`, result);
    projectResults.push(result);

    if (failure) {
      const signature = `${failure.owner}:${failure.failure_class}`;
      const count = (failureSignatures.get(signature) ?? 0) + 1;
      failureSignatures.set(signature, count);
      if (count >= 2) {
        stopReason = `shared defect stop after ${count} occurrences of ${signature}`;
      }
    }
  }

  await writeJson("revision-a-result.json", {
    schema_version: "executable-cadquery-repeatability-revision-result-v1",
    status: projectResults.filter((result) => result.accepted).length >= 2 ? "not_attempted_by_harness" : "unavailable",
    reason: "fewer than two accepted creations were available after the sequential corpus stop",
  });
  await writeJson("revision-b-result.json", {
    schema_version: "executable-cadquery-repeatability-revision-result-v1",
    status: projectResults.filter((result) => result.accepted).length >= 2 ? "not_attempted_by_harness" : "unavailable",
    reason: "fewer than two accepted creations were available after the sequential corpus stop",
  });
  await writeJson("partial-output-result.json", {
    schema_version: "executable-cadquery-repeatability-partial-output-v1",
    status: stopReason ? "not_reached_shared_defect_stop" : "requires_project_06_execution",
    controlled_failure_used: false,
  });
  await writeJson("restart-result.json", {
    schema_version: "executable-cadquery-repeatability-restart-v1",
    status: stopReason ? "not_reached_shared_defect_stop" : "requires_controlled_restart",
    duplicate_provider_operations: null,
    duplicate_worker_jobs: null,
    browser_restore: null,
    artifacts_coherent: null,
  });
  await writeJson("repair-convergence.json", {
    schema_version: "executable-cadquery-repeatability-repair-convergence-v1",
    creations: projectResults.map((result) => ({ project_id: result.project_id, ...result.repair_convergence })),
  });
  await writeJson("artifact-package-results.json", {
    schema_version: "executable-cadquery-repeatability-artifact-results-v1",
    projects: projectResults.map((result) => ({ project_id: result.project_id, accepted: result.accepted, package_validated: result.package_validated, artifacts: result.artifact_results ?? [] })),
  });
  await writeJson("test-summary.json", {
    schema_version: "executable-cadquery-repeatability-test-summary-v1",
    project_results: projectResults.map((result) => ({ project_id: result.project_id, status: result.status, visible_success: result.visible_success, accepted: result.accepted, package_validated: result.package_validated })),
    stop_reason: stopReason,
    provider_calls: projectResults.reduce((sum, result) => sum + Number(result.repair_convergence?.total_model_operations ?? 0), 0),
  });
  await writeJson("final-decision.json", {
    schema_version: "executable-cadquery-repeatability-final-decision-v1",
    decision: projectResults.filter((result) => result.visible_success).length < 3
      ? "executable_cadquery_architecture_not_repeatable"
      : "executable_cadquery_provider_reliability_below_threshold",
    stop_reason: stopReason,
    candidate_ready_count: projectResults.filter((result) => result.visible_success).length,
    accepted_count: projectResults.filter((result) => result.accepted).length,
    package_count: projectResults.filter((result) => result.package_validated).length,
    revision_success_count: 0,
    unresolved_repeated_application_defect: Boolean(stopReason),
    main_modified: false,
  });
});
