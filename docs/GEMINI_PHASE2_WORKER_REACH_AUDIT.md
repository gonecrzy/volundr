# Gemini Phase 2 worker-reach audit

The audit uses these non-overlapping definitions:

- `source_contract_passed`: final assembled source passed hard source-contract
  validation.
- `worker_ready_valid_source`: source contract passed, source was submitted,
  and a worker job was created.
- `worker_reached`: a job was created or execution began.
- `worker_completed`: execution terminated normally with a structured result.
- `worker_runtime_failed`: the worker executed source and returned a runtime or
  CadQuery exception.
- `topology_valid`: preserved topology evidence passed the topology gate.
- `cad_success`: completed execution, valid topology, and a ready artifact;
  worker reach alone never qualifies.

## Corrected counts

| Arm | Contract pass | Worker-ready | Worker reached | Worker completed | Runtime failure | Topology valid |
|---|---:|---:|---:|---:|---:|---:|
| current-production | 4 | 3 | 3 | 3 | 0 | 3 |
| profile-b-sampling | 3 | 2 | 2 | 1 | 1 | 1 |

Profile B case-006 has a source-contract pass, job ID
`3043fdb1-e061-4787-b208-844a21637796`, submitted source, and a worker
traceback ending in `ValueError: More than one wire or face is required` from
CadQuery `loft`. It therefore counts as worker-ready, worker-reached, and
worker-runtime-failed. It does not count as worker-completed, topology-valid,
or CAD success.

The historical `worker_ready_valid_source: 0` for both arms was an aggregation
defect: it read a project-level field instead of the nested source-contract,
job, execution-manifest, and output evidence. The corrected machine-readable
record is `reports/phase-2-worker-reach-audit.json`.
