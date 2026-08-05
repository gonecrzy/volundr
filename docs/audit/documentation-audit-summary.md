# Documentation and Evidence Audit Summary

Schema: `volundr-repository-audit-v1`. The audit was designed to run offline and
does not call a provider or CAD worker.

## Current authoritative documents

- `docs/CURRENT_TRAJECTORY.md`
- `docs/INTEGRATION_TEST_LOOP.md`
- `docs/PROVIDER_CONTRACT.md`
- `docs/STUDY_INDEX.md`

## Inventory totals

- Documentation files: 226 ({"current_authoritative": 4, "current_supporting": 51, "historical_immutable": 149, "historical_superseded": 21, "unknown_requires_review": 1})
- Test and fixture items: 188 ({"historical_integrity_only": 10, "retain_current": 170, "retain_regression": 8})
- Study directories indexed: 4075
- Study records indexed: 189
- Script/provider-code items: 96
- Reference-graph nodes: 699

## Retention and cleanup decisions

- Files retained: all inventoried documentation, tests, scripts, provider code,
  raw captures, attempts, hashes, provenance, artifacts, topology, verification,
  and historical decisions.
- Files updated: the new authoritative documents, the root README entry point,
  and links/redirect notices recorded in the audit decisions.
- Files archived: none unless a separate manifest records the path and hash.
- Files removed: none; immutable evidence and ambiguous historical items are not
  deletion candidates.
- Tests retained: all current, regression, tooling, and historical-integrity
  tests pending explicit evidence of safe consolidation.
- Tests rewritten or consolidated: none inferred from pass/fail alone.
- Unresolved review items:
- `docs/REPRESENTATIVE_WORKFLOW_WAVES.md`
- `existing migration schema drift reported by alembic check`

## Automated checks

- Stale-reference check passed: `True`
- Broken documentation links: 0
- Stale active-document findings: 0
- Migration head/current: 0036_benchmark_model_metadata; the read-only schema
  check reports pre-existing nullable/index drift owned by migration maintenance.

The next development phase is representative complete workflows. Historical
provider winners and repair experiments are indexed as evidence; they do not
override the integration foundation or production routing.
