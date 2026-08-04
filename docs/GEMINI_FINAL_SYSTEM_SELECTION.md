# Gemini final system selection

The final system-selection phase did not run. The first secondary-credential
continuation stopped on the first unfinished C/P3 request with a hard 429
before D. A later replacement continuation completed C and D, but the clean
finalist gate qualified only current/P0 because Profile B/P0 retained the
historical quota stop and both P3 arms contained a provider transport
timeout. The two-finalist comparison was therefore not authorized. The final
machine-readable decision is
`reports/final-system-boundary-decision.json` with decision
`insufficient_evidence`.

This is not a decision to keep or deploy either provider configuration. It is
a quota-safe stop. Production remains unchanged and Profile B is not
deployed. The next authorized study must repeat the complete factorial and,
only after its gates pass, run the two finalist systems across all five frozen
cases with identical clarification continuation and complete transport
capture, after quota is actually available. The backup credential does not
imply an independent project quota.
