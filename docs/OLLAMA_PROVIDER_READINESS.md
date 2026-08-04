# Ollama provider readiness

Readiness is an infrastructure and contract gate. It does not establish CAD
quality.

For each admitted model the gate records exact model identity, a cold request,
two warm requests, token progress, completion reason, latency, and the
resource profile. `scripts/ollama/preflight-model.sh` performs the probes and
`scripts/ollama/evaluate-readiness.sh` writes a compact `readiness.json`.

The required classifications are:

- sustained generation: all three requests complete with nonzero evaluation
  tokens and no stream parse error;
- structured output: the native Ollama JSON format probe succeeds;
- production slot: the Volundr `geometry-slots-v1` response contract succeeds;
- native CAD: a standalone CadQuery response is accepted only without
  Markdown fences, file/network/process operations, or other forbidden side
  effects.

The current remote probes passed sustained generation, structured output, and
production slot compatibility for both installed candidates. Both returned
Markdown-fenced native CAD text, so native CAD is currently a response-contract
failure, not a quality score. The five-case run must preserve that distinction.

