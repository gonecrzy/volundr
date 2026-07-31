import { expect, test } from "@playwright/test";

type Revision = {
  id: string;
  parent_revision_id: string | null;
  design_specification_id: string | null;
  design_plan_id: string | null;
  configuration_change_id: string | null;
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
from volundr_cad.runtime import ParameterSpec, PrintableOutput, Product, component

PARAMETERS = [
    ParameterSpec(id="body_width", label="Body width", type="float", default=80.0, unit="mm"),
    ParameterSpec(id="lid_thickness", label="Lid thickness", type="float", default=4.0, unit="mm"),
]

@component("body")
def body_model(params):
    return cq.Workplane("XY").box(params["body_width"], 50, 24)

@component("lid")
def lid_model(params):
    return cq.Workplane("XY").box(params["body_width"], 50, params["lid_thickness"])

def build(params):
    body = body_model(params)
    lid = lid_model(params)
    return Product(parameters=PARAMETERS, outputs=[
        PrintableOutput(output_id="body", label="Body", component_id="body", model=body, expected_solid_count=1, allow_disconnected_solids=False),
        PrintableOutput(output_id="lid", label="Lid", component_id="lid", model=lid, expected_solid_count=1, allow_disconnected_solids=False),
    ])
`;

test("requirements clarification flows into Design Plan approval and CadQuery candidate review", async ({ page }) => {
  const workflowHeaders = {
    "x-workflow-run-id": "workflow-run-1",
    "x-workflow-root-run-id": "workflow-run-1",
    "x-workflow-correlation-id": "workflow-correlation-1",
  };
  const project = {
    id: "project-1",
    name: "Untitled draft",
    original_intent: "",
    status: "draft",
    active_revision_id: null,
  };
  const revisions: Revision[] = [];
  let currentSpecification = designSpecification({
    outcome: "clarification_required",
    clarification_required: true,
    generation_ready: false,
    clarification_questions: [
      {
        id: "question-depth",
        project_id: "project-1",
        design_specification_id: "spec-1",
        requirement_id: "fit_depth",
        question: "What shelf depth should the bracket support?",
        reason: "Shelf depth affects the bracket leg length.",
        display_order: 1,
        created_at: "2026-07-30T16:30:00Z",
      },
    ],
  });
  let currentPlan: ReturnType<typeof designPlan> | null = null;
  const candidate = revision({
    id: "rev-generated",
    design_specification_id: "spec-1",
    design_plan_id: "plan-1",
    revision_number: 1,
    source_type: "ai_initial",
    review_state: "ready",
    is_accepted: false,
    output_manifest_path: "projects/project-1/revisions/rev-generated/output-manifest.json",
    expected_output_count: 1,
    required_output_count: 1,
    successful_output_count: 1,
  });
  const outputsByRevision = new Map<string, ReturnType<typeof revisionOutput>[]>([
    [
      "rev-generated",
      [
        revisionOutput({
          id: "generated-bracket",
          revision_id: "rev-generated",
          output_id: "bracket",
          label: "Bracket",
          component_id: "bracket",
          component_ids: ["bracket"],
        }),
      ],
    ],
  ]);

  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace(/^\/api/, "");

    if (request.method() === "GET" && path === "/projects") {
      return route.fulfill({ json: [] });
    }
    if (request.method() === "GET" && path === "/projects/project-1") {
      return route.fulfill({ json: project });
    }
    if (request.method() === "GET" && path === "/printability-profiles") {
      return route.fulfill({ json: [] });
    }
    if (request.method() === "POST" && path === "/projects/draft") {
      return route.fulfill({ status: 201, json: project });
    }
    if (request.method() === "GET" && path === "/projects/project-1/messages") {
      return route.fulfill({ json: [] });
    }
    if (request.method() === "POST" && path === "/projects/project-1/requirements") {
      return route.fulfill({ status: 201, headers: workflowHeaders, json: currentSpecification });
    }
    if (request.method() === "POST" && path === "/workflow/frontend-events") {
      return route.fulfill({ status: 201, json: { accepted_count: 1 } });
    }
    if (request.method() === "POST" && path === "/design-specifications/spec-1/clarification-answers") {
      currentSpecification = designSpecification({
        outcome: "generation_ready",
        clarification_required: false,
        generation_ready: true,
        clarification_questions: [],
        specification: {
          purpose: "Adjustable shelf bracket",
          critical_dimensions: [
            {
              id: "shelf_depth",
              label: "Shelf depth",
              value: 180,
              unit: "mm",
              source: "clarification",
              importance: "critical",
              protected: true,
            },
          ],
          functional_requirements: [
            {
              id: "mounting_holes",
              description: "Two wall mounting holes",
              source: "user",
              importance: "critical",
              protected: true,
            },
          ],
          assumptions: [
            {
              id: "material_thickness",
              description: "Use 5 mm printable material thickness",
              source: "product_default",
              requires_approval: false,
            },
          ],
        },
      });
      return route.fulfill({ json: currentSpecification });
    }
    if (request.method() === "POST" && path === "/design-specifications/spec-1/design-plan") {
      currentPlan = designPlan();
      return route.fulfill({ status: 201, headers: workflowHeaders, json: currentPlan });
    }
    if (request.method() === "POST" && path === "/design-plans/plan-1/approve") {
      currentPlan = designPlan({ review_state: "approved", approved_at: "2026-07-30T16:35:00Z" });
      return route.fulfill({ json: currentPlan });
    }
    if (request.method() === "POST" && path === "/design-plans/plan-1/generate") {
      revisions.push(candidate);
      currentPlan = designPlan({
        review_state: "approved",
        approved_at: "2026-07-30T16:35:00Z",
        generated_revision_id: "rev-generated",
      });
      return route.fulfill({ status: 201, headers: workflowHeaders, json: candidate });
    }
    if (request.method() === "POST" && path === "/candidates/rev-generated/accept") {
      candidate.review_state = "accepted";
      candidate.is_accepted = true;
      candidate.accepted_at = "2026-07-30T16:40:00Z";
      project.active_revision_id = candidate.id;
      return route.fulfill({ headers: workflowHeaders, json: candidate });
    }
    if (request.method() === "GET" && path === "/workflow-runs/workflow-run-1/debug-bundle.zip") {
      return route.fulfill({
        body: "workflow-debug-workflow-run-1",
        contentType: "application/zip",
      });
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
    if (request.method() === "GET" && path === "/revisions/rev-generated/export.zip") {
      return route.fulfill({ body: "export", contentType: "application/zip" });
    }
    if (request.method() === "GET" && path.endsWith("/source")) {
      return route.fulfill({ body: source, contentType: "text/plain" });
    }
    if (request.method() === "GET" && path.endsWith("/compile-log")) {
      return route.fulfill({ body: "CadQuery execution completed", contentType: "text/plain" });
    }
    if (request.method() === "GET" && path.endsWith("/diff")) {
      return route.fulfill({ status: 404, json: { detail: "not found" } });
    }
    if (request.method() === "GET" && path.endsWith("/stl")) {
      return route.fulfill({ body: "solid empty\nendsolid empty\n", contentType: "model/stl" });
    }
    if (request.method() === "GET" && path.endsWith("/step")) {
      return route.fulfill({ body: "ISO-10303-21;", contentType: "model/step" });
    }
    if (request.method() === "GET" && /^\/revision-outputs\/[^/]+\/compile-log$/.test(path)) {
      return route.fulfill({ body: "Output compilation finished", contentType: "text/plain" });
    }
    if (request.method() === "GET" && path === "/candidates/rev-generated/findings") {
      return route.fulfill({ json: [] });
    }
    if (request.method() === "GET" && path === "/candidates/rev-generated/geometric-analysis") {
      return route.fulfill({
        json: {
          id: "analysis-rev-generated",
          revision_id: "rev-generated",
          design_specification_id: "spec-1",
          analysis_version: "geometric-invariants-v1",
          tolerance_profile_version: "geometry-tolerance-v1",
          mesh_hash: "mesh-generated",
          source_hash: "source-hash",
          analysis_ms: 8.1,
          created_at: "2026-07-30T16:36:00Z",
          findings: [],
        },
      });
    }

    return route.fulfill({ status: 404, json: { detail: `unhandled ${request.method()} ${path}` } });
  });

  await page.goto("/");
  await expect(page.getByLabel("Design progress").getByText("Describe", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Design progress").getByText("Review requirements", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Design progress").getByText("Review proposed design", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Design progress").getByText("Review new version", { exact: true })).toBeVisible();
  await expect(page.getByText("You do not need to specify every dimension.")).toBeVisible();
  await page.getByLabel("AI chat message").fill("Create a shelf bracket for a board.");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByLabel("Design requirements").getByText("Waiting for clarification")).toBeVisible();
  await expect(page.getByLabel("Design requirements").getByText("A few details are still needed")).toBeVisible();
  await expect(page.getByLabel("Design requirements").getByRole("textbox")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Design requirements" })).toBeFocused();

  await page.getByLabel("AI chat message").fill("180 mm shelf depth");
  await page.getByRole("button", { name: "Answer", exact: true }).click();
  await expect(page.getByLabel("Design requirements").getByText("Requirements ready")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Your requirements" })).toBeVisible();

  await page.getByRole("button", { name: "Review proposed design" }).click();
  await expect(page.getByLabel("Proposed design").getByText("Ready for your review")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Proposed design" })).toBeFocused();
  await expect(page.getByText("Mounting holes (hole_group)")).toBeVisible();
  await expect(page.getByText("Bracket - one part")).toBeVisible();
  await expect(page.getByRole("button", { name: "Generate design" })).toBeEnabled();

  await page.getByRole("button", { name: "Generate design" }).click();
  await expect(page.getByText("New version - R1 - Ready to review")).toBeVisible();
  await expect(page.getByLabel("Candidate review").getByText("1/1", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Candidate review").getByRole("button", { name: /Bracket/ })).toBeVisible();
  await expect(page.getByLabel("Candidate review").getByRole("link", { name: "STEP" })).toBeVisible();
  await expect(page.getByLabel("Candidate review").getByRole("link", { name: "STL" })).toBeVisible();
  await expect(page.getByLabel("Candidate review").getByText("Topology valid")).toBeVisible();
  await expect(page.getByLabel("Candidate review").getByText("Solids 1/1")).toBeVisible();
  await expect(page.getByText("Geometric checks")).toBeVisible();
  await expect(page.getByText("0 verified, 0 violated, 0 unable to verify")).toBeVisible();
  await page.getByText("Technical details").click();
  await expect(page.getByText(/^Workflow run:/)).toBeVisible();
  await expect(page.getByText("workflow-run-1", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Copy workflow run ID" })).toBeVisible();
  const diagnosticBundle = page.getByRole("link", { name: "Download diagnostic bundle" });
  await expect(diagnosticBundle).toBeVisible();
  await expect(diagnosticBundle).toHaveAttribute(
    "href",
    /\/api\/workflow-runs\/workflow-run-1\/debug-bundle\.zip/,
  );
  const bundleHref = await diagnosticBundle.getAttribute("href");
  if (!bundleHref) {
    throw new Error("diagnostic bundle href was not rendered");
  }
  const bundleResponsePromise = page.waitForResponse(/\/api\/workflow-runs\/workflow-run-1\/debug-bundle\.zip/);
  await page.evaluate((href) => fetch(href), bundleHref);
  const bundleResponse = await bundleResponsePromise;
  expect(bundleResponse.ok()).toBeTruthy();
  await page.getByRole("button", { name: "Accept new version" }).click();
  await expect(page.getByText("Current design - R1 - Current design")).toBeVisible();
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("link", { name: "Export design" }).click();
  expect((await downloadPromise).suggestedFilename()).not.toBe("");
});

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
    if (request.method() === "GET" && path === "/projects/project-1") {
      return route.fulfill({ json: project });
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
    if (request.method() === "GET" && path.endsWith("/step")) {
      return route.fulfill({ body: "ISO-10303-21;", contentType: "model/step" });
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
  await expect(page.getByText("Current design - R1 - Current design")).toBeVisible();

  await page.getByLabel("AI chat message").fill("Make the lid 4 mm thick");
  await page.getByRole("button", { name: "Change the design" }).click();
  await expect(page.getByLabel("Planned changes").getByText("Ready for your review")).toBeVisible();
  await expect(page.getByText("Increase lid thickness from 3 mm to 4 mm")).toBeVisible();
  await expect(page.getByText("lid_thickness: 3 -> 4")).toBeVisible();
  await expect(page.getByLabel("Planned changes").getByText("Output body", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Generate new version" })).toBeDisabled();

  await page.getByRole("button", { name: "Review planned changes" }).click();
  await expect(page.getByText("New version - R2 - Ready with warnings")).toBeVisible();
  await expect(page.getByText("Revision scope checks")).toBeVisible();
  await expect(page.getByText("Passed approved revision scope")).toBeVisible();
  await expect(page.getByText("Revision verification")).toBeVisible();
  await expect(page.getByText("lid_thickness: expected 4, detected 4")).toBeVisible();
  await expect(page.getByText("Printable parts - 2")).toBeVisible();
  await expect(page.getByLabel("Candidate review").getByRole("button", { name: /Body/ })).toBeVisible();
  await expect(page.getByLabel("Candidate review").getByRole("button", { name: /Lid/ })).toBeVisible();
  await expect(page.getByText("R1 active")).toBeVisible();

  await page.getByRole("button", { name: "Accept new version", exact: true }).click();
  await expect(page.getByText("Current design - R2 - Current design")).toBeVisible();

  await page.getByLabel("AI chat message").fill("Make the body width 90 mm");
  await page.getByRole("button", { name: "Change the design" }).click();
  await expect(page.getByLabel("Planned changes").getByText("Ready for your review")).toBeVisible();
  await page.getByRole("button", { name: "Review planned changes" }).click();
  await expect(page.getByLabel("Planned changes").getByText("Revision scope checks")).toBeVisible();
  await expect(page.getByLabel("Planned changes").getByText("Rejected before compile", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Planned changes").getByText("Unauthorized parameter change")).toBeVisible();
  await expect(page.getByLabel("Source checks").getByText("Revision source rejected before compile")).toBeVisible();
  await expect(page.getByText("R2 active")).toBeVisible();
});

test("deterministic configuration generates a CadQuery candidate without replacing the active revision", async ({ page }) => {
  const project = {
    id: "project-1",
    name: "Configured Rail",
    original_intent: "Create a configurable mounting rail.",
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
  ];
  const configuredCandidate = revision({
    id: "rev-config",
    parent_revision_id: "rev-active",
    configuration_change_id: "config-1",
    revision_number: 2,
    source_type: "ai_revision",
    is_accepted: false,
    review_state: "ready",
    design_specification_id: "spec-1",
    design_plan_id: "plan-1",
    output_manifest_path: "projects/project-1/revisions/rev-config/output-manifest.json",
    expected_output_count: 1,
    required_output_count: 1,
    successful_output_count: 1,
  });
  const outputsByRevision = new Map<string, ReturnType<typeof revisionOutput>[]>([
    [
      "rev-active",
      [
        revisionOutput({
          id: "active-rail",
          revision_id: "rev-active",
          output_id: "rail",
          label: "Rail body",
          component_id: "rail_body",
          component_ids: ["rail_body"],
        }),
      ],
    ],
    [
      "rev-config",
      [
        revisionOutput({
          id: "configured-rail",
          revision_id: "rev-config",
          output_id: "rail",
          label: "Rail body",
          component_id: "rail_body",
          component_ids: ["rail_body"],
          metadata: {
            size_x_mm: 90,
            size_y_mm: 50,
            size_z_mm: 24,
            volume_mm3: 108000,
            triangle_count: 12,
            connected_components: 1,
            is_watertight: true,
            is_winding_consistent: true,
            center_of_mass: [45, 25, 12],
          },
        }),
      ],
    ],
  ]);
  let preview = configurationChange({ generated_revision_id: null });

  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace(/^\/api/, "");

    if (request.method() === "GET" && path === "/projects") {
      return route.fulfill({ json: [project] });
    }
    if (request.method() === "GET" && path === "/projects/project-1") {
      return route.fulfill({ json: project });
    }
    if (request.method() === "GET" && path === "/printability-profiles") {
      return route.fulfill({ json: [] });
    }
    if (request.method() === "GET" && path === "/projects/project-1/messages") {
      return route.fulfill({ json: [] });
    }
    if (request.method() === "GET" && path === "/projects/project-1/design-specification") {
      return route.fulfill({ json: designSpecification() });
    }
    if (request.method() === "GET" && path === "/projects/project-1/design-plan") {
      return route.fulfill({
        json: designPlan({ review_state: "approved", approved_at: "2026-07-30T16:35:00Z", generated_revision_id: "rev-active" }),
      });
    }
    if (request.method() === "GET" && path === "/projects/project-1/revision-plan") {
      return route.fulfill({ status: 404, json: { detail: "not found" } });
    }
    if (request.method() === "GET" && path === "/projects/project-1/configuration/parameters") {
      return route.fulfill({
        json: [
          {
            id: "body_width",
            label: "Body width",
            value: 80,
            unit: "mm",
            type: "number",
            editable: true,
            protected: false,
            source_mapped: true,
            minimum: 60,
            maximum: 120,
            allowed_values: [],
            affected_components: ["rail_body"],
            affected_outputs: ["rail"],
          },
        ],
      });
    }
    if (request.method() === "GET" && path === "/projects/project-1/configuration/presets") {
      return route.fulfill({ json: [] });
    }
    if (request.method() === "POST" && path === "/projects/project-1/configuration/preview") {
      const body = await request.postDataJSON();
      expect(body.parameter_values).toEqual({ body_width: 90 });
      preview = configurationChange({ generated_revision_id: null });
      return route.fulfill({ status: 201, json: preview });
    }
    if (request.method() === "POST" && path === "/configuration-changes/config-1/generate") {
      revisions.push(configuredCandidate);
      preview = configurationChange({ generated_revision_id: "rev-config" });
      return route.fulfill({ status: 201, json: configuredCandidate });
    }
    if (request.method() === "GET" && path === "/configuration-changes/config-1") {
      return route.fulfill({ json: preview });
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
      return route.fulfill({ body: "CadQuery execution completed with parameter values", contentType: "text/plain" });
    }
    if (request.method() === "GET" && path.endsWith("/diff")) {
      return route.fulfill({ status: 404, json: { detail: "not found" } });
    }
    if (request.method() === "GET" && path.endsWith("/stl")) {
      return route.fulfill({ body: "solid empty\nendsolid empty\n", contentType: "model/stl" });
    }
    if (request.method() === "GET" && path.endsWith("/step")) {
      return route.fulfill({ body: "ISO-10303-21;", contentType: "model/step" });
    }
    if (request.method() === "GET" && /^\/revision-outputs\/[^/]+\/compile-log$/.test(path)) {
      return route.fulfill({ body: "Output compilation finished", contentType: "text/plain" });
    }
    if (request.method() === "GET" && /^\/candidates\/[^/]+\/findings$/.test(path)) {
      return route.fulfill({ json: [] });
    }
    if (request.method() === "GET" && /^\/candidates\/[^/]+\/geometric-analysis$/.test(path)) {
      return route.fulfill({ status: 404, json: { detail: "not found" } });
    }

    return route.fulfill({ status: 404, json: { detail: `unhandled ${request.method()} ${path}` } });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "Projects" }).click();
  await page.getByRole("button", { name: "Configured Rail" }).click();
  await expect(page.getByText("Current design - R1 - Current design")).toBeVisible();
  await expect(page.getByLabel("Configure parameters").getByText("Body width (mm)")).toBeVisible();

  await page.getByLabel("Body width (mm)").fill("90");
  await page.getByRole("button", { name: "Preview effects" }).click();
  await expect(page.getByLabel("Configure parameters").getByText("Configuration ready")).toBeVisible();
  await expect(page.getByLabel("Configure parameters").getByText("1 component, 1 output")).toBeVisible();

  await page.getByLabel("Configure parameters").getByRole("button", { name: "Create new version" }).click();
  await expect(page.getByText("New version - R2 - Ready to review")).toBeVisible();
  await expect(page.getByLabel("Candidate review").getByText("90 x 50 x 24 mm")).toBeVisible();
  await expect(page.getByLabel("Candidate review").getByText("Topology valid")).toBeVisible();
  await expect(page.getByText("R1 active")).toBeVisible();
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
          execution_state: "ready",
          required: true,
        }),
        revisionOutput({
          id: "blocked-bosses",
          revision_id: "rev-blocked",
          output_id: "alignment_bosses",
          label: "Alignment bosses",
          execution_state: "blocked",
          required: true,
          stl_path: null,
          step_path: null,
          expected_solid_count: 1,
          detected_solid_count: 3,
          allow_disconnected_solids: false,
          topology_metadata: {
            valid: false,
            failure_reason: "solid_count_mismatch",
            expected_solid_count: 1,
            detected_solid_count: 3,
            allow_disconnected_solids: false,
            shell_count: 3,
          },
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
    if (request.method() === "GET" && path === "/projects/project-1") {
      return route.fulfill({ json: project });
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
      return route.fulfill({ body: "CadQuery execution completed", contentType: "text/plain" });
    }
    if (request.method() === "GET" && path.endsWith("/diff")) {
      return route.fulfill({ status: 404, json: { detail: "not found" } });
    }
    if (request.method() === "GET" && path.endsWith("/stl")) {
      return route.fulfill({ body: "solid empty\nendsolid empty\n", contentType: "model/stl" });
    }
    if (request.method() === "GET" && path.endsWith("/step")) {
      return route.fulfill({ body: "ISO-10303-21;", contentType: "model/step" });
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
  await expect(page.getByText("Current design - R1 - Current design")).toBeVisible();

  await page.getByRole("button", { name: /R2/ }).click();
  await expect(page.getByText("New version - R2 - Needs changes")).toBeVisible();
  await expect(page.getByLabel("Candidate review").getByText("1/2")).toBeVisible();
  await expect(page.getByLabel("Candidate review").getByRole("button", { name: /Base/ })).toBeVisible();
  await expect(page.getByLabel("Candidate review").getByRole("button", { name: /Alignment bosses/ })).toBeVisible();
  await expect(page.getByLabel("Candidate review").getByText("Topology failed: solid count mismatch")).toBeVisible();
  await expect(page.getByLabel("Candidate review").getByText("Solids 3/1")).toBeVisible();
  await expect(page.getByText("Solid-count mismatch: expected_solid_count=1, detected_solid_count=3")).toBeVisible();
  await expect(page.getByLabel("Candidate review").getByText("topology.solid_count_mismatch", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Accept new version", exact: true })).toBeDisabled();
  await expect(page.getByText("R1 active")).toBeVisible();
});

function revision(overrides: Partial<Revision>): Revision {
  return {
    id: "revision",
    parent_revision_id: null,
    design_specification_id: null,
    design_plan_id: null,
    configuration_change_id: null,
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

function designSpecification(overrides: Record<string, unknown> = {}) {
  return {
    id: "spec-1",
    project_id: "project-1",
    generation_attempt_id: "attempt-requirements",
    superseded_specification_id: null,
    version_number: 1,
    schema_version: "design-specification-v1",
    prompt_template_version: "requirements-v1",
    ruleset_version: "cadquery-ruleset-v1",
    provider: "fake",
    provider_model: "fake-model",
    user_instruction: "Create a shelf bracket for a board.",
    raw_response_path: null,
    specification_path: "projects/project-1/design-specifications/spec-1.json",
    content_hash: "spec-hash",
    outcome: "generation_ready",
    supported_scope: true,
    clarification_required: false,
    generation_ready: true,
    created_at: "2026-07-30T16:30:00Z",
    specification: {
      purpose: "Adjustable shelf bracket",
      critical_dimensions: [
        {
          id: "shelf_depth",
          label: "Shelf depth",
          value: 180,
          unit: "mm",
          source: "clarification",
          importance: "critical",
          protected: true,
        },
      ],
      functional_requirements: [
        {
          id: "mounting_holes",
          description: "Two wall mounting holes",
          source: "user",
          importance: "critical",
          protected: true,
        },
      ],
      assumptions: [],
    },
    clarification_questions: [],
    ...overrides,
  };
}

function designPlan(overrides: Record<string, unknown> = {}) {
  return {
    id: "plan-1",
    project_id: "project-1",
    design_specification_id: "spec-1",
    generation_attempt_id: "attempt-plan",
    superseded_design_plan_id: null,
    version_number: 1,
    schema_version: "design-plan-v1",
    prompt_template_version: "design-plan-v1",
    ruleset_version: "cadquery-ruleset-v1",
    provider: "fake",
    provider_model: "fake-model",
    raw_response_path: null,
    plan_path: "projects/project-1/design-plans/plan-1.json",
    content_hash: "plan-hash",
    outcome: "plan_ready",
    review_state: "pending_review",
    clarification_required: false,
    plan_ready: true,
    approved_at: null,
    rejected_at: null,
    created_at: "2026-07-30T16:34:00Z",
    generated_revision_id: null,
    clarification_questions: [],
    plan: {
      purpose: "Shelf bracket with protected shelf depth",
      design_level: "single_part",
      parameters: [
        {
          id: "shelf_depth",
          label: "Shelf depth",
          value: 180,
          unit: "mm",
          editable: true,
          protected: true,
          component_id: "bracket",
        },
        {
          id: "hole_spacing",
          label: "Hole spacing",
          value: 48,
          unit: "mm",
          editable: true,
          protected: false,
          component_id: "bracket",
        },
      ],
      derived_parameters: [
        {
          id: "leg_length",
          label: "Leg length",
          expression: "shelf_depth - 20",
          unit: "mm",
          depends_on: ["shelf_depth"],
        },
      ],
      dependency_edges: [
        {
          from: "shelf_depth",
          to: "leg_length",
          relationship: "drives",
        },
      ],
      components: [
        {
          id: "bracket",
          label: "Bracket",
          description: "One-piece shelf bracket",
          features: ["mounting_holes"],
          parameters: ["shelf_depth", "hole_spacing"],
        },
      ],
      features: [
        {
          id: "mounting_holes",
          component_id: "bracket",
          type: "hole_group",
          description: "Mounting holes",
          parameters: ["hole_spacing"],
          protected: true,
        },
      ],
      presets: [],
      assembly_strategy: { type: "single_output", instructions: ["Print flat on the wall face."] },
      printable_outputs: [
        {
          id: "bracket",
          label: "Bracket",
          component_ids: ["bracket"],
          quantity: 1,
          orientation: "wall face on build plate",
        },
      ],
      risks: [
        {
          id: "load_capacity",
          severity: "warning",
          description: "Load capacity requires user validation.",
        },
      ],
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
    execution_state: "ready",
    output_type: "printable_component",
    label: "Body",
    filename: "body.stl",
    quantity: 1,
    required: true,
    entrypoint: "body",
    source_hash: "source-hash",
    stl_path: "projects/project-1/revisions/revision/stl/body.stl",
    stl_hash: "stl-hash",
    step_path: "projects/project-1/revisions/revision/step/body.step",
    step_hash: "step-hash",
    compile_log_path: "projects/project-1/revisions/revision/logs/body.log",
    compile_ms: 25,
    compile_error: null,
    execution_command: ["python", "_volundr_cadquery_runner.py"],
    expected_solid_count: 1,
    detected_solid_count: 1,
    allow_disconnected_solids: false,
    topology_metadata: {
      valid: true,
      expected_solid_count: 1,
      detected_solid_count: 1,
      allow_disconnected_solids: false,
      shell_count: 1,
    },
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

function configurationChange(overrides: Record<string, unknown>) {
  return {
    id: "config-1",
    project_id: "project-1",
    base_revision_id: "rev-active",
    generated_revision_id: null,
    design_specification_id: "spec-1",
    design_plan_id: "plan-1",
    schema_version: "configuration-change-v1",
    reason: "user_configuration",
    selected_preset_id: null,
    validation_state: "configuration_ready",
    base_source_hash: "source-hash",
    content_hash: "configuration-hash",
    requested_changes: { body_width: 90 },
    preset_values: {},
    user_overrides: {},
    resolved_parameters: { body_width: 90 },
    affected_parameters: ["body_width"],
    affected_components: ["rail_body"],
    affected_outputs: ["rail"],
    validation_errors: [],
    override_manifest_path: "projects/project-1/configuration-changes/config-1/parameter-overrides.json",
    configuration_path: "projects/project-1/configuration-changes/config-1/configuration.json",
    created_at: "2026-07-30T16:40:00Z",
    approved_at: null,
    ...overrides,
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
