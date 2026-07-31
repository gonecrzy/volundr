# Parametric Product Model

Volundr represents configurable products through immutable Design Plans and deterministic configuration changes.

`docs/CADQUERY_BACKEND.md` is authoritative for the CadQuery architecture.
Product-model concepts in this document are current for CadQuery source and
worker execution.

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

Component-targeted full-source revisions are covered by `docs/COMPONENT_TARGETED_REVISIONS.md`. They use the Design Plan component/output graph to constrain Gemini while preserving the complete authoritative CadQuery source.

Functional intent contracts and readiness states are defined in `docs/FUNCTIONAL_DESIGN_INTENT.md`.
