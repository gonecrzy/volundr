# Gemini Settings Selection

The settings study used six frozen packets and two repetitions per candidate,
with current prompts and stage-specific thinking. S0 and S1 were run first;
later candidates were not needed after the gate.

| Profile | Result |
| --- | --- |
| S0 current explicit (`temperature=0.2`, `topP=0.95`, `topK=40`) | eligible; 12/12 quality passes |
| S1 Profile B (seed 1701, candidate count 1) | incomplete after one preserved transport failure; 11/12 content passes |

S0 won the preregistered gate. This is an objective result of the new
provider-contract study, not a claim that the current production build is
better. S2 and S3 were correctly gated because no unresolved seed question
remained after S0 qualified and S1 was incomplete.

The exact decision is in `settings-study-decision.json`.
