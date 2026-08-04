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
| Buildability score | 0.9123 |

Profile B passed the stable-foundation path because it cleared the absolute
floor, remained noninferior to Profile A, maintained acceptance, improved
repeatability by three packets, and had no invented-critical-meaning or
integrity regression.

The focused five-case live comparison completed both arms, but neither arm
established worker-ready valid source across the set. The result is promising
but requires a second validation before any future production decision.
