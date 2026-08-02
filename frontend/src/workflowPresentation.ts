export type GenerationStage = {
  label: string;
  complete: boolean;
};

export type UserWorkflowPhase = "understanding" | "planning" | "creating" | "checking";

const phaseByStage: Record<UserWorkflowPhase, Set<string>> = {
  understanding: new Set([
    "project_request",
    "requirements",
    "requirement_extraction",
    "requirement_validation",
    "requirement_clarification",
    "clarification",
    "requirement_processing",
  ]),
  planning: new Set([
    "planning",
    "design_planning",
    "design_plan_generation",
    "design_plan_validation",
    "direct_brief",
    "compact_plan",
    "detailed_plan",
    "plan_validation",
    "planning_repair",
    "revision_planning",
  ]),
  creating: new Set([
    "source_generation",
    "source_extraction",
    "source_contract_validation",
    "contract_repair",
    "worker_submission",
    "cad_execution",
    "configuration_execution",
    "component_revision",
  ]),
  checking: new Set([
    "topology_validation",
    "mesh_validation",
    "functional_validation",
    "printability_validation",
    "candidate_classification",
    "output_preservation",
    "artifact_consistency",
    "snapshot_generation",
    "export",
  ]),
};

export function userWorkflowPhase(stage: string | null | undefined): UserWorkflowPhase | null {
  if (!stage) {
    return null;
  }
  for (const [phase, stages] of Object.entries(phaseByStage) as [UserWorkflowPhase, Set<string>][]) {
    if (stages.has(stage)) {
      return phase;
    }
  }
  return null;
}

export function workflowProgress(stage: string | null | undefined): {
  label: string;
  phase: UserWorkflowPhase | null;
  steps: Array<{ label: string; state: "complete" | "active" | "pending" }>;
} {
  const phase = userWorkflowPhase(stage);
  const phases: Array<[UserWorkflowPhase, string]> = [
    ["understanding", "Understanding"],
    ["planning", "Planning"],
    ["creating", "Creating"],
    ["checking", "Checking"],
  ];
  const activeIndex = phase ? phases.findIndex(([value]) => value === phase) : -1;
  return {
    label: phase === "understanding"
      ? "Understanding your request…"
      : phase === "planning"
        ? "Planning the design…"
        : phase === "checking"
          ? "Checking the model…"
          : "Creating the model…",
    phase,
    steps: phases.map(([value, label], index) => ({
      label,
      state: activeIndex < 0 ? "pending" : index < activeIndex ? "complete" : index === activeIndex ? "active" : "pending",
    })),
  };
}

const generationStages: Record<string, GenerationStage> = {
  project_request: { label: "Understanding your request", complete: false },
  requirement_extraction: { label: "Understanding requirements", complete: false },
  requirement_validation: { label: "Understanding requirements", complete: false },
  design_plan_generation: { label: "Planning the design", complete: false },
  design_plan_validation: { label: "Planning the design", complete: false },
  source_generation: { label: "Creating the CAD model", complete: false },
  source_extraction: { label: "Creating the CAD model", complete: false },
  source_contract_validation: { label: "Checking the model build", complete: false },
  contract_repair: { label: "Correcting a model-build issue", complete: false },
  worker_submission: { label: "Preparing printable parts", complete: false },
  cad_execution: { label: "Creating the CAD model", complete: false },
  topology_validation: { label: "Checking solid bodies", complete: false },
  mesh_validation: { label: "Checking printable parts", complete: false },
  printability_validation: { label: "Reviewing printability", complete: true },
  candidate_classification: { label: "Preparing your new version", complete: true },
};

export function generationProgress(stage: string | null | undefined): GenerationStage {
  return generationStages[stage ?? ""] ?? { label: "Preparing your design", complete: false };
}

export function candidateStatusSummary(input: {
  total: number;
  blockedRequired: number;
  ready: number;
}): string {
  if (input.blockedRequired > 0) {
    return `The full design cannot be accepted because ${input.blockedRequired === 1 ? "one required printable part is" : `${input.blockedRequired} required printable parts are`} blocked.`;
  }
  if (input.total === 0) {
    return "Printable parts are still being prepared.";
  }
  return `${input.ready}/${input.total} printable ${input.total === 1 ? "part is" : "parts are"} ready to review.`;
}

export type RecoveryPresentation = {
  title: string;
  currentDesignMessage: string;
  primaryAction: string;
  secondaryAction: string | null;
};

export function recoveryPresentation(stage: string | null | undefined): RecoveryPresentation {
  if (stage === "topology_validation") {
    return {
      title: "This printable part contains separate solid bodies that were expected to be connected.",
      currentDesignMessage: "Your current design was not changed.",
      primaryAction: "Revise this part",
      secondaryAction: "Try generation again",
    };
  }
  if (stage === "worker_failure") {
    return {
      title: "Volundr could not finish building this required printable part.",
      currentDesignMessage: "Your current design was not changed.",
      primaryAction: "Retry building this part",
      secondaryAction: "Reject new version",
    };
  }
  if (stage === "provider_response") {
    return {
      title: "The AI service could not complete this request.",
      currentDesignMessage: "No design changes were saved.",
      primaryAction: "Try again",
      secondaryAction: null,
    };
  }
  return {
    title: "Volundr could not build the proposed design consistently.",
    currentDesignMessage: "Your current design was not changed.",
    primaryAction: "Try generation again",
    secondaryAction: "Review proposed design",
  };
}
