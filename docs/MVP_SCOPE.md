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
- Persist a versioned Design Specification before new initial OpenSCAD generation.
- Generate and persist an immutable Parametric Design Plan from a ready Design Specification.
- Require explicit Design Plan approval before new initial OpenSCAD generation in the stabilized frontend flow.
- Use the approved Design Plan as product-structure authority for OpenSCAD generation.
- Generate and persist immutable structured Revision Plans before scoped AI revisions.
- Require explicit Revision Plan approval before AI source revision.
- Allow direct editing of approved editable Design Plan parameters and preset switching through deterministic configuration changes without invoking Gemini.
- Validate new AI OpenSCAD against the source contract before compilation, including security rules, required structure, protected Design Specification values, and advisory quality findings.
- Validate revised AI source against the approved Revision Plan before compilation.
- Preserve prompt version, provider/model, request context, raw output, extracted source, validation result, and failure class for each generation attempt.
- Present successful AI generations as candidate revisions until the user explicitly accepts or rejects them.

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
- Verify selected measurable protected geometric invariants after compile, including bounds, build-plate placement, simple axis-aligned holes, hole spacing, hole count, and coarse wall thickness.
- Do not claim print success is guaranteed.
- Use blocking validation findings to prevent automatic acceptance of unsafe or invalid AI-generated candidates.

### Source Editing

- Show source in Monaco Editor.
- Allow manual edits.
- Compile manually edited source as a new revision.
- Never overwrite the existing accepted revision.
- After an accepted design exists, manual compiles create candidate revisions that require explicit acceptance.

### Revisions

- Maintain parent-child revision history.
- Display instruction, timestamp, status, and model metadata.
- Restore a prior revision by making it the active revision.
- Preserve failed attempts without presenting them as accepted models.
- Keep AI-generated candidates distinct from user-accepted active revisions when validation warnings or assumptions require review.
- Keep requirement extraction, clarification, and unsupported-request states distinct from failed model revisions.
- Keep revision planning, revision clarification, revision conflicts, and unsupported revision states distinct from failed model revisions.
- Use Revision Plans to preserve protected parameters, components, features, outputs, dependencies, and unrelated modules during AI revisions.
- Prevent blocked and rejected candidates from becoming active through restore or accept actions.

### Downloads

- Download `.scad`.
- Download `.stl`.
- Download one STL per Design Plan printable output.
- Download `output-manifest.json`.
- Download deterministic ZIP exports containing source, Design Specification, Design Plan, output manifest, assembly notes, and STL artifacts.
- Include configuration metadata and parameter override manifests in exports for configuration-generated revisions.
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
- Component-targeted AI revisions
- structural parameter redesign without structured revision planning
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
