# Gemini System-Boundary Methods Study
> **Execution mode:** Inline Execution

**Goal:** Determine whether Gemini provider configuration, bounded Volundr-owned response processing, and a narrowly targeted prompt variant provide the safest stable end-to-end CAD foundation, without changing default production behavior.

**Study identity:** `gemini-system-boundary-methods-01`

**Evidence root:** `data/debug-sessions/gemini-system-boundary-methods/gemini-system-boundary-methods-01/`

## Architecture

- Add an experiment-scoped processing module under `backend/app/services/gemini_consistency/`. It receives the provider-authored response and stage context, preserves the original, and returns a processed response only for an explicit benchmark processing header. The default path remains byte-for-byte current behavior.
- Reuse the existing Volundr API, isolated database/data directories, Gemini API provider, CadQuery worker, source validators, topology gates, evidence capture, and Profile B generation override. Add no production configuration change and no Ollama path.
- Use a shared monotonic limiter for all live calls in the study: concurrency one, 12 starts/minute default, 15/rolling-60s hard cap, five-second minimum gap, and no hard-429 retry.
- Build an offline replay/analyzer over the preserved Phase 1 and audited Phase 2 evidence. It must be provider/worker-free and must fail closed on semantic or identity ambiguity.
- Generate one self-contained redacted manual-review JSON in addition to ordinary per-call/per-project evidence.

## Execution tasks and rollback points

### Task 1 — Preregister and snapshot the study
**Files:** `backend/app/services/gemini_consistency/system_boundary_methods.py`, `backend/scripts/run_gemini_system_boundary_methods.py`, `backend/tests/test_gemini_system_boundary_methods.py`, study evidence root reports.

- [ ] Record repository, migration, packet/case, profile, and historical-report hashes.
- [ ] Copy source reports under `reports/historical/source-evidence/` without modifying the original experiment tree.
- [ ] Write `study-preregistration.json` before any provider call, including hypotheses, candidates, gates, cases, metrics, rate policy, and decision vocabulary.
- [ ] Add failing tests for preregistration immutability, source preservation, and zero-call offline mode.
- [ ] Verify RED, implement, run focused tests, and commit as `Add study preregistration and replay framework`.

### Task 2 — Implement bounded processing candidates
**Files:** `backend/app/services/gemini_consistency/system_boundary_methods.py`, benchmark-only provider/API plumbing, focused tests.

- [ ] Implement P0 through P5 as explicit transformations with provenance/action logs and before/after semantic and integrity hashes.
- [ ] Keep code-fence/envelope cleanup and generic aliases conservative; restore only uniquely authoritative Volundr-owned metadata; fail closed on ambiguous IDs or prior-shape sources.
- [ ] Ensure P3 reruns source validation and never changes operation order, numeric literals, completed slot hashes, or provider-owned meaning.
- [ ] Add tests for all listed safety requirements, including worker/reach, verification, and production-default invariance.
- [ ] Verify RED/GREEN and commit as `Add bounded processing candidates`.

### Task 3 — Run offline replay and select a processing method
**Files:** study reports and documentation.

- [ ] Replay all 30 Phase 1 records, all 35 preserved Phase 2 provider calls, and all ten Phase 2 projects against P0–P5.
- [ ] Produce `offline-processing-replay.json`, `processing-method-scorecard.json`, and `processing-method-decision.json`.
- [ ] Select exactly one method only if it passes every safety gate, improves at least two records/projects, advances at least one source/worker/blocker metric, and is generic across two object types/stages; otherwise write a gated `run:false` result.
- [ ] Commit as `Complete offline processing ablation` after fresh replay and tests.

### Task 4 — Add and verify the live factorial harness
**Files:** `backend/scripts/run_gemini_system_boundary_methods.py`, benchmark API/provider plumbing, rate/capture tests.

- [ ] Run only if Task 3 qualifies a method.
- [ ] Execute 12 operations: case-001, case-003, case-006 × current/Profile B × P0/winner, with identical frozen facts, clarification continuation, case order, worker settings, validation gates, and retry policy.
- [ ] Capture original and processed provider records, exact model identities, generation configs, limiter events, and full project workflow evidence.
- [ ] Stop on hard quota failure and leave completed operations resumable; do not retry hard 429.
- [ ] Produce factorial results and comparison with descriptive provider, processing, interaction, and case effects.
- [ ] Commit harness as `Add corrected provider-processing factorial harness`; commit live result as `Run factorial comparison`.

### Task 5 — Classify residual defects and gate prompt work
**Files:** `backend/app/services/gemini_consistency/system_boundary_methods.py`, `residual-model-defects.json`, tests/docs.

- [ ] Attribute every remaining failure to provider, processing, Volundr, worker, topology, verification, harness, mixed, or insufficient evidence.
- [ ] Authorize prompt work only for a repeated or representative critical provider-owned defect that bounded processing cannot repair.
- [ ] Commit as `Add residual-defect ownership analysis`.

### Task 6 — Run the targeted prompt micro-study if authorized
**Files:** experiment prompt variant, prompt-study runner, tests/reports/docs.

- [ ] If gated, run exactly 12 calls across the three frozen stage packets × Profile B current/targeted prompt × two repetitions.
- [ ] Change only the pre-registered stage language; hold Profile B generation settings, seed, packet input, scoring, and winning processing constant.
- [ ] Select the targeted variant only if all floors pass, the defect is fixed in two applicable records, and no semantic/identity/provenance/consistency regression occurs.
- [ ] Commit as `Add targeted prompt variant when justified` and `Run prompt micro-ablation` as applicable; otherwise retain explicit `run:false` reports.

### Task 7 — Run final two-system validation and record decision
**Files:** final runner/report generation, required reports/docs/tests.

- [ ] Select two finalists only from configurations justified by prior gates; do not automatically include the targeted prompt.
- [ ] Run exactly five cases × two finalists = ten complete operations with answered clarifications and no tuning between cases.
- [ ] Produce `final-system-validation-results.json`, `final-system-comparison.json`, `final-system-boundary-decision.json`, and `all-methods-manual-review.json`.
- [ ] Update required documentation, run all verification checks, inspect diffs, and commit as `Run final two-system validation` and `Record final system-boundary decision`.

## Verification ladder

- Focused deterministic processing/replay/rate/capture/redaction tests.
- Source validator and worker replay tests; migration-head and compile checks.
- Full backend suite; frontend tests/build; read-only Playwright smoke check only.
- Confirm no calls to Ollama, no unregistered Gemini calls, no hard-429 retry, exact cap compliance, preserved historical hashes, unchanged production defaults, complete redacted bundle, and clean worktree.

## Safety and rollback

- Never modify `data/debug-sessions/gemini-profile-ablation/gemini-profile-ablation-01/`.
- Never use destructive git operations or rewrite prior commits.
- Each commit above is a verified rollback point. Live evidence is append-only and resumable.
- If a gate fails, record `run:false` for later phases and stop without weakening thresholds.
