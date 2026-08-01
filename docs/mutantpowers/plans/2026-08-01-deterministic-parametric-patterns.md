# Deterministic Parametric Patterns
> **Execution mode:** Inline Execution

**Goal:** Move repeated-pattern arithmetic into deterministic Volundr-owned
helpers so protected count and spacing inputs reach geometry through canonical
pattern points.

**Constraints:** Preserve existing validation gates and JSON compatibility,
avoid holder-specific branches, do not change the chat-first frontend, and
update only the affected geometry-body prompt version.

### Task 1: RED tests

**Files:** `backend/tests/test_parametric_patterns.py`,
`backend/tests/test_cadquery_parameter_effects.py`,
`backend/tests/test_cadquery_source_scaffold.py`

Add tests for helper validation, deterministic ordering/hash/provenance,
pattern specifications, canonical `pushPoints` use, provider point-array
rejection, and count/spacing effect propagation. Run the focused tests and
confirm they fail for missing helpers/integration.

### Task 2: Pattern runtime

**Files:** `backend/volundr_cad/patterns.py`,
`backend/volundr_cad/runtime.py`

Implement validated linear, rectangular, and circular point generation with
finite numeric inputs, supported axes/planes, one-item behavior, deterministic
centering/order, unit/provenance metadata, and stable hashes. Expose the
canonical point values through runtime parameter context without changing the
existing parameter JSON format.

### Task 3: Plan and scaffold integration

**Files:** `backend/app/schemas/project.py`,
`backend/app/services/projects/service.py`,
`backend/app/services/cad/source_scaffold.py`,
`backend/app/services/cad/cadquery_source_authority.py`

Accept a generic `patterns` section, validate pattern references and ownership,
derive canonical point parameters from approved count/spacing inputs, include
pattern specifications and point manifests in source authority, and render
scaffold-owned point parameters/helpers before provider bodies.

### Task 4: Source/effect enforcement

**Files:** `backend/app/services/cad/parameter_effects.py`,
`backend/app/services/cad/geometry_bodies.py`,
`backend/app/services/ai/gemini_cli.py`

Treat `params[pattern_points] -> pushPoints` as the approved count/spacing
effect chain. Reject provider-created point arrays, replacement pattern
helpers, cardinality mismatch, and unused required patterns with explicit
findings. Update only structured geometry-body generation/repair prompt
versions and instructions.

### Task 5: Verification and live record

Run focused tests, full backend suite, frontend tests/build, deterministic
Playwright suites, and the exact live request. Record the result in
`docs/BOTTLE_HOLDER_PATTERN_LIVE_EVALUATION.md`, whether worker/function gates
pass or a new genuine semantic/physical blocker remains. Commit implementation
and live record separately.

