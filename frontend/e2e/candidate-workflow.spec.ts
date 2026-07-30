import { expect, test } from "@playwright/test";

type Revision = {
  id: string;
  parent_revision_id: string | null;
  design_specification_id: string | null;
  design_plan_id: string | null;
  revision_number: number;
  source_type: string;
  status: string;
  is_accepted: boolean;
  review_state: string | null;
  accepted_at: string | null;
  rejected_at: string | null;
  user_instruction: string | null;
  cad_backend: string;
  source_language: string;
  stl_path: string | null;
  ai_output_path: string | null;
  output_manifest_path: string | null;
  expected_output_count: number | null;
  required_output_count: number | null;
  successful_output_count: number | null;
  blocked_output_count: number | null;
  failed_output_count: number | null;
  created_at: string;
  metadata: {
    size_x_mm: number;
    size_y_mm: number;
    size_z_mm: number;
    volume_mm3: number;
    triangle_count: number;
    connected_components: number;
    is_watertight: boolean;
  } | null;
  error_message: string | null;
  validation_summary: {
    blocking_count: number;
    advisory_count: number;
    dismissed_count: number;
  };
};

const source = `
import cadquery as cq
from volundr_cad.runtime import ParameterSpec, PrintableOutput, Product

PARAMETERS = [
    ParameterSpec(id="body_width", label="Body width", type="float", default=80.0, unit="mm"),
    ParameterSpec(id="lid_thickness", label="Lid thickness", type="float", default=4.0, unit="mm"),
]

def build(params):
    body = cq.Workplane("XY").box(params["body_width"], 50, 24)
    lid = cq.Workplane("XY").box(params["body_width"], 50, params["lid_thickness"])
    return Product(parameters=PARAMETERS, outputs=[
        PrintableOutput(output_id="body", label="Body", component_id="body", model=body),
        PrintableOutput(output_id="lid", label="Lid", component_id="lid", model=lid),
    ])
`;

test("structured revision planning preserves active revision until scoped candidate is accepted", async ({ page }) => {
  const project = {
    id: "project-1",
    name: "Revision Workflow",
    original_intent: "Create a configurable enclosure.",
    status: "active",
    active_revision_id: "rev-active",
  };
  const revisions: Revision[] = [
    revision({
      id: "rev-active",
      revision_number: 1,
      source_type: "ai_initial",
      is_accepted: true,
      review_state: "accepted",
      design_specification_id: "spec-1",
      design_plan_id: "plan-1",
      output_manifest_path: "projects/project-1/revisions/rev-active/output-manifest.json",
      expected_output_count: 2,
      required_output_count: 2,
      successful_output_count: 2,
    }),
  ];
  const outputsByRevision = new Map<string, ReturnType<typeof revisionOutput>[]>([
    [
      "rev-active",
      [
        revisionOutput({ id: "active-body", revision_id: "rev-active", output_id: "body", label: "Body" }),
        revisionOutput({ id: "active-lid", revision_id: "rev-active", output_id: "lid", label: "Lid" }),
      ],
    ],
  ]);
  let currentRevisionPlan: ReturnType<typeof revisionPlan> | null = null;
  let planCount = 0;
  let generateRevisionCount = 0;

  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace(/^\/api/, "");

    if (request.method() === "GET" && path === "/projects") {
      return route.fulfill({ json: [project] });
    }
    if (request.method() === "GET" && path === "/printability-profiles") {
      return route.fulfill({ json: [] });
    }
    if (request.method() === "GET" && path === "/projects/project-1/messages") {
      return route.fulfill({ json: [] });
    }
    if (request.method() === "GET" && path === "/projects/project-1/design-specification") {
      return route.fulfill({ status: 404, json: { detail: "not found" } });
    }
    if (request.method() === "GET" && path === "/projects/project-1/design-plan") {
      return route.fulfill({ status: 404, json: { detail: "not found" } });
    }
    if (request.method() === "GET" && path === "/projects/project-1/revision-plan") {
      if (!currentRevisionPlan) {
        return route.fulfill({ status: 404, json: { detail: "not found" } });
      }
      return route.fulfill({ json: currentRevisionPlan });
    }
    if (request.method() === "GET" && path === "/projects/project-1/revisions") {
      return route.fulfill({ json: revisions });
    }
    if (request.method() === "GET" && /^\/revisions\/[^/]+\/outputs$/.test(path)) {
      const revisionId = path.split("/")[2];
      return route.fulfill({ json: outputsByRevision.get(revisionId) ?? [] });
    }
    if (request.method() === "GET" && /^\/revisions\/[^/]+\/output-manifest$/.test(path)) {
      const revisionId = path.split("/")[2];
      return route.fulfill({
        json: {
          schema_version: "output-manifest-v1",
          project_id: "project-1",
          revision_id: revisionId,
          design_plan_id: "plan-1",
          source: { filename: "source.py", sha256: "source-hash" },
          outputs: outputsByRevision.get(revisionId) ?? [],
        },
      });
    }
    if (request.method() === "GET" && /^\/revisions\/[^/]+\/export\.zip$/.test(path)) {
      return route.fulfill({ body: "PK", contentType: "application/zip" });
    }
    if (request.method() === "GET" && path.endsWith("/source")) {
      return route.fulfill({ body: source, contentType: "text/plain" });
    }
    if (request.method() === "GET" && path.endsWith("/compile-log")) {
      return route.fulfill({ body: "Compilation finished", contentType: "text/plain" });
    }
    if (request.method() === "GET" && path.endsWith("/diff")) {
      return route.fulfill({ status: 404, json: { detail: "not found" } });
    }
    if (request.method() === "GET" && path.endsWith("/stl")) {
      return route.fulfill({ body: "solid empty\nendsolid empty\n", contentType: "model/stl" });
    }
    if (request.method() === "GET" && /^\/revision-outputs\/[^/]+\/compile-log$/.test(path)) {
      return route.fulfill({ body: "Output compilation finished", contentType: "text/plain" });
    }
    if (request.method() === "POST" && path === "/projects/project-1/revision-plans") {
      planCount += 1;
      currentRevisionPlan = revisionPlan({
        id: `revision-plan-${planCount}`,
        user_instruction: planCount === 1 ? "Make the lid 4 mm thick" : "Make the body width 90 mm",
        revision_plan:
          planCount === 1
            ? {
                ...revisionPlanPayload(),
                summary: "Increase lid thickness from 3 mm to 4 mm",
              }
            : {
                ...revisionPlanPayload(),
                summary: "Resize body width, but source later violates protected scope",
                allowed_parameter_changes: ["body_width"],
                protected_parameters: [{ parameter_id: "lid_thickness", expected_value: 4, unit: "mm" }],
                success_criteria: [{ type: "parameter_value", target_id: "body_width", expected_value: 90, unit: "mm" }],
              },
      });
      return route.fulfill({ status: 201, json: currentRevisionPlan });
    }
    if (request.method() === "POST" && /^\/revision-plans\/[^/]+\/approve$/.test(path)) {
      currentRevisionPlan = { ...currentRevisionPlan!, review_state: "approved", approved_at: "2026-07-25T13:10:00Z" };
      return route.fulfill({ json: currentRevisionPlan });
    }
    if (request.method() === "POST" && /^\/revision-plans\/[^/]+\/reject$/.test(path)) {
      currentRevisionPlan = { ...currentRevisionPlan!, review_state: "rejected", rejected_at: "2026-07-25T13:12:00Z" };
      return route.fulfill({ json: currentRevisionPlan });
    }
    if (request.method() === "GET" && /^\/revision-plans\/[^/]+$/.test(path)) {
      return route.fulfill({ json: currentRevisionPlan });
    }
    if (request.method() === "GET" && /^\/revision-plans\/[^/]+\/compliance-result$/.test(path)) {
      if (currentRevisionPlan?.generated_revision_id || generateRevisionCount > 1) {
        return route.fulfill({
          json:
            generateRevisionCount > 1
              ? complianceResult(false)
              : complianceResult(true),
        });
      }
      return route.fulfill({ status: 404, json: { detail: "not found" } });
    }
    if (request.method() === "GET" && /^\/revision-plans\/[^/]+\/success-results$/.test(path)) {
      if (!currentRevisionPlan?.generated_revision_id) {
        return route.fulfill({ status: 404, json: { detail: "not found" } });
      }
      return route.fulfill({ json: [successResult()] });
    }
    if (request.method() === "POST" && /^\/revision-plans\/[^/]+\/generate$/.test(path)) {
      generateRevisionCount += 1;
      if (generateRevisionCount === 2) {
        return route.fulfill({
          status: 409,
          json: {
            detail:
              "Revision source rejected before compile\n- Unauthorized parameter change: lid_thickness expected 4 mm, detected 5 mm",
          },
        });
      }

      const next = revision({
        id: "rev-scoped",
        parent_revision_id: "rev-active",
        design_specification_id: "spec-1",
        design_plan_id: "plan-1",
        revision_number: 2,
        source_type: "ai_revision",
        review_state: "ready_with_warnings",
        validation_summary: { blocking_count: 0, advisory_count: 1, dismissed_count: 0 },
        output_manifest_path: "projects/project-1/revisions/rev-scoped/output-manifest.json",
        expected_output_count: 2,
        required_output_count: 2,
        successful_output_count: 2,
      });
      revisions.push(next);
      outputsByRevision.set("rev-scoped", [
        revisionOutput({ id: "scoped-body", revision_id: "rev-scoped", output_id: "body", label: "Body" }),
        revisionOutput({
          id: "scoped-lid",
          revision_id: "rev-scoped",
          output_id: "lid",
          label: "Lid",
          metadata: {
            size_x_mm: 80,
            size_y_mm: 50,
            size_z_mm: 4,
            volume_mm3: 16000,
            triangle_count: 12,
            connected_components: 1,
            is_watertight: true,
            is_winding_consistent: true,
            center_of_mass: [40, 25, 2],
          },
        }),
      ]);
      currentRevisionPlan = { ...currentRevisionPlan!, generated_revision_id: next.id };
      return route.fulfill({ status: 201, json: next });
    }
    if (request.method() === "GET" && path === "/candidates/rev-scoped/findings") {
      return route.fulfill({
        json: [
          finding({
            id: "finding-thin-edge",
            rule_id: "printability.thin_edge",
            severity: "warning",
            is_blocking: false,
          }),
        ],
      });
    }
    if (request.method() === "GET" && path === "/candidates/rev-scoped/geometric-analysis") {
      return route.fulfill({
        json: {
          id: "analysis-rev-scoped",
          revision_id: "rev-scoped",
          design_specification_id: "spec-1",
          analysis_version: "geometric-invariants-v1",
          tolerance_profile_version: "geometry-tolerance-v1",
          mesh_hash: "mesh-rev-scoped",
          source_hash: "source-rev-scoped",
          analysis_ms: 12.5,
          created_at: "2026-07-25T13:00:00Z",
          findings: [],
        },
      });
    }
    if (request.method() === "POST" && path === "/candidates/rev-scoped/accept") {
      project.active_revision_id = "rev-scoped";
      const active = revisions.find((entry) => entry.id === "rev-active")!;
      active.is_accepted = true;
      active.review_state = "accepted";
      const accepted = revisions.find((entry) => entry.id === "rev-scoped")!;
      accepted.is_accepted = true;
      accepted.review_state = "accepted";
      accepted.accepted_at = "2026-07-25T13:15:00Z";
      return route.fulfill({ json: accepted });
    }

    return route.fulfill({ status: 404, json: { detail: `unhandled ${request.method()} ${path}` } });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "Projects" }).click();
  await page.getByRole("button", { name: "Revision Workflow" }).click();
  await expect(page.getByText("Active design - R1 - Accepted revision")).toBeVisible();
  await expect(page.getByRole("link", { name: "Python" })).toBeVisible();
  await expect(page.getByLabel("Python source")).toBeVisible();

  await page.getByLabel("AI chat message").fill("Make the lid 4 mm thick");
  await page.getByRole("button", { name: "Plan revision" }).click();
  await expect(page.getByLabel("Revision Plan").getByText("Revision plan review")).toBeVisible();
  await expect(page.getByText("Increase lid thickness from 3 mm to 4 mm")).toBeVisible();
  await expect(page.getByText("lid_thickness: 3 -> 4")).toBeVisible();
  await expect(page.getByLabel("Revision Plan").getByText("Output body", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Generate revision" })).toBeDisabled();

  await page.getByRole("button", { name: "Approve revision plan" }).click();
  await expect(page.getByText("Candidate - R2 - Ready with warnings")).toBeVisible();
  await expect(page.getByText("Revision scope checks")).toBeVisible();
  await expect(page.getByText("Passed approved revision scope")).toBeVisible();
  await expect(page.getByText("Revision verification")).toBeVisible();
  await expect(page.getByText("lid_thickness: expected 4, detected 4")).toBeVisible();
  await expect(page.getByText("Printable outputs")).toBeVisible();
  await expect(page.getByLabel("Candidate review").getByRole("button", { name: /Body/ })).toBeVisible();
  await expect(page.getByLabel("Candidate review").getByRole("button", { name: /Lid/ })).toBeVisible();
  await expect(page.getByText("R1 active")).toBeVisible();

  await page.getByRole("button", { name: "Accept", exact: true }).click();
  await expect(page.getByText("Active design - R2 - Accepted revision")).toBeVisible();

  await page.getByLabel("AI chat message").fill("Make the body width 90 mm");
  await page.getByRole("button", { name: "Plan revision" }).click();
  await expect(page.getByLabel("Revision Plan").getByText("Revision plan review")).toBeVisible();
  await page.getByRole("button", { name: "Approve revision plan" }).click();
  await expect(page.getByLabel("Revision Plan").getByText("Revision scope checks")).toBeVisible();
  await expect(page.getByLabel("Revision Plan").getByText("Rejected before compile", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Revision Plan").getByText("Unauthorized parameter change")).toBeVisible();
  await expect(page.getByLabel("Source checks").getByText("Revision source rejected before compile")).toBeVisible();
  await expect(page.getByText("R2 active")).toBeVisible();
});

test("blocked CadQuery candidate shows partial outputs and solid-count rejection", async ({ page }) => {
  const project = {
    id: "project-1",
    name: "Solid Count Review",
    original_intent: "Create a mounting base with alignment bosses.",
    status: "active",
    active_revision_id: "rev-active",
  };
  const revisions: Revision[] = [
    revision({
      id: "rev-active",
      revision_number: 1,
      source_type: "ai_initial",
      is_accepted: true,
      review_state: "accepted",
      design_specification_id: "spec-1",
      design_plan_id: "plan-1",
      output_manifest_path: "projects/project-1/revisions/rev-active/output-manifest.json",
      expected_output_count: 1,
      required_output_count: 1,
      successful_output_count: 1,
    }),
    revision({
      id: "rev-blocked",
      parent_revision_id: "rev-active",
      revision_number: 2,
      source_type: "ai_initial",
      is_accepted: false,
      review_state: "blocked",
      design_specification_id: "spec-1",
      design_plan_id: "plan-1",
      output_manifest_path: "projects/project-1/revisions/rev-blocked/output-manifest.json",
      expected_output_count: 2,
      required_output_count: 2,
      successful_output_count: 1,
      blocked_output_count: 1,
      failed_output_count: 1,
      validation_summary: { blocking_count: 1, advisory_count: 0, dismissed_count: 0 },
      error_message: "Required output alignment_bosses failed topology validation",
    }),
  ];
  const outputsByRevision = new Map<string, ReturnType<typeof revisionOutput>[]>([
    [
      "rev-active",
      [
        revisionOutput({
          id: "active-base",
          revision_id: "rev-active",
          output_id: "base",
          label: "Base",
        }),
      ],
    ],
    [
      "rev-blocked",
      [
        revisionOutput({
          id: "blocked-base",
          revision_id: "rev-blocked",
          output_id: "base",
          label: "Base",
          output_state: "ready",
          required: true,
        }),
        revisionOutput({
          id: "blocked-bosses",
          revision_id: "rev-blocked",
          output_id: "alignment_bosses",
          label: "Alignment bosses",
          output_state: "blocked",
          required: true,
          stl_path: null,
          compile_error:
            "Solid-count mismatch: expected_solid_count=1, detected_solid_count=3; disconnected solids are not allowed.",
          validation_summary: { blocking_count: 1, advisory_count: 0, dismissed_count: 0 },
        }),
      ],
    ],
  ]);

  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace(/^\/api/, "");

    if (request.method() === "GET" && path === "/projects") {
      return route.fulfill({ json: [project] });
    }
    if (request.method() === "GET" && path === "/printability-profiles") {
      return route.fulfill({ json: [] });
    }
    if (request.method() === "GET" && path === "/projects/project-1/messages") {
      return route.fulfill({ json: [] });
    }
    if (request.method() === "GET" && path === "/projects/project-1/design-specification") {
      return route.fulfill({ status: 404, json: { detail: "not found" } });
    }
    if (request.method() === "GET" && path === "/projects/project-1/design-plan") {
      return route.fulfill({ status: 404, json: { detail: "not found" } });
    }
    if (request.method() === "GET" && path === "/projects/project-1/revision-plan") {
      return route.fulfill({ status: 404, json: { detail: "not found" } });
    }
    if (request.method() === "GET" && path === "/projects/project-1/revisions") {
      return route.fulfill({ json: revisions });
    }
    if (request.method() === "GET" && /^\/revisions\/[^/]+\/outputs$/.test(path)) {
      const revisionId = path.split("/")[2];
      return route.fulfill({ json: outputsByRevision.get(revisionId) ?? [] });
    }
    if (request.method() === "GET" && /^\/revisions\/[^/]+\/output-manifest$/.test(path)) {
      const revisionId = path.split("/")[2];
      return route.fulfill({
        json: {
          schema_version: "output-manifest-v1",
          project_id: "project-1",
          revision_id: revisionId,
          source: { filename: "source.py", sha256: "source-hash" },
          outputs: outputsByRevision.get(revisionId) ?? [],
        },
      });
    }
    if (request.method() === "GET" && path.endsWith("/source")) {
      return route.fulfill({ body: source, contentType: "text/plain" });
    }
    if (request.method() === "GET" && path.endsWith("/compile-log")) {
      return route.fulfill({ body: "CadQuery worker completed", contentType: "text/plain" });
    }
    if (request.method() === "GET" && path.endsWith("/diff")) {
      return route.fulfill({ status: 404, json: { detail: "not found" } });
    }
    if (request.method() === "GET" && path.endsWith("/stl")) {
      return route.fulfill({ body: "solid empty\nendsolid empty\n", contentType: "model/stl" });
    }
    if (request.method() === "GET" && /^\/revision-outputs\/[^/]+\/compile-log$/.test(path)) {
      return route.fulfill({ body: "Output compilation finished", contentType: "text/plain" });
    }
    if (request.method() === "GET" && path === "/candidates/rev-blocked/findings") {
      return route.fulfill({
        json: [
          finding({
            id: "finding-solid-count",
            rule_id: "topology.solid_count_mismatch",
            severity: "critical",
            is_blocking: true,
          }),
        ],
      });
    }
    if (request.method() === "GET" && path === "/candidates/rev-blocked/geometric-analysis") {
      return route.fulfill({ status: 404, json: { detail: "not found" } });
    }

    return route.fulfill({ status: 404, json: { detail: `unhandled ${request.method()} ${path}` } });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "Projects" }).click();
  await page.getByRole("button", { name: "Solid Count Review" }).click();
  await expect(page.getByText("Active design - R1 - Accepted revision")).toBeVisible();

  await page.getByRole("button", { name: /R2/ }).click();
  await expect(page.getByText("Candidate - R2 - Blocked")).toBeVisible();
  await expect(page.getByLabel("Candidate review").getByText("1/2")).toBeVisible();
  await expect(page.getByLabel("Candidate review").getByRole("button", { name: /Base/ })).toBeVisible();
  await expect(page.getByLabel("Candidate review").getByRole("button", { name: /Alignment bosses/ })).toBeVisible();
  await expect(page.getByText("Solid-count mismatch: expected_solid_count=1, detected_solid_count=3")).toBeVisible();
  await expect(page.getByLabel("Candidate review").getByText("topology.solid_count_mismatch", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Accept", exact: true })).toBeDisabled();
  await expect(page.getByText("R1 active")).toBeVisible();
});

function revision(overrides: Partial<Revision>): Revision {
  return {
    id: "revision",
    parent_revision_id: null,
    design_specification_id: null,
    design_plan_id: null,
    revision_number: 1,
    source_type: "ai_revision",
    status: "succeeded",
    is_accepted: false,
    review_state: "ready",
    accepted_at: null,
    rejected_at: null,
    user_instruction: "Generated",
    cad_backend: "cadquery",
    source_language: "python",
    stl_path: "model.stl",
    ai_output_path: null,
    output_manifest_path: null,
    expected_output_count: null,
    required_output_count: null,
    successful_output_count: null,
    blocked_output_count: null,
    failed_output_count: null,
    created_at: "2026-07-25T13:00:00Z",
    metadata: {
      size_x_mm: 80,
      size_y_mm: 50,
      size_z_mm: 24,
      volume_mm3: 96000,
      triangle_count: 12,
      connected_components: 1,
      is_watertight: true,
    },
    error_message: null,
    validation_summary: {
      blocking_count: 0,
      advisory_count: 0,
      dismissed_count: 0,
    },
    ...overrides,
  };
}

function revisionOutput(overrides: Record<string, unknown>) {
  return {
    id: "output",
    revision_id: "revision",
    design_plan_id: "plan-1",
    design_specification_id: "spec-1",
    output_id: "body",
    component_id: "body",
    component_ids: ["body"],
    output_state: "ready",
    output_type: "printable_component",
    label: "Body",
    filename: "body.stl",
    quantity: 1,
    required: true,
    entrypoint: "body",
    source_hash: "source-hash",
    stl_path: "projects/project-1/revisions/revision/stl/body.stl",
    stl_hash: "stl-hash",
    compile_log_path: "projects/project-1/revisions/revision/logs/body.log",
    compile_ms: 25,
    compile_error: null,
    execution_command: ["python", "_volundr_cadquery_runner.py"],
    metadata: {
      size_x_mm: 80,
      size_y_mm: 50,
      size_z_mm: 24,
      volume_mm3: 96000,
      triangle_count: 12,
      connected_components: 1,
      is_watertight: true,
      is_winding_consistent: true,
      center_of_mass: [40, 25, 12],
    },
    validation_summary: {
      blocking_count: 0,
      advisory_count: 0,
      dismissed_count: 0,
    },
    preferred_orientation: null,
    created_at: "2026-07-25T13:00:00Z",
    updated_at: "2026-07-25T13:00:00Z",
    ...overrides,
  };
}

function revisionPlan(overrides: Record<string, unknown>) {
  return {
    id: "revision-plan",
    project_id: "project-1",
    base_revision_id: "rev-active",
    base_design_specification_id: "spec-1",
    base_design_plan_id: "plan-1",
    generation_attempt_id: "attempt-revision-plan",
    superseded_revision_plan_id: null,
    generated_revision_id: null,
    revised_design_specification_id: null,
    revised_design_plan_id: null,
    version_number: 1,
    schema_version: "revision-plan-v1",
    prompt_template_version: "revision-planning-v1",
    ruleset_version: "gemini-ruleset-v1",
    provider: "fake",
    provider_model: "fake-model",
    user_instruction: "Make the lid 4 mm thick",
    reason: "user_request",
    raw_response_path: null,
    plan_path: "projects/project-1/revision-plans/revision-plan.json",
    content_hash: "revision-plan-hash",
    base_source_hash: "source-hash",
    base_output_manifest_hash: "manifest-hash",
    base_design_specification_hash: "spec-hash",
    base_design_plan_hash: "plan-hash",
    outcome: "revision_ready",
    review_state: "pending_review",
    clarification_required: false,
    revision_ready: true,
    approved_at: null,
    rejected_at: null,
    created_at: "2026-07-25T13:10:00Z",
    revision_plan: revisionPlanPayload(),
    clarification_questions: [],
    ...overrides,
  };
}

function revisionPlanPayload() {
  return {
    summary: "Increase lid thickness from 3 mm to 4 mm",
    requested_changes: [
      {
        target_type: "parameter",
        target_id: "lid_thickness",
        current_value: 3,
        requested_value: 4,
        change_type: "set_value",
        source: "user",
      },
    ],
    required_dependency_changes: [
      {
        parameter_id: "lid_lip_depth",
        affects: ["lid"],
      },
    ],
    targeted_components: ["lid"],
    targeted_features: ["lid_lip"],
    targeted_outputs: ["lid"],
    targeted_findings: [],
    allowed_parameter_changes: ["lid_thickness", "lid_lip_depth"],
    protected_parameters: [
      { parameter_id: "body_width", expected_value: 80, unit: "mm" },
      { parameter_id: "wall_thickness", expected_value: 3, unit: "mm" },
    ],
    protected_components: ["body"],
    protected_features: ["mounting_tabs"],
    protected_outputs: ["body"],
    prohibited_changes: ["Do not change body output geometry."],
    success_criteria: [
      { type: "parameter_value", target_id: "lid_thickness", expected_value: 4, unit: "mm" },
      { type: "parameter_unchanged", target_id: "wall_thickness", expected_value: 3, unit: "mm" },
      { type: "output_exists", target_id: "lid", expected_value: true },
    ],
    clarification_questions: [],
    outcome: "revision_ready",
    revision_ready: true,
    clarification_required: false,
  };
}

function complianceResult(passed: boolean) {
  return {
    id: "compliance-1",
    revision_plan_id: "revision-plan-1",
    generation_attempt_id: "attempt-revision",
    revision_id: passed ? "rev-scoped" : null,
    base_source_hash: "source-hash",
    revised_source_hash: passed ? "source-scoped" : "source-rejected",
    passed,
    validation_ms: 3.2,
    findings: passed
      ? []
      : [
          {
            rule_id: "revision.unauthorized_parameter_change",
            is_blocking: true,
            title: "Unauthorized parameter change",
            explanation: "lid_thickness expected 4 mm, detected 5 mm",
            expected_value: 4,
            detected_value: 5,
            parameter_id: "lid_thickness",
          },
        ],
    created_at: "2026-07-25T13:11:00Z",
  };
}

function successResult() {
  return {
    id: "success-1",
    revision_plan_id: "revision-plan-1",
    generation_attempt_id: "attempt-revision",
    revision_id: "rev-scoped",
    criterion_type: "parameter_value",
    target_id: "lid_thickness",
    verification_state: "success_verified",
    expected_value: 4,
    detected_value: 4,
    unit: "mm",
    tolerance: 0.000001,
    confidence: 1,
    is_blocking: false,
    explanation: "Revised parameter matched the approved Revision Plan.",
    metadata: {},
    created_at: "2026-07-25T13:11:00Z",
  };
}

function finding(overrides: {
  id: string;
  rule_id: string;
  category?: string;
  severity: "warning" | "critical";
  is_blocking: boolean;
}) {
  return {
    revision_id: "revision",
    category: overrides.rule_id.split(".")[0],
    title: overrides.rule_id,
    explanation: `${overrides.rule_id} explanation`,
    suggested_correction: `${overrides.rule_id} correction`,
    detected_value: "1",
    unit: "mm",
    threshold_value: null,
    orientation_dependent: true,
    affected_geometry_summary: null,
    metadata_json: "{}",
    finding_state: "open",
    dismissal_reason: null,
    dismissed_at: null,
    created_at: "2026-07-25T13:00:00Z",
    ...overrides,
  };
}
