# Gemini Settings Selection

The settings study used six frozen packets and two repetitions per candidate,
with current prompts and stage-specific thinking. S0 and S1 were run first;
later candidates were not needed after the gate.

| Profile | Result |
| --- | --- |
| S0 current explicit (`temperature=0.2`, `topP=0.95`, `topK=40`) | eligible; 12/12 quality passes |
| S1 Profile B (seed 1701, candidate count 1) | 12/12 content passes after one replacement operation; one historical 504 is excluded from the content denominator |

The corrected content-only decision selects S0 by lower contract entropy, while
S1 is also content-qualified. The historical transport failure is preserved
and cannot disqualify S1. This is provider-contract evidence only, not a claim
that the current production build is better.

The exact decision is in `settings-study-decision.json`.
