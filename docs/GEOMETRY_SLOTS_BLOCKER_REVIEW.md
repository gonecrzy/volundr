# Geometry-slots blocker review

Status: complete for frozen batch
`8ea3488d-940b-44de-9ed1-772efef6597f`. This is an evidence review and a
narrow state-integrity correction record. It does not implement a CAD
generation correction, bypass compact-plan validation, add helpers, or run a
second live batch.

The authoritative evidence is the preserved local batch directory:

`/tmp/volundr-live-e2e.VMFoAm/data/debug-sessions/8ea3488d-940b-44de-9ed1-772efef6597f/`

The historical `live-batch-manifest.json` is retained as evidence of the
state-integrity defect. Its preliminary project outcome is not used as an
authoritative result below; the frozen `report.json`, project summaries,
workflow events, attempts, worker manifests, output manifests, and findings
are authoritative.

## Authoritative blocker table

“Slots after completion” means the final normalized slot response count; it
does not mean that source, worker, topology, or candidate gates passed.
Connected-component count was not persisted by either worker manifest and is
reported as unavailable rather than inferred from shell count.

| Project | Route | Geometry contract | Initial valid slots | Slots after completion | Source valid | Worker reached | Worker execution | Artifacts | Topology | Feature verification | Final blocker |
| --- | --- | --- | ---: | ---: | --- | --- | --- | --- | --- | --- | --- |
| wall carrier | compact plan | slot route not reached | — | — | no | no | not reached | none | not reached | not reached | `plan.validation.blocked` / compact-plan normalization |
| portable holder | compact plan | `volundr-geometry-slots-v1` | 1/6 | 6/6 | yes | yes | exit 0, `execution_failed`, output shape invalid | none; all hashes/paths null | invalid: 1 expected, 2 detected, 2 shells | not reached as a terminal gate | `worker_runtime_failure` |
| desktop organizer | compact plan | `volundr-geometry-slots-v1` | 1/6 | 6/6 | yes | yes | exit 0, successful | STEP/STL/BREP present | valid: 1 expected, 1 detected, 1 shell | five critical `requirement.*` findings blocked verification | `verification_blocked`; stale required-output state recorded as integrity |
| monitor wall mount | detailed plan | `legacy_contract` | — | 0 | yes | no | not reached | none | not reached | not reached | `design_artifact_inconsistent` before worker |
| screw-lid container | compact plan | `volundr-geometry-slots-v1` | 0/9 | 9/9 | yes | no | not reached | none | not reached | not reached | `design_artifact_inconsistent` before worker |

Each project has one earliest authoritative blocker. Later symptoms are not
promoted to primary blockers: the portable topology event follows the worker
execution failure, and the portable candidate event is explicitly marked a
downstream symptom.

## Worker-reaching project analysis

### Portable holder

- Submitted source hash:
  `2afff2e111e92f670b111eca3cb030fd53ad5fc29bfb44745f102207258f7e10`.
- The initial slot response preserved slot `0`; slots `1`–`5` were invalid
  because their bodies used unbound names. One focused completion call was
  made for exactly those five slots and returned all six slots. The preserved
  slot-0 hash was
  `746797e563a1e2ed5028af7ab8d55d0d716c7d47eb8b809baacc7a57d022afac`.
- The worker exited with code `0` at the process level but reported
  `execution_failed` and `output shape is invalid` for required output
  `print_tackle_holder`.
- No STEP, STL, or BREP artifact was produced; all output paths and hashes
  were null and STL size was zero.
- The requested output manifest expected one solid. The worker detected two
  solids and two shells, with connected-component count unavailable. The
  measured bounds were 303 × 195 × 98 mm and volume was
  501,535.159 mm³. The topology outcome was `solid_count_mismatch` and
  `valid: false`.
- The candidate event recorded one failed output and is marked a downstream
  symptom. No artifact-readiness or feature-measurement gate could have
  changed this result.

Classification: **`worker_runtime_failure`**. The invalid topology is a
corroborating geometry defect, but the earliest terminal event is the worker
failure.

### Desktop organizer

- Submitted source hash:
  `a207cff966328381c16324856372b796d7babecefdeaefcbc6105184ca493e5d`.
- The initial slot response preserved slot `0`; slots `1`–`5` were invalid
  because their bodies used unbound names. One focused completion call was
  made for those five slots and returned all six slots. The preserved slot-0
  hash was
  `58e736698afcd8459fb6c8480e53127855862435f283b5a2a426fe69e4be4786`.
- The worker exited successfully and produced the required
  `desktop_organizer_output` STEP, STL, and BREP artifacts. Their recorded
  hashes were:
  - STL: `53caad916965fc3c2b6f605815d95f0eadeea9c6203eb8c2995de04deb132f6e`;
  - STEP: `f48af7308a192e49e233fc8e49871fe0b21f73418f2f49aa0e4f0cb318c11f23`;
  - BREP: `d4d6940a7f306238abec11dddfeb4a04dc65fe6d4e33bc676ebc8831ef5c0960`.
- The required output expected one solid and detected one solid and one shell.
  Topology was `valid: true`. The bounds were 220 × 140 × 65 mm and volume
  was 249,379.235 mm³. Connected-component count was unavailable in the
  persisted manifest.
- The materialized output state was nevertheless `blocked`, producing the
  stale `design_artifact.manifest_required_output_not_ready` finding even
  though registered STEP/STL/BREP artifacts and topology passed. The resolver
  now preserves that original finding and records it as a nonblocking
  integrity warning.
- Five requirement findings were independently blocking:
  `requirement.req_one_piece`, `requirement.req_phone_slot`,
  `requirement.req_pen_compartment`, `requirement.req_accessory_compartments`,
  and `requirement.req_cable_notch`. Those findings, not the stale manifest,
  kept promotion blocked.

Classification: **`verification_blocked`**. This is not
`artifact_readiness_blocked`: artifacts and topology passed, while applicable
requirement verification remained blocked.

## Feature-verification counterfactual

Deterministic feature verification alone would have changed **neither**
worker-reaching final outcome.

- Portable holder: **no**. The worker failed, artifacts were absent, and
  topology was invalid before a feature-measurement-only decision could help.
- Desktop organizer: **no**. The worker and topology gates passed, the stale
  manifest state was reconciled, and the candidate remained blocked only by
  the independent requirement-verification findings.

This directly rejects deterministic feature verification as the next
generation blocker for this batch.

## Compact-plan normalization review

The wall-carrier block recorded `plan.layout_semantics_missing` and pattern
alias normalization findings. The screw-lid block recorded
`plan.layout_pattern_linked` and pattern alias normalization findings. The
persisted normalized plans contained `plan_ready` structures with explicit
components and printable outputs; the findings themselves were nonblocking
warnings, even though the workflow recorded a blocking normalization outcome.

The failures are best classified as unsupported provider representation and
layout/normalization interoperability. They are not evidence of provider-
authored identity ownership, component ownership loss, provenance loss,
validation-target mapping loss, or actual missing design meaning. The accepted
requirements contain enough information to construct a stable Volundr-owned
component/output/slot manifest shape. They do not, by themselves, prove every
layout relationship or product-specific semantic needed to bypass the accepted
Plan record safely. No bypass is implemented in this review.

## Slot-completion review

The portable holder and desktop organizer showed the same pattern:

1. six slots were requested;
2. slot `0` was valid and retained;
3. slots `1`–`5` contained `geometry_body.unbound_name` findings;
4. one focused completion call targeted only slots `1`–`5`;
5. the completion returned all six slots;
6. the preserved slot-0 hash was retained unchanged;
7. the completed source passed source validation and reached the worker.

The focused call did not fail due to response shape, parser order, duplicate
IDs, or a slot-count mismatch. The evidence supports **acceptable bounded
partial completion with repeated provider omission/unbound-name generation**;
prompt salience is a plausible contributing cause, but this batch cannot
separate it from provider variability. It is not a focused-completion
reliability blocker, and slot-count overload is not established.

## Manifest/report integrity correction

The defect was in the live harness: `runProject` inferred `candidate` from
the presence of any succeeded revision before the batch was finished, while
the frozen report resolved the final state from worker, topology, artifact,
verification, and candidate evidence. That produced `candidate` for the
desktop organizer even though the frozen report correctly said `Blocked after
worker`.

The correction is intentionally narrow:

- `resolve_project_outcome` is now the shared authoritative resolver for the
  frozen report, batch drawer, and comparison outcome fields;
- `codex-review.md` receives its outcome table from the frozen report
  summaries;
- the live manifest helper maps project outcomes from the finished report's
  `summary.projects` and never from revision presence;
- artifacts alone cannot create a candidate outcome;
- report regeneration remains evidence-only and does not change membership or
  call a provider or worker.

The historical frozen manifest is not rewritten; it remains the regression
evidence that proves the bug. Newly materialized manifests now agree with the
authoritative frozen report.

## Actual next priority

Exactly one priority is selected:

**Generic geometry/topology convergence.**

This is selected because both projects that reached the worker failed to
become valid candidates, the earliest worker-reaching blocker was a runtime
output-shape/solid relationship failure, and the other worker result was
blocked by required-output readiness despite valid topology. It is a generic
frontier across product families and is supported by executed worker evidence.

The alternatives are rejected for this review:

- **Deterministic feature verification:** rejected by both counterfactuals;
  no worker outcome was blocked solely by unavailable deterministic feature
  measurements.
- **Compact-plan-to-slot convergence:** two compact plans were blocked before
  the worker and the accepted requirements can support a stable manifest
  shape, but safely bypassing all Plan semantics is not proven by this batch.
  It is a follow-on investigation, not the selected priority.
- **Slot completion reliability:** rejected because both observed focused calls
  recovered all five invalid slots, preserved the completed slot, passed source
  validation, and reached the worker.

No selected CAD correction is implemented in this review.
