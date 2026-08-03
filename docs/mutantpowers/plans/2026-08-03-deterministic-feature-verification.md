# Deterministic feature verification and source-to-result traceability

## Objective

Implement generic, deterministic evidence for geometry-slot outputs. The
system must separately report source declaration, provider-function execution,
geometry presence, and requirement measurement, while preserving existing
requirement findings and candidate gates. Use the frozen portable-holder and
desktop-organizer evidence, then run one focused `feature-verification-live-01`
batch. Do not change screw-lid or monitor generation.

## Execution approach

This is an inline execution plan. Each implementation phase is TDD-gated:
write focused failing tests, run the smallest relevant test set to establish
RED, implement the smallest generic change, then run the same tests to reach
GREEN before moving on.

## Phases and commit points

1. **Frozen evidence reconstruction** — inspect the preserved portable and
   organizer source, manifests, topology, artifacts, requirement targets, and
   findings; classify every unresolved feature finding and record the evidence
   table in `docs/DETERMINISTIC_FEATURE_VERIFICATION.md`.
2. **Source-to-result evidence (commit 1)** — add compact runtime feature
   traces to the generic CadQuery runner and persist them through output and
   validation-finding metadata. Cover execution, shape identity, summaries,
   operation category, and trace findings.
3. **Generic measurements (commit 2)** — add reusable shape/topology/void/
   compartment measurement primitives and semantic tolerance handling; persist
   evidence records and reconcile existing requirement findings without
   product-specific verifier classes.
4. **Bounded feature repair (commit 3)** — extend the existing repair boundary
   with one feature-informed, localized repair operation, protected unaffected
   output/slot hashes, remeasurement, and rejection of unchanged or unrelated
   results.
5. **Frozen regressions (commit 4)** — add redacted portable and organizer
   fixtures plus the required backend regression matrix, including missing,
   ambiguous, topology, tolerance, repair, candidate, and physical-warning
   cases.
6. **Frontend and deterministic browser coverage (commit 5)** — expose compact
   technical evidence and truthful states in existing developer surfaces; add
   frontend tests and 1440x900 Playwright scenarios with ignored local
   screenshots under `data/debug-sessions/feature-verification-deterministic/`.
7. **Verification gate and live batch (commit 6)** — run backend/frontend,
   build, geometry, Playwright, Compose, health, and diff gates; run and freeze
   `feature-verification-live-01` with the five unchanged mixed-CAD prompts,
   preserving route, contract, worker, artifact, trace, measurements, repair,
   provider, token, latency, finding, and candidate evidence.
8. **Documentation and next priority (commit 7)** — record the live results,
   update the required current documentation without rewriting historical
   reports, freeze the repository, and select exactly one next priority without
   implementing it.

## Verification checklist

- source names and provider claims never satisfy a requirement by themselves;
- absent, disconnected, removed-later, unmeasured, failed, missing, and
  ambiguous features remain distinguishable;
- final geometry and authoritative topology drive candidate state;
- one feature repair is at most one user operation and is remeasured;
- physical engineering warnings remain independent of geometric success;
- all required tests, build, browser, Compose, health, and diff checks pass;
- raw evidence and screenshots remain local and outside Git; the repository is
  clean after the seven intended commits.
