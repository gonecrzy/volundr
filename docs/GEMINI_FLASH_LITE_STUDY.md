# Gemini Flash Lite behavior study

Volundr’s controlled study uses only `gemini-3.5-flash-lite`, the normal HTTP
workflow API, and the frozen ten-case corpus in
`benchmarks/gemini-flash-lite-study-v1.json`.

The study is a before-and-after product correction study: baseline and
validation each contain three controlled repetitions of the same ten cases.
The rounds are not a controlled provider comparison because cleanup occurs
between them.

Run a manifest without provider calls:

```bash
./scripts/run-gemini-study --dry-run
```

Run one live round at a time, preserving private evidence under
`data/debug-sessions/gemini-flash-lite-study/<study-id>/`:

```bash
./scripts/run-gemini-study --round baseline
./scripts/report-gemini-study data/debug-sessions/gemini-flash-lite-study/gemini-flash-lite-study-01
```

Do not start validation until baseline review, bounded cleanup, and full
offline replay are complete.
