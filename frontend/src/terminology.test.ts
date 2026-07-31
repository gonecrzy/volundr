import { describe, expect, it } from "vitest";
import {
  assistantVocabulary,
  provenanceLabel,
  reviewStepLabel,
} from "./terminology";

describe("assistant vocabulary", () => {
  it("keeps backend lifecycle terms out of primary labels", () => {
    expect(assistantVocabulary.designSpecification).toBe("Design requirements");
    expect(assistantVocabulary.designPlan).toBe("Proposed design");
    expect(assistantVocabulary.candidateRevision).toBe("New version");
    expect(assistantVocabulary.acceptedRevision).toBe("Current design");
    expect(assistantVocabulary.revisionOutput).toBe("Printable part");
  });

  it("uses clear provenance labels", () => {
    expect(provenanceLabel("user")).toBe("You provided");
    expect(provenanceLabel("clarification")).toBe("You confirmed");
    expect(provenanceLabel("product_default")).toBe("Volundr proposes");
    expect(provenanceLabel("calculated")).toBe("Calculated");
  });

  it("frames the review as two user-facing steps", () => {
    expect(reviewStepLabel("requirements")).toBe("Step 1 of 2 - Your requirements");
    expect(reviewStepLabel("proposal")).toBe("Step 2 of 2 - Proposed design");
  });
});
