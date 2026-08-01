# Frontend User-Testing Plan

Date: 2026-08-01

The usability track uses deterministic fixtures. Every project remains
revisionable through chat, while parametric controls are optional and only
appear after an explicit request. Live CAD design quality is a separate track
and is not a substitute UX fixture.

## Protocol

Use an isolated test or benchmark project for each session. Open Volundr with `?testScenario=<scenario-id>` so the correlated frontend trace is marked as a testing session. Preserve the workflow run ID, frontend event trace, diagnosis, stage trace, and redacted diagnostic bundle after every scenario.

Record observations outside Volundr. Do not put observer notes or participant free-form text into frontend telemetry.

Ask after every task:

- What did Volundr ask you to decide?
- Which dimensions came from you?
- Which dimensions did Volundr propose?
- Which design is currently active?

Classify issues as Critical, High, Medium, or Low by the consequence to the user's ability to get or retain a printable design.

## Scenario 1: Simple Explicit Part

**Scenario ID:** `new-project-explicit-part`

Starting state: empty project workspace.

Task: create a mounting plate with all fit-critical measurements supplied.

Success criteria: no unnecessary clarification; participant identifies their
requirements and Volundr proposals; Volundr automatically creates a passing
Current working version and the participant exports it explicitly without an
approval button.

Observe: time to first design, clarification count, proposal understanding, acceptance confidence.

Inspect events: `request_started`, `request_submitted`, `requirements_review_viewed`, `proposed_design_viewed`, `generation_started`, `candidate_opened`, `candidate_accepted`, `export_requested`.

Preserve: final bundle and diagnosis. Ask: “Which dimensions did Volundr choose for you, if any?”

## Scenario 2: Intent-First Holder

**Scenario ID:** `new-project-intent-first`

Starting state: empty project workspace.

Task: describe an object to hold and provide only fit-critical measurements.

Success criteria: only material questions are asked; proposal sections are understood; participant knows they do not need every model dimension.

Observe: whether the reason for each clarification is understood; whether the participant can identify an editable proposed value.

Inspect events: `clarification_displayed`, `clarification_answered`, `requirements_review_viewed`, `proposed_design_viewed`.

Preserve: clarification run bundle. Ask: “What did Volundr need from you, and why?”

## Scenario 3: Configurable Organizer

**Scenario ID:** `configure-organizer`

Starting state: accepted repeated-cell organizer fixture.

Task: change the cell count or width through Adjust parameters.

Success criteria: participant finds parameter adjustment; understands no AI
redesign is needed; understands affected printable parts before the new version
becomes current, without a provider call or approval-heavy normal path.

Observe: Configure discoverability and effect-preview clarity.

Inspect events: `configuration_opened`, `configuration_previewed`, `configuration_submitted`, `candidate_opened`, `candidate_accepted`. Confirm the run has zero provider calls.

Preserve: configuration bundle and comparison against the base run. Ask: “Why did this change not need an AI redesign?”

## Scenario 4: Multi-Part Enclosure Lid Revision

**Scenario ID:** `revise-enclosure-lid`

Starting state: accepted enclosure fixture with base and lid.

Task: change only the lid.

Success criteria: participant chooses Change the design; sees the preserved body
and target lid; distinguishes Current working version from the new attempt; and
understands that only a passing revision becomes current automatically.

Observe: Revise discoverability, protected-body understanding, confidence that the base remains active until acceptance.

Inspect events: `revision_opened`, `revision_requested`, `revision_plan_approved`, `candidate_opened`, `candidate_accepted`.

Preserve: base and revision bundles plus run comparison. Ask: “What would you do to change only the lid?”

## Scenario 5: Recoverable Failure

**Scenario ID:** `recoverable-blocked-part`

Starting state: accepted design plus deterministic blocked-output fixture.

Task: review a blocked new version and choose a recovery action.

Success criteria: participant understands the current design is safe; sees why the new version cannot be accepted; can choose an appropriate recovery without reading technical details.

Observe: recovery action choice, willingness to open technical details, and whether blocked terminology is mistaken for user error.

Inspect events: `candidate_opened`, `output_selected`, `failure_recovery_selected`, `visible_error_displayed`, `diagnostic_bundle_requested`.

Preserve: blocked run bundle and diagnosis. Ask: “What stopped the failed design from replacing your current one?”

## Session Review

For each issue, attach the scenario ID, workflow run ID, relevant frontend event sequence, diagnosis confidence, and bundle path. Prioritize evidence that separates a comprehension problem from a provider, worker, model-build, or frontend-state defect.

## Current testing status

The deterministic precondition is now the chat-first suite: explicit first
draft, essential clarification, provider-free parameter change, automatic
component revision, blocked-attempt recovery, stable project reopen/export,
and start-over lineage. These fixtures pass, so observed UX testing may
proceed. Use deterministic fixtures for usability and keep the real-provider
multi-design and bottle-holder runs as a separate live CAD-quality track.

Do not ask participants to judge physical compliance from an upstream provider
or planning failure. Preserve the workflow run ID, event trace, diagnosis, and
redacted diagnostic bundle for every session.
