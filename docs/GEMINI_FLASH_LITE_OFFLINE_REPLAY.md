# Gemini Flash Lite offline replay

Replay never constructs a provider. `--offline-required` is mandatory and the
result records the live source record, replay starting point, original and
replay identities/classifications, downstream outcomes, changed fields, and
regression/improvement classification.

Supported starting points are `raw_provider_response`, `parsed_response`,
`normalized_response`, `assembled_source`, and `worker_result`.
