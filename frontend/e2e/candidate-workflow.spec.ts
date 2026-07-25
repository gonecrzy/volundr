import { expect, test } from "@playwright/test";

type Revision = {
  id: string;
  parent_revision_id: string | null;
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
  let generateCount = 0;

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
    if (request.method() === "POST" && path === "/projects/project-1/generate") {
      generateCount += 1;
      const next =
        generateCount === 1
          ? revision({
              id: "rev-warning",
              parent_revision_id: "rev-active",
              revision_number: 2,
              source_type: "ai_revision",
              review_state: "ready_with_warnings",
              validation_summary: { blocking_count: 0, advisory_count: 1, dismissed_count: 0 },
            })
          : revision({
              id: "rev-blocked",
              parent_revision_id: "rev-warning",
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

  await page.getByLabel("AI chat message").fill("Generate a warned candidate");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByText("Candidate - R2 - Ready with warnings")).toBeVisible();
  await expect(page.getByText("Advisory warnings")).toBeVisible();
  await expect(page.getByText("mesh.disconnected_components", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Accept", exact: true })).toBeEnabled();
  await expect(page.getByText("R1 active")).toBeVisible();

  await page.getByRole("button", { name: "Accept", exact: true }).click();
  await expect(page.getByText("Active design - R2 - Accepted revision")).toBeVisible();

  await page.getByLabel("AI chat message").fill("Generate a blocked candidate");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByText("Candidate - R3 - Blocked candidate")).toBeVisible();
  await expect(page.getByText("Blocking findings")).toBeVisible();
  await expect(page.getByText("profile.build_volume", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Accept", exact: true })).toBeDisabled();
  await expect(page.getByText("Resolve 1 blocking finding with a new revision before accepting.")).toBeVisible();

  await page.getByRole("button", { name: "Reject" }).click();
  await expect(page.getByText("Historical revision - R3 - Rejected candidate")).toBeVisible();
  await expect(page.getByText("R2 active")).toBeVisible();
});

function revision(overrides: Partial<Revision>): Revision {
  return {
    id: "revision",
    parent_revision_id: null,
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
