# External real-world CAD benchmark pilot

This pilot supplements the executable-CadQuery seed/debug and development
corpora. It does not replace them and does not change the production CAD,
recovery, semantic-verification, or provider paths.

## Purpose

The eventual benchmark contains 50 real functional 3D-printable projects in 10
categories, with five projects per category. The initial pilot reserves five
neutral mounting-bracket projects:

- `mounting-bracket-001`
- `mounting-bracket-002`
- `mounting-bracket-003`
- `mounting-bracket-004`
- `mounting-bracket-005`

The slots are deliberately empty until each external source is separately
vetted for availability, attribution, licensing, and functional diversity.

The intended diversity is a selection criterion, not evaluator logic: a small
sensor/electronics mount, a wall/equipment bracket, a machine/tool interface,
a load-bearing or measurement-component bracket, and a more geometrically
involved angled/curved/multi-feature mount.

## Two modes

Each imported project will support two independent runs through the ordinary
Volundr CAD workflow:

1. `premise_only`: a neutral user-like request. The reference geometry, title,
   URL, creator, and hidden exact dimensions are not sent to Gemini. Normal
   clarification is allowed.
2. `reference_specification`: the same functional premise plus intentionally
   selected dimensional facts that a human could reasonably provide. The
   evaluator retains the reference geometry privately; the provider receives
   no reference STL, STEP, BREP, or render.

The original creator description is provenance only. The benchmark premise is
written separately, with creator/site identity and distinctive wording removed
where practical.

## Layout and provenance

Committed pilot metadata is in:

```text
benchmarks/external/mounting-brackets-v1/manifest.json
```

Reference bytes and derived local artifacts belong under the existing ignored
runtime tree:

```text
data/external-benchmarks/mounting-brackets-v1/<project>/
  reference/<part_id>.stl|step|brep
  provenance/<original-source-filename>
  source.json
  premise.txt
  reference-spec.json
  derived-reference.json
```

Reference bytes are evaluator inputs and are not committed by default. The
manifest records the neutral project ID, benchmark/version, category, source
site and URL, creator, source title, license, acquisition date, original file
name, local relative path, file type, and SHA-256. No source URL or model is
invented for an empty pilot slot.

The importer refuses missing or unreadable geometry and never edits the input
file. It copies bytes into the ignored local reference tree, verifies each copy
hash, and writes separate provenance, premise, reference-spec, and derived
fact records. A project may contain one or more explicitly mapped canonical
parts. Each canonical part has a neutral `part_id`, original filename, file
type, SHA-256, and derived geometry facts. Noncanonical source files are
stored under `provenance/` and never affect canonical part count.

The multi-part form is explicit and order-independent:

```json
{
  "canonical_reference_parts": [
    {"part_id": "base", "source_filename": "base.stl"},
    {"part_id": "platform", "source_filename": "platform.stl"}
  ]
}
```

The importer rejects duplicate part IDs, duplicate source paths, missing
membership, malformed later parts, and incomplete projects before updating the
manifest. The original single-file API remains supported.

## Schema and ingestion

The generic manifest supports `development`, `validation`, `holdout`, and
`pilot` assignments. Pilot assignments are placeholders and do not select the
future unseen holdout.

Import one vetted reference with:

```bash
python scripts/import_external_benchmark_reference.py \
  --benchmark mounting-brackets-v1 \
  --project mounting-bracket-001 \
  --source-metadata /path/to/source.json \
  --reference-file /path/to/downloaded-model.stl
```

Repeat `--reference-file` for a multi-part project and use repeated
`--provenance-file` arguments for alternate/source files. The metadata must
map every canonical filename to a unique neutral part ID; input order is not
used for identity.

STL, STEP, and BREP are supported. STL units are explicitly recorded as
`assumed_mm` unless specified by benchmark metadata. STEP/BREP units are
recorded as `unverified_model_units` unless supplied by the source metadata.

Derived facts are generic only: file hash/type, bounding-box sizes, volume,
surface area, center of mass, component/solid counts where defensible, mesh
vertex/face counts for STL, and topology-v2 evidence for STEP/BREP. The layer
does not reverse-engineer semantic features.

Standard-view isometric/front/top/right renders are deferred: existing render
utilities are coupled to generated-output presentation and adding a separate
reference renderer would expand this infrastructure checkpoint. If added
later, renders remain evaluator artifacts and are never sent to Gemini.

## Comparison and run records

The evaluator stores two independent result families:

- `requirement_compliance`: authoritative requirement counts and semantic
  outcomes from the normal Volundr workflow.
- `reference_similarity`: currently bounding-box error by axis, volume and
  surface-area differences/ratios, and solid-count agreement.

For multi-part projects, comparison requires an explicit reference-part to
generated-output mapping. It reports project part-count agreement, per-part
metrics keyed by neutral reference part ID, and aggregate constituent metrics
separately. It never pairs files alphabetically or merges independent parts
for ingestion.

Geometric similarity is not CAD correctness. A valid design may differ from a
creator's reference while satisfying the user's requirements, and a similar
shape that violates an explicit requirement is not a success.

The run schema reserves workflow/revision IDs, provider/model profile,
prompt hashes, provider-attempt IDs, source hash, worker/topology/semantic
results, artifact hashes, reference metrics, failure stage/class, and first
incorrect owner. It is a record around the existing workflow, not a second CAD
generation system.

Deferred metrics include rigidly aligned surface distance, Chamfer,
Hausdorff/P95, volumetric IoU, silhouette/profile similarity, and feature
agreement. They require a separately justified deterministic protocol and are
not part of this pilot-infrastructure checkpoint.

## Scope boundary

This checkpoint makes no provider calls and runs no benchmark designs. It does
not implement B-Rep cylindrical-opening extraction, feature recognition,
reference geometry, repair logic, prompts, model changes, or holdout access.
The next step is to lock and import five live references, then run a small
smoke benchmark through the normal Volundr path before scaling beyond the
mounting-bracket pilot.
