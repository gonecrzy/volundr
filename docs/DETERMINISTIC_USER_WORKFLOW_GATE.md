# Deterministic User Workflow Gate

This checkpoint verifies the five primary user-testing workflows through the
real frontend, FastAPI routes, SQLite persistence, workflow recorder, controlled
provider, and controlled CAD worker. Browser tests do not mock API responses.

## Primary Scenarios

The completed scenarios are:

1. Explicit part: submit a complete request, review the requirements and
   proposal, generate a candidate, accept it, export it, and download its
   diagnostic bundle.
2. Intent-first holder: answer one essential clarification without losing the
   original request, then review and generate the candidate.
3. Configurable organizer: change four columns to six through Adjust
   parameters. The configuration run makes zero provider calls, preserves the
   source hash, changes the parameter hash, and promotes the candidate only
   after acceptance.
4. Enclosure lid revision: approve a scoped Revision Plan, generate a complete
   component-targeted source, preserve the base output, validate both outputs,
   and accept the revised assembly.
5. Recoverable blocked candidate: review a blocked New version while the
   accepted Current design remains active. Topology failures route to a
   part-specific revision request; transient worker failures retry the same
   source, parameters, and output without calling the provider.

Scenario 5 uses two real persistence fixtures:

- `multiple_solids`: the required output has expected solid count 1 and
  detected solid count 2. Diagnosis identifies topology as the first failure.
- `worker_failure`: the required output has a structured worker failure. The
  failed result is preserved, and a deterministic retry produces a valid
  output and reclassifies the candidate.

## Fixture Architecture

The fixture server is `backend/app/testing/e2e_fixture_server.py`. It uses the
production project service, workflow recorder, SQLite session, provider
adapter, and CadQuery runner interface. Fixture modes change controlled worker
results; they do not return pre-rendered candidate screens.

Playwright fixture routes are test-only and are isolated by a disposable data
directory. The project summary endpoint exposes bounded evidence for assertions:
provider calls, worker calls, workflow runs, event order, artifacts, frontend
events, and revisions.

## Success Gate

Before observed testing, the deterministic gate requires:

- all five primary scenarios pass in real Chromium;
- current and New version labels remain unambiguous;
- blocked candidates cannot be accepted through the UI or API;
- acceptance and export use the intended revision;
- configuration runs prove zero provider calls;
- retry runs preserve the failed worker evidence and use unchanged source and
  parameter hashes;
- every scenario has correlated workflow and frontend events;
- diagnostic bundles are valid ZIPs with a redaction report;
- no unhandled browser exceptions or unexplained failed requests remain;
- fixture projects are disposable and do not leak state between runs.

## Scenario 5 Evidence

The blocked-candidate browser test verifies `candidate_opened`,
`output_selected`, `visible_error_displayed`, `failure_recovery_selected`, and
`diagnostic_bundle_requested`. Backend evidence links the topology or worker
failure to the downstream `candidate.classified` event. Retry evidence records
the original worker snapshot, a separate retry child run, worker submission and
result, and reclassification.

The primary user-facing contract is:

- the Current design remains active and unchanged;
- the New version is not accepted while a required part is blocked;
- the message explains the actual failure without exposing rule IDs;
- recovery actions are visible without opening technical details;
- technical details and the diagnostic bundle preserve the causal evidence.

## Commands

From `backend`:

```text
PYTHONPATH=. .venv/bin/pytest tests/test_blocked_candidate_fixture.py -q
```

From `frontend`:

```text
npm run test -- --run
npm run build
npx playwright test e2e/workflow-gate.spec.ts e2e/configure-organizer.spec.ts e2e/enclosure-revision.spec.ts e2e/recoverable-blocked-workflow.spec.ts
```

The Playwright harness accepts `VOLUNDR_E2E_PORT` and
`VOLUNDR_E2E_WEB_PORT` so repeated runs cannot attach to a shared development
server. It also accepts `VOLUNDR_E2E_VIEWPORT_WIDTH` and
`VOLUNDR_E2E_VIEWPORT_HEIGHT` and captures screenshots only on failure.

The integrity checkpoint ran all 13 tests five times against five fresh
SQLite fixture roots: 65/65 passed. The browser runtimes were approximately
1.5 minutes per run. No fixture server remained running and the disposable
fixture directories were removed after the checkpoint.

Responsive checks passed for the full suite at 1920x1080, 1440x900, and
1024x768. Mobile review checks passed at 390x844 for clarification,
candidate acceptance/export, blocked-state review, and recovery actions.

Focused failure checks covered provider interruption, contract and plan repair
lineage, stale workflow diagnosis, consistency rejection, worker timeout and
duplicate completion, revision scope and identity rejection, blocked
acceptance, output retry preservation, and duplicate submission. Disposable
source-copy mutation checks detected deliberate mutations for early candidate
acceptance, protected-output drift, provider use during configuration, a
blocked candidate becoming acceptable, incorrect diagnosis root selection, and
retry evidence replacement.

The live Gemini group remains opt-in and is not part of the deterministic gate.
It was not run in this checkpoint because live credentials and quota were not
provided.

## Known Limitations

The topology recovery test prepares a targeted revision request but does not
complete a second structural revision. The fixture summary is intentionally a
bounded test aid rather than a production analytics surface. The mutation
checks are an ad hoc disposable-source checkpoint rather than a committed
general mutation-testing framework.
