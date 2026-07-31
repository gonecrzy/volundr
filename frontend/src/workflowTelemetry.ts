export type WorkflowCorrelation = {
  workflowRunId?: string | null;
  correlationId?: string | null;
};

export type FrontendWorkflowEventName =
  | "project_created"
  | "request_started"
  | "request_submitted"
  | "clarification_displayed"
  | "clarification_answered"
  | "requirements_review_viewed"
  | "proposed_design_viewed"
  | "proposal_edited"
  | "design_review_opened"
  | "design_approved"
  | "generation_started"
  | "progress_stage_shown"
  | "candidate_opened"
  | "output_selected"
  | "warning_expanded"
  | "configuration_opened"
  | "configuration_previewed"
  | "configuration_submitted"
  | "revision_opened"
  | "revision_requested"
  | "revision_plan_approved"
  | "candidate_accepted"
  | "candidate_rejected"
  | "export_requested"
  | "visible_error_displayed"
  | "failure_recovery_selected"
  | "diagnostic_bundle_requested";

export type FrontendWorkflowEventPayload = {
  action_name: FrontendWorkflowEventName;
  route: string;
  user_visible_state: string;
  timestamp: string;
  backend_request_id?: string | null;
  metadata: Record<string, string | number | boolean | null>;
};

const registeredEvents = new Set<string>([
  "project_created",
  "request_started",
  "request_submitted",
  "clarification_displayed",
  "clarification_answered",
  "requirements_review_viewed",
  "proposed_design_viewed",
  "proposal_edited",
  "design_review_opened",
  "design_approved",
  "generation_started",
  "progress_stage_shown",
  "candidate_opened",
  "output_selected",
  "warning_expanded",
  "configuration_opened",
  "configuration_previewed",
  "configuration_submitted",
  "revision_opened",
  "revision_requested",
  "revision_plan_approved",
  "candidate_accepted",
  "candidate_rejected",
  "export_requested",
  "visible_error_displayed",
  "failure_recovery_selected",
  "diagnostic_bundle_requested",
]);

export function buildCorrelatedHeaders(
  headers: HeadersInit | undefined,
  correlation: WorkflowCorrelation,
): Record<string, string> {
  const result: Record<string, string> = {};
  if (headers instanceof Headers || Array.isArray(headers)) {
    new Headers(headers).forEach((value, key) => {
      result[key] = value;
    });
  } else if (headers) {
    Object.assign(result, headers);
  }
  if (correlation.workflowRunId) {
    result["X-Workflow-Run-Id"] = correlation.workflowRunId;
  }
  if (correlation.correlationId) {
    result["X-Workflow-Correlation-Id"] = correlation.correlationId;
  }
  return result;
}

export function isRegisteredFrontendWorkflowEvent(value: string): value is FrontendWorkflowEventName {
  return registeredEvents.has(value);
}

export function createFrontendWorkflowEvent(input: {
  actionName: FrontendWorkflowEventName;
  route: string;
  userVisibleState: string;
  backendRequestId?: string | null;
  metadata?: Record<string, unknown>;
}): FrontendWorkflowEventPayload {
  return {
    action_name: input.actionName,
    route: input.route,
    user_visible_state: input.userVisibleState,
    timestamp: new Date().toISOString(),
    backend_request_id: input.backendRequestId ?? null,
    metadata: sanitizeMetadata(input.metadata ?? {}),
  };
}

function sanitizeMetadata(metadata: Record<string, unknown>): Record<string, string | number | boolean | null> {
  return Object.fromEntries(
    Object.entries(metadata)
      .filter((entry): entry is [string, string | number | boolean | null] => {
        const value = entry[1];
        return (
          typeof value === "string" ||
          typeof value === "number" ||
          typeof value === "boolean" ||
          value === null
        );
      })
      .slice(0, 20),
  );
}
