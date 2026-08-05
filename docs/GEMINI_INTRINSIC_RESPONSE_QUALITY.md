# Gemini Intrinsic Response Quality

Intrinsic quality is provider-only evidence. It scores requirements, Plan,
geometry, and repair responses against frozen packet meaning without reading
current parser, worker, topology, verification, or candidate state.

Every response receives exactly one result: `pass`,
`pass_with_benign_format_variation`, `fail_incomplete`, `fail_conflicting`,
`fail_invented_critical_meaning`, `fail_invalid_api`,
`fail_undefined_symbols`, `fail_structurally_empty`,
`fail_wrong_output_obligation`, `fail_wrong_geometry_strategy`,
`transport_failure`, or `quota_failure`.

Consistency is reported separately through semantic, structural, identity,
decision, geometry-strategy, byte, entropy, and canonicalization metrics.
Transport and quota failures are evidence of availability and are excluded
from model-content scoring.

The implementation is the pure module
`backend/app/services/gemini_consistency/provider_contract.py`.
