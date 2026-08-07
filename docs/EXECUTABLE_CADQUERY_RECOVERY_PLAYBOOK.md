# Executable CadQuery Recovery and Qualification Playbook

This is the authoritative program specification for the executable-CadQuery
recovery goal. It is materialized from the user-provided goal objective and
the approved recovery architecture. It governs implementation, qualification,
evidence, and completion decisions.

## Branch and checkpoint discipline

Work only on `experiment/gemini-executable-cadquery-v1`. Never merge,
cherry-pick, or push experimental changes to `main`.

At every program start or resumed checkpoint record:

- experimental branch HEAD and origin experimental HEAD;
- main HEAD and common ancestor;
- worktree status;
- Alembic current, heads, and check;
- production feature defaults;
- complete baseline test counts.

Stop on unexpected branch divergence. Maintain the machine-readable tracker at
`data/debug-sessions/executable-cadquery/recovery-program-progress.json`.

## Program objective

Build Volundr into a recovery-oriented CAD system in which:

- Gemini produces complete executable CadQuery;
- Volundr validates, classifies, routes, retries, repairs, presents, and
  preserves revisions;
- failures are recovered at the cheapest correct layer;
- user requirements are distinguished from Gemini design choices;
- underspecified prompts permit legitimate design creativity;
- user feedback becomes authoritative revision intent;
- final success is determined by the actual final CAD package;
- a fresh blind Codex CAD-QA reviewer independently evaluates every final
  package.

The final question is: “Does the final CAD package match the user’s original
request and all accepted revisions?”

## Architectural ownership

Persisted workflow evidence flows through this boundary:

```text
persisted evidence
→ recovery policy classifies and selects an action
→ workflow/orchestrator persists the decision
→ owning subsystem executes the action
→ result is persisted
→ recovery policy evaluates again
```

`recovery.py` is side-effect free policy authority. Provider transport,
worker, verifier, exporter, package service, preview pipeline, and reviewer
remain execution authorities.

Important recovery state is durable. Before an action runs, persist the
observation, failure class, first owner, chosen action, attempt ordinal,
restart stage, invalidations, and policy version. Restart must recompute or
resume without duplicating provider or worker operations.

Recovery rules are generic failure-class rules. Project IDs, fixture names,
and semantic equivalents are forbidden. Any deterministic fix discovered from
one project requires a synthetic/general regression proving it is class-based.

Each policy declares the earliest restart stage and what downstream evidence it
invalidates. Examples:

```yaml
stl_export_failure:
  action: rerun_export
  restart_from: artifact_export
  invalidates: [package_generation]

semantic_requirement_failed:
  action: gemini_semantic_repair
  restart_from: source_contract
  invalidates: [worker, topology, semantic_measurement, artifacts, package, preview]

preview_render_failure:
  action: rebuild_preview
  restart_from: preview_rendering
  invalidates: []
```

## Requirement and candidate policy

Every requirement is classified before verification:

- `machine_required`;
- `review_required`;
- `informational`.

`machine_required` plus no verifier is `unsupported_verifier`, an application
coverage defect. It must not be silently downgraded to human review.
`review_required` may create an explicit review obligation. Informational
requirements are nonblocking.

Candidate state has one authoritative derivation from persisted requirement,
output, artifact, and review evidence:

- `candidate_blocked`;
- `candidate_ready_for_review`;
- `candidate_fully_verified`.

The API, frontend, qualification harness, and tests consume that same
derivation.

## Recovery ordering and bounded repair

Always prefer, in order:

1. reuse valid persisted results;
2. deterministic cleanup;
3. retry an idempotent failed stage;
4. apply an application-owned fix;
5. request Gemini complete-source repair;
6. require an explicit user or reviewer decision.

Examples:

- valid B-Rep plus STL export failure → retry/fix export, not Gemini;
- missing machine verifier → application coverage defect;
- invalid CadQuery API call → Gemini L1;
- invalid topology → Gemini L2;
- measured dimension mismatch → Gemini L3 only when geometry owns the mismatch.

Gemini always receives and returns complete replacement source. Volundr must not
patch source, reconstruct geometry strategy, substitute CadQuery operations, or
prescribe project-specific modeling methods.

Never continue solely because unused attempts remain. L1 progression requires
objective execution progress, such as a later phase, additional completed
required output, or a changed failure/diagnostic signature. L2 requires
objective topology progress. Repeated source/error/topology state stops.

## Independent CAD QA

Every otherwise eligible final package receives a fresh blind Codex CAD-QA
review. The reviewer receives only the original request, clarification
answers, ordered user revisions, output identities, final package, neutral
measurements, renders, units, and tolerances.

The reviewer must not receive Volundr’s verdict, Gemini history, failure
history, previous reviews, expected result, or developer hypotheses. A guided
adjudication is never a blind PASS.

The reviewer returns `PASS`, `FAIL`, or `UNCERTAIN`. FAIL and UNCERTAIN route
back through the same recovery system, with a fresh reviewer after recovery.
Hard deterministic Volundr failures cannot be overridden by Codex.

Neutral measurements should include output identities, solid count, bounding
box, volume, detectable hole/cylinder and planar-face measurements, artifact
hashes, relationship measurements, and revision deltas. Screenshots are not a
substitute for measurements.

## Credential policy

Credential work is frozen at the approved boundary:

```text
GEMINI_API_KEY   → primary
GEMINI_API_KEY_2 → fallback only after HTTP 429
```

The API receives resolved secret settings directly. The transport sends the
logical request with primary, persists that attempt on HTTP 429, waits at least
30 seconds, and sends the exact same request once with fallback while retaining
the logical operation ID and creating a new attempt ID. A fallback 429 stops.
Timeout/502/503/504 retries stay on the original credential. 401/403,
malformed output, semantic, worker, topology, verification, and artifact
failures never rotate credentials.

Neither key may reach frontend, browser, Playwright, worker, evidence, or logs.
Do not revisit credential selection without a real transport/auth/rate-limit
failure.

## Seed / debug corpus: P1–P5

P1–P5 are permanent regression fixtures and the seed/debug corpus. They are
not the certification corpus. Preserve their authoritative identities, hashes,
worker results, repair envelopes, stale-artifact explanations, failures, and
review outcomes exactly. Do not regenerate them or rewrite a failure as a
success to satisfy a phase gate.

The seed corpus exposes recovery-routing, stale-state, execution, topology,
semantic-verification, artifact/package, revision/persistence, and
reviewer/evidence defects. Seed projects should improve when generic
capabilities improve, but no project-specific rule may be added to clear one.

## Phase 0 — Seed Stabilization

Phase 0 is complete when the following system properties are proven:

- the centralized recovery router is authoritative;
- failure stages and first-owner classification are trustworthy;
- stale evidence cannot drive repair;
- recovery decisions are durable;
- recovery actions return to the router after execution;
- deterministic recovery is separate from Gemini repair;
- source, execution, topology, semantic, and artifact failures route to
  distinct stages;
- credential handling is stable;
- independent blind QA works;
- hard deterministic failures cannot be overridden by model review;
- full regression and product-integrity gates pass; and
- no unidentified shared application-integrity defect prevents meaningful
  cross-project execution.

P1–P5 do not need to reach `5 / 5 independent PASS` before Phase 1. Their
unresolved blockers remain regression fixtures, recovery examples, and future
validation cases. The authoritative seed matrix remains the source of truth.

Qualification-harness contract-manifest injection is a harness mechanism, not
the intended product contract source.

## Phase 1A — Frozen First-Blocker Survey

After the Phase 0 seed-stabilization properties are verified, create a diverse
16-project DEVELOPMENT corpus. Freeze every initial user prompt before the
first provider call. Freeze planned clarification answers and user-feedback or
revision turns as well.

For every project, run exactly this first-pass path:

```text
user request
→ clarification only when genuinely necessary
→ design contract
→ one initial complete-source generation
→ deterministic pipeline
→ stop at the first real blocker or candidate-ready
```

Run all 16 projects to first-pass state before changing application code,
recovery rules, Gemini prompts, repair envelopes, or semantic policy based on
individual corpus outcomes. If a security, credential, persistence, database,
or artifact-integrity defect appears, stop the survey, fix the integrity
defect, and restart or reconcile the survey as appropriate.

The survey corpus composition is:

- 4 highly specified projects;
- 8 partially specified projects; and
- 4 intent-heavy/minimally specified projects.

At least 8 projects include frozen user feedback or revision turns. Across the
16, include single-output and multi-output designs; rotational, prismatic,
curved/swept, cavity/shell, holes/patterns, mating relationships, optional
outputs, and revision-heavy workflows. Do not make the set variants of
brackets, enclosures, or P1–P5.

Do not over-specify most projects. Record each contract fact with:

- origin: `user_explicit`, `user_clarified`, `model_design_choice`, or
  `system_default`;
- authority: `required`, `protected`, or `flexible`.

Gemini may choose reasonable designs where the user leaves ordinary choices
open. Do not invent dimensions and grade Gemini against them as hidden user
requirements. Clarify only when ambiguity materially affects fit, mating,
function, safety, compatibility, or output identity.

At least half the corpus contains realistic frozen feedback such as widening
openings, reducing bulk, moving an exit, adding bosses, spacing holders,
tilting a design, or using larger mounting holes. Do not predefine hidden exact
dimensions for feedback that does not state them.

The Phase 1A result is a first-blocker matrix that distinguishes initial
PASS/candidate-ready projects, source-contract blockers, execution blockers,
topology blockers, semantic-measurement blockers, unsupported-verifier
blockers, artifact blockers, and presentation/review blockers. Do not collapse
unrelated errors into one broad category.

Maintain explicit persisted queues:

```text
READY_QUEUE
APPLICATION_QUEUE
GEMINI_REPAIR_QUEUE
REVIEW_QUEUE
TERMINAL_QUEUE
```

Movement is driven only by the centralized router.

## Phase 1B — Cluster-Driven Recovery Development

After the complete 16-project first-blocker survey, cluster failures by
generic mechanism and work breadth-first by failure class, not one project at
a time. Representative clusters include:

```text
source_contract_violation
cadquery_api_error
build_execution_error
invalid_shape
solid_count_mismatch
semantic_requirement_failed
unsupported_verifier
stl_export_failure
package_generation_failure
preview_render_failure
revision_drift
```

For each cluster:

1. reproduce the generic mechanism;
2. determine application/provider ownership;
3. improve routing or evidence generically;
4. add general or synthetic regression coverage;
5. advance every affected project;
6. discover each project’s next blocker; and
7. return projects to the appropriate queue.

Before accepting a new recovery rule, verify that it does not depend on a
project ID, corpus number, exact fixture dimension, project-specific feature
name, known final source, known one-project solution, or copied successful
prompt. A deterministic fix from one project is acceptable only when the
mechanism is clearly geometry-independent, such as stale-state handling,
export retry, workspace initialization, exception classification, package
reconciliation, or preview regeneration. Every generic rule needs synthetic
or general regression coverage; otherwise prefer evidence from at least two
unrelated projects.

Track `new_generic_recovery_rules_by_project_order` and
`existing_rule_recovery_rate`. The desired pattern is that new generic rules
flatten across projects 1–4, 5–8, 9–12, and 13–16, while later projects
increasingly recover using existing rules.

Development continues until all 16 final packages independently PASS. Track
both initial PASS rate and eventual PASS rate; eventual independent PASS is
the primary development metric.

## Policy freeze

Only after `16 / 16` DEVELOPMENT projects independently PASS, freeze, version,
and hash the recovery registry, failure taxonomy, stage ordering, semantic
policy, design-contract schema, source dialect, Gemini generation and repair
prompts, repair ceilings, progress rules, candidate policy, neutral measurement
schema, and blind reviewer prompt. Do not continue tuning against development
projects after the freeze.

## Phase 2 — Unseen Holdout Qualification

Keep 8 holdout projects hidden and unseen during development. Do not expose
their prompts to development or cluster-driven recovery work. Use different
geometry/task combinations from the development set.

Composition is 2 highly specified, 4 partially specified, and 2 intent-heavy
projects; at least 4 include revision turns. Do not tune by individual holdout
project. If a generic application defect requires policy changes, stop the
holdout, fix the defect, invalidate that qualification, and create a new unseen
holdout before claiming generalization. Target is `8 / 8` eventual independent
PASS.

## Metrics and evidence

Track initial and eventual PASS, source-contract success, worker-start rate,
topology and semantic pass rates, Gemini operations to PASS, maximum repair
depth, repair success by class, deterministic recoveries, provider repairs,
artifact retries, blind-review cycles, clarification rates, revision success,
user-intent preservation, design drift, package validity, and independent PASS.
Also track `new_generic_recovery_rules_by_project_order` and
`existing_rule_recovery_rate`; later projects should need fewer new generic
rules and should increasingly recover with existing rules.

The primary metric is eventual independent PASS, not first-shot Gemini success.

Persist compact evidence only. Never put secrets, raw provider bodies, or
databases in the progress file.

## Policy freeze and commit cycles

Use substantive commits, approximately:

1. centralized recovery routing;
2. unified semantic verification and candidate policy;
3. independent CAD package review;
4. generic fixes recovering the seed/debug corpus;
5. seed stabilization and methodology checkpoint;
6. freeze the diverse development corpus;
7. breadth-first generic recovery improvements;
8. development-corpus result;
9. freeze recovery policy for holdout;
10. holdout qualification result.

Commit messages describe implementation or phase milestones, not bookkeeping.
Push the experimental branch after substantive commits. Keep main unchanged.

## Provider-call discipline and no-go conditions

Before every provider operation record why deterministic recovery cannot handle
it, which repair level owns it, the exact evidence Gemini will receive, and
what objective progress justifies another repair. Persist that decision.

Stop broad execution on credential leakage, authorization failure, artifact
isolation failure, database integrity failure, revision corruption,
cross-project contamination, repeated unidentified shared defects,
project-specific recovery logic, blind-review contamination, or accidental
production enablement.

## Verification and completion

At each phase gate run the complete applicable backend and frontend suites,
frontend build and offline browser suite, recovery-router and progress tests,
semantic-policy and repair-envelope tests, worker/topology, artifact/package,
revision, independent-review, authentication, and credential-boundary tests;
Alembic current/heads/check; Compose; nginx; secret scan; `git diff --check`;
and clean-worktree verification.

The experiment is eligible for merge review only when historical five,
development corpus, and unseen holdout gates all pass, required revisions
pass, no project-specific hacks exist, full regressions pass, production is
disabled by default, and main is unchanged.

The final program decision is:

```text
executable_cadquery_recovery_ready_for_merge_review
```

Do not declare completion because tests pass, a router exists, models render,
or Volundr says candidate-ready. Completion requires every gate above.

## Checklist

- [x] authoritative playbook present and read in full
- [x] experimental branch and main divergence recorded
- [x] migration and production-default baseline recorded
- [x] baseline backend/frontend counts recorded
- [x] centralized recovery policy and durable decisions
- [x] semantic and candidate policy unified
- [x] independent package review and neutral measurements
- [ ] Phase 0: seed stabilization gate; P1–P5 remain permanent fixtures
- [ ] Phase 1A: diverse 16-project corpus frozen before first calls
- [ ] Phase 1A: all 16 first-blocker results persisted
- [ ] Phase 1B: breadth-first generic recovery development complete
- [ ] development gate: 16/16 eventual independent PASS
- [ ] policy freeze committed and versioned
- [ ] Phase 2 unseen holdout: 8/8 eventual independent PASS
- [ ] final merge-review gate
