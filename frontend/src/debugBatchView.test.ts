import { describe, expect, it } from "vitest";
import { debugBatchBannerText, debugBatchComparisonLabel } from "./debugBatchView";
import type { DebugBatch } from "./debugBatch";


const batch: DebugBatch = {
  id: "batch-1",
  label: "mixed-01",
  notes: null,
  target_project_count: 5,
  baseline_batch_id: null,
  state: "active",
  git_head: "abcdef123456",
  branch: "main",
  migration_head: "0028_debug_batches",
  application_version: "app",
  frontend_build_identity: "front",
  backend_build_identity: "back",
  worker_build_identity: "worker",
  build_identities: {},
  identity_complete: false,
  provider: "gemini_api",
  configured_default_model: "gemini-3.5-flash-lite",
  stage_model_policy: {},
  actual_provider_models: {},
  prompt_versions: {},
  configuration_hash: "hash",
  started_at: "2026-08-03T00:00:00Z",
  finished_at: null,
  report_path: null,
  report_generation_state: "not_started",
  evidence_contract_version: "debug-batch-v1",
  comparison_status: "not_applicable",
  redaction_status: "pending",
  integrity_status: "pending",
  memberships: [],
};


describe("debug batch view presentation", () => {
  it("shows active project progress without obscuring the target", () => {
    expect(debugBatchBannerText(batch)).toBe("Debug batch: mixed-01    0 of 5 projects");
  });

  it("distinguishes controlled comparisons", () => {
    expect(debugBatchComparisonLabel("controlled")).toBe("Controlled comparison");
    expect(debugBatchComparisonLabel("uncontrolled")).toBe("Uncontrolled comparison");
    expect(debugBatchComparisonLabel("configuration_mismatch")).toContain("configuration mismatch");
    expect(debugBatchComparisonLabel("identity_incomplete")).toContain("identity incomplete");
  });
});
