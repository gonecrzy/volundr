# Volundr Data Model

This document defines the persistent entities and invariants needed for projects, immutable revisions, Design Specifications, immutable Design Plans, AI attempts, CAD jobs, mesh metadata, and project conversation history.

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
revision_number
source_type
user_instruction
scad_source_path
stl_path
compile_log_path
ai_output_path
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

## DesignSpecification

Represents an immutable structured interpretation of a user request before OpenSCAD generation. New initial AI generations require a ready Design Specification. Clarification answers create a new specification version rather than mutating the prior one.

Fields:

```text
id
project_id
generation_attempt_id
superseded_specification_id
version_number
schema_version
prompt_template_version
gemini_ruleset_version
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

Represents an immutable parametric product model generated after an approved `generation_ready` Design Specification and before OpenSCAD generation. A Design Plan is the structure authority for parameters, derived dependencies, components, features, presets, assembly strategy, and printable outputs. Plan approval is explicit; new initial OpenSCAD generation should use an approved Design Plan when one exists.

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
gemini_ruleset_version
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
  -> plan_clarification_required -> rejected | replanned after user input
  -> plan_ready -> pending_review -> approved | rejected
  -> approved -> OpenSCAD generation may start

Design Plans are immutable. Replanning creates a new version with superseded_design_plan_id set.
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

Requirement-extraction attempts store parsed Design Specifications at `parsed-design-spec.json`. OpenSCAD generation attempts store the authoritative Design Specification snapshot at `design-spec.json`.

## SourceValidationResult

Represents one deterministic static validation of extracted OpenSCAD source before compilation.

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

## GeometricAnalysisResult

Represents one deterministic post-compile geometric invariant analysis for a revision.

Fields:

```text
id
revision_id
design_specification_id
analysis_version
tolerance_profile_version
mesh_hash
source_hash
result_path
analysis_ms
created_at
```

`result_path` points to the full JSON result, including verification state, confidence, expected value, detected value, tolerance, source/feature metadata, analyzer version, and linked `validation_finding_id` for persisted non-pass findings. New AI candidates with Design Specifications receive this analysis before candidate state is derived. Existing legacy revisions may have no geometric analysis.

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
