# Ollama prompt compatibility

The benchmark uses one frozen five-case corpus and two fixed seeds (`101` and
`202`) per model. Prompt text, context length, retry policy, and environment
must be unchanged between the two runs. Provider settings are recorded with
each experiment and no provider credentials are sent to the browser.

The structured/production profile requests JSON owned by Volundr and is the
only profile eligible for production-slot comparison. The native profile is a
diagnostic subset for models that may be better suited to direct CadQuery
generation; it must not be promoted into the production workflow without a
separate adapter and contract test.

Every prompt, provider response, generated source, worker output, screenshot
metadata, and frontend network record passes through the shared redaction
writer. Unsent drafts, keystrokes, pointer movement, and unrelated browser
activity are not collected.

