# Live debug batch implementation

This document defines the developer-assisted live evaluation surface. It is
separate from ordinary project use and from observed frontend usability
testing. Normal project creation and workflows remain unchanged when
`VOLUNDR_DEVELOPER_TOOLS_ENABLED=false`.

## Capability and authorization

The single backend-authoritative setting is:

```text
VOLUNDR_DEVELOPER_TOOLS_ENABLED=false
```

It is an advanced deployment setting and is intentionally absent from the
minimal `.env.example`. `GET /api/capabilities` exposes only the safe boolean
`developer_tools_enabled`. Every debug-batch route depends on the same server
check: start, list/detail, finish, report, evidence download, frontend evidence
submission, and comparison. Hiding a button is only a usability measure; it is
not authorization. Provider credentials, policy files, and internal settings
never enter the browser.

## Persistence and correlation

The implementation adds only `debug_batches` and ordered
`debug_batch_memberships`. Membership points to the project identifier without
making project deletion cascade into the evidence record, so a deleted or
archived member becomes an explicit integrity condition in the report.

Only projects created while a batch is active are attached. Opening an existing
project, editing an unrelated project, and later revisions do not attach it.
Membership is inserted in the same transaction as project creation. A unique
partial database index allows only one active/finishing batch, and ordered
membership positions are unique within a batch. Finishing is idempotent and
freezes membership; a frozen batch cannot accept new members.

The batch stores immutable comparison metadata: Git HEAD and branch, migration
head, provider, configured model, stage model policy, actual provider models,
prompt versions, configuration hash, backend/frontend/worker build identities,
and start/finish timestamps. Downstream evidence is correlated through the
existing project → messages/workflows → attempts → worker jobs → revisions →
artifacts/exports chain. No batch ID is added to every existing table.

## Evidence storage and redaction

Raw evidence stays local and outside Git under the durable data root:

```text
data/debug-sessions/<batch-id>/
```

The path is ignored by Git. Reports materialize bounded copies of authoritative
messages, requirement/planning artifacts, prompt context, attempts, source,
worker results, findings, snapshots, revisions, exports, and frontend network or
error evidence. They do not create a competing workflow or event system.

The redaction pass scans rendered prompts, provider responses, generated source,
worker output, screenshot metadata, and frontend network evidence. It removes
API keys, authorization headers, cookies, database credentials, secret
environment values, and unnecessary absolute host paths. The frontend capture
allowlist contains only event type, safe endpoint path, project/revision/
workflow IDs, visible error kind, HTTP status, and timestamp. It never captures
unsent drafts, keystrokes, pointer movement, response bodies, or unrelated
browser activity.

## Read-only reporting

Finishing and regenerating a report only collect existing evidence. They do not
retry providers, rerun workflows, regenerate geometry, create candidates,
promote revisions, create reporting-only exports, rewrite messages, or alter
project timestamps. Missing projects or artifacts become integrity findings and
do not crash report generation. A failed report can be regenerated without
changing frozen membership.

## Comparison and safety boundary

Batch 2 is controlled only when Git HEAD, migration head, provider, model policy,
prompt versions, configuration hash, and backend/frontend/worker build
identities match Batch 1. Every mismatch is persisted, the comparison is
uncontrolled, and the planned controlled live run must stop until the
configuration is restored.

The monitor-wall-mount scenario is a geometry and workflow evaluation only.
Passing geometry does not imply load-bearing safety. Reports retain explicit
physical engineering and test-review warnings.

## Testing separation

Deterministic Playwright controls and screenshots validate the developer surface
and authorization behavior. Observed usability testing remains a separate
facilitated track using deterministic fixtures and must not be reported as
developer-assisted real-provider live-batch evidence.
