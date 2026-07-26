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

export type RevisionOutputState =
  | "queued"
  | "compiling"
  | "compiled"
  | "validating"
  | "ready"
  | "ready_with_warnings"
  | "blocked"
  | "failed"
  | "skipped";

export type RevisionOutput = {
  id: string;
  revision_id: string;
  output_id: string;
  component_id: string | null;
  component_ids: string[];
  output_state: RevisionOutputState;
  output_type: string;
  label: string;
  filename: string;
  quantity: number;
  required: boolean;
  module_name: string;
  stl_path: string | null;
  stl_hash: string | null;
  compile_log_path: string | null;
  compile_error: string | null;
  metadata: {
    size_x_mm: number;
    size_y_mm: number;
    size_z_mm: number;
    volume_mm3: number;
    triangle_count: number;
    connected_components: number;
    is_watertight: boolean;
    is_winding_consistent: boolean;
    center_of_mass: [number, number, number];
  } | null;
  validation_summary: ValidationSummary;
};

export type CandidateFinding = {
  id: string;
  rule_id: string;
  category?: string;
  severity: "notice" | "warning" | "critical";
  is_blocking: boolean;
  title: string;
  explanation: string;
  suggested_correction: string;
  detected_value?: string | null;
  threshold_value?: string | null;
  source_line_start?: number | null;
  finding_state: string;
};

export type CandidateFindingRecoveryActionKind = "profile" | "revise";

export type CandidateFindingRecoveryAction = {
  kind: CandidateFindingRecoveryActionKind;
  label: string;
  description: string;
};

export type GeometricVerificationState =
  | "verified"
  | "violated"
  | "unverifiable"
  | "not_applicable";

export type GeometricFinding = {
  validation_finding_id: string | null;
  rule_id: string;
  requirement_id: string | null;
  verification_state: GeometricVerificationState;
  expected_value: number | string | null;
  detected_value: number | string | null;
  unit: string | null;
  tolerance: number | null;
  confidence: number;
  severity: "notice" | "warning" | "critical";
  is_blocking: boolean;
  title: string;
  explanation: string;
  suggested_correction: string;
  feature_id: string | null;
  metadata: Record<string, unknown>;
};

export type GeometricAnalysis = {
  id: string;
  revision_id: string;
  design_specification_id: string | null;
  analysis_version: string;
  tolerance_profile_version: string;
  mesh_hash: string;
  source_hash: string | null;
  analysis_ms: number;
  created_at: string;
  findings: GeometricFinding[];
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

export function outputStateLabel(output: RevisionOutput): string {
  switch (output.output_state) {
    case "ready":
      return "Ready";
    case "ready_with_warnings":
      return "Ready with warnings";
    case "blocked":
      return "Blocked";
    case "failed":
      return "Failed";
    case "validating":
      return "Validating";
    case "compiling":
      return "Compiling";
    case "queued":
      return "Queued";
    case "skipped":
      return "Skipped";
    default:
      return output.output_state;
  }
}

export function outputDimensionsLabel(output: RevisionOutput): string {
  if (!output.metadata) {
    return "Dimensions unavailable";
  }
  const { size_x_mm, size_y_mm, size_z_mm } = output.metadata;
  return `${formatDimension(size_x_mm)} x ${formatDimension(size_y_mm)} x ${formatDimension(size_z_mm)} mm`;
}

export function canRetryOutput(output: RevisionOutput): boolean {
  return output.output_state === "failed";
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

export function sourceCheckFindings(findings: CandidateFinding[]): CandidateFinding[] {
  return findings.filter((finding) => {
    const category = finding.category ?? finding.rule_id.split(".", 1)[0];
    return category.startsWith("source_") || category === "specification_compliance";
  });
}

export function sourceCheckSummary(findings: CandidateFinding[]): {
  blocking: CandidateFinding[];
  advisory: CandidateFinding[];
  passedRequiredStructure: boolean;
  passedProtectedDimensions: boolean;
} {
  const sourceFindings = sourceCheckFindings(findings);
  const blocking = sourceFindings.filter((finding) => finding.is_blocking);
  const advisory = sourceFindings.filter((finding) => !finding.is_blocking);
  return {
    blocking,
    advisory,
    passedRequiredStructure: !blocking.some((finding) => finding.category === "source_structure"),
    passedProtectedDimensions: !blocking.some(
      (finding) => finding.category === "specification_compliance",
    ),
  };
}

export function geometricFindingBuckets(findings: GeometricFinding[]): {
  verified: GeometricFinding[];
  violated: GeometricFinding[];
  unverifiable: GeometricFinding[];
  notApplicable: GeometricFinding[];
} {
  return {
    verified: findings.filter((finding) => finding.verification_state === "verified"),
    violated: findings.filter((finding) => finding.verification_state === "violated"),
    unverifiable: findings.filter((finding) => finding.verification_state === "unverifiable"),
    notApplicable: findings.filter((finding) => finding.verification_state === "not_applicable"),
  };
}

export function revisionPromptFromGeometricFinding(finding: GeometricFinding): string {
  const expected = formatMaybeValue(finding.expected_value, finding.unit);
  const detected = formatMaybeValue(finding.detected_value, finding.unit);
  const tolerance =
    finding.tolerance === null || finding.tolerance === undefined
      ? "unspecified tolerance"
      : `tolerance ${finding.tolerance}${finding.unit ? ` ${finding.unit}` : ""}`;
  const findingReference = finding.validation_finding_id
    ? `validation finding ${finding.validation_finding_id}`
    : `rule ${finding.rule_id}`;
  return [
    `Revise the candidate to resolve ${findingReference}.`,
    `Rule: ${finding.rule_id}.`,
    finding.requirement_id ? `Requirement: ${finding.requirement_id}.` : null,
    finding.feature_id ? `Feature: ${finding.feature_id}.` : null,
    `expected ${expected}; detected ${detected}; ${tolerance}; confidence ${finding.confidence}.`,
    finding.explanation,
    finding.suggested_correction,
    "Preserve unrelated protected requirements, dimensions, markers, modules, and accepted design intent.",
  ]
    .filter((line): line is string => Boolean(line))
    .join("\n");
}

export function revisionPromptFromCandidateFinding(finding: CandidateFinding): string {
  return [
    `Revise the current candidate to resolve validation finding ${finding.id}.`,
    `Rule: ${finding.rule_id}.`,
    `Title: ${finding.title}.`,
    finding.explanation,
    finding.detected_value ? `Detected: ${finding.detected_value}.` : null,
    finding.threshold_value ? `Expected or threshold: ${finding.threshold_value}.` : null,
    finding.suggested_correction,
    "Preserve unrelated protected requirements, dimensions, markers, modules, outputs, and accepted design intent.",
  ]
    .filter((line): line is string => Boolean(line))
    .join("\n");
}

export function candidateFindingRecoveryActions(
  finding: CandidateFinding,
): CandidateFindingRecoveryAction[] {
  if (!finding.is_blocking) {
    return [];
  }
  const actions: CandidateFindingRecoveryAction[] = [];
  if (finding.rule_id === "profile.build_volume" || finding.category === "profile") {
    actions.push({
      kind: "profile",
      label: "Review printer profile",
      description: "Check whether the selected printer build volume is correct before redesigning.",
    });
  }
  actions.push({
    kind: "revise",
    label: "Revise model",
    description: "Create a scoped revision prompt from this blocking finding.",
  });
  return actions;
}

function formatMaybeValue(value: number | string | null, unit: string | null): string {
  if (value === null || value === undefined || value === "") {
    return "unverified";
  }
  return `${value}${unit ? ` ${unit}` : ""}`;
}

function formatDimension(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}
