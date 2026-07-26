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
