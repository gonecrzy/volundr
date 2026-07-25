import { describe, expect, it } from "vitest";
import {
  acceptDisabledReason,
  canAcceptRevision,
  candidateFindingBuckets,
  revisionViewerLabel,
  revisionWorkflowLabel,
  sourceCheckFindings,
  sourceCheckSummary,
  type CandidateFinding,
  type CandidateRevision,
  type ProjectState,
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

describe("candidate view helpers", () => {
  it("labels active, candidate, and historical revisions distinctly", () => {
    expect(revisionViewerLabel(revision({ id: "active-revision", is_accepted: true }), project)).toBe(
      "Active design",
    );
    expect(revisionViewerLabel(revision({ review_state: "ready_with_warnings" }), project)).toBe(
      "Candidate",
    );
    expect(revisionViewerLabel(revision({ id: "old", is_accepted: true }), project)).toBe(
      "Historical revision",
    );
  });

  it("renders stable candidate state text", () => {
    expect(revisionWorkflowLabel(revision({ review_state: "ready" }))).toBe("Ready candidate");
    expect(revisionWorkflowLabel(revision({ review_state: "ready_with_warnings" }))).toBe(
      "Ready with warnings",
    );
    expect(revisionWorkflowLabel(revision({ review_state: "blocked" }))).toBe("Blocked candidate");
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
      finding({ id: "source", category: "source_structure", rule_id: "source_structure.missing_main_model_module" }),
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
});
