# Volundr Documentation Map

This file explains exactly what belongs in each project document.

| File | Responsibility |
|---|---|
| `CODEX_KICKOFF_PROMPT.md` | The instruction Codex executes when beginning or resuming foundational work. |
| `README.md` | Repository entry point, project summary, status, and document links. |
| `docs/PRODUCT_DIRECTION.md` | Product purpose, target user, principles, success criteria, and long-term direction. |
| `docs/MVP_SCOPE.md` | V1 inclusions, exclusions, and scope guard. |
| `docs/DOCKER_BASELINE.md` | Canonical service/container names, network name, volume boundaries, and Compose skeleton. |
| `docs/ARCHITECTURE.md` | Approved V1 components, interfaces, Docker service names, runtime flow, storage, and deployment. |
| `docs/MODEL_GENERATION_CONTRACT.md` | Rules for AI-generated OpenSCAD and revision/repair behavior. |
| `docs/CAD_EXECUTION_SECURITY.md` | Isolation, resource limits, source screening, logging, and failure handling. |
| `docs/DATA_MODEL.md` | Persistent entities, fields, relationships, and immutability rules. |
| `docs/CURRENT_STAGE_ROADMAP.md` | Ordered milestones, status, goals, and exit criteria. |
| `docs/TEST_STRATEGY.md` | Unit, integration, end-to-end, fixture, and regression expectations. |

When information conflicts:

1. `PRODUCT_DIRECTION.md` controls product intent.
2. `MVP_SCOPE.md` controls V1 scope.
3. `ARCHITECTURE.md` controls approved implementation defaults.
4. `MODEL_GENERATION_CONTRACT.md` and `CAD_EXECUTION_SECURITY.md` control generated CAD behavior and execution safety.
5. `CURRENT_STAGE_ROADMAP.md` controls work order.
