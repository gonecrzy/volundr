# Gemini Flash Lite baseline

Baseline is three repetitions of the ten frozen cases in identical order.
Before every repetition the runner checks application readiness, model
availability, and performs one minimal provider readiness call. Quota,
transport, timeout, and content failures are recorded separately from CAD
quality and stop the run safely.

No prompt, policy, code, schema, or configuration changes are allowed during
the baseline repetitions. Each provider attempt is written as an immutable,
redacted JSON record, including retries and failures.
