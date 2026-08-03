# Provider convergence regression fixtures

The committed replay corpus is
`backend/tests/fixtures/provider_convergence/provider_response_replays.json`.
It is a minimal, redacted corpus derived from the local post-correction batch
`0ba9c31b-5d0e-440e-b34b-7b766afa1d39`. Full provider responses, prompts,
conversations, source, and worker traces remain local under the durable data
root and outside Git.

The corpus covers:

- malformed JSON that cannot be repaired without inventing syntax or values;
- fenced/schema-invalid assumptions that can use the unambiguous `label`
  display alias;
- structurally recognizable geometry content blocked by ambiguous feature
  identity;
- missing provenance that remains blocked without one authoritative source;
- unchanged focused repair;
- protected identity mutation classified as regressive;
- approved fence/trailing-comma normalization.

Every fixture records its originating batch, project, attempt, and stage. The
replay test asserts parse status, expected normalization, repair eligibility,
repair outcome, and final blocking state. The fixture source is evidence for
future deterministic tests, not permission to weaken schema or provenance
validation.

## Selection manifest

| Fixture | Evidence class | Expected result |
| --- | --- | --- |
| `post-correction-monitor-invalid-json` | malformed requirements JSON | invalid JSON; bounded repair may be attempted once |
| `post-correction-monitor-schema-invalid` | assumptions schema with display alias | valid after deterministic normalization; no invented text |
| `post-correction-organizer-identity-ambiguity` | geometry identity collision | semantic contradiction; blocked |
| `post-correction-screw-lid-missing-provenance` | Plan relationship without authoritative source | provenance invalid; blocked |
| `focused-repair-unchanged` | no semantic repair delta | `repair.no_effect`; blocked |
| `focused-repair-regressive-identity` | protected identity changed | `repair.regressed`; blocked |
| `normalized-fenced-trailing-comma` | approved representation difference | valid after normalization |

