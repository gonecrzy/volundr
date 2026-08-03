# Live batch post-correction comparison

The original frozen pair remains the controlled comparison:

- Batch 1: `e1eb77dd-c6a3-4d62-9a49-72b49aa32c5d`
- Batch 2: `1ec92524-0401-40a2-a0e1-077cb8c52f57`
- Comparison status: `controlled`, identity match: `true`

That claim is historical evidence from before correction round 1. The new
`mixed-cad-live-correction-01` batch is deliberately unpaired and therefore
does not claim a new controlled comparison. It was run to verify the repaired
evidence, identity, classification, redaction, and generic convergence paths.

## Identity conclusion

The qualifying post-correction batch had complete, matching component
identities internally: Git SHA `5361b2a298c3f59e9b0d7c77fe74b509a1892894`,
migration head `0031_widen_debug_batch_identities`, provider `gemini_api`,
model `gemini-3.5-flash-lite`, and the recorded configuration hash. That makes
its evidence attributable, but not a controlled before/after comparison by
itself.

The two earlier qualification attempts are not accepted live results. They
were preserved locally: the first identified missing live frontend identity
injection; the second verified the identity fix and identified a test assertion
reading the `/report` envelope incorrectly. Both were harness qualification
failures, not product-quality claims.

## Comparison decision

Controlled comparison: confirmed for the original frozen Batch 1/Batch 2 pair.

Post-correction Batch 01: identity-complete, redaction-confirmed,
uncontrolled/unpaired verification batch. A future controlled comparison must
run a new unchanged pair after the next generic provider/schema/provenance
correction, with all identity fields matching before the second batch starts.
