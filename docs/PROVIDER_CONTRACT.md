# Observable Provider and Execution Contracts

This document defines the current integration-facing contracts. It names
ownership and evidence without reproducing full prompts. Versioned prompt
locations are backend/app/services/gemini_integration/prompts.py and
backend/app/services/ai/gemini_cli.py; captured prompt hashes are preserved in
the study evidence. The current integration profile is
gemini_flash_lite_contract_v1.

For the current checkout, the integration prompt-builder hash is
70d7e2a2de058b5a776b771e8f67b51bfd434162ba78272a3a67b131d5bea46e and the
production prompt-builder hash is
827b8004c6face7ac9c2ab3996b88c86d97a90d4f6848093db1360522edba05b. The
profile and boundary hashes are indexed by the audit and captured study
manifests.

The integration qualification records T2 for requirements, the existing Plan
prompt version, and T5 for geometry. The T5 geometry rendering is an explicit
integration runner overlay; it is not a production-route change.

## Universal rules

Every boundary preserves raw input, parsed form, normalized form, hashes,
provenance, validation findings, and failure class. Volundr normalization may
change representation only when the authoritative contract makes the mapping
exact and unambiguous. Intrinsic invalidity fails closed; semantic adapter
repair is not a substitute for provider regeneration.

Provider-owned local implementation is open-ended. In particular, geometry may
use additive, subtractive, intersecting, loft, sweep, revolve, shell, Boolean,
transform, selector, or other valid CadQuery operations supported by the
runtime. No hand-maintained fixture-derived API list, variable list, statement
template, or geometry recipe is an acceptance rule.

## Stage contracts

| Boundary | Observable obligation | Volundr-owned checks and evidence |
|---|---|---|
| Requirements | Preserve user facts, distinguish known from missing fit-critical facts, and return explicit clarification state when needed. | Parseability, meaningful records, no invented critical values, no contradictory readiness, typed evidence, raw response and prompt hash. |
| Plan | Preserve requirement traceability, meaningful components/features, valid references, output obligations, and protected facts. | Reference validation, identity/provenance mapping, output-count and readiness checks, typed Plan evidence. |
| Geometry | Return exactly the assigned slot identities and fulfill each slot responsibility using authorized inputs. | Slot identity, authorized inputs, Python syntax, definite symbol use, protected values, responsibility, final result-symbol assignment, CadQuery validation, typed geometry evidence. |
| Printable-output identity | Keep one unambiguous Volundr-owned runtime identity through assembly and execution. | Map Plan id to canonical worker output_id once at source assembly; reject missing, duplicate, or conflicting identities; preserve mapping provenance. |
| Source assembly | Produce a complete scaffolded CadQuery source unit from the accepted Plan and geometry evidence. | No semantic repair, source hash, scaffold hash/version, protected symbols, exact output manifest, static contract findings. |
| Worker | Execute only the assembled source in the isolated CAD worker with the requested outputs. | Study/job provenance, canonical requested IDs, execution status, traceback, resource/timeout evidence, no provider credential. |
| Artifact | Collect the artifacts actually produced for each requested output. | Output ID, format, path, digest, size, completeness, and artifact findings; missing artifacts block closed-loop success. |
| Topology | Inspect the produced artifact/model without changing its meaning. | Per-output topology, solid counts, validity, disconnected/empty findings, expected-output identity, and raw topology capture. |
| Verification | Evaluate deterministic and requirement-linked evidence against the accepted Plan. | Verification findings, protected-fact status, artifact/topology linkage, severity, and blocking status. |
| Candidate decision | Resolve the evidence into one explicit outcome. | Candidate/blocked/review decision, all blocking findings, provenance, and correlation to the same study/project/revision. |

## Geometry invariants

The geometry protocol constrains only: response structure; exact manifest slot
identity; required result-symbol identity; authorized external inputs; valid
executable Python; symbol definition and use; protected-fact preservation;
assigned responsibility; and absence of unrelated slot work. Provider variable
names are unrestricted valid local Python identifiers. A Workplane, Shape,
Assembly, or other valid runtime result is accepted when it satisfies the
authoritative slot contract and the runtime's intrinsic checks.

## Identity and provenance

The Plan representation may carry a printable output's source id. At the
integration source-assembly/worker-request boundary, Volundr performs the one
explicit mapping to output_id. The worker manifest, artifact records, topology
records, verification, and candidate decision use output_id. Both source and
canonical values, mapping rule, study ID, project/revision IDs, and integration
marker remain in evidence. No fallback or semantic guessing is allowed.

## Failure ownership

Diagnosis follows the first incorrect boundary through the causal chain:

```text
authoritative manifest -> rendered prompt -> raw response -> parsed response
  -> contract validation -> source assembly -> worker -> artifact
  -> topology -> verification -> candidate decision
```

Provider misunderstanding, invalid provider content, parser loss, validator
false rejection, unstated assembler requirements, worker execution, artifact
collection, topology, verification, and harness defects remain distinct issue
owners. Multiple independent issues are recorded together; the earliest
advancement blocker does not erase later evidence.
