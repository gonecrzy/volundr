# Ollama response normalization

Normalization is representation-only. The runner preserves `raw-response.txt`
and writes a separate normalized response with independent raw and normalized
SHA-256 hashes.

Allowed transformations are:

- normalize line endings;
- locate exactly one fenced or unfenced Python candidate and remove both fence
  markers;
- remove unambiguous reasoning wrappers;
- extract one complete JSON object from harmless prose; multiple JSON
  candidates remain rejected;
- sort explicit slot records by slot ID;
- map one unambiguous CadQuery assignment to `result`;
- wrap a normalized native script in the existing worker output contract.

The worker wrapper adds only `PrintableOutput`/`Product` registration. It does
not add an extrusion, hole, dimension, feature, relationship, helper, or
other CAD intent. Multiple plausible final objects remain rejected.

Native full-script and production-slot paths are scored independently. A
native response that returns slot JSON is recorded as
`profile.response_mode_mismatch`, not as CAD-quality failure.
