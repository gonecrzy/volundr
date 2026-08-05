# Current Trajectory

This is the concise entry point for current Gemini-provider integration work.
Historical study conclusions remain evidence; they do not silently redefine
production behavior. The observable boundary contracts are in
[PROVIDER_CONTRACT.md](PROVIDER_CONTRACT.md), and the reproducible offline
loop is in [INTEGRATION_TEST_LOOP.md](INTEGRATION_TEST_LOOP.md).

## Product objective

Volundr is a self-hosted, single-user application for generating, executing,
verifying, revising, and exporting functional 3D-printing products. CadQuery
Python is the editable source of truth; the isolated CAD worker executes it,
STEP is the primary geometry artifact, and STL is derived for preview and
printing. Every accepted design remains revisionable through chat.

## Provider-first adaptation

The provider owns semantic design meaning and local construction strategy.
Volundr owns protocol safety, lifecycle identity, provenance, source assembly,
execution, artifacts, topology, verification, and candidate decisions. Generic
adapters may normalize exact representation differences, but they do not invent
fit facts, repair invalid geometry, or redesign provider output. The first
incorrect boundary is fixed at that boundary and the preserved raw response is
replayed through every downstream boundary.

Geometry is intentionally an obligation contract, not a miniature CAD
language. The provider may choose any valid CadQuery strategy supported by the
runtime. Universal checks cover the assigned slot, authorized inputs, valid
Python, symbol definition/use, protected facts, assigned responsibility, and
the authoritative final result symbol. Local names, helper count, statement
count, workplanes, orientations, and construction methods remain provider
owned.

## Frozen integration configuration

The current integration foundation is explicitly isolated as
gemini_flash_lite_contract_v1:

```yaml
model: gemini-3.5-flash-lite
provider_profile: gemini_flash_lite_contract_v1
settings:
  profile: S0-current-explicit
  temperature: 0.2
  topP: 0.95
  topK: 40
  candidateCount: 1
  seed: omitted
thinking:
  profile: H1-provider-default
  thinkingConfig: omitted
stage_prompts:
  requirements: T2-requirements-missing-fit-v1
  plan: T0-current
  geometry: T5-geometry-exact-slot-contract-v1
repair: not currently qualified or required for representative workflow
integration_status: integration_foundation_ready_for_representative_workflow
production:
  routing_changed: false
  deployed: false
```

The base profile source retains the historical generic geometry version for
compatibility with the unchanged production path; the qualified integration
runner explicitly renders and records the T5 geometry contract shown above.
This distinction is intentional and does not change production routing.

The versioned integration prompt builder and profile source are
backend/app/services/gemini_integration/prompts.py and
backend/app/services/gemini_integration/profile.py. Their audited hashes,
along with adapter and boundary hashes, are recorded in the integration
captures and docs/audit/script-and-code-inventory.json.

At this checkout the source hashes are: integration profile
54698954c522f35832f778f3103f2d9f9395b37741a9df8ea864629f7a9abfec,
integration prompt builder
70d7e2a2de058b5a776b771e8f67b51bfd434162ba78272a3a67b131d5bea46e, and
production Gemini prompt builder
827b8004c6face7ac9c2ab3996b88c86d97a90d4f6848093db1360522edba05b.

## Ownership and routing

Requirements preserve missing fit-critical facts and may stop for explicit
clarification. Plan preserves requirement traceability, component/feature
meaning, and output obligations. Geometry fulfills the authoritative slot
manifest. Source assembly combines those obligations with the Volundr scaffold.
The worker executes the assembled source in isolation. Artifact collection,
topology inspection, verification, and candidate resolution are independent
evidence boundaries.

The integration runner is research-only, requires the exact profile above, and
uses an explicit study ID and integration provenance marker. Normal production
routing cannot activate it. Production files, prompts, adapters, and provider
selection were not changed by the integration qualification or this audit.

## Credentials, rate limits, and retries

Integration live calls, when separately authorized, use only GEMINI_API_KEY_2;
there is no fallback to the primary key. Production uses the configured API
credential only in the API process. The browser and CAD worker receive no
provider credentials.

The integration limiter is shared, monotonic, single-concurrency, and enforces
a five-second minimum gap, the 12-request default, and a hard 15-request
rolling 60-second ceiling. Retry behavior is bounded and captured: the first
429 may retry after the prescribed delay, transport failures have their
prescribed retry, and no unbounded or third attempt is allowed.

## Evidence and replay policy

Raw requests, responses, attempts, rate-limit events, hashes, manifests,
worker captures, artifacts, topology, verification, and decisions are
immutable evidence. Derived reports may be regenerated but are not removed
without a hash-verified replacement manifest. Offline replay and one-variable
counterfactuals run before any additional live call. A differential replay
attributes an outcome change only to the boundary deliberately changed.

Every new project contributes its provider capture, issue/root-cause record,
generalized regression fixture, owning-boundary correction, and replay across
prior captures.

## Current test loop

The loop is:

```text
request -> requirements -> clarification -> Plan -> geometry
  -> source assembly -> worker -> artifact -> topology
  -> verification -> candidate decision
```

The harness records every real boundary independently. It reports the earliest
blocker for advancement and all detectable issues for diagnosis; advancement
is not proof that latent downstream defects are absent. See
INTEGRATION_TEST_LOOP.md for commands and gates.

## Known limitations and next phase

The geometry qualification is a targeted 6/6 result for the identified
geometry-contract failure mode, not a universal capability claim. The current
integration foundation has not qualified representative complete workflows,
repair, or broad project coverage. The next product-development phase is a
representative progression across varied projects, expanding the generalized
regression corpus from each observed failure. It is not another broad provider
tuning study.

Reopen settings or prompt selection only when representative evidence shows a
reproducible provider-owned failure after the current contracts and boundaries
have been replayed, when a new project family changes the measured objective,
or when a transport/model policy change invalidates the frozen configuration.
Do not reopen them because one fixture is inconvenient or because a parser,
validator, assembler, or worker boundary has an unresolved defect.
