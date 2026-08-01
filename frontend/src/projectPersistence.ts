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
      return "Save failed — retrying";
    case "offline":
      return "Offline or server unavailable";
    default:
      return "";
  }
}
