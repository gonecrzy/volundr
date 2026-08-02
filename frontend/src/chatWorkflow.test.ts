import { describe, expect, it } from "vitest";
import { applyChatClarificationAnswer, nextChatWorkflowAction } from "./chatWorkflow";

const questions = [
  { id: "tray_count", question: "How many trays?" },
  { id: "opening_style", question: "Top-loading or front-loading?" },
];

describe("chat workflow helpers", () => {
  it("records a chat message as the next unanswered clarification answer", () => {
    const result = applyChatClarificationAnswer(questions, {}, "5 trays");

    expect(result.answers).toEqual({ tray_count: "5 trays" });
    expect(result.answeredQuestionId).toBe("tray_count");
    expect(result.nextQuestionId).toBe("opening_style");
    expect(result.readyToSubmit).toBe(false);
  });

  it("preserves previous clarification answers and reports ready when complete", () => {
    const result = applyChatClarificationAnswer(
      questions,
      { tray_count: "5 trays" },
      "top loading",
    );

    expect(result.answers).toEqual({
      tray_count: "5 trays",
      opening_style: "top loading",
    });
    expect(result.answeredQuestionId).toBe("opening_style");
    expect(result.nextQuestionId).toBeNull();
    expect(result.readyToSubmit).toBe(true);
  });

  it("ignores blank chat clarification messages", () => {
    const result = applyChatClarificationAnswer(questions, {}, "   ");

    expect(result.answers).toEqual({});
    expect(result.answeredQuestionId).toBeNull();
    expect(result.nextQuestionId).toBe("tray_count");
    expect(result.readyToSubmit).toBe(false);
  });

  it("sends normal follow-up prompts to generation in simple mode", () => {
    expect(
      nextChatWorkflowAction({
        advancedWorkflowEnabled: false,
        hasRequirementClarificationPending: false,
        hasDesignPlanClarificationPending: false,
        hasRevisionPlanClarificationPending: false,
        canPlanRevisionFromCurrentContext: true,
      }),
    ).toBe("generate");
  });

  it("routes follow-up prompts to revision planning only in advanced mode", () => {
    expect(
      nextChatWorkflowAction({
        advancedWorkflowEnabled: true,
        hasRequirementClarificationPending: false,
        hasDesignPlanClarificationPending: false,
        hasRevisionPlanClarificationPending: false,
        canPlanRevisionFromCurrentContext: true,
      }),
    ).toBe("plan_revision");
  });
});
