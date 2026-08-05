# Volundr Documentation Map

This file explains exactly what belongs in each project document.

## Authority categories

### Normative current contracts

These documents define intended behavior and should be read for the matching
task:

- Product direction and scope: `PRODUCT_DIRECTION.md`, `MVP_SCOPE.md`,
  `AI_CAD_DIRECTION_ALIGNMENT.md`.
- Conversation and planning: `CHAT_FIRST_WORKFLOW.md`,
  `PLANNING_DEPTH_MODEL.md`, `REQUIREMENT_SEMANTICS_CONTRACT.md`.
- CAD execution and source: `CADQUERY_BACKEND.md`,
  `GEOMETRY_EXECUTION_CONTEXT.md`, `GEOMETRY_BODY_SYMBOL_CONTRACT.md`,
  `GEMINI_RULESET.md`, `PLAN_SOURCE_IDENTITY_BOUNDARY.md`.
- Persistence and output: `PROJECT_PERSISTENCE.md`, `EXPORTS.md`,
  `MULTI_OUTPUT_GENERATION.md`, `DEPLOYMENT.md`,
  `ENVIRONMENT_VARIABLES.md`.
- Verification and testing: `GEOMETRIC_INVARIANT_VALIDATION.md`,
  `FUNCTIONAL_GEOMETRY_VERIFICATION.md`, `TEST_STRATEGY.md`,
  `FRONTEND_USER_TESTING_PLAN.md`.

### Current evaluation evidence

These reports describe what was actually tested and do not override current
contracts: `PRODUCT_VALIDATION_ROUND_1.md`,
`LIVE_DESIGN_MATRIX_EVALUATION.md`,
`PROVIDER_INTEROPERABILITY_LIVE_EVALUATION.md`,
`COMPACT_DETAILED_HARDENING_LIVE_EVALUATION.md`, and
`USER_TESTING_CHECKPOINT.md` when present.

The Gemini profile-ablation protocol and partial results are recorded in
`GEMINI_PROFILE_ABLATION.md`, `GEMINI_PROMPT_CONCISION_EXPERIMENT.md`,
`GEMINI_STRUCTURED_OUTPUT_EXPERIMENT.md`,
`GEMINI_SAMPLING_AND_SEED_EXPERIMENT.md`,
`GEMINI_THINKING_LEVEL_EXPERIMENT.md`, and
`GEMINI_PROFILE_ABLATION_RESULTS.md`. They are evaluation evidence only and do
not override production contracts.

The focused Phase 2 audit is recorded in `GEMINI_PHASE2_VALIDATION_AUDIT.md`,
with clarification semantics in `GEMINI_PHASE2_CLARIFICATION_AUDIT.md`,
worker semantics in `GEMINI_PHASE2_WORKER_REACH_AUDIT.md`, score provenance in
`GEMINI_BUILDABILITY_SCORE_RECONCILIATION.md`, and the design-only follow-up
in `GEMINI_PROFILE_B_SECOND_VALIDATION_PLAN.md`. These documents are evidence
and planning artifacts; they do not authorize deployment or change production
provider behavior.

The system-boundary methods study is documented in
`GEMINI_SYSTEM_BOUNDARY_METHODS.md`, with the offline processing gate in
`GEMINI_PROCESSING_METHOD_ABLATION.md`, the incomplete factorial in
`GEMINI_PROVIDER_PROCESSING_FACTORIAL.md`, the prompt gate in
`GEMINI_TARGETED_PROMPT_METHOD.md`, and the final selection status in
`GEMINI_FINAL_SYSTEM_SELECTION.md`. Its evidence is experiment-scoped and
does not override production contracts.

The secondary-credential continuation and quota stop are documented in
`GEMINI_SECONDARY_CREDENTIAL_RESUME.md`; the credential value itself is never
part of the evidence.

The provider-contract foundation study is documented in
`GEMINI_PROVIDER_CONTRACT_FOUNDATION.md`, with intrinsic scoring in
`GEMINI_INTRINSIC_RESPONSE_QUALITY.md`, gated settings/thinking/prompt
selection in the corresponding selection documents, frozen contracts in
`GEMINI_PROVIDER_CONTRACTS.md`, adapter behavior in
`GEMINI_PROVIDER_CONTRACT_ADAPTER.md`, and holdout status in
`GEMINI_PROVIDER_CONTRACT_HOLDOUT.md`. Its final decision is evidence only;
it does not override production contracts.

### Historical evaluation evidence

Earlier benchmark and transition reports remain useful for chronology, failure
history, and regression context: `CADQUERY_TRANSITION_EVALUATION.md`,
`MULTI_DESIGN_LIVE_EVALUATION.md`, `REQUIREMENT_DRIVEN_REVISION_LIVE_EVALUATION.md`,
`MULTI_VIEW_SNAPSHOT_LIVE_EVALUATION.md`, and older generation/live reports.
They are evidence, not current implementation authority.

### Superseded or legacy references

OpenSCAD-era contracts such as `MODEL_GENERATION_CONTRACT.md`, historical
roadmap sections describing the pre-CadQuery implementation, and archived
staged-workflow evaluations are retained for context only. They must not be
used to infer current CAD, planning, or user-facing behavior.

## Task-scoped minimum reading

- Frontend: `CHAT_FIRST_WORKFLOW.md`, `FRONTEND_WORKFLOW_AUDIT.md`,
  `PROJECT_PERSISTENCE.md`, `EXPORTS.md`, `FRONTEND_USER_TESTING_PLAN.md`.
- Requirements: `REQUIREMENT_SEMANTICS_CONTRACT.md`,
  `REQUIREMENT_TRACE_CONTRACT.md`, `REQUIREMENT_PIPELINE_AUDIT.md`.
- Planning: `PLANNING_DEPTH_MODEL.md`, `CAD_BRIEF_CONTRACT.md`,
  `COMPACT_PLAN_CONTRACT.md`, `GEOMETRY_EXECUTION_CONTEXT.md`.
- CAD/source: `CADQUERY_BACKEND.md`, `GEOMETRY_BODY_SYMBOL_CONTRACT.md`,
  `PLAN_SOURCE_IDENTITY_BOUNDARY.md`, `CAD_EXECUTION_SECURITY.md`.
- Geometry rollout: `GEOMETRY_SLOT_CONTRACT.md`,
  `GEOMETRY_SLOT_PRODUCTION_ROLLOUT.md`, and
  `GEOMETRY_SLOTS_LIVE_EVALUATION.md`.
- Persistence/export: `PROJECT_PERSISTENCE.md`, `EXPORTS.md`,
  `WORKFLOW_OBSERVABILITY.md`, `DEPLOYMENT.md`.
- Developer evaluation: `LIVE_DEBUG_BATCH_IMPLEMENTATION.md`,
  `LIVE_DEBUG_BATCH_PLAYWRIGHT_EVALUATION.md`, and the dated mixed-CAD batch
  reports when present. These documents describe developer-assisted evaluation
  only; they do not redefine normal usability testing. The correction round is
  recorded in `LIVE_BATCH_CORRECTION_ROUND_1.md`,
  `MIXED_CAD_LIVE_POST_CORRECTION_01.md`, and
  `LIVE_BATCH_POST_CORRECTION_COMPARISON.md`.
- Testing/deployment: `TEST_STRATEGY.md`, `DEPLOYMENT.md`,
  `ENVIRONMENT_VARIABLES.md`, and the relevant current evaluation report.

Do not load the entire documentation tree by default.

| File | Responsibility |
|---|---|
| `CODEX_KICKOFF_PROMPT.md` | The instruction Codex executes when beginning or resuming foundational work. |
| `README.md` | Repository entry point, project summary, status, and document links. |
| `docs/CADQUERY_BACKEND.md` | Authoritative CadQuery-primary backend architecture, staged lifecycle, artifacts, worker boundary, historical OpenSCAD removal notes, and non-goals. |
| `docs/PRODUCT_DIRECTION.md` | Product purpose, target user, principles, success criteria, and long-term direction. |
| `docs/MVP_SCOPE.md` | V1 inclusions, exclusions, and scope guard. |
| `docs/DOCKER_BASELINE.md` | Canonical service/container names, network name, volume boundaries, and Compose skeleton. |
| `docs/ARCHITECTURE.md` | Approved V1 components, interfaces, Docker service names, runtime flow, storage, and deployment. |
| `docs/PARAMETRIC_PRODUCT_MODEL.md` | High-level Parametric Product Model concepts and links to Design Plan, configuration, revision planning, and output behavior. |
| `docs/MODEL_GENERATION_CONTRACT.md` | Archived historical OpenSCAD source-contract behavior. It is not controlling product CAD behavior. |
| `docs/GEMINI_RULESET.md` | Active Gemini ruleset for CadQuery staged generation, repair, configuration, revision, and failure behavior. |
| `docs/MULTI_OUTPUT_GENERATION.md` | Canonical CadQuery output model, per-output lifecycle, assembly classification, retry, and ZIP export behavior. |
| `docs/PARAMETER_CONFIGURATION.md` | Direct parameter editing, preset switching, deterministic CadQuery parameter regeneration, configuration-change persistence, and limits that escalate to revision planning. |
| `docs/STRUCTURED_REVISION_PLANNING.md` | Immutable revision-plan lifecycle, scoped change model, compliance checks, success criteria, and finding-driven revision behavior. |
| `docs/COMPONENT_TARGETED_REVISIONS.md` | Component-targeted full-source revision behavior, source ownership, scope compliance, output preservation, interface verification, and configuration preservation. |
| `docs/GEOMETRIC_INVARIANT_VALIDATION.md` | Supported post-compile geometric invariant checks, CadQuery/Design Plan metadata, tolerances, confidence, blocking policy, and limits. |
| `docs/LIVE_GENERATION_EVALUATION.md` | Controlled live benchmark runner, run manifests, prompt-version comparison, human scoring forms, artifact collection, quota controls, and no-promotion policy. |
| `docs/PRINTABILITY_INSPECTOR.md` | Orientation-aware printability rules, severity schema, and profile thresholds. |
| `docs/CAD_EXECUTION_SECURITY.md` | Isolation, resource limits, source screening, logging, and failure handling. |
| `docs/WORKFLOW_OBSERVABILITY.md` | Workflow runs, stage vocabulary, structured events, artifact registry, diagnosis, stage traces, frontend correlation, redaction, debug bundles, run comparison, retention, and logging levels. |
| `docs/PROJECT_PERSISTENCE.md` | Durable project/workspace authority, stable reopen URLs, stale workflow recovery, and artifact integrity. |
| `docs/EXPORTS.md` | Explicit selected-revision exports, deterministic filenames, persisted ExportRecords, package contents, and 3MF status. |
| `docs/DEPLOYMENT.md` | Compose services, healthchecks, persistent mounts, credential isolation, and supported deployment boundaries. |
| `docs/ENVIRONMENT_VARIABLES.md` | Minimal deployment configuration, typed defaults, provider policy precedence, compatibility variables, derived paths, and test-only environment inventory. |
| `docs/LIVE_DEBUG_BATCH_IMPLEMENTATION.md` | Backend-authorized live debug batches, narrow persistence, evidence/redaction boundary, read-only reporting, and developer deployment setting. |
| `docs/FEATURE_VERIFICATION_LIVE_EVALUATION.md` | Frozen five-project feature-verification batch results, individual outcomes, self-review classifications, screenshots, and the single planning-only next priority. |
| `docs/LIVE_DEBUG_BATCH_PLAYWRIGHT_EVALUATION.md` | Deterministic browser controls, screenshot locations, and proof that the browser cannot execute Codex or shell commands. |
| `docs/LIVE_BATCH_CORRECTION_PLAN.md` | Planning-only post-batch correction priorities; no same-run implementation. |
| `docs/LIVE_BATCH_CORRECTION_ROUND_1.md` | First generic evidence/identity/classification correction pass and its verification boundary. |
| `docs/MIXED_CAD_LIVE_POST_CORRECTION_01.md` | Single qualifying five-project post-correction live batch and screenshot/evidence locations. |
| `docs/LIVE_BATCH_POST_CORRECTION_COMPARISON.md` | Controlled status of the original frozen pair and unpaired post-correction result. |
| `docs/LIVE_BATCH_NEXT_PRIORITY.md` | Planning-only next generic provider/schema/provenance correction family and expected repair scope. |
| `docs/FRONTEND_WORKFLOW_AUDIT.md` | Repository-grounded assessment of the user-facing workflow, terminology, state mapping, recovery, responsiveness, accessibility, and priority corrections. |
| `docs/FRONTEND_USER_TESTING_PLAN.md` | Five observed-user scenarios, measures, correlated events, preserved diagnostic evidence, and post-task questions. |
| `docs/CHAT_WORKSPACE_FRONTEND_EVALUATION.md` | Current chat-first workspace layout, conversation semantics, reconnect behavior, responsive evidence, screenshots, tests, and UX/live-track separation. |
| `docs/AI_CAD_DIRECTION_ALIGNMENT.md` | Normative conversation-first, requirement-led, revisionable product direction and status labels. |
| `docs/PLANNING_DEPTH_MODEL.md` | Semantic planning router outcomes, clarification, revision routing, and failure behavior. |
| `docs/CAD_BRIEF_CONTRACT.md` | Deterministic direct-brief contract and its relationship to the requirement ledger. |
| `docs/GEOMETRY_EXECUTION_CONTEXT.md` | Common normalized execution contract for all planning routes. |
| `docs/PROMPT_CONTEXT_PACK.md` | Branch-specific prompt selection, hashing, persistence, and reproducibility. |
| `docs/PLANNING_DEPTH_LIVE_EVALUATION.md` | Actual evidence and separation for direct, compact, and detailed live cases. |
| `docs/DERIVED_DEPENDENCY_CLASSIFICATION.md` | Execution-relevance classification for malformed derived metadata, blocking policy, persisted evidence, and non-goals. |
| `docs/GEOMETRY_BODY_SYMBOL_CONTRACT.md` | Scaffold-owned geometry function signatures, lexical symbol binding, definite assignment, findings, runtime classification, and bounded repair. |
| `docs/GEOMETRY_SLOT_CONTRACT.md` | Volundr-owned direct/compact slot manifest, reduced provider response, validation, focused completion, fallback, and localized repair. |
| `docs/GEOMETRY_TOPOLOGY_CONVERGENCE.md` | Current boundary between worker/topology success and deterministic feature/requirement evidence. |
| `docs/GEOMETRY_SLOT_PRODUCTION_ROLLOUT.md` | Deterministic and live rollout gates, evidence boundary, safety boundary, and planning-only correction boundary for geometry slots. |
| `docs/GEOMETRY_SLOTS_LIVE_EVALUATION.md` | Frozen five-project live validation record, deterministic gate, per-project results, self-review classifications, and one next priority. |
| `docs/LIVE_DESIGN_MATRIX_EVALUATION.md` | Exact real-provider direct, compact, and detailed design matrix evidence. |
| `docs/COMPACT_DETAILED_PIPELINE_DIAGNOSIS.md` | Stage-specific diagnosis of compact and detailed live pipeline failures. |
| `docs/COMPACT_PLAN_CONTRACT.md` | Compact-plan component/feature boundary, normalization, repeated-layout semantics, and non-goals. |
| `docs/REPEATED_FEATURE_LAYOUTS.md` | Fixed, proposed, configurable, and derived repeated-feature layout semantics. |
| `docs/PLAN_SOURCE_IDENTITY_BOUNDARY.md` | Protected Plan/source identities versus provider-owned local implementation variables. |
| `docs/PROVIDER_INTEROPERABILITY_CONTRACT.md` | Provider boundary, contract manifests, protected identities, and focused repair preservation. |
| `docs/WORKER_DIAGNOSTIC_REPAIR.md` | Localized worker failure classification and one-attempt CadQuery source repair. |
| `docs/PATTERN_COORDINATE_SPACE_CONTRACT.md` | Repeated-feature coordinate spaces, CadQuery placement consumers, worker API contract, and bounded execution evidence. |
| `docs/PROVIDER_INTEROPERABILITY_LIVE_EVALUATION.md` | Final fixed five-case interoperability matrix, repair evidence, threshold, and remaining blockers. |
| `docs/COMPACT_DETAILED_HARDENING_LIVE_EVALUATION.md` | Evidence for compact/detailed interoperability hardening and its safety boundary. |
| `docs/PRODUCT_VALIDATION_ROUND_1.md` | Product-shell, export, revision-chain, live-matrix, frontend, and next-phase validation evidence. |
| `docs/OBSERVED_FRONTEND_TESTING_SCRIPT.md` | Facilitator-neutral observed frontend usability session script. |
| `docs/OBSERVED_FRONTEND_TESTING_RESULTS_TEMPLATE.md` | Results template for a real observed frontend session. |
| `docs/USER_TESTING_CHECKPOINT.md` | Current read-only readiness checkpoint for the next observed frontend session. |
| `docs/DETERMINISTIC_USER_WORKFLOW_GATE.md` | Disposable fixture architecture, five browser workflow scenarios, blocked-candidate recovery evidence, success gate, commands, and known limitations. |
| `docs/REQUIREMENT_DRIVEN_REVISION_LIVE_EVALUATION.md` | Exact real-provider requirement-led revision sequence, worker evidence, compliance, and limitations. |
| `docs/REQUIREMENT_SEMANTICS_CONTRACT.md` | Authoritative requirement kinds, operators, values, units, capacity semantics, proposals, controls, and revisions. |
| `docs/REQUIREMENT_PIPELINE_AUDIT.md` | End-to-end requirement pipeline call graph, semantic coverage matrix, legacy boundaries, and exact-project evidence. |
| `docs/REQUIREMENT_TRACE_NORMALIZATION.md` | Typed unique-match normalization, deferred obligations, ambiguity, evidence, and blocking boundaries. |
| `docs/MULTI_DESIGN_LIVE_EVALUATION.md` | Small real-provider multi-design diagnostic set and accurate upstream/worker outcomes. |
| `docs/DATA_MODEL.md` | Persistent entities, fields, relationships, immutability, and archive/deletion rules. |
| `docs/CURRENT_STAGE_ROADMAP.md` | Ordered milestones, status, goals, and exit criteria. |
| `docs/GEMINI_FLASH_LITE_STUDY.md` | Ten-case Gemini Flash Lite study protocol and execution order. |
| `docs/GEMINI_FLASH_LITE_BASELINE.md` | Controlled baseline repetition and quota rules. |
| `docs/GEMINI_FLASH_LITE_RESPONSE_CORPUS.md` | Immutable response evidence and committed fixture boundary. |
| `docs/GEMINI_FLASH_LITE_CLEANUP.md` | Bounded generic cleanup and offline replay rules. |
| `docs/GEMINI_FLASH_LITE_OFFLINE_REPLAY.md` | Provider-free replay starting points and provenance. |
| `docs/GEMINI_FLASH_LITE_VALIDATION.md` | Post-cleanup validation protocol. |
| `docs/GEMINI_FLASH_LITE_BEFORE_AFTER.md` | Stage-level before/after metrics and interpretation. |
| `docs/GEMINI_FLASH_LITE_NEXT_ACTIONS.md` | Exactly-one next-direction decision contract. |
| `docs/GEMINI_FLASH_LITE_ANALYZER_AUDIT.md` | Offline analyzer defects, corrected definitions, and report provenance. |
| `docs/GEMINI_FLASH_LITE_CORRECTED_RESULTS.md` | Reconciled funnel, consistency, blocker, and before/after results. |
| `docs/GEMINI_FLASH_LITE_FEATURE_EVIDENCE_AUDIT.md` | Feature-verification evidence status and replay limits. |
| `docs/GEMINI_FLASH_LITE_RUN_RECORD.md` | Live run, offline replay, frontend smoke, and analyzer-audit handoff. |
| `docs/TEST_STRATEGY.md` | Unit, integration, end-to-end, fixture, and regression expectations. |
| `docs/OLLAMA_MODEL_CALIBRATION.md` | Ollama-only calibration phase, frozen identities, profile hashes, and operational dispositions. |
| `docs/OLLAMA_HOLDOUT_VALIDATION.md` | Untouched holdout corpus, freeze boundary, and validation status. |
| `docs/OLLAMA_HOLDOUT_FAILURE_ANATOMY.md` | Read-only twelve-pair blocker reconstruction, normalization audit, topology/geometry bands, fairness review, admission proposals, and one next direction. |
| `docs/OLLAMA_BENCHMARK_ADMISSION.md` | Gate requiring specialist and generic admissions before the later formal benchmark. |
| `docs/OLLAMA_NEXT_ACTIONS.md` | Current Ollama direction after calibration and holdout review. |

When information conflicts:

1. `CADQUERY_BACKEND.md` controls the CadQuery-primary architecture.
2. `PRODUCT_DIRECTION.md` controls product intent when it does not conflict with `CADQUERY_BACKEND.md`.
3. `MVP_SCOPE.md` controls scope when it does not conflict with the approved CadQuery architecture.
4. `ARCHITECTURE.md` controls implementation defaults after being reconciled with `CADQUERY_BACKEND.md`.
5. `GEMINI_RULESET.md`, `MULTI_OUTPUT_GENERATION.md`, `PARAMETER_CONFIGURATION.md`, `STRUCTURED_REVISION_PLANNING.md`, `COMPONENT_TARGETED_REVISIONS.md`, `GEOMETRIC_INVARIANT_VALIDATION.md`, `CAD_EXECUTION_SECURITY.md`, and `WORKFLOW_OBSERVABILITY.md` control generated CadQuery behavior, output artifacts, deterministic configuration, scoped revisions, component-targeted full-source revisions, measured geometric invariants, execution safety, and workflow tracing.
6. `CURRENT_STAGE_ROADMAP.md` controls work order.
7. `LIVE_GENERATION_EVALUATION.md` controls how live benchmark evidence is collected before changing that work order.

Functional design intent and deterministic geometry verification: `FUNCTIONAL_DESIGN_INTENT.md`, `FUNCTIONAL_GEOMETRY_VERIFICATION.md`, and `FUNCTIONAL_DESIGN_VERIFICATION_EVALUATION.md`.

Chat-first workflow and staged-mode transition: `CHAT_FIRST_WORKFLOW.md`.

Deterministic visual evidence and revision comparisons:
`MULTI_VIEW_SNAPSHOT_CONTRACT.md`, `REVISION_EVIDENCE_MODEL.md`,
`MULTI_VIEW_SNAPSHOT_LIVE_EVALUATION.md`. Future AI visual review is scoped in
`AI_VISUAL_REVIEW_PLAN.md` and is not implemented.

Durable project reopen and explicit exports: `PROJECT_PERSISTENCE.md`,
`EXPORTS.md`, `DEPLOYMENT.md`, and `ENVIRONMENT_VARIABLES.md`.

For repeated geometry, read [Repeated Feature Layouts](REPEATED_FEATURE_LAYOUTS.md)
and [Pattern Coordinate-Space Contract](PATTERN_COORDINATE_SPACE_CONTRACT.md).
For chat persistence, read [Chat Message Identity Contract](CHAT_MESSAGE_IDENTITY_CONTRACT.md).

For Gemini profile buildability evaluation, read
`GEMINI_BUILDABILITY_EVALUATION.md`,
`GEMINI_ABLATION_EVALUATOR_CORRECTION.md`,
`GEMINI_ABSOLUTE_QUALITY_FLOOR.md`,
`GEMINI_PROFILE_B_STABILITY_REVIEW.md`,
`GEMINI_STABLE_FOUNDATION_VALIDATION.md`, and
`GEMINI_MANUAL_REVIEW_BUNDLE.md`. These are evaluation evidence only and do
not override production contracts.
