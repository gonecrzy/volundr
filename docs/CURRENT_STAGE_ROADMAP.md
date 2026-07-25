# Volundr Current Stage Roadmap

This document records the implementation sequence, current stage status, milestone goals, and exit criteria. Codex should update it whenever a milestone changes state.

## Stage 0 — Foundation Documents

Status: Complete

- Product direction
- MVP scope
- Architecture
- Model-generation contract
- CAD execution security
- Data model
- Codex kickoff prompt

## Stage 1 — Secure CAD Runner

Status: Complete

Goals:

- FastAPI skeleton
- SQLite setup
- OpenSCAD CLI wrapper
- temporary job directories
- compile timeout
- structured compile result
- STL generation
- trimesh metadata
- backend tests
- Docker Compose development environment using `volundr-web`, `volundr-api`, and `volundr-cad-worker`

Exit criteria:

- valid SCAD produces an STL
- invalid SCAD returns structured diagnostics
- timeout behavior is tested
- generated output metadata is stored
- no AI integration is required

## Stage 2 — Browser CAD Workspace

Status: Complete

Implemented:

- manual project creation API
- manual OpenSCAD revision compile API
- persisted source, STL, compile log, and metadata files
- browser workspace with OpenSCAD editor, compile action, revision list, STL preview, metadata, and STL download
- SCAD download
- compile diagnostics display
- active revision restore for successful manual revisions

Goals:

- React/Vite application
- project list
- Monaco editor
- compile action
- Three.js STL viewer
- model metadata panel
- SCAD/STL download

Exit criteria:

- user can manually author or paste OpenSCAD
- user can compile it
- user can inspect and download the result

## Stage 3 — Gemini CLI Generation

Status: Complete

Current status:

- provider abstraction added
- Gemini CLI subprocess adapter added
- SCAD source extraction added
- initial generation endpoint added
- browser generation prompt added
- live generation works with API-key based Gemini CLI authentication
- failed extraction and compile attempts are preserved as failed revisions
- compile failures trigger one bounded AI repair attempt

Goals:

- Gemini CLI authentication documentation
- provider abstraction
- generation prompt
- SCAD extraction
- initial model generation
- error display
- one bounded repair attempt

Exit criteria:

- plain-English prompt creates a compilable model
- raw AI output and extracted source are preserved
- failures are visible and recoverable

## Stage 4 — Projects and Revision History

Status: Complete

Current status:

- immutable revision records are persisted
- parent revision IDs are stored for manual, AI, and repair revisions
- active revision is updated only by successful compiles or restore
- successful prior revisions can be restored
- failed AI attempts remain visible and are not accepted
- projects can be renamed and archived
- project messages are persisted and shown in the workspace

Goals:

- immutable revisions
- parent-child history
- active revision
- restore workflow
- accepted versus failed attempts
- project messages

Exit criteria:

- every successful generation is recoverable
- no working model is overwritten

## Stage 5 — Conversational Revisions

Status: Complete

Current status:

- generation uses the active revision source as current-source context
- follow-up AI revisions are labeled `ai_revision`
- failed follow-up generations use the same preservation and bounded repair path as initial generations
- selected child revisions show a unified source diff against their parent

Goals:

- revision prompt built from original intent, current source, and new instruction
- minimal-edit prompting
- revision diff
- compile and repair
- restore after bad revision

Exit criteria:

- common dimensional and feature changes preserve unrelated geometry

## Stage 6 — Parameter Controls

Status: Not started

Goals:

- parse marked user parameters
- display numeric and boolean controls
- recompile without AI
- validate parameter edits

Exit criteria:

- critical dimensions can be changed without spending an AI generation request

## Stage 7 — Printability Assistance

Status: Future

Possible goals:

- model orientation suggestions
- basic wall-thickness warnings
- overhang heuristics
- slicer CLI integration
- filament and print-time estimates

## Stage 8 — Advanced Interaction

Status: Future

Possible goals:

- screenshot or image feedback
- annotations
- SVG import
- reusable feature library
- CadQuery/build123d provider
- STEP export
