import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createWorkflowPoller } from "./validatedCadQueryPolling";

describe("validated workflow polling", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("does not overlap requests and stops after a terminal workflow state", async () => {
    let resolveRequest: ((value: { state: string }) => void) | undefined;
    const fetchWorkflow = vi.fn(() => new Promise<{ state: string }>((resolve) => { resolveRequest = resolve; }));
    const onWorkflow = vi.fn();
    const poller = createWorkflowPoller({ workflowId: "workflow-1", fetchWorkflow, onWorkflow, baseDelayMs: 1000 });

    poller.start();
    expect(fetchWorkflow).toHaveBeenCalledTimes(1);
    poller.refresh();
    expect(fetchWorkflow).toHaveBeenCalledTimes(1);
    resolveRequest?.({ state: "candidate_ready" });
    await vi.runAllTicks();
    await vi.advanceTimersByTimeAsync(5000);

    expect(fetchWorkflow).toHaveBeenCalledTimes(1);
    expect(onWorkflow).toHaveBeenCalledWith({ state: "candidate_ready" });
  });

  it("backs off transport failures and refreshes when a hidden tab becomes visible", async () => {
    let hidden = false;
    const fetchWorkflow = vi.fn()
      .mockRejectedValueOnce(new Error("temporary"))
      .mockResolvedValue({ state: "worker_running" });
    const poller = createWorkflowPoller({
      workflowId: "workflow-1",
      fetchWorkflow,
      onWorkflow: vi.fn(),
      baseDelayMs: 1000,
      maxDelayMs: 4000,
      isDocumentHidden: () => hidden,
    });

    poller.start();
    await vi.runAllTicks();
    hidden = true;
    await vi.advanceTimersByTimeAsync(4000);
    expect(fetchWorkflow).toHaveBeenCalledTimes(1);

    hidden = false;
    poller.setDocumentHidden(false);
    await vi.runAllTicks();
    expect(fetchWorkflow).toHaveBeenCalledTimes(2);
  });

  it("ignores a response from a workflow route that was replaced while loading", async () => {
    let resolveFirst: ((value: { state: string }) => void) | undefined;
    const fetchWorkflow = vi.fn((workflowId: string) => workflowId === "old"
      ? new Promise<{ state: string }>((resolve) => { resolveFirst = resolve; })
      : Promise.resolve({ state: "candidate_ready" }));
    const onWorkflow = vi.fn();
    const poller = createWorkflowPoller({ workflowId: "old", fetchWorkflow, onWorkflow, baseDelayMs: 1000 });

    poller.start();
    poller.setWorkflowId("new");
    await Promise.resolve();
    resolveFirst?.({ state: "failed" });
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();

    expect(onWorkflow).toHaveBeenCalledTimes(1);
    expect(onWorkflow).toHaveBeenCalledWith({ state: "candidate_ready" });
  });
});
