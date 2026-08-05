# Integration Test Loop

The integration-only harness exercises the real provider adapter and real
execution boundaries in order:

```text
request
  -> requirements
  -> clarification
  -> Plan
  -> geometry
  -> source assembly
  -> worker
  -> artifact
  -> topology
  -> verification
  -> candidate decision
```

The canonical live-capable runner is
backend/scripts/run_gemini_provider_contract_integration.py. Geometry
qualification is the narrower reproducibility runner
backend/scripts/run_gemini_geometry_prompt_narrow_fix.py. Both are
integration-only, require gemini_flash_lite_contract_v1, and write under an
explicit study ID with an integration provenance marker. Neither is reachable
through normal production routing.

## Request and evidence

Before a live gate, the runner freezes the request, profile, settings, prompt
versions/hashes, manifest, corpus, and credential policy. Each boundary writes
an independent capture with raw input/output, parsed and normalized values,
hashes, findings, failure class, operation ID, and provenance. The worker is
never treated as proof that a provider response was valid; artifact, topology,
verification, and candidate evidence are separate captures.

## Earliest blocker and all issues

The runner records the earliest blocker that prevents safe advancement, but it
also performs forensic checks that do not require unsafe continuation. A later
issue remains real even when an earlier issue prevents the normal workflow from
reaching it. Reports therefore distinguish earliest_blocker, the complete
issue register, and the causal graph.

For each issue, preserve:

- the authoritative manifest and rendered prompt;
- raw provider response and parsed response;
- contract validation findings;
- source-assembly expectation;
- first incorrect boundary and owner;
- whether the defect is provider, adapter, parser, validator, assembler,
  worker, artifact, topology, verification, or harness owned;
- independent issues that coexist in the same response.

## Offline replay and counterfactual isolation

Offline replay is the default. It uses captured evidence and makes zero
provider and worker calls. Counterfactuals change one boundary or one artifact
at a time: corrected rendering with the same manifest; corrected parser with
the same raw response; corrected validator with the same parsed response;
known-valid generalized fixture through the current validator; or the original
provider response through source assembly without semantic repair. Synthetic
success is never included in provider-quality metrics.

Differential replay compares the same captured inputs and records the first
changed outcome, changed evidence hash, and owner of the changed boundary.
Replay reports must distinguish live provider attempts from offline report
generation calls and must preserve the original capture hashes.

## Live-call gates

No live call is allowed until:

1. the profile is exactly gemini_flash_lite_contract_v1;
2. the secondary credential policy is satisfied with no primary fallback;
3. the study ID, provenance marker, preregistration, and output directory are
   explicit;
4. offline replay and required counterfactuals have completed;
5. the live operation count, rate/retry policy, and stop condition are fixed;
6. no production routing or product behavior is being changed by the run.

The audit and replay commands are provider-free. The repository audit command
is:

```bash
PYTHONPATH=backend backend/.venv/bin/python backend/scripts/audit_repository.py
```

Use the integration runner's --replay, --counterfactual, or --dry-run modes
for captured evidence. A live mode is a separately authorized operation, not
part of normal tests.

## Regression growth

Fixtures test protocol machinery, not a miniature CAD language. Generalized
valid fixtures cover varied CadQuery strategies, local helpers, statement
counts, result forms, arbitrary slot IDs, and single- or multi-slot responses.
Negative fixtures target actual universal invariants. A new project contributes
its preserved provider capture, issue/root-cause record, generalized fixture,
owning-boundary correction, and replay across all prior captures.

## Representative project waves

The targeted geometry result establishes only that the identified geometry
failure mode's correction passed its qualification packet. The next phase is a
wave of representative complete workflows across varied projects. Each wave
expands coverage and the regression corpus; it does not reopen provider
settings or prompt wording unless a provider-prompt defect is isolated after
the complete causal chain has been tested.
