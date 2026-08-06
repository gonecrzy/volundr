import type { ValidatedWorkflow } from "./validatedCadQueryWorkflow";

export const TERMINAL_VALIDATED_WORKFLOW_STATES = new Set<ValidatedWorkflow["state"]>([
  "candidate_ready",
  "revision_ready",
  "partially_completed",
  "verification_failed",
  "failed",
]);

type TimerHandle = ReturnType<typeof setTimeout>;

type WorkflowPollerOptions<TWorkflow extends { state: string }> = {
  workflowId: string;
  fetchWorkflow: (workflowId: string) => Promise<TWorkflow>;
  onWorkflow: (workflow: TWorkflow) => void;
  onError?: (error: unknown) => void;
  baseDelayMs?: number;
  maxDelayMs?: number;
  isDocumentHidden?: () => boolean;
  setTimeoutFn?: typeof setTimeout;
  clearTimeoutFn?: typeof clearTimeout;
};

export function createWorkflowPoller<TWorkflow extends { state: string }>(options: WorkflowPollerOptions<TWorkflow>) {
  const setTimer = options.setTimeoutFn ?? setTimeout;
  const clearTimer = options.clearTimeoutFn ?? clearTimeout;
  const baseDelayMs = options.baseDelayMs ?? 3000;
  const maxDelayMs = options.maxDelayMs ?? 30_000;
  const hidden = options.isDocumentHidden ?? (() => false);
  let workflowId = options.workflowId;
  let running = false;
  let inFlight = false;
  let refreshQueued = false;
  let timer: TimerHandle | null = null;
  let generation = 0;
  let delayMs = baseDelayMs;

  function clearScheduledTimer() {
    if (timer !== null) {
      clearTimer(timer);
      timer = null;
    }
  }

  function schedule(delay: number) {
    if (!running || hidden() || timer !== null || inFlight) return;
    timer = setTimer(() => {
      timer = null;
      void load();
    }, delay);
  }

  async function load() {
    if (!running || hidden() || inFlight || !workflowId) return;
    const requestGeneration = generation;
    const requestWorkflowId = workflowId;
    inFlight = true;
    try {
      const next = await options.fetchWorkflow(requestWorkflowId);
      if (!running || requestGeneration !== generation || requestWorkflowId !== workflowId) return;
      options.onWorkflow(next);
      delayMs = baseDelayMs;
      if (TERMINAL_VALIDATED_WORKFLOW_STATES.has(next.state as ValidatedWorkflow["state"])) {
        running = false;
        clearScheduledTimer();
      } else if (refreshQueued) {
        refreshQueued = false;
        queueMicrotask(() => void load());
      } else {
        schedule(delayMs);
      }
    } catch (error) {
      if (running && requestGeneration === generation && requestWorkflowId === workflowId) {
        options.onError?.(error);
        delayMs = Math.min(maxDelayMs, Math.max(baseDelayMs, delayMs * 2));
        schedule(delayMs);
      }
    } finally {
      inFlight = false;
      if (refreshQueued && running && !hidden()) {
        refreshQueued = false;
        queueMicrotask(() => void load());
      }
    }
  }

  return {
    start() {
      if (running) return;
      running = true;
      delayMs = baseDelayMs;
      void load();
    },
    stop() {
      running = false;
      generation += 1;
      refreshQueued = false;
      clearScheduledTimer();
    },
    refresh() {
      if (!running || hidden()) return;
      clearScheduledTimer();
      if (inFlight) {
        refreshQueued = true;
        return;
      }
      void load();
    },
    setWorkflowId(nextWorkflowId: string) {
      if (nextWorkflowId === workflowId) return;
      workflowId = nextWorkflowId;
      generation += 1;
      clearScheduledTimer();
      refreshQueued = inFlight;
      if (running && !hidden() && !inFlight) void load();
    },
    setDocumentHidden(isHidden: boolean) {
      if (!running) return;
      if (isHidden) {
        clearScheduledTimer();
        return;
      }
      if (!inFlight) {
        clearScheduledTimer();
        void load();
      }
    },
  };
}
