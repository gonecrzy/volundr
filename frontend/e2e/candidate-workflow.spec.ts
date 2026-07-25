import { expect, test } from "@playwright/test";

type Revision = {
  id: string;
  parent_revision_id: string | null;
  design_specification_id: string | null;
  revision_number: number;
  source_type: string;
  status: string;
  is_accepted: boolean;
  review_state: string | null;
  accepted_at: string | null;
  rejected_at: string | null;
  user_instruction: string | null;
  stl_path: string | null;
  ai_output_path: string | null;
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

const source = "module main_model() { cube([10, 10, 10]); } main_model();";

test("candidate workflow keeps active revision safe while accepting and rejecting candidates", async ({ page }) => {
  const project = {
    id: "project-1",
    name: "Candidate Workflow",
    original_intent: "Create a tested fixture.",
    status: "active",
    active_revision_id: "rev-active",
  };
  const revisions: Revision[] = [
    revision({
      id: "rev-active",
      revision_number: 1,
      source_type: "manual_edit",
      is_accepted: true,
      review_state: "accepted",
    }),
  ];
  let generatedCandidateCount = 0;
  let requirementCount = 0;
  let designPlanCount = 0;
  const designPlans = new Map<string, ReturnType<typeof designPlan>>();

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
    if (request.method() === "GET" && path === "/projects/project-1/revisions") {
      return route.fulfill({ json: revisions });
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
    if (request.method() === "POST" && path === "/projects/project-1/requirements") {
      requirementCount += 1;
      if (requirementCount === 1) {
        return route.fulfill({ status: 201, json: clarificationSpec() });
      }
      return route.fulfill({ status: 201, json: readySpec(`spec-ready-${requirementCount}`) });
    }
    if (
      request.method() === "POST" &&
      path === "/design-specifications/spec-clarify/clarification-answers"
    ) {
      return route.fulfill({ status: 201, json: readySpec("spec-ready-1") });
    }
    if (request.method() === "POST" && /^\/design-specifications\/spec-ready-\d+\/design-plan$/.test(path)) {
      designPlanCount += 1;
      const specificationId = path.split("/")[2];
      const nextPlan = designPlan(`plan-${designPlanCount}`, specificationId);
      designPlans.set(nextPlan.id, nextPlan);
      return route.fulfill({ status: 201, json: nextPlan });
    }
    if (request.method() === "POST" && /^\/design-plans\/plan-\d+\/approve$/.test(path)) {
      const planId = path.split("/")[2];
      const approved = { ...designPlans.get(planId)!, review_state: "approved", approved_at: "2026-07-25T13:02:00Z" };
      designPlans.set(planId, approved);
      return route.fulfill({ json: approved });
    }
    if (request.method() === "POST" && /^\/design-plans\/plan-\d+\/generate$/.test(path)) {
      generatedCandidateCount += 1;
      if (generatedCandidateCount === 3) {
        return route.fulfill({
          status: 409,
          json: {
            detail:
              "Model source rejected before compile\n- Protected value does not match Design Specification: expected 81, detected 90 (line 12)",
          },
        });
      }
      const next =
        generatedCandidateCount === 1
          ? revision({
              id: "rev-warning",
              parent_revision_id: "rev-active",
              design_specification_id: "spec-ready-1",
              revision_number: 2,
              source_type: "ai_revision",
              review_state: "ready_with_warnings",
              validation_summary: { blocking_count: 0, advisory_count: 1, dismissed_count: 0 },
            })
          : revision({
              id: "rev-blocked",
              parent_revision_id: "rev-warning",
              design_specification_id: "spec-ready-2",
              revision_number: 3,
              source_type: "ai_revision",
              review_state: "blocked",
              validation_summary: { blocking_count: 1, advisory_count: 0, dismissed_count: 0 },
            });
      revisions.push(next);
      return route.fulfill({ status: 201, json: next });
    }
    if (request.method() === "GET" && path === "/candidates/rev-warning/findings") {
      return route.fulfill({
        json: [
          finding({
            id: "finding-source-warning",
            rule_id: "source_parameterization.missing_assertions",
            severity: "warning",
            is_blocking: false,
          }),
          finding({
            id: "finding-warning",
            rule_id: "mesh.disconnected_components",
            severity: "warning",
            is_blocking: false,
          }),
        ],
      });
    }
    if (request.method() === "GET" && path === "/candidates/rev-warning/geometric-analysis") {
      return route.fulfill({
        json: geometricAnalysis("rev-warning", [
          geometricFinding({
            rule_id: "geometry.protected_hole_spacing",
            verification_state: "verified",
            expected_value: 50,
            detected_value: 49.95,
            tolerance: 0.25,
            confidence: 0.97,
            severity: "notice",
            is_blocking: false,
            title: "Hole spacing",
            explanation: "Detected protected hole spacing matches the Design Specification.",
            suggested_correction: "No correction is needed.",
          }),
        ]),
      });
    }
    if (request.method() === "GET" && path === "/candidates/rev-blocked/findings") {
      return route.fulfill({
        json: [
          finding({
            id: "finding-hole-spacing",
            rule_id: "geometry.protected_hole_spacing",
            category: "geometry",
            severity: "critical",
            is_blocking: true,
          }),
        ],
      });
    }
    if (request.method() === "GET" && path === "/candidates/rev-blocked/geometric-analysis") {
      return route.fulfill({
        json: geometricAnalysis("rev-blocked", [
          geometricFinding({
            validation_finding_id: "finding-hole-spacing",
            rule_id: "geometry.protected_hole_spacing",
            verification_state: "violated",
            expected_value: 50,
            detected_value: 60,
            tolerance: 0.25,
            confidence: 0.96,
            severity: "critical",
            is_blocking: true,
            title: "Hole spacing",
            explanation: "Detected protected hole spacing differs from the Design Specification.",
            suggested_correction: "Revise the hole centers to match the protected spacing.",
          }),
        ]),
      });
    }
    if (request.method() === "POST" && path === "/candidates/rev-warning/accept") {
      project.active_revision_id = "rev-warning";
      const accepted = revisions.find((entry) => entry.id === "rev-warning")!;
      accepted.is_accepted = true;
      accepted.review_state = "accepted";
      accepted.accepted_at = "2026-07-25T13:00:00Z";
      return route.fulfill({ json: accepted });
    }
    if (request.method() === "POST" && path === "/candidates/rev-blocked/reject") {
      const rejected = revisions.find((entry) => entry.id === "rev-blocked")!;
      rejected.review_state = "rejected";
      rejected.rejected_at = "2026-07-25T13:05:00Z";
      return route.fulfill({ json: rejected });
    }

    return route.fulfill({ status: 404, json: { detail: `unhandled ${request.method()} ${path}` } });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "Projects" }).click();
  await page.getByRole("button", { name: "Candidate Workflow" }).click();
  await expect(page.getByText("Active design - R1 - Accepted revision")).toBeVisible();

  await page.getByLabel("AI chat message").fill("Make this bottle fit on the wall");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByLabel("Requirements").getByText("Waiting for clarification")).toBeVisible();
  await page
    .getByLabel("What is the outside diameter of the container the holder must fit?")
    .fill("81 mm");
  await page.getByRole("button", { name: "Submit answers" }).click();
  await expect(page.getByLabel("Requirements").getByText("Requirements ready")).toBeVisible();
  await expect(page.getByText("Container diameter: 81 mm (clarification)")).toBeVisible();
  await expect(page.getByText("Use a 3 mm wall thickness")).toBeVisible();
  await page.getByRole("button", { name: "Create Design Plan" }).click();
  await expect(page.getByLabel("Design Plan").getByText("Plan review")).toBeVisible();
  await expect(page.getByText("Container holder body (holder_body)")).toBeVisible();
  await page.getByRole("button", { name: "Approve plan" }).click();
  await expect(page.getByLabel("Design Plan").getByText("Plan approved")).toBeVisible();
  await page.getByRole("button", { name: "Continue to generation" }).click();
  await expect(page.getByText("Candidate - R2 - Ready with warnings")).toBeVisible();
  await expect(page.getByText("Source checks")).toBeVisible();
  await expect(
    page.getByLabel("Candidate review").getByText("source_parameterization.missing_assertions", { exact: true }).first(),
  ).toBeVisible();
  await expect(page.getByText("Geometric checks")).toBeVisible();
  await expect(page.getByText("1 verified, 0 violated, 0 unable to verify")).toBeVisible();
  await expect(page.getByText("Advisory warnings")).toBeVisible();
  await expect(page.getByText("mesh.disconnected_components", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Accept", exact: true })).toBeEnabled();
  await expect(page.getByText("R1 active")).toBeVisible();

  await page.getByRole("button", { name: "Accept", exact: true }).click();
  await expect(page.getByText("Active design - R2 - Accepted revision")).toBeVisible();

  await page.getByLabel("AI chat message").fill("Generate a blocked candidate");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByLabel("Requirements").getByText("Requirements ready")).toBeVisible();
  await page.getByRole("button", { name: "Create Design Plan" }).click();
  await expect(page.getByLabel("Design Plan").getByText("Plan review")).toBeVisible();
  await page.getByRole("button", { name: "Approve plan" }).click();
  await page.getByRole("button", { name: "Continue to generation" }).click();
  await expect(page.getByText("Candidate - R3 - Blocked candidate")).toBeVisible();
  await expect(page.getByText("Source checks")).toBeVisible();
  await expect(page.getByText("Passed required structure and protected dimensions")).toBeVisible();
  await expect(page.getByText("0 verified, 1 violated, 0 unable to verify")).toBeVisible();
  await expect(page.getByText("geometry.protected_hole_spacing", { exact: true })).toBeVisible();
  await expect(page.getByText("Expected 50 mm. Detected 60 mm. Tolerance 0.25 mm. Confidence 96%.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Accept", exact: true })).toBeDisabled();
  await expect(page.getByText("Resolve 1 blocking finding with a new revision before accepting.")).toBeVisible();
  await page.getByRole("button", { name: "Revise from finding" }).click();
  await expect(page.getByLabel("AI chat message")).toHaveValue(/finding-hole-spacing/);

  await page.getByLabel("Candidate review").getByRole("button", { name: "Reject" }).click();
  await expect(page.getByText("Historical revision - R3 - Rejected candidate")).toBeVisible();
  await expect(page.getByText("R2 active")).toBeVisible();

  await page.getByLabel("AI chat message").fill("Generate source with mismatched protected diameter");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByLabel("Requirements").getByText("Requirements ready")).toBeVisible();
  await page.getByRole("button", { name: "Create Design Plan" }).click();
  await expect(page.getByLabel("Design Plan").getByText("Plan review")).toBeVisible();
  await page.getByRole("button", { name: "Approve plan" }).click();
  await page.getByRole("button", { name: "Continue to generation" }).click();
  await expect(page.getByLabel("Source checks").getByText("Rejected", { exact: true })).toBeVisible();
  await expect(page.getByText("Protected value does not match Design Specification")).toBeVisible();
  await expect(page.getByText("R2 active")).toBeVisible();
});

function revision(overrides: Partial<Revision>): Revision {
  return {
    id: "revision",
    parent_revision_id: null,
    design_specification_id: null,
    revision_number: 1,
    source_type: "ai_revision",
    status: "succeeded",
    is_accepted: false,
    review_state: "ready",
    accepted_at: null,
    rejected_at: null,
    user_instruction: "Generated",
    stl_path: "model.stl",
    ai_output_path: null,
    created_at: "2026-07-25T13:00:00Z",
    metadata: {
      size_x_mm: 10,
      size_y_mm: 10,
      size_z_mm: 10,
      volume_mm3: 1000,
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

function clarificationSpec() {
  return {
    ...readySpec("spec-clarify"),
    outcome: "clarification_required",
    generation_ready: false,
    clarification_required: true,
    specification: {
      purpose: "Hold a container on a wall",
      critical_dimensions: [],
      functional_requirements: [],
      assumptions: [],
      missing_requirements: [
        {
          id: "container_diameter",
          label: "Container diameter",
          reason: "The holder opening depends on the container size.",
        },
      ],
      conflicts: [],
    },
    clarification_questions: [
      {
        id: "question-container-diameter",
        project_id: "project-1",
        design_specification_id: "spec-clarify",
        requirement_id: "container_diameter",
        question: "What is the outside diameter of the container the holder must fit?",
        reason: "The holder opening depends on the container size.",
        display_order: 0,
        created_at: "2026-07-25T13:00:00Z",
      },
    ],
  };
}

function readySpec(id: string) {
  return {
    id,
    project_id: "project-1",
    generation_attempt_id: `attempt-${id}`,
    superseded_specification_id: id === "spec-ready-1" ? "spec-clarify" : null,
    version_number: id === "spec-clarify" ? 1 : 2,
    schema_version: "1.0",
    prompt_template_version: "requirements-v1",
    gemini_ruleset_version: "gemini-ruleset-v1",
    provider: "fake",
    provider_model: "fake-model",
    user_instruction: "Make this bottle fit on the wall",
    raw_response_path: null,
    specification_path: `projects/project-1/generation-runs/attempt-${id}/parsed-design-spec.json`,
    content_hash: `hash-${id}`,
    outcome: "generation_ready",
    supported_scope: true,
    clarification_required: false,
    generation_ready: true,
    created_at: "2026-07-25T13:00:00Z",
    specification: {
      purpose: "Hold an 81 mm container on a vertical wall",
      critical_dimensions: [
        {
          id: "container_diameter",
          label: "Container diameter",
          value: 81,
          unit: "mm",
          source: "clarification",
          importance: "critical",
          protected: true,
        },
      ],
      functional_requirements: [
        {
          id: "mounting_method",
          description: "Mount to a vertical wall",
          source: "user",
          importance: "critical",
          protected: true,
        },
      ],
      assumptions: [
        {
          id: "default_wall",
          description: "Use a 3 mm wall thickness",
          source: "product_default",
          requires_approval: false,
        },
      ],
      print_requirements: {
        printer_profile_id: "default-fdm-256",
        nozzle_diameter_mm: 0.4,
        layer_height_mm: 0.2,
      },
      conflicts: [],
      missing_requirements: [],
    },
    clarification_questions: [],
  };
}

function designPlan(id: string, specificationId: string) {
  return {
    id,
    project_id: "project-1",
    design_specification_id: specificationId,
    generation_attempt_id: `attempt-${id}`,
    superseded_design_plan_id: null,
    version_number: Number(id.replace("plan-", "")),
    schema_version: "1.0",
    prompt_template_version: "design-plan-v1",
    gemini_ruleset_version: "gemini-ruleset-v1",
    provider: "fake",
    provider_model: "fake-model",
    raw_response_path: null,
    plan_path: `projects/project-1/generation-runs/attempt-${id}/parsed-design-plan.json`,
    content_hash: `hash-${id}`,
    outcome: "plan_ready",
    review_state: "pending_review",
    clarification_required: false,
    plan_ready: true,
    approved_at: null,
    rejected_at: null,
    created_at: "2026-07-25T13:01:00Z",
    plan: {
      schema_version: "1.0",
      design_level: "product",
      product_type: "wall_mounted_cylindrical_holder",
      purpose: "Hold an 81 mm container on a vertical wall",
      units: "mm",
      parameters: [
        {
          id: "container_diameter",
          label: "Container diameter",
          value: 81,
          unit: "mm",
          editable: true,
          protected: true,
          component_id: "holder_body",
        },
        {
          id: "wall_thickness",
          label: "Wall thickness",
          value: 3,
          unit: "mm",
          editable: true,
          protected: false,
          component_id: "holder_body",
        },
      ],
      derived_parameters: [
        {
          id: "holder_inside_diameter",
          label: "Holder inside diameter",
          expression: "container_diameter + 1.0",
          depends_on: ["container_diameter"],
        },
      ],
      dependency_edges: [
        {
          from: "container_diameter",
          to: "holder_inside_diameter",
          relationship: "container size controls holder opening",
        },
      ],
      components: [
        {
          id: "holder_body",
          label: "Container holder body",
          description: "Single printable wall holder",
          features: ["mounting_holes", "retention_lip"],
          parameters: ["container_diameter", "wall_thickness"],
        },
      ],
      features: [
        {
          id: "mounting_holes",
          component_id: "holder_body",
          type: "hole_group",
          description: "Two wall mounting holes",
          parameters: ["mount_hole_spacing"],
          protected: true,
        },
        {
          id: "retention_lip",
          component_id: "holder_body",
          type: "retention",
          description: "Front lip prevents container sliding out",
          parameters: ["wall_thickness"],
          protected: false,
        },
      ],
      presets: [],
      assembly_strategy: {
        type: "single_part",
        instructions: ["Print with the wall face on the build plate."],
      },
      printable_outputs: [
        {
          id: "holder_body_output",
          label: "Holder body",
          component_ids: ["holder_body"],
          quantity: 1,
          orientation: "wall face on Z=0",
        },
      ],
      risks: [
        {
          id: "support_access",
          severity: "warning",
          description: "Deep holder geometry may need local support depending on lip shape.",
          mitigation: "Keep the lip shallow and chamfered.",
        },
      ],
      clarification_required: false,
      clarification_questions: [],
      plan_ready: true,
      outcome: "plan_ready",
    },
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

function geometricAnalysis(revisionId: string, findings: ReturnType<typeof geometricFinding>[]) {
  return {
    id: `analysis-${revisionId}`,
    revision_id: revisionId,
    design_specification_id: "spec-ready-1",
    analysis_version: "geometric-invariants-v1",
    tolerance_profile_version: "geometry-tolerance-v1",
    mesh_hash: `mesh-${revisionId}`,
    source_hash: `source-${revisionId}`,
    analysis_ms: 12.5,
    created_at: "2026-07-25T13:00:00Z",
    findings,
  };
}

function geometricFinding(overrides: {
  validation_finding_id?: string | null;
  rule_id: string;
  verification_state: "verified" | "violated" | "unverifiable" | "not_applicable";
  expected_value: number | string | null;
  detected_value: number | string | null;
  tolerance: number | null;
  confidence: number;
  severity: "notice" | "warning" | "critical";
  is_blocking: boolean;
  title: string;
  explanation: string;
  suggested_correction: string;
}) {
  return {
    validation_finding_id: null,
    requirement_id: "mount_hole_spacing",
    unit: "mm",
    feature_id: "mounting_holes",
    metadata: {},
    ...overrides,
  };
}
