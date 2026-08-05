# Gemini Provider-Contract Correction

Correction study: `provider-contract-correction-01` under the preserved
`gemini-provider-contract-foundation-01` evidence root.

The original evidence was corrected without rewriting it. The one incomplete
S1 settings operation was run once with `GEMINI_API_KEY_2`; both S0 and S1
then had 12/12 content-bearing passes. The 504 transport outcome was excluded
from quality denominators and preserved as historical evidence. S0 was
selected by lower contract entropy.

The requirements micro-study selected `T2-requirements-missing-fit-v1` at
6/6, versus T0 at 4/6. The source-bearing repair study selected no prompt:
T2 improved to 4/6 versus T0 at 2/6 but did not meet the 6/6 gate. The
historical holdout was H0 with explicit MINIMAL thinking, not H1. H1 remains
provisional and must omit `thinkingConfig`.

Because the repair gate failed, the corrected H1 holdout and adapter replay
made zero calls. The final decision is
`corrected_second_validation_required`. No production settings, adapter, or
deployment changed.

Evidence and the redacted combined bundle are under:

`data/debug-sessions/gemini-provider-contract-foundation/gemini-provider-contract-foundation-01/reports/provider-contract-correction-01/`
