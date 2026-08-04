# Gemini Flash Lite five-case baseline

The Gemini anchor in experiment
`0d82313e-2c04-4125-8bfa-1f3f48072464` was
`gemini-3.5-flash-lite`, run twice across the same five frozen cases. All ten
Gemini memberships completed through the normal API workflow. The generated
report records a mean paired consistency score of `0.200`.

This is a baseline for workflow behavior under the frozen configuration, not a
claim that the product output is acceptable. The individual evidence shows
blocked attempts and design-plan/schema/provenance failures, and the runner
also recorded an existing failure-path integrity defect in the API logs:
`user_message_id` was referenced before definition while materializing a failed
AI revision. That defect must be repaired and tested before using a later run
as a regression baseline.

The monitor-wall-mount case remains subject to explicit physical engineering
and test-review warnings even when geometry or workflow checks pass.
