# AI Visual Review Plan

Status: Planned next — not implemented

Volundr currently generates deterministic multi-view evidence only. No AI
visual critic, vision-provider call, image-based promotion gate, or visual
similarity score is implemented in this pass.

## Planned next — not implemented

- advisory visual review against the active requirement ledger;
- explicit distinction between advisory observations and blocking evidence;
- review of selected standard views and conservative sections;
- redaction and retention policy for any future image submission;
- reproducible model/provider/prompt metadata;
- human-review handoff for uncertain qualitative findings.

## Guardrails

Any future visual review must not replace deterministic topology, source,
artifact, consistency, or functional gates. It must not promote a blocked
candidate, infer physical strength from pixels, or silently alter the active
requirement ledger. The first implementation should be advisory and
nonblocking, with an explicit rollout decision after deterministic snapshot
evidence and observed usability testing are stable.

Retrieval, helper-example selection, assemblies, collaborative review, and
unrestricted autonomous redesign are outside this plan.
