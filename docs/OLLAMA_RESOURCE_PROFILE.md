# Ollama resource profile

The admitted model was `qwen2.5-coder:14b`, digest
`9ec8897f747e246e970bc5cfdda85d22f1123dc2e3d34978a010a75968716849`.

Preflight completed before the formal run:

- parameter size: 14.8B;
- quantization: Q4_K_M;
- active context target: 8192;
- context completion: passed;
- classification: `preferred_gpu_resident`;
- observed maximum VRAM: 10,404,390,501 bytes;
- cold latency: 29,411 ms;
- warm latency: 16,597 ms.

The preflight was sufficient to admit the model under the selected resource
policy. It did not predict the later per-case timeouts, so the next run must
measure sustained generation latency and enforce an explicit provider-timeout
gate before claiming comparison readiness.

Raw discovery and preflight records remain local under the experiment evidence
root and contain safe model metadata only; provider credentials are not
written.
