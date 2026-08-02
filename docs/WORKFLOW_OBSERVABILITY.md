# Workflow Observability

This document is the authority for Volundr workflow tracing, event schema, stage vocabulary, diagnostic bundles, and deterministic first-failure diagnosis.

The normal chat workspace is a presentation of the same authoritative records,
not a second lifecycle. It correlates chat submission, intent routing,
clarification, automatic progression, generation, working-version promotion,
blocked-attempt preservation, start-over, and export events with the existing
workflow run. User-facing chat hides internal system events while technical
details and debug bundles retain them.

## Workflow Runs

Chat progression events also record whether a transition was automatic,
confirmed conversationally, or interrupted for essential clarification. The
requirement-led lifecycle records requirement deltas, physical-test feedback,
working-version promotion, blocked-attempt preservation, and start-over
lineage events alongside the existing CAD evidence.

A workflow run represents one user objective moving through internal stages. Runs are stored in `workflow_runs`.

Core fields:

```text
id
project_id
workflow_type
parent_workflow_run_id
root_workflow_run_id
correlation_id
status
logging_mode
event_schema_version
diagnosis_version
redaction_version
application_commit
worker_version
provider
model
prompt_versions_json
started_at
completed_at
```

Supported workflow types:

```text
initial_generation
requirement_clarification
design_plan_creation
regeneration
configuration_change
structured_revision
component_revision
output_retry
candidate_acceptance
candidate_rejection
export
contract_repair
source_generation
```

Terminal states are:

```text
completed
failed
blocked
cancelled
abandoned
```

Runs left `running` after interruption can be classified as `abandoned` by the stale-run classifier. Evidence is retained.

## Root And Child Boundaries

One root run represents one objective. Child runs keep repairs, retries, clarifications, Design Plan creation, candidate decisions, and export actions attached to that objective where the workflow is still active.

Later structural revisions can be new root objectives and should still record base revision and Revision Plan identifiers. The model allows `parent_workflow_run_id` to be null for those independent roots while retaining `project_id`, `revision_plan_id`, and `revision_id` links on events.

## Event Schema

Events are stored in `workflow_events` and are append-only. Each event has:

```text
schema_version
event_id
workflow_run_id
root_workflow_run_id
correlation_id
project_id
sequence_number
occurred_at
recorded_at
stage
event_type
severity
blocking
message
rule_id
entity_type
entity_id
expected_json
detected_json
source_artifact_id
caused_by_event_id
is_root_failure
is_downstream_symptom
deduplication_key
metadata_json
```

`sequence_number` is monotonically increasing within each workflow run and is used before timestamps for ordering inside a run. `occurred_at` records when the event happened; `recorded_at` records when it was persisted.

`deduplication_key` is optional and should be deterministic for retried lifecycle operations, for example:

```text
workflow_run_id + stage + event_type + entity_id + attempt_number
```

The database enforces uniqueness for `(workflow_run_id, sequence_number)` and `(workflow_run_id, deduplication_key)`.

Persistence and export events remain correlated with the originating project
and revision. Workspace reopen emits no new generation attempt; stale-run
recovery records an abandonment state. Export records link the selected
revision, deterministic filename, artifact hashes, warnings, and download
status so an export cannot be mistaken for a new design generation.

## Stage Vocabulary

Use these stage names exactly:

```text
project_request
requirement_extraction
requirement_validation
requirement_clarification
design_specification_review
design_plan_generation
design_plan_validation
design_plan_review
source_generation
source_extraction
source_contract_validation
contract_repair
worker_submission
cad_execution
execution_repair
topology_validation
artifact_consistency
mesh_validation
printability_validation
candidate_classification
candidate_review
configuration_preview
configuration_execution
revision_planning
revision_scope_validation
component_revision
scope_correction
output_preservation
acceptance
rejection
export
frontend_workflow
provider_response
```

## Artifact Registry

Artifacts are stored in `workflow_artifacts`. The registry stores metadata, paths, hashes, redaction state, and supersession links. Large STEP/STL/BREP files are not stored in database blobs.

Records include:

```text
id
workflow_run_id
root_workflow_run_id
correlation_id
project_id
stage
artifact_type
role
path
sha256
size_bytes
media_type
redacted
redaction_status
supersedes_artifact_id
created_at
```

Retries and repairs create new artifact rows. Earlier failed source attempts, failed repair attempts, worker snapshots, manifests, and validation outputs must remain reconstructable. Latest-state fields on revision rows are convenience indexes, not the only evidence.

## Diagnosis

`WorkflowDiagnosisService` writes deterministic `workflow-diagnosis-v1` records. Diagnosis is conservative:

1. explicit `caused_by_event_id` and `is_root_failure`
2. known stage dependency and downstream-symptom rules
3. repair lineage
4. deterministic event ordering
5. timestamps only as a final fallback across run boundaries

Confidence values are:

```text
confirmed
probable
possible
unknown
```

Candidate blocked events are normally final-state symptoms, not root causes. Missing topology after worker failure is a symptom. Unknown causality remains `unknown` or low confidence rather than being presented as confirmed.

## Stage Trace

`WorkflowStageTraceService` builds `stage-trace-v1` from event entity fields and artifact hashes. It supports protected/default/explicit parameter values, submitted execution parameters, source hashes, output artifacts, and first drift detection when an event has both `expected_json` and `detected_json`.

The debug bundle includes both JSON and Markdown trace views.

## Frontend Correlation

The frontend keeps a local frontend session ID and attaches backend workflow headers when available:

```text
X-Workflow-Run-Id
X-Workflow-Root-Run-Id
X-Workflow-Correlation-Id
```

Frontend event ingestion accepts only registered event names and typed scalar metadata. It enforces payload-size limits, batch-size limits, rate limiting, project/workflow ownership checks, correlation checks, and rejection of unknown event names. It does not accept arbitrary browser logs, keyboard input, unrelated browsing behavior, full browser fingerprints, or duplicated free-form design text.

## Redaction

`RedactionService` is allowlist based for provider request metadata and headers. It:

- strips URL query strings
- preserves only approved headers
- redacts known API key, authorization, token, cookie, password, database URL, and signed URL patterns
- never serializes full environment dictionaries
- scans debug-bundle text members before release

Debug bundles include `redaction-report.json`. Sensitive text artifacts are redacted into the bundle when possible. Sensitive binary artifacts must already be confirmed redacted or the bundle fails closed.

## Debug Bundles

`GET /api/workflow-runs/{workflow_run_id}/debug-bundle.zip` creates:

```text
workflow-debug-<workflow_run_id>/
README.md
run-summary.json
diagnosis.json
event-log.ndjson
stage-trace.json
stage-trace.md
artifacts.json
redaction-report.json
artifacts/
```

STEP/STL/BREP geometry is excluded by default. An explicit advanced option can include geometry artifacts. The bundle is generated on demand and is removed by project deletion when generated.

## Run Comparison

`WorkflowRunComparisonService` compares two workflow roots deterministically. It reports:

- provider call count changes
- repair count changes
- explicit/protected/default parameter value regressions
- candidate state changes

Reduced repair count is an improvement only when the comparison basis is deterministic. Metric reductions are otherwise reported as changes, not automatically improvements.

## Retention And Logging Modes

Logging modes:

```text
summary
standard
diagnostic
```

Summary stores stage transitions, final state, root failure, and provider/worker timing. Standard stores structured findings, artifact hashes, stage values, and repair history. Diagnostic retains prompts, raw provider responses, source attempts, manifests, and detailed diagnostics.

Normal projects should avoid unnecessary sensitive payload retention. Test and benchmark projects may use diagnostic mode and retain all prompts, responses, repairs, source attempts, manifests, diagnoses, and comparisons.

Disk growth comes primarily from immutable source attempts, raw provider responses, worker logs, manifests, and optional geometry inclusion in debug bundles. Automated cleanup is intentionally minimal; project deletion removes associated trace records and generated debug bundles.

## API

Technical endpoints:

```text
GET /api/workflow-runs/{workflow_run_id}
GET /api/workflow-runs/{workflow_run_id}/events
GET /api/workflow-runs/{workflow_run_id}/diagnosis
GET /api/workflow-runs/{workflow_run_id}/stage-trace
GET /api/workflow-runs/{workflow_run_id}/debug-bundle.zip
GET /api/workflow-runs/{baseline_workflow_run_id}/compare/{candidate_workflow_run_id}
POST /api/workflow/frontend-events
```

Normal product screens should not expose IDs except in advanced technical details.

## Known Limitations

- Cross-run ordering uses each run's deterministic `sequence_number` plus persisted run/event record times; a global root-sequence counter is not yet stored.
- Stage trace currently derives values from emitted entity events and artifact metadata; older records without entity fields cannot produce full matrices.
- Diagnosis is deterministic and conservative, not AI-assisted root-cause analysis.
- The frontend diagnostic action is intentionally secondary to normal design work; it exposes the workflow ID, final deterministic diagnosis, and debug bundle only in Technical details.

## Frontend User-Testing Correlation

The frontend uses fixed, typed workflow event names for request, review, progress, candidate, configuration, revision, recovery, export, and technical-details actions. Test sessions can add `?testScenario=<safe-scenario-id>`; this produces only `testing_session` and `test_scenario_id` metadata. It does not capture observer notes or arbitrary browser activity. See `docs/FRONTEND_USER_TESTING_PLAN.md` for the five required scenarios and evidence-retention procedure.

Functional planning, source parameter-effect, feature implementation, and deterministic geometry findings are correlated evidence and do not replace earlier artifacts.

Planning-depth evidence is also immutable workflow evidence: route decisions,
missing-information records, direct/compact/detailed plan payloads, normalized
GeometryExecutionContexts, and branch-specific prompt context packs are stored
in the artifact registry. Attempt and workflow metadata may index their hashes
and IDs but is not the authoritative copy.

Chat-first progression records `chat.message.submitted`, `chat.intent.classified`,
`clarification.requested`, `clarification.answered`, `requirements.progressed`,
`design_plan.progressed`, `generation.started`, `parameter_update.routed`,
`structural_revision.routed`, `start_over.branch_created`,
`working_version.promoted`, `blocked_attempt.preserved`, and `export.requested`.

Post-worker evidence adds `snapshot.generated`,
`snapshot.not_applicable_before_worker`, `snapshot.generation_failed`, and
`revision.comparison.generated`. Packet hashes, image hashes, view timing,
artifact IDs, and omission reasons remain in durable artifacts; workflow event
metadata contains only concise indexes and summaries.

Structured geometry attempts also persist per-derived dependency
classification in `scaffold-manifest.json`. A diagnostic-only dependency emits
`planning.derived_dependency_classified` with warning severity and
`blocking=false`; its complete finding, reasons, and classification remain in
the artifact metadata for Technical details and debug bundles. It does not
start contract repair. A blocking dependency retains the same evidence in the
assembly rejection details.
