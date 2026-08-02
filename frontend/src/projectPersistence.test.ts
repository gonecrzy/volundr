import { describe, expect, it } from "vitest";
import {
  planHasExposedControls,
  projectPath,
  projectIdFromPath,
  saveStatusLabel,
  shouldLoadCompileLog,
  type SaveStatus,
} from "./projectPersistence";

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

  it("loads configuration only when a plan exposes controls", () => {
    expect(planHasExposedControls({ exposed_controls: [] })).toBe(false);
    expect(planHasExposedControls({ exposed_controls: [{ parameter_id: "thickness" }] })).toBe(true);
    expect(planHasExposedControls({ parameters: [{ editable: true }] })).toBe(true);
    expect(planHasExposedControls(null)).toBe(false);
  });

  it("does not request compile logs for pre-worker blocked revisions", () => {
    expect(shouldLoadCompileLog({ status: "blocked", stl_path: null })).toBe(false);
    expect(shouldLoadCompileLog({ status: "succeeded", stl_path: "model.stl" })).toBe(true);
  });
});
