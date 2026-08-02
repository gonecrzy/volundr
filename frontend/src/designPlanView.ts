export type DesignPlanReviewState =
  | "clarification_required"
  | "pending_review"
  | "approved"
  | "rejected";

type RetentionProposal = {
  strategy?: string;
  release_behavior?: string;
  removal_direction?: string;
  parameters?: Array<{ id?: string; label?: string; value?: number | string | boolean | null; unit?: string | null }>;
  verification?: { human_review_required?: boolean };
};

export function retentionProposalLines(
  contract: { retention_interfaces?: RetentionProposal[] } | null | undefined,
): string[] {
  const retention = contract?.retention_interfaces?.[0];
  if (!retention) {
    return [];
  }
  const strategyLabels: Record<string, string> = {
    flexible_snap_arm: "Flexible snap arm",
    retaining_lip: "Retaining lip",
    spring_clip: "Spring clip",
    removable_strap: "Removable strap",
    rotating_gate: "Rotating gate",
    friction_band: "Friction band",
    latch: "Latch",
  };
  const lines = [strategyLabels[retention.strategy ?? ""] ?? retention.strategy ?? "Retention mechanism"];
  if (retention.release_behavior || retention.removal_direction) {
    const releaseLabel = (retention.release_behavior ?? "review required")
      .replace("one_handed", "one-handed")
      .replaceAll("_", " ");
    lines.push(
      `Release: ${releaseLabel}; removal direction: ${retention.removal_direction ?? "review required"}`,
    );
  }
  for (const parameter of retention.parameters ?? []) {
    if (!parameter.label || parameter.value === null || parameter.value === undefined) {
      continue;
    }
    lines.push(`${parameter.label}: ${parameter.value}${parameter.unit ? ` ${parameter.unit}` : ""}`);
  }
  if (retention.verification?.human_review_required) {
    lines.push("Final retention strength requires review and print testing");
  }
  return lines;
}

export type DesignPlanSummary = {
  outcome: "plan_ready" | "plan_clarification_required" | "plan_failed";
  review_state: DesignPlanReviewState;
  plan_ready: boolean;
  clarification_required: boolean;
  generated_revision_id?: string | null;
  clarification_questions?: Array<{
    id: string;
    question: string;
    reason?: string | null;
    related_plan_field?: string | null;
  }>;
  plan: {
    purpose?: string;
    design_level?: string;
    parameters?: Array<{
      id: string;
      label: string;
      value: number | string | boolean | null;
      unit?: string | null;
      source?: string;
      provenance?: { relationship?: string; explanation?: string | null };
      editable?: boolean;
      protected?: boolean;
    }>;
    derived_parameters?: Array<{
      id: string;
      label: string;
      value?: number | string | boolean | null;
      expression?: string | null;
      unit?: string | null;
      source?: string;
      provenance?: { relationship?: string; explanation?: string | null };
      depends_on?: string[];
    }>;
    dependency_edges?: Array<{
      from: string;
      to: string;
      relationship: string;
    }>;
    components?: Array<{
      id: string;
      label: string;
      features?: string[];
      parameters?: string[];
    }>;
    features?: Array<{
      id: string;
      component_id: string;
      type: string;
      description: string;
      protected?: boolean;
    }>;
    printable_outputs?: Array<{
      id: string;
      label: string;
      component_ids: string[];
      quantity: number;
    }>;
    risks?: Array<{
      id?: string;
      severity?: string;
      description?: string;
    }>;
    clarification_questions?: Array<{
      id?: string;
      question?: string;
      reason?: string;
    }>;
  };
};

export function designPlanStageLabel(plan: DesignPlanSummary | null): string {
  if (!plan) {
    return "Waiting for proposed design";
  }
  switch (plan.review_state) {
    case "clarification_required":
      return "A few design details are needed";
    case "pending_review":
      return "Ready for your review";
    case "approved":
      return "Ready to generate";
    case "rejected":
      return "Proposal not used";
  }
}

export function canApproveDesignPlan(plan: DesignPlanSummary | null): boolean {
  return plan?.review_state === "pending_review" && plan.plan_ready;
}

export function canGenerateFromDesignPlan(plan: DesignPlanSummary | null): boolean {
  return plan?.review_state === "approved" && plan.plan_ready && !plan.generated_revision_id;
}

export function designPlanClarificationQuestions(plan: DesignPlanSummary | null): Array<{
  id: string;
  question: string;
  reason?: string | null;
}> {
  const persisted = plan?.clarification_questions ?? [];
  if (persisted.length > 0) {
    return persisted;
  }
  return (plan?.plan.clarification_questions ?? [])
    .filter((question): question is { id: string; question: string; reason?: string } =>
      Boolean(question.id && question.question),
    )
    .map((question) => ({
      id: question.id,
      question: question.question,
      reason: question.reason,
    }));
}

export function designPlanSummaryCounts(plan: DesignPlanSummary | null): {
  parameters: number;
  derived: number;
  components: number;
  features: number;
  outputs: number;
} {
  return {
    parameters: plan?.plan.parameters?.length ?? 0,
    derived: plan?.plan.derived_parameters?.length ?? 0,
    components: plan?.plan.components?.length ?? 0,
    features: plan?.plan.features?.length ?? 0,
    outputs: plan?.plan.printable_outputs?.length ?? 0,
  };
}
