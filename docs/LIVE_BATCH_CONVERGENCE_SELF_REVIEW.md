# Mixed-CAD convergence self-review

This is the post-pair review of all ten projects. It follows the preserved
`codex-review.md` instructions in each frozen batch folder and uses the
existing messages, requirement/design artifacts, generation attempts, worker
events, revisions, findings, and report integrity records. No correction was
implemented during or after the pair.

## Project-by-project review

| Position | Batch 1 | Batch 2 | Review |
| ---: | --- | --- | --- |
| 1 wall carrier | Provider-content block before worker | Provider-content block before worker | Repeated pre-worker convergence/source boundary; no valid geometry |
| 2 portable holder | Source extraction and unchanged repair before worker | Worker output/topology block | Repeated holder-family failure with provider/runtime variability |
| 3 desktop organizer | Invalid JSON/source-generation block | Source-generation artifact inconsistency | Repeated pre-worker provider/source boundary |
| 4 monitor wall mount | Invalid Design Plan before worker | Provenance-invalid Plan and regressive repair | Repeated provenance/repair boundary; physical safety warning retained |
| 5 screw-lid container | Worker reached, verification blocked | Report says not started; attempts show source-generation activity | Repeated screw-lid/source boundary plus an integrity/misleading-state defect |

## Required classification

### Repeated cross-product defects

The provider-to-contract boundary remains the repeated cross-product defect.
Across the pair, valid JSON/envelope normalization often made the response
parseable, but source-generation, design-artifact, provenance, or semantic
contracts still blocked downstream progress. The bounded repair behavior
preserved the first response and stopped unchanged/regressive repairs, but it
did not yield accepted geometry in this pair.

### Repeated same-family defects

The portable holder, organizer, monitor mount, and screw-lid each failed in
the same broad family-specific area in both batches: drainage/topology,
feature/source extraction, Plan provenance, and lid-grip/thread/source
contracts respectively. These are product-family observations, not fixes to
apply in this run. The wall carrier also repeated a pre-worker source/design
artifact boundary stop.

### Provider variability

The same positions did not fail at identical stages or with identical
responses. The holder moved from pre-worker unchanged repair to post-worker
topology; the organizer moved from invalid JSON to artifact inconsistency;
and the screw-lid moved from post-worker verification to a report state that
understated preserved generation activity. These differences are evidence of
provider/runtime variability and should not be overinterpreted as a controlled
CAD-quality improvement.

### Isolated anomalies

The exact `rectangular_pattern_points` contract rejection, the invalid JSON
escape, the missing `modified_shape` assignment, and the lid-grip-ribs
function restriction are isolated signatures. They remain regression
candidates, but none is the one deferred next priority.

### Integrity or misleading-state defects

Batch 2 classified the screw-lid project as `Not started` even though its
preserved generation-attempt chain contains source-generation attempts and a
final attempt left in `started` state. The report must distinguish “no
workflow activity” from “activity existed but did not reach a terminal
accepted/failed state.” This is the highest-confidence integrity defect from
the controlled pair.

The redaction and integrity reports themselves completed without crashing;
absolute worker paths were converted to data-relative evidence and raw
evidence remained local and outside Git.
