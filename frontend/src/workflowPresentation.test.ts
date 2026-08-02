import { describe, expect, it } from "vitest";
import {
  candidateStatusSummary,
  generationProgress,
  recoveryPresentation,
  userWorkflowPhase,
} from "./workflowPresentation";

describe("workflow presentation", () => {
  it("maps internal stages to meaningful generation progress", () => {
    expect(generationProgress("requirement_extraction")).toEqual({
      label: "Understanding requirements",
      complete: false,
    });
    expect(generationProgress("cad_execution")).toEqual({
      label: "Creating the CAD model",
      complete: false,
    });
    expect(generationProgress("printability_validation")).toEqual({
      label: "Reviewing printability",
      complete: true,
    });
  });

  it.each([
    ["requirement_extraction", "understanding"],
    ["compact_plan", "planning"],
    ["cad_execution", "creating"],
    ["snapshot_generation", "checking"],
  ] as const)("maps %s to the %s user phase", (stage, phase) => {
    expect(userWorkflowPhase(stage)).toBe(phase);
  });

  it("uses a neutral phase when the current stage is unavailable", () => {
    expect(userWorkflowPhase("unknown_stage")).toBeNull();
    expect(userWorkflowPhase(null)).toBeNull();
  });

  it("explains a blocked part without treating the candidate as the root problem", () => {
    expect(
      candidateStatusSummary({ total: 3, blockedRequired: 1, ready: 2 }),
    ).toBe("The full design cannot be accepted because one required printable part is blocked.");
  });

  it("uses recovery copy that protects the current design", () => {
    expect(recoveryPresentation("source_contract_validation")).toEqual({
      title: "Volundr could not build the proposed design consistently.",
      currentDesignMessage: "Your current design was not changed.",
      primaryAction: "Try generation again",
      secondaryAction: "Review proposed design",
    });
  });

  it("distinguishes topology recovery from a worker retry", () => {
    expect(recoveryPresentation("topology_validation").title).toContain("separate solid bodies");
    expect(recoveryPresentation("worker_failure")).toEqual({
      title: "Volundr could not finish building this required printable part.",
      currentDesignMessage: "Your current design was not changed.",
      primaryAction: "Retry building this part",
      secondaryAction: "Reject new version",
    });
  });
});
