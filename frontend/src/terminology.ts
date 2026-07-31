export const assistantVocabulary = {
  designSpecification: "Design requirements",
  designPlan: "Proposed design",
  revisionPlan: "Planned changes",
  candidateRevision: "New version",
  acceptedRevision: "Current design",
  protectedParameter: "Dimension to preserve",
  validationFinding: "Design check",
  sourceContract: "Model build checks",
  designConsistency: "Design consistency",
  topologyValidation: "Solid/body checks",
  revisionOutput: "Printable part",
  configurationChange: "Parameter update",
  componentRevision: "Change one part",
} as const;

export function provenanceLabel(source: string | undefined): string {
  switch (source) {
    case "user":
      return "You provided";
    case "clarification":
      return "You confirmed";
    case "product_default":
    case "printer_profile":
    case "ai_assumption":
      return "Volundr proposes";
    case "calculated":
      return "Calculated";
    default:
      return "Source not recorded";
  }
}

export function reviewStepLabel(step: "requirements" | "proposal"): string {
  return step === "requirements"
    ? "Step 1 of 2 - Your requirements"
    : "Step 2 of 2 - Proposed design";
}
