export type DesignPlanReviewState =
  | "clarification_required"
  | "pending_review"
  | "approved"
  | "rejected";

export type DesignPlanSummary = {
  outcome: "plan_ready" | "plan_clarification_required" | "plan_failed";
  review_state: DesignPlanReviewState;
  plan_ready: boolean;
  clarification_required: boolean;
  plan: {
    purpose?: string;
    design_level?: string;
    parameters?: Array<{
      id: string;
      label: string;
      value: number | string | boolean | null;
      unit?: string | null;
      editable?: boolean;
      protected?: boolean;
    }>;
    derived_parameters?: Array<{
      id: string;
      label: string;
      expression: string;
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
    return "Plan not created";
  }
  switch (plan.review_state) {
    case "clarification_required":
      return "Plan clarification required";
    case "pending_review":
      return "Plan review";
    case "approved":
      return "Plan approved";
    case "rejected":
      return "Plan rejected";
  }
}

export function canApproveDesignPlan(plan: DesignPlanSummary | null): boolean {
  return plan?.review_state === "pending_review" && plan.plan_ready;
}

export function canGenerateFromDesignPlan(plan: DesignPlanSummary | null): boolean {
  return plan?.review_state === "approved" && plan.plan_ready;
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
