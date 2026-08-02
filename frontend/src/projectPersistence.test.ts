import { describe, expect, it } from "vitest";
import { projectPath, projectIdFromPath, saveStatusLabel, type SaveStatus } from "./projectPersistence";

describe("project persistence presentation", () => {
  it("maps project IDs to stable workspace URLs and back", () => {
    expect(projectPath("project-123")).toBe("/projects/project-123");
    expect(projectIdFromPath("/projects/project-123")).toBe("project-123");
    expect(projectIdFromPath("/projects/project-123/versions/revision-4")).toBe("project-123");
    expect(projectIdFromPath("/")).toBeNull();
  });

  it.each<[SaveStatus, string]>([
    ["saving", "Saving…"],
    ["saved", "Saved"],
    ["failed", "Save failed"],
    ["offline", "Disconnected"],
    ["idle", ""],
  ])("labels %s from backend save state", (status, label) => {
    expect(saveStatusLabel(status)).toBe(label);
  });
});
