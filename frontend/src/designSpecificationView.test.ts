import { describe, expect, it } from "vitest";
import {
  assumptionBuckets,
  canContinueGeneration,
  defaultProvenanceRows,
  protectedRequirementCount,
  requirementPresentationGroups,
  requirementProvenanceRows,
  requirementStageLabel,
  sourceLabel,
  traceFailureMessage,
  type DesignSpecificationSummary,
} from "./designSpecificationView";

function specification(overrides: Partial<DesignSpecificationSummary>): DesignSpecificationSummary {
  return {
    outcome: "generation_ready",
    generation_ready: true,
    clarification_required: false,
    specification: {
      purpose: "Mount a controller",
      critical_dimensions: [
        {
          id: "hole_spacing",
          label: "Hole spacing",
          value: 60,
          unit: "mm",
          source: "user",
          protected: true,
        },
      ],
      functional_requirements: [
        {
          id: "mounting_method",
          description: "Use two screws",
          source: "user",
          protected: true,
        },
      ],
      assumptions: [
        {
          id: "default_wall",
          description: "Use a 3 mm wall thickness",
          source: "product_default",
        },
        {
          id: "button_access",
          description: "Leave front access open",
          source: "ai_assumption",
        },
      ],
    },
    ...overrides,
  };
}

describe("design specification view helpers", () => {
  it("renders stable requirement-stage labels", () => {
    expect(requirementStageLabel(null)).toBe("Idle");
    expect(requirementStageLabel(specification({ outcome: "generation_ready" }))).toBe(
      "Requirements ready",
    );
    expect(
      requirementStageLabel(
        specification({
          outcome: "clarification_required",
          generation_ready: false,
          clarification_required: true,
        }),
      ),
    ).toBe("Waiting for clarification");
    expect(requirementStageLabel(specification({ outcome: "unsupported_request" }))).toBe(
      "Unsupported request",
    );
  });

  it("allows continue only for ready specifications", () => {
    expect(canContinueGeneration(specification({ outcome: "generation_ready" }))).toBe(true);
    expect(
      canContinueGeneration(
        specification({
          outcome: "clarification_required",
          generation_ready: false,
          clarification_required: true,
        }),
      ),
    ).toBe(false);
  });

  it("counts protected dimensions and requirements", () => {
    expect(protectedRequirementCount(specification({}))).toBe(2);
  });

  it("splits defaults from AI assumptions", () => {
    const buckets = assumptionBuckets(specification({}));

    expect(buckets.defaults).toEqual(["Use a 3 mm wall thickness"]);
    expect(buckets.aiAssumptions).toEqual(["Leave front access open"]);
  });

  it("renders provenance labels for explicit requirements and defaults", () => {
    expect(sourceLabel("user")).toBe("Your request");
    expect(sourceLabel("product_default")).toBe("Volundr functional default");
    expect(requirementProvenanceRows(specification({}))).toEqual([
      "Hole spacing: 60 mm. Source: Your request",
    ]);
    expect(defaultProvenanceRows(specification({}))).toEqual([
      "Use a 3 mm wall thickness. Source: Volundr functional default",
    ]);
  });

  it("renders a recoverable trace failure state", () => {
    expect(
      traceFailureMessage(
        specification({
          generation_ready: false,
          specification: {
            ...specification({}).specification,
            requirement_trace: {
              status: "blocked",
              findings: [{ rule_id: "design_plan.explicit_value_mismatch" }],
            },
          },
        }),
      ),
    ).toBe("Volundr could not preserve one of your supplied dimensions. The model has not been generated.");
  });

  it("separates user requirements, proposals, calculated values, and essential decisions", () => {
    const groups = requirementPresentationGroups(
      specification({
        outcome: "clarification_required",
        generation_ready: false,
        clarification_required: true,
        specification: {
          ...specification({}).specification,
          parameters: [
            { id: "wall", label: "Wall thickness", value: 3, unit: "mm", source: "product_default" },
            { id: "overall", label: "Overall width", value: 90, unit: "mm", source: "calculated" },
          ],
          missing_requirements: [
            { id: "height", label: "Maximum height", reason: "Needed to fit the available space." },
          ],
        },
      }),
    );

    expect(groups.userProvided).toEqual(["Hole spacing: 60 mm"]);
    expect(groups.proposals).toEqual(["Wall thickness: 3 mm"]);
    expect(groups.calculated).toEqual(["Overall width: 90 mm"]);
    expect(groups.essentialDecisions).toEqual(["Maximum height: Needed to fit the available space."]);
  });
});
