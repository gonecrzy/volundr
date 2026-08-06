export type ValidatedWorkflowState =
  | "awaiting_clarification"
  | "requirements_ready"
  | "plan_ready"
  | "geometry_generating"
  | "worker_running"
  | "partially_completed"
  | "verification_failed"
  | "candidate_ready"
  | "revision_ready"
  | "failed";

export type ValidatedOutputState =
  | "pending"
  | "completed"
  | "invalid_shape"
  | "semantic_verification_failed"
  | "worker_timeout"
  | "export_failed"
  | "not_generated"
  | "blocked_by_upstream_failure";

export type ValidatedWorkflowOutput = {
  output_id: string;
  state: ValidatedOutputState;
  required?: boolean;
  artifact_available?: boolean;
  solid_count?: number | null;
  topology_status?: string | null;
  semantic_verification?: string | null;
  safe_diagnostic?: string | null;
};

export type ValidatedCandidatePolicy = {
  state?: "candidate_blocked" | "candidate_ready_for_review" | "candidate_fully_verified";
  blockers?: string[];
  review_obligations?: string[];
  eligible_for_review?: boolean;
  fully_verified?: boolean;
};

export type ValidatedWorkflow = {
  id: string;
  project_id: string;
  state: ValidatedWorkflowState;
  revision_id?: string | null;
  parent_workflow_id?: string | null;
  parent_revision_id?: string | null;
  requirements: Record<string, unknown>;
  plan: Record<string, unknown>;
  verification: Record<string, unknown>;
  candidate_policy: ValidatedCandidatePolicy;
  diagnostics: Record<string, unknown>;
  package_available: boolean;
  package_manifest: Record<string, unknown>;
  outputs: ValidatedWorkflowOutput[];
  user_instruction?: string;
  route?: string;
  provenance?: Record<string, unknown>;
  created_at?: string;
  updated_at?: string;
};

export type ValidatedWorkflowArtifact = {
  artifact_id: string;
  kind: string;
  output_id?: string | null;
  filename: string;
  media_type: string;
  size_bytes: number;
  sha256: string;
  available: boolean;
  download_url?: string | null;
};

export type ValidatedRequestAction = "start_design" | "clarification" | "acceptance" | "revision" | "package";

type RequestIdentityStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">;
type PendingRequestPayload = Record<string, unknown>;

export class ValidatedWorkflowRequestError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ValidatedWorkflowRequestError";
    this.status = status;
  }
}

export function isDefinitiveValidatedRequestError(reason: unknown): boolean {
  return reason instanceof ValidatedWorkflowRequestError && reason.status >= 400 && reason.status < 500;
}

function defaultRequestIdentity(): string {
  if (typeof globalThis.crypto?.randomUUID === "function") {
    return globalThis.crypto.randomUUID();
  }
  const bytes = new Uint8Array(16);
  if (typeof globalThis.crypto?.getRandomValues === "function") {
    globalThis.crypto.getRandomValues(bytes);
  } else {
    for (let index = 0; index < bytes.length; index += 1) {
      bytes[index] = Math.floor(Math.random() * 256);
    }
  }
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  return [...bytes].map((byte, index) => `${byte.toString(16).padStart(2, "0")}${[3, 5, 7, 9].includes(index) ? "-" : ""}`).join("");
}

export function createValidatedRequestIdentityStore(
  storage: RequestIdentityStorage | null = typeof window !== "undefined" ? window.sessionStorage : null,
  identityFactory: () => string = defaultRequestIdentity,
) {
  const keyFor = (action: ValidatedRequestAction, scope: string) => `volundr:validated-request:${action}:${scope}`;
  const pendingKeyFor = (action: ValidatedRequestAction, scope: string) => `${keyFor(action, scope)}:pending`;
  return {
    getOrCreate(action: ValidatedRequestAction, scope: string): string {
      const storageKey = keyFor(action, scope);
      const existing = storage?.getItem(storageKey);
      if (existing) return existing;
      const identity = identityFactory();
      storage?.setItem(storageKey, identity);
      return identity;
    },
    clear(action: ValidatedRequestAction, scope: string): void {
      storage?.removeItem(keyFor(action, scope));
      storage?.removeItem(pendingKeyFor(action, scope));
    },
    setPending(action: ValidatedRequestAction, scope: string, payload: PendingRequestPayload): void {
      storage?.setItem(pendingKeyFor(action, scope), JSON.stringify(payload));
    },
    getPending<T extends PendingRequestPayload>(action: ValidatedRequestAction, scope: string): T | null {
      const serialized = storage?.getItem(pendingKeyFor(action, scope));
      if (!serialized) return null;
      try {
        const parsed = JSON.parse(serialized);
        return parsed && typeof parsed === "object" ? parsed as T : null;
      } catch {
        return null;
      }
    },
  };
}

export function createValidatedWorkflowApi(
  apiBase: string,
  fetcher: typeof fetch = fetch,
) {
  async function request<T>(path: string, init?: RequestInit): Promise<T> {
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (init?.headers) {
      Object.entries(init.headers).forEach(([key, value]) => {
        if (typeof value === "string") headers[key] = value;
      });
    }
    const response = await fetcher(`${apiBase}${path}`, { ...init, headers });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new ValidatedWorkflowRequestError(
        typeof body.detail === "string" ? body.detail : "The design workflow could not be completed.",
        response.status,
      );
    }
    return response.json() as Promise<T>;
  }

  return {
    getWorkflow(workflowId: string, projectId?: string) {
      const path = projectId
        ? `/validated-cadquery/projects/${encodeURIComponent(projectId)}/designs/${encodeURIComponent(workflowId)}`
        : `/validated-cadquery/workflows/${encodeURIComponent(workflowId)}`;
      return request<ValidatedWorkflow>(path);
    },
    listArtifacts(workflowId: string, projectId?: string) {
      const path = projectId
        ? `/validated-cadquery/projects/${encodeURIComponent(projectId)}/designs/${encodeURIComponent(workflowId)}/artifacts`
        : `/validated-cadquery/workflows/${encodeURIComponent(workflowId)}/artifacts`;
      return request<ValidatedWorkflowArtifact[]>(path);
    },
    startDesign(name: string, intent: string, idempotencyKey = defaultRequestIdentity()) {
      return request<ValidatedWorkflow>("/validated-cadquery/designs", {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey },
        body: JSON.stringify({ name, intent }),
      });
    },
    submitClarification(workflowId: string, questionId: string, answer: string, idempotencyKey = defaultRequestIdentity()) {
      return request<ValidatedWorkflow>(`/validated-cadquery/workflows/${encodeURIComponent(workflowId)}/clarification`, {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey },
        body: JSON.stringify({ answers: [{ question_id: questionId, answer }] }),
      });
    },
    acceptCandidate(workflowId: string, idempotencyKey = defaultRequestIdentity()) {
      return request<ValidatedWorkflow>(`/validated-cadquery/workflows/${encodeURIComponent(workflowId)}/accept`, {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey },
      });
    },
    startRevision(workflowId: string, body: Record<string, unknown>, idempotencyKey = defaultRequestIdentity()) {
      return request<ValidatedWorkflow>(`/validated-cadquery/workflows/${encodeURIComponent(workflowId)}/revision`, {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey },
        body: JSON.stringify(body),
      });
    },
    createPackage(workflowId: string, idempotencyKey = defaultRequestIdentity()) {
      return request<ValidatedWorkflow>(`/validated-cadquery/workflows/${encodeURIComponent(workflowId)}/package`, {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey },
      });
    },
  };
}

const WORKFLOW_LABELS: Record<ValidatedWorkflowState, string> = {
  awaiting_clarification: "A detail is needed",
  requirements_ready: "Requirements ready",
  plan_ready: "Plan ready",
  geometry_generating: "Preparing your design",
  worker_running: "Building your design",
  partially_completed: "Partially complete",
  verification_failed: "Verification needs attention",
  candidate_ready: "Ready to review",
  revision_ready: "Revision ready to review",
  failed: "Action needed",
};

const OUTPUT_LABELS: Record<ValidatedOutputState, string> = {
  pending: "Waiting to build",
  completed: "Ready",
  invalid_shape: "Shape needs correction",
  semantic_verification_failed: "Does not match the requested design",
  worker_timeout: "Could not finish building",
  export_failed: "Download unavailable",
  not_generated: "Not generated",
  blocked_by_upstream_failure: "Waiting on an earlier step",
};

export function workflowStageLabel(state: ValidatedWorkflowState): string {
  return WORKFLOW_LABELS[state] ?? "In progress";
}

export function outputStateLabel(state: ValidatedOutputState): string {
  return OUTPUT_LABELS[state] ?? "Needs attention";
}

export function workflowSummary(workflow: Pick<ValidatedWorkflow, "state" | "outputs">): string {
  if (workflow.state === "partially_completed") {
    return "One or more parts are ready; another part needs attention.";
  }
  if (workflow.state === "candidate_ready" || workflow.state === "revision_ready") {
    return "Your design passed the available checks and is ready to review.";
  }
  if (workflow.state === "verification_failed") {
    return "The design was built, but one or more checks need attention.";
  }
  if (workflow.state === "failed") {
    return "The workflow could not finish. Review the guidance below.";
  }
  return "Your design is progressing through its checks.";
}
