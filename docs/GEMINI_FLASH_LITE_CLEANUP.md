# Gemini Flash Lite cleanup

Cleanup begins only after all 30 baseline operations are frozen and reviewed.
`reports/baseline.json` and `cleanup/analysis.json` record recurring generic
signatures. At most three generic production corrections are eligible; each
must cite affected cases/repetitions, owner, regression fixtures, overfitting
risk, and expected outcome change.

Development uses zero Gemini calls:

```bash
./scripts/run-gemini-study --replay gemini-flash-lite-study-01 \
  --from raw_provider_response --offline-required
```

Do not add product-specific CAD generators or weaken safety, topology,
verification, or candidate-promotion gates.
