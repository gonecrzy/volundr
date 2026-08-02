# Plan-to-Source Identity Boundary

Status: Implemented in this pass.

The boundary separates identities that Volundr must preserve from ordinary
provider implementation names.

## Protected identities

The following remain authoritative and exact where present:

- printable component IDs;
- required feature IDs used for trace or verification;
- printable output IDs;
- exposed control IDs;
- scaffold parameters and helper identities;
- required pattern IDs;
- assembly/interface IDs;
- geometry function IDs and result symbols.

Missing required components, outputs, protected features, scaffold mutation,
and assembly mismatches remain blocking.

## Provider locals

Provider-owned local variables may use any safe, definitely assigned Python
name. A local is not a Plan identity merely because it is numeric, derived, or
named similarly to a requirement. Local values may be literals, expressions,
or values read through the approved `params` interface.

The source authority records nonblocking `source.local_implementation_variable`
diagnostics for successful source attempts. A local that collides with a
protected identity or is exported as an unapproved scaffold parameter is not
silently accepted; the existing source contract remains authoritative.

The geometry prompt explicitly reserves the module-level `PARAMETERS` list for
approved scaffold parameter identities. Ordinary calculations stay inside the
provider function body.

## Evidence

Original provider payloads, normalized plans, source bodies, assembled source,
source-validation findings, and execution results remain separate immutable
artifacts. Normalization cannot change the requirement ledger or create a
provider-approved detailed plan by implication.
