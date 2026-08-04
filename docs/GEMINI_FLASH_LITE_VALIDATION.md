# Gemini Flash Lite validation

Validation repeats the identical ten prompts and fact sheets three times after
cleanup is frozen. It uses new projects and new provider interactions; it does
not reuse baseline responses. No code, prompt, configuration, or schema change
is permitted during validation.

Use the same runner with `--round validation`, then generate reports. Label
the resulting comparison before-and-after, not controlled provider variance.
