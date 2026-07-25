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
    if (request.method() === "POST" && path.startsWith("/design-specifications/spec-ready-")) {
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
    if (request.method() === "GET" && path === "/candidates/rev-blocked/findings") {
      return route.fulfill({
        json: [
          finding({
            id: "finding-blocked",
            rule_id: "profile.build_volume",
            severity: "critical",
            is_blocking: true,
          }),
        ],
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
  await page.getByRole("button", { name: "Continue to generation" }).click();
  await expect(page.getByText("Candidate - R2 - Ready with warnings")).toBeVisible();
  await expect(page.getByText("Source checks")).toBeVisible();
  await expect(
    page.getByLabel("Candidate review").getByText("source_parameterization.missing_assertions", { exact: true }).first(),
  ).toBeVisible();
  await expect(page.getByText("Advisory warnings")).toBeVisible();
  await expect(page.getByText("mesh.disconnected_components", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Accept", exact: true })).toBeEnabled();
  await expect(page.getByText("R1 active")).toBeVisible();

  await page.getByRole("button", { name: "Accept", exact: true }).click();
  await expect(page.getByText("Active design - R2 - Accepted revision")).toBeVisible();

  await page.getByLabel("AI chat message").fill("Generate a blocked candidate");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByLabel("Requirements").getByText("Requirements ready")).toBeVisible();
  await page.getByRole("button", { name: "Continue to generation" }).click();
  await expect(page.getByText("Candidate - R3 - Blocked candidate")).toBeVisible();
  await expect(page.getByText("Blocking findings")).toBeVisible();
  await expect(page.getByText("profile.build_volume", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Accept", exact: true })).toBeDisabled();
  await expect(page.getByText("Resolve 1 blocking finding with a new revision before accepting.")).toBeVisible();

  await page.getByRole("button", { name: "Reject" }).click();
  await expect(page.getByText("Historical revision - R3 - Rejected candidate")).toBeVisible();
  await expect(page.getByText("R2 active")).toBeVisible();

  await page.getByLabel("AI chat message").fill("Generate source with mismatched protected diameter");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByLabel("Requirements").getByText("Requirements ready")).toBeVisible();
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

function finding(overrides: {
  id: string;
  rule_id: string;
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
