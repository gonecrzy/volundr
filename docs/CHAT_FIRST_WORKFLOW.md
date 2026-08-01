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
