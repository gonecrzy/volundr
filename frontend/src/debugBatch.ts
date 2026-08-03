export type DebugBatchCapabilities = {
  developer_tools_enabled: boolean;
};

export type DebugBatchStartInput = {
  label: string;
  targetProjectCount: string | number;
  notes?: string;
  baselineBatchId?: string;
};

export type DebugBatchStartPayload = {
  label: string;
  target_project_count: number;
  notes?: string;
  baseline_batch_id?: string;
  frontend_build_identity: string;
};

export type DebugBatchMembership = {
  project_id: string;
  position: number;
  project_name?: string | null;
  missing: boolean;
  workflow_phase: string;
  worker_reached: boolean;
  current_working_revision_id: string | null;
  attempt_count: number;
  retry_count: number;
  provider_call_count: number;
  provider_retry_count: number;
  content_repair_count: number;
  generation_attempt_count: number;
  workflow_stage_attempt_count: number;
  user_operation_count: number;
  outcome_category: string;
  final_outcome: string;
};

export type DebugBatch = {
  id: string;
  label: string;
  notes: string | null;
  target_project_count: number;
  baseline_batch_id: string | null;
  state: "active" | "finishing" | "frozen" | "failed" | string;
  git_head: string;
  branch: string;
  migration_head: string;
  application_version: string;
  frontend_build_identity: string;
  backend_build_identity: string;
  worker_build_identity: string;
  provider: string;
  configured_default_model: string;
  stage_model_policy: Record<string, unknown>;
  actual_provider_models: Record<string, unknown>;
  prompt_versions: Record<string, unknown>;
  configuration_hash: string;
  started_at: string;
  finished_at: string | null;
  report_path: string | null;
  report_generation_state: string;
  evidence_contract_version: string;
  comparison_status: string;
  redaction_status: string;
  integrity_status: string;
  memberships: DebugBatchMembership[];
};

export type DebugBatchReport = {
  batch: DebugBatch;
  summary: Record<string, unknown>;
  report_path: string | null;
  codex_review_instruction: string | null;
};

export type DebugBatchComparison = {
  batch_id: string;
  baseline_batch_id: string;
  status: string;
  identity_match: boolean;
  mismatches: Record<string, Record<string, unknown>>;
  identity_evidence: Record<string, unknown>;
  project_comparisons: Array<Record<string, unknown>>;
};

export function normalizeDebugBatchStart(input: DebugBatchStartInput): {
  label: string;
  targetProjectCount: number;
  notes?: string;
  baselineBatchId?: string;
} {
  const label = input.label.trim();
  if (!label) {
    throw new Error("Batch name is required");
  }
  const targetProjectCount = Number(input.targetProjectCount);
  if (!Number.isInteger(targetProjectCount) || targetProjectCount < 1 || targetProjectCount > 20) {
    throw new Error("Target projects must be between 1 and 20");
  }
  const notes = input.notes?.trim() || undefined;
  const baselineBatchId = input.baselineBatchId?.trim() || undefined;
  return { label, targetProjectCount, notes, baselineBatchId };
}

export function buildDebugBatchStartPayload(
  input: DebugBatchStartInput,
  frontendBuildIdentity: string,
): DebugBatchStartPayload {
  const normalized = normalizeDebugBatchStart(input);
  return {
    label: normalized.label,
    target_project_count: normalized.targetProjectCount,
    ...(normalized.notes ? { notes: normalized.notes } : {}),
    ...(normalized.baselineBatchId ? { baseline_batch_id: normalized.baselineBatchId } : {}),
    frontend_build_identity: frontendBuildIdentity,
  };
}

const OUTCOME_LABELS: Record<string, string> = {
  not_started: "Not started",
  in_progress: "In progress",
  waiting_for_clarification: "Waiting for clarification",
  working_version_created: "Working version created",
  accepted: "Accepted",
  accepted_with_warnings: "Accepted with warnings",
  candidate_created: "Candidate created",
  blocked_before_worker: "Blocked before worker",
  blocked_after_worker: "Blocked after worker",
  interrupted: "Interrupted",
  infrastructure_failure: "Infrastructure failure",
};

export function debugBatchOutcomeLabel(value: string | null | undefined): string {
  return OUTCOME_LABELS[value ?? "not_started"] ?? "Not started";
}

export function safeFrontendDebugEvent(input: Record<string, unknown>): Record<string, unknown> {
  const allowed = [
    "event_type",
    "safe_endpoint_path",
    "project_id",
    "revision_id",
    "workflow_id",
    "visible_error_kind",
    "http_status",
    "occurred_at",
  ];
  return Object.fromEntries(allowed.filter((key) => input[key] !== undefined).map((key) => [key, input[key]]));
}

export function debugBatchProjectCount(batch: DebugBatch): number {
  return batch.memberships.length;
}
