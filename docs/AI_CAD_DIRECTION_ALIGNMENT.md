# AI CAD Direction Alignment

## Status

- Conversation-first: Implemented
- Requirement-ledger authority: Implemented
- Indefinite chat revisionability: Implemented in this pass
- Optional exposed controls: Implemented
- Proportional planning depth: Implemented in this pass
- Safe ordinary geometry reaching execution: Implemented in this pass
- Deterministic evidence over source-style preference: Implemented
- Advisory visual review: Planned next
- Smallest-scope repairs: Planned next
- Retrieval and assemblies: Later
- Product shell, persistence, Current working version safety, and selected revision exports: Implemented

## Normative direction

Volundr is conversation-first and requirement-led. The active requirement ledger
is authoritative; a brief, compact plan, detailed plan, source body, and prompt
pack are immutable execution artifacts derived from it.

Every design remains revisionable through chat. Parametric controls are optional
and explicitly requested. A numeric requirement does not imply a reusable source
parameter, and a design is not blocked merely because its implementation is not
generalized for future values.

Planning depth is proportional to semantic complexity: a deterministic direct
brief for a sufficiently specified single part, a compact plan for interacting
features, and the existing detailed plan for multipart or assembly relationships.
All routes use the existing generation, worker, validation, candidate, history,
and export lifecycle.

Deterministic B-Rep, topology, artifact, and functional evidence outranks source
style preferences. Qualitative behavior that cannot be proven from available
geometry remains human-review or test-print evidence rather than a false pass.

Visual review will initially be advisory. Retrieval, examples, and richer
assemblies remain later phases. Unrestricted live user CAD-quality testing stays
separate from deterministic UX fixture testing until the live evidence supports
it.

## Derived dependency classification — Implemented in this pass

Derived metadata remains observable without becoming an unconditional source
style gate. Dependencies that serve exposed controls, configurable patterns,
scaffold obligations, or generated geometry remain blocking. Unused malformed
derived metadata is retained as a warning and ordinary geometry is judged by
worker and post-worker evidence. See
`docs/DERIVED_DEPENDENCY_CLASSIFICATION.md`.

## Provider source scope — Implemented in this pass

Ordinary requirement-led designs remain free to use literals or local
expressions. That freedom does not make unresolved Python names acceptable.
Structured geometry bodies receive an exact scaffold-owned symbol inventory;
loaded names are checked with conservative lexical and definite-assignment
rules before worker submission. A safely identified runtime `NameError` can
enter one targeted body repair, while unidentified failures remain blocked.
This is source correctness, not a return to strict source parametrization.
