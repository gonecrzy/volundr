# Representative workflow waves

The representative-wave runner is a research-only, manifest-driven wrapper
around the existing Gemini requirements, Plan, geometry, source assembly,
static validation, CAD worker, artifact, topology, verification, and candidate
boundaries. It does not change production routing.

The frozen wave-01 manifest is:

`data/debug-sessions/representative-workflow-waves/representative-workflow-wave-01/wave-manifest.json`

The evidence root is:

`data/debug-sessions/representative-workflow-waves/representative-workflow-wave-01/`

All live commands require the exact `gemini_flash_lite_contract_v1` profile and
use only `GEMINI_API_KEY_2`. The baseline is preregistered and all projects run
before product corrections are authorized.

## Commands

From the repository root:

```bash
# Create or verify the evidence tree without provider or worker calls.
PYTHONPATH=backend backend/.venv/bin/python backend/scripts/run_representative_workflow_wave.py \
  --manifest data/debug-sessions/representative-workflow-waves/representative-workflow-wave-01/wave-manifest.json \
  --root data/debug-sessions/representative-workflow-waves/representative-workflow-wave-01 \
  --prepare

# Run every manifest project through the real workflow boundaries.
PYTHONPATH=backend backend/.venv/bin/python backend/scripts/run_representative_workflow_wave.py \
  --manifest data/debug-sessions/representative-workflow-waves/representative-workflow-wave-01/wave-manifest.json \
  --root data/debug-sessions/representative-workflow-waves/representative-workflow-wave-01 \
  --baseline --live

# Resume an interrupted baseline without rerunning completed project IDs.
PYTHONPATH=backend backend/.venv/bin/python backend/scripts/run_representative_workflow_wave.py \
  --manifest data/debug-sessions/representative-workflow-waves/representative-workflow-wave-01/wave-manifest.json \
  --root data/debug-sessions/representative-workflow-waves/representative-workflow-wave-01 \
  --baseline --live --resume

# Generate the complete issue register, causal graph, clusters, and ranking.
PYTHONPATH=backend backend/.venv/bin/python backend/scripts/run_representative_workflow_wave.py \
  --manifest data/debug-sessions/representative-workflow-waves/representative-workflow-wave-01/wave-manifest.json \
  --root data/debug-sessions/representative-workflow-waves/representative-workflow-wave-01 \
  --analyze

# Replay captured responses offline; both modes make zero provider/worker calls.
PYTHONPATH=backend backend/.venv/bin/python backend/scripts/run_representative_workflow_wave.py \
  --manifest data/debug-sessions/representative-workflow-waves/representative-workflow-wave-01/wave-manifest.json \
  --root data/debug-sessions/representative-workflow-waves/representative-workflow-wave-01 \
  --replay

PYTHONPATH=backend backend/.venv/bin/python backend/scripts/run_representative_workflow_wave.py \
  --manifest data/debug-sessions/representative-workflow-waves/representative-workflow-wave-01/wave-manifest.json \
  --root data/debug-sessions/representative-workflow-waves/representative-workflow-wave-01 \
  --counterfactual

# Record the correction ledger, wave decision, and next-wave recommendation.
PYTHONPATH=backend backend/.venv/bin/python backend/scripts/run_representative_workflow_wave.py \
  --manifest data/debug-sessions/representative-workflow-waves/representative-workflow-wave-01/wave-manifest.json \
  --root data/debug-sessions/representative-workflow-waves/representative-workflow-wave-01 \
  --finalize

# Materialize a fresh five-project manifest from the recorded recommendation.
PYTHONPATH=backend backend/.venv/bin/python backend/scripts/run_representative_workflow_wave.py \
  --manifest data/debug-sessions/representative-workflow-waves/representative-workflow-wave-01/wave-manifest.json \
  --root data/debug-sessions/representative-workflow-waves/representative-workflow-wave-01 \
  --next-wave-template --output /tmp/representative-workflow-wave-02.json
```

The manifest is the only wave-specific orchestration input. A future wave
requires a new `wave_id` and a new manifest/project corpus; the runner and
boundary code do not need to be copied or edited.
