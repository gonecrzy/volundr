# Revision Evidence Model

Status: Implemented in this pass

Revision evidence is a deterministic comparison between worker-produced
artifacts for a parent revision and a later revision. It explains observable
change without claiming that a source diff or a rendered image proves physical
correctness.

## Comparison manifest

`revision-comparison-v1` records:

- `from_revision_id` and `to_revision_id`;
- the user revision instruction;
- requirement-delta and preserved-requirement IDs when available;
- intended and observed changed component IDs;
- before/after bounding-box dimensions, volume, solid count, and component
  count;
- signed geometry deltas for dimensions and volume;
- standard-view pairings with before/after image artifact IDs;
- camera-direction matching and shared/separate scale evidence;
- added, removed, resolved, and still-blocking validation finding rule IDs;
- a stable `comparison_hash`.

The comparison is persisted as a workflow artifact and uses a unique path for
each generation. It is generated only when both the parent and new revision
have usable snapshot context; missing evidence is recorded rather than
invented.

## Interpretation

Metrics answer “what changed measurably?” View pairs answer “which
deterministic visual evidence corresponds to that change?” Finding deltas
answer “which known validation outcomes changed?” None of these answers
whether a qualitative behavior such as one-handed removal or snap durability
is physically demonstrated.

The existing validation and promotion gates remain authoritative. A revision
that fails topology, source, consistency, functional, or candidate policy
cannot become Current working version merely because its images look similar.
A passing revision is promoted by the existing workflow engine, and the prior
version remains recoverable.

## User-facing evidence

The workspace keeps the interactive viewer primary. The secondary Views panel
shows standard snapshot thumbnails, optional sections when present, warnings,
and a lightbox. A revision comparison panel shows paired views and compact
geometry metrics. Technical details retain artifact IDs, timings, hashes, and
validation evidence.

Project-library thumbnails use the latest accepted/successful snapshot when
one exists, while the project and revision records remain the source of truth
for current-version state.
