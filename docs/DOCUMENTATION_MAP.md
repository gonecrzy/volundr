# Volundr Documentation Map

This file explains exactly what belongs in each project document.

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
| `docs/FRONTEND_WORKFLOW_AUDIT.md` | Repository-grounded assessment of the user-facing workflow, terminology, state mapping, recovery, responsiveness, accessibility, and priority corrections. |
| `docs/FRONTEND_USER_TESTING_PLAN.md` | Five observed-user scenarios, measures, correlated events, preserved diagnostic evidence, and post-task questions. |
| `docs/DETERMINISTIC_USER_WORKFLOW_GATE.md` | Disposable fixture architecture, five browser workflow scenarios, blocked-candidate recovery evidence, success gate, commands, and known limitations. |
| `docs/REQUIREMENT_DRIVEN_REVISION_LIVE_EVALUATION.md` | Exact real-provider requirement-led revision sequence, worker evidence, compliance, and limitations. |
| `docs/DATA_MODEL.md` | Persistent entities, fields, relationships, and immutability rules. |
| `docs/CURRENT_STAGE_ROADMAP.md` | Ordered milestones, status, goals, and exit criteria. |
| `docs/TEST_STRATEGY.md` | Unit, integration, end-to-end, fixture, and regression expectations. |

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
