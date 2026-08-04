# Native CAD capability

Native CAD is evaluated as a bounded diagnostic. The model receives a frozen
geometry request and must return one self-contained CadQuery program with
`import cadquery as cq` and a `result` value. Markdown fences, file writes,
network access, subprocesses, and unapproved packages are failures of the
response contract.

A native-CAD pass does not grant permission to execute arbitrary model output.
Execution remains in the existing isolated worker and existing source
authority/validation path. Native results are evidence only and do not create
revisions, candidates, promotions, or exports solely for reporting.

The monitor-wall-mount case remains a geometry/workflow evaluation only. No
report or frontend state may imply load-bearing safety; the physical
engineering and test-review warning is retained even when geometry passes.

