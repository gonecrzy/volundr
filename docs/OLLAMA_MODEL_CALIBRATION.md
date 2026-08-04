# Ollama model calibration and admission

Calibration is a separate phase from the formal five-case benchmark. The
runner uses one active model and one generation at a time, preserves raw
responses outside Git, and records normalized representations separately.

Final evidence: `data/debug-sessions/ollama-calibration/calibration-admission-report/`
Starting-point evidence: `data/debug-sessions/ollama-calibration/calibration-live-all-remaining/`

The experiment recorded:

- starting base commit `b288cc1ea3e19a587e18ac7822b21ef95cc8f7ca` and
  `origin/main...HEAD = 0 1` are preserved in the starting-point evidence;
- the committed-code final runs record their source run roots and current
  divergence in `experiment.json`;
- exact model names and full digests from `/api/tags` and `/api/show`;
- no Gemini calls;
- no formal five-case benchmark;
- no concurrent model loads or generations.

Each model passed identity and sustained cold-plus-two-warm operational checks.
Operational success is not treated as CAD quality.

| Model | Infrastructure | Production | Native CAD | Holdout | Admission |
| --- | --- | --- | --- | --- | --- |
| CAD-Coder Q8 | passed | not tested | validated | failed | operational low CAD quality |
| ProCAD-coder Q8 | passed | not tested | partially validated | failed | operational low CAD quality |
| Qwen2.5 CadQuery Q4 | passed | not tested | validated | failed | operational low CAD quality |
| Qwen2.5-Coder 14B Q5 | passed | partially compatible | validated | failed | operational low CAD quality |
| DeepSeek-Coder-V2-Lite Q4 | passed | not tested | validated | failed | operational low CAD quality |
| C3Dv0 | passed | not tested | partially validated | failed | operational low CAD quality |

No model satisfied specialist/generic admission after fair holdout checks. The
later benchmark is therefore explicitly unauthorized. The queue retains the
CAD findings, accepted slot limitations, and all original issue paths.
