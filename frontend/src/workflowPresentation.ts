export type GenerationStage = {
  label: string;
  complete: boolean;
};

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
      title: "One printable part needs another design pass.",
      currentDesignMessage: "Your current design was not changed.",
      primaryAction: "Revise this part",
      secondaryAction: "Try generation again",
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
