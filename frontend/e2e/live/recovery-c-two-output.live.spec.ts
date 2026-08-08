import { createHash } from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { expect, test } from "@playwright/test";

const prompt =
  "Design a two-piece desktop storage box consisting of a separately printable box body and a separately printable lid. Keep the body approximately 80 mm wide by 60 mm deep by 30 mm high. Choose a reasonable printable wall thickness and lid clearance.";
const evidenceRoot = path.resolve(
  "..",
  "data",
  "debug-sessions",
  "executable-cadquery",
  "recovery-development-16",
  "recovery-c-live-two-output-confirmation",
);

function sha256(value: string | Buffer): string {
  return createHash("sha256").update(value).digest("hex");
}

function safeHistory(history: unknown): Array<Record<string, unknown>> {
  if (!Array.isArray(history)) return [];
  return history.map((entry) => {
    const item = entry && typeof entry === "object" ? entry as Record<string, any> : {};
    const provider = item.provider_attempt && typeof item.provider_attempt === "object"
      ? item.provider_attempt
      : {};
    const worker = item.worker_result && typeof item.worker_result === "object" ? item.worker_result : {};
    const topology = item.topology_result && typeof item.topology_result === "object" ? item.topology_result : {};
    const semantic = item.semantic_result && typeof item.semantic_result === "object" ? item.semantic_result : {};
    return {
      operation_id: item.operation_id ?? null,
      repair_level: item.repair_level ?? null,
      observed_stage: item.observed_stage ?? null,
      failure_boundary: item.failure_boundary ?? null,
      failure_class: item.failure_class ?? null,
      first_incorrect_owner: item.first_incorrect_owner ?? null,
      source_hash: item.source_hash ?? null,
      result_hash: item.result_hash ?? null,
      normalized_error: item.normalized_error ?? null,
      provider_attempt: {
        attempt_id: provider.attempt_id ?? null,
        logical_operation_id: provider.logical_operation_id ?? null,
        credential_slot: provider.credential_slot ?? null,
        status_code: provider.status_code ?? null,
        transport_retry_classification: provider.transport_retry_classification ?? null,
        rate_limit_429_classification: provider.rate_limit_429_classification ?? null,
        raw_response_hash: provider.raw_response_hash ?? null,
      },
      worker_result: {
        job_id: worker.job_id ?? null,
        success: worker.success ?? null,
        output_ids: worker.output_ids ?? [],
        result_hash: worker.result_hash ?? null,
      },
      topology_result: {
        valid: topology.valid ?? null,
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

function safeWorkflow(workflow: Record<string, any>): Record<string, any> {
  const provenance = workflow.provenance && typeof workflow.provenance === "object"
    ? workflow.provenance
    : {};
  return {
    id: workflow.id ?? null,
    project_id: workflow.project_id ?? null,
    revision_id: workflow.revision_id ?? null,
    state: workflow.state ?? null,
    route: workflow.route ?? null,
    user_instruction_sha256: typeof workflow.user_instruction === "string"
      ? sha256(workflow.user_instruction)
      : sha256(prompt),
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
      contract_source: provenance.contract_source ?? null,
      provider_id: provenance.provider_id ?? null,
      provider_transport: provenance.provider_transport ?? null,
      source_generation_mode: provenance.source_generation_mode ?? null,
      source_hash: provenance.source_hash ?? null,
      output_ids: provenance.output_ids ?? null,
      automatic_provider_operation_count: provenance.automatic_provider_operation_count ?? null,
      automatic_provider_operation_budget: provenance.automatic_provider_operation_budget ?? null,
      repair_history: safeHistory(provenance.repair_history),
    },
  };
}

test("confirms first-class logical outputs through the normal product path", async ({ page }) => {
  test.setTimeout(3_600_000);
  expect(process.env.VOLUNDR_EXECUTABLE_CADQUERY_CORPUS_MANIFEST_PATH ?? "").toBe("");
  await fs.mkdir(evidenceRoot, { recursive: true });
  await fs.writeFile(
    path.join(evidenceRoot, "prompt.json"),
    `${JSON.stringify({ prompt, prompt_sha256: sha256(prompt), corpus_manifest: "unset" }, null, 2)}\n`,
    "utf8",
  );

  const idempotencyKey = "recovery-c-two-output-synthetic";
  const startedAt = new Date().toISOString();
  const response = await page.request.post("/api/validated-cadquery/designs", {
    headers: { "Idempotency-Key": idempotencyKey },
    data: { name: "synthetic-two-piece-storage-box", intent: prompt },
    timeout: 1_500_000,
  });
  const responseText = await response.text();
  let initial: Record<string, any> = {};
  try {
    initial = JSON.parse(responseText) as Record<string, any>;
  } catch {
    initial = { response_text: responseText.slice(0, 2000) };
  }

  let workflow: Record<string, any> = initial;
  let artifacts: Array<Record<string, any>> = [];
  let attempts: Array<Record<string, any>> = [];
  let downloadedArtifacts: Array<Record<string, any>> = [];
  if (typeof initial.id === "string") {
    const workflowResponse = await page.request.get(`/api/validated-cadquery/workflows/${initial.id}`);
    expect(workflowResponse.ok()).toBeTruthy();
    workflow = await workflowResponse.json() as Record<string, any>;
    const artifactResponse = await page.request.get(`/api/validated-cadquery/workflows/${initial.id}/artifacts`);
    if (artifactResponse.ok()) artifacts = await artifactResponse.json() as Array<Record<string, any>>;
    const attemptsResponse = await page.request.get(`/api/projects/${workflow.project_id}/generation-attempts`);
    if (attemptsResponse.ok()) attempts = await attemptsResponse.json() as Array<Record<string, any>>;
    const artifactDir = path.join(evidenceRoot, "artifacts");
    await fs.mkdir(artifactDir, { recursive: true });
    downloadedArtifacts = [];
    for (const artifact of artifacts) {
      if (!artifact.available || !artifact.download_url || !["step", "stl", "brep"].includes(String(artifact.kind))) continue;
      const artifactResponse = await page.request.get(String(artifact.download_url));
      if (!artifactResponse.ok()) continue;
      const bytes = Buffer.from(await artifactResponse.body());
      const filename = `${String(artifact.output_id ?? "output").replace(/[^A-Za-z0-9_.-]/g, "-")}.${artifact.kind}`;
      await fs.writeFile(path.join(artifactDir, filename), bytes);
      downloadedArtifacts.push({
        artifact_id: artifact.artifact_id ?? null,
        output_id: artifact.output_id ?? null,
        kind: artifact.kind,
        sha256: sha256(bytes),
        size_bytes: bytes.length,
      });
    }
  }

  const safe = safeWorkflow(workflow);
  const contract = safe.design_contract && typeof safe.design_contract === "object"
    ? safe.design_contract as Record<string, any>
    : {};
  const outputIds = Array.isArray(contract.outputs)
    ? contract.outputs.map((output: Record<string, any>) => String(output.output_id ?? ""))
    : [];
  const semantic = safe.verification?.semantic_verification ?? {};
  const rawEvidence = {
    schema_version: "recovery-c-live-two-output-confirmation-raw-v1",
    started_at: startedAt,
    finished_at: new Date().toISOString(),
    prompt_sha256: sha256(prompt),
    idempotency_key: idempotencyKey,
    http_status: response.status(),
    initial_response: {
      id: initial.id ?? null,
      state: initial.state ?? null,
      project_id: initial.project_id ?? null,
    },
    workflow: safe,
    generation_attempts: attempts.map((attempt) => ({
      id: attempt.id ?? null,
      attempt_number: attempt.attempt_number ?? null,
      status: attempt.status ?? null,
      provider: attempt.provider ?? null,
      model: attempt.model ?? attempt.model_id ?? null,
      prompt_version: attempt.prompt_version ?? null,
      failure_class: attempt.failure_class ?? null,
    })),
    artifacts,
    downloaded_artifacts: downloadedArtifacts,
    reference_isolation: {
      reference_geometry_supplied: false,
      request_body: { name: "synthetic-two-piece-storage-box", intent_sha256: sha256(prompt) },
    },
  };
  await fs.writeFile(path.join(evidenceRoot, "raw-live-evidence.json"), `${JSON.stringify(rawEvidence, null, 2)}\n`, "utf8");
  await fs.writeFile(
    path.join(evidenceRoot, "live-confirmation-assessment.json"),
    `${JSON.stringify({
      schema_version: "recovery-c-live-two-output-confirmation-v1",
      decision: outputIds.length === 2 ? "RECOVERY_C_LIVE_CONFIRMED" : "RECOVERY_C_PIPELINE_DEFECT",
      prompt,
      corpus_manifest: "unset",
      contract_source: contract.contract_source ?? null,
      contract_output_ids: outputIds,
      logical_output_count: outputIds.length,
      generated_output_ids: Array.isArray(safe.outputs)
        ? safe.outputs.map((output: Record<string, any>) => output.output_id ?? null)
        : [],
      semantic_counts: {
        total: Array.isArray(semantic.findings) ? semantic.findings.length : null,
        passed: semantic.passed ?? [],
        failed: semantic.failed ?? [],
        unverifiable: semantic.unverifiable ?? [],
        review_required: semantic.review_required ?? [],
        unsupported: semantic.unsupported ?? [],
        status: semantic.status ?? null,
      },
      provider_attempts: safe.provenance.repair_history,
      provider_call_count: safe.provenance.automatic_provider_operation_count ?? null,
      worker_executions: safe.provenance.repair_history.filter((entry: Record<string, any>) => entry.worker_result?.job_id).length,
      downloaded_artifacts: downloadedArtifacts,
      reference_isolation: rawEvidence.reference_isolation,
      note: "A generated source that omits a declared required output remains a geometry/source failure; this assessment only treats the identity path as confirmed when the contract preserves both IDs.",
    }, null, 2)}\n`,
    "utf8",
  );
});
