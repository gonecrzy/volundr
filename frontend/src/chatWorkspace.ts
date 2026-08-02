export type ChatDisplayKind =
  | "user"
  | "assistant"
  | "clarification"
  | "progress"
  | "success"
  | "blocked"
  | "error"
  | "hidden";

export type WorkspaceMessageLike = {
  role: string;
  content: string;
  revision_id?: string | null;
};

export type WorkspaceRevisionLike = {
  review_state?: string | null;
  status?: string | null;
  is_accepted?: boolean;
};

export type WorkspaceLayoutMode = "desktop" | "drawer" | "tabs";

export type SubmissionErrorPresentation = {
  title: string;
  body: string;
  action: "Retry";
};

export function classifyProjectMessage(message: WorkspaceMessageLike): ChatDisplayKind {
  if (message.role === "system_event") {
    return "hidden";
  }
  if (message.role === "user" || message.role === "user_request" || message.role === "user_revision") {
    return "user";
  }
  if (message.role.includes("clarification")) {
    return "clarification";
  }
  if (message.role.includes("progress")) {
    return "progress";
  }
  if (message.role.includes("success")) {
    return "success";
  }
  if (message.role.includes("blocked")) {
    return "blocked";
  }
  if (message.role.includes("error")) {
    return "error";
  }
  return "assistant";
}

export function layoutModeForWidth(width: number): WorkspaceLayoutMode {
  if (width >= 1280) {
    return "desktop";
  }
  if (width >= 1000) {
    return "drawer";
  }
  return "tabs";
}

export function userFacingSubmissionError(error: unknown): SubmissionErrorPresentation {
  const detail = error instanceof Error ? error.message : String(error ?? "");
  if (/failed to fetch|networkerror|network request|connection/i.test(detail)) {
    return {
      title: "Could not connect to Volundr",
      body: "Your message was not lost. Check the connection and try again.",
      action: "Retry",
    };
  }
  return {
    title: "Message not sent",
    body: "Your message could not be sent. It has not been discarded.",
    action: "Retry",
  };
}

export function canExportRevision(revision: WorkspaceRevisionLike | null): boolean {
  if (!revision) {
    return false;
  }
  return Boolean(
    revision.is_accepted &&
      revision.status === "succeeded" &&
      ["accepted", "ready", "ready_with_warnings"].includes(revision.review_state ?? ""),
  );
}
