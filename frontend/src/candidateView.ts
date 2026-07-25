export type ReviewState = "ready" | "ready_with_warnings" | "blocked" | "rejected" | "accepted";

export type ProjectState = {
  active_revision_id: string | null;
};

export type ValidationSummary = {
  blocking_count: number;
  advisory_count: number;
  dismissed_count: number;
};

export type CandidateRevision = {
  id: string;
  revision_number: number;
  source_type: string;
  status: string;
  is_accepted: boolean;
  review_state: ReviewState | null;
  validation_summary: ValidationSummary;
};

export type CandidateFinding = {
  id: string;
  rule_id: string;
  severity: "notice" | "warning" | "critical";
  is_blocking: boolean;
  title: string;
  explanation: string;
  suggested_correction: string;
  finding_state: string;
};

export function revisionViewerLabel(
  revision: CandidateRevision | null,
  project: ProjectState | null,
): string {
  if (!revision) {
    return "Draft workspace";
  }
  if (project?.active_revision_id === revision.id) {
    return "Active design";
  }
  if (revision.is_accepted || revision.review_state === "accepted" || revision.review_state === "rejected") {
    return "Historical revision";
  }
  if (revision.review_state && ["ready", "ready_with_warnings", "blocked"].includes(revision.review_state)) {
    return "Candidate";
  }
  return "Historical revision";
}

export function revisionWorkflowLabel(revision: CandidateRevision | null): string {
  if (!revision) {
    return "Draft workspace";
  }
  switch (revision.review_state) {
    case "ready":
      return "Ready candidate";
    case "ready_with_warnings":
      return "Ready with warnings";
    case "blocked":
      return "Blocked candidate";
    case "rejected":
      return "Rejected candidate";
    case "accepted":
      return "Accepted revision";
    default:
      return revision.status;
  }
}

export function canAcceptRevision(revision: CandidateRevision | null): boolean {
  if (!revision) {
    return false;
  }
  return (
    (revision.review_state === "ready" || revision.review_state === "ready_with_warnings") &&
    revision.validation_summary.blocking_count === 0
  );
}

export function acceptDisabledReason(revision: CandidateRevision | null): string | null {
  if (!revision) {
    return "Select a candidate before accepting.";
  }
  if (revision.validation_summary.blocking_count > 0) {
    const count = revision.validation_summary.blocking_count;
    return `Resolve ${count} blocking ${count === 1 ? "finding" : "findings"} with a new revision before accepting.`;
  }
  if (revision.review_state === "accepted") {
    return "This revision is already accepted.";
  }
  if (revision.review_state === "rejected") {
    return "Rejected candidates cannot be accepted.";
  }
  if (revision.review_state !== "ready" && revision.review_state !== "ready_with_warnings") {
    return "Only ready candidates can be accepted.";
  }
  return null;
}

export function candidateFindingBuckets(findings: CandidateFinding[]): {
  blocking: CandidateFinding[];
  advisory: CandidateFinding[];
} {
  return {
    blocking: findings.filter((finding) => finding.is_blocking),
    advisory: findings.filter((finding) => !finding.is_blocking),
  };
}
