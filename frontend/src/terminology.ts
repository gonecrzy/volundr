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

export function provenanceRelationshipLabel(
  relationship: string | undefined,
  source?: string,
): string {
  switch (relationship) {
    case "direct":
      return "You provided";
    case "user_override":
      return "Your override";
    case "derived_formula":
    case "calculated":
      return "Calculated from the design requirements";
    case "standard_lookup":
      return "Volundr standard proposal";
    case "product_default":
    case "printer_default":
    case "ai_proposal":
      return "Volundr proposes";
    default:
      return provenanceLabel(source);
  }
}

export function reviewStepLabel(step: "requirements" | "proposal"): string {
  return step === "requirements"
    ? "Step 1 of 2 - Your requirements"
    : "Step 2 of 2 - Proposed design";
}
