import { describe, expect, it } from "vitest";
import { describeProviderResponse, conciseProviderOutcome } from "./providerResponsePresentation";

describe("provider response presentation", () => {
  it("distinguishes normalization, repair, and final classification without raw fields", () => {
    const presentation = describeProviderResponse({
      stage: "compact_plan",
      classification: "valid_after_repair",
      original_response_received: true,
      deterministic_normalization: true,
      repair_attempted: true,
      repair_outcome: "valid_after_repair",
      final_stage: "accepted",
    });

    expect(presentation).toEqual({
      received: "Provider response received",
      normalization: "Deterministically normalized",
      repair: "Focused repair: valid_after_repair",
      final: "Accepted",
    });
    expect(JSON.stringify(presentation)).not.toContain("schema");
    expect(JSON.stringify(presentation)).not.toContain("provenance");
  });

  it("keeps the normal chat outcome concise", () => {
    expect(conciseProviderOutcome("design plan")).toBe(
      "Volundr could not complete the design plan for this request. No working version was created.",
    );
  });
});
