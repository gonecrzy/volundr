# External CAD 50-project corpus

This corpus supplements the executable-CadQuery seed/debug and development
corpora. It is evaluator-only reference data: the normal Volundr user and
benchmark generation paths do not receive the reference geometry.

## Frozen shape

`external-cad-50-v1` contains 50 neutral benchmark IDs in 10 functional
categories, with five projects per category. The deterministic split is three
development, one validation, and one holdout project per category. The
mounting-bracket pilot is preserved as the five projects in the same frozen
corpus; its earlier pilot and smoke records remain historical methodology
evidence and are not silently counted as a development survey.

The 45-project acquisition package is validated by its outer SHA-256 and by
CRC and byte-preservation checks for every inner project ZIP. Canonical part
membership is explicit in intake metadata. Alternative variants, native CAD,
PDFs, and other source material remain provenance and do not change canonical
part count.

## Reference analysis

STL and 3MF references are mesh-derived evidence. Closed meshes receive
`watertight_mesh_reference`; open meshes receive
`nonwatertight_mesh_reference`, and closed-volume facts are withheld when
unreliable. STEP/BREP references are analyzed through OpenCascade and receive
`analytic_brep_authoritative` only when topology is valid. 3MF support is
benchmark tooling only; it does not make 3MF an authoritative generated-CAD
format. Large assemblies can be marked `replacement_recommended` rather than
being silently reduced to an arbitrary part.

Each project has a paraphrased `premise_only` request and a separate
`reference_specification` containing intentionally selected, provenance-tagged
facts. Specifications are classified as `minimal`, `moderate`, or
`reconstruction_grade`; geometric similarity and requirement/product
compliance remain separate result families.

## Holdout protection

After freeze, routine development tooling may see only a holdout project's
neutral ID, category, and split assignment. Source title, creator, URL,
premise, reference specification, reference geometry, derived geometry, and
run results are protected until the explicit holdout qualification gate. This
is a repository/process holdout for evaluation discipline; public source
models may have been seen during model training.

The corpus freezer owns metadata, ingestion, reference analysis, split
assignment, comparison preparation, and reporting. It does not own CAD
generation, requirement semantics, repair behavior, or provider-specific
logic. The next permitted activity after review is a frozen first-pass survey
of the 30 development projects, with no holdout runs.

Before that survey, comparison qualification is maintained separately as
`external-cad-50-v1.1`. It preserves v1, audits the 30 development
specifications, and permits interpreted reference-similarity metrics only for
projects marked `comparison_ready`.
