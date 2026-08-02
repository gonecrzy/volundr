# Prompt Context Pack

## Status

Implemented in this pass.

## Selection

Each geometry or repair attempt receives one branch-specific
`prompt-context-pack-v1`. It includes only the context needed for that attempt:

- active requirement IDs and payloads;
- the current revision delta and preserved requirements;
- the selected brief or plan artifact;
- affected components and features;
- the current accepted revision summary when revising;
- relevant blocking findings;
- the structured-body contract and scaffold-owned interfaces;
- explicit exposed controls.

The pack records inclusion reasons, excluded categories, prompt version, token
count when available, and a stable SHA-256 `context_hash`. Unrelated history,
full conversation transcripts, superseded unrelated requirements, old provider
responses, unrelated components, complete debug bundles, and repeated
documentation are excluded by default. Helper/example retrieval IDs are empty
until retrieval is implemented.

## Persistence and reproducibility

The pack is written as an immutable workflow artifact for the generation or
repair attempt. Attempt metadata may index the hash, but the artifact is the
authoritative copy. Identical relevant inputs produce the same hash even when
unrelated history changes. Relevant requirement or revision changes produce a
new hash.

Privacy/redaction follows the existing workflow artifact policy. Packs are
available to diagnostics, reruns, debug bundles, live reports, revision history,
and prompt reproduction without exposing them in normal chat.

For structured geometry generation and repair, the pack also preserves the
affected function's exact symbol inventory and any source-scope diagnostics.
These include the approved signature, parameter access form, allowed helpers,
and repair scope. They are execution evidence, not new requirement or
parametric obligations.
