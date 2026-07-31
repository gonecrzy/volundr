export type RequirementOutcome =
  | "generation_ready"
  | "clarification_required"
  | "requirements_conflict"
  | "unsupported_request"
  | "extraction_failed";

export type DesignSpecificationSummary = {
  outcome: RequirementOutcome;
  generation_ready: boolean;
  clarification_required: boolean;
  specification: {
    purpose?: string;
    critical_dimensions?: Array<{
      id: string;
      label: string;
      value: number | string | boolean | null;
      unit?: string | null;
      source: string;
      authority?: string;
      protected?: boolean;
    }>;
    parameters?: Array<{
      id: string;
      label: string;
      value: number | string | boolean | null;
      unit?: string | null;
      source: string;
      protected?: boolean;
      explanation?: string | null;
    }>;
    assumptions?: Array<{
      id: string;
      description: string;
      source: string;
      requires_approval?: boolean;
    }>;
    functional_requirements?: Array<{
      id: string;
      description: string;
      source: string;
      protected?: boolean;
    }>;
    conflicts?: Array<{ description?: string; id?: string }>;
    missing_requirements?: Array<{ label?: string; reason?: string; id?: string }>;
    requirement_trace?: {
      status?: string;
      findings?: Array<{ rule_id?: string; message?: string }>;
    };
    validation_status?: string;
  };
};

export function requirementStageLabel(specification: DesignSpecificationSummary | null): string {
  if (!specification) {
    return "Idle";
  }
  switch (specification.outcome) {
    case "generation_ready":
      return "Requirements ready";
    case "clarification_required":
      return "Waiting for clarification";
    case "requirements_conflict":
      return "Requirements conflict";
    case "unsupported_request":
      return "Unsupported request";
    case "extraction_failed":
      return "Extraction failed";
  }
}

export function canContinueGeneration(specification: DesignSpecificationSummary | null): boolean {
  return specification?.outcome === "generation_ready" && specification.generation_ready;
}

export function protectedRequirementCount(specification: DesignSpecificationSummary | null): number {
  if (!specification) {
    return 0;
  }
  const dimensions = specification.specification.critical_dimensions ?? [];
  const requirements = specification.specification.functional_requirements ?? [];
  return (
    dimensions.filter((dimension) => dimension.protected).length +
    requirements.filter((requirement) => requirement.protected).length
  );
}

export function assumptionBuckets(specification: DesignSpecificationSummary | null): {
  defaults: string[];
  aiAssumptions: string[];
} {
  const assumptions = specification?.specification.assumptions ?? [];
  return {
    defaults: assumptions
      .filter((assumption) => assumption.source === "product_default" || assumption.source === "printer_profile")
      .map((assumption) => assumption.description),
    aiAssumptions: assumptions
      .filter((assumption) => assumption.source === "ai_assumption")
      .map((assumption) => assumption.description),
  };
}

export function sourceLabel(source: string | undefined): string {
  switch (source) {
    case "user":
      return "Your request";
    case "clarification":
      return "Your clarification";
    case "printer_profile":
      return "Printer profile default";
    case "product_default":
      return "Volundr functional default";
    case "calculated":
      return "Calculated";
    case "ai_assumption":
      return "AI assumption";
    default:
      return source ?? "Unknown";
  }
}

export function requirementProvenanceRows(specification: DesignSpecificationSummary | null): string[] {
  const dimensions = specification?.specification.critical_dimensions ?? [];
  return dimensions.map((dimension) => {
    const value = `${dimension.value ?? "unset"}${dimension.unit ? ` ${dimension.unit}` : ""}`;
    return `${dimension.label}: ${value}. Source: ${sourceLabel(dimension.source)}`;
  });
}

export function defaultProvenanceRows(specification: DesignSpecificationSummary | null): string[] {
  const assumptions = specification?.specification.assumptions ?? [];
  return assumptions
    .filter((assumption) => assumption.source === "product_default" || assumption.source === "printer_profile")
    .map((assumption) => `${assumption.description}. Source: ${sourceLabel(assumption.source)}`);
}

export function requirementPresentationGroups(specification: DesignSpecificationSummary | null): {
  userProvided: string[];
  proposals: string[];
  calculated: string[];
  essentialDecisions: string[];
} {
  const dimensions = specification?.specification.critical_dimensions ?? [];
  const parameters = specification?.specification.parameters ?? [];
  const renderValue = (entry: { label: string; value: unknown; unit?: string | null }) =>
    `${entry.label}: ${entry.value ?? "not set"}${entry.unit ? ` ${entry.unit}` : ""}`;
  const userProvided = dimensions
    .filter((dimension) => dimension.source === "user" || dimension.source === "clarification")
    .map(renderValue);
  const groupedParameters = [...dimensions, ...parameters];
  const proposals = groupedParameters
    .filter((entry) => ["product_default", "printer_profile", "ai_assumption"].includes(entry.source))
    .map(renderValue);
  const calculated = groupedParameters.filter((entry) => entry.source === "calculated").map(renderValue);
  const essentialDecisions = (specification?.specification.missing_requirements ?? []).map((missing) =>
    [missing.label ?? missing.id ?? "A decision", missing.reason].filter(Boolean).join(": "),
  );
  return { userProvided, proposals, calculated, essentialDecisions };
}

export function traceFailureMessage(specification: DesignSpecificationSummary | null): string | null {
  const trace = specification?.specification.requirement_trace;
  if (trace?.status === "blocked" || specification?.specification.validation_status === "blocked") {
    return "Volundr could not preserve one of your supplied dimensions. The model has not been generated.";
  }
  return null;
}
