# Ollama-only five-case results

This document is the result template for the controlled Ollama-only run. The
raw evidence root is local and outside Git:
`data/debug-sessions/ollama-only/<experiment-id>/`.

The first comparison is limited to the five frozen corpus cases, each run
twice per admitted model. Every case is an independently created project and
keeps all provider attempts, clarification rounds, workflow events, worker
results, revisions, artifacts, exports, and integrity findings.

Previous mixed-provider v2/v3 artifacts are retained only as
`excluded_infrastructure_evaluation`; they are not model-quality evidence.
An incomplete pair has no mean consistency score. Missing artifacts and
deleted/archived member projects are recorded as integrity findings rather than
crashing report generation.

Batch result fields to fill after execution:

- experiment and evidence root;
- admitted/excluded model identities and readiness status;
- completed, failed, incomplete, and missing case counts;
- per-case outcomes, retries, clarification rounds, worker reach, and
  integrity findings;
- production-slot versus native-CAD contract status;
- screenshot paths, all local and outside Git.

