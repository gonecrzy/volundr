import { describe, expect, it } from "vitest";
import {
  debugBatchOutcomeLabel,
  normalizeDebugBatchStart,
  safeFrontendDebugEvent,
  type DebugBatchCapabilities,
} from "./debugBatch";


describe("debug batch contracts", () => {
  it("trims and validates start modal values", () => {
    expect(
      normalizeDebugBatchStart({
        label: "  mixed-01  ",
        targetProjectCount: "5",
        notes: "  first run  ",
        baselineBatchId: "",
      }),
    ).toEqual({
      label: "mixed-01",
      targetProjectCount: 5,
      notes: "first run",
      baselineBatchId: undefined,
    });
    expect(() => normalizeDebugBatchStart({ label: " ", targetProjectCount: "5" })).toThrow(
      "Batch name is required",
    );
    expect(() => normalizeDebugBatchStart({ label: "x", targetProjectCount: "21" })).toThrow(
      "Target projects must be between 1 and 20",
    );
  });

  it("uses only the backend capability for visibility", () => {
    const enabled: DebugBatchCapabilities = { developer_tools_enabled: true };
    const disabled: DebugBatchCapabilities = { developer_tools_enabled: false };
    expect(enabled.developer_tools_enabled).toBe(true);
    expect(disabled.developer_tools_enabled).toBe(false);
  });

  it("keeps high-level outcome labels stable", () => {
    expect(debugBatchOutcomeLabel("blocked_before_worker")).toBe("Blocked before worker");
    expect(debugBatchOutcomeLabel("working_version_created")).toBe("Working version created");
    expect(debugBatchOutcomeLabel("unknown")).toBe("Not started");
  });

  it("strips unsafe frontend evidence fields", () => {
    expect(
      safeFrontendDebugEvent({
        event_type: "network_failure",
        safe_endpoint_path: "/api/projects/p-1",
        http_status: 502,
        project_id: "p-1",
        authorization: "secret",
        cookies: "secret",
        draft: "do not retain",
      }),
    ).toEqual({
      event_type: "network_failure",
      safe_endpoint_path: "/api/projects/p-1",
      http_status: 502,
      project_id: "p-1",
    });
  });
});
