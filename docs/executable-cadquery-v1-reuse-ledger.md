# Executable CadQuery v1 Reuse Ledger

This ledger records the components selected for the isolated Gemini complete-source experiment. The experimental route is additive and disabled by default.

| Existing component | Standardized output | Experimental disposition | Reason |
| --- | --- | --- | --- |
| `backend/app/services/cad/cadquery_contract.py` | `cadquery-v1` AST metadata and contract findings | Reused unchanged for source screening; narrowly extended only if canonical output checks require a non-geometry helper | The provider must return worker-compatible complete source. |
| `backend/app/services/cad/cadquery_runner.py` | Sandboxed compile result, diagnostics, topology metadata, STL/STEP/BREP hashes | Reused unchanged | The experiment must measure Gemini source against the existing executor. |
| `backend/app/services/cad/worker_client.py` and `backend/app/services/cad/jobs.py` | Filesystem job submission/result loading | Reused unchanged | Existing worker boundary already provides isolation and timeout behavior. |
| `ProjectService` revision/output persistence | Durable source, revision, per-output worker state, exports, source/artifact hashes | Narrowly extended with a complete-source entry point and semantic-plan override | This avoids source reconstruction while retaining existing artifact ownership. |
| `GeometryAnalyzerRegistry` and `FunctionalGeometryVerifierRegistry` | Mesh-level semantic findings and verification states | Reused through a contract-to-verifier projection | Volundr selects requirement facts; it does not select CadQuery construction. |
| `feature_measurements.py` and `feature_evidence.py` | Dimension, opening, position, and topology evidence | Reused | Existing measurement behavior covers the frozen fixture’s obligations. |
| `ValidatedCadQueryWorkflow` and `ValidatedCadQueryOutput` | Product workflow state, outputs, package metadata, safe diagnostics | Reused; experimental service uses route identity and provenance JSON | Existing tables already support workflow/read/poll/package behavior. |
| `ValidatedCadQueryOperation` | Idempotency identity | Reused unchanged | Start, accept, package, and revision requests remain retry-safe. |
| `ValidatedCadQueryProviderAttempt` and validated Gemini transport | Credential slots, attempt IDs, request hashes, 429 fallback | Reused; experimental logical operation metadata is additionally recorded in provenance | Transport retries stay attempts under one provider operation. |
| `ValidatedCadQueryWorkflowService` | Authentication, ownership, artifact download, acceptance, reconciliation | Reused by subclass/composition for common operations | The legacy service remains authoritative when the experimental flag is false. |
| `frontend/src/ValidatedCadQueryWorkflowView.tsx` | Chat-first workflow review and controls | Reused and narrowly extended with experimental status/presentation | The experiment must appear in the existing workspace shell. |
| Current reconstruction/scaffold/geometry-slot route | Provider fragments or Volundr-assembled source | Bypassed only for the experimental route | Gemini owns each complete source unit; Volundr never splices or reconstructs it. |
| Codex proxy adapter | Geometry-only Codex routing | Not used | The objective explicitly forbids calling the Codex proxy. |
| New migration | Typed repair-session columns/table | Not used initially | Existing JSON/provenance fields represent the required state without a schema invariant gap. |
