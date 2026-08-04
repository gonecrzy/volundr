# Ollama installation and import gate

This is the installation record for the Ollama-only evaluation. The remote
endpoint is an advanced deployment dependency, not a browser dependency. The
minimal `.env.example` remains unchanged.

The endpoint must pass `/api/version`, `/api/tags`, `/api/ps`, `/api/show`,
`/api/generate`, `/api/chat`, and `/api/pull`. `scripts/ollama/probe-server.sh`
records those responses and timings. `install-models.sh` uses only the Ollama
pull API for registry models. Safetensors/GGUF checkpoints that require host
conversion are explicitly recorded as excluded when host filesystem access or
an exact import recipe is unavailable; they are never silently skipped.

The verified remote inventory for this run is:

| Model | Installation status | Evidence | Evaluation status |
| --- | --- | --- | --- |
| `joshuaokolo/C3Dv0:latest` | installed | exact digest, size, quantization, `/api/show` | admitted to readiness and five-case candidate |
| `qwen2.5-coder:14b` | installed | exact digest, size, quantization, `/api/show` | admitted to readiness and five-case candidate |
| `dagbs/deepseek-coder-v2-lite-instruct:q4_k_m` | pending | registry identity found, not pulled | explicit pending exclusion |
| published specialist GGUF/Safetensors candidates | host import required | no authorized host import path | explicit exclusion |

Raw evidence is stored locally under `data/debug-sessions/ollama-only/` and
outside Git. It is redacted before durable write and the directory is ignored
by Git. No API key, cookie, authorization header, database credential, or
unnecessary host path belongs in the evidence.

