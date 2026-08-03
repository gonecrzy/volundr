# Geometry Slot Contract Production Plan

## Objective

Productionize `volundr-geometry-slots-v1` for direct and compact geometry
generation. Volundr owns all stable executable structure and Gemini returns
only ordered statement bodies and result symbols. Preserve the existing
requirement, planning, provenance, source-safety, worker, verification,
revision, and promotion gates. Run one unchanged mixed live validation batch
after deterministic verification and choose exactly one next CAD priority;
do not implement that priority in this pass.

## Guardrails

- Keep the existing `cadquery-scaffold-v1` source scaffold and legacy geometry
  body contract for detailed plans and explicit legacy fallback.
- Do not add product-specific geometry or screw-thread helpers.
- Do not add another evidence framework or run another model comparison.
- Keep provider-facing slot briefs reduced and deterministic; persist the full
  internal plan and existing provenance separately.
- Allow one focused missing/invalid-slot completion and one localized
  worker-informed repair, preserving unaffected slot hashes.
- Fallback to the legacy contract only before worker submission, only when no
  provider repair has been used, and record the fallback explicitly.
- Do not change prompts, code, configuration, or retry policy between the
  live batch's projects; do not apply fixes during or after that batch.
- Keep raw live evidence local under `data/debug-sessions/`, redacted, and
  outside Git.

## Implementation sequence and TDD gates

### 1. Contract core and route selection — commit 1

Write failing tests first for:

- Volundr-owned slot count/order/signatures and response-order independence;
- duplicate, unknown, prohibited, invalid-result, import, declaration, and
  unavailable-helper rejection;
- authorized parameters, ordinary locals, and exposed-control validation;
- direct/compact slot selection and detailed legacy selection;
- reduced provider brief exclusions and scaffold-exposed helper inventory.

Implement:

- `backend/app/services/cad/geometry_slots.py` with the versioned schema,
  authoritative slot manifest, reduced provider brief, parsing/classification,
  canonical body assembly, slot hashes, and source rendering integration;
- typed rollout configuration with `auto`, `legacy_contract`, and
  `geometry_slots_v1` semantics, documented outside the minimal `.env.example`;
- `ModelGenerationRequest` fields for selected contract, slot manifest/brief,
  completion scope, and preserved slot hashes;
- Gemini routing and a slot-only prompt branch that never asks the provider
  for declarations, imports, IDs, signatures, scaffold, or entrypoint code.

Verify focused contract/provider tests and the existing geometry contract suite.

### 2. Partial completion and bounded fallback/repair — commit 2

Write failing tests first for:

- partial valid responses retaining completed slots;
- one focused completion containing only missing/invalid slots;
- rejection of changed completed slots and unchanged/regressive completion;
- one localized worker repair changing one slot only;
- pre-worker legacy fallback and explicit metadata;
- singular user-facing operation and no duplicate progress outcome.

Implement service integration in
`backend/app/services/projects/service.py` and workflow/attempt artifact
recording. Keep existing source validation, worker submission, topology,
verification, Current working version, and revision protection unchanged.
For direct/compact revisions, scope manifests to affected slots and reuse safe
unaffected accepted bodies. Keep detailed plans on the legacy path.

Verify focused service, workflow, revision, and provider-call tests plus the
full existing backend suite.

### 3. Frozen experiment regressions — commit 3

Freeze redacted real-response fixtures under
`backend/tests/fixtures/geometry_slots/` for the seven required cases:

1. undeclared organizer `corner_radius`;
2. valid simplified organizer;
3. wrong slot/function count;
4. unsupported arguments;
5. imports;
6. screw-lid `circular_pattern_points`;
7. wall-carrier localized worker failure and successful repair.

Add deterministic replay tests for classifications, focused completion,
helper/source safety, repair scope, and byte/hash stability. Do not commit raw
unredacted responses or live evidence.

### 4. Frontend technical observability and deterministic browser coverage — commit 4

Expose only safe selected-contract/completion/fallback summaries in existing
technical details. Normal chat must not show slot terminology. Ensure internal
completion/fallback calls do not create duplicate user-visible progress
messages and final blocked/success wording remains accurate.

Add frontend unit tests and deterministic Playwright scenarios for direct,
compact, partial completion, bounded fallback, worker repair, duplicate-message
protection, and Current working version protection. Capture the required
1440x900 deterministic screenshots using repository conventions, without
committing raw live evidence.

### 5. Compose/pre-live gate

Run backend tests, frontend tests/build, migration checks, Compose config and
health, API readiness, worker readiness, Playwright suites, and `git diff
--check`. Do not start the live batch until all required gates pass and the
repository is clean.

### 6. One live validation batch — commit 5

Run `geometry-slots-live-01` through the real frontend, configured provider,
and CadQuery worker using the same five mixed prompts/fact sheets from the
prior mixed-CAD batches. Record route, contract, slot counts, completion,
fallback, validation, worker, topology, candidate, provider-call, token, and
latency evidence for every project. Preserve all attempts and keep raw
evidence outside Git. Do not rerun a model comparison or change code/prompts/
configuration during the batch.

Update `docs/GEOMETRY_SLOTS_LIVE_EVALUATION.md` and the required existing
diagnostic/architecture/test/observability documentation with measured
results, and compare worker reach/tokens against prior evidence.

### 7. Select exactly one next priority — commit 6

Select one evidence-backed priority from the objective's six choices:

- expand slots to detailed/multipart designs;
- add a generic CAD helper/tool surface;
- improve bounded worker repair;
- improve deterministic feature verification;
- conduct formal observed frontend testing;
- reconsider provider/model strategy.

Write the planning-only recommendation in the live evaluation documentation
and `docs/LIVE_BATCH_CORRECTION_PLAN.md` if applicable. Do not implement it.

## Required documentation updates

Create:

- `docs/GEOMETRY_SLOT_CONTRACT.md`
- `docs/GEOMETRY_SLOT_PRODUCTION_ROLLOUT.md`
- `docs/GEOMETRY_SLOTS_LIVE_EVALUATION.md`

Update the objective-listed generation blocker, experiment, contract,
architecture, test strategy, observability, roadmap, and documentation-map
files. State the detailed-route boundary and that raw evidence stays local
and outside Git.

## Final verification

Confirm direct and compact production requests use slots; detailed requests
retain the documented legacy path; provider output cannot define stable
structure; partial completion and one-slot repair preserve unaffected hashes;
fixtures replay deterministically; the live batch is complete and frozen;
exactly one next priority is selected; backend/frontend/Playwright/Compose
checks pass; no active live process remains; raw evidence is ignored and
redacted; and the repository is clean.
