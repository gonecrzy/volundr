export type RevisionPlanReviewState =
  | "clarification_required"
  | "pending_review"
  | "approved"
  | "rejected";

export type RevisionPlanOutcome =
  | "revision_ready"
  | "clarification_required"
  | "revision_conflict"
  | "unsupported_revision"
  | "planning_failed";

export type RevisionPlanSummary = {
  outcome: RevisionPlanOutcome;
  review_state: RevisionPlanReviewState;
  revision_ready: boolean;
  clarification_required: boolean;
  revision_plan: {
    summary?: string;
    requested_changes?: Array<{
      target_type: string;
      target_id: string;
      current_value?: number | string | boolean | null;
      requested_value?: number | string | boolean | null;
      change_type?: string;
      source?: string;
    }>;
    required_dependency_changes?: Array<{
      parameter_id: string;
      affects?: string[];
    }>;
    targeted_components?: string[];
    targeted_features?: string[];
    targeted_outputs?: string[];
    targeted_findings?: string[];
    protected_parameters?: Array<{
      parameter_id: string;
      expected_value?: number | string | boolean | null;
      unit?: string | null;
    }>;
    protected_components?: string[];
    protected_features?: string[];
    protected_outputs?: string[];
    prohibited_changes?: string[];
    success_criteria?: Array<{
      type: string;
      target_id: string;
      expected_value?: number | string | boolean | null;
      unit?: string | null;
    }>;
    clarification_questions?: Array<{
      id?: string;
      question?: string;
      reason?: string;
      related_requirement_id?: string;
    }>;
  };
};

export type RevisionComplianceFinding = {
  rule_id: string;
  is_blocking: boolean;
  title: string;
  explanation?: string;
  expected_value?: unknown;
  detected_value?: unknown;
  parameter_id?: string | null;
  component_id?: string | null;
  feature_id?: string | null;
  output_id?: string | null;
};

export type RevisionComplianceResult = {
  passed: boolean;
  findings: RevisionComplianceFinding[];
};

export type RevisionSuccessResult = {
  id: string;
  criterion_type: string;
  target_id: string;
  verification_state: "success_verified" | "success_violated" | "success_unverifiable";
  expected_value: unknown;
  detected_value: unknown;
  unit: string | null;
  tolerance: number | null;
  confidence: number;
  is_blocking: boolean;
  explanation: string;
  metadata: Record<string, unknown>;
};

export function revisionPlanStageLabel(plan: RevisionPlanSummary | null): string {
  if (!plan) {
    return "Revision plan not created";
  }
  switch (plan.review_state) {
    case "clarification_required":
      return "Revision clarification required";
    case "pending_review":
      return "Revision plan review";
    case "approved":
      return "Revision plan approved";
    case "rejected":
      return "Revision plan rejected";
  }
}

export function canApproveRevisionPlan(plan: RevisionPlanSummary | null): boolean {
  return plan?.review_state === "pending_review" && plan.revision_ready;
}

export function canGenerateFromRevisionPlan(plan: RevisionPlanSummary | null): boolean {
  return plan?.review_state === "approved" && plan.revision_ready;
}

export function revisionPlanSummaryCounts(plan: RevisionPlanSummary | null): {
  requestedChanges: number;
  dependencies: number;
  targetedComponents: number;
  targetedOutputs: number;
  protectedParameters: number;
  protectedOutputs: number;
  successCriteria: number;
} {
  return {
    requestedChanges: plan?.revision_plan.requested_changes?.length ?? 0,
    dependencies: plan?.revision_plan.required_dependency_changes?.length ?? 0,
    targetedComponents: plan?.revision_plan.targeted_components?.length ?? 0,
    targetedOutputs: plan?.revision_plan.targeted_outputs?.length ?? 0,
    protectedParameters: plan?.revision_plan.protected_parameters?.length ?? 0,
    protectedOutputs: plan?.revision_plan.protected_outputs?.length ?? 0,
    successCriteria: plan?.revision_plan.success_criteria?.length ?? 0,
  };
}

export function revisionComplianceBuckets(result: RevisionComplianceResult | null): {
  blocking: RevisionComplianceFinding[];
  advisory: RevisionComplianceFinding[];
} {
  const findings = result?.findings ?? [];
  return {
    blocking: findings.filter((finding) => finding.is_blocking),
    advisory: findings.filter((finding) => !finding.is_blocking),
  };
}

export function revisionSuccessBuckets(results: RevisionSuccessResult[]): {
  verified: RevisionSuccessResult[];
  violated: RevisionSuccessResult[];
  unverifiable: RevisionSuccessResult[];
} {
  return {
    verified: results.filter((result) => result.verification_state === "success_verified"),
    violated: results.filter((result) => result.verification_state === "success_violated"),
    unverifiable: results.filter((result) => result.verification_state === "success_unverifiable"),
  };
}
