import { describe, expect, it } from "vitest";
import {
  canApproveRevisionPlan,
  canGenerateFromRevisionPlan,
  componentRevisionCounts,
  revisionComplianceBuckets,
  revisionPlanStageLabel,
  revisionPlanSummaryCounts,
  revisionSuccessBuckets,
  type RevisionComplianceResult,
  type RevisionPlanSummary,
  type RevisionSuccessResult,
} from "./revisionPlanView";

function plan(overrides: Partial<RevisionPlanSummary>): RevisionPlanSummary {
  return {
    outcome: "revision_ready",
    review_state: "pending_review",
    revision_ready: true,
    clarification_required: false,
    revision_plan: {
      summary: "Increase lid thickness",
      requested_changes: [
        {
          target_type: "product_parameter",
          target_id: "lid_thickness",
          current_value: 3,
          requested_value: 4,
          change_type: "replace",
          source: "user",
        },
      ],
      required_dependency_changes: [{ parameter_id: "lid_thickness", affects: ["lid_lip_depth"] }],
      targeted_components: ["lid"],
      targeted_features: ["lid_panel"],
      targeted_outputs: ["lid"],
      protected_parameters: [{ parameter_id: "wall_thickness", expected_value: 3, unit: "mm" }],
      protected_components: ["body"],
      protected_features: ["body_shell"],
      protected_outputs: ["body"],
      success_criteria: [
        { type: "parameter_value", target_id: "lid_thickness", expected_value: 4, unit: "mm" },
      ],
      clarification_questions: [],
    },
    ...overrides,
  };
}

function success(overrides: Partial<RevisionSuccessResult>): RevisionSuccessResult {
  return {
    id: "success-1",
    criterion_type: "parameter_value",
    target_id: "lid_thickness",
    verification_state: "success_verified",
    expected_value: 4,
    detected_value: 4,
    unit: "mm",
    tolerance: null,
    confidence: 1,
    is_blocking: false,
    explanation: "Matched.",
    metadata: {},
    ...overrides,
  };
}

describe("revision plan view helpers", () => {
  it("renders stable lifecycle labels", () => {
    expect(revisionPlanStageLabel(null)).toBe("Revision plan not created");
    expect(revisionPlanStageLabel(plan({ review_state: "pending_review" }))).toBe(
      "Revision plan review",
    );
    expect(revisionPlanStageLabel(plan({ review_state: "approved" }))).toBe(
      "Revision plan approved",
    );
    expect(revisionPlanStageLabel(plan({ review_state: "clarification_required" }))).toBe(
      "Revision clarification required",
    );
  });

  it("requires explicit approval before source revision", () => {
    expect(canApproveRevisionPlan(plan({ review_state: "pending_review" }))).toBe(true);
    expect(canGenerateFromRevisionPlan(plan({ review_state: "pending_review" }))).toBe(false);
    expect(canApproveRevisionPlan(plan({ review_state: "approved" }))).toBe(false);
    expect(canGenerateFromRevisionPlan(plan({ review_state: "approved" }))).toBe(true);
  });

  it("summarizes revision targets and protections", () => {
    expect(revisionPlanSummaryCounts(plan({}))).toEqual({
      requestedChanges: 1,
      dependencies: 1,
      targetedComponents: 1,
      targetedOutputs: 1,
      protectedParameters: 1,
      protectedOutputs: 1,
      successCriteria: 1,
    });
  });

  it("splits compliance findings by blocking state", () => {
    const result: RevisionComplianceResult = {
      passed: false,
      findings: [
        { rule_id: "revision.unauthorized_parameter_change", is_blocking: true, title: "Blocked" },
        { rule_id: "revision.advisory", is_blocking: false, title: "Advisory" },
      ],
    };

    expect(revisionComplianceBuckets(result).blocking.map((entry) => entry.rule_id)).toEqual([
      "revision.unauthorized_parameter_change",
    ]);
    expect(revisionComplianceBuckets(result).advisory.map((entry) => entry.rule_id)).toEqual([
      "revision.advisory",
    ]);
  });

  it("groups success criteria by verification state", () => {
    const buckets = revisionSuccessBuckets([
      success({ verification_state: "success_verified" }),
      success({ verification_state: "success_violated", target_id: "body_width" }),
      success({ verification_state: "success_unverifiable", target_id: "handle_balance" }),
    ]);

    expect(buckets.verified).toHaveLength(1);
    expect(buckets.violated).toHaveLength(1);
    expect(buckets.unverifiable).toHaveLength(1);
  });

  it("counts component-targeted revision preservation states", () => {
    expect(
      componentRevisionCounts({
        summary: {
          targeted_outputs: [{ output_id: "lid", change_state: "changed_as_expected" }],
          protected_outputs: [
            { output_id: "body", preservation_state: "verified_unchanged" },
            { output_id: "handle", preservation_state: "unexpected_change" },
          ],
          interfaces: [
            {
              interface_id: "lid_body",
              parameter_id: "screw_spacing",
              verification_state: "verified",
              is_blocking: false,
            },
            {
              interface_id: "hinge",
              parameter_id: "pin_diameter",
              verification_state: "violated",
              is_blocking: true,
            },
          ],
        },
      }),
    ).toEqual({
      targetedOutputs: 1,
      protectedOutputs: 2,
      unexpectedProtectedChanges: 1,
      verifiedInterfaces: 1,
      violatedInterfaces: 1,
    });
  });
});
