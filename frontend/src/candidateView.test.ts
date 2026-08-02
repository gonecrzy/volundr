import { describe, expect, it } from "vitest";
import {
  acceptDisabledReason,
  canAcceptRevision,
  candidateFindingBuckets,
  candidateFindingRecoveryActions,
  designConsistencyLabel,
  revisionViewerLabel,
  revisionWorkflowLabel,
  sourceCheckFindings,
  sourceCheckSummary,
  geometricFindingBuckets,
  revisionPromptFromGeometricFinding,
  revisionPromptFromCandidateFinding,
  outputDimensionsLabel,
  outputPlacementLabel,
  outputSolidCountLabel,
  outputStateLabel,
  outputTopologyLabel,
  canRetryOutput,
  type GeometricFinding,
  type CandidateFinding,
  type CandidateRevision,
  type ProjectState,
  type RevisionOutput,
} from "./candidateView";

const project: ProjectState = {
  active_revision_id: "active-revision",
};

function revision(overrides: Partial<CandidateRevision>): CandidateRevision {
  return {
    id: "candidate-revision",
    revision_number: 2,
    source_type: "ai_revision",
    status: "succeeded",
    is_accepted: false,
    review_state: "ready",
    validation_summary: {
      blocking_count: 0,
      advisory_count: 0,
      dismissed_count: 0,
    },
    ...overrides,
  };
}

function finding(overrides: Partial<CandidateFinding>): CandidateFinding {
  return {
    id: "finding-1",
    rule_id: "mesh.disconnected_components",
    severity: "warning",
    is_blocking: false,
    title: "Disconnected Components",
    explanation: "The STL contains disconnected components.",
    suggested_correction: "Confirm this separation is desired.",
    finding_state: "open",
    ...overrides,
  };
}

function geometricFinding(overrides: Partial<GeometricFinding>): GeometricFinding {
  return {
    validation_finding_id: null,
    rule_id: "geometry.protected_overall_dimension",
    requirement_id: "part_width",
    verification_state: "verified",
    expected_value: 80,
    detected_value: 80.1,
    unit: "mm",
    tolerance: 0.2,
    confidence: 0.99,
    severity: "notice",
    is_blocking: false,
    title: "Overall width",
    explanation: "Overall width matches.",
    suggested_correction: "No correction is needed.",
    feature_id: null,
    metadata: {},
    ...overrides,
  };
}

function revisionOutput(overrides: Partial<RevisionOutput>): RevisionOutput {
  return {
    id: "output-1",
    revision_id: "candidate-revision",
    output_id: "body",
    component_id: "body",
    component_ids: ["body"],
    execution_state: "ready",
    output_type: "printable_component",
    label: "Body",
    filename: "body.stl",
    quantity: 1,
    required: true,
    entrypoint: "body",
    stl_path: "projects/example/body.stl",
    stl_hash: "hash",
    step_path: "projects/example/body.step",
    step_hash: "step-hash",
    expected_solid_count: 1,
    detected_solid_count: 1,
    allow_disconnected_solids: false,
    compile_log_path: "projects/example/body.log",
    compile_error: null,
    topology_metadata: {
      valid: true,
      expected_solid_count: 1,
      detected_solid_count: 1,
      shell_count: 1,
    },
    metadata: {
      size_x_mm: 80,
      size_y_mm: 50,
      size_z_mm: 6,
      volume_mm3: 24000,
      triangle_count: 12,
      connected_components: 1,
      is_watertight: true,
      is_winding_consistent: true,
      center_of_mass: [40, 25, 3],
    },
    validation_summary: { blocking_count: 0, advisory_count: 0, dismissed_count: 0 },
    ...overrides,
  };
}

describe("candidate view helpers", () => {
  it("labels active, candidate, and historical revisions distinctly", () => {
    expect(revisionViewerLabel(revision({ id: "active-revision", is_accepted: true }), project)).toBe(
      "Current design",
    );
    expect(revisionViewerLabel(revision({ review_state: "ready_with_warnings" }), project)).toBe(
      "New version",
    );
    expect(revisionViewerLabel(revision({ id: "old", is_accepted: true }), project)).toBe(
      "Earlier version",
    );
  });

  it("renders stable candidate state text", () => {
    expect(revisionWorkflowLabel(revision({ review_state: "ready" }))).toBe("Ready to review");
    expect(revisionWorkflowLabel(revision({ review_state: "ready_with_warnings" }))).toBe(
      "Ready with warnings",
    );
    expect(revisionWorkflowLabel(revision({ review_state: "blocked" }))).toBe("Needs changes");
  });

  it("enables acceptance only for ready candidates without blocking findings", () => {
    expect(canAcceptRevision(revision({ review_state: "ready" }))).toBe(true);
    expect(canAcceptRevision(revision({ review_state: "ready_with_warnings" }))).toBe(true);
    expect(
      canAcceptRevision(
        revision({
          review_state: "blocked",
          validation_summary: { blocking_count: 1, advisory_count: 0, dismissed_count: 0 },
        }),
      ),
    ).toBe(false);
    expect(
      canAcceptRevision(
        revision({
          design_consistency: {
            status: "blocked",
            pre_execution_passed: false,
            post_execution_passed: false,
            revision_base_ready: false,
            configuration_ready: false,
            blocking_count: 1,
            advisory_count: 0,
            findings: [
              {
                rule_id: "design_artifact.output_missing",
                explanation: "planned output `body` has no matching CadQuery PrintableOutput",
                is_blocking: true,
              },
            ],
          },
        }),
      ),
    ).toBe(false);
  });

  it("explains disabled acceptance for blocked candidates", () => {
    expect(
      acceptDisabledReason(
        revision({
          review_state: "blocked",
          validation_summary: { blocking_count: 2, advisory_count: 1, dismissed_count: 0 },
        }),
      ),
    ).toBe("Resolve 2 blocking findings with a new revision before accepting.");
    expect(
      acceptDisabledReason(
        revision({
          design_consistency: {
            status: "blocked",
            pre_execution_passed: false,
            post_execution_passed: false,
            revision_base_ready: false,
            configuration_ready: false,
            blocking_count: 1,
            advisory_count: 0,
            findings: [],
          },
        }),
      ),
    ).toBe("Resolve 1 internal design mismatch before accepting.");
  });

  it("labels design consistency state", () => {
    expect(
      designConsistencyLabel(
        revision({
          design_consistency: {
            status: "passed",
            pre_execution_passed: true,
            post_execution_passed: true,
            revision_base_ready: true,
            configuration_ready: true,
            blocking_count: 0,
            advisory_count: 0,
            findings: [],
          },
        }),
      ),
    ).toBe("Passed");
    expect(
      designConsistencyLabel(
        revision({
          design_consistency: {
            status: "blocked",
            pre_execution_passed: false,
            post_execution_passed: false,
            revision_base_ready: false,
            configuration_ready: false,
            blocking_count: 3,
            advisory_count: 0,
            findings: [],
          },
        }),
      ),
    ).toBe("Blocked - 3 internal mismatches");
  });

  it("splits blocking and advisory findings for display", () => {
    const buckets = candidateFindingBuckets([
      finding({ id: "blocking", is_blocking: true, severity: "critical" }),
      finding({ id: "advisory", is_blocking: false, severity: "warning" }),
    ]);

    expect(buckets.blocking.map((entry) => entry.id)).toEqual(["blocking"]);
    expect(buckets.advisory.map((entry) => entry.id)).toEqual(["advisory"]);
  });

  it("extracts source-contract findings for source check display", () => {
    const findings = [
      finding({ id: "mesh", category: "mesh", rule_id: "mesh.empty_or_zero_volume" }),
      finding({ id: "source", category: "source_structure", rule_id: "cadquery.contract" }),
      finding({
        id: "spec",
        category: "specification_compliance",
        rule_id: "specification_compliance.protected_value_mismatch",
      }),
    ];

    expect(sourceCheckFindings(findings).map((entry) => entry.id)).toEqual(["source", "spec"]);
  });

  it("summarizes blocking source checks separately from quality findings", () => {
    const summary = sourceCheckSummary([
      finding({
        id: "quality",
        category: "source_parameterization",
        rule_id: "source_parameterization.missing_assertions",
      }),
      finding({
        id: "mismatch",
        category: "specification_compliance",
        is_blocking: true,
        rule_id: "specification_compliance.protected_value_mismatch",
        severity: "critical",
      }),
    ]);

    expect(summary.blocking.map((entry) => entry.id)).toEqual(["mismatch"]);
    expect(summary.advisory.map((entry) => entry.id)).toEqual(["quality"]);
    expect(summary.passedProtectedDimensions).toBe(false);
  });

  it("groups geometric findings by verification state", () => {
    const buckets = geometricFindingBuckets([
      geometricFinding({ rule_id: "geometry.protected_overall_dimension" }),
      geometricFinding({ verification_state: "violated", rule_id: "geometry.protected_hole_spacing" }),
      geometricFinding({ verification_state: "unverifiable", rule_id: "geometry.protected_wall_thickness" }),
    ]);

    expect(buckets.verified).toHaveLength(1);
    expect(buckets.violated).toHaveLength(1);
    expect(buckets.unverifiable).toHaveLength(1);
  });

  it("builds revision prompt context from linked geometric finding", () => {
    const prompt = revisionPromptFromGeometricFinding(
      geometricFinding({
        validation_finding_id: "finding-123",
        rule_id: "geometry.protected_hole_spacing",
        expected_value: 50,
        detected_value: 60,
        tolerance: 0.25,
        confidence: 0.96,
      }),
    );

    expect(prompt).toContain("finding-123");
    expect(prompt).toContain("geometry.protected_hole_spacing");
    expect(prompt).toContain("expected 50");
    expect(prompt).toContain("detected 60");
  });

  it("builds revision prompt context from candidate blocker", () => {
    const prompt = revisionPromptFromCandidateFinding(
      finding({
        id: "blocker-1",
        rule_id: "mesh.disconnected_components",
        is_blocking: true,
        severity: "critical",
        title: "Disconnected components",
        explanation: "The handle is a loose component.",
        suggested_correction: "Join the handle to the body or make it a declared separate output.",
        detected_value: "2",
      }),
    );

    expect(prompt).toContain("blocker-1");
    expect(prompt).toContain("mesh.disconnected_components");
    expect(prompt).toContain("The handle is a loose component.");
    expect(prompt).toContain("Join the handle to the body");
    expect(prompt).toContain("Preserve unrelated");
  });

  it("offers profile and revision recovery for build-volume blockers", () => {
    const actions = candidateFindingRecoveryActions(
      finding({
        id: "volume-1",
        category: "profile",
        rule_id: "profile.build_volume",
        is_blocking: true,
        severity: "critical",
      }),
    );

    expect(actions.map((action) => action.kind)).toEqual(["profile", "revise"]);
    expect(actions[0].label).toBe("Review printer profile");
    expect(actions[1].label).toBe("Revise model");
  });

  it("offers targeted revision for mesh and geometry blockers", () => {
    expect(
      candidateFindingRecoveryActions(
        finding({
          category: "mesh",
          rule_id: "mesh.disconnected_components",
          is_blocking: true,
          severity: "critical",
        }),
      ).map((action) => action.kind),
    ).toEqual(["revise"]);
    expect(
      candidateFindingRecoveryActions(
        finding({
          category: "geometry",
          rule_id: "geometry.build_plate_min_z",
          is_blocking: true,
          severity: "critical",
        }),
      ).map((action) => action.kind),
    ).toEqual(["revise"]);
  });

  it("does not offer recovery actions for advisory findings", () => {
    expect(candidateFindingRecoveryActions(finding({ is_blocking: false }))).toEqual([]);
  });

  it("labels output states and dimensions", () => {
    expect(outputStateLabel(revisionOutput({ execution_state: "ready_with_warnings" }))).toBe(
      "Ready with warnings",
    );
    expect(outputStateLabel(revisionOutput({ execution_state: "blocked" }))).toBe("Blocked");
    expect(outputDimensionsLabel(revisionOutput({}))).toBe("80 x 50 x 6 mm");
    expect(outputDimensionsLabel(revisionOutput({ metadata: null }))).toBe("Dimensions unavailable");
  });

  it("labels output topology and solid-count checks", () => {
    expect(outputTopologyLabel(revisionOutput({}))).toBe("Topology valid");
    expect(outputSolidCountLabel(revisionOutput({}))).toBe("Solids 1/1");
    expect(
      outputTopologyLabel(
        revisionOutput({
          topology_metadata: { valid: false, failure_reason: "solid_count_mismatch" },
        }),
      ),
    ).toBe("Topology failed: solid count mismatch");
    expect(
      outputSolidCountLabel(
        revisionOutput({
          expected_solid_count: null,
          detected_solid_count: null,
          topology_metadata: null,
        }),
      ),
    ).toBe("Solid count unavailable");
  });

  it("labels output print placement without exposing raw transforms", () => {
    expect(outputPlacementLabel(revisionOutput({ topology_metadata: null }))).toBe("Placement not reported");
    expect(
      outputPlacementLabel(
        revisionOutput({
          topology_metadata: {
            valid: true,
            placement_policy: "cadquery-output-placement-v1",
            print_transform: { translation: [0, 0, 0], rotation: [0, 0, 0] },
          },
        }),
      ),
    ).toBe("Placed on build plate");
    expect(
      outputPlacementLabel(
        revisionOutput({
          topology_metadata: {
            valid: true,
            placement_policy: "cadquery-output-placement-v1",
            print_transform: { translation: [0, 0, 2], rotation: [0, 0, 0] },
          },
        }),
      ),
    ).toBe("Raised 2 mm to build plate");
  });

  it("shows retry only for failed outputs", () => {
    expect(canRetryOutput(revisionOutput({ execution_state: "failed" }))).toBe(true);
    expect(canRetryOutput(revisionOutput({ execution_state: "blocked" }))).toBe(false);
    expect(canRetryOutput(revisionOutput({ execution_state: "ready" }))).toBe(false);
  });
});
