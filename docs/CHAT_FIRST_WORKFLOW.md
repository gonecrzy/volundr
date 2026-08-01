# Chat-First Workflow

When `VITE_VOLUNDR_CHAT_FIRST=true` and `VOLUNDR_CHAT_FIRST=true`, the
conversation is the normal workflow control surface. The initial message
authorizes a first draft; no requirements, Design Plan, or generation approval
button is required.

The frontend submits one `POST /api/projects/{project_id}/chat` message. The
backend deterministically routes it to requirement extraction, clarification,
parameter configuration, structural/component revision planning, start-over,
or export. Existing Design Specification, Design Plan, Revision Plan,
generation, worker, source, topology, consistency, and functional gates remain
authoritative.

```text
message -> requirements -> Design Plan -> first draft -> validation
                                      -> Current working version
```

Only a passing revision may be promoted. A blocked attempt is retained in
history and leaves the previous Current working version unchanged. Parameter
messages use deterministic configuration and do not call a provider. Structural
and component messages persist an internal Revision Plan before generation.

Chat requests accept a `client_message_id`; duplicate submissions return the
stored response. A generation completion checks that its base is still the
current revision before promotion, preventing stale work from overwriting a
newer version.

“Start over” creates a new specification/plan/revision lineage while preserving
prior accepted versions. Export is always explicit and supports STL, STEP, and
the complete project package. Technical evidence remains available through
workflow runs and diagnostic bundles.

The staged/developer UI remains available when the flag is false so existing
diagnostic workflows can be maintained during rollout. After deterministic
chat-first and live gates pass, remove the staged user-facing controls and
retain only their internal service contracts and diagnostic tests.

The chat-first presentation is a persistent three-region workspace: the
conversation is the normal control surface, the viewer shows the current or
selected version, and the inspector keeps requirements, proposals, checks,
printable parts, history, and technical evidence visible without making
approval controls part of the normal path. At narrower widths the inspector
becomes a drawer or Details tab. See
`docs/CHAT_WORKSPACE_FRONTEND_EVALUATION.md` for the current evidence.

## Persistence And Export

Project URLs use `/projects/{project_id}` and reload from the backend workspace
aggregate. The workspace response includes messages, active requirements,
revision history, current working version, active workflow, and artifact
integrity. A stale interrupted run is recoverable as evidence and does not
silently restart provider work.

Export remains an explicit user action. It creates a durable `ExportRecord` for
the selected successful revision with deterministic filenames and hashes.
Blocked attempts cannot be exported, and duplicate requests resolve to the
same completed record.

Ordinary numeric values are not automatically controls. The active
requirement ledger records user requirements, proposals, revision deltas, and
physical-test observations. A revision may regenerate the source completely;
it never depends on the original source exposing a reusable parameter. Only an
explicit request such as “Expose bottle diameter as an adjustable control”
activates the strict source-effect contract for that control.

Planning is invisible in normal chat. The backend chooses a direct brief,
compact plan, or detailed plan from ledger and project semantics, then
continues automatically through the same generation and validation lifecycle.
Narrow revisions may use deterministic revision briefs; interacting or
multipart changes retain provider-backed Revision Plans.

After worker output, the same workflow may attach deterministic standard-view
snapshots, component thumbnails, conservative sections, and a comparison to
the prior revision. This evidence is nonblocking and remains secondary to the
authoritative requirement, validation, artifact, and Current working version
records.
