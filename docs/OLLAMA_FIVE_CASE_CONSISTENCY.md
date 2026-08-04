# Historical mixed-provider five-case consistency (excluded)

Status: `excluded_infrastructure_evaluation`. This artifact is retained for
failure-preservation history only and is not model-quality evidence.

The formal candidate run was:

`0d82313e-2c04-4125-8bfa-1f3f48072464`

The generated report records five paired case slots for each provider and
reports mean scores of `0.200` for Gemini and `0.840` for Ollama. Those values
must not be treated as a quality ranking: Ollama did not complete a full set of
paired memberships. Its case failures were preserved under the raw evidence
root rather than silently converted into success or omitted.

Gemini completed all ten scheduled case memberships. Ollama completed only the
fixed wall-mount membership in run 1; the remaining Ollama attempts include
read-timeouts and internal-server failures. The report contains one explicit
integrity finding (`endpoint_unavailable` for the wall-mount design
specification) and the raw failure records contain the transport details.

The configuration identities matched for the candidate run, so the comparison
is controlled at the configuration level. It is not sufficient for a
controlled quality claim because provider coverage is incomplete. A follow-up
Ollama-only run is required after the provider repairs. Use
`docs/OLLAMA_FIVE_CASE_RESULTS.md` for the fresh result.

Raw evidence is local and outside Git at:

`data/debug-sessions/model-consistency/0d82313e-2c04-4125-8bfa-1f3f48072464/`
