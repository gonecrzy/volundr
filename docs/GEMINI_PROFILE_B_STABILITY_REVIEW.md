# Gemini Profile B stability review

Profile B is the current prompt and response format with Gemini default
sampling, fixed seed `1701`, and no temperature/top-p/top-k override.

Offline Phase 1 results:

| Measure | Profile B |
| --- | ---: |
| Quality-floor passes | 6/6 |
| Corrected semantic quality | 1.0000 |
| Semantic-consistent packets | 3/3 |
| Byte-identical packets | 3/3 |
| Acceptance | 6/6 |
| Buildability score | 0.9789 authoritative; 0.9123 preserved historical narrative |

Profile B passed the stable-foundation path because it cleared the absolute
floor, remained noninferior to Profile A, maintained acceptance, improved
repeatability by three packets, and had no invented-critical-meaning or
integrity regression.

The focused five-case live comparison completed both arms, but neither arm
established worker-ready valid source across the set. The result is promising
but requires a second validation before any future production decision.

The focused comparison has since been audited offline. Profile B case-001
correctly requested fit-critical clarification, but the harness did not submit
the frozen answer. The corrected worker-ready counts are current 3/5 and
Profile B 2/5; Profile B case-006 reached the worker and failed inside
CadQuery. The final audited decision is
`corrected_second_validation_required`; see the Phase 2 audit and second-
validation plan.
