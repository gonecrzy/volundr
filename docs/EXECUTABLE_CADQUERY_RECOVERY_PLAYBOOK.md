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

## Phase 0 — existing five-project recovery

Do not generate a new corpus. For each frozen project:

- identify the earliest unresolved blocker;
- route it through the centralized policy;
- reuse valid persisted stages;
- avoid unnecessary Gemini calls;
- produce a valid final package;
- create neutral measurements and rendered evidence;
- run fresh blind Codex CAD QA.

Exit is exactly `5 / 5 independent PASS`. Do not begin the development corpus
before this condition.

Current frozen ownership must remain:

- P1: original wrong-package blind FAIL preserved; the second review is guided
  adjudication, not blind; independent status requires deterministic neutral
  B-Rep proof or a fresh uncontaminated blind reviewer;
- P2: solid-count/topology blocker;
- P3: execution-level blocker when evidence proves `build_function` and
  `Workplane.arc` is unavailable; never relabel it artifact-first;
- P4: invalid-topology blocker with a valid base and failing lid preserved;
- P5: execution-level `StdFail_NotDone`/`BRep_API` blocker until topology is
  actually reached; do not classify provider topology convergence early.

For P2/P4, record every L2 attempt’s source hash, topology metrics, normalized
failure, complete repair envelope, whether implementation changed, and whether
objective topology progress occurred. Provider convergence is valid only after
the bounded L2 policy is exhausted without progress and application/worker
boundaries are proven healthy.

For P3/P5, structured execution diagnostics must identify the failing
operation safely before any bounded L1 provider operation. L1 may continue only
while source or error state changes. Do not change source in Volundr.

Qualification-harness contract-manifest injection is a harness mechanism, not
the intended product contract source.

## Phase 1 — 16-project development corpus

Begin only after Phase 0 is 5/5 independent PASS. Freeze prompts/contracts
before the first call. Use four highly specified, eight partially specified,
and four intent-heavy projects, including at least eight planned feedback or
revision turns and both single- and multi-output projects.

Preserve every contract fact with an origin (`user_explicit`, `user_clarified`,
`model_design_choice`, `system_default`) and authority (`required`, `protected`,
`flexible`). Do not over-specify partially specified or intent-heavy prompts.

Generate one initial complete source for every project, then process
breadth-first: classify blockers, cluster generic failures, fix the generic
class, and advance affected projects. Do not optimize one project deeply while
others remain unclassified. Exit is `16 / 16` independent PASS.

Maintain explicit persisted queues:

```text
READY_QUEUE
APPLICATION_QUEUE
GEMINI_REPAIR_QUEUE
REVIEW_QUEUE
TERMINAL_QUEUE
```

A project changes queue only through a persisted router decision.

## Phase 2 — unseen holdout

After Phase 1 reaches 16/16, freeze and hash the recovery registry, failure
taxonomy, semantic policy, design-contract schema, source dialect, generation
and repair prompts, repair ceilings, progress rules, candidate policy, neutral
measurement schema, and blind reviewer prompt. Commit the freeze before
touching holdout projects.

Use an unseen eight-project holdout: two highly specified, four partially
specified, and two intent-heavy, with at least four revisions. Do not tune by
individual holdout project. A generic defect pauses and invalidates the
qualification, requiring a fresh unseen holdout set before generalization.
Target is `8 / 8` eventual independent PASS.

## Metrics and evidence

Track initial and eventual PASS, source-contract success, worker-start rate,
topology and semantic pass rates, Gemini operations to PASS, maximum repair
depth, repair success by class, deterministic recoveries, provider repairs,
artifact retries, blind-review cycles, clarification rates, revision success,
user-intent preservation, design drift, package validity, and independent PASS.

The primary metric is eventual independent PASS, not first-shot Gemini success.

Persist compact evidence only. Never put secrets, raw provider bodies, or
databases in the progress file.

## Policy freeze and commit cycles

Use substantive commits, approximately:

1. centralized recovery routing;
2. unified semantic verification and candidate policy;
3. independent CAD package review;
4. generic fixes recovering the current five;
5. current-five completion;
6. freeze the development corpus;
7. breadth-first generic recovery improvements;
8. development-corpus result;
9. freeze recovery for holdout;
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
- [ ] Phase 0: 5/5 independent PASS
- [ ] development corpus frozen before Phase 1 calls
- [ ] Phase 1: 16/16 independent PASS
- [ ] recovery policy freeze committed
- [ ] Phase 2 holdout: 8/8 independent PASS
- [ ] final merge-review gate
