# Volundr Data Model

This document defines the persistent entities and invariants needed for projects, immutable revisions, Design Specifications, immutable Design Plans, immutable Revision Plans, AI attempts, CAD jobs, mesh metadata, and project conversation history.

## CadQuery Transition Status

The target data model is CadQuery-native and provider-neutral. Phase 3 removes `Revision.scad_source_path`, `RevisionOutput.module_name`, `RevisionOutput.compile_command_json`, and persisted `gemini_ruleset_version` columns as canonical fields. The completed transition stores backend/source-language metadata, CadQuery source paths and hashes, execution manifests, STEP/STL artifact hashes, topology metadata, mesh metadata, and validation summaries without permanent SCAD aliases.

## Project

Represents one design effort.

Fields:

```text
id
name
slug
original_intent
status
active_revision_id
created_at
updated_at
archived_at
```

Suggested `status` values:

```text
draft
active
archived
```

Draft projects support unnamed short-lived workspaces. They are hidden from the default project list, can own revisions, and become normal active projects when saved with a user-visible name. Draft projects older than 14 days may be deleted during opportunistic cleanup.

Archived projects are hidden from the default project list but remain recoverable until removed. Archived projects older than 60 days may be permanently deleted during opportunistic cleanup, including their revisions, messages, and project files.

Permanent project deletion removes the project database row, dependent revisions and messages, and the project asset directory under `data/projects`.

## Revision

Represents one immutable model state.

Fields:

```text
id
project_id
parent_revision_id
design_specification_id
design_plan_id
configuration_change_id
revision_number
source_type
user_instruction
cad_backend
source_language
source_path
source_hash
source_contract_version
execution_manifest_path
stl_path
compile_log_path
ai_output_path
output_manifest_path
expected_output_count
required_output_count
successful_output_count
blocked_output_count
failed_output_count
status
is_accepted
review_state
accepted_at
rejected_at
created_at
```

Suggested `source_type` values:

```text
ai_initial
ai_revision
ai_repair
manual_edit
restored
configuration_change
```

Suggested `status` values:

```text
pending
compiling
succeeded
failed
rejected
```

Suggested `review_state` values:

```text
ready
ready_with_warnings
blocked
rejected
accepted
```

Candidate state diagram:

```text
compile/mesh/validation complete
  -> blocking findings? yes -> blocked -> rejected
  -> advisory findings? yes -> ready_with_warnings -> accepted | rejected
  -> no findings -> ready -> accepted | rejected

accepted -> active_revision_id may point here
blocked -> accepted is forbidden
rejected -> accepted is forbidden
```

Manual source compilation establishes the first active accepted revision when no active design exists. Later manual compiles and AI compiles create candidates until explicitly accepted.

For approved Design Plan generation, the revision represents the assembly-level candidate. Individual printable artifacts are represented by `RevisionOutput` rows. `stl_path` remains as a compatibility pointer to the first successful printable output when one exists.

Configuration-generated revisions link to `configuration_change_id`. In the CadQuery target they copy accepted source unchanged, validate typed parameter values, and execute through the isolated worker without source rewriting or provider calls. The current OpenSCAD implementation uses persisted `-D` overrides during per-output compilation until Phase 7 replaces that path.

## CadQuery Target Revision Fields

The Phase 3 revision model now stores backend-neutral source fields directly.

For normal product revisions:

```text
cad_backend = cadquery
source_language = python
```

Each successful output stores STEP and STL paths/hashes, optional BREP paths/hashes, topology metadata, mesh metadata, validation summary, expected and detected solid counts, and disconnected-solid policy.

## ConfigurationChange

Represents an immutable previewed parameter or preset change against an accepted base revision.

Fields:

```text
id
project_id
base_revision_id
generated_revision_id
design_specification_id
design_plan_id
schema_version
reason
selected_preset_id
validation_state
base_source_hash
content_hash
requested_changes_json
preset_values_json
user_overrides_json
resolved_parameters_json
affected_parameters_json
affected_components_json
affected_outputs_json
validation_errors_json
configuration_path
override_manifest_path
created_at
approved_at
```

Suggested `validation_state` values:

```text
configuration_ready
clarification_required
invalid_configuration
requires_design_revision
configuration_failed
```

Only `configuration_ready` may generate a candidate revision. Generation sets `generated_revision_id` and `approved_at`; it does not mutate the base revision, Design Plan, or accepted source.

## ConfigurationPreset

Represents a project-local preset for an approved Design Plan.

Fields:

```text
id
project_id
design_plan_id
preset_id
label
parameter_values_json
created_at
```

Design Plan presets remain embedded in Design Plan JSON. Project-local presets are additional user-created groups of values and do not modify the Design Plan.

## RevisionOutput

Represents one printable artifact produced from a Design Plan output.

Fields:

```text
id
revision_id
design_plan_id
design_specification_id
output_id
component_id
component_ids_json
output_state
output_type
label
filename
quantity
required
entrypoint
source_hash
step_path
step_hash
brep_path
brep_hash
stl_path
stl_hash
compile_log_path
compile_ms
compile_error
execution_command_json
topology_metadata_json
mesh_metadata_json
metadata_json
validation_summary_json
preferred_orientation_json
created_at
updated_at
```

Suggested `output_state` values:

```text
queued
compiling
compiled
validating
ready
ready_with_warnings
blocked
failed
skipped
```

Output artifacts are immutable product evidence for a candidate revision except when a failed output is explicitly retried from the same authoritative source hash, parameter hash, and output ID. Output retry does not call Gemini.

## DesignSpecification

Represents an immutable structured interpretation of a user request before CadQuery generation. New initial AI generations require a ready Design Specification. Clarification answers create a new specification version rather than mutating the prior one.

Fields:

```text
id
project_id
generation_attempt_id
superseded_specification_id
version_number
schema_version
prompt_template_version
ruleset_version
provider
provider_model
user_instruction
raw_response_path
specification_path
content_hash
outcome
supported_scope
clarification_required
generation_ready
created_at
```

Suggested `outcome` values:

```text
generation_ready
clarification_required
requirements_conflict
unsupported_request
extraction_failed
```

The JSON stored at `specification_path` uses schema version `1.0`:

```json
{
  "schema_version": "1.0",
  "project_id": "uuid",
  "generation_attempt_id": "uuid",
  "object_type": "wall_mounted_cylindrical_holder",
  "purpose": "Hold an 81 mm container on a vertical surface",
  "units": "mm",
  "supported_scope": true,
  "critical_dimensions": [
    {
      "id": "container_diameter",
      "label": "Container diameter",
      "value": 81.0,
      "unit": "mm",
      "tolerance": null,
      "source": "user",
      "importance": "critical",
      "protected": true
    }
  ],
  "parameters": [
    {
      "id": "fit_clearance",
      "label": "Fit clearance",
      "value": 0.8,
      "unit": "mm",
      "source": "product_default",
      "importance": "important",
      "protected": false,
      "editable": true,
      "explanation": "General removable fit for an FDM-printed holder"
    }
  ],
  "functional_requirements": [
    {
      "id": "mounting_method",
      "description": "Mount to a vertical wall using two screws",
      "source": "user",
      "importance": "critical",
      "protected": true
    }
  ],
  "print_requirements": {
    "printer_profile_id": "default-fdm-256",
    "nozzle_diameter_mm": 0.4,
    "layer_height_mm": 0.2,
    "material": null,
    "supports_allowed": null,
    "preferred_orientation": null
  },
  "assumptions": [
    {
      "id": "default_wall",
      "description": "Use a 3 mm wall thickness",
      "source": "product_default",
      "requires_approval": false
    }
  ],
  "conflicts": [],
  "missing_requirements": [],
  "clarification_required": false,
  "clarification_questions": [],
  "generation_ready": true,
  "outcome": "generation_ready"
}
```

Dimension and requirement sources are:

```text
user
clarification
calculated
printer_profile
product_default
ai_assumption
```

Importance values are:

```text
critical
important
optional
cosmetic
```

Protected by default: user or clarification supplied critical dimensions, explicit hole count, explicit spacing, mating dimensions, required features, maximum envelope constraints, and selected printer build-volume constraints.

## DesignPlan

Represents an immutable parametric product model generated after an approved `generation_ready` Design Specification and before CadQuery generation. A Design Plan is the structure authority for parameters, derived dependencies, components, features, presets, assembly strategy, and printable outputs. Plan approval is explicit; new initial CadQuery generation must use an approved Design Plan. Printable output semantics are defined in `docs/MULTI_OUTPUT_GENERATION.md`.

Fields:

```text
id
project_id
design_specification_id
generation_attempt_id
superseded_design_plan_id
version_number
schema_version
prompt_template_version
ruleset_version
provider
provider_model
raw_response_path
plan_path
content_hash
outcome
review_state
clarification_required
plan_ready
approved_at
rejected_at
created_at
```

Suggested `outcome` values:

```text
plan_ready
plan_clarification_required
plan_failed
```

Suggested `review_state` values:

```text
clarification_required
pending_review
approved
rejected
```

Design Plan lifecycle:

```text
Design Specification generation_ready
  -> design-plan-v1 extraction
  -> plan_clarification_required -> rejected | clarification answers -> superseding plan version
  -> plan_ready -> pending_review -> approved | rejected
  -> approved -> CadQuery generation may start
  -> UI approval starts generation immediately during the current stabilization workflow
```

Design Plans are immutable. Planning clarification answers are persisted against the non-ready Design Plan, then `design-plan-v1` is rerun with the previous plan, original Design Specification, persisted questions, and answers. The resulting plan stores `superseded_design_plan_id`.

## DesignPlanClarificationQuestion

Represents one specific question attached to a non-ready Design Plan.

Fields:

```text
id
project_id
design_plan_id
related_plan_field
question
reason
display_order
created_at
```

## DesignPlanClarificationAnswer

Represents one user answer to a Design Plan clarification question.

Fields:

```text
id
project_id
design_plan_id
question_id
related_plan_field
question_text
answer
created_at
```

The JSON stored at `plan_path` uses schema version `1.0`:

```json
{
  "schema_version": "1.0",
  "project_id": "uuid",
  "design_specification_id": "uuid",
  "generation_attempt_id": "uuid",
  "design_level": "product",
  "product_type": "configurable_bracket",
  "purpose": "Mount a small electronics module to a wall",
  "units": "mm",
  "parameters": [
    {
      "id": "mount_hole_spacing",
      "label": "Mount hole spacing",
      "value": 60,
      "unit": "mm",
      "source_requirement_id": "mount_hole_spacing",
      "editable": true,
      "protected": true,
      "component_id": "bracket_body"
    }
  ],
  "derived_parameters": [
    {
      "id": "plate_height",
      "label": "Plate height",
      "expression": "mount_hole_spacing + 20",
      "unit": "mm",
      "depends_on": ["mount_hole_spacing"]
    }
  ],
  "dependency_edges": [
    {
      "from": "mount_hole_spacing",
      "to": "plate_height",
      "relationship": "spacing controls minimum plate height"
    }
  ],
  "components": [
    {
      "id": "bracket_body",
      "label": "Bracket body",
      "description": "Main printable bracket",
      "features": ["mounting_holes"],
      "parameters": ["mount_hole_spacing"]
    }
  ],
  "features": [
    {
      "id": "mounting_holes",
      "component_id": "bracket_body",
      "type": "hole_group",
      "description": "Two wall mounting holes",
      "parameters": ["mount_hole_spacing"],
      "protected": true
    }
  ],
  "presets": [
    {
      "id": "default",
      "label": "Default",
      "parameter_values": {"mount_hole_spacing": 60}
    }
  ],
  "assembly_strategy": {
    "type": "single_part",
    "instructions": ["Print flat with wall face on the build plate."]
  },
  "printable_outputs": [
    {
      "id": "bracket_body_output",
      "label": "Bracket body",
      "component_ids": ["bracket_body"],
      "quantity": 1,
      "orientation": "wall face on Z=0"
    }
  ],
  "risks": [
    {
      "id": "layer_strength",
      "severity": "warning",
      "description": "Wall loads should be carried by ribs, not a thin flat plate.",
      "mitigation": "Use triangular ribs behind the mounting face."
    }
  ],
  "clarification_required": false,
  "clarification_questions": [],
  "plan_ready": true,
  "outcome": "plan_ready"
}
```

## RevisionPlan

Represents an immutable, scoped plan for changing an accepted revision. Revision Plans are generated from an accepted base revision plus its Design Specification, approved Design Plan, output manifest, source metadata, and optionally selected validation findings. The full lifecycle and payload schema are defined in `docs/STRUCTURED_REVISION_PLANNING.md`.

Fields:

```text
id
project_id
base_revision_id
base_design_specification_id
base_design_plan_id
generation_attempt_id
superseded_revision_plan_id
generated_revision_id
revised_design_specification_id
revised_design_plan_id
version_number
schema_version
prompt_template_version
ruleset_version
provider
provider_model
user_instruction
reason
raw_response_path
plan_path
content_hash
base_source_hash
base_output_manifest_hash
base_design_specification_hash
base_design_plan_hash
outcome
review_state
clarification_required
revision_ready
approved_at
rejected_at
created_at
```

Suggested `outcome` values:

```text
revision_ready
clarification_required
revision_conflict
unsupported_revision
planning_failed
```

Suggested `review_state` values:

```text
clarification_required
pending_review
approved
rejected
```

Revision Plans are immutable. Clarification answers create a new version with `superseded_revision_plan_id` set. CadQuery revision generation requires a `revision_ready` plan in `approved` state. Component-targeted full-source revision behavior is defined in `docs/COMPONENT_TARGETED_REVISIONS.md`.

## RevisionPlanClarificationQuestion

Represents one specific question attached to a non-ready Revision Plan.

Fields:

```text
id
project_id
revision_plan_id
requirement_id
question
reason
display_order
created_at
```

## RevisionPlanClarificationAnswer

Represents the user's answer to a persisted revision-plan clarification question. Answers are retained as history and used as structured context for the next revision-plan run.

Fields:

```text
id
project_id
question_id
revision_plan_id
related_requirement_id
question_text
answer
created_at
```

## ClarificationQuestion

Represents one specific question attached to a non-ready Design Specification.

Fields:

```text
id
project_id
design_specification_id
requirement_id
question
reason
display_order
created_at
```

## ClarificationAnswer

Represents the user's answer to a persisted clarification question. Answers are retained as history and used as structured context for the next requirement-extraction run.

Fields:

```text
id
project_id
question_id
design_specification_id
related_requirement_id
question_text
answer
created_at
```

## GenerationAttempt

Captures each AI interaction, including attempts that never became valid revisions.

Fields:

```text
id
project_id
base_revision_id
attempt_number
provider
provider_model
prompt_version
request_payload_path
raw_output_path
extracted_source_path
status
error_message
started_at
completed_at
```

The current implementation also persists `resulting_revision_id`, non-secret provider settings, prompt-template version, Gemini ruleset version, source/output hashes, and request/prompt/raw-output/extracted-source/design-spec/intermediate artifact paths.

Requirement-extraction attempts store parsed Design Specifications at `parsed-design-spec.json`. CadQuery generation attempts store the authoritative Design Specification snapshot at `design-spec.json`.

## SourceValidationResult

Represents one deterministic static validation of extracted CAD source before execution.

Fields:

```text
id
project_id
generation_attempt_id
design_specification_id
revision_id
contract_version
ruleset_version
validator_version
source_hash
result_path
passed_hard_checks
validation_ms
created_at
```

`result_path` points to the full JSON result, including source metadata, hard violations, quality findings, specification findings, module names, parameter names, requirement mappings, feature mappings, and timing. `revision_id` is nullable because hard source-contract failures stop before a revision or candidate exists.

## ValidationFinding

Represents one persisted non-pass validation result. Findings may belong to a revision/candidate after compile, or only to a generation attempt when source-contract validation fails before compile.

Fields:

```text
id
revision_id
revision_output_id
generation_attempt_id
design_specification_id
source_validation_result_id
rule_id
category
severity
is_blocking
title
explanation
suggested_correction
detected_value
unit
threshold_value
source_line_start
source_line_end
orientation_dependent
affected_geometry_summary
metadata_json
finding_state
dismissal_reason
dismissed_at
created_at
```

Suggested `severity` values:

```text
notice
warning
critical
```

`is_blocking` is authoritative for acceptance. Severity alone does not decide whether a candidate can be accepted. Non-blocking findings may be dismissed, but blocking findings cannot be dismissed into acceptability.

`revision_output_id` is set for component-level mesh, geometric, and printability findings. Assembly-level findings leave it null and attach only to `revision_id`.

## GeometricAnalysisResult

Represents one deterministic post-compile geometric invariant analysis for a revision or a specific printable output.

Fields:

```text
id
revision_id
revision_output_id
design_specification_id
analysis_version
tolerance_profile_version
mesh_hash
source_hash
result_path
analysis_ms
created_at
```

`result_path` points to the full JSON result, including verification state, confidence, expected value, detected value, tolerance, source/feature metadata, analyzer version, and linked `validation_finding_id` for persisted non-pass findings. New AI candidates with Design Specifications receive this analysis before candidate state is derived. Multi-output candidates receive output-scoped results. Existing legacy revisions may have no geometric analysis.

## RevisionComplianceResult

Represents deterministic pre-compile validation that a revised source stayed within the approved Revision Plan.

Fields:

```text
id
project_id
revision_plan_id
generation_attempt_id
revision_id
base_source_hash
revised_source_hash
result_path
passed
validation_ms
created_at
```

`result_path` stores blocking and advisory compliance findings. `revision_id` is nullable because failed compliance stops before compile and candidate creation.

## ComponentRevisionSummary

Represents the persisted comparison summary for a component-targeted full-source revision.

Fields:

```text
id
project_id
revision_plan_id
revision_id
base_revision_id
generation_attempt_id
base_source_hash
revised_source_hash
equivalence_profile_version
summary_path
created_at
```

`summary_path` stores `component-revision-summary-v1` JSON containing targeted output change states, protected output preservation states, interface verification results, source compliance linkage, and configuration context linkage. Legacy revisions may have no component revision summary.

## RevisionSuccessResult

Represents post-generation verification of a Revision Plan success criterion.

Fields:

```text
id
project_id
revision_plan_id
generation_attempt_id
revision_id
criterion_type
target_id
verification_state
expected_value_json
detected_value_json
unit
tolerance
confidence
is_blocking
explanation
metadata_json
created_at
```

Suggested `verification_state` values:

```text
success_verified
success_violated
success_unverifiable
```

## CadJob

Captures CAD execution details.

Fields:

```text
id
revision_id
attempt_id
status
source_hash
exit_code
timed_out
stdout_path
stderr_path
output_path
output_size_bytes
started_at
completed_at
```

## MeshMetadata

Fields:

```text
revision_id
size_x_mm
size_y_mm
size_z_mm
volume_mm3
triangle_count
connected_components
is_watertight
is_winding_consistent
center_of_mass_json
warnings_json
```

## SavedPrintabilityProfile

Represents a reusable single-user printer preset for printability inspection.

Fields:

```text
id
profile_version
printer_name
process
material_behavior
build_volume_x_mm
build_volume_y_mm
build_volume_z_mm
nozzle_diameter_mm
default_layer_height_mm
created_at
updated_at
```

Saved printability profiles use the same profile values sent to the inspector. They are global presets for the local instance, not slicer profiles, and do not add filament or print-time estimates.

## ProjectMessage

Optional V1 structure for preserving conversation without treating the chat transcript as the source of truth.

Fields:

```text
id
project_id
revision_id
role
content
created_at
```

Roles:

```text
user
assistant
system_event
```

## Design Rules

- Revisions are immutable.
- Restoring an accepted revision changes `active_revision_id`; it does not delete newer revisions.
- Blocked and rejected candidates cannot be restored as active revisions.
- Failed AI attempts remain traceable.
- File paths are stored relative to Volundr data root.
- Large source and log content may be stored as files rather than database blobs.
- SQLite foreign keys must be enabled.
