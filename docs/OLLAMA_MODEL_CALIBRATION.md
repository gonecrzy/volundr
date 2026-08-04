# Ollama model calibration and admission

Calibration is a separate phase from the formal five-case benchmark. The
runner uses one active model and one generation at a time, preserves raw
responses outside Git, and records normalized representations separately.

Final evidence: `data/debug-sessions/ollama-calibration/calibration-final-pass/`

The experiment recorded:

- base commit `b288cc1ea3e19a587e18ac7822b21ef95cc8f7ca`;
- `origin/main...HEAD = 0 1` (the requested local commit was preserved);
- exact model names and full digests from `/api/tags` and `/api/show`;
- no Gemini calls;
- no formal five-case benchmark;
- no concurrent model loads or generations.

Each model passed identity and sustained cold-plus-two-warm operational checks.
Operational success is not treated as CAD quality.

| Model | Infrastructure | Production | Native CAD | Holdout | Admission |
| --- | --- | --- | --- | --- | --- |
| CAD-Coder Q8 | passed | incompatible | validated | failed | deferred for profile resolution |
| ProCAD-coder Q8 | passed | incompatible | partially validated | blocked | deferred for profile resolution |
| Qwen2.5 CadQuery Q4 | passed | incompatible | partially validated | blocked | deferred for profile resolution |
| Qwen2.5-Coder 14B Q5 | passed | partially compatible | partially validated | blocked | deferred for profile resolution |
| DeepSeek-Coder-V2-Lite Q4 | passed | incompatible | partially validated | blocked | deferred for profile resolution |
| C3Dv0 | passed | incompatible | partially validated | blocked | deferred for profile resolution |

No model was admitted. The later benchmark is therefore explicitly
unauthorized.
