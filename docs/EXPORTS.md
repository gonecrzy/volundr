# Volundr exports

Export is explicit and backend-owned. The default selection is the project’s
Current working version; a user may explicitly select a successful historical
revision. Blocked, failed, rejected, or artifact-incomplete revisions are not
exportable.

## API

Create an export with:

```http
POST /api/projects/{project_id}/exports
Content-Type: application/json

{"export_type":"stl","revision_id":"...","output_id":"body"}
```

Supported types are `stl`, `step`, `assembly_step`, `print_parts_zip`, and
`project_package`. The response is an `ExportRecord` containing the selected
project/revision, deterministic filename, included component IDs, warnings,
content hash, size, and completion state. Download through
`GET /api/exports/{export_id}/download`; the browser never constructs package
contents or chooses an arbitrary filesystem path.

Per-part names follow:

```text
{project-slug}_{part-slug}_r{revision-number}.stl
{project-slug}_{part-slug}_r{revision-number}.step
{project-slug}_print-parts_r{revision-number}.zip
{project-slug}_project_r{revision-number}.zip
```

Names are sanitized for cross-platform use. Registered output paths are
resolved below `VOLUNDR_DATA_DIR`; traversal and missing/empty artifacts are
rejected.

## Packages

The printable-parts ZIP contains individual STL and STEP files,
`manifest.json`, `README.txt`, and `verification-summary.json`. The complete
project package additionally contains project metadata, active requirements,
requirement history, revision history, verification evidence, source, and
registered BREP/geometry artifacts when present. It does not include API
keys, cookies, authorization headers, database credentials, environment
files, provider secrets, or worker temporary paths.

STEP is the primary exact geometry artifact. Volundr only offers a combined
assembly STEP when the selected revision has one exact exportable object; it
does not concatenate independent STEP files into an invalid assembly. 3MF is
the next export milestone: it requires a validated millimeter-unit mesh
writer with named multi-object placement before it should be advertised.

Repeated requests for the same project, revision, export type, and component
selection reuse a completed registered export when its file still exists.

The chat-first workspace keeps export explicit: the top-bar Export action and
export drawer are disabled until a successful accepted revision is selected.
The drawer supports STL, STEP, and complete project package actions through
the existing backend export records.
