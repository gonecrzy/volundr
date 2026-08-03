export type ProviderResponseTechnical = {
  stage: string | null;
  classification: string | null;
  original_response_received: boolean;
  deterministic_normalization: boolean;
  repair_attempted: boolean;
  repair_outcome: string | null;
  final_stage: string | null;
};

export function describeProviderResponse(response: ProviderResponseTechnical): {
  received: string;
  normalization: string;
  repair: string;
  final: string;
} {
  return {
    received: response.original_response_received
      ? "Provider response received"
      : "Provider response not received",
    normalization: response.deterministic_normalization
      ? "Deterministically normalized"
      : "No deterministic normalization",
    repair: response.repair_attempted
      ? `Focused repair: ${response.repair_outcome ?? "attempted"}`
      : "No focused repair",
    final: finalResponseLabel(response.final_stage ?? response.classification),
  };
}

function finalResponseLabel(value: string | null): string {
  switch (value) {
    case "accepted":
    case "valid":
    case "valid_after_normalization":
    case "valid_after_repair":
      return "Accepted";
    case "unchanged_repair":
      return "Blocked: unchanged repair";
    case "regressive_repair":
      return "Blocked: regressive repair";
    default:
      return value ? `Blocked: ${value.replaceAll("_", " ")}` : "Final outcome pending";
  }
}

export function conciseProviderOutcome(stage: string): string {
  return `Volundr could not complete the ${stage} for this request. No working version was created.`;
}
