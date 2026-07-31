import { describe, expect, it } from "vitest";
import {
  canApproveDesignPlan,
  canGenerateFromDesignPlan,
  designPlanClarificationQuestions,
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
    expect(designPlanStageLabel(null)).toBe("Waiting for proposed design");
    expect(designPlanStageLabel(plan({ review_state: "pending_review" }))).toBe(
      "Ready for your review",
    );
    expect(designPlanStageLabel(plan({ review_state: "approved" }))).toBe("Ready to generate");
    expect(designPlanStageLabel(plan({ review_state: "clarification_required" }))).toBe(
      "A few design details are needed",
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

  it("uses persisted design plan clarification question ids when available", () => {
    expect(
      designPlanClarificationQuestions(
        plan({
          clarification_questions: [
            {
              id: "db-question",
              question: "Should the body and lid be separate outputs?",
              reason: "This affects the printable output manifest.",
            },
          ],
          plan: {
            clarification_questions: [
              {
                id: "provider-question",
                question: "Provider question",
              },
            ],
          },
        }),
      ),
    ).toEqual([
      {
        id: "db-question",
        question: "Should the body and lid be separate outputs?",
        reason: "This affects the printable output manifest.",
      },
    ]);
  });
});
