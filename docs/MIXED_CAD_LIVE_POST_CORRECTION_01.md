# Mixed CAD live post-correction 01

This is the single qualifying post-correction live verification batch. Raw
evidence remains local and outside Git at:

`/tmp/volundr-live-e2e.VWUxlv/data/debug-sessions/0ba9c31b-5d0e-440e-b34b-7b766afa1d39/`

The repository stores this summary and the implementation/tests only; the
durable raw batch folder is not authoritative when copied into Git.

## Configuration identity

- Label: `mixed-cad-live-correction-01`
- Batch ID: `0ba9c31b-5d0e-440e-b34b-7b766afa1d39`
- Git HEAD: `5361b2a298c3f59e9b0d7c77fe74b509a1892894`
- Migration head: `0031_widen_debug_batch_identities`
- Provider: `gemini_api`
- Configured model: `gemini-3.5-flash-lite`
- Configuration hash: `76d0ab528fa8eba60a8cb272c80ab3ad1afcd5fa54862bea020f0d788fae55d3`
- Backend/frontend/worker identities: the same Git SHA, `dirty=false`, and
  the same build timestamp; `identity_complete=true`.
- Provider retries: `0`; content repairs: `2`; provider calls: `14`;
  generation attempts: `14`; workflow-stage attempts: `40`.

The five prompts were unchanged from the frozen mixed-CAD batches. Each
project received the existing fact-sheet answers, no more than two clarification
rounds, and the existing one-retry policy. No code, prompt, provider/model,
environment, policy, image, schema, or retry-policy fix was applied during the
run.

## Results

| Project position | Final classification | Worker reached | Provider calls | Content repairs |
| --- | --- | ---: | ---: | ---: |
| 1 wall-mounted carrier | post-worker verification block | yes | 3 | 0 |
| 2 portable holder | post-worker topology block | yes | 3 | 0 |
| 3 desktop organizer | provider content failure | no | 3 | 0 |
| 4 fixed monitor mount | provider content failure | no | 2 | 1 |
| 5 screw-lid container | provider content failure | no | 3 | 1 |

The funnel was: 5 projects created, 5 requirements completed, 3 source
contracts passed, 2 geometry executions reached, 2 workers reached, 1
snapshot produced, 0 valid geometries, 0 promoted working versions, and 0
exports. The report recorded no integrity findings and redaction was confirmed.

The repeated report signature was candidate classification on two projects.
The project-specific post-worker findings were a verification block for the
carrier and a disconnected-solid/topology block for the portable holder. The
three pre-worker stops were provider/schema/provenance/content convergence
failures, including two bounded content repairs.

## Screenshots

Screenshots are retained with the raw evidence, outside Git:

`/tmp/volundr-live-e2e.VWUxlv/data/debug-sessions/0ba9c31b-5d0e-440e-b34b-7b766afa1d39/screenshots/`

The folder contains batch start/empty/drawer/finish/summary captures and
initial/final captures for all five projects. The final browser run passed its
durable-evidence path and secret scan.

This was not a second batch for controlled comparison. The earlier frozen pair
remains the controlled comparison; this run is a post-correction verification
of the same prompt set.
