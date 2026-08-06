import { describe, expect, it } from "vitest";
import {
  createValidatedWorkflowApi,
  outputStateLabel,
  workflowStageLabel,
  workflowSummary,
} from "./validatedCadQueryWorkflow";

describe("validated CadQuery workflow presentation", () => {
  it("uses product language for workflow stages", () => {
    expect(workflowStageLabel("worker_running")).toBe("Building your design");
    expect(workflowStageLabel("revision_ready")).toBe("Revision ready to review");
    expect(workflowStageLabel("failed")).toBe("Action needed");
  });

  it("explains partial completion without hiding completed siblings", () => {
    expect(outputStateLabel("completed")).toBe("Ready");
    expect(outputStateLabel("worker_timeout")).toBe("Could not finish building");
    expect(
      workflowSummary({
        state: "partially_completed",
        outputs: [
          { output_id: "body", state: "completed" },
          { output_id: "lid", state: "worker_timeout" },
        ],
      }),
    ).toBe("One or more parts are ready; another part needs attention.");
  });

  it("keeps workflow requests in the typed API layer with actor and idempotency headers", async () => {
    const calls: Array<{ url: string; init?: RequestInit }> = [];
    const fetcher = async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ url: String(input), init });
      return new Response(JSON.stringify({ id: "workflow-1", project_id: "project-1", outputs: [] }), { status: 200 });
    };
    const api = createValidatedWorkflowApi("/api", fetcher);

    await api.startDesign("Design", "Intent", "request-1");
    await api.getWorkflow("workflow-1", "project-1");

    expect(calls[0].url).toBe("/api/validated-cadquery/designs");
    expect((calls[0].init?.headers as Record<string, string>)["X-Volundr-Actor-Id"]).toBeUndefined();
    expect((calls[0].init?.headers as Record<string, string>)["Idempotency-Key"]).toBe("request-1");
    expect(calls[1].url).toBe("/api/validated-cadquery/projects/project-1/designs/workflow-1");
  });
});
