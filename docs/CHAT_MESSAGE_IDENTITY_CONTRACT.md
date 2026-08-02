# Chat Message Identity Contract

Status: Implemented 2026-08-02.

The chat ledger contains one visible user message for each actual submission.
Client message IDs provide idempotency; workflow records reference that message
instead of inserting another visible copy.

## Authoritative submissions

Initial requests, clarification answers, revisions, physical-test feedback,
and start-over requests are persisted as `ProjectMessage` rows with the
client-supplied message ID when available. A repeat with the same project and
client ID returns the stored workflow response and does not create a second
submission or assistant outcome. Two different client IDs remain two
intentional submissions even when their text is identical.

The authoritative message may be linked to the resulting revision. Generation
attempts and workflow events retain IDs and metadata, not another user-visible
copy of the instruction.

## Clarification provenance

Clarification answers remain explicit user evidence with source
`clarification_user`. They retain the question ID, answer ID, raw wording, and
project-message ID through the requirement ledger and later revisions.
Volundr-selected alternatives remain `volundr_proposal` and are not presented
as user choices.

## Legacy records and rendering

Older runs may contain a user-role workflow instruction without a client ID.
When its revision/workflow linkage and matching authoritative submission make
its internal origin unambiguous, the read API exposes it as `system_event` so
the frontend filters it without destructive history rewriting. Ambiguous
records are not deduplicated by text alone.

Assistant progress, clarification, success, and blocked outcomes are likewise
persisted once per workflow outcome. A retry preserves the prior evidence and
does not create duplicate visible outcomes for the same idempotent submission.

## Non-goals

This contract does not delete historical records, merge intentional duplicate
submissions, replace workflow events, or redesign the frontend conversation.
