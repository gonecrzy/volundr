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
      protected?: boolean;
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
