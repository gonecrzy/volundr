# Design Artifact Consistency Review

Date: 2026-07-30

## 1. Current Candidate Acceptance Prerequisites

`ProjectService.accept_candidate()` currently permits acceptance when:

- the revision exists,
- `review_state` is `ready` or `ready_with_warnings`,
- no open blocking `ValidationFinding` exists.

It does not require a deterministic certificate tying together Design Specification, Design Plan, CadQuery source metadata, execution parameters, output manifest, and produced artifacts.

## 2. Existing Plan-To-Source Checks

Current source validation checks:

- CadQuery syntax and allowed AST shape,
- `cadquery-v1` runtime contract,
- `ParameterSpec` declaration shape,
- `PrintableOutput` declaration shape,
- explicit user requirement parameter trace via `requirement-trace-v1`.

It does not compare source component IDs, feature IDs, output IDs, output ownership, non-user parameter defaults, required/optional output status, or expected solid-count policy against the approved Design Plan before execution.

## 3. Existing Source-To-Execution Checks

Current execution setup:

- derives submitted parameter values from explicit overrides or Design Plan parameters,
- validates explicit requirement values when a requirement inventory exists,
- computes a submitted parameter hash,
- asks the worker for Design Plan output IDs.

The worker records executed `source_hash`, `parameter_hash`, submitted `parameters`, requested output IDs, produced output IDs, topology metadata, and artifact hashes. Those facts are available for certification, but they are not currently certified as a required candidate gate.

## 4. Existing Output Manifest Checks

The output manifest is generated from persisted `RevisionOutput` rows. It records source hash, parameter hash, output IDs, component IDs, artifact paths/hashes, topology metadata, and dimensions.

There is no current validator proving that:

- manifest output IDs match Design Plan and source identities,
- persisted output rows match worker execution output IDs,
- artifact hashes still match files,
- expected and detected solid-count policy passed for every required output,
- no unexpected output was produced.

## 5. Why The Enclosure Candidate Passed

The enclosure compiled and had no final topology/solid-count rejection, so it could be reviewed and accepted. The lifecycle never required Plan/source identity agreement before acceptance.

The accepted artifact set contained these mismatches:

- Plan components: `base_shell`, `snap_lid`
- Source components: `enclosure_base`, `enclosure_lid`
- Plan outputs: `base`, `lid`
- Source outputs: `base_body`, `lid_body`
- Plan `wall_thickness`: `3.0 mm`
- Source `wall_thickness` default: `2.5 mm`

Those mismatches were only discovered later during component revision, after Revision Plan and revision-generation provider calls.

## 6. Checks Possible Before Execution

Pre-execution certification can deterministically verify:

- Design Specification explicit requirements are represented in the Design Plan through `requirement-trace-v1`.
- required Design Plan component IDs exist in source metadata.
- protected/revision-targetable Design Plan feature IDs exist in source metadata.
- every Design Plan printable output exists as a source `PrintableOutput`.
- source output component ownership matches the Design Plan output ownership.
- Design Plan parameters exist as source `ParameterSpec` entries when directly editable/submitted.
- source defaults match approved Plan values unless an explicit configuration override is being submitted.
- submitted execution parameters are declared by source and match approved Plan values or explicit override values.
- expected solid-count and required/optional status in source metadata match the Design Plan.

## 7. Checks Requiring Execution Artifacts

Post-execution certification requires worker/persisted artifacts:

- every required planned output was returned successfully,
- execution output IDs match source and Plan identities,
- execution source hash matches revision source hash,
- execution parameter hash matches the submitted/persisted parameter hash,
- persisted output records match output manifest entries,
- STEP/STL/BREP paths and hashes exist for produced outputs where expected,
- topology metadata exists for required outputs,
- detected solid count matches expected solid count,
- no unexpected output appears in execution or manifest.

## 8. Proposed Certification Structure

Add a versioned persisted artifact:

```text
design-artifact-consistency-v1
```

Use one DB row pointing to a JSON artifact, following `SourceValidationResult` and revision-compliance conventions. Store:

- project, revision, Design Specification, Design Plan IDs,
- source hash,
- parameter hash,
- output manifest hash,
- pre-execution, post-execution, acceptance, revision-base, and configuration readiness booleans,
- component, feature, output, and parameter mapping summaries,
- stable findings with rule IDs, severities, blocking flags, expected/detected values, and user-safe explanations.

Persist mapping summaries so historical results are explainable without reparsing old source under newer rules.

## 9. Recovery Options For Inconsistent Candidates

User-facing recovery should not ask for more dimensions when the mismatch is internal. Offer:

- regenerate from the approved Design Specification and Design Plan,
- review technical mismatches,
- discard/reject the candidate and keep the previous accepted revision.

Provider-backed metadata/source alignment repair can exist later as an explicit advanced action, but should not be silently invoked during readiness checks.

## 10. Intentional Identifier Differences

Python function names may differ from product identity IDs. This is valid:

```python
@component("base_shell")
def build_enclosure_base(params):
    ...
```

Stable product identities must be explicit in source metadata:

- Design Plan component ID equals source `@component(...)` or `PrintableOutput.component_id`.
- Design Plan feature ID equals source `@feature(...)` for protected or revision-targetable features.
- Design Plan output ID equals source `PrintableOutput.output_id`, execution output ID, persisted output row ID, and output manifest ID.

Fuzzy inferred aliases such as `base ~= base_body` or `snap_lid ~= enclosure_lid` are not acceptable certification evidence.
