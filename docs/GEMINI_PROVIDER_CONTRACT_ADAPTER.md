# Gemini Provider Contract Adapter

`GeminiProviderContractAdapter` is a pure generic adapter. It parses provider
responses, normalizes only allowed aliases, attaches Volundr-owned identity
and provenance, maps supplied slots and result symbols, and emits detailed
actions with before/after semantic hashes.

It never adds missing meaning, dimensions, features, operations, provenance,
verification, or CAD repairs. Ambiguity and intrinsic contract failures are
rejected. Complete provider-owned geometry source is preserved verbatim; the
adapter does not invoke the current parser or worker.

Offline replay accepted all 12 selected live records. Historical replay
accepted 24 of 109 records and rejected known bad or transport records. The
holdout replay accepted 17 of 20, matching the intrinsic quality result. The
adapter is therefore not authorized for end-to-end integration while the
provider contract itself is unstable.
