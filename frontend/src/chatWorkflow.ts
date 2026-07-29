export type ChatClarificationQuestion = {
  id: string;
  question: string;
};

export type ChatClarificationResult = {
  answers: Record<string, string>;
  answeredQuestionId: string | null;
  nextQuestionId: string | null;
  readyToSubmit: boolean;
};

export type ChatWorkflowAction =
  | "answer_requirement_clarification"
  | "answer_design_plan_clarification"
  | "answer_revision_plan_clarification"
  | "plan_revision"
  | "generate";

export type ChatWorkflowState = {
  advancedWorkflowEnabled: boolean;
  hasRequirementClarificationPending: boolean;
  hasDesignPlanClarificationPending: boolean;
  hasRevisionPlanClarificationPending: boolean;
  canPlanRevisionFromCurrentContext: boolean;
};

export function nextChatWorkflowAction(state: ChatWorkflowState): ChatWorkflowAction {
  if (state.hasRequirementClarificationPending) {
    return "answer_requirement_clarification";
  }
  if (state.advancedWorkflowEnabled && state.hasDesignPlanClarificationPending) {
    return "answer_design_plan_clarification";
  }
  if (state.advancedWorkflowEnabled && state.hasRevisionPlanClarificationPending) {
    return "answer_revision_plan_clarification";
  }
  if (state.advancedWorkflowEnabled && state.canPlanRevisionFromCurrentContext) {
    return "plan_revision";
  }
  return "generate";
}

export function applyChatClarificationAnswer(
  questions: ChatClarificationQuestion[],
  currentAnswers: Record<string, string>,
  message: string,
): ChatClarificationResult {
  const answers = { ...currentAnswers };
  const nextQuestion = questions.find((question) => !answers[question.id]?.trim());
  const trimmed = message.trim();
  if (!nextQuestion || !trimmed) {
    return {
      answers,
      answeredQuestionId: null,
      nextQuestionId: nextQuestion?.id ?? null,
      readyToSubmit:
        questions.length > 0 && questions.every((question) => Boolean(answers[question.id]?.trim())),
    };
  }

  answers[nextQuestion.id] = trimmed;
  const remainingQuestion = questions.find((question) => !answers[question.id]?.trim());
  return {
    answers,
    answeredQuestionId: nextQuestion.id,
    nextQuestionId: remainingQuestion?.id ?? null,
    readyToSubmit: questions.length > 0 && !remainingQuestion,
  };
}
