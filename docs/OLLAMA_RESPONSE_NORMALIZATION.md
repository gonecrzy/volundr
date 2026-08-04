# Ollama response normalization

Normalization is representation-only. The runner preserves `raw-response.txt`
and writes a separate normalized response.

Allowed transformations are:

- normalize line endings;
- remove one outer Markdown fence;
- remove unambiguous reasoning wrappers;
- extract one complete JSON object from harmless prose;
- sort explicit slot records by slot ID;
- map one unambiguous CadQuery assignment to `result`;
- wrap a normalized native script in the existing worker output contract.

The worker wrapper adds only `PrintableOutput`/`Product` registration. It does
not add an extrusion, hole, dimension, feature, relationship, helper, or
other CAD intent. Multiple plausible final objects remain rejected.

Native full-script and production-slot paths are scored independently. A
native response that returns slot JSON is recorded as
`profile.response_mode_mismatch`, not as CAD-quality failure.
