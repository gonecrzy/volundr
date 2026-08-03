# Live debug batch Playwright evaluation

Deterministic browser validation was run with the fixture backend, not the live
Gemini provider. It covered the requested developer surfaces without changing
the normal workspace design.

Command:

```bash
npm --prefix frontend run test:e2e -- debug-batch.spec.ts
```

Result: 5 passed, 22.5 seconds.

Scenarios covered:

1. The backend capability response hides the Debug batch action when the safe
   boolean is false.
2. Starting a batch shows the active banner, start modal, and empty drawer.
3. Two projects created while the batch is active are ordered members with
   high-level outcome, worker, attempt, retry, and current-revision fields.
4. Finish confirmation freezes the batch, produces the result, and observes no
   browser request that could execute Codex.
5. A matching frozen baseline produces a controlled comparison.

Screenshots are generated under the ignored local Playwright output directory:

```text
frontend/test-results/debug-batch-feature-disabled.png
frontend/test-results/debug-batch-start-modal.png
frontend/test-results/debug-batch-empty-drawer.png
frontend/test-results/debug-batch-drawer-two-projects.png
frontend/test-results/debug-batch-finish-confirmation.png
frontend/test-results/debug-batch-complete-result.png
frontend/test-results/debug-batch-comparison-result.png
```

The test uses direct fixture project creation for the membership-order scenario
so it does not turn a deterministic control test into a provider or worker
quality test. Real mixed-CAD evidence is collected only by the separately
documented live batches. Observed usability testing remains a separate
facilitated fixture-based activity.
