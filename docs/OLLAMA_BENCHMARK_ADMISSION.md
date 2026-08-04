# Ollama benchmark admission

The later formal benchmark is gated by the calibration admission record. The
gate requires:

- at least one admitted CAD specialist;
- at least one admitted generic coding baseline;
- a final status for every intended model;
- frozen, hashed profiles;
- unresolved infrastructure and adapter errors excluded from quality scores.

The final combined record is in
`data/debug-sessions/ollama-calibration/calibration-admission-report/`.
It records no admitted specialist or generic baseline after the final fair
holdout checks:

```text
OLLAMA BENCHMARK ADMISSION
Formal five-case benchmark authorized: no
Reason: no specialist and generic baseline satisfied the full admission gate.
```

The formal runner reads `admission.json` and raises before any five-case API,
provider, Gemini, or worker execution when no authorized calibration record
exists. This calibration goal did not start the formal benchmark.

The read-only failure-anatomy review proposed
`operational_low_cad_quality_confirmed` for all six current dispositions. It
did not modify `admission.json`; the formal gate remains false and the later
benchmark remains unauthorized because no specialist/generic pair passed fair
holdout validation.
