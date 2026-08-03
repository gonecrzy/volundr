# Geometry slot contract

Status: implemented for direct and compact generation.

`volundr-geometry-slots-v1` makes stable executable structure a Volundr
responsibility. The backend derives an ordered internal slot manifest from the
approved Design Plan and renders the existing CadQuery scaffold. The provider
returns only a JSON list of slot records containing ordered statements and one
result symbol per slot.

## Route boundary

- `direct_brief` and `compact_plan` select the slot contract in `auto` mode.
- `detailed_plan` retains the existing `legacy_contract` path.
- `legacy_contract` and `geometry_slots_v1` can be selected explicitly through
  the advanced backend setting `VOLUNDR_GEOMETRY_CONTRACT_MODE`.
- The provider never chooses slot count, order, function IDs, signatures,
  scaffold code, imports, declarations, entrypoints, or stable parameters.

The provider-facing brief is reduced. It contains slot IDs, authorized
parameter IDs, required inputs, exposed helpers, and the required result. The
full manifest remains an internal execution artifact and is persisted with the
existing prompt-context and attempt evidence.

## Validation and bounded recovery

Volundr rejects duplicate or unknown slots, missing/extra records, imports,
declarations, unsafe names, unbound symbols, invalid parameter access,
unsupported helpers, invalid result symbols, and unauthorized changes to
completed slots. Canonical statements are hashed per slot before the existing
scaffold is rendered.

One focused completion may request only missing or invalid slots. Completed
slot hashes are preserved. Before worker submission, an incomplete or
unrepairable slot response may make one recorded fallback request through the
legacy contract. After worker diagnostics identify one affected function, one
localized slot repair may replace that slot; unaffected slot hashes must stay
unchanged. Existing source validation, worker isolation, topology, geometry
verification, candidate, revision, and Current working version gates remain
authoritative.

## Evidence

The implementation records the selected contract, slot count, focused
completion, fallback reason, slot JSON, original statements, canonical slot
bodies, scaffold manifest, and hashes as ordinary generation-attempt/workflow
artifacts. It does not create a second workflow or event system. Normal chat
shows only the existing outcome; contract telemetry is limited to technical
details for support and review.

The monitor-wall-mount case remains a geometry/workflow evaluation only. A
passing mesh or geometry check is not a load-bearing safety claim; physical
engineering and test review warnings remain explicit.
