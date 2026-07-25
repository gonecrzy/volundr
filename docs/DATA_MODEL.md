# Volundr Data Model

This document defines the persistent entities and invariants needed for projects, immutable revisions, AI attempts, CAD jobs, mesh metadata, and project conversation history.

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

## Revision

Represents one immutable model state.

Fields:

```text
id
project_id
parent_revision_id
revision_number
source_type
user_instruction
scad_source_path
stl_path
compile_log_path
ai_output_path
status
is_accepted
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
- Restoring a revision changes `active_revision_id`; it does not delete newer revisions.
- Failed AI attempts remain traceable.
- File paths are stored relative to Volundr data root.
- Large source and log content may be stored as files rather than database blobs.
- SQLite foreign keys must be enabled.
