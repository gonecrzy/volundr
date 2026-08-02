# Codex Kickoff Prompt — Volundr

This is the current implementation entry point for Volundr. Read
`docs/DOCUMENTATION_MAP.md` first, then load only the task-scoped normative
documents listed there. Current evaluation reports provide evidence; historical
and superseded documents do not override current contracts.

## Mission

Build and maintain a local-first web application that lets one technical owner:

1. Describe a functional 3D-printable product in plain language.
2. Preserve the authoritative requirement ledger.
3. Clarify only materially missing information.
4. Select proportional planning: direct brief, compact plan, or detailed plan.
5. Generate safe CadQuery Python through the configured provider.
6. Execute it in the isolated CadQuery worker.
7. Inspect geometry, topology, artifacts, and requirement evidence.
8. Promote only a passing candidate to the Current working version.
9. Revise indefinitely through chat without requiring reusable parameters.
10. Explicitly export selected successful revisions.

Every design remains revisionable. Parametric controls are optional and must be
explicitly requested; ordinary numeric requirements do not become source
contracts automatically.

## Current architecture

- Frontend: React, TypeScript, and Vite
- Backend: Python 3.12+ with FastAPI
- Database: SQLite with SQLAlchemy and Alembic
- CAD source: CadQuery Python
- CAD execution: isolated `volundr-cad-worker`
- Geometry authority: OpenCascade B-Rep with STL as a derived artifact
- Provider: Gemini API by default, with provider abstraction preserved
- Deployment: Docker Compose with `volundr-web`, `volundr-api`, and
  `volundr-cad-worker`
- Testing: pytest, Vitest, and Playwright

## Authoritative request path

```text
user message
  -> requirement extraction and semantic preservation
  -> essential clarification when needed
  -> proportional direct brief, compact plan, or detailed plan
  -> GeometryExecutionContext normalization
  -> branch-specific prompt context pack
  -> safe structured CadQuery source
  -> source contract and symbol validation
  -> isolated worker execution
  -> topology, functional, artifact, and requirement checks
  -> candidate classification and safe promotion
  -> snapshots, history, revision, comparison, and explicit export
```

Use the existing project, requirement-ledger, planning, generation, worker,
validation, artifact, and Current working version services. Do not create a
parallel lifecycle or requirement store.

## Product boundaries

- Never overwrite an accepted/current revision with a failed attempt.
- Preserve blocked attempts, workflow evidence, source, and diagnostics.
- Keep provider credentials out of the frontend and worker.
- Treat deterministic geometry and topology evidence as stronger than source
  style preferences.
- Keep qualitative claims as human-review or test-print evidence when they
  cannot be proven deterministically.
- V1 supports simple multi-component/output relationships and packaging.
  True assembly mates, ports, kinematics, and mechanism simulation are later
  capabilities.
- Visual AI review, retrieval, embeddings, prior-design learning, and
  collaborative editing are not implemented unless a task explicitly changes
  that scope.

## Working rules

1. Inspect the relevant current contract and call sites before changing code.
2. Preserve original and normalized artifacts when correcting interoperability.
3. Make the smallest generic correction supported by reproduced evidence.
4. Add focused regression coverage before claiming a behavioral fix.
5. Run the task-scoped backend/frontend/Playwright checks and `git diff --check`.
6. Keep historical evaluation reports intact; append dated evidence only when
   a task asks for an evaluation update.
