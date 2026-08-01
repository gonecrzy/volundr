import { describe, expect, it } from "vitest";
import {
  classifyProjectMessage,
  layoutModeForWidth,
  userFacingSubmissionError,
  canExportRevision,
  type WorkspaceRevisionLike,
} from "./chatWorkspace";

describe("chat workspace presentation", () => {
  it("classifies persisted messages without exposing internal system events", () => {
    expect(
      classifyProjectMessage({ role: "user", content: "Make a bracket", revision_id: null }),
    ).toBe("user");
    expect(
      classifyProjectMessage({ role: "assistant_clarification", content: "What size?", revision_id: null }),
    ).toBe("clarification");
    expect(
      classifyProjectMessage({ role: "assistant_progress", content: "Creating the model", revision_id: null }),
    ).toBe("progress");
    expect(
      classifyProjectMessage({ role: "system_event", content: "Revision R1 succeeded", revision_id: "r1" }),
    ).toBe("hidden");
  });

  it.each([
    [1920, "desktop"],
    [1280, "desktop"],
    [1279, "drawer"],
    [1000, "drawer"],
    [999, "tabs"],
    [390, "tabs"],
  ] as const)("uses the required responsive mode at %s px", (width, expected) => {
    expect(layoutModeForWidth(width)).toBe(expected);
  });

  it("maps connection failures to recoverable user-facing copy", () => {
    expect(userFacingSubmissionError(new TypeError("Failed to fetch"))).toEqual({
      title: "Could not connect to Volundr",
      body: "Your message was not lost. Check the connection and try again.",
      action: "Retry",
    });
  });

  it("does not expose raw server diagnostics in normal chat", () => {
    const result = userFacingSubmissionError(new Error("HTTP 500: stack trace"));
    expect(result.body).not.toContain("HTTP 500");
    expect(result.body).not.toContain("stack trace");
  });

  it("only enables export for successful selected revisions", () => {
    const revision: WorkspaceRevisionLike = { review_state: "accepted", status: "succeeded", is_accepted: true };
    expect(canExportRevision(revision)).toBe(true);
    expect(canExportRevision({ review_state: "blocked", status: "failed", is_accepted: false })).toBe(false);
    expect(canExportRevision(null)).toBe(false);
  });
});
