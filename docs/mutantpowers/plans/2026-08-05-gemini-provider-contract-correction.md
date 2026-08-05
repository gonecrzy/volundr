# Gemini Provider Contract Correction Plan

> **Execution mode:** Inline Execution

Goal: correct the methodology of `gemini-provider-contract-foundation-01`
without altering historical evidence or production behavior.

## Design

Use a continuation directory under the existing study evidence root:
`reports/provider-contract-correction-01/`. Preserve and hash the prior
reports before any live call. Keep intrinsic content denominators separate
from transport/quota outcomes.

The corrected provider profile is selected in stages:

1. Compare S0/S1 using content-bearing responses only; run only the unmatched
   S1 operation.
2. Retain H1 provisionally and validate that its payload omits
   `thinkingConfig`.
3. Keep Plan and geometry at T0. Run a narrow missing-fit requirements study
   against three holdout intentions.
4. Replace the invalid repair packet with three real source-bearing repair
   packets and compare baseline repair versus the bounded-payload prompt.
5. Select requirements and repair prompts independently, then run the exact
   selected settings/H1/stage-prompt profile over a corrected ten-packet
   holdout.
6. Replay through the adapter only after the corrected provider profile
   qualifies; otherwise record the provider rejection and do not authorize
   adapter integration.

No current parser, worker, topology, verification, or production setting is a
selection input. All live calls use only `GEMINI_API_KEY_2`, one shared
secondary-only limiter, and the existing two-attempt retry policy.

## Tasks and rollback points

1. Add the offline methodology audit, historical copies, corrected packet
   definitions, denominator evaluator, and deterministic tests. Verify with
   focused tests; commit `Audit provider-contract correction methodology`.
2. Implement the single-operation S1 replacement and corrected settings
   comparison. Verify call identity, content denominators, and no duplicate
   logical operations; commit `Correct settings evidence denominators`.
3. Add and run the narrow requirements prompt study; commit
   `Add missing-fit requirements prompt correction`.
4. Add real repair packet fixtures, bounded repair contract, evaluator, and
   prompt study; commit `Add real bounded repair contract study`.
5. Select stage-specific prompts and run the corrected H1 holdout; commit
   `Run corrected H1 provider holdout`.
6. Replay qualifying evidence through the adapter and generate corrected
   reports, bundle, and documentation; commit `Record corrected provider and adapter decisions`.

## Verification

Run the correction tests, redaction scan, exact attempt/denominator audit,
full backend suite, frontend tests/build, migration-head check, compile checks,
`git diff --check`, and clean-worktree validation. Stop live work immediately
on an absent secondary key or hard quota condition; do not retry a second
hard quota failure.
