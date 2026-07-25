# Volundr V1 Scope

This document is the V1 feature boundary. It lists what Volundr must include, what is explicitly excluded, and the test used to prevent premature scope expansion.

## Included

### Projects

- Create a project with a name and initial design request.
- View recent projects.
- Rename and archive projects.
- Store the original project intent separately from later revision instructions.

### AI Generation

- Generate OpenSCAD through Gemini CLI.
- Supply a controlled system prompt and model-generation contract.
- Capture raw model output.
- Extract SCAD from markdown or surrounding explanation when necessary.
- Limit automatic repair attempts.
- Store every attempt, including failures.
- Ask for clarification before OpenSCAD generation when critical fit, fastener, load, orientation, or conflicting dimensions make generation unsafe to guess.
- Preserve prompt version, provider/model, request context, raw output, extracted source, validation result, and failure class for each generation attempt.

### OpenSCAD Execution

- Compile source using OpenSCAD CLI.
- Use isolated temporary job directories.
- Enforce runtime and output limits.
- Capture warnings and errors.
- Produce STL output.
- Reject missing, empty, or implausibly large outputs.

### Model Inspection

- Display STL in an interactive 3D viewer.
- Show:
  - X, Y, and Z dimensions
  - triangle count
  - volume
  - watertight status
  - connected component count
- Provide standard views and fit-to-model.
- Inspect printability using the current model orientation and a configurable FDM printer profile.
- Report printability risks as Pass, Notice, Warning, or Critical findings, without a single percentage score.
- Do not claim print success is guaranteed.
- Use blocking validation findings to prevent automatic acceptance of unsafe or invalid AI-generated candidates.

### Source Editing

- Show source in Monaco Editor.
- Allow manual edits.
- Compile manually edited source as a new revision.
- Never overwrite the existing accepted revision.

### Revisions

- Maintain parent-child revision history.
- Display instruction, timestamp, status, and model metadata.
- Restore a prior revision by making it the active revision.
- Preserve failed attempts without presenting them as accepted models.
- Keep AI-generated candidates distinct from user-accepted active revisions when validation warnings or assumptions require review.

### Downloads

- Download `.scad`.
- Download `.stl`.
- Use clear filenames derived from the project and revision.

### Deployment

- Docker Compose is the official and only supported V1 installation method.
- Three explicitly named services: `volundr-web`, `volundr-api`, and `volundr-cad-worker`.
- Persistent bind-mounted application data.
- Configuration through environment variables.
- Compatible with Traefik and Authentik forward-auth.
- No application-native account system required.

## Excluded From V1

- Multi-user accounts
- Per-user Google authentication
- Billing, credits, subscriptions, or payments
- Public sharing
- Community gallery
- Collaboration
- Comments
- Mobile application
- Arbitrary STL editing
- STEP import or editing
- CAD assemblies
- Organic sculpting
- Photo-to-model generation
- Physics simulation
- Finite element analysis
- CNC workflows
- Manufacturing drawings
- Automatic support generation
- Full slicer integration
- Filament or print-time estimates
- Model marketplace
- Custom AI training
- Native-host installation as a separately supported V1 deployment path
- Browser-side OpenSCAD as the primary engine
- Real-time collaborative editing

## Scope Guard

A feature should not enter V1 merely because it is technically interesting.

A feature belongs in V1 only when it materially improves this core loop:

```text
describe -> generate -> compile -> inspect -> revise -> export
```
