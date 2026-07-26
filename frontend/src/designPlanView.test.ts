import { describe, expect, it } from "vitest";
import {
  canApproveDesignPlan,
  canGenerateFromDesignPlan,
  designPlanStageLabel,
  designPlanSummaryCounts,
  type DesignPlanSummary,
} from "./designPlanView";

function plan(overrides: Partial<DesignPlanSummary>): DesignPlanSummary {
  return {
    outcome: "plan_ready",
    review_state: "pending_review",
    plan_ready: true,
    clarification_required: false,
    plan: {
      purpose: "Mount a controller",
      design_level: "product",
      parameters: [{ id: "hole_spacing", label: "Hole spacing", value: 60 }],
      derived_parameters: [
        {
          id: "plate_width",
          label: "Plate width",
          expression: "hole_spacing + 30",
          depends_on: ["hole_spacing"],
        },
      ],
      components: [{ id: "body", label: "Body" }],
      features: [
        {
          id: "mounting_holes",
          component_id: "body",
          type: "hole_group",
          description: "Two holes",
        },
      ],
      printable_outputs: [
        { id: "body_output", label: "Body", component_ids: ["body"], quantity: 1 },
      ],
    },
    ...overrides,
  };
}

describe("design plan view helpers", () => {
  it("renders stable review labels", () => {
    expect(designPlanStageLabel(null)).toBe("Plan not created");
    expect(designPlanStageLabel(plan({ review_state: "pending_review" }))).toBe(
      "Plan review",
    );
    expect(designPlanStageLabel(plan({ review_state: "approved" }))).toBe("Plan approved");
    expect(designPlanStageLabel(plan({ review_state: "clarification_required" }))).toBe(
      "Plan clarification required",
    );
  });

  it("requires review approval before generation", () => {
    expect(canApproveDesignPlan(plan({ review_state: "pending_review" }))).toBe(true);
    expect(canGenerateFromDesignPlan(plan({ review_state: "pending_review" }))).toBe(false);
    expect(canApproveDesignPlan(plan({ review_state: "approved" }))).toBe(false);
    expect(canGenerateFromDesignPlan(plan({ review_state: "approved" }))).toBe(true);
    expect(canGenerateFromDesignPlan(plan({ review_state: "approved", generated_revision_id: "rev-1" }))).toBe(false);
  });

  it("summarizes generic product model sections", () => {
    expect(designPlanSummaryCounts(plan({}))).toEqual({
      parameters: 1,
      derived: 1,
      components: 1,
      features: 1,
      outputs: 1,
    });
  });
});
