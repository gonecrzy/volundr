export type SaveStatus = "idle" | "saving" | "saved" | "failed" | "offline";

export function projectPath(projectId: string): string {
  return `/projects/${encodeURIComponent(projectId)}`;
}

export function projectIdFromPath(pathname: string): string | null {
  const match = pathname.match(/^\/projects\/([^/]+)(?:\/versions\/[^/]+)?\/?$/);
  return match ? decodeURIComponent(match[1]) : null;
}

export function saveStatusLabel(status: SaveStatus): string {
  switch (status) {
    case "saving":
      return "Saving…";
    case "saved":
      return "Saved";
    case "failed":
      return "Save failed";
    case "offline":
      return "Disconnected";
    default:
      return "";
  }
}

export function planHasExposedControls(
  plan: { exposed_controls?: unknown; parameters?: Array<{ editable?: boolean }> } | null | undefined,
): boolean {
  if (Array.isArray(plan?.exposed_controls)) {
    return plan.exposed_controls.length > 0;
  }
  // Staged fixtures and legacy plans predate the explicit exposed_controls
  // field; retain their editable-parameter contract during the transition.
  return Boolean(plan?.parameters?.some((parameter) => parameter.editable === true));
}

export function shouldLoadCompileLog(revision: { status: string; stl_path?: string | null }): boolean {
  return revision.status === "succeeded" || Boolean(revision.stl_path);
}
