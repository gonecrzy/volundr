import { describe, expect, it } from "vitest";
import {
  buildCorrelatedHeaders,
  createFrontendWorkflowEvent,
  isRegisteredFrontendWorkflowEvent,
} from "./workflowTelemetry";

describe("workflow telemetry helpers", () => {
  it("adds correlation and workflow IDs when available", () => {
    expect(
      buildCorrelatedHeaders(
        { "Content-Type": "application/json" },
        { workflowRunId: "workflow-1", correlationId: "correlation-1" },
      ),
    ).toEqual({
      "Content-Type": "application/json",
      "X-Workflow-Run-Id": "workflow-1",
      "X-Workflow-Correlation-Id": "correlation-1",
    });
  });

  it("rejects unknown frontend workflow event names", () => {
    expect(isRegisteredFrontendWorkflowEvent("candidate_accepted")).toBe(true);
    expect(isRegisteredFrontendWorkflowEvent("progress_stage_shown")).toBe(true);
    expect(isRegisteredFrontendWorkflowEvent("failure_recovery_selected")).toBe(true);
    expect(isRegisteredFrontendWorkflowEvent("keyboard_input")).toBe(false);
  });

  it("creates typed frontend events without arbitrary text capture", () => {
    const event = createFrontendWorkflowEvent({
      actionName: "candidate_accepted",
      route: "/",
      userVisibleState: "candidate_review",
      backendRequestId: "request-1",
      metadata: {
        revision_id: "revision-1",
        unsupported: { nested: "object" },
      },
    });

    expect(event.action_name).toBe("candidate_accepted");
    expect(event.metadata).toEqual({ revision_id: "revision-1" });
    expect(event.backend_request_id).toBe("request-1");
  });
});
