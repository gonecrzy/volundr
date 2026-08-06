# Temporary Codex geometry provider

`codex_proxy` is an experiment-only provider for the validated CadQuery flow.
The default remains `gemini_api`, and the validated flow remains disabled by
default.

When `VOLUNDR_VALIDATED_GEOMETRY_PROVIDER=codex_proxy` is enabled in the API
container, Gemini continues to own requirements and Design Plan stages. Codex
receives only the existing geometry-generation prompt and returns text for the
existing CadQuery contract. The adapter sends no tools, shell access,
repository context, filesystem context, or network instructions to the model.

The adapter uses the configured Responses-compatible base URL and model, sends
Bearer authentication only from `VOLUNDR_CODEX_API_KEY`, includes a bounded
timeout and explicit client request ID, and stores only redacted attempt
metadata. Refusal, incomplete, timeout, transport, authentication, and rate
limit responses fail closed. A rate-limit response is not retried by the
adapter; the application’s existing geometry contract-repair policy remains
the only bounded follow-up path.

Codex variables are passed only to `volundr-api`. They must not appear in the
web build, browser storage, worker environment, package artifacts, evidence,
or logs. The live comparison must use the exact frozen Project 01 inputs and
must not regenerate requirements or the Plan.
