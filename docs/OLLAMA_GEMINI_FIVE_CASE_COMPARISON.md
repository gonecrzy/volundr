# Ollama / Gemini five-case comparison

## Decision

The candidate comparison is controlled by matching configuration identity, but
not valid for a quality conclusion. Do not select Ollama or Gemini based on the
reported mean scores from this run.

The matching identities were Git HEAD, migration head, provider/model policy,
prompt versions, configuration hash, and backend/frontend/worker build
identities. The comparison artifact records no identity mismatches. The
provider coverage, however, is asymmetric: Gemini completed 10/10 scheduled
memberships, while Ollama completed 1/10 and preserved nine failure attempts.

## Evidence

The formal raw evidence is local and outside Git:

`data/debug-sessions/model-consistency/0d82313e-2c04-4125-8bfa-1f3f48072464/`

Generated summaries are under the corresponding ignored
`debug-sessions/gemini-consistency/<experiment-id>/reports/` directory. The
v2 run is excluded because it failed on the Ollama provider initialization
path; it is not part of this comparison.

## Repair conclusion

The next action is a repair-and-rerun gate, not a model choice. Fix the
failure-path integrity exception, make incomplete provider pairs ineligible for
quality means, and resolve or explicitly accommodate Ollama timeout and
structured-output failures. Then rerun the same five cases with the same
configuration and no product fixes during execution.
