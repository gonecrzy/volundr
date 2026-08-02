# Requirement Semantics Contract

Status: Implemented in this pass.

The requirement ledger is the authoritative record of what the user asked
Volundr to make. Planning artifacts, geometry source, and verification targets
are derived execution representations; they must preserve the ledger's meaning
rather than replace it.

## Semantic record

An active requirement uses the existing ledger record with semantic fields
equivalent to:

```json
{
  "requirement_id": "tray_capacity",
  "kind": "capacity",
  "operator": "up_to",
  "value": 5,
  "unit": "tray",
  "subject": "tackle_tray_holder",
  "object_type": "3600_size_tackle_tray",
  "target": "tray_storage",
  "source": "initial_user",
  "explicit": true,
  "raw_evidence": "can hold up to 5 3600 size tackle trays"
}
```

The database reuses the existing requirement-ledger table. Semantic fields are
stored in its evidence envelope so older rows remain readable and recoverable.

## Operators

| Operator | Meaning |
| --- | --- |
| `exact` | The value must equal the requested value. |
| `minimum` / `at_least` | The result must be no smaller than the value. |
| `maximum` / `up_to` | The result must be no larger than the value; for capacity, occupancy below the maximum is allowed. |
| `range` | The result must remain between the declared bounds. |
| `approximately` | The value is a proposal with an explicit approximation semantics and tolerance handled by verification. |
| `present` / `absent` | A feature or behavior is required or prohibited. |
| `qualitative` | The requirement needs review or a supported qualitative verifier. |

`kind`, `operator`, `value`, `unit`, and `object_type` are not inferred only
from a free-text label when typed evidence is available. For example, “up to
5” remains an upper-capacity requirement, not an exact five-tray occupancy
requirement and not a reusable count control.

## Authority and proposals

`initial_user`, `revision_user`, and `physical_test_feedback` requirements are
authoritative inputs. Derived functional necessities and Volundr proposals are
retained with their source and explicitness but cannot silently become user
requirements. Numeric user input does not become an exposed control unless the
user asks for reusable adjustment.

## Planning and verification

Direct briefs, compact Plans, and detailed Plans copy semantic requirements
into their derived execution context. A measurable ordinary requirement may be
traced to a unique Plan feature and deferred to a geometry-verification target.
The target records the operator and expected value; it does not claim a pass
before worker geometry exists. Missing bookkeeping may be normalized when the
relationship is unique. Ambiguous relationships, missing required features,
and exposed-control trace failures remain blocking.

Qualitative behavior such as one-handed access, retention force, or durability
is retained as a requirement and may produce human-review or test-print
evidence rather than a false deterministic pass.

## Revisions

A revision creates a requirement delta. The old active interpretation is
superseded, the new operator and raw evidence are retained, and unaffected
requirements remain active. Physical observations are persisted separately
from Volundr's requested correction. Revisions do not require a pre-existing
source parameter; exposed controls remain strictly validated.

## Non-goals

This contract does not create a second ledger, make all requirements
parametric, infer product-specific vocabulary, invent geometry, or weaken
source, topology, artifact, functional, export, or Current working version
gates.
