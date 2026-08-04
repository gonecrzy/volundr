# Historical mixed-provider five-case compatibility (excluded)

Status: `excluded_infrastructure_evaluation`; completed as a compatibility
probe, not a clean quality comparison and not a model-quality result.

The revised benchmark used exactly five frozen cases from
`benchmarks/ollama-consistency-v1.json`:

- vague phone stand;
- desktop organizer;
- two-tray holder;
- fixed monitor wall mount;
- screw-lid container.

The formal candidate was experiment
`0d82313e-2c04-4125-8bfa-1f3f48072464`, using Gemini
`gemini-3.5-flash-lite` as the anchor and the explicitly admitted remote
Ollama model `qwen2.5-coder:14b`. Both models were scheduled for two API runs,
with 20 memberships retained. No browser submission was used.

Compatibility evidence shows that the Ollama route, model selection, seed
settings, evidence creation, and normal project workflow were reachable. The
Ollama result was operationally incomplete: one case produced a completed
membership and nine case attempts were materialized as failure evidence,
including read timeouts and internal-server errors. Therefore this run proves
route compatibility and failure preservation, not model suitability.

The prior v2 run is excluded because all Ollama operations failed before model
execution due a missing provider policy object. It is historical diagnostic
evidence only.

The fixed monitor wall-mount case remains a geometry/workflow evaluation. No
report or UI state may imply load-bearing safety; physical engineering and test
review remain required.
