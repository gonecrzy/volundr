# Gemini Flash Lite study run record

This is the post-run handoff for `gemini-flash-lite-study-01`. The private,
redacted evidence root is:

`data/debug-sessions/gemini-flash-lite-study/gemini-flash-lite-study-01/`

The run used corpus `gemini-flash-lite-study-v1`, corpus hash
`7f4c6b4e87f24782a63d4487ebb75bf8096c96c0dfe1776f165e28ea6b806a24`, provider
`gemini_api`, and the exact requested model `gemini-3.5-flash-lite`.

## Baseline

Baseline completed 10 frozen cases × 3 repetitions (30 project operations).
The recorded report contains 119 provider calls, 8 repair calls, 30 projects
reaching valid source, 13 reaching the worker, 5 producing valid topology, and
1 candidate-ready-or-warning outcome.

## Offline cleanup and replay

The bounded cleanup analysis selected no production correction: the only
eligible recurring signature was `provider_failure`, which did not justify a
generic product change. The single raw-response replay processed 124 captured
records with `offline_required: true` and recorded `provider_calls: 0`.

## Validation

Validation completed the same 10 frozen cases × 3 repetitions (30 new project
operations) in a separate evidence tree. The report contains 117 provider
calls, 10 repair calls, 30 projects reaching valid source, 14 reaching the
worker, 5 producing valid topology, and 2 candidate-ready-or-warning
outcomes.

## Before-and-after interpretation

The generated comparison is explicitly labeled `before-and-after product
correction study` and is not a controlled provider-variability pair. The
recorded changes were +1 candidate-ready-or-warning outcome, +1 worker-reached
project, and unchanged valid-source and valid-topology counts. Feature
evidence remained unmeasured in both rounds.

