# Parametric Product Model

Volundr represents configurable products through immutable Design Plans and deterministic configuration changes.

The Design Plan defines:

- product parameters and derived parameters
- dependency edges
- components and features
- presets
- assembly strategy
- printable outputs
- risks and design level

Direct user configuration is covered by `docs/PARAMETER_CONFIGURATION.md`. Configuration may change only approved editable input parameters and preset values. It does not mutate the Design Plan or accepted source. Structural changes escalate to `docs/STRUCTURED_REVISION_PLANNING.md`.

Printable outputs and assembly-level artifacts are covered by `docs/MULTI_OUTPUT_GENERATION.md`.
