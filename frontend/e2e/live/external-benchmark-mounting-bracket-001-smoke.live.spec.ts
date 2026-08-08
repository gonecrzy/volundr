import { test } from "@playwright/test";
import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";

const evidenceRoot = path.resolve(
  "..",
  "data",
  "debug-sessions",
  "external-benchmarks",
  "mounting-brackets-v1",
  "smoke-001",
);
const liveDataDir = process.env.VOLUNDR_LIVE_DATA_DIR ?? "/tmp/volundr-live-e2e-unconfigured";
const manifestPath = path.resolve("..", "benchmarks", "external", "mounting-brackets-v1", "manifest.json");
const selectedMode = process.env.VOLUNDR_EXTERNAL_BENCHMARK_MODE;

if (process.env.VOLUNDR_EXECUTABLE_CADQUERY_CORPUS_MANIFEST_PATH) {
  throw new Error(
    "External benchmark runs must use the production requirement path; use the external benchmark runner, not a corpus contract manifest.",
  );
}
if (selectedMode && !["premise_only", "reference_specification"].includes(selectedMode)) {
  throw new Error(`Unsupported VOLUNDR_EXTERNAL_BENCHMARK_MODE: ${selectedMode}`);
}

type JsonObject = Record<string, any>;

function sha256(value: string | Buffer) {
  return crypto.createHash("sha256").update(value).digest("hex");
}

async function readManifestProject() {
  const manifest = JSON.parse(await fs.readFile(manifestPath, "utf8")) as JsonObject;
  const project = manifest.projects.find((item: JsonObject) => item.benchmark_id === "mounting-bracket-001");
  if (!project) throw new Error("mounting-bracket-001 is absent from the locked manifest");
  return { manifest, project };
}

function safeHistory(history: unknown) {
  if (!Array.isArray(history)) return [];
  return history.map((item: JsonObject) => {
    const providerAttempt = item.provider_attempt && typeof item.provider_attempt === "object"
      ? item.provider_attempt
      : {};
    const transportAttempts = Array.isArray(providerAttempt.transport_attempts)
      ? providerAttempt.transport_attempts.map((transport: JsonObject) => ({
          logical_operation_id: transport.logical_operation_id ?? null,
          attempt_id: transport.attempt_id ?? null,
          credential_slot: transport.credential_slot ?? null,
          request_started_at: transport.request_started_at ?? null,
          status_code: transport.status_code ?? null,
          response_received: transport.response_received ?? null,
          response_length: transport.response_length ?? null,
          raw_response_hash: transport.raw_response_hash ?? null,
          exception_type: transport.exception_type ?? null,
          normalized_transport_error: transport.normalized_transport_error ?? null,
          transport_retry_classification: transport.transport_retry_classification ?? null,
          rate_limit_429_classification: transport.rate_limit_429_classification ?? null,
        }))
      : [];
    const worker = item.worker_result && typeof item.worker_result === "object" ? item.worker_result : {};
    const topology = item.topology_result && typeof item.topology_result === "object" ? item.topology_result : {};
    const semantic = item.semantic_result && typeof item.semantic_result === "object" ? item.semantic_result : {};
    return {
      operation_id: item.operation_id ?? null,
      attempt_number: item.attempt_number ?? null,
      repair_level: item.repair_level ?? null,
      observed_stage: item.observed_stage ?? null,
      failure_boundary: item.failure_boundary ?? null,
      failure_class: item.failure_class ?? null,
      first_incorrect_owner: item.first_incorrect_owner ?? null,
      source_hash: item.source_hash ?? null,
      extracted_source_hash: item.extracted_source_hash ?? null,
      raw_response_hash: item.raw_response_hash ?? null,
      extraction_succeeded: item.extraction_succeeded ?? null,
      syntax_valid: item.syntax_valid ?? null,
      source_contract_valid: item.source_contract_valid ?? null,
      result_hash: item.result_hash ?? null,
      normalized_error: item.normalized_error ?? null,
      progress: item.progress ?? null,
      revision_id: item.revision_id ?? null,
      provider_attempt: {
        attempt_number: providerAttempt.attempt_number ?? null,
        level: providerAttempt.level ?? null,
        status: providerAttempt.status ?? null,
        failure_class: providerAttempt.failure_class ?? null,
        logical_operation_id: providerAttempt.logical_operation_id ?? null,
        attempt_id: providerAttempt.attempt_id ?? null,
        credential_slot: providerAttempt.credential_slot ?? null,
        request_started_at: providerAttempt.request_started_at ?? null,
        status_code: providerAttempt.status_code ?? null,
        response_received: providerAttempt.response_received ?? null,
        response_length: providerAttempt.response_length ?? null,
        raw_response_hash: providerAttempt.raw_response_hash ?? null,
        exception_type: providerAttempt.exception_type ?? null,
        normalized_transport_error: providerAttempt.normalized_transport_error ?? null,
        transport_retry_classification: providerAttempt.transport_retry_classification ?? null,
        rate_limit_429_classification: providerAttempt.rate_limit_429_classification ?? null,
        transport_attempts: transportAttempts,
      },
      worker_result: {
        job_id: worker.job_id ?? null,
        phase: worker.phase ?? null,
        success: worker.success ?? null,
        failure_class: worker.failure_class ?? null,
        output_ids: worker.output_ids ?? [],
        result_hash: worker.result_hash ?? null,
        execution_manifest_path: worker.execution_manifest_path ?? null,
      },
      topology_result: {
        valid: topology.valid ?? null,
        outcome: topology.outcome ?? null,
        detected_solid_count: topology.detected_solid_count ?? null,
        expected_solid_count: topology.expected_solid_count ?? null,
        schema_version: topology.schema_version ?? null,
      },
      semantic_result: {
        status: semantic.status ?? null,
        passed: semantic.passed ?? [],
        failed: semantic.failed ?? [],
        unverifiable: semantic.unverifiable ?? [],
        review_required: semantic.review_required ?? [],
        unsupported: semantic.unsupported ?? [],
      },
    };
  });
}

function safeWorkflow(workflow: JsonObject | null) {
  if (!workflow) return null;
  const provenance = workflow.provenance && typeof workflow.provenance === "object" ? workflow.provenance : {};
  return {
    id: workflow.id ?? null,
    project_id: workflow.project_id ?? null,
    revision_id: workflow.revision_id ?? null,
    parent_workflow_id: workflow.parent_workflow_id ?? null,
    state: workflow.state ?? null,
    route: workflow.route ?? null,
    user_instruction_sha256: typeof workflow.user_instruction === "string" ? sha256(workflow.user_instruction) : null,
    requirements: workflow.requirements ?? {},
    plan: workflow.plan ?? {},
    design_contract: provenance.executable_design_contract ?? null,
    verification: workflow.verification ?? {},
    candidate_policy: workflow.candidate_policy ?? {},
    diagnostics: workflow.diagnostics ?? {},
    package_manifest: workflow.package_manifest ?? {},
    package_available: workflow.package_available ?? false,
    outputs: workflow.outputs ?? [],
    provenance: {
      provider_id: provenance.provider_id ?? null,
      provider_transport: provenance.provider_transport ?? null,
      source_generation_mode: provenance.source_generation_mode ?? null,
      source_hash: provenance.source_hash ?? null,
      output_ids: provenance.output_ids ?? null,
      accepted_revision_id: provenance.accepted_revision_id ?? null,
      automatic_provider_operation_count: provenance.automatic_provider_operation_count ?? null,
      automatic_provider_operation_budget: provenance.automatic_provider_operation_budget ?? null,
      repair_history: safeHistory(provenance.repair_history),
    },
  };
}

async function jsonResponse(response: any) {
  const text = await response.text();
  try {
    return { status: response.status(), body: JSON.parse(text) as JsonObject };
  } catch {
    return { status: response.status(), body_text: text.slice(0, 1200) };
  }
}

async function getJson(page: any, endpoint: string) {
  const response = await page.request.get(endpoint);
  return jsonResponse(response);
}

async function runSmoke(page: any, mode: "premise_only" | "reference_specification", prompt: string, idempotencyKey: string) {
  const startedAt = new Date().toISOString();
  const requestBody = { name: "mounting-bracket-001", intent: prompt };
  const startResponse = await page.request.post("/api/validated-cadquery/designs", {
    headers: { "Idempotency-Key": idempotencyKey },
    data: requestBody,
  });
  const start = await jsonResponse(startResponse);
  const initialWorkflow = start.body && typeof start.body.id === "string" ? start.body : null;
  let acceptance: JsonObject | null = null;
  let finalWorkflow: JsonObject | null = initialWorkflow;
  let artifacts: JsonObject[] = [];
  let attempts: JsonObject[] = [];
  const downloadedArtifacts: JsonObject[] = [];

  if (initialWorkflow) {
    const workflowResponse = await getJson(page, `/api/validated-cadquery/workflows/${initialWorkflow.id}`);
    finalWorkflow = workflowResponse.body && typeof workflowResponse.body.id === "string" ? workflowResponse.body : initialWorkflow;
    if (["candidate_ready", "revision_ready"].includes(String(finalWorkflow.state))) {
      const acceptResponse = await page.request.post(`/api/validated-cadquery/workflows/${initialWorkflow.id}/accept`, {
        headers: { "Idempotency-Key": `${idempotencyKey}-accept` },
        data: {},
      });
      acceptance = await jsonResponse(acceptResponse);
      const acceptedWorkflow = await getJson(page, `/api/validated-cadquery/workflows/${initialWorkflow.id}`);
      if (acceptedWorkflow.body && typeof acceptedWorkflow.body.id === "string") finalWorkflow = acceptedWorkflow.body;
    }
    const artifactResponse = await getJson(page, `/api/validated-cadquery/workflows/${initialWorkflow.id}/artifacts`);
    if (Array.isArray(artifactResponse.body)) artifacts = artifactResponse.body;
    const attemptsResponse = await getJson(page, `/api/projects/${initialWorkflow.project_id}/generation-attempts`);
    if (Array.isArray(attemptsResponse.body)) attempts = attemptsResponse.body;
    for (const artifact of artifacts) {
      if (!artifact.available || !artifact.download_url || !["step", "stl", "brep"].includes(String(artifact.kind))) continue;
      const artifactResponse = await page.request.get(artifact.download_url);
      if (!artifactResponse.ok()) continue;
      const bytes = Buffer.from(await artifactResponse.body());
      const artifactDirectory = path.join(liveDataDir, "external-benchmark-smoke", mode);
      await fs.mkdir(artifactDirectory, { recursive: true });
      const targetPath = path.join(artifactDirectory, `${String(artifact.output_id).replace(/[^A-Za-z0-9_.-]/g, "-")}.${artifact.kind}`);
      await fs.writeFile(targetPath, bytes);
      downloadedArtifacts.push({
        artifact_id: artifact.artifact_id,
        output_id: artifact.output_id,
        kind: artifact.kind,
        path: targetPath,
        sha256: sha256(bytes),
        expected_sha256: artifact.sha256,
      });
    }
  }

  return {
    schema_version: "external-cad-benchmark-smoke-raw-v1",
    benchmark_project_id: "mounting-bracket-001",
    mode,
    prompt,
    prompt_sha256: sha256(prompt),
    idempotency_key: idempotencyKey,
    started_at: startedAt,
    start_response: start,
    initial_workflow: safeWorkflow(initialWorkflow),
    acceptance,
    final_workflow: safeWorkflow(finalWorkflow),
    artifacts,
    downloaded_artifacts: downloadedArtifacts,
    generation_attempts: attempts,
    reference_only_isolation: {
      reference_geometry_sent_in_request: false,
      request_body_keys: Object.keys(requestBody).sort(),
      forbidden_reference_identifiers_in_request: [
        "https://www.printables.com/model/509653",
        "speed-sensor-bracket.step",
        "ba49cf0037e2f1decff2d1e1b4cd987674f0f8be30d6cc71bb9d6901f1079d90",
      ].filter((value) => JSON.stringify(requestBody).includes(value)),
    },
    finished_at: new Date().toISOString(),
  };
}

test("runs the two mounting-bracket-001 smoke modes sequentially", async ({ page }) => {
  test.setTimeout(3_600_000);
  const { project } = await readManifestProject();
  const premise = selectedMode === "reference_specification"
    ? null
    : await runSmoke(page, "premise_only", project.premise, "mounting-bracket-001-premise-only");
  await fs.mkdir(evidenceRoot, { recursive: true });
  if (premise) {
    await fs.writeFile(path.join(evidenceRoot, "premise-only-raw.json"), `${JSON.stringify(premise, null, 2)}\n`, "utf8");
  }

  const referenceSpecification = selectedMode === "premise_only"
    ? null
    : await runSmoke(
        page,
        "reference_specification",
        project.reference_spec.prompt,
        "mounting-bracket-001-reference-specification",
      );
  if (referenceSpecification) {
    await fs.writeFile(path.join(evidenceRoot, "reference-specification-raw.json"), `${JSON.stringify(referenceSpecification, null, 2)}\n`, "utf8");
  }
  await fs.writeFile(
    path.join(evidenceRoot, "smoke-order.json"),
    `${JSON.stringify({
      schema_version: "external-cad-benchmark-smoke-order-v1",
      benchmark_project_id: "mounting-bracket-001",
      sequential: true,
      modes: selectedMode ? [selectedMode] : ["premise_only", "reference_specification"],
      provider_calls_requested_by_harness: selectedMode ? 1 : 2,
      reference_geometry_sent_to_provider: false,
      live_data_dir: liveDataDir,
    }, null, 2)}\n`,
    "utf8",
  );
});
